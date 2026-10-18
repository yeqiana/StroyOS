"""Real Final Semantic FAIL must be a bounded review decision, not a Driver crash."""
from __future__ import annotations
import hashlib
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "episodes" / "_system"))
import frame_semantic_review as fsr


def _sample(tmp_path, *, valid=True, summary=False):
    png = tmp_path / "frame-01.png"
    png.write_bytes(b"real-frame-bytes")
    sha = hashlib.sha256(png.read_bytes()).hexdigest()
    reviewed = [{"frame": "01", "path": png, "path_rel": "frame-01.png", "sha256": sha}]
    data = {"frames": [{"frame": "01", "decision": "fail",
                         "checks": {"story_beat_fidelity": False},
                         "issue_codes": ["STORY_BEAT_NOT_VISIBLE"]}],
            "issue_codes": ["STORY_BEAT_NOT_VISIBLE"],
            "summary": {"passed": summary}}
    if not valid:
        data["frames"][0]["issue_codes"] = ["INVENTED_ISSUE"]
    return reviewed, data


def _run(tmp_path, data, reviewed, provenance, *, initial_status="ORIGINAL_READY"):
    ledger = {"frames": {"01": {"status": initial_status, "content_repairs_used": 0}},
              "policy": {"max_content_repairs_per_frame": 1}}
    calls = []
    def review(args):
        calls.append(args.decision)
    def escalate(_ep, frame, *, reason):
        calls.append("needs_user")
        return {"frame": frame, "status": "NEEDS_USER"}
    def ledger_frame(ep, frame):
        return {"status": "NEEDS_USER"}  # no additional paid attempt permitted
    with patch.object(fsr, "checks_for_version", return_value=["story_beat_fidelity"]), \
         patch.object(fsr, "episode_contract_version", return_value="test"), \
         patch.object(fsr, "directing_v3_required", return_value=False), \
         patch.object(fsr.production_ledger, "load_authority", return_value=ledger), \
         patch.object(fsr.production_ledger, "content_repair_limit", return_value=1), \
         patch.object(fsr.production_ledger, "cmd_review", side_effect=review), \
         patch.object(fsr.production_ledger, "mark_review_needs_user", side_effect=escalate), \
         patch.object(fsr, "_ledger_frame", side_effect=ledger_frame), \
         patch.object(fsr, "review_source_bindings", return_value={"source": "bound"}), \
         patch.object(fsr.phase4_contract, "required", return_value=False), \
         patch.object(fsr, "write_json") as saved, \
         patch.object(fsr, "prepare_review_commit", side_effect=AssertionError("PASS-only authority must not run on FAIL")):
        result = fsr._apply_candidate_gate(
            tmp_path, data=data, reviewed=reviewed, contexts={},
            provenance=provenance, attempt=1)
        return result, calls, saved


def test_real_failure_returns_repair_code_without_pass_only_commit(tmp_path):
    frames, result = _sample(tmp_path)
    provenance = fsr.runtime_provenance.build_vision_critic_provenance(attempt=1)
    provenance["review_source_bindings"] = {"source": "bound"}
    rc, calls, saved = _run(tmp_path, result, frames, provenance)
    assert rc == 2
    assert calls == ["repair"]
    assert saved.called


def test_false_summary_pass_cannot_mutate_ledger(tmp_path):
    frames, result = _sample(tmp_path, summary=True)
    provenance = fsr.runtime_provenance.build_vision_critic_provenance(attempt=1)
    provenance["review_source_bindings"] = {"source": "bound"}
    rc, calls, saved = _run(tmp_path, result, frames, provenance)
    assert rc == 3
    assert not calls and not saved.called


def test_bad_provenance_cannot_mutate_ledger(tmp_path):
    frames, result = _sample(tmp_path)
    rc, calls, saved = _run(tmp_path, result, frames, {"review_source_bindings": {"source": "bound"}})
    assert rc == 3
    assert not calls and not saved.called


def test_unknown_critic_issue_cannot_mutate_ledger(tmp_path):
    frames, result = _sample(tmp_path, valid=False)
    provenance = fsr.runtime_provenance.build_vision_critic_provenance(attempt=1)
    provenance["review_source_bindings"] = {"source": "bound"}
    rc, calls, saved = _run(tmp_path, result, frames, provenance)
    assert rc == 3
    assert not calls and not saved.called

def test_weak_pass_frame_final_failure_becomes_needs_user_without_paid_retry(tmp_path):
    frames, result = _sample(tmp_path)
    provenance = fsr.runtime_provenance.build_vision_critic_provenance(attempt=1)
    provenance["review_source_bindings"] = {"source": "bound"}
    rc, calls, saved = _run(tmp_path, result, frames, provenance, initial_status="WEAK_PASS")
    assert rc == 2
    assert calls == ["needs_user"]
    assert saved.called