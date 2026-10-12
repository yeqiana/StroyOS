"""R37 explicit read-only authority composition, never implicit production I/O.

This module accepts *already authorized and injected* readers. It creates no
Redis/MySQL connection, starts no Driver, acquires no capacity permit, and
cannot turn a GET into production execution. An opt-in is mandatory whenever
an actual source is present; partial Worker/Writer dependencies fail closed.
"""
from __future__ import annotations

from typing import Callable, Mapping, Any

from platform.operations.runtime_authority_evidence import (
    EpisodeStatusReader, RuntimeAuthorityEvidenceService,
)
from platform.operations.runtime_authority_readers import (
    AdvisoryCapacityReadOnlyReader, EpisodeRepository, MySqlAuthorityReadOnlyReaders,
    SqlReader,
)
from platform.operations.runtime_live_authority_readers import (
    EpisodeWorkerHeartbeatReadOnlyReader, EpisodeWriterFenceReadOnlyReader,
    RedisHeartbeatReader,
)


def build_runtime_authority_readonly(
    status_reader: EpisodeStatusReader,
    *,
    approve_external_reads: bool = False,
    mysql: SqlReader | None = None,
    episodes: EpisodeRepository | None = None,
    redis: RedisHeartbeatReader | None = None,
    driver_status: Callable[[str], Mapping[str, Any]] | None = None,
    owner_fence: Callable[[str], Mapping[str, Any]] | None = None,
    capacity_snapshot: Callable[[], Mapping[str, Any]] | None = None,
) -> RuntimeAuthorityEvidenceService:
    """Create a read-only projection using explicit, non-writable sources.

    A trusted API deployment must supply least-privileged SQL SELECT and Redis
    GET/PTTL credentials, not mutable clients as write-capable authority.
    These permissions cannot be proven solely through an injected Python
    object; production access is NOT enabled by this factory.
    """
    sources = (mysql, episodes, redis, driver_status, owner_fence, capacity_snapshot)
    configured = any(source is not None for source in sources)
    if approve_external_reads is not True:
        if configured:
            raise ValueError("RUNTIME_AUTHORITY_EXTERNAL_READS_NOT_APPROVED")
        return RuntimeAuthorityEvidenceService(status_reader)
    if (mysql is None) != (episodes is None):
        raise ValueError("RUNTIME_AUTHORITY_MYSQL_EPISODE_IDENTITY_REQUIRED")
    if redis is not None and (mysql is None or episodes is None):
        raise ValueError("RUNTIME_AUTHORITY_WORKER_TASK_LINEAGE_REQUIRED")
    if (driver_status is None) != (owner_fence is None):
        raise ValueError("RUNTIME_AUTHORITY_WRITER_FENCE_REQUIRED")
    if mysql is not None and not callable(getattr(mysql, "query_one", None)):
        raise ValueError("RUNTIME_AUTHORITY_MYSQL_SELECT_READER_REQUIRED")
    if episodes is not None and not callable(getattr(episodes, "unique_owner_by_namespace", None)):
        raise ValueError("RUNTIME_AUTHORITY_EPISODE_NAMESPACE_READER_REQUIRED")
    if redis is not None and (
        not callable(getattr(mysql, "query_all", None))
        or not callable(getattr(redis, "get", None))
        or not callable(getattr(redis, "pttl", None))
    ):
        raise ValueError("RUNTIME_AUTHORITY_WORKER_GET_PTTL_AND_TASK_SCAN_REQUIRED")
    if driver_status is not None and (
        not callable(driver_status) or not callable(owner_fence)
    ):
        raise ValueError("RUNTIME_AUTHORITY_WRITER_READER_REQUIRED")
    if capacity_snapshot is not None and not callable(capacity_snapshot):
        raise ValueError("RUNTIME_AUTHORITY_CAPACITY_READER_REQUIRED")

    readers: dict[str, Any] = {}
    if mysql is not None:
        scoped = MySqlAuthorityReadOnlyReaders(mysql, episodes)
        readers["task"] = scoped.task
        readers["attempt"] = scoped.attempt
        if redis is not None:
            readers["worker"] = EpisodeWorkerHeartbeatReadOnlyReader(scoped, redis)
    if driver_status is not None:
        readers["writer"] = EpisodeWriterFenceReadOnlyReader(driver_status, owner_fence)
    if capacity_snapshot is not None:
        readers["capacity"] = AdvisoryCapacityReadOnlyReader(capacity_snapshot)

    return RuntimeAuthorityEvidenceService(
        status_reader, authorized_readers=readers,
        permit_authority_reads=bool(readers),
    )
