"""Read-only inspection of canonical Driver's in-lock heartbeat observation.

Never touch/acquire the actual writer lock. A fresh and process-matched claim
is useful evidence but not an instantaneous proof of kernel lock ownership.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Callable

REL = Path("meta/runtime/writer-owner-observation.json")
MAX_BYTES = 2048
MAX_AGE_SECONDS = 45
EPOCH = re.compile(r"^[a-f0-9]{32}$")
FINGERPRINT = re.compile(r"^[a-f0-9]{64}$")


def unknown(reason: str) -> dict[str, Any]:
    return {
        "scope": "DRIVER_IN_LOCK_OBSERVATION",
        "read_only": True,
        "status": "UNKNOWN",
        "reason": reason,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "fresh_seconds": None,
        "producer_process_verified": False,
        "kernel_lock_verified": False,
        "provider_inflight_verified": False,
    }


def _same_process(pid: int, created_at: float) -> bool:
    try:
        import psutil
        process = psutil.Process(pid)
        if not process.is_running() or process.status() in ("zombie", "dead"):
            return False
        return abs(process.create_time() - created_at) < 0.5
    except Exception:
        return False


def observe_writer_owner(
    episode: Path, *, now: datetime | None = None,
    process_matches: Callable[[int, float], bool] = _same_process,
) -> dict[str, Any]:
    """Status remains UNKNOWN unless all independent observations line up."""
    path = Path(episode).resolve()
    file = path / REL
    if not file.exists():
        return unknown("NO_CANONICAL_DRIVER_OWNER_EVIDENCE")
    try:
        if (file.is_symlink() or file.parent.is_symlink() or not file.is_file()
                or not file.resolve(strict=True).is_relative_to(path)
                or not 0 < file.stat().st_size <= MAX_BYTES):
            return unknown("OWNER_EVIDENCE_UNSAFE")
        original = file.read_bytes()
        if not 0 < len(original) <= MAX_BYTES:
            return unknown("OWNER_EVIDENCE_UNSAFE")
        data = json.loads(original.decode("utf-8"))
        if not isinstance(data, dict):
            return unknown("OWNER_EVIDENCE_INVALID")
        if data.get("schema_version") != 1 or data.get("source") != "canonical_persistent_runner":
            return unknown("OWNER_EVIDENCE_INVALID")
        if data.get("reported_lock") != "meta/runtime-runner.lock":
            return unknown("OWNER_EVIDENCE_INVALID")
        if not EPOCH.fullmatch(str(data.get("epoch", ""))):
            return unknown("OWNER_EVIDENCE_INVALID")
        fingerprint = hashlib.sha256(str(path).casefold().encode("utf-8")).hexdigest()
        if not FINGERPRINT.fullmatch(str(data.get("episode_fingerprint", ""))) or data["episode_fingerprint"] != fingerprint:
            return unknown("OWNER_EPISODE_MISMATCH")
        if data.get("status") != "HELD":
            return unknown("OWNER_NOT_REPORTED_HELD")
        pid, started = data.get("pid"), data.get("process_created_at")
        if type(pid) is not int or pid <= 0 or type(started) not in (float, int) or not 0 < started < 4102444800:
            return unknown("OWNER_PROCESS_IDENTITY_INVALID")
        timestamp = datetime.fromisoformat(str(data.get("heartbeat_at", "")).replace("Z", "+00:00"))
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            return unknown("OWNER_TIME_INVALID")
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None or current.utcoffset() is None:
            return unknown("OWNER_CLOCK_UNAVAILABLE")
        age = (current - timestamp.astimezone(timezone.utc)).total_seconds()
        if not -5 <= age <= MAX_AGE_SECONDS:
            return unknown("OWNER_HEARTBEAT_STALE")
        if not process_matches(pid, float(started)):
            return unknown("OWNER_PROCESS_NOT_VERIFIED")
        # A release/replace racing with process inspection must not yield green.
        if file.read_bytes() != original:
            return unknown("OWNER_EVIDENCE_CHANGED_DURING_READ")
        return {
            **unknown(None),
            "status": "FRESH_PRODUCER_LOCK_CLAIM",
            "reason": None,
            "fresh_seconds": round(max(0.0, age)),
            "producer_process_verified": True,
            # Strictly NOT a proof that a kernel byte-range lock remains held
            # at the reader's point in time, nor that a Provider is running.
            "kernel_lock_verified": False,
            "provider_inflight_verified": False,
        }
    except Exception:
        return unknown("OWNER_EVIDENCE_UNAVAILABLE")
