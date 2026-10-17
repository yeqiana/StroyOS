"""Typed Redis hot-state facade for Story OS Episode runtime projections.

Everything stored here is rebuildable.  Historical facts belong in MySQL.
"""
from __future__ import annotations

from dataclasses import dataclass


PREFIX = "STORYOS:EP"
LOCK_PREFIX = "STORYOS:LOCK:EP"


@dataclass(frozen=True)
class HotStateSpec:
    suffix: str
    ttl_seconds: int | None


SPECS = {
    "NEXT_ACTION": HotStateSpec("NEXT_ACTION", 900),
    # Driver epoch must outlive long blocking critic/model steps; its liveness is fenced by PID+beacon.
    # A fixed 180s TTL caused a live Driver to be reported as NEVER_STARTED during final review.
    "DRIVER_STATE": HotStateSpec("DRIVER_STATE", None),
    "DRIVER_HEARTBEAT": HotStateSpec("DRIVER_HEARTBEAT", 90),
    "CIRCUIT_BREAKER": HotStateSpec("CIRCUIT_BREAKER", 300),
    # In-flight scoped Codex task identity must outlive its remote runner request.
    # A fixed TTL (formerly 600s) expired while the User Runner was still busy,
    # preventing the next Driver from safely attaching to that paid request.
    # Only explicit completion/clear may remove it; stale identities are checked
    # against the runner + immutable result receipts before reuse.
    "INFLIGHT": HotStateSpec("INFLIGHT", None),
    "HOST_REQUEST_CURRENT": HotStateSpec("HOST_REQUEST_CURRENT", 900),
    # Pending production work is authoritative Redis hot-state. It must survive
    # idle review/approval windows; expiring the key silently drops queued frames.
    "QUEUE": HotStateSpec("QUEUE", None),
    "COUNTERS": HotStateSpec("COUNTERS", 600),
    "EFFECTIVE_CONFIG": HotStateSpec("EFFECTIVE_CONFIG", 3600),
    "RUNTIME_CAPABILITIES": HotStateSpec("RUNTIME_CAPABILITIES", 300),
    "RUNNER_STATE": HotStateSpec("RUNNER_STATE", 120),
    "RUNTIME_ROUTE": HotStateSpec("RUNTIME_ROUTE", 900),
    "RESUME_TOKEN": HotStateSpec("RESUME_TOKEN", 900),
    "RESUME_CAPSULE": HotStateSpec("RESUME_CAPSULE", 1800),
    "FAST_PATH": HotStateSpec("FAST_PATH", 900),
    "FULL_AUTO_STATUS": HotStateSpec("FULL_AUTO_STATUS", 900),
    "TRACE_CURRENT": HotStateSpec("TRACE_CURRENT", 300),
    "TRANSPORT_STATE": HotStateSpec("TRANSPORT_STATE", 300),
    "BATCH_CAPABILITY": HotStateSpec("BATCH_CAPABILITY", 3600),
    "CODEX_BATCH_CAPABILITY": HotStateSpec("CODEX_BATCH_CAPABILITY", 3600),
}


def episode_key(episode_id: str, kind: str) -> str:
    episode_id = str(episode_id or "").strip()
    kind = str(kind or "").strip().upper()
    if not episode_id:
        raise ValueError("episode_id is required")
    if kind not in SPECS:
        raise ValueError(f"unsupported hot-state kind: {kind}")
    return f"{PREFIX}:{episode_id}:{SPECS[kind].suffix}"


def lock_key(episode_id: str, scope: str) -> str:
    episode_id = str(episode_id or "").strip()
    scope = str(scope or "").strip().upper()
    if not episode_id or not scope:
        raise ValueError("episode_id and scope are required")
    return f"{LOCK_PREFIX}:{episode_id}:{scope}"


class EpisodeHotStateStore:
    """Small typed facade over RuntimeStateStore / RedisRuntimeStateStore."""

    def __init__(self, store):
        self.store = store

    def put(self, episode_id: str, kind: str, value, *, ttl_seconds: int | None = None) -> None:
        spec = SPECS[str(kind).upper()]
        self.store.set_state(
            episode_key(episode_id, kind),
            value,
            expire_seconds=spec.ttl_seconds if ttl_seconds is None else int(ttl_seconds),
        )

    def get(self, episode_id: str, kind: str):
        return self.store.get_state(episode_key(episode_id, kind))

    def delete(self, episode_id: str, kind: str) -> None:
        self.store.delete_state(episode_key(episode_id, kind))
