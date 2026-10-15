"""Bounded, localhost-opt-in, read-only observation of legacy Redis TaskStateManager records.

This legacy Redis key only contains task_id and status: no Episode, frame,
Worker, heartbeat_time or verified production lease. NEVER infer active work.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import os
import re
from typing import Any

PREFIX = "storyos:task:"
SUFFIX = ":state"
IDENTITY = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
STATUSES = frozenset(("PENDING", "QUEUED", "RUNNING", "RETRYING", "BLOCKED", "FAILED", "SUCCEEDED", "COMPLETED", "CANCELLED"))
MAX_SCAN_ROUNDS = 12
MAX_RECORDS = 128
MAX_EXPOSED = 40


def _result(available: bool, reason: str | None = None) -> dict[str, Any]:
    return {
        "scope": "LOCAL_REDIS_TASK_STATE_OBSERVATION",
        "source": "redis_storyos_task_state",
        "read_only": True,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "available": available,
        "reason": reason,
        "scan_complete": False,
        "record_count": 0,
        "unverified_count": 0,
        "running_claims": 0,
        "queued_claims": 0,
        "records": [],
        "live_execution_verified": False,
        "episode_binding_verified": False,
    }


def observe_local_redis_task_states(client=None) -> dict[str, Any]:
    """SCAN/GET only. Never emit raw Task ID, Redis keys or payload fields."""
    if client is None and os.environ.get("STORYOS_LOCAL_MONITOR_REDIS") != "1":
        return _result(False, "READ_ONLY_REDIS_NOT_ENABLED")
    owned = client is None
    result = _result(True)
    try:
        if owned:
            import redis
            client = redis.Redis(
                host="127.0.0.1", port=6379, db=int(os.environ.get("STORYOS_REDIS_DB", "0")),
                password=os.environ.get("STORYOS_REDIS_PASSWORD") or None,
                decode_responses=True, socket_connect_timeout=1.5,
                socket_timeout=1.5, retry_on_timeout=False,
            )
        cursor = 0
        visited: set[str] = set()
        for _ in range(MAX_SCAN_ROUNDS):
            cursor, keys = client.scan(cursor=cursor, match=PREFIX + "*" + SUFFIX, count=40)
            for key in keys:
                if len(visited) >= MAX_RECORDS:
                    result["reason"] = "SCAN_LIMIT_REACHED"
                    break
                if not isinstance(key, str) or not key.startswith(PREFIX) or not key.endswith(SUFFIX) or key in visited:
                    continue
                token = key[len(PREFIX):-len(SUFFIX)]
                if not IDENTITY.fullmatch(token):
                    continue
                visited.add(key)
                result["record_count"] += 1
                raw = client.get(key)
                if not isinstance(raw, str) or len(raw) > 4096:
                    result["unverified_count"] += 1
                    continue
                try:
                    state = json.loads(raw)
                    if not isinstance(state, dict) or state.get("task_id") != token:
                        raise ValueError("identity mismatch")
                    status = state.get("status")
                    if not isinstance(status, str) or status not in STATUSES:
                        raise ValueError("unknown status")
                except (TypeError, ValueError, json.JSONDecodeError):
                    result["unverified_count"] += 1
                    continue
                if status == "RUNNING":
                    result["running_claims"] += 1
                if status in ("PENDING", "QUEUED"):
                    result["queued_claims"] += 1
                if len(result["records"]) < MAX_EXPOSED:
                    result["records"].append({
                        "task_tag": sha256(token.encode("utf-8")).hexdigest()[:12],
                        "recorded_status": status,
                        "episode_ref": None, "frame": None, "worker": None,
                        "updated_at": None, "freshness_verified": False,
                    })
            if len(visited) >= MAX_RECORDS:
                break
            if cursor in (0, "0"):
                result["scan_complete"] = True
                break
        if not result["scan_complete"] and result["reason"] is None:
            result["reason"] = "SCAN_INCOMPLETE"
    except Exception:
        return _result(False, "READ_ONLY_REDIS_UNAVAILABLE")
    finally:
        if owned and client is not None:
            try:
                client.close()
            except Exception:
                pass
    return result
