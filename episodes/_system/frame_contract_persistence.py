from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import storage_config
import story_json
import episode_identity
import mysql_connection_cache
import runtime_workspace

from platform.repository.frame_contract_projection import (
    document_reference,
    json_sha256,
)


CONTRACT_DOCUMENT_ROOT = "meta/runtime/contracts/frames"


def _episode_id(ep: Path) -> str:
    return episode_identity.storage_episode_id(ep)


def _source_sha(row: dict) -> str | None:
    material = row.get("hash_material")
    if not isinstance(material, dict) or not material:
        return None
    payload = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def externalize(ep: Path, row: dict) -> dict:
    """Persist the full contract outside MySQL and return its bounded reference."""
    ref = document_reference_for(row)
    rel = ref["rel"]
    path = runtime_workspace.write_json(ep, rel, row)
    ref["bytes"] = path.stat().st_size
    return ref


def document_reference_for(row: dict, *, bytes_size: int = 0) -> dict:
    """Build the deterministic external reference without writing the document."""
    frame = int(row["frame"])
    document_sha = json_sha256(row)
    return {
        "rel": f"{CONTRACT_DOCUMENT_ROOT}/{frame:02d}-{document_sha}.json",
        "sha256": document_sha,
        "bytes": int(bytes_size),
    }


def persist(ep: Path, row: dict, *, status: str = "ACTIVE") -> dict:
    """Mirror a resolved Frame Contract when Episode metadata mode is ``dual``."""
    mode = storage_config.episode_meta_store_config()["mode"]
    if mode == "json":
        return {"mode": mode, "mysql_written": False}

    from platform.repository.mysql.mysql_frame_contract_repository import (
        MySqlFrameContractRepository,
    )
    from platform.repository.mysql.schema_v2 import DATABASE_NAME

    kwargs = storage_config.mysql_connection_kwargs({"database": DATABASE_NAME})
    # A reused connection, not a fresh TCP handshake per frame.  See
    # mysql_connection_cache.
    connection = mysql_connection_cache.shared_connection(kwargs)
    document_ref = externalize(Path(ep).resolve(), row)
    saved = MySqlFrameContractRepository(connection).save_version(
        {
            "episode_id": _episode_id(Path(ep).resolve()),
            "frame_no": int(row["frame"]),
            "status": status,
            "sha256": row["contract_sha256"],
            "source_sha256": _source_sha(row),
            "payload": row,
            "payload_ref": document_ref,
        }
    )
    return {"mode": mode, "mysql_written": True, "document_ref": document_ref, **saved}


def load_sha_bound_version(ep: Path, frame: int | str, contract_sha256: str) -> dict | None:
    """Fetch immutable historical contract bytes, not the latest mutable projection.

    A recorded pixel SHA must not be "repaired" by taking the latest source and
    replacing its SHA. Verify both the MySQL version and external document digest.
    """
    ep = Path(ep).resolve()
    sha = str(contract_sha256 or "").lower()
    if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
        return None
    if storage_config.episode_meta_store_config()["mode"] not in {"mysql", "dual"}:
        return None
    from platform.repository.mysql.schema_v2 import DATABASE_NAME
    connection = mysql_connection_cache.shared_connection(
        storage_config.mysql_connection_kwargs({"database": DATABASE_NAME}))
    row = connection.query_one(
        "SELECT SHA256,PAYLOAD FROM TB_FRAME_CONTRACT "
        "WHERE EPISODE_ID=%s AND FRAME_NO=%s AND SHA256=%s "
        "ORDER BY VERSION_NO DESC LIMIT 1",
        (_episode_id(ep), int(frame), sha))
    if not row or str(row.get("SHA256") or "").lower() != sha:
        return None
    projection = row.get("PAYLOAD")
    if isinstance(projection, str):
        projection = json.loads(projection)
    if not isinstance(projection, dict):
        return None
    ref = document_reference(projection)
    if ref:
        document = runtime_workspace.read_json(ep, ref.get("rel"), default=None)
        if (not isinstance(document, dict)
                or json_sha256(document) != str(ref.get("sha256") or "").lower()):
            return None
    else:
        document = projection
    if not isinstance(document.get("hash_material"), dict):
        return None
    if (str(document.get("contract_sha256") or "").lower() != sha
            or _source_sha(document) != sha):
        return None
    return document


def load_latest(ep: Path, frame: int | str, *, legacy_path: str | Path | None = None) -> dict | None:
    """Read latest Frame Contract from MySQL in dual/mysql mode, then JSON fallback."""
    ep = Path(ep).resolve()
    mode = storage_config.episode_meta_store_config()["mode"]
    if mode in {"dual", "mysql"}:
        from platform.repository.mysql.mysql_frame_contract_repository import (
            MySqlFrameContractRepository,
        )
        from platform.repository.mysql.schema_v2 import DATABASE_NAME

        kwargs = storage_config.mysql_connection_kwargs({"database": DATABASE_NAME})
        try:
            connection = mysql_connection_cache.shared_connection(kwargs)
            row = MySqlFrameContractRepository(connection).get_latest(_episode_id(ep), int(frame))
            if row and isinstance(row.get("payload"), dict):
                ref = document_reference(row["payload"])
                if ref:
                    document = runtime_workspace.read_json(ep, ref.get("rel"), default=None)
                    if (
                        isinstance(document, dict)
                        and json_sha256(document) == str(ref.get("sha256") or "").lower()
                        and str(document.get("contract_sha256") or "").lower()
                        == str(row.get("sha256") or "").lower()
                    ):
                        return document
                else:
                    return row["payload"]
        except Exception:
            # dual remains fail-soft; mysql is the durable authority and must not
            # silently resurrect compatibility JSON on repository failure.
            if mode == "mysql":
                raise
        if mode == "mysql":
            return None

    if legacy_path is None:
        legacy_path = ep / "meta/runtime/contracts/frames" / f"{int(frame):02d}.json"
    path = Path(legacy_path)
    if path.is_file():
        return story_json.read_json(path, default=None)
    return None
