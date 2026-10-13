from __future__ import annotations
from datetime import datetime, timedelta, timezone
import json
import os
import unittest
from unittest.mock import patch

from platform.operations.local_worker_heartbeat_readonly import observe_local_redis_heartbeats

NOW = datetime(2026, 10, 13, 2, 0, tzinfo=timezone.utc)


class ReadOnlyRedis:
    def __init__(self, records, fail=False):
        self.records = records
        self.calls = []
        self.fail = fail

    def scan(self, *, cursor, match, count):
        self.calls.append(("SCAN", match))
        if self.fail:
            raise ConnectionError("THIS_IS_A_SECRET_URL")
        return 0, list(self.records)

    def ttl(self, key):
        self.calls.append(("TTL", key))
        return self.records[key][0]

    def get(self, key):
        self.calls.append(("GET", key))
        return self.records[key][1]


def worker(name, age, ttl, status="ONLINE", extra=None):
    key = "storyos:worker:" + name + ":heartbeat"
    row = {"worker_id": name, "status": status,
           "heartbeat_time": (NOW - timedelta(seconds=age)).isoformat(),
           **(extra or {})}
    return key, (ttl, json.dumps(row))


class RedisHeartbeatObservationTests(unittest.TestCase):
    def test_stale_timestamp_even_when_redis_ttl_is_positive(self):
        key, record = worker("worker-1", 8 * 3600, 74)
        db = ReadOnlyRedis({key: record})
        data = observe_local_redis_heartbeats(db, now=NOW)
        self.assertTrue(data["available"])
        self.assertEqual(data["record_count"], 1)
        self.assertEqual(data["fresh_heartbeats"], 0)
        self.assertEqual(data["stale_heartbeats"], 1)
        self.assertFalse(data["worker_execution_verified"])
        self.assertFalse(data["writer_owner_verified"])
        self.assertEqual({x[0] for x in db.calls}, {"SCAN", "TTL", "GET"})

    def test_fresh_ttl_and_matching_identity_are_observations_not_writer_proof(self):
        key, record = worker("worker-1", 25, 66)
        d = observe_local_redis_heartbeats(ReadOnlyRedis({key: record}), now=NOW)
        self.assertEqual(d["fresh_heartbeats"], 1)
        self.assertFalse(d["worker_execution_verified"])
        self.assertFalse(d["task_attempt_verified"])

    def test_naive_datetime_with_positive_ttl_is_unverified(self):
        key, record = worker("worker-1", 15, 80)
        row = json.loads(record[1])
        row["heartbeat_time"] = "2026-10-13T02:00:00"
        d = observe_local_redis_heartbeats(
            ReadOnlyRedis({key: (80, json.dumps(row))}), now=NOW)
        self.assertEqual(d["record_count"], 1)
        self.assertEqual(d["unverified_heartbeats"], 1)
        self.assertEqual(d["fresh_heartbeats"], 0)
        self.assertEqual(d["stale_heartbeats"], 0)

    def test_non_expiring_key_does_not_claim_fresh(self):
        key, record = worker("worker-1", 15, -1)
        d = observe_local_redis_heartbeats(ReadOnlyRedis({key: record}), now=NOW)
        self.assertEqual(d["fresh_heartbeats"], 0)
        self.assertEqual(d["stale_heartbeats"], 1)

    def test_wrong_identity_and_invalid_payload_are_unverified(self):
        key, record = worker("worker-1", 20, 60, extra={"worker_id": "someone-else", "password": "secret-data"})
        other = "storyos:worker:broken:heartbeat"
        d = observe_local_redis_heartbeats(
            ReadOnlyRedis({key: record, other: (20, '{"unparsed":')}),
            now=NOW)
        self.assertEqual(d["unverified_heartbeats"], 2)
        self.assertEqual(d["fresh_heartbeats"], 0)
        serialized = json.dumps(d)
        self.assertNotIn("secret", serialized)
        self.assertNotIn("someone", serialized)
        self.assertNotIn("worker-1", serialized)

    def test_future_time_cannot_claim_fresh(self):
        key, record = worker("worker-1", -3600, 58)
        d = observe_local_redis_heartbeats(ReadOnlyRedis({key: record}), now=NOW)
        self.assertEqual(d["stale_heartbeats"], 1)

    def test_read_failure_fail_closed_without_credentials_or_raw_exception(self):
        d = observe_local_redis_heartbeats(ReadOnlyRedis({}, fail=True), now=NOW)
        self.assertFalse(d["available"])
        self.assertEqual(d["reason"], "READ_ONLY_REDIS_UNAVAILABLE")
        self.assertNotIn("SECRET", json.dumps(d))

    def test_default_optout_never_connects(self):
        with patch.dict(os.environ, {"STORYOS_LOCAL_MONITOR_REDIS": ""}):
            d = observe_local_redis_heartbeats()
        self.assertFalse(d["available"])
        self.assertEqual(d["reason"], "READ_ONLY_REDIS_NOT_ENABLED")

    def test_bounded_scan_does_not_return_ids(self):
        sample = dict(worker("safe-" + str(i), 15, 60) for i in range(280))
        d = observe_local_redis_heartbeats(ReadOnlyRedis(sample), now=NOW)
        self.assertFalse(d["scan_complete"])
        self.assertEqual(d["record_count"], 256)
        self.assertEqual(d["reason"], "SCAN_LIMIT_REACHED")
        self.assertNotIn("safe-1", json.dumps(d))


if __name__ == "__main__":
    unittest.main()
