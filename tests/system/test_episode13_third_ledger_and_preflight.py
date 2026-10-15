"""Successful third image may be committed only for the proven network compensation."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT / "episodes/_system"))
sys.path.insert(0,str(ROOT / "scripts"))
import production_ledger  # bootstrap facade first to avoid circular import
import production_ledger_run as ledger
import generation_attempt_authority as auth
import storyos_attempt_readonly_preflight as readonly


def test_exact_successful_third_attempt_only(monkeypatch):
    episode = ROOT / "episodes/00_独立篇/13_失物归还的那扇门"
    records = {
        1: {"status":"FAILED_AFTER_DISPATCH",
            "failure_class":"IMAGE_TOOL_NETWORK_ERROR_DURABLE_RECEIPT"},
        2: {"status":"SUCCEEDED", "provider":"codex_subscription"},
        3: {"status":"SUCCEEDED", "attempt_index":3,
            "generation_key":"generation3", "provider":"codex_subscription",
            "payload_model":"gpt-image-2.5-flare", "payload_quality":"high",
            "result_ref":"real_candidate.png"},
    }
    monkeypatch.setattr(auth,"load_attempt",lambda _ep,_key,index: records.get(index))
    monkeypatch.setattr(auth,"load_asset_state",lambda _ep,_key: {
        "attempts_consumed":3,"active_attempt_index":None})
    candidate = {"kind":"baseline_candidate"}
    assert ledger._verified_episode13_third_image_success(episode,"01",candidate,"generation3")
    assert not ledger._verified_episode13_third_image_success(episode,"02",candidate,"generation3")
    assert not ledger._verified_episode13_third_image_success(episode,"01",
        {"kind":"ordinary_repair"},"generation3")
    assert not ledger._verified_episode13_third_image_success(episode,"01",candidate,"other-key")
    records[3]["status"]="OUTCOME_UNKNOWN"
    assert not ledger._verified_episode13_third_image_success(episode,"01",candidate,"generation3")


def test_preflight_compensation_is_scoped_not_global():
    episode="00_独立篇/13_失物归还的那扇门"
    exact=episode+"/frame-01"
    other=episode+"/frame-02"
    correct_attempts=[{"LOGICAL_ASSET_KEY":exact,"ATTEMPT_INDEX":x,"STATUS":"SUCCEEDED"}
                      for x in (1,2,3)]
    correct_states=[{"LOGICAL_ASSET_KEY":exact,"ATTEMPTS_CONSUMED":3,
                     "ACTIVE_ATTEMPT_INDEX":None}]
    assert readonly._history_integrity_issues(episode,correct_attempts,correct_states)==[]
    mismatched=[{"LOGICAL_ASSET_KEY":other,"ATTEMPT_INDEX":3,"STATUS":"SUCCEEDED"}]
    issues=readonly._history_integrity_issues(episode,mismatched,[
        {"LOGICAL_ASSET_KEY":other,"ATTEMPTS_CONSUMED":3}])
    codes={x["code"] for x in issues}
    assert "ATTEMPT_INDEX_OUT_OF_RANGE" in codes
    assert "ATTEMPT_BUDGET_OUT_OF_RANGE" in codes
