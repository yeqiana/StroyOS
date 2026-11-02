"""Recover EP14 reviewed F009 from the verified second native RAW, without image calls.

Only one SHA-pinned 1092x1440 Provider PNG and immutable MySQL Attempt #2 may
be reconciled. Fit inside the canonical 1080x1350 canvas with 28-pixel edge
extension, NEVER crop. This yields a candidate, NOT a passed pixel review.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

import generation_attempt_authority as authority
import image_unknown_raw_reconcile as unknown
import image_blocked_recovery as legacy
import logical_asset_identity as identity
import production_ep14_canonical_activation as activation
import production_ledger
import production_recovery
import provider_capability
import provider_receipt_persistence as receipts
import scheduler_core
import canvas_normalize

RAW_SHA = "298e2b45253d447f7e49856bf310c64775db8fbd9131db3cc1d28c719d72ae9f"
FRAME = 9
PILOT_ITEM_ID = "8eefd4854826"
RAW_SIZE = (1092, 1440)
CANVAS_SIZE = (1080, 1350)
POLICY = "NP01_EP14_F009_EXACT_SHA_NONCROP_EDGE_FILL"
EPISODE_NAME = "14_深渊疗愈所_第一集_净土生命还原"


class RecoveryDenied(RuntimeError):
    pass


def _deny(reason):
    raise RecoveryDenied(reason)


def _episode(ep):
    ep = Path(ep).resolve()
    if ep.parent.name != "00_独立篇" or ep.name != EPISODE_NAME:
        _deny("EP14_F009_EPISODE_IDENTITY_REQUIRED")
    return ep


def _row(ep):
    q = scheduler_core.load_queue(ep)
    selected = [x for x in q.get("items", [])
                if x.get("scope") == "batch" and x.get("kind") == "repair"
                and int(x.get("frame") or 0) == FRAME]
    held = [x for x in q.get("items", [])
            if x.get("scope") == "batch" and x.get("kind") == "repair"
            and int(x.get("frame") or 0) in (29, 48)]
    if (len(selected) != 1 or selected[0].get("id") != PILOT_ITEM_ID
            or selected[0].get("status") != "external_blocked"
            or selected[0].get("technical_failure_code") != "ASPECT_RATIO_MISMATCH"
            or len(held) != 2
            or {int(x["frame"]) for x in held} != {29, 48}
            or any(x.get("status") != "pilot_hold" for x in held)):
        _deny("EP14_F009_EXACT_UNKNOWN_ATTEMPT_AND_PILOT_HOLD_REQUIRED")
    item = selected[0]
    if "ASPECT_RATIO_MISMATCH" not in str(item.get("last_error") or ""):
        _deny("EP14_F009_PROVIDER_RATIO_ERROR_NOT_PRESENT")
    try:
        package = activation.load_for_dispatch(ep, item, for_raw_recovery=True)
    except (activation.ActivationDenied, KeyError, ValueError) as exc:
        raise RecoveryDenied("EP14_F009_FINAL_RENDER_ACTIVE_MYSQL_SHA_NOT_VERIFIED") from exc
    if (package.get("independent_preimage_text_approved") is not True
            or package.get("postimage_pixel_review_required") is not True):
        _deny("EP14_F009_APPROVED_PREIMAGE_AND_POSTIMAGE_REVIEW_REQUIRED")
    return q, item, package


def inspect(ep):
    ep = _episode(ep)
    _, item, package = _row(ep)
    evidence = legacy.inspect_item(ep, item)
    if (evidence.get("auto_resolvable") is not True
            or evidence.get("code") != "ASPECT_RATIO_MISMATCH"
            or not 0.05 <= float(evidence.get("ratio_delta") or 0) <= 0.06):
        _deny("EP14_F009_PRESERVED_CANVAS_EXCEPTION_NOT_ELIGIBLE")
    raw = Path(evidence["raw_path"]).resolve()
    if (not raw.is_relative_to(ep) or not raw.is_file()
            or unknown.sha(raw) != RAW_SHA):
        _deny("EP14_F009_IMMUTABLE_PROVIDER_RAW_SHA_MISMATCH")
    with Image.open(raw) as im:
        if im.size != RAW_SIZE or im.format != "PNG":
            _deny("EP14_F009_EXACT_PRESERVED_RAW_FORMAT_SIZE_REQUIRED")
        im.verify()
    target = Path(evidence["output_path"]).resolve()
    if (target != (ep / "media/candidates/scheduled" /
                   f"09-{PILOT_ITEM_ID}-a2.png").resolve()
            or target.exists()):
        _deny("EP14_F009_CANDIDATE_MUST_BE_ABSENT")
    width, height, _ = canvas_normalize.read_canvas(ep)
    if (width, height) != CANVAS_SIZE:
        _deny("EP14_F009_CANONICAL_CANVAS_DRIFT")
    receipt_path, receipt, persisted = unknown._receipt(ep, item, evidence)
    attempt_key = identity.frame_asset_key(ep, FRAME)
    state = authority.load_asset_state(ep, attempt_key)
    first = authority.load_attempt(ep, attempt_key, 1) or {}
    second = authority.load_attempt(ep, attempt_key, 2) or {}
    generation_key = authority.stable_generation_key(
        identity.episode_id(ep), attempt_key, 2)
    if (first.get("status") != "FAILED_AFTER_DISPATCH"
            or first.get("failure_class") != "IMAGE_PROVIDER_SAFETY_REJECTED"
            or second.get("status") != "OUTCOME_UNKNOWN"
            or second.get("failure_class") != "generation_failed_before_candidate_commit"
            or second.get("provider") != "codex_subscription"
            or second.get("generation_key") != generation_key
            or second.get("result_ref") not in (None, "")
            or not second.get("dispatch_committed_at")
            or not second.get("generation_observed_at")
            or int(state.get("attempts_consumed") or 0) != 2
            or int(state.get("fencing_counter") or 0) != 2
            or state.get("active_attempt_index") is not None
            or receipt.get("generation_key") != generation_key
            or int(receipt.get("attempt_index") or 0) != 2
            or int(receipt.get("fencing_token") or 0) != 2
            or second.get("runner_request_id") != receipt.get("request_id")
            or receipt.get("generation_route") != "codex_subscription"
            or receipt.get("payload_model") != second.get("payload_model")
            or receipt.get("payload_quality") != second.get("payload_quality")
            or receipt.get("normalize_decision") != "ASPECT_RATIO_MISMATCH"
            or receipt.get("raw_sha256") != RAW_SHA
            or receipt.get("prompt_package_sha256") != package["package_sha256"]
            or receipt.get("frame_contract_sha256") != package["frame_contract_sha256"]
            or receipt.get("requested_canvas", {}).get("width") != CANVAS_SIZE[0]
            or receipt.get("requested_canvas", {}).get("height") != CANVAS_SIZE[1]
            or receipt.get("exact_raw_canvas_guaranteed") is not False
            or persisted.get("source") != "mysql"
            or not persisted.get("receipt_id")):
        _deny("EP14_F009_SECOND_ATTEMPT_MYSQL_RECEIPT_PROOF_INVALID")
    return {
        **evidence, "frame": FRAME, "item_id": item["id"],
        "scope": "batch", "raw_path": raw, "output_path": target,
        "receipt_path": receipt_path, "receipt_id": persisted["receipt_id"],
        "receipt_legacy_path": persisted["legacy_path"],
        "receipt_sha256": unknown._receipt_digest(receipt),
        "raw_sha256": RAW_SHA, "asset_key": attempt_key,
        "generation_key": generation_key, "attempt_index": 2,
        "frame_contract_sha256": receipt["frame_contract_sha256"],
        "prompt_package_sha256": receipt["prompt_package_sha256"],
        "result": "F009_VERIFIED_RAW_NONCROP_RECOVERY_ELIGIBLE",
        "image_calls": 0, "paid_attempts_reserved": 0,
        "postimage_pixel_review_required": True,
    }


def _normalize_no_crop(raw, output):
    """Aspect-preserving fit with replicated edge strips; never crops pixels."""
    raw = Path(raw)
    output = Path(output)
    if output.exists():
        _deny("EP14_F009_OUTPUT_ALREADY_EXISTS")
    if unknown.sha(raw) != RAW_SHA:
        _deny("EP14_F009_RAW_CHANGED_BEFORE_NORMALIZATION")
    with Image.open(raw) as image:
        if image.size != RAW_SIZE or image.format != "PNG":
            _deny("EP14_F009_UNEXPECTED_RAW_GEOMETRY")
        resized = image.convert("RGB").resize((1024, 1350), Image.Resampling.LANCZOS)
        out = Image.new("RGB", CANVAS_SIZE)
        out.paste(resized, (28, 0))
        out.paste(resized.crop((0, 0, 1, 1350)).resize((28, 1350)), (0, 0))
        out.paste(resized.crop((1023, 0, 1024, 1350)).resize((28, 1350)), (1052, 0))
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_name("." + output.name + ".noncrop-tmp")
    try:
        out.save(tmp, "PNG", optimize=True)
        tmp.replace(output)
    finally:
        if tmp.exists():
            tmp.unlink()
    return {
        "source_size": list(RAW_SIZE), "target_size": list(CANVAS_SIZE),
        "operation": "FIT_INSIDE_EDGE_EXTEND_NO_CROP",
        "scale_size": [1024, 1350],
        "padding": {"left": 28, "right": 28, "top": 0, "bottom": 0},
        "ratio_delta": 0.052083333,
        "crop_applied": False, "reencoded": True, "local_attempts": 1,
        "policy": POLICY, "postimage_pixel_review_required": True,
    }


def recover(ep):
    """No generation tool call. Exact MySQL UNKNOWN->SUCCEEDED CAS, then ledger+queue."""
    ep = _episode(ep)
    try:
        with scheduler_core.queue_transaction(ep):
            proof = inspect(ep)
            raw, target = Path(proof["raw_path"]), Path(proof["output_path"])
            operation = _normalize_no_crop(raw, target)
            with Image.open(target) as image:
                if image.size != CANVAS_SIZE or image.format != "PNG":
                    _deny("EP14_F009_NORMALIZED_FORMAT_OR_SIZE_INVALID")
                image.verify()
            digest = unknown.sha(target)
            provider_capability.finalize_receipt(proof["receipt_path"], operation, target)
            latest = receipts.load_by_path(ep, proof["receipt_path"])
            if (not latest or latest.get("source") != "mysql"
                    or latest.get("receipt_status") != "FINALIZED"
                    or latest.get("receipt_id") != proof["receipt_id"]):
                _deny("EP14_F009_FINAL_MYSQL_RECEIPT_NOT_COMMITTED")
            proof["receipt_sha256"] = unknown._receipt_digest(latest["payload"])
            unknown._mysql_reconcile(ep, proof, target, digest)
            production_ledger.cmd_recover_success(SimpleNamespace(
                episode_dir=str(ep), frame="09", path=str(target),
                provider_receipt=str(proof["receipt_path"]),
                transaction_id=str(proof["transaction_id"]),
                runner_request_id=None,
                recovery_reason="EP14_F009_VERIFIED_NONCROP_PROVIDER_RAW_ATTEMPT2",
            ))
            q = scheduler_core.load_queue(ep)
            selected = [x for x in q["items"] if x.get("id") == PILOT_ITEM_ID]
            if len(selected) != 1 or selected[0]["status"] != "external_blocked":
                _deny("EP14_F009_QUEUE_CHANGED_BEFORE_COMMIT")
            row = selected[0]
            row["status"] = "generated"
            row["output_path"] = target.resolve().relative_to(unknown.ROOT.resolve()).as_posix()
            row["last_error"] = None
            row["completed_at"] = production_recovery.now()
            row["attempt_index"] = 2
            row["generation_key"] = proof["generation_key"]
            row["normalization_recovery"] = {
                **operation,
                "kind": "EP14_F009_MYSQL_UNKNOWN_NONCROP_RECOVERY",
                "candidate_sha256": digest,
                "provider_receipt": str(proof["receipt_path"]),
                "pixel_review_completed": False,
            }
            row.pop("technical_failure_code", None)
            row.pop("external_block_reason", None)
            row.pop("retry_exhausted", None)
            production_recovery.mark_terminal(
                ep, row, "COMMITTED", recovery="EP14_F009_NONCROP_RAW_AFTER_UNKNOWN")
            scheduler_core.save_queue(ep, q)
            return {
                "status": "PASS", "frame": FRAME,
                "candidate_path": str(target),
                "candidate_sha256": digest, "crop_applied": False,
                "pixel_review_completed": False,
                "postimage_pixel_review_required": True,
                "image_calls": 0, "paid_attempts_reserved": 0,
            }
    except scheduler_core.QueueMutationBusy:
        return {"status": "BLOCKED", "reason": "QUEUE_MUTATION_BUSY"}
