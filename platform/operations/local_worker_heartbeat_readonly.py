"""Conservative, Redis GET/TTL/SCAN-only local Worker heartbeat observations.

A TTL refreshed without a fresh heartbeat_time is stale. A recent heartbeat
does NOT prove Writer ownership, Generation Attempt authorization or live work.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import re
from typing import Any

PREFIX = "storyos:worker:"
SUFFIX = ":heartbeat"
WORKER_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
MAX_ITEMS = 256
MAX_SCANS = 16
MAX_HEARTBEAT_AGE_SECONDS = 120


def _response(*, available: bool, reason: str | None = None) -> dict[str, Any]:
    return {
        "scope": "LOCAL_REDIS_HEARTBEAT_OBSERVATION",
        "read_only": True,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "source": "redis_storyos_worker_heartbeat",
        "available": available,
        "reason": reason,
        "record_count": 0,
        "fresh_heartbeats": 0,
        "stale_heartbeats": 0,
        "unverified_heartbeats": 0,
        "scan_complete": False,
        "worker_execution_verified": False,
        "writer_owner_verified": False,
        "task_attempt_verified": False,
    }


def observe_local_redis_heartbeats(client=None, *, now: datetime | None = None) -> dict[str, Any]:
    """Fail closed without read opt-in, or when Redis is unavailable.

    Never return worker IDs, raw Redis values, credentials, hostname, keys,
    arbitrary exception strings or sensitive task details.
    """
    if client is None and os.environ.get("STORYOS_LOCAL_MONITOR_REDIS") != "1":
        return _response(available=False, reason="READ_ONLY_REDIS_NOT_ENABLED")
    owned = client is None
    result = _response(available=True)
    try:
        if owned:
            import redis
            client = redis.Redis(
                host="127.0.0.1", port=6379,
                db=int(os.environ.get("STORYOS_REDIS_DB", "0")),
                password=os.environ.get("STORYOS_REDIS_PASSWORD") or None,
                decode_responses=True,
                socket_connect_timeout=1.5, socket_timeout=1.5,
                retry_on_timeout=False,
            )
        snapshot_time = now or datetime.now(timezone.utc)
        if snapshot_time.tzinfo is None or snapshot_time.utcoffset() is None:
            raise ValueError("snapshot timestamp is not timezone-aware")
        cursor = 0
        visited: set[str] = set()
        for _ in range(MAX_SCANS):
            cursor, candidates = client.scan(cursor=cursor, match=PREFIX + "*" + SUFFIX, count=40)
            for key in candidates:
                if len(visited) >= MAX_ITEMS:
                    result["reason"] = "SCAN_LIMIT_REACHED"
                    break
                if not isinstance(key, str) or not key.startswith(PREFIX) or not key.endswith(SUFFIX):
                    continue
                identity = key[len(PREFIX):-len(SUFFIX)]
                if not WORKER_ID.fullmatch(identity) or key in visited:
                    continue
                visited.add(key)
                result["record_count"] += 1
                ttl = client.ttl(key)
                raw = client.get(key)
                if raw is None or not isinstance(raw, str) or len(raw) > 4096:
                    result["unverified_heartbeats"] += 1
                    continue
                try:
                    value = json.loads(raw)
                    if not isinstance(value, dict) or value.get("worker_id") != identity:
                        raise ValueError("worker identity mismatch")
                    observed = datetime.fromisoformat(str(value.get("heartbeat_time", "")).replace("Z", "+00:00"))
                    if observed.tzinfo is None or observed.utcoffset() is None:
                        raise ValueError("invalid timezone")
                    age = (snapshot_time - observed.astimezone(timezone.utc)).total_seconds()
                    # Redis TTL alone cannot prove a new heartbeat actually occurred.
                    if value.get("status") == "ONLINE" and type(ttl) is int and ttl > 0 and -5 <= age <= MAX_HEARTBEAT_AGE_SECONDS:
                        result["fresh_heartbeats"] += 1
                    else:
                        result["stale_heartbeats"] += 1
                except (ValueError, OverflowError, TypeError, json.JSONDecodeError):
                    result["unverified_heartbeats"] += 1
            if len(visited) >= MAX_ITEMS:
                break
            if cursor == 0:
                result["scan_complete"] = True
                break
        if not result["scan_complete"] and result["reason"] is None:
            result["reason"] = "SCAN_INCOMPLETE"
    except Exception:
        return _response(available=False, reason="READ_ONLY_REDIS_UNAVAILABLE")
    finally:
        if owned and client is not None:
            try:
                client.close()
            except Exception:
                pass
    return result
