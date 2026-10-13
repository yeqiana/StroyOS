"""True recorded StoryOS production evidence through the existing read-only API."""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.storyos_local_readonly_api import LocalEpisodeFileStatuses
from platform.operations.local_episode_monitoring import read_recorded_production


class RecordedFileMonitoringTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.meta = Path(self.temp.name) / "episodes" / "系列" / "测试作品" / "meta"
        self.meta.mkdir(parents=True)
        (self.meta / "episode-state.json").write_text(
            json.dumps({"episode_id": "01", "title": "测试", "series": "系列",
                        "current_state": "VISUAL_CALIBRATED"}, ensure_ascii=False),
            encoding="utf-8",
        )
        self.service = LocalEpisodeFileStatuses(self.meta.parents[3])

    def put(self, name, payload):
        (self.meta / name).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def detail(self):
        ref = self.service.list_episode_statuses()["items"][0]["episode_ref"]
        return self.service.get_episode_status(ref)

    def test_true_ledger_queue_and_checkpoint_without_fake_liveness(self):
        self.put("production-ledger.json", {"frames": {
            "01": {"status": "LOCKED", "approved_asset": {"path": "SECRET-should-never-return"},
                   "attempts": [{"token": "SECRET-LEAK"}]},
            "02": {"status": "NEEDS_USER", "attempts": [{}, {}]},
        }, "updated_at": "2026-10-12T11:00:00+08:00"})
        self.put("production-queue.json", {
            "items": [
                {"frame": 1, "status": "superseded", "attempts": 1},
                {"frame": 1, "status": "generated", "attempts": 2},
                {"frame": 2, "status": "failed", "attempts": 3,
                 "last_error": {"code": "MODEL_TIMEOUT", "message": "API_SECRET=LEAK"}},
            ]})
        self.put("runtime-checkpoint.json", {"step_runs": [
            {"step": "STORY", "status": "PASS", "attempt": 1,
             "note": "PRIVATE-PROMPT-SHOULD-NOT-APPEAR"},
        ]})
        self.put("runtime-runner-state.json", {
            "status": "RUNNING", "heartbeat": "2026-10-12T11:00:00+08:00",
            "credential": "SECRET-NEVER-RETURN"})
        self.put("frame-semantic-review.json", {"summary": {"passed": False}})
        detail = self.detail()
        self.assertEqual(detail["execution_status"], "UNKNOWN")
        self.assertEqual(detail["heartbeat"]["health"], "unknown")
        self.assertEqual(detail["monitoring_scope"], "RECORDED_FILES_ONLY")
        self.assertFalse(detail["can_retry"])
        self.assertEqual(detail["image_progress"]["accepted_frames"], 1)
        self.assertEqual(detail["image_progress"]["expected_frames"], 2)
        self.assertEqual(detail["queue_summary"]["recorded_items"], 3)
        self.assertEqual(detail["queue_summary"]["status_counts"]["superseded"], 1)
        self.assertEqual(len(detail["frame_records"]), 2)
        self.assertEqual(detail["frame_records"][0]["queue_status"], "generated")
        self.assertEqual(detail["frame_records"][1]["last_error_code"], "MODEL_TIMEOUT")
        self.assertEqual(detail["frame_records"][1]["recorded_attempt_entries"], 2)
        self.assertFalse(detail["runner_record"]["verified_live"])
        self.assertEqual(detail["runner_record"]["recorded_status"], "RUNNING")
        self.assertFalse(detail["review_records"]["frame_review"]["passed"])
        serialized = json.dumps(detail, ensure_ascii=False)
        for secret in ("SECRET", "PRIVATE", "API_SECRET", "credential", "prompt"):
            self.assertNotIn(secret, serialized)

    def test_absent_or_partial_evidence_never_creates_false_progress(self):
        detail = self.detail()
        self.assertEqual(detail["frame_records"], [])
        self.assertIsNone(detail["image_progress"])
        self.assertIsNone(detail["runner_record"])
        self.assertEqual(detail["recorded_sources"], {})
        self.assertEqual(detail["execution_status"], "UNKNOWN")
        self.put("production-queue.json", {"items": [{"frame": 1, "status": "queued"}]})
        updated = self.detail()
        self.assertEqual(len(updated["frame_records"]), 1)
        self.assertIsNone(updated["image_progress"])

    def test_corrupted_file_fails_closed_and_never_returns_raw_content(self):
        (self.meta / "production-queue.json").write_text('{"API_KEY":"SECRET', encoding="utf-8")
        detail = self.detail()
        self.assertEqual(detail["queue_summary"], None)
        self.assertIn("production-queue.json:UNREADABLE", detail["source_errors"])
        self.assertNotIn("SECRET", json.dumps(detail))

    def test_injected_frame_numbers_and_free_text_cannot_be_exposed(self):
        self.put("production-ledger.json", {"frames": {
            "01": {"status": "PASSED", "attempts": []},
            "../../secret": {"status": "PASSED", "approved_asset": {"path": "SECRET"}},
            "21": {"status": "PASSED", "approved_asset": {"path": "SECRET"}},
        }})
        self.put("production-queue.json", {"items": [
            {"frame": 1, "status": "queued", "last_error":
                {"message": "C:/sensitive/codex-token-SECRET", "code": "bad path SECRET"}},
        ]})
        detail = self.detail()
        self.assertEqual(len(detail["frame_records"]), 1)
        self.assertIsNone(detail["frame_records"][0]["last_error_code"])
        self.assertNotIn("SECRET", json.dumps(detail))

    def test_no_write_of_existing_files(self):
        self.put("production-queue.json", {"items": [{"frame": 1, "status": "failed"}]})
        before = (self.meta / "production-queue.json").read_bytes()
        _ = self.detail()
        self.assertEqual((self.meta / "production-queue.json").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
