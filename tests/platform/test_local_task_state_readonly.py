"""Fail-closed TaskStateManager Redis observation: no inferred live production."""
import json
import os
import unittest
from unittest.mock import patch
from platform.operations.local_task_state_readonly import observe_local_redis_task_states

class FakeRedis:
    def __init__(self, items, error=False):
        self.items, self.error, self.calls = items, error, []
    def scan(self, *, cursor, match, count):
        self.calls.append("SCAN")
        if self.error:
            raise ConnectionError("redacted-secret-do-not-emit")
        return 0, list(self.items)
    def get(self, key):
        self.calls.append("GET")
        return self.items[key]

def row(task, status, **extras):
    return "storyos:task:" + task + ":state", json.dumps({"task_id": task, "status": status, **extras})

class RedisTaskObservationTests(unittest.TestCase):
    def test_empty_scan_does_not_prove_zero_running_tasks(self):
        result = observe_local_redis_task_states(FakeRedis({}))
        self.assertTrue(result["available"])
        self.assertTrue(result["scan_complete"])
        self.assertEqual(result["record_count"], 0)
        self.assertFalse(result["live_execution_verified"])

    def test_status_claims_are_not_live_evidence(self):
        sample = dict([row("one", "RUNNING", episode_id="secret", worker="also-secret"),
                       row("two", "QUEUED"), row("three", "FAILED")])
        db = FakeRedis(sample)
        result = observe_local_redis_task_states(db)
        self.assertEqual(result["running_claims"], 1)
        self.assertEqual(result["queued_claims"], 1)
        self.assertEqual(result["record_count"], 3)
        self.assertFalse(result["live_execution_verified"])
        self.assertFalse(result["episode_binding_verified"])
        self.assertEqual({*db.calls}, {"SCAN", "GET"})
        serialized = json.dumps(result)
        self.assertNotIn("secret", serialized)
        self.assertNotIn("one", serialized)
        self.assertNotIn("also", serialized)
        self.assertTrue(all(r["updated_at"] is None for r in result["records"]))

    def test_identity_and_unknown_status_fail_closed(self):
        a, b = row("alpha", "RUNNING", task_id="fake")
        c, d = row("beta", "ELEVATED")
        result = observe_local_redis_task_states(FakeRedis({a: b, c: d}))
        self.assertEqual(result["unverified_count"], 2)
        self.assertEqual(result["running_claims"], 0)

    def test_bad_payload_or_failure_does_not_expose(self):
        result = observe_local_redis_task_states(FakeRedis({"storyos:task:z:state":'{"token":"secret"'}))
        self.assertEqual(result["unverified_count"], 1)
        self.assertEqual(observe_local_redis_task_states(FakeRedis({},error=True))["reason"], "READ_ONLY_REDIS_UNAVAILABLE")

    def test_optin_is_required(self):
        with patch.dict(os.environ, {"STORYOS_LOCAL_MONITOR_REDIS": ""}):
            result = observe_local_redis_task_states()
        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "READ_ONLY_REDIS_NOT_ENABLED")

    def test_scanning_is_bounded_and_redacted(self):
        sample = dict(row("task-" + str(i), "RUNNING") for i in range(160))
        result = observe_local_redis_task_states(FakeRedis(sample))
        self.assertEqual(result["record_count"], 128)
        self.assertEqual(len(result["records"]), 40)
        self.assertFalse(result["scan_complete"])

if __name__ == "__main__":
    unittest.main()
