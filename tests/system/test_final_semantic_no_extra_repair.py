"""No-extra-image-repair final semantic decision remains an actual FAIL."""
from __future__ import annotations
import hashlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SYSTEM = Path(__file__).resolve().parents[2] / "episodes/_system"
if str(SYSTEM) not in sys.path:
    sys.path.insert(0, str(SYSTEM))

import frame_semantic_review as review


def test_no_extra_repair_keeps_user_held_passes_and_escalates_failed_ready(tmp_path):
    statuses = {"01": "WEAK_PASS", "09": "NEEDS_USER", "13": "ORIGINAL_READY"}
    decisions = {"01": "pass", "09": "pass", "13": "fail"}
    reviewed = []
    for key in statuses:
        asset = tmp_path / f"{key}.png"
        asset.write_bytes(f"reviewed candidate {key}".encode())
        reviewed.append({
            "frame": key, "path": asset, "path_rel": asset.name,
            "sha256": hashlib.sha256(asset.read_bytes()).hexdigest(),
        })
    rows = [{
        "frame": key, "decision": decision,
        "checks": {}, "issue_codes": (["KEY_PROP_DRIFT"] if decision == "fail" else []),
        "notes": "model review evidence",
    } for key, decision in decisions.items()]
    ledger = {"policy": {"max_content_repairs_per_frame": 1},
              "frames": {k: {"status": v} for k, v in statuses.items()}}
    calls = []
    def cmd_review(args):
        calls.append((str(args.frame).zfill(2), args.decision))
        assert args.decision == "needs_user"
        statuses[str(args.frame).zfill(2)] = "NEEDS_USER"

    def blocked(*args, **kwargs):
        raise AssertionError("no-extra-repair must never promote, lock or authorize repair")

    with patch.object(review, "validate_candidate_gate_rows", return_value=[]), \
         patch.object(review, "episode_contract_version", return_value="test"), \
         patch.object(review, "directing_v3_required", return_value=False), \
         patch.object(review.production_ledger, "load_authority", return_value=ledger), \
         patch.object(review.production_ledger, "content_repair_limit", return_value=1), \
         patch.object(review.production_ledger, "cmd_review", side_effect=cmd_review), \
         patch.object(review.production_ledger, "cmd_authorize_repair", side_effect=blocked), \
         patch.object(review.production_ledger, "cmd_promote", side_effect=blocked), \
         patch.object(review.production_ledger, "cmd_lock", side_effect=blocked), \
         patch.object(review.production_ledger, "mark_review_needs_user", side_effect=blocked), \
         patch.object(review, "review_source_bindings", return_value={}), \
         patch.object(review, "_ledger_frame", side_effect=lambda ep, k: {"status": statuses[k]}), \
         patch.object(review.phase4_contract, "required", return_value=False), \
         patch.object(review.runtime_provenance, "validate_critic_provenance", return_value=[]), \
         patch.object(review, "write_json") as written:
        rc = review._apply_candidate_gate(
            tmp_path, data={"frames": rows, "issue_codes": ["KEY_PROP_DRIFT"],
                            "summary": {"passed": False}},
            reviewed=reviewed, contexts={},
            provenance={"review_source_bindings": {}}, attempt=1,
            no_auto_repair=True)
    assert rc == 2
    assert calls == [("13", "needs_user")]
    assert statuses == {"01": "WEAK_PASS", "09": "NEEDS_USER", "13": "NEEDS_USER"}
    assert written.called
