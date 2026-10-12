"""R36: explicitly injected read-only Worker TTL and Writer lease observers.

Worker heartbeat is global Redis state, NOT an Episode assignment. Only an
unambiguous RUNNING Task.owner_id from the canonical Episode-scoped MySQL table
may link it to one Episode. Neither reader grants dispatch/retry authority.

Writer proof requires a separately authorized fenced-owner reader in addition
to the canonical Driver's process/beacon report. A PID or file alone is never
a lease or a fencing token. No default production connections are opened.
"""
from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Protocol

from platform.operations.runtime_authority_evidence import AUTHORITATIVE_SOURCES
from platform.operations.runtime_authority_readers import MySqlAuthorityReadOnlyReaders


_WORKER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:\-]{0,95}$")
_MAX_JSON_BYTES = 4096


def _time(value: Any) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("AUTHORITY_TIMESTAMP_MISSING")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("AUTHORITY_TIMESTAMP_INVALID") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("AUTHORITY_TIMESTAMP_TIMEZONE_MISSING")
    return parsed.astimezone(timezone.utc)


def _age_seconds(value: Any, now: datetime, *, max_age: float) -> float:
    age = (now - _time(value)).total_seconds()
    if not -5 <= age <= max_age:
        raise ValueError("AUTHORITY_HEARTBEAT_STALE")
    return max(0.0, age)


class RedisHeartbeatReader(Protocol):
    def get(self, key: str) -> bytes | str | None: ...
    def pttl(self, key: str) -> int: ...


class EpisodeWorkerHeartbeatReadOnlyReader:
    """Bind ONE active MySQL Task owner to its live Redis heartbeat, with TTL.

    Absence of a running task, an ambiguous Task owner, a perpetual Redis key,
    an expired heartbeat, or a missing TTL is fail-closed. A healthy heartbeat
    is not evidence that the Worker still owns the execution/Driver lease.
    """

    def __init__(
        self,
        mysql: MySqlAuthorityReadOnlyReaders,
        redis: RedisHeartbeatReader,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        max_heartbeat_age_seconds: int = 120,
        max_ttl_ms: int = 600_000,
    ) -> None:
        self._mysql = mysql
        self._redis = redis
        self._clock = clock
        self._max_age = max_heartbeat_age_seconds
        self._max_ttl = max_ttl_ms
        if (type(self._max_age) is not int or not 1 <= self._max_age <= 300
                or type(self._max_ttl) is not int or not 1 <= self._max_ttl <= 3_600_000):
            raise ValueError("AUTHORITY_WORKER_TTL_POLICY_INVALID")

    def _single_task_owner(self, episode_id: str) -> tuple[str, str]:
        rows = self._mysql.connection.query_all(
            "SELECT TASK_ID, EPISODE_ID, OWNER_ID, STATUS FROM TB_TASK "
            "WHERE EPISODE_ID=%s AND STATUS='RUNNING' AND OWNER_ID IS NOT NULL "
            "ORDER BY START_TIME DESC, TASK_ID ASC LIMIT 2",
            (episode_id,),
        )
        if not isinstance(rows, (list, tuple)) or len(rows) != 1 or not isinstance(rows[0], Mapping):
            raise ValueError("AUTHORITY_WORKER_TASK_OWNER_AMBIGUOUS")
        task = rows[0]
        task_id = task.get("TASK_ID")
        worker_id = task.get("OWNER_ID")
        if (task.get("EPISODE_ID") != episode_id or task.get("STATUS") != "RUNNING"
                or not isinstance(task_id, str) or not task_id.strip()
                or not isinstance(worker_id, str) or _WORKER_ID.fullmatch(worker_id) is None):
            raise ValueError("AUTHORITY_WORKER_TASK_EPISODE_MISMATCH")
        return task_id, worker_id

    def __call__(self, episode_ref: str) -> dict[str, Any]:
        episode_id = self._mysql._episode_id(episode_ref)
        task_identity = self._single_task_owner(episode_id)
        _, worker_id = task_identity
        key = "storyos:worker:" + worker_id + ":heartbeat"
        # Redis GET/PTTL can race with a Worker reboot or Task reassignment.
        # Re-read BOTH sources and fail closed if either has changed.
        payload = self._redis.get(key)
        ttl = self._redis.pttl(key)
        if type(ttl) is not int or not 0 < ttl <= self._max_ttl:
            raise ValueError("AUTHORITY_WORKER_HEARTBEAT_TTL_UNVERIFIED")
        if isinstance(payload, bytes):
            if len(payload) > _MAX_JSON_BYTES:
                raise ValueError("AUTHORITY_WORKER_HEARTBEAT_TOO_LARGE")
            payload = payload.decode("utf-8")
        if not isinstance(payload, str) or len(payload.encode("utf-8")) > _MAX_JSON_BYTES:
            raise ValueError("AUTHORITY_WORKER_HEARTBEAT_MISSING")
        data = json.loads(payload)
        if not isinstance(data, dict) or data.get("worker_id") != worker_id or data.get("status") != "ONLINE":
            raise ValueError("AUTHORITY_WORKER_HEARTBEAT_IDENTITY_MISMATCH")
        now = self._clock().astimezone(timezone.utc)
        _age_seconds(data.get("heartbeat_time"), now, max_age=self._max_age)

        second_payload = self._redis.get(key)
        second_ttl = self._redis.pttl(key)
        if (second_payload != payload and
                (not isinstance(second_payload, bytes) or second_payload.decode("utf-8") != payload)):
            raise ValueError("AUTHORITY_WORKER_HEARTBEAT_CHANGED_DURING_READ")
        if type(second_ttl) is not int or not 0 < second_ttl <= self._max_ttl:
            raise ValueError("AUTHORITY_WORKER_HEARTBEAT_EXPIRED_DURING_READ")
        if self._mysql._episode_id(episode_ref) != episode_id:
            raise ValueError("AUTHORITY_WORKER_EPISODE_REASSIGNED_DURING_READ")
        if self._single_task_owner(episode_id) != task_identity:
            raise ValueError("AUTHORITY_WORKER_TASK_REASSIGNED_DURING_READ")
        return {
            "episode_ref": episode_ref,
            "source": AUTHORITATIVE_SOURCES["worker"],
            "verified": True,
            "read_only": True,
            "observed_at": self._clock().astimezone(timezone.utc).isoformat(),
            "heartbeat_verified": True,
            "execution_lease_verified": False,
        }


class EpisodeWriterFenceReadOnlyReader:
    """Require live Driver + fresh beacon + one canonical fencing lease.

    The fenced-owner reader is *mandatory*: there is no implicit file/Redis
    fallback. Inject a trusted owner authority explicitly at composition time.
    PID/liveness/driver JSON alone is never sufficient to set verified=True.
    """

    def __init__(
        self,
        driver_status: Callable[[str], Mapping[str, Any]],
        owner_fence: Callable[[str], Mapping[str, Any]],
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        max_beacon_age_seconds: int = 90,
        max_lease_horizon_seconds: int = 3600,
    ) -> None:
        self._driver_status = driver_status
        self._owner_fence = owner_fence
        self._clock = clock
        self._beacon_max = max_beacon_age_seconds
        self._lease_max = max_lease_horizon_seconds
        if (type(self._beacon_max) is not int or not 1 <= self._beacon_max <= 120
                or type(self._lease_max) is not int or not 1 <= self._lease_max <= 3600):
            raise ValueError("AUTHORITY_WRITER_LEASE_POLICY_INVALID")

    def __call__(self, episode_ref: str) -> dict[str, Any]:
        driver = self._driver_status(episode_ref)
        if not isinstance(driver, Mapping) or driver.get("episode_ref") != episode_ref:
            raise ValueError("AUTHORITY_WRITER_DRIVER_EPISODE_UNVERIFIED")
        pid = driver.get("pid")
        if (type(pid) is not int or pid <= 0
                or driver.get("driver_state") != "RUNNING"
                or driver.get("liveness") != "ALIVE"):
            raise ValueError("AUTHORITY_WRITER_DRIVER_NOT_VERIFIED")
        now = self._clock().astimezone(timezone.utc)
        age = driver.get("beacon_age_seconds")
        if (type(age) not in (int, float) or not math.isfinite(age)
                or not 0 <= age <= self._beacon_max):
            raise ValueError("AUTHORITY_WRITER_BEACON_STALE")
        _age_seconds(driver.get("beacon_at"), now, max_age=self._beacon_max)
        fence = self._owner_fence(episode_ref)
        if not isinstance(fence, Mapping) or fence.get("episode_ref") != episode_ref:
            raise ValueError("AUTHORITY_WRITER_FENCE_EPISODE_MISMATCH")
        if fence.get("authority_source") != "runtime_driver_owner_fence":
            raise ValueError("AUTHORITY_WRITER_FENCE_SOURCE_UNVERIFIED")
        if (fence.get("owner_active") is not True
                or type(fence.get("owner_count")) is not int or fence["owner_count"] != 1
                or type(fence.get("driver_pid")) is not int or fence["driver_pid"] != pid
                or type(fence.get("fencing_epoch")) is not int
                or not 1 <= fence["fencing_epoch"] <= 2**63 - 1):
            raise ValueError("AUTHORITY_WRITER_FENCE_NOT_UNIQUE")
        expires = _time(fence.get("lease_expires_at"))
        remaining = (expires - now).total_seconds()
        if not 0 < remaining <= self._lease_max:
            raise ValueError("AUTHORITY_WRITER_LEASE_EXPIRED_OR_UNBOUNDED")
        _age_seconds(fence.get("observed_at"), now, max_age=120)

        # A reader-only snapshot is not atomic. Verify that the fenced owner
        # and Driver did not change WHILE the two sources were inspected.
        # This is still advisory, not an acquired or renewable lease.
        second_fence = self._owner_fence(episode_ref)
        second_driver = self._driver_status(episode_ref)
        if not isinstance(second_fence, Mapping) or not isinstance(second_driver, Mapping):
            raise ValueError("AUTHORITY_WRITER_SNAPSHOT_CHANGED")
        for attribute in ("episode_ref", "authority_source", "owner_active",
                          "owner_count", "driver_pid", "fencing_epoch", "lease_expires_at"):
            if second_fence.get(attribute) != fence.get(attribute):
                raise ValueError("AUTHORITY_WRITER_FENCE_CHANGED_DURING_READ")
        if (second_driver.get("episode_ref") != episode_ref
                or second_driver.get("driver_state") != "RUNNING"
                or second_driver.get("liveness") != "ALIVE"
                or type(second_driver.get("pid")) is not int
                or second_driver["pid"] != pid):
            raise ValueError("AUTHORITY_WRITER_DRIVER_CHANGED_DURING_READ")
        second_now = self._clock().astimezone(timezone.utc)
        second_age = second_driver.get("beacon_age_seconds")
        if (type(second_age) not in (int, float) or not math.isfinite(second_age)
                or not 0 <= second_age <= self._beacon_max):
            raise ValueError("AUTHORITY_WRITER_BEACON_STALE_DURING_READ")
        _age_seconds(second_driver.get("beacon_at"), second_now, max_age=self._beacon_max)
        if (expires - second_now).total_seconds() <= 0:
            raise ValueError("AUTHORITY_WRITER_LEASE_EXPIRED_DURING_READ")
        _age_seconds(second_fence.get("observed_at"), second_now, max_age=120)
        return {
            "episode_ref": episode_ref,
            "source": AUTHORITATIVE_SOURCES["writer"],
            "verified": True,
            "read_only": True,
            "observed_at": now.isoformat(),
            "owner_fence_verified": True,
            "lease_advisory_only": True,
        }
