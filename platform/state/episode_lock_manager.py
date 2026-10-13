"""Atomic fenced Episode ownership. This is lease identity, NOT a monotonic fence.

Production writers must additionally validate their lease at each MySQL/Provider
authority boundary before distributed cross-host production is permitted.
"""
from __future__ import annotations

import uuid


class EpisodeLockManager:
    PREFIX = "storyos:lock:episode:"

    def __init__(self, store):
        self.store = store

    @classmethod
    def _key(cls, episode_id: str) -> str:
        if not isinstance(episode_id, str) or not episode_id.strip():
            raise ValueError("EPISODE_ID_REQUIRED")
        return f"{cls.PREFIX}{episode_id}"

    @staticmethod
    def _payload(episode_id: str, owner_id: str, token: str) -> dict:
        if not owner_id or not token:
            raise ValueError("OWNER_ID_AND_TOKEN_REQUIRED")
        return {"episode_id": episode_id, "owner_id": owner_id, "lease_token": token}

    def acquire_lease(self, episode_id: str, owner_id: str, *,
                      ttl_seconds: int = 60) -> str | None:
        """Fail closed if the backing store cannot perform atomic NX+TTL."""
        if not isinstance(ttl_seconds, int) or not 1 <= ttl_seconds <= 3600:
            raise ValueError("LEASE_TTL_INVALID")
        key = self._key(episode_id)
        token = uuid.uuid4().hex
        payload = self._payload(episode_id, owner_id, token)
        atomic = getattr(self.store, "set_if_absent", None)
        if not callable(atomic):
            return None
        try:
            return token if atomic(key, payload, expire_seconds=ttl_seconds) else None
        except Exception:
            return None

    def acquire(self, episode_id: str, owner_id: str) -> bool:
        """Legacy boolean admission; token-aware release requires acquire_lease."""
        return self.acquire_lease(episode_id, owner_id) is not None

    def renew(self, episode_id: str, owner_id: str, token: str, *,
              ttl_seconds: int = 60) -> bool:
        if not isinstance(ttl_seconds, int) or not 1 <= ttl_seconds <= 3600:
            return False
        atomic = getattr(self.store, "compare_and_expire", None)
        if not callable(atomic):
            return False
        try:
            return bool(atomic(self._key(episode_id),
                               self._payload(episode_id, owner_id, token),
                               expire_seconds=ttl_seconds))
        except Exception:
            # Redis timeout/connection errors are also non-authorizing.
            return False

    def release(self, episode_id: str, owner_id: str | None = None,
                token: str | None = None) -> bool:
        """Compare-and-delete; NEVER delete solely on the Episode key."""
        if not owner_id or not token:
            return False
        atomic = getattr(self.store, "compare_and_delete", None)
        if not callable(atomic):
            return False
        try:
            return bool(atomic(self._key(episode_id),
                               self._payload(episode_id, owner_id, token)))
        except Exception:
            return False
