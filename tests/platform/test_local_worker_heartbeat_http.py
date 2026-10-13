"""HTTP Redis monitor remains localhost-only, cross-origin denied, GET-only."""
import json
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from platform.api.http_server import PlatformApiHttpServer
from scripts.storyos_local_readonly_api import ReadOnlyLocalDispatcher, LocalReadOnlyHandler


class WorkerReadOnlyHttpTests(unittest.TestCase):
    def setUp(self):
        server = PlatformApiHttpServer(("127.0.0.1", 0), ReadOnlyLocalDispatcher({}))
        server.RequestHandlerClass = LocalReadOnlyHandler
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        self.addCleanup(t.join, 3)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.base = "http://127.0.0.1:" + str(server.server_address[1])

    def test_get_only_returns_allowlisted_snapshot(self):
        snapshot = {"scope": "LOCAL_REDIS_HEARTBEAT_OBSERVATION", "record_count": 1,
                    "stale_heartbeats": 1, "fresh_heartbeats": 0,
                    "worker_execution_verified": False, "read_only": True}
        with patch("scripts.storyos_local_readonly_api.observe_local_redis_heartbeats", return_value=snapshot) as reader:
            with urlopen(self.base + "/api/v1/local-monitor/workers", timeout=3) as response:
                self.assertEqual(response.status, 200)
                self.assertIsNone(response.headers.get("Access-Control-Allow-Origin"))
                payload = json.loads(response.read())
            self.assertEqual(payload["code"], "OK")
            self.assertEqual(payload["data"], snapshot)
            reader.assert_called_once_with()
        with self.assertRaises(HTTPError) as denied:
            urlopen(Request(self.base + "/api/v1/local-monitor/workers",
                            data=b"{}", method="POST"), timeout=3)
        self.assertEqual(denied.exception.code, 403)

    def test_cors_and_query_fail_closed_before_reading_redis(self):
        with patch("scripts.storyos_local_readonly_api.observe_local_redis_heartbeats") as reader:
            for url, headers in (
                ("/api/v1/local-monitor/workers?key=exfiltrate", {}),
                ("/api/v1/local-monitor/workers", {"Origin": "https://untrusted.example"}),
                ("/api/v1/local-monitor/workers", {"Sec-Fetch-Site": "cross-site"}),
            ):
                with self.subTest(url=url, headers=headers):
                    req = Request(self.base + url, headers=headers)
                    with self.assertRaises(HTTPError) as denied:
                        urlopen(req, timeout=3)
                    self.assertEqual(denied.exception.code, 403)
            reader.assert_not_called()
