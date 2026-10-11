"""Recover one native baseline Ledger document on the *same* MySQL transaction.

The caller holds the Generation Attempt state and row FOR UPDATE. The Ledger
authority BLOB and typed projection are written on that connection, never by
the ordinary ledger facade (which opens its own transaction).
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import episode_identity
import production_ledger_persistence as ledger_store
from platform.repository.mysql.mysql_production_attempt_repository import MySqlProductionAttemptRepository
from platform.repository.mysql.mysql_production_frame_repository import MySqlProductionFrameRepository
from platform.repository.mysql.mysql_production_ledger_authority_repository import MySqlProductionLedgerAuthorityRepository


class LedgerRecoveryDenied(RuntimeError):
    pass


def _core():
    # The facade must finish its bootstrap before the circular ledger modules
    # are accessed. Calling this only during recovery avoids partial imports.
    import production_ledger
    return production_ledger


def _deny(code: str):
    raise LedgerRecoveryDenied(code)


def _check_existing(document: dict, source: dict, *, completed: bool) -> dict:
    frames = document.get("frames") or {}
    frame = frames.get("01")
    if not isinstance(frame, dict) or len(frame.get("attempts") or []) != 1:
        _deny("NATIVE_RECONCILIATION_LEDGER_ATTEMPTS_DRIFT")
    attempt = frame["attempts"][-1]
    tx = str(source["runtime_transaction_id"])
    if (attempt.get("kind") != "original"
            or not attempt.get("attempt_id")
            or attempt.get("runtime_transaction_id") != tx
            or str((attempt.get("request") or {}).get("frame") or "") != "01"
            or (attempt.get("request") or {}).get("frame_contract_sha256") != source["frame_contract_sha256"]
            or (attempt.get("request") or {}).get("prompt_sha256") != source["scene_prompt_sha256"]
            or (attempt.get("request") or {}).get("model") != "gpt-image-2.5-flare"
            or (attempt.get("request") or {}).get("quality") != "high"
            or document.get("canvas", {}).get("width") != source["canvas_width"]
            or document.get("canvas", {}).get("height") != source["canvas_height"]):
        _deny("NATIVE_RECONCILIATION_LEDGER_CONTRACT_DRIFT")
    if completed:
        info = (frame.get("current_candidate") or {})
        correction = attempt.get("recovery_correction") or {}
        if (frame.get("status") != "ORIGINAL_READY"
                or attempt.get("result") != "success"
                or info.get("sha256") != source["candidate_sha256"]
                or info.get("path") != source["candidate_repo_rel"]
                or info.get("generation_key") != source["generation_key"]
                or info.get("generation_attempt_index") != 1
                or correction.get("proof_evidence_sha256") != source["evidence_sha256"]
                or correction.get("runtime_transaction_id") != tx
                or correction.get("runner_request_id") != source["runner_request_id"]
                or correction.get("previous_result") != "technical_failure"):
            _deny("NATIVE_RECONCILIATION_LEDGER_IDEMPOTENCY_DRIFT")
    else:
        error = attempt.get("error") or {}
        failures = frame.get("technical_failures") or []
        if (frame.get("status") != "TECH_FAILED"
                or attempt.get("result") != "technical_failure"
                or frame.get("current_candidate") is not None
                or "NATIVE_BASELINE_PIXEL_TOOL_PROOF_UNVERIFIED" not in str(error.get("message") or "")
                or error.get("code") != "IMAGE_BACKEND_ERROR"
                or not failures or failures[-1].get("attempt_id") != attempt["attempt_id"]
                or failures[-1].get("recovered_at")
                or (attempt.get("provider_attempt") or {}).get("status") != "NOT_INVOKED"):
            _deny("NATIVE_RECONCILIATION_LEDGER_FAILURE_DRIFT")
    return attempt


def corrected_ledger_document(document: dict, source: dict) -> dict:
    """Pure correction, preserving prior failure and audit fields."""
    out = deepcopy(document)
    att = _check_existing(out, source, completed=False)
    # Read-only provenance checks match the canonical Ledger success path.
    # Source contracts are checked before SQL CAS and cannot be weakened.
    core = _core()
    ep = Path(source["episode"])
    core.verify_attempt_visual_provenance(ep, att)
    core.verify_attempt_frame_contract_provenance(ep, "01", att)
    frame = out["frames"]["01"]
    now = core.now_iso()
    candidate = {
        "path": source["candidate_repo_rel"],
        "sha256": source["candidate_sha256"],
        "width": source["canvas_width"],
        "height": source["canvas_height"],
        "recorded_at": now,
        "kind": "original",
        "attempt_id": att["attempt_id"],
        "generation_key": source["generation_key"],
        "generation_attempt_index": 1,
    }
    old_error = deepcopy(att["error"])
    old_provider = deepcopy(att.get("provider_attempt") or {})
    att["recovery_correction"] = {
        "at": now,
        "previous_result": "technical_failure",
        "previous_error": old_error,
        "previous_provider_attempt": old_provider,
        "reason": "native_runner_thread_scoped_png_verified_after_unknown",
        "proof_evidence_sha256": source["evidence_sha256"],
        "raw_png_sha256": source["raw_sha256"],
        "normalized_png_sha256": source["candidate_sha256"],
        "generation_key": source["generation_key"],
        "attempt_index": 1,
        "runner_request_id": source["runner_request_id"],
        "runtime_transaction_id": source["runtime_transaction_id"],
        "provider_model_attested": False,
        "review_pass": False,
    }
    att["provider_attempt"] = {
        **old_provider, "status": "COMPLETED",
        "runner_request_id": source["runner_request_id"],
        "completed_at": now,
        "proof_kind": "TRUSTED_NATIVE_RUNNER_THREAD_SCOPED_IMAGE_SHA",
        "payload_model_attested": False,
        "native_image_generation_jsonl_events": 0,
    }
    att.pop("error", None)
    att["generation_key"] = source["generation_key"]
    att["generation_attempt_index"] = 1
    att["result"] = "success"
    att["completed_at"] = now
    att["candidate"] = candidate
    frame["current_candidate"] = candidate
    frame["status"] = "ORIGINAL_READY"
    frame["technical_failures"][-1]["recovered_at"] = now
    frame["technical_failures"][-1]["recovered_runner_request_id"] = source["runner_request_id"]
    out["updated_at"] = now
    _check_existing(out, source, completed=True)
    return out


def locked_ledger_update(connection, ep: Path, source: dict, *, already_succeeded: bool) -> bool:
    """Lock, cross-check, write BLOB and typed projections on the caller's TX."""
    if ledger_store.mode() != "mysql":
        _deny("NATIVE_RECONCILIATION_MYSQL_LEDGER_REQUIRED")
    storage_id = episode_identity.storage_episode_id(ep)
    lock = connection.query_one(
        "SELECT SHA256 FROM TB_PRODUCTION_LEDGER_AUTHORITY "
        "WHERE EPISODE_ID=%s FOR UPDATE", (storage_id,),
    )
    if not lock:
        _deny("NATIVE_RECONCILIATION_LEDGER_AUTHORITY_MISSING")
    repo = MySqlProductionLedgerAuthorityRepository(connection)
    existing = repo.get(storage_id)
    if not existing or existing.get("sha256") != lock.get("SHA256"):
        _deny("NATIVE_RECONCILIATION_LEDGER_AUTHORITY_SHA_DRIFT")
    document = existing["document"]
    if already_succeeded:
        _check_existing(document, source, completed=True)
        return False
    updated = corrected_ledger_document(document, source)
    repo.upsert(storage_id, updated)
    counts = ledger_store._persist_projection(
        storage_id, updated,
        MySqlProductionFrameRepository(connection),
        MySqlProductionAttemptRepository(connection),
        frame_keys={"01"},
    )
    if counts != (1, 1):
        _deny("NATIVE_RECONCILIATION_LEDGER_PROJECTION_FAILED")
    return True
