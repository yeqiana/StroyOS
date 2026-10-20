"""No-real-database regression for the live monitoring read-only boundary."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from platform.operations.local_mysql_catalog_readonly import SQL_CATALOG, observe_mysql_catalog
from scripts.storyos_local_readonly_api import LocalEpisodeFileStatuses


ENV = {"STORYOS_LOCAL_MONITOR_MYSQL": "1", "STORYOS_MONITOR_MYSQL_RO_USER": "storyos_observer",
       "STORYOS_MONITOR_MYSQL_RO_PASSWORD": "test-only", "STORYOS_MONITOR_MYSQL_RO_DB": "STORY_OS_RUNTIME"}
NAMESPACE = "00_独立篇/14_深渊疗愈所_第一集_净土生命还原"


class FakeDb:
    def __init__(self, grants=None):
        self.calls = []
        self.grants = grants or [{"Grants": "GRANT SELECT ON `STORY_OS_RUNTIME`.* TO 'storyos_observer'@'127.0.0.1'"}]
        self.rolled_back = False
        self.closed = False

    def cursor(self): return self
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def execute(self, sql, params=None): self.calls.append(sql)
    def fetchall(self):
        if self.calls[-1] == "SHOW GRANTS": return self.grants
        if self.calls[-1] == SQL_CATALOG:
            return [{"EPISODE_NAMESPACE": NAMESPACE, "BUSINESS_EPISODE_ID": "00-14",
                     "TITLE": "深渊疗愈所", "CURRENT_STATE": "IDEA_LOCKED",
                     "STATE_UPDATE_TIME": datetime(2026, 10, 20, 9, 0), "UPDATE_TIME": None,
                     "MYSQL_PRIVATE": "must_not_emit"}]
        raise AssertionError("unexpected SQL")
    def rollback(self): self.rolled_back = True
    def close(self): self.closed = True


class LiveEpisodeMonitoringTests(unittest.TestCase):
    def test_catalog_select_only_and_no_private_columns(self):
        db = FakeDb()
        result = observe_mysql_catalog(connect=lambda **kw: db, config=ENV)
        self.assertTrue(result["available"])
        self.assertEqual(result["items"][0]["production_stage"], "IDEA_LOCKED")
        self.assertNotIn("MYSQL_PRIVATE", json.dumps(result))
        self.assertTrue(db.rolled_back and db.closed)
        self.assertEqual(db.calls, ["SHOW GRANTS", "START TRANSACTION READ ONLY", SQL_CATALOG])
        for forbidden in ("INSERT ", "UPDATE ", "DELETE ", "CREATE ", "ALTER ", "DROP ", "FOR UPDATE"):
            self.assertFalse(any(forbidden in sql.upper() for sql in db.calls))

    def test_no_privilege_never_reads_catalog(self):
        db = FakeDb(grants=[{"Grants": "GRANT INSERT ON *.* TO 'observer'@'localhost'"}])
        result = observe_mysql_catalog(connect=lambda **kw: db, config=ENV)
        self.assertFalse(result["available"])
        self.assertEqual(db.calls, ["SHOW GRANTS"])

    def test_without_mysql_new_episode_has_unknown_stage_not_fake_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            directory = root / "episodes" / Path(NAMESPACE)
            (directory / "meta").mkdir(parents=True)
            (directory / "meta" / "release-manifest.json").write_text("{}", encoding="utf-8")
            service = LocalEpisodeFileStatuses(root)
            with patch("scripts.storyos_local_readonly_api.observe_mysql_catalog",
                       return_value={"available": False, "reason": "READ_ONLY_MYSQL_NOT_ENABLED"}):
                result = service.list_episode_statuses()
                self.assertEqual(result["total"], 1)
                item = result["items"][0]
                self.assertEqual(item["production_stage"], "UNKNOWN")
                self.assertEqual(item["state_source"], "local_episode_directory_unverified")
                self.assertNotIn("_namespace", item)
                detail = service.get_episode_status(item["episode_ref"])
                self.assertEqual(detail["execution_status"], "UNKNOWN")

    def test_mysql_authority_discovers_episode_without_json_and_reads_latest_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            directory = root / "episodes" / Path(NAMESPACE)
            (directory / "meta" / "runtime").mkdir(parents=True)
            (directory / "meta" / "release-manifest.json").write_text("{}", encoding="utf-8")
            (directory / "meta" / "runtime" / "trace-events.jsonl").write_text(
                json.dumps({"event_type": "WORKER_DISPATCH_COMMITTED",
                            "step": "CREATIVE_STORY", "timestamp": "2026-10-20T16:53:41+08:00"}) + "\n",
                encoding="utf-8")
            record = {"namespace": NAMESPACE, "title": "深渊疗愈所",
                      "business_episode_id": "00-14", "production_stage": "IDEA_LOCKED",
                      "updated_at": "2026-10-20T09:00:00+00:00"}
            with patch("scripts.storyos_local_readonly_api.observe_mysql_catalog",
                       return_value={"available": True, "reason": None,
                                     "items": [record], "truncated": False}):
                service = LocalEpisodeFileStatuses(root)
                result = service.list_episode_statuses()
                self.assertEqual(result["total"], 1)
                item = result["items"][0]
                self.assertEqual(item["state_source"], "mysql_episode_state_read_only")
                self.assertEqual(item["production_stage"], "IDEA_LOCKED")
                detail = service.get_episode_status(item["episode_ref"])
                self.assertEqual(detail["current_action"], "CREATIVE_STORY")
                self.assertEqual(detail["execution_status"], "DISPATCH_RECORDED")
                self.assertNotIn("_namespace", detail)
                self.assertIsNone(detail["image_attempted_frames_observed"])

    def test_terminal_run_envelope_keeps_preceding_blocked_node(self):
        from platform.operations.local_runtime_trace_readonly import latest_node
        with tempfile.TemporaryDirectory() as tmp:
            ep = Path(tmp) / "episode"
            runtime = ep / "meta" / "runtime"
            runtime.mkdir(parents=True)
            events = [
                {"event_type": "STEP_FAILED", "step": "CREATIVE_STORY",
                 "status": "BLOCKED", "failure_class": 4,
                 "timestamp": "2026-10-20T17:17:44+08:00"},
                {"event_type": "EPISODE_RUN_FINISHED", "step": None,
                 "status": "FAILED", "timestamp": "2026-10-20T17:17:45+08:00"},
            ]
            (runtime / "trace-events.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in events), encoding="utf-8")
            latest = latest_node(ep)
            self.assertEqual(latest["current_action"], "CREATIVE_STORY")
            self.assertEqual(latest["execution_status"], "BLOCKED_RECORDED")
            self.assertEqual(latest["blocking_reason"], "STEP_BLOCKED")




    def test_story_excerpt_only_from_safe_bounded_draft(self):
        from scripts.storyos_local_readonly_api import read_local_story_excerpt
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "episode"
            docs = directory / "docs"
            docs.mkdir(parents=True)
            story = docs / "story.md"
            paragraph = "深秋山路发生滑坡，三名年轻人误入纯白色的疗养院，并逐渐意识到这里隐藏着令人不安的秘密。"
            story.write_text("# 标题\n\n## 完整故事（草稿）\n\n" + paragraph + "\n\n## 角色\n无", encoding="utf-8")
            self.assertEqual(read_local_story_excerpt(directory), paragraph)
            story.write_text("# 标题\n\n## 角色\n信息", encoding="utf-8")
            self.assertIsNone(read_local_story_excerpt(directory))
            story.write_text("# 标题\n## 完整故事\n\n" + "字" * (96 * 1024), encoding="utf-8")
            self.assertIsNone(read_local_story_excerpt(directory))

    def test_story_excerpt_detail_does_not_turn_into_release_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            directory = root / "episodes" / Path(NAMESPACE)
            (directory / "meta").mkdir(parents=True)
            (directory / "docs").mkdir()
            (directory / "meta" / "release-manifest.json").write_text("{}", encoding="utf-8")
            (directory / "docs" / "story.md").write_text(
                "# 标题\n\n## 完整故事\n\n"
                "三人意外误入深山中的纯白疗养院，逐渐发现异常迹象，却无法立即确认背后的真相。\n",
                encoding="utf-8")
            record = {"namespace": NAMESPACE, "title": "深渊疗愈所",
                      "business_episode_id": "00-14", "production_stage": "IDEA_LOCKED",
                      "updated_at": "2026-10-20T09:00:00+00:00"}
            with patch("scripts.storyos_local_readonly_api.observe_mysql_catalog",
                       return_value={"available": True, "reason": None,
                                     "items": [record], "truncated": False}):
                service = LocalEpisodeFileStatuses(root)
                summary = service.list_episode_statuses()["items"][0]
                self.assertNotIn("story_excerpt", summary, "story source is detail-only")
                detail = service.get_episode_status(summary["episode_ref"])
                self.assertIn("三人意外误入", detail["story_excerpt"])
                self.assertEqual(detail["story_excerpt_source"], "local_story_draft")
                self.assertEqual(detail["production_stage"], "IDEA_LOCKED")



if __name__ == "__main__":
    unittest.main()
