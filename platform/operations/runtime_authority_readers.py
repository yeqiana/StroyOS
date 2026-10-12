"""Explicit opt-in, SELECT-only authority readers for the R35 evidence API.

These adapters never create MySQL/Redis connections. An authorized bootstrap
must inject an existing read-only MySQL connection and Episode repository.
Never register them in local file-mode or call them during provider dispatch.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Protocol

from platform.repository.mysql.schema_v2 import DATABASE_NAME
from platform.operations.runtime_authority_evidence import AUTHORITATIVE_SOURCES


class SqlReader(Protocol):
    def query_one(self, sql: str, params: tuple | None = None) -> dict | None: ...


class EpisodeRepository(Protocol):
    def unique_owner_by_namespace(self, episode_namespace: str) -> dict | None: ...


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _count(row: dict | None, column: str) -> int:
    if row is None:
        raise ValueError("AUTHORITY_COUNT_NOT_FOUND")
    raw = row.get(column)
    if type(raw) is int or (isinstance(raw, str) and raw.isdecimal()):
        count = int(raw)
        if 0 <= count <= 100000:
            return count
    raise ValueError("AUTHORITY_COUNT_INVALID")


class MySqlAuthorityReadOnlyReaders:
    """Read canonical MySQL Task/Attempt counts, not a legacy JSON projection.

    The caller must use a restricted SELECT-only DB account. Every access
    rechecks database identity, case mode and one unique Episode namespace
    owner before executing an Episode-ID-scoped SELECT.
    """

    def __init__(self, connection: SqlReader, episodes: EpisodeRepository) -> None:
        self.connection = connection
        self.episodes = episodes

    def _episode_id(self, episode_ref: str) -> str:
        identity = self.connection.query_one(
            "SELECT DATABASE() AS selected_database, @@lower_case_table_names AS case_mode"
        ) or {}
        if identity.get("selected_database") != DATABASE_NAME or identity.get("case_mode") != 0:
            raise ValueError("AUTHORITY_DATABASE_IDENTITY_UNVERIFIED")
        episode = self.episodes.unique_owner_by_namespace(episode_ref)
        if (not episode or str(episode.get("episode_namespace") or "") != episode_ref
                or str(episode.get("disposition") or "ACTIVE").upper() != "ACTIVE"):
            raise ValueError("AUTHORITY_EPISODE_NAMESPACE_UNVERIFIED")
        identifier = str(episode.get("episode_id") or "").strip()
        if not identifier or len(identifier) > 64:
            raise ValueError("AUTHORITY_EPISODE_ID_INVALID")
        return identifier

    def task(self, episode_ref: str) -> dict[str, Any]:
        episode_id = self._episode_id(episode_ref)
        row = self.connection.query_one(
            "SELECT COUNT(*) AS task_count FROM TB_TASK WHERE EPISODE_ID=%s",
            (episode_id,),
        )
        return {
            "episode_ref": episode_ref,
            "source": AUTHORITATIVE_SOURCES["task"],
            "verified": True, "read_only": True, "observed_at": _now(),
            "task_count": _count(row, "task_count"),
        }

    def attempt(self, episode_ref: str) -> dict[str, Any]:
        # The TB_TASK.EPISODE_ID is the storage UID, but the immutable image
        # Generation Attempt authority is keyed by the *Episode namespace*.
        # Still verify unique ACTIVE namespace ownership before querying it.
        self._episode_id(episode_ref)
        row = self.connection.query_one(
            "SELECT COUNT(*) AS attempt_count, "
            "SUM(CASE WHEN STATUS IN ('RESERVED','DISPATCH_COMMITTED','OUTCOME_UNKNOWN') "
            "THEN 1 ELSE 0 END) AS unresolved_count, "
            "SUM(CASE WHEN STATUS='OUTCOME_UNKNOWN' THEN 1 ELSE 0 END) AS unknown_count "
            "FROM TB_GENERATION_ATTEMPT WHERE EPISODE_ID=%s",
            (episode_ref,),
        )
        count = _count(row, "attempt_count")
        unresolved_count = _count(
            {**(row or {}), "unresolved_count": (row or {}).get("unresolved_count") or 0},
            "unresolved_count",
        )
        unknown_count = _count(
            {**(row or {}), "unknown_count": (row or {}).get("unknown_count") or 0},
            "unknown_count",
        )
        if not 0 <= unknown_count <= unresolved_count <= count:
            raise ValueError("AUTHORITY_ATTEMPT_STATE_COUNTS_INCONSISTENT")
        return {
            "episode_ref": episode_ref,
            "source": AUTHORITATIVE_SOURCES["attempt"],
            "verified": True, "read_only": True, "observed_at": _now(),
            "attempt_count": count, "unresolved": unresolved_count > 0,
            "unknown": unknown_count > 0,
        }


class AdvisoryCapacityReadOnlyReader:
    """Single-repo OS lock observation; never grants a capacity reservation."""

    def __init__(self, snapshot_fn: Callable[[], Mapping[str, Any]]) -> None:
        self._snapshot = snapshot_fn

    def __call__(self, episode_ref: str) -> dict[str, Any]:
        snapshot = self._snapshot()
        max_count = snapshot.get("global_max_inflight_images")
        busy, available = snapshot.get("observed_busy"), snapshot.get("observed_available")
        if (snapshot.get("scope") != "LOCAL_GIT_COMMON_DIRECTORY"
                or snapshot.get("advisory_snapshot_only") is not True
                or type(max_count) is not int or max_count != 5
                or type(busy) is not int or type(available) is not int
                or busy < 0 or available < 0 or busy + available != 5):
            raise ValueError("AUTHORITY_CAPACITY_SNAPSHOT_UNVERIFIED")
        return {
            "episode_ref": episode_ref,
            "source": AUTHORITATIVE_SOURCES["capacity"],
            "verified": True, "read_only": True, "observed_at": _now(),
            "observed_busy": busy, "observed_available": available,
            "advisory_snapshot_only": True,
        }
