"""Episode-scoped read-only timeline of real MySQL production evidence.

Historical rows are NOT evidence of a presently executing Task, Frame or Provider.
All frames are drawn only from a verified Episode's read-only database snapshot.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

MAX_FRAMES = 20
MAX_AGE_SECONDS = 365 * 24 * 60 * 60
RESOLUTION_REQUIRED = frozenset({"OUTCOME_UNKNOWN"})


def _seconds_since(value: object, now: datetime) -> int | None:
    if not isinstance(value, str):
        return None
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if date.tzinfo is None or date.utcoffset() is None:
            return None
        seconds = (now.astimezone(timezone.utc) - date.astimezone(timezone.utc)).total_seconds()
        if seconds < -5 or seconds > MAX_AGE_SECONDS:
            return None
        return max(0, int(seconds))
    except (ValueError, OverflowError):
        return None


def _frame(value: object) -> int | None:
    if type(value) is int and 1 <= value <= MAX_FRAMES:
        return value
    return None


def _attempt_no(value: object) -> int | None:
    if type(value) is int and 0 <= value <= 1000:
        return value
    return None


def _safe_text(value: object) -> str | None:
    if isinstance(value, str) and value and len(value) <= 64:
        return value
    return None


def _empty(reason: str) -> dict[str, Any]:
    return {
        "scope": "VERIFIED_EPISODE_RECORDED_PROGRESS",
        "available": False,
        "reason": reason,
        "read_only": True,
        "verified_current_frame": None,
        "verified_current_task": None,
        "provider_call_verified": False,
        "stalled_verified": False,
        "execution_in_progress_verified": False,
        "writer_producer_claim_fresh": False,
        "recent_task": None,
        "recent_frame": None,
        "frame_attempts": [],
        "unresolved_generation_count": 0,
        "unresolved_generation_sample_only": True,
        "may_be_truncated": True,
    }


def summarize_production_progress(
    mysql: Mapping[str, Any] | None,
    owner: Mapping[str, Any] | None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Never join task IDs to generation assets without an authoritative link."""
    if not isinstance(mysql, Mapping) or not mysql.get("available"):
        return _empty("MYSQL_IDENTITY_OR_READONLY_UNAVAILABLE")
    if not mysql.get("database_identity_verified") or not mysql.get("read_only_grants_verified"):
        return _empty("MYSQL_IDENTITY_OR_READONLY_UNAVAILABLE")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        return _empty("OBSERVER_CLOCK_UNAVAILABLE")
    tasks = mysql.get("task_records")
    attempts = mysql.get("production_attempt_records")
    generations = mysql.get("generation_attempt_records")
    if not all(isinstance(rows, list) for rows in (tasks, attempts, generations)):
        return _empty("MYSQL_RESULT_SHAPE_UNVERIFIED")
    result = _empty(None)
    result["available"] = True
    result["reason"] = None
    result["writer_producer_claim_fresh"] = bool(
        isinstance(owner, Mapping)
        and owner.get("status") == "FRESH_PRODUCER_LOCK_CLAIM"
        and owner.get("producer_process_verified") is True
    )

    # TB_TASK often describes runtime checkpoint steps with FRAME_NO=NULL.
    # Its status is SAVED, never a live task/Provider statement.
    for row in tasks[:60]:
        if not isinstance(row, Mapping):
            continue
        result["recent_task"] = {
            "task_type": _safe_text(row.get("task_type")),
            "recorded_status": _safe_text(row.get("status")),
            "frame": _frame(row.get("frame")),
            "attempt_no": _attempt_no(row.get("attempt_no")),
            "recorded_updated_at": row.get("updated_at") if _seconds_since(row.get("updated_at"), current) is not None else None,
            "age_seconds": _seconds_since(row.get("updated_at"), current),
        }
        break

    by_frame: dict[int, dict[str, Any]] = {}
    for row in attempts[:60]:
        if not isinstance(row, Mapping):
            continue
        number = _frame(row.get("frame"))
        if number is None:
            continue
        status = _safe_text(row.get("status"))
        age = _seconds_since(row.get("recorded_at"), current)
        elapsed = row.get("elapsed_ms")
        item = {
            "frame": number,
            "last_attempt_no": _attempt_no(row.get("attempt_no")),
            "last_recorded_status": status,
            "last_kind": _safe_text(row.get("kind")),
            "last_error_code": _safe_text(row.get("error_code")),
            # Producer-reported historical duration; NOT current wall clock.
            "last_recorded_duration_ms": elapsed if type(elapsed) is int and 0 <= elapsed <= 86_400_000 else None,
            "recorded_at": row.get("recorded_at") if age is not None else None,
            "age_seconds": age,
        }
        # SQL sorted by CREATE_TIME DESC, so first sighting is the newest
        # sampled attempt per frame. Do not invent attempts outside 60 rows.
        if number not in by_frame:
            by_frame[number] = item

    ordered = list(by_frame.values())
    result["frame_attempts"] = sorted(ordered, key=lambda x: x["frame"])
    # The SQL snapshot is ordered by CREATE_TIME DESC; preserve that order
    # rather than selecting the highest frame number (production may repair old frames).
    result["recent_frame"] = next(
        (by_frame.get(_frame(row.get("frame")))
         for row in attempts[:60] if isinstance(row, Mapping)
         and _frame(row.get("frame")) in by_frame),
        None,
    )

    unresolved = []
    for row in generations[:60]:
        if not isinstance(row, Mapping):
            continue
        if row.get("status") in RESOLUTION_REQUIRED:
            unresolved.append(row)
    result["unresolved_generation_count"] = len(unresolved)
    # API rows are capped at 60; a short page cannot prove full coverage.
    result["may_be_truncated"] = bool(mysql.get("may_be_truncated", True))
    return result
