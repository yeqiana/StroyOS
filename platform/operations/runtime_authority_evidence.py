"""Read-only Runtime authority evidence contract (R35).

There is deliberately NO default connection to MySQL, Redis, a production Driver
or a paid Provider. A caller must explicitly inject approved read adapters for
each domain. Local episode file projections never authorize these adapters.
The output describes provenance; it cannot grant any production action.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Protocol


class EpisodeStatusReader(Protocol):
    def get_episode_status(self, episode: str) -> dict[str, Any] | None: ...


EvidenceReader = Callable[[str], Mapping[str, Any] | None]
EVIDENCE_DOMAINS = ("task", "attempt", "worker", "writer", "capacity")
AUTHORITATIVE_SOURCES = {
    "task": "mysql_task_repository",
    "attempt": "mysql_generation_attempt_authority",
    "worker": "redis_worker_heartbeat",
    "writer": "runtime_driver_owner_fence",
    "capacity": "git_common_directory_os_permits",
}
_LOCAL_SOURCES = frozenset({"local_workspace_episode_state_file", "isolated-test"})
_MAX_INFLIGHT_IMAGES = 5


def _evidence_unavailable(reason: str) -> dict[str, Any]:
    return {"status": "UNAVAILABLE", "reason": reason, "observed_at": None,
            "source": None, "read_only": True}


class RuntimeAuthorityEvidenceService:
    """Fail-closed projection with opt-in authority readers.

    Reader output must match the requested Episode identity exactly. Readers
    are never invoked in local-file mode, or unless *explicitly* enabled by
    an authorized application composition root. All output fields are
    allowlisted to avoid exposing DSNs, lease secrets, or arbitrary payloads.
    """

    def __init__(
        self,
        status_reader: EpisodeStatusReader,
        *,
        authorized_readers: Mapping[str, EvidenceReader] | None = None,
        permit_authority_reads: bool = False,
    ) -> None:
        self._status_reader = status_reader
        self._readers = dict(authorized_readers or {})
        if set(self._readers).difference(EVIDENCE_DOMAINS):
            raise ValueError("UNKNOWN_RUNTIME_EVIDENCE_READER")
        self._permitted = permit_authority_reads is True

    def get_episode_authority(self, episode: str) -> dict[str, Any] | None:
        expected = str(episode or "").strip()
        if not expected or len(expected) > 256:
            raise ValueError("episode must be a non-empty bounded identity")
        detail = self._status_reader.get_episode_status(expected)
        if detail is None:
            return None
        if not isinstance(detail, dict) or str(detail.get("episode_ref") or "") != expected:
            # A stale / cross-Episode projector must not be enriched with
            # unrelated MySQL Task, Attempt or Redis heartbeat data.
            raise ValueError("RUNTIME_AUTHORITY_EPISODE_IDENTITY_MISMATCH")
        state_source = str(detail.get("state_source") or "")
        local = state_source in _LOCAL_SOURCES
        mode = ("LOCAL_READ_ONLY_EVIDENCE" if local else
                "AUTHORIZED_READ_ONLY" if self._permitted else
                "AUTHORITY_NOT_CONFIGURED")
        result: dict[str, Any] = {
            "schema_version": 1,
            "episode_ref": expected,
            "stage_source": state_source or None,
            "scope": mode,
            "read_only": True,
            "production_authorization": False,
            "can_start": False,
            "can_retry": False,
            "can_publish": False,
            "model_calls": 0,
            "global_image_capacity_policy": _MAX_INFLIGHT_IMAGES,
            "evidence": {},
        }
        for name in EVIDENCE_DOMAINS:
            if local:
                result["evidence"][name] = _evidence_unavailable("LOCAL_STAGE_ONLY")
            elif not self._permitted or name not in self._readers:
                result["evidence"][name] = _evidence_unavailable("AUTHORITY_READER_NOT_CONFIGURED")
            else:
                result["evidence"][name] = self._inspect(name, expected)
        return result

    def _inspect(self, name: str, episode_ref: str) -> dict[str, Any]:
        try:
            observed = self._readers[name](episode_ref)
            if not isinstance(observed, Mapping):
                return _evidence_unavailable("AUTHORITY_RECORD_MISSING")
            if str(observed.get("episode_ref") or "") != episode_ref:
                return _evidence_unavailable("AUTHORITY_RECORD_IDENTITY_MISMATCH")
            if observed.get("source") != AUTHORITATIVE_SOURCES[name]:
                return _evidence_unavailable("AUTHORITY_SOURCE_UNVERIFIED")
            if observed.get("verified") is not True or observed.get("read_only") is not True:
                return _evidence_unavailable("AUTHORITY_PROOF_INCOMPLETE")
            observed_at = str(observed.get("observed_at") or "")
            try:
                timestamp = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
                if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                    raise ValueError("timezone missing")
                if abs((datetime.now(timezone.utc) - timestamp.astimezone(timezone.utc)).total_seconds()) > 120:
                    return _evidence_unavailable("AUTHORITY_OBSERVATION_STALE")
            except (ValueError, TypeError, OverflowError):
                return _evidence_unavailable("AUTHORITY_OBSERVATION_TIME_INVALID")

            # A reader returning a valid envelope cannot assert that a Worker
            # heartbeat or Writer fence was verified unless that exact proof
            # bit is true. A PID, cached Worker row, or owner record alone
            # must never be presented as an authoritative live signal.
            if name == "worker" and observed.get("heartbeat_verified") is not True:
                return _evidence_unavailable("WORKER_HEARTBEAT_UNVERIFIED")
            if name == "writer" and observed.get("owner_fence_verified") is not True:
                return _evidence_unavailable("WRITER_FENCE_UNVERIFIED")
            # Policy-only advisory OS capacity is never a production permit.
            proof_status = "ADVISORY_ONLY" if name == "capacity" else "READ_ONLY_VERIFIED"
            item: dict[str, Any] = {
                "status": proof_status,
                "source": AUTHORITATIVE_SOURCES[name],
                "observed_at": timestamp.astimezone(timezone.utc).isoformat(),
                "read_only": True,
            }
            if name == "task":
                count = observed.get("task_count")
                if type(count) is int and 0 <= count <= 100000:
                    item["task_count"] = count
            elif name == "attempt":
                count = observed.get("attempt_count")
                if type(count) is int and 0 <= count <= 100000:
                    item["attempt_count"] = count
                if observed.get("unresolved") is True:
                    item["unresolved"] = True
                if observed.get("unknown") is True:
                    item["unknown"] = True
            elif name == "worker":
                item["heartbeat_verified"] = observed.get("heartbeat_verified") is True
            elif name == "writer":
                item["owner_fence_verified"] = observed.get("owner_fence_verified") is True
            elif name == "capacity":
                busy, available = observed.get("observed_busy"), observed.get("observed_available")
                if (type(busy) is int and type(available) is int and
                        0 <= busy <= _MAX_INFLIGHT_IMAGES and
                        available == _MAX_INFLIGHT_IMAGES - busy):
                    item.update({"observed_busy": busy, "observed_available": available})
                item["advisory_snapshot_only"] = True
            return item
        except Exception as exc:
            return {"status": "UNAVAILABLE", "reason": "AUTHORITY_READER_FAILED",
                    "error_type": type(exc).__name__, "observed_at": None,
                    "source": None, "read_only": True}
