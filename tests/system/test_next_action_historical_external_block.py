"""Historical provider refusals must not re-block real, reviewed repair pixels."""
from pathlib import Path
import sys

SYSTEM = Path(__file__).resolve().parents[2] / "episodes/_system"
if str(SYSTEM) not in sys.path:
    sys.path.insert(0, str(SYSTEM))
import next_action


def test_superseded_original_is_retained_but_not_live_block(monkeypatch, tmp_path):
    pixel = "episodes/test/media/candidates/scheduled/48-a2.png"
    queue = {"items": [
        {"frame": 48, "kind": "original", "status": "external_blocked"},
        {"frame": 48, "kind": "repair", "status": "generated",
         "output_path": pixel},
    ]}
    monkeypatch.setattr(next_action.scheduler_core, "load_queue", lambda ep: queue)
    monkeypatch.setattr(next_action.production_ledger, "load_authority",
                        lambda ep, **kw: {"frames": {
                            "48": {"status": "NEEDS_USER", "current_candidate": {
                                "path": pixel, "sha256": "a"*64}}
                        }})
    summary = next_action.queue_summary(tmp_path)
    assert summary["counts"]["external_blocked"] == 0
    assert summary["external_blocked_items"] == []
    assert queue["items"][0]["status"] == "external_blocked"


def test_repair_content_failed_but_pixels_committed_is_not_provider_block(monkeypatch, tmp_path):
    pixel = "episodes/test/media/candidates/scheduled/48-a2.png"
    queue = {"items": [
        {"frame": 48, "kind": "original", "status": "external_blocked"},
        {"frame": 48, "kind": "repair", "status": "scout_repair",
         "output_path": pixel, "vision_batch_review": {"decision": "REPAIR_NOW"}},
    ]}
    monkeypatch.setattr(next_action.scheduler_core, "load_queue", lambda ep: queue)
    monkeypatch.setattr(next_action.production_ledger, "load_authority",
                        lambda ep, **kw: {"frames": {
                            "48": {"status": "NEEDS_USER", "current_candidate": {
                                "path": pixel, "sha256": "d"*64}}
                        }})
    result = next_action.queue_summary(tmp_path)
    assert result["counts"]["external_blocked"] == 0
    assert queue["items"][0]["status"] == "external_blocked"


def test_unverified_or_wrong_candidate_cannot_hide_old_block(monkeypatch, tmp_path):
    pixel = "episodes/test/media/candidates/scheduled/48-a2.png"
    queue = {"items": [
        {"frame": 48, "kind": "original", "status": "external_blocked"},
        {"frame": 48, "kind": "repair", "status": "generated",
         "output_path": pixel},
    ]}
    monkeypatch.setattr(next_action.scheduler_core, "load_queue", lambda ep: queue)
    for path, sha in ((pixel, None), ("wrong.png", "b"*64), ("", "b"*64)):
        monkeypatch.setattr(next_action.production_ledger, "load_authority",
                            lambda ep, path=path, sha=sha, **kw: {
                                "frames": {"48": {"status": "NEEDS_USER",
                                                  "current_candidate": {"path": path, "sha256": sha}}}})
        result = next_action.queue_summary(tmp_path)
        assert result["counts"]["external_blocked"] == 1
        assert result["external_blocked_items"] == [queue["items"][0]]


def test_newer_block_still_blocks_when_old_pixels_exist(monkeypatch, tmp_path):
    pixel = "episodes/test/media/candidates/scheduled/48-a2.png"
    queue = {"items": [
        {"frame": 48, "kind": "repair", "status": "generated", "output_path": pixel},
        {"frame": 48, "kind": "repair", "status": "external_blocked"},
    ]}
    monkeypatch.setattr(next_action.scheduler_core, "load_queue", lambda ep: queue)
    monkeypatch.setattr(next_action.production_ledger, "load_authority",
                        lambda ep, **kw: {"frames": {"48": {
                            "current_candidate": {"path": pixel, "sha256": "c"*64}}}})
    result = next_action.queue_summary(tmp_path)
    assert result["counts"]["external_blocked"] == 1
