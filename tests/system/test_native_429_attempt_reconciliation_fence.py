"""Native Codex 429 text is not evidence that dispatched image Attempt failed."""
import sys
from pathlib import Path
from unittest.mock import patch
import pytest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"episodes/_system"))
import image_scheduler as scheduler
ITEM={"id":"pilot-02","frame":2,"scope":"repair","kind":"repair"}
KEY="ga1-fixed-generation-key"

def evidence(*,status="OUTCOME_UNKNOWN",generation_key=KEY,life_key=KEY,
             life_id="pilot-02",life_attempt=2,consumed=2,active=None):
    return ({"attempts_consumed":consumed,"active_attempt_index":active,"remaining_attempts":0},
            {"status":status,"generation_key":generation_key,"attempt_index":2},
            {"item_id":life_id,"generation_key":life_key,"attempt":life_attempt})

def evaluate(case,code="RATE_LIMIT_429"):
    state,attempt,life=case
    with (patch.object(scheduler.logical_asset_identity,"frame_asset_key",return_value="frame-02"),
          patch.object(scheduler.generation_attempt_authority,"load_asset_state",return_value=state),
          patch.object(scheduler.generation_attempt_authority,"load_attempt",return_value=attempt),
          patch.object(scheduler.production_recovery,"lifecycle_path",return_value=Path("dummy")),
          patch.object(scheduler.production_recovery,"_read",return_value=life)):
        return scheduler._fence_native_rate_limit_unknown(Path("."),ITEM,code)

def test_real_429_message_quarantines_verified_unknown():
    assert evaluate(evidence())=="IMAGE_ATTEMPT_OUTCOME_UNKNOWN"
    assert "IMAGE_ATTEMPT_OUTCOME_UNKNOWN" in scheduler.NON_REGENERATING_FAILURE_CODES

@pytest.mark.parametrize("override",[
    {"generation_key":"different"},{"life_key":"different"},{"life_id":"other"},
    {"life_attempt":1},{"consumed":1},{"active":2}])
def test_ambiguous_attempt_identity_fails_closed(override):
    assert evaluate(evidence(**override))=="IMAGE_ATTEMPT_AUTHORITY_UNVERIFIED"

@pytest.mark.parametrize("code",["LOGIN_AUTH_IMAGE_TOOL_CAPABILITY_UNKNOWN","TIMEOUT",
                                  "IMAGE_BACKEND_NO_OUTPUT","NETWORK_ERROR"])
def test_unrelated_codes_preserved_no_db_lookup(code):
    with patch.object(scheduler.generation_attempt_authority,"load_asset_state") as db:
        assert scheduler._fence_native_rate_limit_unknown(Path("."),ITEM,code)==code
        db.assert_not_called()

def test_postdispatch_failed_receipt_does_not_invent_unknown():
    assert evaluate(evidence(status="FAILED_AFTER_DISPATCH"))=="RATE_LIMIT_429"

def test_mysql_unavailable_denies_optimistic_rate_limit_retry():
    with patch.object(scheduler.generation_attempt_authority,"load_asset_state",side_effect=RuntimeError("down")):
        assert scheduler._fence_native_rate_limit_unknown(Path("."),ITEM,"RATE_LIMIT_429")=="IMAGE_ATTEMPT_AUTHORITY_UNVERIFIED"

def test_both_scheduler_failure_paths_consult_authority():
    src=(ROOT/"episodes/_system/image_scheduler.py").read_text(encoding="utf-8")
    assert src.count("code=_fence_native_rate_limit_unknown(ep,item,code)")>=2

def test_unknown_or_unverified_code_cannot_regenerate():
    for code in ("IMAGE_ATTEMPT_OUTCOME_UNKNOWN","IMAGE_ATTEMPT_AUTHORITY_UNVERIFIED"):
        assert scheduler._terminal_technical_status(Path("."),ITEM,code)=="blocked"
        assert code not in scheduler.RETRYABLE_TECH_CODES

def test_postdispatch_unknown_requires_matching_lifecycle_not_plain_429():
    src=(ROOT/"episodes/_system/raw_candidate_budget.py").read_text(encoding="utf-8")
    assert 'authority.mark_outcome_unknown(ep, lease' in src
    assert 'lease.get("_phase") == "DISPATCH_COMMITTED"' in src

def test_legacy_failed_queue_does_not_unlock_attempt_retries():
    assert evaluate(evidence(status="SUCCEEDED"))=="RATE_LIMIT_429"
