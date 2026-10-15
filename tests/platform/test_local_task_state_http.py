"""Task-state endpoint: localhost-only, GET-only, no query/cross-origin."""
import json
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from platform.api.http_server import PlatformApiHttpServer
from scripts.storyos_local_readonly_api import ReadOnlyLocalDispatcher, LocalReadOnlyHandler

class TaskReadOnlyHttpTests(unittest.TestCase):
    def setUp(self):
        self.server = PlatformApiHttpServer(("127.0.0.1", 0), ReadOnlyLocalDispatcher({}))
        self.server.RequestHandlerClass = LocalReadOnlyHandler
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.thread.join, 3)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = "http://127.0.0.1:" + str(self.server.server_address[1])

    def test_read_only_task_endpoint(self):
        data = {"scope": "LOCAL_REDIS_TASK_STATE_OBSERVATION", "available": True,
                "records": [], "record_count": 0, "live_execution_verified": False}
        with patch("scripts.storyos_local_readonly_api.observe_local_redis_task_states", return_value=data) as reader:
            with urlopen(self.base + "/api/v1/local-monitor/tasks", timeout=3) as response:
                self.assertEqual(response.status, 200)
                self.assertIsNone(response.headers.get("Access-Control-Allow-Origin"))
                self.assertEqual(json.loads(response.read())["data"], data)
            reader.assert_called_once_with()

    def test_deny_mutations_query_and_cross_origin_before_redis(self):
        with patch("scripts.storyos_local_readonly_api.observe_local_redis_task_states") as reader:
            requests = [
                Request(self.base + "/api/v1/local-monitor/tasks", data=b"{}", method="POST"),
                Request(self.base + "/api/v1/local-monitor/tasks?include=secrets"),
                Request(self.base + "/api/v1/local-monitor/tasks", headers={"Origin":"https://untrusted.example"}),
                Request(self.base + "/api/v1/local-monitor/tasks", headers={"Sec-Fetch-Site":"cross-site"}),
            ]
            for request in requests:
                with self.subTest(request=request.full_url):
                    with self.assertRaises(HTTPError) as err:
                        urlopen(request, timeout=3)
                    self.assertEqual(err.exception.code, 403)
            reader.assert_not_called()

if __name__ == "__main__":
    unittest.main()
