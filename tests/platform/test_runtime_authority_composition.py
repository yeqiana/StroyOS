"""R37 opt-in composition, fake MySQL/Redis/Writer; no provider or network."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pytest

from platform.operations.runtime_authority_composition import build_runtime_authority_readonly


EP = "series/episode"
UID = "EPU_internal"
WORKER = "r37-worker"


def now():
    return datetime.now(timezone.utc)


class Status:
    def __init__(self, source="MYSQL_REDIS_CUTOVER"):
        self.source = source
        self.calls = []

    def get_episode_status(self, ref):
        self.calls.append(ref)
        if ref != EP:
            return None
        return {"episode_ref": ref, "state_source": self.source}


class Episodes:
    def __init__(self):
        self.calls = []

    def unique_owner_by_namespace(self, namespace):
        self.calls.append(namespace)
        return {"episode_namespace": namespace, "episode_id": UID,
                "disposition": "ACTIVE"}


class MySql:
    def __init__(self):
        self.calls = []

    def query_one(self, sql, params=None):
        self.calls.append((sql, params))
        assert sql.startswith("SELECT ")
        if sql.startswith("SELECT DATABASE()"):
            return {"selected_database": "STORY_OS_RUNTIME", "case_mode": 0}
        if "FROM TB_TASK " in sql:
            assert params == (UID,)
            return {"task_count": 1}
        if "FROM TB_GENERATION_ATTEMPT " in sql:
            assert params == (EP,)
            return {"attempt_count": 2, "unresolved_count": 1, "unknown_count": 1}
        raise AssertionError("unexpected SQL")

    def query_all(self, sql, params=None):
        self.calls.append((sql, params))
        assert sql.startswith("SELECT ") and params == (UID,)
        return [{"EPISODE_ID": UID, "TASK_ID": "task1", "STATUS": "RUNNING",
                 "OWNER_ID": WORKER}]

    def execute(self, *args):
        raise AssertionError("read-only SQL must not execute writes")


class Redis:
    def __init__(self):
        self.calls = []

    def get(self, key):
        self.calls.append(("get", key))
        assert key == f"storyos:worker:{WORKER}:heartbeat"
        return json.dumps({"worker_id": WORKER, "status": "ONLINE",
                           "heartbeat_time": now().isoformat()}).encode()

    def pttl(self, key):
        self.calls.append(("pttl", key))
        return 120000

    def set(self, *args):
        raise AssertionError("read-only Redis must not write")


def driver(ref):
    return {"episode_ref": ref, "driver_state": "RUNNING", "liveness": "ALIVE",
            "pid": 7744, "beacon_at": now().isoformat(),
            "beacon_age_seconds": 0.5}


def fenced(ref):
    return {"episode_ref": ref, "authority_source": "runtime_driver_owner_fence",
            "owner_active": True, "owner_count": 1, "driver_pid": 7744,
            "fencing_epoch": 3, "observed_at": now().isoformat(),
            "lease_expires_at": (now() + timedelta(minutes=5)).isoformat(),
            "lease_secret": "do-not-expose"}


def capacity():
    return {"scope": "LOCAL_GIT_COMMON_DIRECTORY",
            "global_max_inflight_images": 5,
            "observed_busy": 1, "observed_available": 4,
            "advisory_snapshot_only": True}


def test_no_config_does_not_create_connections_or_reader_calls():
    service = build_runtime_authority_readonly(Status())
    report = service.get_episode_authority(EP)
    assert report["scope"] == "AUTHORITY_NOT_CONFIGURED"
    assert all(v["status"] == "UNAVAILABLE" for v in report["evidence"].values())
    assert report["production_authorization"] is False


@pytest.mark.parametrize("key,object_factory", [
    ("mysql", MySql), ("episodes", Episodes), ("redis", Redis),
    ("driver_status", lambda: driver), ("owner_fence", lambda: fenced),
    ("capacity_snapshot", lambda: capacity),
])
def test_explicit_ack_is_required_even_for_one_injected_source(key, object_factory):
    with pytest.raises(ValueError, match="RUNTIME_AUTHORITY_EXTERNAL_READS_NOT_APPROVED"):
        build_runtime_authority_readonly(Status(), **{key: object_factory()})


@pytest.mark.parametrize("kwargs,reason", [
    ({"mysql": MySql()}, "RUNTIME_AUTHORITY_MYSQL_EPISODE_IDENTITY_REQUIRED"),
    ({"episodes": Episodes()}, "RUNTIME_AUTHORITY_MYSQL_EPISODE_IDENTITY_REQUIRED"),
    ({"redis": Redis()}, "RUNTIME_AUTHORITY_WORKER_TASK_LINEAGE_REQUIRED"),
    ({"driver_status": driver}, "RUNTIME_AUTHORITY_WRITER_FENCE_REQUIRED"),
    ({"owner_fence": fenced}, "RUNTIME_AUTHORITY_WRITER_FENCE_REQUIRED"),
])
def test_partial_dependencies_fail_before_any_external_read(kwargs, reason):
    with pytest.raises(ValueError, match=reason):
        build_runtime_authority_readonly(Status(), approve_external_reads=True, **kwargs)



@pytest.mark.parametrize("kwargs,reason", [
    ({"mysql": object(), "episodes": Episodes()}, "RUNTIME_AUTHORITY_MYSQL_SELECT_READER_REQUIRED"),
    ({"mysql": MySql(), "episodes": object()}, "RUNTIME_AUTHORITY_EPISODE_NAMESPACE_READER_REQUIRED"),
    ({"mysql": MySql(), "episodes": Episodes(), "redis": object()},
     "RUNTIME_AUTHORITY_WORKER_GET_PTTL_AND_TASK_SCAN_REQUIRED"),
    ({"mysql": MySql(), "episodes": Episodes(), "redis": Redis(),
      "driver_status": driver, "owner_fence": object()},
     "RUNTIME_AUTHORITY_WRITER_READER_REQUIRED"),
    ({"capacity_snapshot": object()}, "RUNTIME_AUTHORITY_CAPACITY_READER_REQUIRED"),
])
def test_reader_dependency_misconfiguration_fails_before_network(kwargs, reason):
    with pytest.raises(ValueError, match=reason):
        build_runtime_authority_readonly(Status(), approve_external_reads=True, **kwargs)


def test_worker_requires_mysql_task_scan_and_cannot_use_simple_count_reader():
    class CountOnlyMySql:
        def query_one(self, sql, params=None):
            raise AssertionError("factory should reject this before I/O")
    with pytest.raises(ValueError, match="RUNTIME_AUTHORITY_WORKER_GET_PTTL_AND_TASK_SCAN_REQUIRED"):
        build_runtime_authority_readonly(
            Status(), approve_external_reads=True,
            mysql=CountOnlyMySql(), episodes=Episodes(), redis=Redis(),
        )


def test_approval_without_sources_does_not_claim_authority():
    report = build_runtime_authority_readonly(
        Status(), approve_external_reads=True,
    ).get_episode_authority(EP)
    assert report["scope"] == "AUTHORITY_NOT_CONFIGURED"
    assert all(v["status"] == "UNAVAILABLE" for v in report["evidence"].values())


def test_explicit_readonly_composition_proves_five_sources_without_granting_actions():
    mysql, episodes, redis = MySql(), Episodes(), Redis()
    service = build_runtime_authority_readonly(
        Status(), approve_external_reads=True,
        mysql=mysql, episodes=episodes, redis=redis,
        driver_status=driver, owner_fence=fenced, capacity_snapshot=capacity,
    )
    result = service.get_episode_authority(EP)
    assert result["scope"] == "AUTHORIZED_READ_ONLY"
    proof = result["evidence"]
    assert [proof[k]["status"] for k in ("task", "attempt", "worker", "writer", "capacity")] == [
        "READ_ONLY_VERIFIED", "READ_ONLY_VERIFIED", "READ_ONLY_VERIFIED",
        "READ_ONLY_VERIFIED", "ADVISORY_ONLY",
    ]
    assert proof["attempt"]["unknown"] is True
    assert proof["attempt"]["unresolved"] is True
    assert proof["worker"]["heartbeat_verified"] is True
    assert proof["writer"]["owner_fence_verified"] is True
    assert proof["capacity"]["advisory_snapshot_only"] is True
    assert all(sql.startswith("SELECT ") for sql, _ in mysql.calls)
    assert all(key == f"storyos:worker:{WORKER}:heartbeat" for _, key in redis.calls)
    assert "do-not-expose" not in str(result)
    assert WORKER not in str(result)
    assert result["production_authorization"] is False
    assert not any(result[name] for name in ("can_start", "can_retry", "can_publish"))


def test_local_file_origin_blocks_all_sources_even_when_configured():
    mysql, redis = MySql(), Redis()
    service = build_runtime_authority_readonly(
        Status("local_workspace_episode_state_file"),
        approve_external_reads=True,
        mysql=mysql, episodes=Episodes(), redis=redis,
        driver_status=lambda ref: (_ for _ in ()).throw(AssertionError("no Driver")),
        owner_fence=lambda ref: (_ for _ in ()).throw(AssertionError("no Owner")),
        capacity_snapshot=lambda: (_ for _ in ()).throw(AssertionError("no Capacity")),
    )
    data = service.get_episode_authority(EP)
    assert data["scope"] == "LOCAL_READ_ONLY_EVIDENCE"
    assert all(v["reason"] == "LOCAL_STAGE_ONLY" for v in data["evidence"].values())
    assert mysql.calls == [] and redis.calls == []
    assert data["model_calls"] == 0


def test_unknown_episode_does_not_read_external_sources():
    mysql, redis = MySql(), Redis()
    status = Status()
    service = build_runtime_authority_readonly(
        status, approve_external_reads=True,
        mysql=mysql, episodes=Episodes(), redis=redis,
    )
    assert service.get_episode_authority("other/episode") is None
    assert mysql.calls == [] and redis.calls == []


def test_capacity_only_snapshot_is_advisory_never_provider_permit():
    report = build_runtime_authority_readonly(
        Status(), approve_external_reads=True, capacity_snapshot=capacity,
    ).get_episode_authority(EP)
    assert report["evidence"]["capacity"]["status"] == "ADVISORY_ONLY"
    assert report["evidence"]["worker"]["status"] == "UNAVAILABLE"
    assert report["production_authorization"] is False
    assert report["can_retry"] is False
