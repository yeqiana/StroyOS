from __future__ import annotations

import hashlib
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from platform.api.controllers import RuntimeStatusApiController
from platform.api.http_server import build_http_server
from scripts.storyos_local_readonly_api import (
    LocalApprovedMedia,
    LocalEpisodeFileStatuses,
    LocalReadOnlyHandler,
    ReadOnlyLocalDispatcher,
)

TINY_PNG = b"\x89PNG\r\n\x1a\n" + b"approved-image-test-data"


class LocalApprovedMediaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.episodes = self.root / "episodes"
        self.episodes.mkdir()
        self.episode = self.episodes / "09_stories" / "05_wedding"
        (self.episode / "meta").mkdir(parents=True)
        (self.episode / "meta" / "episode-state.json").write_text(
            json.dumps({"title": "婚礼前夜", "episode_id": "09-05", "current_state": "READY_TO_PUBLISH"}),
            encoding="utf-8",
        )
        self.approved = self.episode / "media" / "approved"
        self.approved.mkdir(parents=True)
        (self.approved / "01.png").write_bytes(TINY_PNG)
        self.candidate = self.episode / "media" / "candidates"
        self.candidate.mkdir()
        (self.candidate / "02.png").write_bytes(TINY_PNG)
        self.service = LocalEpisodeFileStatuses(self.root)
        self.media = LocalApprovedMedia(self.service)

    def test_catalog_only_approved_exact_episode(self):
        items, tokens = self.media.scan()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "婚礼前夜")
        self.assertEqual(items[0]["business_episode_id"], "09-05")
        self.assertEqual([x["frame"] for x in items[0]["frames"]], [1])
        url = items[0]["frames"][0]["url"]
        self.assertNotIn("09_stories", url)
        self.assertEqual(self.media.image(url.rsplit("/", 1)[-1]), (TINY_PNG, "image/png"))
        self.assertIsNone(self.media.image("../01.png"))
        self.assertIsNone(self.media.image("2" * 32))

    def test_source_fingerprint_revalidates_bytes_without_granting_binding(self):
        row = self.media.scan()[0][0]
        token = row["frames"][0]["url"].rsplit("/", 1)[-1]
        evidence = self.media.source_fingerprint(row["episode_ref"], token)
        self.assertEqual(evidence["sha256"], hashlib.sha256(TINY_PNG).hexdigest())
        self.assertEqual(evidence["frame"], 1)
        self.assertEqual(evidence["source"], "local_workspace_approved_only")
        self.assertEqual(evidence["production_reference_binding"], "NOT_SUBMITTED")
        self.assertEqual(evidence["provider_execution"], "UNVERIFIED")
        self.assertNotIn("path", evidence)
        self.assertIsNone(self.media.source_fingerprint("LOCAL_" + "0" * 24, token))
        self.assertIsNone(self.media.source_fingerprint(row["episode_ref"], "../01.png"))
        self.assertIsNone(self.media.source_fingerprint(row["episode_ref"], "0" * 32))
        # The media token identifies the path, not immutable pixels: recompute every time.
        changed = TINY_PNG + b"updated"
        (self.approved / "01.png").write_bytes(changed)
        self.assertEqual(self.media.source_fingerprint(row["episode_ref"], token)["sha256"],
                         hashlib.sha256(changed).hexdigest())
        (self.approved / "01.png").write_bytes(b"not-an-image")
        self.assertIsNone(self.media.source_fingerprint(row["episode_ref"], token))

    def test_archive_tests_symlink_and_unapproved_blocked(self):
        archived = self.episodes / "_archive" / "historic"
        (archived / "meta").mkdir(parents=True)
        (archived / "meta" / "episode-state.json").write_text(
            json.dumps({"title": "archived", "episode_id": "BAD", "current_state": "PUBLISHED"}))
        (archived / "media" / "approved").mkdir(parents=True)
        (archived / "media" / "approved" / "01.png").write_bytes(TINY_PNG)
        (self.approved / "02.png").write_bytes(b"bad-not-png")
        (self.approved / "30.png").write_bytes(TINY_PNG)
        outside = self.root / "secrets.png"
        outside.write_bytes(TINY_PNG)
        try:
            (self.approved / "03.png").symlink_to(outside)
        except (OSError, NotImplementedError):
            pass
        rows, tokens = self.media.scan()
        self.assertEqual([r["title"] for r in rows], ["婚礼前夜"])
        self.assertEqual([f["frame"] for f in rows[0]["frames"]], [1])
        self.assertEqual(len(tokens), 1)

    def test_http_catalog_binary_origin_and_readonly(self):
        server = build_http_server(
            {"RuntimeStatusApiController": RuntimeStatusApiController(self.service)},
            host="127.0.0.1", port=0)
        server.dispatcher = ReadOnlyLocalDispatcher(
            {"RuntimeStatusApiController": RuntimeStatusApiController(self.service)})
        server.approved_media = self.media
        server.RequestHandlerClass = LocalReadOnlyHandler
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_port}"

        def open_path(route, headers=None, method="GET"):
            return urlopen(Request(base + route, headers=headers or {}, method=method), timeout=4)

        with open_path("/api/v1/local-media/catalog") as response:
            payload = json.load(response)
            self.assertEqual(response.status, 200)
            self.assertEqual(payload["data"]["source"], "local_workspace_approved_only")
            self.assertNotIn("Access-Control-Allow-Origin", response.headers)
        url = payload["data"]["items"][0]["frames"][0]["url"]
        owner = payload["data"]["items"][0]["episode_ref"]
        fingerprint_url = "/api/v1/local-media/source-fingerprint/" + owner + "/" + url.rsplit("/", 1)[-1]
        with open_path(fingerprint_url) as response:
            proof = json.load(response)
            self.assertEqual(proof["data"]["sha256"], hashlib.sha256(TINY_PNG).hexdigest())
            self.assertEqual(proof["data"]["production_reference_binding"], "NOT_SUBMITTED")
            self.assertNotIn("Access-Control-Allow-Origin", response.headers)
        with open_path(url) as response:
            self.assertEqual(response.read(), TINY_PNG)
            self.assertEqual(response.headers["Content-Type"], "image/png")
            self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        for route, kw, status in (
            (url, {"headers": {"Origin": "https://evil.example"}}, 403),
            ("/api/v1/local-media/images/../01.png", {}, 404),
            (url + "?path=secrets", {}, 400),
            (fingerprint_url + "?path=secrets", {}, 400),
            (fingerprint_url, {"headers": {"Origin": "https://evil.example"}}, 403),
            (fingerprint_url.replace(owner, "LOCAL_" + "0" * 24), {}, 404),
            (fingerprint_url, {"method": "POST"}, 403),
            ("/api/v1/local-media/catalog", {"method": "POST"}, 403),
        ):
            with self.subTest(route=route, status=status), self.assertRaises(HTTPError) as ctx:
                open_path(route, **kw)
            self.assertEqual(ctx.exception.code, status)
        with open_path("/api/v1/runtime/statuses?limit=10&offset=0") as response:
            self.assertEqual(json.load(response)["data"]["total"], 1)


if __name__ == "__main__":
    unittest.main()
