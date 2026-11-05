"""Resume bounded final semantic shards without treating a cached critic as a PASS."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SYSTEM = Path(__file__).resolve().parents[2] / "episodes/_system"
if str(SYSTEM) not in sys.path:
    sys.path.insert(0, str(SYSTEM))

import frame_semantic_review as review


@pytest.fixture
def cached_shard(tmp_path, monkeypatch):
    ep = tmp_path / "episode"
    (ep / "meta").mkdir(parents=True)
    frame = {"frame": "09", "path_rel": "media/frame09.png", "sha256": "a" * 64}
    shard = {"index": 1, "target_frames": ["09"], "context_frames": [],
             "selected": [frame]}
    pending = {"attempt": 1, "review_scope": "FULL_FRAME_SET",
               "assets": [{"frame": frame["frame"], "path": frame["path_rel"],
                           "sha256": frame["sha256"]}], "contexts": {"story": "bound"}}
    request = review.pending_request_path(ep, 1)
    request.write_text(json.dumps(pending), encoding="utf-8")
    candidate = ep / "meta/.frame-semantic-shard-1-1.candidate.json"
    candidate.write_text(json.dumps({
        "frames": [{"frame": "09", "decision": "fail"}],
        "issue_codes": [],
        "summary": {"passed": False},
    }), encoding="utf-8")
    log = ep / "meta/frame-semantic-critic-attempt-1-shard-1.jsonl"
    log.write_text("", encoding="utf-8")

    monkeypatch.setattr(review, "reviewable_frame_records",
                        lambda *args, **kwargs: [frame])
    monkeypatch.setattr(review, "context_hashes", lambda ep: {"story": "bound"})
    monkeypatch.setattr(review, "reviewable_phase4_binding_errors",
                        lambda ep, frames: [])
    monkeypatch.setattr(review, "_full_review_shards", lambda frames: [
        {"index": 1, "target_frames": ["09"], "context_frames": [],
         "selected": [frame]}
    ])
    monkeypatch.setattr(review, "episode_contract_version", lambda ep: "test")
    monkeypatch.setattr(review, "directing_v3_required", lambda ep: False)
    monkeypatch.setattr(review, "validate_candidate_gate_rows",
                        lambda *args, **kwargs: [])
    monkeypatch.setattr(review, "repo_rel", lambda path: str(path))
    return ep, frame, shard, candidate, log


def test_resume_reuses_bound_failed_shard_without_second_codex_call(cached_shard, monkeypatch):
    ep, _, shard, candidate, _ = cached_shard

    def do_not_dispatch(*args, **kwargs):
        pytest.fail("cached review must not call Codex a second time")

    monkeypatch.setattr(review.critic_runner, "launch", do_not_dispatch)
    result = review._launch_full_review_shard(
        ep, shard, attempt=1, codex=Path("codex"), timeout=1)
    assert result["data"]["summary"]["passed"] is False
    assert result["data"]["frames"][0]["decision"] == "fail"
    assert result["candidate_sha256"] == review.sha256_file(candidate)
    assert candidate.is_file()


def test_resume_rejects_changed_asset_hash(cached_shard):
    ep, frame, shard, _, _ = cached_shard
    frame["sha256"] = "b" * 64
    assert review._validated_cached_full_review_shard(ep, shard, attempt=1) is None


def test_resume_rejects_changed_context(cached_shard, monkeypatch):
    ep, _, shard, _, _ = cached_shard
    monkeypatch.setattr(review, "context_hashes", lambda ep: {"story": "drift"})
    assert review._validated_cached_full_review_shard(ep, shard, attempt=1) is None


def test_resume_rejects_missing_log(cached_shard):
    ep, _, shard, _, log = cached_shard
    log.unlink()
    assert review._validated_cached_full_review_shard(ep, shard, attempt=1) is None


def test_resume_rejects_mismatched_critic_summary(cached_shard):
    ep, _, shard, candidate, _ = cached_shard
    result = json.loads(candidate.read_text(encoding="utf-8"))
    result["summary"]["passed"] = True
    candidate.write_text(json.dumps(result), encoding="utf-8")
    assert review._validated_cached_full_review_shard(ep, shard, attempt=1) is None


def test_resume_rejects_changed_shard_selection(cached_shard):
    ep, _, shard, _, _ = cached_shard
    shard["selected"] = [{"frame": "10"}]
    assert review._validated_cached_full_review_shard(ep, shard, attempt=1) is None
