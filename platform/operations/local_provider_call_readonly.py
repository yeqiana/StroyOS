"""Readonly R13 provider-call window, never an execution/dispatch authorization.

A reported frame is accepted only when a freshly process-verified Driver owner
matches the in-process provider-call epoch AND the SELECT-only Generation
Attempt for that frame is durably DISPATCH_COMMITTED with no terminal record.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from platform.operations.local_writer_owner_readonly import (
    observe_writer_owner, REL as OWNER_REL, _same_process,
)

REL = Path("meta/runtime/provider-inflight-observation.json")
MAX_BYTES = 4096
MAX_FRESH_SECONDS = 45
MAX_CALL_SECONDS = 24 * 60 * 60
HEX32 = re.compile(r"^[a-f0-9]{32}$")
HEX64 = re.compile(r"^[a-f0-9]{64}$")


def unknown(reason: str) -> dict[str, Any]:
    return {
        "scope": "CANONICAL_PROVIDER_CALL_WINDOW_READ_ONLY",
        "read_only": True, "status": "UNKNOWN", "reason": reason,
        "verified_current_frames": [], "verified_current_image_attempts": [],
        "provider_call_verified": False, "kernel_lock_verified": False,
        "task_id_verified": False, "stalled_verified": False,
        "observed_at": datetime.now(timezone.utc).isoformat(),
    }


def _read(ep: Path, rel: Path, bound: int) -> bytes | None:
    file = ep / rel
    if (file.is_symlink() or file.parent.is_symlink() or not file.is_file()
            or not file.resolve(strict=True).is_relative_to(ep)
            or not 0 < file.stat().st_size <= bound):
        return None
    raw = file.read_bytes()
    return raw if 0 < len(raw) <= bound else None


def _clock(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (ValueError, OverflowError):
        return None


def observe_provider_calls(
    episode: Path, mysql: Mapping[str, Any] | None, *,
    now: datetime | None = None,
) -> dict[str, Any]:
    ep = Path(episode).resolve()
    if not (isinstance(mysql, Mapping) and mysql.get("available") is True
            and mysql.get("database_identity_verified") is True
            and mysql.get("read_only_grants_verified") is True):
        return unknown("MYSQL_ATTEMPT_AUTHORITY_NOT_VERIFIED")
    if observe_writer_owner(ep).get("status") != "FRESH_PRODUCER_LOCK_CLAIM":
        return unknown("DRIVER_OWNER_NOT_VERIFIED")
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        return unknown("OBSERVER_CLOCK_INVALID")
    try:
        owner_raw = _read(ep, OWNER_REL, 2048)
        raw = _read(ep, REL, MAX_BYTES)
        if not raw or not owner_raw:
            return unknown("PROVIDER_OBSERVATION_MISSING")
        owner = json.loads(owner_raw)
        data = json.loads(raw)
        if not isinstance(owner, dict) or not isinstance(data, dict):
            return unknown("PROVIDER_OBSERVATION_INVALID")
        fingerprint = hashlib.sha256(str(ep).casefold().encode("utf-8")).hexdigest()
        if (owner.get("source") != "canonical_persistent_runner"
                or owner.get("status") != "HELD"
                or data.get("schema_version") != 1
                or data.get("source") != "canonical_gateway_provider_call"
                or data.get("status") != "ACTIVE"
                or not HEX64.fullmatch(str(data.get("episode_fingerprint", "")))
                or data.get("episode_fingerprint") != fingerprint
                or owner.get("episode_fingerprint") != fingerprint
                or not HEX32.fullmatch(str(data.get("owner_epoch", "")))
                or data.get("owner_epoch") != owner.get("epoch")
                or data.get("pid") != owner.get("pid")
                or data.get("process_created_at") != owner.get("process_created_at")):
            return unknown("PROVIDER_OWNER_EPOCH_MISMATCH")
        pid, created = data.get("pid"), data.get("process_created_at")
        if type(pid) is not int or pid <= 0 or type(created) not in (int, float):
            return unknown("PROVIDER_PROCESS_INVALID")
        freshness = _clock(data.get("heartbeat_at"))
        age = (clock - freshness).total_seconds() if freshness else -100
        if not -5 <= age <= MAX_FRESH_SECONDS:
            return unknown("PROVIDER_HEARTBEAT_STALE")
        if not _same_process(pid, created):
            return unknown("PROVIDER_PROCESS_EXITED")
        entries = data.get("inflight")
        if not isinstance(entries, list) or not 1 <= len(entries) <= 5:
            return unknown("NO_VERIFIED_PROVIDER_CALL")
        rows = mysql.get("generation_attempt_records")
        if not isinstance(rows, list):
            return unknown("GENERATION_ATTEMPT_ROWS_MISSING")
        authoritative = {
            (r.get("frame"), r.get("attempt_index"))
            for r in rows if isinstance(r, Mapping)
            and r.get("status") == "DISPATCH_COMMITTED"
            and r.get("terminal_recorded_at") is None
            and _clock(r.get("dispatch_recorded_at")) is not None
            and type(r.get("frame")) is int and type(r.get("attempt_index")) is int
        }
        verified = []
        seen = set()
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("phase") != "PROVIDER_CALL_ENTERED":
                return unknown("INVALID_CALL_SPAN")
            f, attempt = entry.get("frame"), entry.get("attempt_index")
            if type(f) is not int or type(attempt) is not int or not 1 <= f <= 20 or not 1 <= attempt <= 2:
                return unknown("INVALID_CALL_FRAME")
            span = entry.get("span")
            if not HEX32.fullmatch(str(span)):
                return unknown("INVALID_CALL_SPAN")
            start = _clock(entry.get("started_at"))
            elapsed = (clock - start).total_seconds() if start else -1
            if not -5 <= elapsed <= MAX_CALL_SECONDS:
                return unknown("CALL_CLOCK_INVALID")
            if (f, attempt) not in authoritative or (f, attempt) in seen:
                return unknown("GENERATION_ATTEMPT_DISPATCH_NOT_VERIFIED")
            seen.add((f, attempt))
            verified.append({
                "frame": f, "attempt_index": attempt,
                "provider_call_age_seconds": max(0, int(elapsed)),
            })
        if (_read(ep, OWNER_REL, 2048) != owner_raw
                or _read(ep, REL, MAX_BYTES) != raw):
            return unknown("PROVIDER_OBSERVATION_CHANGED_DURING_READ")
        return {
            **unknown(None), "status": "FRESH_PROVIDER_CALL_EVIDENCE",
            "reason": None, "verified_current_frames": sorted({v["frame"] for v in verified}),
            "verified_current_image_attempts": sorted(verified, key=lambda v: (v["frame"], v["attempt_index"])),
            "provider_call_verified": True,
        }
    except Exception:
        return unknown("PROVIDER_OBSERVATION_UNAVAILABLE")
