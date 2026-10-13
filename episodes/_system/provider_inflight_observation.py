"""Best-effort provider-call telemetry ONLY inside an admitted single-node Driver.

Not a dispatch authority. Never grants leases, retries calls or reads provider
credentials. The existing gateway/fence remains the sole dispatch boundary.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import threading
import uuid

import logical_asset_identity
import runtime_atomic_store
import writer_owner_observation

REL = Path("meta/runtime/provider-inflight-observation.json")
MAX_INFLIGHT = 5
_GUARD = threading.RLock()
_SESSIONS: dict[str, dict] = {}


def _key(episode: Path) -> str:
    return str(Path(episode).resolve()).casefold()


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_owner(ep: Path, epoch: dict | None) -> bool:
    return bool(isinstance(epoch, dict)
                and epoch.get("pid") == os.getpid()
                and re.fullmatch(r"[a-f0-9]{32}", str(epoch.get("epoch", "")))
                and epoch.get("episode_fingerprint") == writer_owner_observation.episode_fingerprint(ep)
                and type(epoch.get("process_created_at")) in (int, float))


def _write(episode: Path, session: dict, status: str) -> bool:
    try:
        owner = session["owner"]
        runtime_atomic_store.atomic_write_json(Path(episode) / REL, {
            "schema_version": 1,
            "source": "canonical_gateway_provider_call",
            "status": status,
            "owner_epoch": owner["epoch"],
            "pid": owner["pid"],
            "process_created_at": owner["process_created_at"],
            "episode_fingerprint": owner["episode_fingerprint"],
            "heartbeat_at": _stamp(),
            "inflight": list(session["entries"].values())[:MAX_INFLIGHT] if status == "ACTIVE" else [],
        })
        return True
    except Exception:
        return False


def attach(episode: Path, epoch: dict | None) -> bool:
    """Only the Driver that acquired the normal OS lock calls this."""
    ep = Path(episode).resolve()
    if not _safe_owner(ep, epoch):
        return False
    with _GUARD:
        key = _key(ep)
        if key in _SESSIONS:
            return False
        _SESSIONS[key] = {"owner": dict(epoch), "entries": {}}
        return _write(ep, _SESSIONS[key], "ACTIVE")


def heartbeat(episode: Path, epoch: dict | None) -> bool:
    ep = Path(episode).resolve()
    with _GUARD:
        current = _SESSIONS.get(_key(ep))
        if not current or not _safe_owner(ep, epoch) or current["owner"]["epoch"] != epoch["epoch"]:
            return False
        return _write(ep, current, "ACTIVE")


def detach(episode: Path, epoch: dict | None) -> bool:
    ep = Path(episode).resolve()
    with _GUARD:
        key = _key(ep)
        current = _SESSIONS.get(key)
        if not current or not _safe_owner(ep, epoch) or current["owner"]["epoch"] != epoch["epoch"]:
            return False
        _SESSIONS.pop(key, None)
        current["entries"].clear()
        return _write(ep, current, "RELEASED")


def _frame(episode: Path, row: dict) -> dict | None:
    try:
        if str(row.get("episode_id")) != logical_asset_identity.episode_id(episode):
            return None
        key = str(row.get("logical_asset_key") or "")
        match = re.fullmatch(re.escape(logical_asset_identity.episode_id(episode)) + r"/frame-(\d{2})", key)
        if not match or not 1 <= int(match.group(1)) <= 20:
            return None
        attempt = row.get("attempt_index")
        if type(attempt) is not int or not 1 <= attempt <= 2:
            return None
        return {"frame": int(match.group(1)), "attempt_index": attempt}
    except Exception:
        return None


@contextmanager
def provider_span(episode: Path, committed: list[dict]):
    """Wrap precisely the irreversible call() edge; no async/thread API needed."""
    ep = Path(episode).resolve()
    items = [_frame(ep, x) for x in committed if isinstance(x, dict)]
    span_id = None
    if items and all(item is not None for item in items) and len(items) <= MAX_INFLIGHT:
        with _GUARD:
            session = _SESSIONS.get(_key(ep))
            if session and len(session["entries"]) + len(items) <= MAX_INFLIGHT:
                span_id = uuid.uuid4().hex
                for index, item in enumerate(items):
                    session["entries"][span_id + ":" + str(index)] = {
                        **item,
                        "span": span_id,
                        "started_at": _stamp(),
                        "phase": "PROVIDER_CALL_ENTERED",
                    }
                _write(ep, session, "ACTIVE")
    try:
        yield
    finally:
        if span_id is not None:
            with _GUARD:
                session = _SESSIONS.get(_key(ep))
                if session:
                    for key in [k for k in session["entries"] if k.startswith(span_id + ":")]:
                        session["entries"].pop(key, None)
                    _write(ep, session, "ACTIVE")
