"""Persist EP14 three-frame render candidates without activating refused images.

MySQL stores all three under a separate IMAGE_RENDER_CANDIDATE namespace in
one transaction. Large payloads are immutable SHA-named Runtime artifacts.
The current IMAGE packages, queue, revision head and Attempts are untouched.
"""
from __future__ import annotations

import json
from pathlib import Path

import episode_identity
import production_ep14_render_queue_stage as queue_stage
import runtime_workspace
import scheduler_core
import storage_config
from platform.repository.mysql.payload_policy import (
    MAX_INLINE_PAYLOAD_BYTES, bounded_json, document_reference,
    payload_bytes, payload_sha256, prompt_package_projection,
)
from platform.repository.mysql.mysql_prompt_package_repository import (
    MySqlPromptPackageRepository, _package_id,
)
from platform.repository.mysql.mysql_connection import MySqlConnection
from platform.repository.mysql.schema_v2 import DATABASE_NAME

PACKAGE_TYPE = "IMAGE_RENDER_CANDIDATE"
STATUS = "THREE_FRAME_MYSQL_CANDIDATES_STAGED_NOT_ACTIVATED"


class CandidateDenied(ValueError):
    pass


def _episode_id(ep: Path) -> str:
    return episode_identity.storage_episode_id(Path(ep).resolve())


def _candidate_refs(ep: Path, q: dict) -> tuple[dict, list[dict]]:
    """Verify the whole live queue and three reviewed candidate packages."""
    marker = q.get(queue_stage.QUEUE_KEY)
    if (not isinstance(marker, dict)
            or marker.get("state") != "STAGED_BLOCKED"
            or marker.get("production_dispatch_authorized") is not False
            or marker.get("canonical_prompt_packages_activated") is not False):
        raise CandidateDenied("EP14_QUEUE_NOT_SAFELY_STAGED")
    rows = queue_stage._queue_rows(q)
    result = []
    for frame in sorted(queue_stage.FRAMES):
        row = rows[frame]
        source = queue_stage.preview_worker_source(ep, row)
        pkg = source.get("source") or {}
        if (source.get("stage_binding_sha256") != marker.get("binding_sha256")
                or source.get("bundle_sha256") != marker.get("bundle_sha256")
                or source.get("production_dispatch_authorized") is not False
                or pkg.get("canonical_activation") is not False
                or pkg.get("production_dispatch_authorized") is not False
                or pkg.get("canonical_prompt_package_written") is not False
                or pkg.get("storyboard_source", {}).get("render_original_text_injected") is not False
                or "text" in pkg.get("storyboard_source", {})
                or pkg.get("package_sha256") !=
                    source.get("package_sha256")):
            raise CandidateDenied(f"EP14_FRAME_{frame:02d}_CANDIDATE_NOT_CANONICAL_SAFE")
        result.append(pkg)
    if len(result) != 3 or [int(x["frame"]) for x in result] != [9, 29, 48]:
        raise CandidateDenied("EP14_THREE_FRAME_CANDIDATES_INCOMPLETE")
    return marker, result


def _candidate_plan(ep: Path, q: dict) -> dict:
    marker, packages = _candidate_refs(ep, q)
    episode_id = _episode_id(ep)
    records = []
    for pkg in packages:
        frame = int(pkg["frame"])
        sha = pkg["package_sha256"]
        if not queue_stage._is_sha(sha):
            raise CandidateDenied("EP14_CANDIDATE_SHA_INVALID")
        rel = f"meta/runtime/prompt-packages/candidates/{frame:02d}-{payload_sha256(pkg)}.json"
        ref = document_reference(pkg, rel)
        projected = prompt_package_projection(pkg, ref)
        # Keep the historical 16KiB inline limit by storing only a projection.
        bounded_json(projected, entity="EP14 render candidate projection")
        records.append({
            "frame": frame,
            "id": _package_id(episode_id, frame, PACKAGE_TYPE, sha),
            "sha": sha,
            "payload": pkg,
            "projection": projected,
            "reference": ref,
            "external_bytes": payload_bytes(pkg),
        })
    return {
        "schema": "ep14_mysql_render_candidate_stage_v1",
        "status": "READY_TO_PERSIST_NONCANONICAL_CANDIDATES",
        "expected_queue_sha256": queue_stage._sha(q),
        "stage_binding_sha256": marker["binding_sha256"],
        "bundle_sha256": marker["bundle_sha256"],
        "records": records,
        "production_dispatch_authorized": False,
        "mysql_writes": 0,
        "paid_attempts_reserved": 0,
    }


def plan(ep: Path) -> dict:
    ep = Path(ep).resolve()
    state = _candidate_plan(ep, scheduler_core.load_queue(ep))
    return {
        "status": state["status"],
        "expected_queue_sha256": state["expected_queue_sha256"],
        "stage_binding_sha256": state["stage_binding_sha256"],
        "bundle_sha256": state["bundle_sha256"],
        "candidate_ids": [r["id"] for r in state["records"]],
        "external_bytes": [r["external_bytes"] for r in state["records"]],
        "mysql_writes": 0,
        "production_dispatch_authorized": False,
    }


def _verify_row(repo: MySqlPromptPackageRepository, ep: Path, record: dict) -> None:
    row = repo.get_by_id(record["id"])
    if (not row
            or row.get("prompt_package_id") != record["id"]
            or row.get("episode_id") != _episode_id(ep)
            or int(row.get("frame_no") or 0) != record["frame"]
            or row.get("package_type") != PACKAGE_TYPE
            or row.get("sha256") != record["sha"]
            or row.get("payload") != record["projection"]):
        raise CandidateDenied("EP14_MYSQL_CANDIDATE_RECORD_MISSING_OR_DRIFTED")
    doc = row["payload"].get("document") or {}
    full = runtime_workspace.read_json(ep, doc.get("rel"), default=None)
    if (not isinstance(full, dict)
            or payload_sha256(full) != record["reference"]["sha256"]
            or full != record["payload"]):
        raise CandidateDenied("EP14_MYSQL_CANDIDATE_RUNTIME_DOCUMENT_DRIFT")


def _open_db():
    return MySqlConnection(**storage_config.mysql_connection_kwargs({"database": DATABASE_NAME}))


def persist(ep: Path, *, expected_queue_sha256: str,
            expected_bundle_sha256: str) -> dict:
    """CAS queue + one MySQL transaction across three candidates.

    Queue is NOT mutated here; MySQL/Redis atomicity is deliberately not
    asserted. A future activation must re-check both current authorities.
    """
    ep = Path(ep).resolve()
    if (not queue_stage._is_sha(expected_queue_sha256)
            or not queue_stage._is_sha(expected_bundle_sha256)):
        raise CandidateDenied("EP14_EXPLICIT_QUEUE_AND_BUNDLE_CAS_REQUIRED")
    with scheduler_core.queue_transaction(ep):
        q = scheduler_core.load_queue(ep)
        if queue_stage._sha(q) != expected_queue_sha256:
            raise CandidateDenied("EP14_CANDIDATE_QUEUE_CHANGED")
        state = _candidate_plan(ep, q)
        if state["bundle_sha256"] != expected_bundle_sha256:
            raise CandidateDenied("EP14_CANDIDATE_BUNDLE_CHANGED")
        # Immutable external source artifacts must exist before commit.
        # A failed DB transaction can leave harmless unreferenced files.
        for record in state["records"]:
            rel = record["reference"]["rel"]
            existing = runtime_workspace.read_json(ep, rel, default=None)
            if existing is not None and existing != record["payload"]:
                raise CandidateDenied("EP14_CANDIDATE_ARTIFACT_SHA_COLLISION")
            if existing is None:
                runtime_workspace.write_json(ep, rel, record["payload"])
            verified = runtime_workspace.read_json(ep, rel, default=None)
            if verified != record["payload"]:
                raise CandidateDenied("EP14_CANDIDATE_ARTIFACT_VERIFY_FAILED")

        connection = _open_db()
        try:
            with connection.transaction():
                repo = MySqlPromptPackageRepository(connection)
                for record in state["records"]:
                    # INSERT IGNORE + exact verification is immutable; never
                    # use upsert() which overwrites an existing SHA row.
                    connection.execute(
                        "INSERT IGNORE INTO TB_PROMPT_PACKAGE "
                        "(PROMPT_PACKAGE_ID,EPISODE_ID,FRAME_NO,PACKAGE_TYPE,SHA256,PAYLOAD) "
                        "VALUES (%s,%s,%s,%s,%s,%s)",
                        (record["id"], _episode_id(ep), record["frame"],
                         PACKAGE_TYPE, record["sha"],
                         bounded_json(record["projection"], entity="EP14 candidate")),
                    )
                    _verify_row(repo, ep, record)
                # No writes to TB_GENERATION_ATTEMPT or production Revision.
            if queue_stage._sha(scheduler_core.load_queue(ep)) != expected_queue_sha256:
                raise CandidateDenied("EP14_CANDIDATE_QUEUE_CHANGED_AFTER_COMMIT")
            return {
                "status": STATUS,
                "frames": [r["frame"] for r in state["records"]],
                "bundle_sha256": state["bundle_sha256"],
                "stage_binding_sha256": state["stage_binding_sha256"],
                "candidate_ids": [r["id"] for r in state["records"]],
                "canonical_render_activated": False,
                "production_dispatch_authorized": False,
                "paid_attempts_reserved": 0,
            }
        finally:
            connection.close()


def verify(ep: Path) -> dict:
    """Check the completed three-row MySQL bundle without writing anything."""
    ep = Path(ep).resolve()
    state = _candidate_plan(ep, scheduler_core.load_queue(ep))
    db = _open_db()
    try:
        repo = MySqlPromptPackageRepository(db)
        for record in state["records"]:
            _verify_row(repo, ep, record)
        return {
            "status": "VERIFIED_THREE_MYSQL_CANDIDATES_NOT_ACTIVATED",
            "frames": [r["frame"] for r in state["records"]],
            "bundle_sha256": state["bundle_sha256"],
            "production_dispatch_authorized": False,
            "mysql_writes": 0,
        }
    finally:
        db.close()
