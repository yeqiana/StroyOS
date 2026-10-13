"""Optional local telemetry emitted solely inside a Driver's acquired OS lock.

This is an observation, NOT a second Writer lease or a lock authority.
Failure to emit it must not interrupt normal production.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import uuid

import runtime_atomic_store

REL = Path("meta/runtime/writer-owner-observation.json")
SCHEMA = 1


def episode_fingerprint(episode: Path) -> str:
    return hashlib.sha256(str(Path(episode).resolve()).casefold().encode("utf-8")).hexdigest()


def new_epoch(episode: Path) -> dict | None:
    try:
        import psutil
        created = float(psutil.Process(os.getpid()).create_time())
        if created <= 0:
            return None
        return {
            "epoch": uuid.uuid4().hex,
            "pid": os.getpid(),
            "process_created_at": created,
            "episode_fingerprint": episode_fingerprint(episode),
        }
    except Exception:
        return None


def emit(episode: Path, epoch: dict | None, *, held: bool) -> bool:
    if not epoch:
        return False
    try:
        # Callers only publish HELD after runner_state_store.acquire_lock()
        # succeeded and publish RELEASED before releasing that OS lock.
        runtime_atomic_store.atomic_write_json(Path(episode) / REL, {
            "schema_version": SCHEMA,
            "source": "canonical_persistent_runner",
            "reported_lock": "meta/runtime-runner.lock",
            "status": "HELD" if held else "RELEASED",
            "epoch": epoch["epoch"],
            "pid": epoch["pid"],
            "process_created_at": epoch["process_created_at"],
            "episode_fingerprint": epoch["episode_fingerprint"],
            "heartbeat_at": datetime.now(timezone.utc).isoformat(),
        })
        return True
    except Exception:
        # Telemetry loss must never acquire/release the lock or fail production.
        return False
