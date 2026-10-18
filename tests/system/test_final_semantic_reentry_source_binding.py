"""A recovered Final Semantic review must bind the same frozen sources as its pending request."""
from __future__ import annotations
import json
import sys
from pathlib import Path
from unittest.mock import patch
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "episodes" / "_system"))
import frame_semantic_review as fsr


@pytest.mark.parametrize("sharded", [False, True])
def test_completed_review_reentry_carries_verified_frozen_bindings(tmp_path, sharded):
    ep = tmp_path
    (ep / "meta").mkdir()
    frozen = {"schema_version": 1, "frames": {"01": {"sha256": "a" * 64}}}
    contexts = {"story_sha256": "s" * 64}
    reviewed = [{"frame": "01", "path_rel": "candidate/01.png",
                 "path": ep / "candidate/01.png", "sha256": "a" * 64}]
    pending = {
        "schema_version": 1, "attempt": 1, "review_scope": "FULL_FRAME_SET",
        "assets": [{"frame": "01", "path": "candidate/01.png", "sha256": "a" * 64}],
        "contexts": contexts,
    }
    fsr.pending_request_path(ep, 1).write_text(json.dumps(pending), encoding="utf-8")
    candidate = ep / fsr.CANDIDATE_REL
    candidate.write_text(json.dumps({"frames": [{"frame": "01", "decision": "fail",
                                                  "issue_codes": ["STORY_BEAT_NOT_VISIBLE"]}],
                                     "summary": {"passed": False}}), encoding="utf-8")
    (ep / "meta/frame-semantic-critic-attempt-1.jsonl").write_text(
        "recorded-log", encoding="utf-8")
    if sharded:
        logs = []
        for idx in (1, 2):
            log = ep / "meta" / f"shard-{idx}.jsonl"
            log.write_text("durable native Codex receipt", encoding="utf-8")
            logs.append({"index": idx, "log_path": str(log)})
        (ep / "meta/frame-semantic-sharded-attempt-1.json").write_text(
            json.dumps({
                "schema_version": 2, "attempt": 1, "target_coverage": ["01"],
                "candidate_sha256": fsr.sha256_file(candidate),
                "source_bindings_sha256": fsr.sha256_json(frozen),
                "shard_count": 2, "shards": logs,
                "global_closure": {"status": "SKIPPED_LOCAL_FAILURE"}
            }), encoding="utf-8")
    captured = []

    def apply(_ep, *, data, reviewed, provenance, **_kwargs):
        captured.append(provenance.get("review_source_bindings"))
        assert provenance.get("review_source_bindings") == frozen
        return 2  # model FAIL can be routed to the bounded Ledger repair lane.

    with patch.object(fsr, "ROOT", ep), \
         patch.object(fsr, "reviewable_frame_records", return_value=reviewed), \
         patch.object(fsr, "context_hashes", return_value=contexts), \
         patch.object(fsr, "reviewable_phase4_binding_errors", return_value=[]), \
         patch.object(fsr, "review_source_bindings", return_value=frozen), \
         patch.object(fsr, "repo_path", side_effect=lambda raw, _label: Path(raw)), \
         patch.object(fsr, "_apply_candidate_gate", side_effect=apply):
        rc = fsr.apply_pending_candidate(ep, attempt=1)
    assert rc == 2
    assert captured == [frozen]