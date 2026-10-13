"""R10: production monitoring cannot classify tests or archives as productions."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.storyos_local_readonly_api import LocalEpisodeFileStatuses


class RealEpisodeBoundaryTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.episodes = self.root / "episodes"
        self.episodes.mkdir()
        self.real1 = self.write("故事系列/作品A", "01-01", "A")
        self.real2 = self.write("故事系列/作品B", "01-02", "B")
        self.archive = self.write("_archive/legacy", "00-01", "should-not-see-archive")
        self.internal = self.write("_tests/qa-episode", "TEST-01", "should-not-see-test")
        self.hidden = self.write(".scratch/draft", "02-01", "should-not-see-hidden")
        self.nested = self.write("故事系列/杂项目/作品C", "02-02", "should-not-see-nested")
        self.missing_id = self.write("_tests/driver-abc", None, "should-not-see-driver")
        self.service = LocalEpisodeFileStatuses(self.root)

    def write(self, folder, episode_id, title):
        meta = self.episodes / folder / "meta"
        meta.mkdir(parents=True)
        row = {"title": title, "series": "故事系列", "current_state": "VISUAL_CALIBRATED"}
        if episode_id is not None:
            row["episode_id"] = episode_id
        file = meta / "episode-state.json"
        file.write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")
        return file

    def ref(self, file):
        relative = file.relative_to(self.episodes).as_posix()
        return "LOCAL_" + hashlib.sha256(relative.encode("utf-8")).hexdigest()[:24]

    def test_only_genuine_root_series_episode_visible_and_stable_refs(self):
        page = self.service.list_episode_statuses("100", "0")
        self.assertEqual(page["total"], 2)
        self.assertEqual([x["title"] for x in page["items"]], ["A", "B"])
        self.assertEqual({r["episode_ref"] for r in page["items"]},
                         {self.ref(self.real1), self.ref(self.real2)})
        self.assertEqual(page["stage_counts"], {"VISUAL_CALIBRATED": 2})
        self.assertFalse(page["has_more"])

    def test_internal_and_archive_cannot_be_opened_by_guessing_ref(self):
        for file in (self.archive, self.internal, self.hidden, self.nested, self.missing_id):
            with self.subTest(path=file.parent.parent.name):
                with patch("scripts.storyos_local_readonly_api.observe_mysql_episode") as query:
                    self.assertIsNone(self.service.get_episode_status(self.ref(file)))
                    query.assert_not_called()

    def test_real_episode_detail_still_has_file_and_mysql_contract(self):
        with patch("scripts.storyos_local_readonly_api.observe_mysql_episode",
                   return_value={"available": False, "reason": "TEST_READONLY"}) as spy:
            d = self.service.get_episode_status(self.ref(self.real1))
            self.assertIsNotNone(d)
            self.assertEqual(d["title"], "A")
            self.assertEqual(d["execution_status"], "UNKNOWN")
            self.assertEqual(d["mysql_monitor"]["reason"], "TEST_READONLY")
            spy.assert_called_once_with("故事系列/作品A", "01-01")


if __name__ == "__main__":
    unittest.main()
