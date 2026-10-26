#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Resolve non-regenerating image failures without silently generating again.

Only deterministic technical recovery lives here.  In particular, a provider
RAW whose requested canvas was correct but whose returned ratio falls inside
the explicitly configured provider-crop exception may be normalized from the
preserved RAW.  Content decisions remain with the normal pixel-review gates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from types import SimpleNamespace

import canvas_normalize
import frame_contract
import production_ledger
import production_queue_store
import production_recovery
import provider_capability
import provider_receipt_persistence
import raw_candidate_budget
import scheduler_core
import story_json

ROOT = Path(__file__).resolve().parents[2]
LEDGER_REL = Path("meta/production-ledger.json")
SUPPORTED_AUTO_CODES = {"ASPECT_RATIO_MISMATCH"}
# Missing native Codex image-tool capability is not a failed image generation.
NATIVE_IMAGE_CAPABILITY_CODES = frozenset({
    "CODEX_NATIVE_IMAGE_PROVIDER_REQUIRED",
    "LOGIN_AUTH_IMAGE_TOOL_CAPABILITY_UNKNOWN",
    "LOGIN_AUTH_IMAGE_TOOL_UNAVAILABLE_FOR_VISIBLE_MODELS",
    "LOGIN_AUTH_IMAGE_TOOL_CONFIG_UNAVAILABLE",
})


def _read(path: Path) -> dict:
    data = story_json.read_json(path, default={})
    return data if isinstance(data, dict) else {}


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _repo_path(raw: str) -> Path:
    path = Path(str(raw or ""))
    path = path.resolve() if path.is_absolute() else (ROOT / path).resolve()
    path.relative_to(ROOT.resolve())
    return path


def _receipt_from_error(ep: Path, item: dict, attempt: dict) -> Path | None:
    texts = [str(item.get("last_error") or ""), str(((attempt.get("error") or {}).get("message")) or "")]
    for text in texts:
        match = re.search(r"provider_receipt=([^;]+)", text)
        if not match:
            continue
        try:
            path = _repo_path(match.group(1).strip())
            path.relative_to(Path(ep).resolve())
        except (ValueError, OSError):
            continue
        # During JSON -> MySQL dual-write cutover the compatibility file may
        # already have been removed. Keep returning the validated in-Episode
        # path so provider_receipt_persistence can fall back to MySQL by the
        # recorded legacy path.
        return path
    return None


def _latest_attempt(ledger: dict, frame: int) -> dict:
    row = (ledger.get("frames") or {}).get(f"{int(frame):02d}") or {}
    attempts = row.get("attempts") or []
    return attempts[-1] if attempts and isinstance(attempts[-1], dict) else {}


def inspect_item(ep: Path, item: dict, *, exception_crop_ratio_max: float | None = None) -> dict:
    """Return a deterministic recovery plan for one unresolved blocked item."""
    ep = Path(ep).resolve()
    frame = int(item.get("frame") or 0)
    code = str(item.get("technical_failure_code") or "")
    base = {"frame": frame, "item_id": str(item.get("id") or ""), "code": code, "auto_resolvable": False}
    if code in NATIVE_IMAGE_CAPABILITY_CODES:
        return {
            **base,
            "reason": "native_codex_session_image_tool_attestation_missing",
            "recovery_action": "VERIFY_NATIVE_CODEX_IMAGE_CAPABILITY",
            "recovery_hint": "Confirm native Codex image tool in a real session or finish the fixed bounded Phase5A canary; preserve the queue item and Attempt until then",
        }
    if frame <= 0 or code not in SUPPORTED_AUTO_CODES:
        return {**base, "reason": "unsupported_non_regenerating_failure"}

    ledger = production_ledger.load_authority(ep, default={}) or {}
    attempt = _latest_attempt(ledger, frame)
    tx = str(((item.get("execution") or {}).get("transaction_id")) or "")
    if attempt.get("result") != "technical_failure" or not tx or str(attempt.get("runtime_transaction_id") or "") != tx:
        return {**base, "reason": "ledger_transaction_not_recoverable"}
    error = attempt.get("error") or {}
    if str(error.get("code") or "") != code:
        return {**base, "reason": "ledger_failure_code_mismatch"}

    current = frame_contract.compile_frame(ep, frame, write_cache=False)
    request = attempt.get("request") or {}
    recorded_contract = str(request.get("frame_contract_sha256") or "")
    if not recorded_contract or recorded_contract != str(current.get("contract_sha256") or ""):
        return {**base, "reason": "frame_contract_drift"}
    recorded_visual = request.get("visual_profile") or {}
    try:
        current_visual = production_ledger.current_visual_provenance(ep)
    except Exception:
        return {**base, "reason": "visual_profile_provenance_unavailable"}
    for key in ("profile_id", "profile_path", "profile_sha256", "capture_profile"):
        if str(recorded_visual.get(key) or "") != str(current_visual.get(key) or ""):
            return {**base, "reason": f"visual_profile_drift:{key}"}

    receipt_path = _receipt_from_error(ep, item, attempt)
    if receipt_path is None:
        return {**base, "reason": "provider_receipt_missing"}
    loaded_receipt = provider_receipt_persistence.load_by_path(ep, receipt_path)
    if not loaded_receipt:
        return {**base, "reason": "provider_receipt_missing"}
    receipt = loaded_receipt.get("payload") or {}
    if not isinstance(receipt, dict):
        return {**base, "reason": "provider_receipt_invalid"}
    if str(receipt.get("frame") or "").zfill(2) != f"{frame:02d}":
        return {**base, "reason": "provider_receipt_frame_mismatch"}
    if str(receipt.get("normalize_decision") or "") != code:
        return {**base, "reason": "provider_receipt_decision_mismatch"}

    canvas = ledger.get("canvas") or {}
    expected = (int(canvas.get("width") or 0), int(canvas.get("height") or 0))
    requested = receipt.get("requested_canvas") or {}
    requested_size = (int(requested.get("width") or 0), int(requested.get("height") or 0))
    if expected[0] <= 0 or expected[1] <= 0 or requested_size != expected:
        return {**base, "reason": "generation_request_canvas_mismatch"}

    try:
        raw_path = _repo_path(str(receipt.get("raw_path") or ""))
        raw_path.relative_to(ep)
    except (ValueError, OSError):
        return {**base, "reason": "provider_raw_path_invalid"}
    if not raw_path.is_file():
        return {**base, "reason": "provider_raw_missing"}
    expected_raw_sha = str(receipt.get("raw_sha256") or "").lower()
    if not expected_raw_sha or _sha256_file(raw_path).lower() != expected_raw_sha:
        return {**base, "reason": "provider_raw_sha_mismatch"}

    delta = float(receipt.get("ratio_delta") or 0.0)
    if delta <= canvas_normalize.REVIEW_RATIO_DELTA_MAX:
        return {**base, "reason": "ratio_should_use_normal_normalization_path", "ratio_delta": delta}
    maximum = (canvas_normalize.EXCEPTION_CROP_RATIO_DELTA_MAX
               if exception_crop_ratio_max is None else float(exception_crop_ratio_max))
    if delta > maximum:
        return {**base, "reason": "provider_crop_exception_limit_exceeded", "ratio_delta": delta}
    if bool(receipt.get("exact_raw_canvas_guaranteed")):
        return {**base, "reason": "provider_claimed_exact_canvas_but_returned_mismatch", "ratio_delta": delta}

    attempt_no = max(1, int(item.get("attempts") or 1))
    output = ep / "media/candidates/scheduled" / f"{frame:02d}-{item['id']}-a{attempt_no}.png"
    if output.exists():
        return {**base, "reason": "normalization_output_already_exists_requires_reconciliation", "ratio_delta": delta}
    return {
        **base,
        "auto_resolvable": True,
        "reason": "provider_ratio_exception_is_deterministically_recoverable",
        "ratio_delta": delta,
        "raw_path": str(raw_path),
        "provider_receipt": str(receipt_path),
        "output_path": str(output),
        "transaction_id": tx,
    }


def inspect(ep: Path, items: list[dict] | None = None) -> list[dict]:
    ep = Path(ep).resolve()
    queue = scheduler_core.load_queue(ep)
    rows = items if items is not None else [
        row for row in (queue.get("items") or [])
        if isinstance(row, dict) and row.get("status") == "blocked"
    ]
    return [inspect_item(ep, row) for row in rows]


def _recover_locked(ep: Path, *, frames: list[int] | None = None) -> dict:
    """Recover eligible blocked RAWs while the caller owns the Queue lock."""
    ep = Path(ep).resolve()
    queue = scheduler_core.load_queue(ep)
    wanted = {int(x) for x in (frames or [])}
    rows = [
        row for row in (queue.get("items") or [])
        if isinstance(row, dict)
        and row.get("status") == "blocked"
        and (not wanted or int(row.get("frame") or 0) in wanted)
    ]
    plans = [inspect_item(ep, row) for row in rows]
    unresolved = [row for row in plans if not row.get("auto_resolvable")]
    if unresolved:
        return {"status": "BLOCKED", "recovered": 0, "unresolved": unresolved, "plans": plans}

    recovered = []
    for item, plan in zip(rows, plans):
        frame = int(item["frame"])
        output = Path(plan["output_path"])
        receipt_path = Path(plan["provider_receipt"])
        raw_path = Path(plan["raw_path"])
        generation_key = production_recovery.generation_key_for_item(ep, item)
        if not generation_key:
            return {"status": "BLOCKED", "recovered": len(recovered), "reason": "generation_attempt_evidence_missing", "plans": plans}
        try:
            width, height, _ = canvas_normalize.read_canvas(ep)
            normalization = canvas_normalize.normalize_provider_crop_exception(
                raw_path,
                output,
                width,
                height,
                reason=(
                    "deterministic recovery of preserved provider RAW after ASPECT_RATIO_MISMATCH; "
                    "generation requested the canonical canvas and provider exact raw dimensions are not guaranteed"
                ),
            )
            receipt_info = provider_capability.finalize_receipt(receipt_path, normalization, output)
            import generation_attempt_authority
            budget_commit = generation_attempt_authority.complete_external_generation(
                ep, generation_attempt_authority.frame_key(ep, frame), generation_key,
                result_ref=str(output),
            )
            production_ledger.cmd_recover_success(SimpleNamespace(
                episode_dir=str(ep),
                frame=f"{frame:02d}",
                path=str(output),
                provider_receipt=str(receipt_path),
                transaction_id=str(plan["transaction_id"]),
                runner_request_id=None,
                recovery_reason="provider_ratio_normalization_exception",
            ))
        except Exception:
            raise

        item["status"] = "generated"
        item["output_path"] = output.resolve().relative_to(ROOT.resolve()).as_posix()
        item["completed_at"] = production_recovery.now()
        item["last_error"] = None
        item["normalization_recovery"] = {
            "kind": "provider_ratio_exception",
            "ratio_delta": plan["ratio_delta"],
            "provider_receipt": receipt_info["path"],
            "crop_applied": bool(normalization.get("crop_applied")),
            "operation": normalization.get("operation"),
        }
        item.pop("technical_failure_code", None)
        item.pop("retry_exhausted", None)
        item.pop("external_block_reason", None)
        production_recovery.mark_terminal(ep, item, "COMMITTED", recovery="provider_ratio_normalization_exception")
        recovered.append({"frame": frame, "item_id": item["id"], "output_path": item["output_path"]})

    scheduler_core.save_queue(ep, queue)
    return {"status": "PASS", "recovered": len(recovered), "items": recovered, "plans": plans}


def recover(ep: Path, *, frames: list[int] | None = None) -> dict:
    """Serialize deterministic recovery against schedulers and Queue cutover."""
    ep = Path(ep).resolve()
    try:
        with scheduler_core.queue_transaction(ep):
            return _recover_locked(ep, frames=frames)
    except scheduler_core.QueueMutationBusy:
        return {"status": "BLOCKED", "recovered": 0, "reason": "QUEUE_MUTATION_BUSY", "plans": []}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("inspect"); p.add_argument("episode_dir", type=Path)
    p = sub.add_parser("recover"); p.add_argument("episode_dir", type=Path); p.add_argument("--frame", type=int, action="append")
    args = ap.parse_args()
    if args.cmd == "inspect":
        print(json.dumps(inspect(args.episode_dir), ensure_ascii=False, indent=2))
        return 0
    result = recover(args.episode_dir, frames=args.frame)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
