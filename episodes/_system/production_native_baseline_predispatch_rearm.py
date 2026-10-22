#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One-shot, fail-closed recovery for a Visual Lock baseline *pre-dispatch* block.

No provider call or paid Attempt is made here. The proof probes only a fresh
native Codex session's available tools; the ordinary Worker still owns all
generation, Attempt reservation and pixel/review authority afterwards.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import generation_attempt_authority as attempts
import image_payload_transport
import image_scheduler
import logical_asset_identity
import model_policy
import production_native_baseline_proof as baseline
import runtime_driver
import scheduler_core


FAILURE = "LOGIN_AUTH_IMAGE_TOOL_CAPABILITY_UNKNOWN"
PREFIX = FAILURE + ": independent payload route unavailable; provider=codex_subscription"
REARM_FLAG = "native_baseline_predispatch_rearm_count"


def _eligible(ep: Path, q: dict, payload: dict, controller: dict) -> dict | None:
    driver = runtime_driver.status(ep)
    if (driver.get("driver_state") != "EXITED"
            or str(driver.get("exit_code") or "") != "4"):
        return None
    rows = q.get("items") or []
    first = next((r for r in rows if int(r.get("frame") or 0) == 1), None)
    if (len(rows) != 4 or not isinstance(first, dict)
            or first.get("scope") != "visual_lock"
            or first.get("status") != "blocked"
            or first.get("technical_failure_code") != FAILURE
            or first.get("last_error") != PREFIX
            or int(first.get("attempts") or 0) != 1
            or int(first.get(REARM_FLAG) or 0) != 0
            or first.get("output_path") or first.get("candidate_output_path")
            or first.get("external_block")):
        return None
    key = logical_asset_identity.frame_asset_key(ep, 1)
    if (attempts.load_attempt(ep, key, 1) is not None
            or attempts.load_attempt(ep, key, 2) is not None):
        return None
    if not baseline.eligible(
            ep, first, payload, controller,
            blocked_predispatch=True, queue_override=q):
        return None
    return first


def rearm_one(ep: Path, *, acknowledged: bool = False) -> dict:
    ep = Path(ep).resolve()
    if not acknowledged:
        return {"status": "BLOCKED", "reason": "EXPLICIT_ACK_REQUIRED"}
    payload = model_policy.resolve("image.payload", episode=ep)
    controller = model_policy.resolve("image.controller", episode=ep)
    try:
        with image_scheduler.queue_transaction(ep):
            queue = image_scheduler.load_queue(ep)
            first = _eligible(ep, queue, payload, controller)
            if first is None:
                return {"status": "BLOCKED", "reason": "PRE_DISPATCH_AUTHORITIES_UNVERIFIED"}
            item_id = str(first.get("id") or "")
            if not item_id:
                return {"status": "BLOCKED", "reason": "MISSING_QUEUE_ITEM_ID"}
    except (scheduler_core.QueueMutationBusy, RuntimeError, ValueError, OSError):
        return {"status": "BLOCKED", "reason": "QUEUE_OR_AUTHORITY_UNAVAILABLE"}

    # Network/smoke check is outside the lock: no image tool calls permitted.
    try:
        strict = image_payload_transport.payload_capability_preflight(
            model=str(payload.get("model") or ""),
            quality=str(payload.get("quality") or ""),
            proof_transport_model=str(controller.get("model") or ""),
            proof_transport_effort=str(controller.get("reasoning_effort") or ""),
        )
        secondary = baseline.attest_secondary(strict, payload, controller, None)
    except Exception:
        secondary = None
    if secondary is None:
        return {"status": "BLOCKED", "reason": "CURRENT_SESSION_IMAGE_TOOL_UNVERIFIED"}

    # Repeat all checks inside a new queue transaction (no stale green light).
    try:
        with image_scheduler.queue_transaction(ep):
            queue = image_scheduler.load_queue(ep)
            first = _eligible(ep, queue, payload, controller)
            if first is None or str(first.get("id") or "") != item_id:
                return {"status": "BLOCKED", "reason": "AUTHORITIES_DRIFTED"}
            first[REARM_FLAG] = 1
            first["native_baseline_visibility_sha256"] = baseline.evidence_sha(secondary)
            first["native_baseline_original_error"] = str(first["last_error"])
            first["status"] = "queued"
            first["last_error"] = None
            first.pop("technical_failure_code", None)
            image_scheduler.save_queue(ep, queue)
    except (scheduler_core.QueueMutationBusy, RuntimeError, ValueError, OSError):
        return {"status": "BLOCKED", "reason": "QUEUE_OR_AUTHORITY_CHANGED"}
    return {
        "status": "PASS", "frame": 1, "scope": "visual_lock",
        "rearmed_item": item_id, "other_admission_frames_unchanged": 3,
        "provider_calls": 0, "paid_attempts_reserved": 0,
        "next_action": "RECHECK_CANONICAL_DAG_ADMISSION",
    }


def main() -> int:
    from platform.repository.mysql.mysql_connection_pool import set_process_role
    set_process_role("scheduler")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("episode_dir", type=Path)
    parser.add_argument("--ack-real-production", action="store_true")
    args = parser.parse_args()
    result = rearm_one(args.episode_dir, acknowledged=args.ack_real_production)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
