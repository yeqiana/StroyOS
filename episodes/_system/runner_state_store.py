#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Story OS V2.7 runner lifecycle state storage.

Runtime lifecycle evidence only. It does not replace episode-state.json.
"""
from __future__ import annotations

import datetime as dt
import os
import threading
from pathlib import Path

import runtime_workspace
import hot_state_bridge

REL = Path("meta/runtime-runner-state.json")
LOCK_REL = Path("meta/runtime-runner.lock")
_HELD = {}
_GUARD = threading.RLock()


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def load(episode: Path) -> dict:
    hot = hot_state_bridge.read(episode, "RUNNER_STATE")
    data = hot_state_bridge.value_or_fallback(
        hot,
        lambda: runtime_workspace.read_json(episode, REL, default={}),
        default={},
    )
    return data if isinstance(data, dict) else {}


def save(episode: Path, **fields) -> dict:
    with _GUARD:
        current = load(episode)
        # A new RUNNING epoch must not inherit terminal diagnostics from the
        # previous process. Keeping rc/last_error while status=RUNNING made a
        # healthy recovered Driver look failed and alive at the same time.
        if fields.get("status") == "RUNNING":
            for stale in ("return_code", "last_error", "last_action", "error", "attempt", "cycles"):
                current.pop(stale, None)
        current.update(fields)
        current["heartbeat"] = _now()
        if hot_state_bridge.compatibility_write_allowed():
            runtime_workspace.write_json(episode, REL, current)
        hot_state_bridge.mirror(episode, "RUNNER_STATE", current)
        return current


def mark_running(episode: Path, **fields) -> dict:
    return save(episode, status="RUNNING", **fields)


def mark_completed(episode: Path, **fields) -> dict:
    return save(episode, status="COMPLETED", **fields)


def mark_failed(episode: Path, **fields) -> dict:
    return save(episode, status="FAILED", **fields)


def acquire_lock(episode: Path, *, lock_rel:Path=LOCK_REL) -> bool:
    """OS advisory lock: released by the kernel even after terminate/kill.

    Keep the lock inode on disk; deleting it allows two different inodes to be
    locked concurrently. The file's existence is never evidence of a live owner.
    """
    path = (episode / lock_rel).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _GUARD:
        if path in _HELD:
            return False
        handle = path.open("a+b")
        try:
            # Windows byte-range locking works beyond EOF. Never write to an
            # unlocked empty file: two freshly started local Drivers can race.
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        _HELD[path] = handle
        return True


def release_lock(episode: Path, *, lock_rel:Path=LOCK_REL) -> None:
    path = (episode / lock_rel).resolve()
    with _GUARD:
        handle = _HELD.pop(path, None)
        if handle is not None:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()
