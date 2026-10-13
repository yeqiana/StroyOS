from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import episode_identity
import runtime_workspace
import storage_config
import story_json

from platform.repository.mysql.payload_policy import (
    MAX_INLINE_PAYLOAD_BYTES,
    document_reference,
    payload_bytes,
    payload_sha256,
)
from platform.repository.mysql.schema_v2 import DATABASE_NAME


DOC_ROOT = Path("meta/runtime/review-records")


def _mode() -> str:
    return storage_config.episode_meta_store_config()["mode"]


def _safe_type(review_type: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", str(review_type).strip())
    if not value:
        raise ValueError("review_type required")
    return value[:64]


def _repository():
    from platform.repository.mysql.mysql_connection import MySqlConnection
    from platform.repository.mysql.mysql_review_record_repository import (
        MySqlReviewRecordRepository,
    )

    connection = MySqlConnection(
        **storage_config.mysql_connection_kwargs({"database": DATABASE_NAME})
    )
    return connection, MySqlReviewRecordRepository(connection)


def _payload_content_sha(payload: dict) -> str:
    return payload_sha256(payload)


def _stored_content_sha(payload: dict) -> str:
    if payload.get("projection_type") == "EPISODE_REVIEW_REF":
        return str(payload.get("source_sha256") or "").lower()
    return payload_sha256(payload)


def _externalize(ep: Path, review_type: str, payload: dict) -> dict | None:
    if payload_bytes(payload) <= MAX_INLINE_PAYLOAD_BYTES:
        return None
    digest = payload_sha256(payload)
    rel = (DOC_ROOT / _safe_type(review_type) / f"{digest}.json").as_posix()
    ref = document_reference(payload, rel)
    path = runtime_workspace.write_json(ep, rel, payload)
    ref["bytes"] = path.stat().st_size
    return ref


def persist(
    ep: Path,
    review_type: str,
    payload: dict,
    *,
    decision: str,
    reviewer_type: str | None = None,
    source_sha256: str | None = None,
) -> dict:
    ep = Path(ep).resolve()
    mode = _mode()
    if mode == "json":
        return {"mode": mode, "mysql_written": False}
    if not isinstance(payload, dict):
        raise ValueError("review payload must be object")
    connection, repository = _repository()
    try:
        episode_id = episode_identity.storage_episode_id(ep)
        safe_type = _safe_type(review_type)
        latest = repository.get_latest(episode_id, safe_type)
        content_sha = _payload_content_sha(payload)
        latest_sha = (
            _stored_content_sha(latest["payload"])
            if latest and isinstance(latest.get("payload"), dict)
            else ""
        )
        attempt_no = (
            int(latest.get("attempt_no") or 1)
            if latest and latest_sha == content_sha
            else int((latest or {}).get("attempt_no") or 0) + 1
        )
        ref = _externalize(ep, safe_type, payload)
        saved = repository.upsert({
            "episode_id": episode_id,
            "review_type": safe_type,
            "attempt_no": attempt_no,
            "decision": str(decision),
            "source_sha256": source_sha256,
            "reviewer_type": reviewer_type,
            "payload": payload,
            "payload_ref": ref,
        })
        return {
            "mode": mode,
            "mysql_written": True,
            "document_ref": ref,
            "content_sha256": content_sha,
            **saved,
        }
    finally:
        connection.close()


def load_latest(
    ep: Path,
    review_type: str,
    *,
    legacy_path: str | Path | None = None,
) -> dict | None:
    ep = Path(ep).resolve()
    mode = _mode()
    if mode in {"dual", "mysql"}:
        connection = None
        try:
            connection, repository = _repository()
            row = repository.get_latest(
                episode_identity.storage_episode_id(ep),
                _safe_type(review_type),
            )
            if row and isinstance(row.get("payload"), dict):
                payload = row["payload"]
                document = (
                    payload.get("document")
                    if payload.get("projection_type") == "EPISODE_REVIEW_REF"
                    else None
                )
                if isinstance(document, dict):
                    full = runtime_workspace.read_json(
                        ep, document.get("rel"), default=None
                    )
                    if (
                        isinstance(full, dict)
                        and payload_sha256(full)
                        == str(document.get("sha256") or "").lower()
                    ):
                        return full
                else:
                    return payload
        except Exception:
            if mode == "mysql":
                raise
        finally:
            if connection is not None:
                connection.close()
        if mode == "mysql":
            return None

    if legacy_path is not None:
        path = Path(legacy_path)
        if path.is_file():
            data = story_json.read_json(path, default=None)
            return data if isinstance(data, dict) else None
    return None


def load_attempt(
    ep: Path,
    review_type: str,
    attempt_no: int,
    *,
    legacy_path: str | Path | None = None,
) -> dict | None:
    """Load an immutable historical review attempt without changing latest authority."""
    ep = Path(ep).resolve()
    mode = _mode()
    attempt_no = int(attempt_no)
    if attempt_no < 1:
        raise ValueError("attempt_no must be >= 1")
    if mode in {"dual", "mysql"}:
        connection = None
        try:
            connection, repository = _repository()
            row = next((item for item in repository.list_attempts(
                episode_identity.storage_episode_id(ep), _safe_type(review_type)
            ) if int(item.get("attempt_no") or 0) == attempt_no), None)
            if row and isinstance(row.get("payload"), dict):
                payload = row["payload"]
                document = (
                    payload.get("document")
                    if payload.get("projection_type") == "EPISODE_REVIEW_REF"
                    else None
                )
                if isinstance(document, dict):
                    full = runtime_workspace.read_json(ep, document.get("rel"), default=None)
                    if (isinstance(full, dict)
                            and payload_sha256(full) == str(document.get("sha256") or "").lower()):
                        return full
                    return None
                return payload
        except Exception:
            if mode == "mysql":
                raise
        finally:
            if connection is not None:
                connection.close()
        if mode == "mysql":
            return None
    if legacy_path is not None:
        path = Path(legacy_path)
        if path.is_file():
            data = story_json.read_json(path, default=None)
            provenance = (data or {}).get("critic_provenance") or {}
            return data if isinstance(data, dict) and provenance.get("attempt") == attempt_no else None
    return None


def authority_sha256(
    ep: Path,
    review_type: str,
    *,
    legacy_path: str | Path | None = None,
) -> str | None:
    payload = load_latest(ep, review_type, legacy_path=legacy_path)
    return payload_sha256(payload) if isinstance(payload, dict) else None


def materialize_export(
    ep: Path,
    review_type: str,
    *,
    payload: dict | None = None,
    filename: str | None = None,
) -> Path | None:
    ep = Path(ep).resolve()
    data = payload if isinstance(payload, dict) else load_latest(ep, review_type)
    if not isinstance(data, dict):
        return None
    name = filename or (_safe_type(review_type).lower() + ".json")
    target = ep / "meta" / "runtime" / "review-exports" / name
    story_json.write_json(target, data)
    return target


def save(
    ep: Path,
    review_type: str,
    legacy_rel: str | Path,
    payload: dict,
    *,
    decision: str,
    reviewer_type: str | None = None,
    source_sha256: str | None = None,
) -> dict:
    ep = Path(ep).resolve()
    mode = _mode()
    db = persist(
        ep,
        review_type,
        payload,
        decision=decision,
        reviewer_type=reviewer_type,
        source_sha256=source_sha256,
    )
    path = ep / Path(legacy_rel)
    if mode != "mysql":
        story_json.write_json(path, payload)
    return {"path": path, **db}
