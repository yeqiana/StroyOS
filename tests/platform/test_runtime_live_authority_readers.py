"""R36 Worker TTL / Episode lineage / single fenced Writer — hermetic only.

All MySQL queries and Redis reads are instrumented; no background Worker,
production Driver, images, or external service is started by this suite.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest

from platform.operations.runtime_authority_evidence import RuntimeAuthorityEvidenceService
from platform.operations.runtime_authority_readers import MySqlAuthorityReadOnlyReaders
from platform.operations.runtime_live_authority_readers import (
    EpisodeWorkerHeartbeatReadOnlyReader,
    EpisodeWriterFenceReadOnlyReader,
)

REF = "series/episode"
EP_UID = "EPU_bound"
WORKER = "r36-worker"
NOW = datetime.now(timezone.utc).replace(microsecond=0)


class Status:
    def __init__(self, source="MYSQL_REDIS_CUTOVER"):
        self.source = source

    def get_episode_status(self, ref):
        return {"episode_ref": ref, "state_source": self.source}


class EpisodeRepo:
    def __init__(self, namespace=REF, disposition="ACTIVE"):
        self.namespace, self.disposition = namespace, disposition

    def unique_owner_by_namespace(self, namespace):
        return {"episode_namespace": self.namespace, "episode_id": EP_UID,
                "disposition": self.disposition}


class Sql:
    def __init__(self, tasks=None, database="STORY_OS_RUNTIME", case_mode=0):
        self.database, self.case_mode = database, case_mode
        self.tasks = tasks if tasks is not None else [{
            "TASK_ID": "task-ep",
            "EPISODE_ID": EP_UID,
            "STATUS": "RUNNING",
            "OWNER_ID": WORKER,
        }]
        self.calls = []

    def query_one(self, sql, params=None):
        self.calls.append((sql, params))
        assert sql.startswith("SELECT ")
        assert params is None
        return {"selected_database": self.database, "case_mode": self.case_mode}

    def query_all(self, sql, params=None):
        self.calls.append((sql, params))
        assert sql.startswith("SELECT ")
        assert "WHERE EPISODE_ID=%s" in sql
        assert "STATUS='RUNNING'" in sql
        assert params == (EP_UID,)
        return deepcopy(self.tasks)

    def execute(self, *args):
        raise AssertionError("SQL_MUTATION_FORBIDDEN")


class Redis:
    def __init__(self, *, obj=None, ttl=118_000):
        self.obj = obj if obj is not None else {
            "worker_id": WORKER, "status": "ONLINE",
            "heartbeat_time": (NOW - timedelta(seconds=3)).isoformat(),
        }
        self.ttl=ttl
        self.calls=[]

    def get(self, key):
        self.calls.append(("get",key))
        return json.dumps(self.obj).encode("utf-8")

    def pttl(self, key):
        self.calls.append(("pttl",key))
        return self.ttl

    def set(self, *args):
        raise AssertionError("REDIS_MUTATION_FORBIDDEN")


def worker_reader(*, sql=None, redis=None, repo=None):
    sql = sql or Sql()
    redis = redis or Redis()
    return EpisodeWorkerHeartbeatReadOnlyReader(
        MySqlAuthorityReadOnlyReaders(sql, repo or EpisodeRepo()),
        redis, clock=lambda: NOW,
    ), sql, redis


def driver():
    return {
        "episode_ref": REF, "driver_state": "RUNNING", "liveness": "ALIVE",
        "pid": 8812, "beacon_age_seconds": 3.0,
        "beacon_at": (NOW - timedelta(seconds=3)).isoformat(),
    }


def fence():
    return {
        "episode_ref": REF, "authority_source": "runtime_driver_owner_fence",
        "owner_active": True, "owner_count": 1, "driver_pid": 8812,
        "fencing_epoch": 9,
        "observed_at": (NOW - timedelta(seconds=1)).isoformat(),
        "lease_expires_at": (NOW + timedelta(minutes=5)).isoformat(),
        "lease_secret": "SHOULD_NOT_LEAK",
    }


def writer_reader(*, drive=None, lease=None):
    return EpisodeWriterFenceReadOnlyReader(
        lambda _: deepcopy(drive) if drive is not None else driver(),
        lambda _: deepcopy(lease) if lease is not None else fence(),
        clock=lambda: NOW,
    )


def projected(readers, source="MYSQL_REDIS_CUTOVER"):
    return RuntimeAuthorityEvidenceService(
        Status(source), permit_authority_reads=True,
        authorized_readers=readers,
    ).get_episode_authority(REF)


def test_real_task_binding_redis_pttl_tz_and_no_mutations():
    reader, sql, redis = worker_reader()
    report = projected({"worker": reader})
    proof = report["evidence"]["worker"]
    assert proof["status"] == "READ_ONLY_VERIFIED"
    assert proof["heartbeat_verified"] is True
    assert proof["source"] == "redis_worker_heartbeat"
    assert proof["observed_at"]
    assert report["production_authorization"] is False
    assert report["can_start"] is False and report["can_retry"] is False
    assert len(sql.calls) == 4  # pre/post MySQL Episode + active Task validation
    assert all(sql.startswith("SELECT ") for sql, _ in sql.calls)
    assert redis.calls == [
        ("get", f"storyos:worker:{WORKER}:heartbeat"),
        ("pttl", f"storyos:worker:{WORKER}:heartbeat"),
        ("get", f"storyos:worker:{WORKER}:heartbeat"),
        ("pttl", f"storyos:worker:{WORKER}:heartbeat"),
    ]
    assert WORKER not in str(report)
    assert "task-ep" not in str(report)


@pytest.mark.parametrize("ttl", [None, True, -2, -1, 0, 600_001, "120000"])
def test_missing_infinite_or_forged_ttl_is_not_worker_online(ttl):
    reader, _, _ = worker_reader(redis=Redis(ttl=ttl))
    result = projected({"worker": reader})
    assert result["evidence"]["worker"]["status"] == "UNAVAILABLE"
    assert result["production_authorization"] is False


@pytest.mark.parametrize("obj", [
    {"worker_id": "somebody-else", "status": "ONLINE",
     "heartbeat_time": (NOW-timedelta(seconds=2)).isoformat()},
    {"worker_id": WORKER, "status": "OFFLINE",
     "heartbeat_time": NOW.isoformat()},
    {"worker_id": WORKER, "status": "ONLINE",
     "heartbeat_time": (NOW-timedelta(seconds=200)).isoformat()},
    {"worker_id": WORKER, "status": "ONLINE",
     "heartbeat_time": (NOW+timedelta(seconds=20)).isoformat()},
    {"worker_id": WORKER, "status": "ONLINE",
     "heartbeat_time": NOW.replace(tzinfo=None).isoformat()},
    {"worker_id": WORKER, "status": "ONLINE", "heartbeat_time": "bad"},
])
def test_wrong_worker_offline_stale_future_or_naive_timestamps_rejected(obj):
    reader, _, _ = worker_reader(redis=Redis(obj=obj))
    result = projected({"worker": reader})
    assert result["evidence"]["worker"]["status"] == "UNAVAILABLE"


@pytest.mark.parametrize("rows", [
    [],
    [{"TASK_ID": "task-ep", "EPISODE_ID": "other", "STATUS": "RUNNING", "OWNER_ID": WORKER}],
    [{"TASK_ID": "task-ep", "EPISODE_ID": EP_UID, "STATUS": "WAITING", "OWNER_ID": WORKER}],
    [{"TASK_ID": "task-ep", "EPISODE_ID": EP_UID, "STATUS": "RUNNING", "OWNER_ID": ""}],
    [{"TASK_ID": "task-ep", "EPISODE_ID": EP_UID, "STATUS": "RUNNING", "OWNER_ID": "invalid/worker"}],
    [{"TASK_ID": "task-ep", "EPISODE_ID": EP_UID, "STATUS": "RUNNING", "OWNER_ID": WORKER},
     {"TASK_ID": "task-ep2", "EPISODE_ID": EP_UID, "STATUS": "RUNNING", "OWNER_ID": WORKER}],
])
def test_unbound_ambiguous_task_worker_never_queries_redis(rows):
    redis = Redis()
    reader, _, _ = worker_reader(sql=Sql(tasks=rows), redis=redis)
    result = projected({"worker": reader})
    assert result["evidence"]["worker"]["status"] == "UNAVAILABLE"
    assert redis.calls == []


def test_foreign_episode_db_or_disposition_never_reads_worker_redis():
    for sql, repo in [
        (Sql(database="STORY_OS_RUNTIME_OLD"), EpisodeRepo()),
        (Sql(case_mode=1), EpisodeRepo()),
        (Sql(), EpisodeRepo(namespace="other/episode")),
        (Sql(), EpisodeRepo(disposition="VOIDED")),
    ]:
        redis = Redis()
        reader, _, _ = worker_reader(sql=sql, redis=redis, repo=repo)
        assert projected({"worker": reader})["evidence"]["worker"]["status"] == "UNAVAILABLE"
        assert redis.calls == []


def test_valid_writer_needs_actual_beacon_and_one_fenced_owner():
    report = projected({"writer": writer_reader()})
    proof = report["evidence"]["writer"]
    assert proof["status"] == "READ_ONLY_VERIFIED"
    assert proof["owner_fence_verified"] is True
    assert proof["source"] == "runtime_driver_owner_fence"
    assert report["production_authorization"] is False
    assert "SHOULD_NOT_LEAK" not in str(report)
    assert "8812" not in str(report)
    assert "fencing_epoch" not in str(report)


@pytest.mark.parametrize("change", [
    {"episode_ref": "other/ep"},
    {"driver_state": "ALIVE_NOT_BEATING"},
    {"liveness": "UNKNOWN"},
    {"pid": 0},
    {"pid": True},
    {"beacon_age_seconds": None},
    {"beacon_age_seconds": -1},
    {"beacon_age_seconds": 91},
    {"beacon_at": (NOW - timedelta(seconds=200)).isoformat()},
    {"beacon_at": (NOW + timedelta(seconds=20)).isoformat()},
])
def test_writer_requires_healthy_episode_bound_driver_beacon(change):
    bad = {**driver(), **change}
    result=projected({"writer":writer_reader(drive=bad)})
    assert result["evidence"]["writer"]["status"]=="UNAVAILABLE"


@pytest.mark.parametrize("change", [
    {"episode_ref":"other/ep"},
    {"authority_source":"a-local-json-file"},
    {"owner_active":False},
    {"owner_count":2},
    {"owner_count":0},
    {"owner_count":True},
    {"driver_pid":8813},
    {"fencing_epoch":0},
    {"fencing_epoch":True},
    {"lease_expires_at":(NOW-timedelta(seconds=1)).isoformat()},
    {"lease_expires_at":(NOW+timedelta(days=7)).isoformat()},
    {"lease_expires_at":"not-a-timestamp"},
    {"observed_at":(NOW-timedelta(minutes=10)).isoformat()},
])
def test_writer_requires_unique_fresh_fenced_lease(change):
    bad={**fence(),**change}
    result=projected({"writer":writer_reader(lease=bad)})
    assert result["evidence"]["writer"]["status"]=="UNAVAILABLE"
    assert "SHOULD_NOT_LEAK" not in str(result)


def test_missing_fence_reader_does_not_upgrade_pid_beacon_to_verified():
    writer=EpisodeWriterFenceReadOnlyReader(lambda _:driver(),lambda _:None,clock=lambda:NOW)
    result=projected({"writer":writer})
    assert result["evidence"]["writer"]["status"]=="UNAVAILABLE"
    assert result["can_publish"] is False



@pytest.mark.parametrize("overrides", [
    {"max_heartbeat_age_seconds": True},
    {"max_heartbeat_age_seconds": 9999},
    {"max_heartbeat_age_seconds": 0},
    {"max_ttl_ms": True},
    {"max_ttl_ms": 999999999},
])
def test_worker_ttl_policy_must_not_be_disabled_by_bad_configuration(overrides):
    with pytest.raises(ValueError, match="AUTHORITY_WORKER_TTL_POLICY_INVALID"):
        EpisodeWorkerHeartbeatReadOnlyReader(
            MySqlAuthorityReadOnlyReaders(Sql(), EpisodeRepo()),
            Redis(), **overrides,
        )


@pytest.mark.parametrize("overrides", [
    {"max_beacon_age_seconds": True},
    {"max_beacon_age_seconds": 500},
    {"max_beacon_age_seconds": 0},
    {"max_lease_horizon_seconds": True},
    {"max_lease_horizon_seconds": 86400},
])
def test_writer_fencing_policy_cannot_use_unbounded_configuration(overrides):
    with pytest.raises(ValueError, match="AUTHORITY_WRITER_LEASE_POLICY_INVALID"):
        EpisodeWriterFenceReadOnlyReader(
            lambda _: driver(), lambda _: fence(), **overrides,
        )



def test_r37_worker_task_reassigned_during_redis_read_fails_closed():
    class ReassignedSql(Sql):
        read_count = 0

        def query_all(self, sql, params=None):
            self.read_count += 1
            rows = super().query_all(sql, params)
            if self.read_count == 2:
                rows[0]["OWNER_ID"] = "replacement-worker"
            return rows

    reader, db, redis = worker_reader(sql=ReassignedSql())
    report = projected({"worker": reader})
    assert report["evidence"]["worker"]["status"] == "UNAVAILABLE"
    assert report["evidence"]["worker"]["reason"] == "AUTHORITY_READER_FAILED"
    assert len(db.calls) == 4
    assert len(redis.calls) == 4
    assert report["production_authorization"] is False


def test_r37_worker_episode_uid_changed_during_redis_read_fails_closed():
    class ReboundEpisodes(EpisodeRepo):
        reads = 0

        def unique_owner_by_namespace(self, namespace):
            self.reads += 1
            result = super().unique_owner_by_namespace(namespace)
            if self.reads == 2:
                result["episode_id"] = "EPU_other"
            return result

    reader, _, _ = worker_reader(repo=ReboundEpisodes())
    report = projected({"worker": reader})
    assert report["evidence"]["worker"]["status"] == "UNAVAILABLE"
    assert report["can_retry"] is False


def test_r37_worker_redis_heartbeat_replaced_mid_read_fails_closed():
    class ChangingHeartbeat(Redis):
        n = 0

        def get(self, key):
            self.n += 1
            result = super().get(key)
            if self.n == 2:
                data = json.loads(result)
                data["heartbeat_time"] = NOW.isoformat()
                return json.dumps(data).encode("utf-8")
            return result

    reader, _, redis = worker_reader(redis=ChangingHeartbeat())
    report = projected({"worker": reader})
    assert report["evidence"]["worker"]["status"] == "UNAVAILABLE"
    assert len(redis.calls) == 4


def test_r37_worker_redis_heartbeat_expired_between_reads_fails_closed():
    class ExpiringHeartbeat(Redis):
        n = 0

        def pttl(self, key):
            self.n += 1
            self.calls.append(("pttl", key))
            return self.ttl if self.n == 1 else -2

    reader, _, _ = worker_reader(redis=ExpiringHeartbeat())
    report = projected({"worker": reader})
    assert report["evidence"]["worker"]["status"] == "UNAVAILABLE"
    assert report["production_authorization"] is False


@pytest.mark.parametrize("changed_field,new_value", [
    ("fencing_epoch", 10),
    ("owner_count", 2),
    ("driver_pid", 9999),
    ("lease_expires_at", (NOW+timedelta(minutes=10)).isoformat()),
    ("owner_active", False),
])
def test_r37_writer_fencing_changed_between_samples_blocks(changed_field, new_value):
    snapshots = [fence(), {**fence(), changed_field: new_value}]
    reader = EpisodeWriterFenceReadOnlyReader(
        lambda ep: driver(),
        lambda ep: snapshots.pop(0),
        clock=lambda: NOW,
    )
    report = projected({"writer": reader})
    assert report["evidence"]["writer"]["status"] == "UNAVAILABLE"
    assert report["can_start"] is False


def test_r37_writer_driver_pid_recycled_between_samples_blocks():
    seen = [driver(), {**driver(), "pid": 8877}]
    reader = EpisodeWriterFenceReadOnlyReader(
        lambda ep: seen.pop(0), lambda ep: fence(), clock=lambda: NOW,
    )
    report = projected({"writer": reader})
    assert report["evidence"]["writer"]["status"] == "UNAVAILABLE"


def test_r37_writer_lease_expires_between_samples_blocks():
    clock_values = iter([NOW, NOW+timedelta(minutes=6)])
    reader = EpisodeWriterFenceReadOnlyReader(
        lambda ep: driver(), lambda ep: fence(),
        clock=lambda: next(clock_values),
    )
    report = projected({"writer": reader})
    assert report["evidence"]["writer"]["status"] == "UNAVAILABLE"
    assert report["can_retry"] is False


def test_r37_writer_beacon_stops_during_fence_read_blocks():
    seen = [driver(), {**driver(), "beacon_age_seconds": 150}]
    reader = EpisodeWriterFenceReadOnlyReader(
        lambda ep: seen.pop(0), lambda ep: fence(), clock=lambda: NOW,
    )
    report = projected({"writer": reader})
    assert report["evidence"]["writer"]["status"] == "UNAVAILABLE"


def test_r37_good_two_sample_writer_is_evidence_only():
    result = projected({"writer": writer_reader()})
    assert result["evidence"]["writer"]["status"] == "READ_ONLY_VERIFIED"
    assert result["can_start"] is False
    assert result["can_retry"] is False
    assert result["can_publish"] is False
    assert result["production_authorization"] is False


def test_local_file_never_reads_worker_or_fenced_owner():
    calls=[]
    service=RuntimeAuthorityEvidenceService(
        Status(source="local_workspace_episode_state_file"),
        permit_authority_reads=True,
        authorized_readers={
            "worker":lambda ep:calls.append("redis"),
            "writer":lambda ep:calls.append("fence"),
        },
    )
    result=service.get_episode_authority(REF)
    assert calls==[]
    assert all(item["status"]=="UNAVAILABLE" for item in result["evidence"].values())
