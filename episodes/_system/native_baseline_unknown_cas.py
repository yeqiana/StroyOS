"""Strict native Frame 01 UNKNOWN reconciliation: provenance first, CAS second.

This module does not dispatch any image generation or perform pixel/visual review.
It is intentionally not wired into an automatic scheduler retry loop. A caller
must separately reconcile the existing Production Ledger/queue after an SQL CAS.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from PIL import Image, UnidentifiedImageError
import canvas_normalize

import codex_user_runner
import episode_state_persistence
import generation_attempt_authority as authority
import logical_asset_identity
import production_native_baseline_proof
import scheduler_core

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_REL = Path("meta/runtime/native-baseline-frame01-runner-artifact-reconciliation-evidence.json")
EXPECTED_REASON = "NATIVE_BASELINE_PIXEL_TOOL_PROOF_UNVERIFIED"
EXPECTED_EVIDENCE_KIND = "STORYOS_NATIVE_RUNNER_ARTIFACT_SHA_RECONCILIATION_EVIDENCE"
EXPECTED_EVIDENCE_STATUS = (
    "RUNNER_THREAD_ARTIFACT_BYTES_VERIFIED__GENERATION_ATTEMPT_OUTCOME_UNKNOWN_UNRESOLVED"
)
SHA64 = re.compile(r"[0-9a-f]{64}\Z")


class NativeReconciliationDenied(RuntimeError):
    """No mutation is permitted when any source or fence is ambiguous."""


def _deny(reason: str):
    raise NativeReconciliationDenied(reason)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _episode_file(ep: Path, relative: str, expected_parent: str) -> Path:
    if not isinstance(relative, str) or "\\" in relative or not relative:
        _deny("NATIVE_RECONCILIATION_PATH_INVALID")
    value = Path(relative)
    if value.is_absolute() or ".." in value.parts or value.parts[0] != expected_parent:
        _deny("NATIVE_RECONCILIATION_PATH_INVALID")
    path = (ep / value).resolve()
    if not path.is_relative_to(ep) or not path.is_file():
        _deny("NATIVE_RECONCILIATION_SOURCE_MISSING")
    return path


def verify_frame01_sources(ep: Path) -> dict:
    """Independent read-only check; no DB transaction, provider call or write."""
    ep = Path(ep).resolve()
    # Scope is intentionally one existing official production Episode.
    if (ep != (ROOT / "episodes/00_独立篇/06_五十亩山地之后_全新重制").resolve()
            or not ep.is_dir()):
        _deny("NATIVE_RECONCILIATION_EPISODE_SCOPE_INVALID")
    evidence_path = ep / EVIDENCE_REL
    if not evidence_path.is_file():
        _deny("NATIVE_RECONCILIATION_EVIDENCE_MISSING")
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    if not isinstance(evidence, dict):
        _deny("NATIVE_RECONCILIATION_EVIDENCE_INVALID")
    for key, expected in (
        ("schema_version", 1), ("episode_id", "00-06"), ("frame", 1),
        ("attempt_index", 1), ("kind", EXPECTED_EVIDENCE_KIND),
        ("status", EXPECTED_EVIDENCE_STATUS), ("transport", "native_codex"),
        ("model_execution_kind", "image"), ("codex_turn_completed", True),
        ("codex_jsonl_image_generation_call_count", 0),
        ("provider_model_attested", False), ("review_pass", False),
        ("attempt_authority_mutated", False),
    ):
        if evidence.get(key) != expected:
            _deny("NATIVE_RECONCILIATION_EVIDENCE_CONTRACT_DRIFT")
    for key in (
        "source_generated_png_sha256", "episode_raw_png_sha256",
        "normalized_png_sha256", "codex_log_sha256",
        "frame_contract_sha256", "prompt_package_sha256",
    ):
        if not SHA64.fullmatch(str(evidence.get(key) or "")):
            _deny("NATIVE_RECONCILIATION_SOURCE_SHA_INVALID")
    if evidence["source_generated_png_sha256"] != evidence["episode_raw_png_sha256"]:
        _deny("NATIVE_RECONCILIATION_RAW_SOURCE_MISMATCH")
    request_id = evidence.get("native_runner_request_id")
    if not re.fullmatch(r"[0-9a-f]{32}", str(request_id or "")):
        _deny("NATIVE_RECONCILIATION_REQUEST_ID_INVALID")
    raw = _episode_file(ep, evidence.get("episode_raw_png_relative_path"), "media")
    if raw.parent != (ep / "media/raw").resolve():
        _deny("NATIVE_RECONCILIATION_RAW_PATH_INVALID")
    if raw.stat().st_size != evidence.get("source_generated_png_bytes"):
        _deny("NATIVE_RECONCILIATION_RAW_SIZE_DRIFT")
    candidate = _episode_file(ep, evidence.get("normalized_png_relative_path"), "media")
    if raw == candidate or _sha(raw) != evidence["episode_raw_png_sha256"]:
        _deny("NATIVE_RECONCILIATION_RAW_SHA_DRIFT")
    if _sha(candidate) != evidence["normalized_png_sha256"]:
        _deny("NATIVE_RECONCILIATION_CANDIDATE_SHA_DRIFT")
    if raw.suffix.lower() != ".png" or candidate.suffix.lower() != ".png":
        _deny("NATIVE_RECONCILIATION_PIXEL_FORMAT_INVALID")
    try:
        for image_path in (raw, candidate):
            with Image.open(image_path) as pixel:
                if pixel.format != "PNG":
                    _deny("NATIVE_RECONCILIATION_PIXEL_FORMAT_INVALID")
                pixel.verify()
        with Image.open(candidate) as pixel:
            actual_size = pixel.size
        width, height, _aspect = canvas_normalize.read_canvas(ep)
        if actual_size != (width, height):
            _deny("NATIVE_RECONCILIATION_CANVAS_MISMATCH")
    except (OSError, ValueError, UnidentifiedImageError):
        _deny("NATIVE_RECONCILIATION_PIXEL_DECODE_INVALID")

    rows = (scheduler_core.load_queue(ep) or {}).get("items") or []
    if len(rows) != 4:
        _deny("NATIVE_RECONCILIATION_VISUAL_LOCK_QUEUE_DRIFT")
    by_frame = {int(row.get("frame") or 0): row for row in rows}
    if set(by_frame) != {1, 8, 16, 17}:
        _deny("NATIVE_RECONCILIATION_VISUAL_LOCK_QUEUE_DRIFT")
    item = by_frame[1]
    package = item.get("prompt_package") or {}
    if (evidence.get("normalized_png_relative_path") !=
            f"media/candidates/scheduled/01-{item.get('id')}-a1.png"
            or not raw.name.startswith("01-")):
        _deny("NATIVE_RECONCILIATION_CANDIDATE_IDENTITY_INVALID")
    if (item.get("id") != evidence.get("queue_item_id")
            or item.get("status") != "external_blocked"
            or item.get("scope") != "visual_lock"
            or item.get("kind") != "original"
            or package.get("frame_contract_sha256") != evidence["frame_contract_sha256"]
            or package.get("package_sha256") != evidence["prompt_package_sha256"]):
        _deny("NATIVE_RECONCILIATION_QUEUE_CONTRACT_DRIFT")
    if any(by_frame[frame].get("status") != "queued"
           or list(by_frame[frame].get("depends_on") or []) != [1]
           for frame in (8, 16, 17)):
        _deny("NATIVE_RECONCILIATION_DEPENDENT_FRAME_STARTED")
    if (episode_state_persistence.load(ep) or {}).get("current_state") != "STORYBOARD_LOCKED":
        _deny("NATIVE_RECONCILIATION_STAGE_CHANGED")

    # The source must be the user Runner's durable request, not JSON passed
    # by a caller and not a cached prose summary of a Codex execution.
    runner_result = codex_user_runner.read_task_result(request_id)
    codex_home, _ = codex_user_runner.codex_home()
    log = ep / "meta/image-workers" / f"01-{item['id']}-a1.jsonl"
    if not log.is_file() or _sha(log) != evidence["codex_log_sha256"]:
        _deny("NATIVE_RECONCILIATION_CODEX_LOG_DRIFT")
    proof = production_native_baseline_proof.verify_runner_scoped_generated_image(
        runner_result=runner_result, runner_request_id=request_id,
        codex_log=log, raw_pixel=raw, trusted_codex_home=codex_home,
    )
    if (not proof or proof.get("proof_kind") !=
            "TRUSTED_NATIVE_RUNNER_THREAD_SCOPED_IMAGE_SHA"
            or proof.get("native_codex_thread_id") != evidence.get("thread_id")
            or proof.get("exported_artifact_relative_path") != evidence.get("generated_artifact_relative_path")
            or proof.get("raw_png_sha256") != evidence["episode_raw_png_sha256"]
            or proof.get("source_png_sha256") != evidence["source_generated_png_sha256"]
            or proof.get("native_codex_log_sha256") != evidence["codex_log_sha256"]
            or proof.get("runner_request_id") != request_id
            or proof.get("native_image_generation_jsonl_events") != 0
            or proof.get("provider_model_attested") is not False
            or proof.get("review_pass") is not False):
        _deny("NATIVE_RECONCILIATION_RUNNER_PROVENANCE_INVALID")
    return {
        "episode": ep, "evidence_sha256": _sha(evidence_path),
        "generation_key": evidence["generation_key"],
        "queue_item_id": item["id"], "raw_sha256": evidence["episode_raw_png_sha256"],
        "candidate": candidate, "candidate_sha256": evidence["normalized_png_sha256"],
        "frame_contract_sha256": evidence["frame_contract_sha256"],
        "prompt_package_sha256": evidence["prompt_package_sha256"],
        "runner_request_id": request_id, "native_codex_thread_id": evidence["thread_id"],
        "review_pass": False, "ledger_reconciled": False,
    }


def reconcile_frame01_unknown(ep: Path, *, expected_fencing_token: int,
                              expected_evidence_sha256: str) -> dict:
    """Single-purpose MySQL CAS; original Attempt #1 remains consumed.

    Caller must separately invoke the validated Ledger/queue recovery path.
    Retried calls are idempotent only if the exact verified result still matches.
    No review status, episode stage, image budget or queue state is modified.
    """
    verified = verify_frame01_sources(ep)
    if (not SHA64.fullmatch(str(expected_evidence_sha256 or ""))
            or verified["evidence_sha256"] != expected_evidence_sha256
            or int(expected_fencing_token) < 1):
        _deny("NATIVE_RECONCILIATION_PROOF_OR_FENCE_MISMATCH")
    ep = verified["episode"]
    episode_id = logical_asset_identity.episode_id(ep)
    key = authority.frame_key(ep, 1)
    generation_key = verified["generation_key"]
    if generation_key != authority.stable_generation_key(episode_id, key, 1):
        _deny("NATIVE_RECONCILIATION_GENERATION_KEY_MISMATCH")
    candidate_ref = str(verified["candidate"])
    connection = authority._connect()
    try:
        with connection.transaction():
            state = authority._row(connection, episode_id, key)
            row = connection.query_one(
                "SELECT * FROM TB_GENERATION_ATTEMPT WHERE EPISODE_ID=%s "
                "AND LOGICAL_ASSET_KEY=%s AND ATTEMPT_INDEX=1 FOR UPDATE",
                (episode_id, key),
            )
            if (not state or not row
                    or int(state.get("ATTEMPTS_CONSUMED") or 0) != 1
                    or state.get("ACTIVE_ATTEMPT_INDEX") is not None
                    or int(state.get("FENCING_COUNTER") or 0) != expected_fencing_token
                    or int(row.get("FENCING_TOKEN") or 0) != expected_fencing_token
                    or row.get("GENERATION_KEY") != generation_key
                    or not row.get("DISPATCH_COMMITTED_AT")):
                _deny("NATIVE_RECONCILIATION_STALE_ATTEMPT_FENCE")
            context = authority._context(row)
            if (context.get("scope") != "visual_lock"
                    or context.get("queue_item_id") != verified["queue_item_id"]
                    or context.get("visual_lock_frame") != 1
                    or context.get("tool_capability_claim") != "UNKNOWN_NOT_YET_PROVEN"
                    or context.get("image_capability_proof_purpose") != production_native_baseline_proof.REASON
                    or context.get("frame_contract_sha256") != verified["frame_contract_sha256"]
                    or context.get("prompt_package_sha256") != verified["prompt_package_sha256"]
                    or context.get("controller_effort") != "high"
                    or not SHA64.fullmatch(str(row.get("MODEL_POLICY_SHA256") or ""))
                    or context.get("model_policy_sha256") != row.get("MODEL_POLICY_SHA256")
                    or row.get("CONTROLLER_MODEL") != "gpt-6-luna"
                    or row.get("PAYLOAD_MODEL") != "gpt-image-2.5-flare"
                    or row.get("PAYLOAD_QUALITY") != "high"
                    or row.get("PROVIDER") != "codex_subscription"):
                _deny("NATIVE_RECONCILIATION_ATTEMPT_CONTEXT_DRIFT")
            if row.get("STATUS") == "SUCCEEDED":
                if row.get("RESULT_REF") != candidate_ref:
                    _deny("NATIVE_RECONCILIATION_SUCCEEDED_RESULT_DRIFT")
                return {**verified, "status": "SUCCEEDED", "idempotent": True,
                        "attempt_index": 1, "fencing_token": expected_fencing_token}
            if (row.get("STATUS") != "OUTCOME_UNKNOWN"
                    or row.get("FAILURE_CLASS") != EXPECTED_REASON
                    or row.get("RESULT_REF") not in (None, "")):
                _deny("NATIVE_RECONCILIATION_ATTEMPT_NOT_ELIGIBLE")
            # SQL CAS is the only mutation. Preserve the old failure class
            # for audit; provenance lives in the frozen Episode evidence.
            updated = connection.execute(
                "UPDATE TB_GENERATION_ATTEMPT SET STATUS='SUCCEEDED', "
                "GENERATION_OBSERVED_AT=COALESCE(GENERATION_OBSERVED_AT,%s), "
                "RESULT_REF=%s WHERE EPISODE_ID=%s AND LOGICAL_ASSET_KEY=%s "
                "AND ATTEMPT_INDEX=1 AND STATUS='OUTCOME_UNKNOWN' "
                "AND GENERATION_KEY=%s AND FENCING_TOKEN=%s "
                "AND FAILURE_CLASS=%s AND RESULT_REF IS NULL",
                (authority._utcnow(), candidate_ref, episode_id, key,
                 generation_key, expected_fencing_token, EXPECTED_REASON),
            )
            if updated != 1:
                _deny("NATIVE_RECONCILIATION_CAS_LOST")
        return {**verified, "status": "SUCCEEDED", "idempotent": False,
                "attempt_index": 1, "fencing_token": expected_fencing_token,
                "ledger_reconciled": False, "visual_review_pass": False}
    finally:
        connection.close()
