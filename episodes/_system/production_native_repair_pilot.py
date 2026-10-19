#!/usr/bin/env python3
"""One acknowledged native repair image capability pilot, not a general UNKNOWN PASS.

Only frame 02 of Episode 13's immutable thirteen-frame repair wave may be
rearmed. Before a paid Attempt, the worker must independently repeat a fresh,
non-generating native Codex tool-visibility proof and the existing MySQL
Generation Attempt authority must still grant its normal second attempt.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
from pathlib import Path

import episode_state_persistence
import generation_attempt_authority as attempts
import image_payload_transport
import logical_asset_identity
import model_policy
import production_ledger
import production_native_baseline_proof as baseline
import runtime_request
import runtime_router
import scheduler_core
import storage_config
import story_json

ROOT = Path(__file__).resolve().parents[2]
FAILURE = "LOGIN_AUTH_IMAGE_TOOL_CAPABILITY_UNKNOWN"
FLAG = "native_repair_single_frame_proof"
REPAIR_FRAMES = frozenset({2, 4, 6, 7, 9, 11, 12, 13, 14, 16, 17, 19, 20})
PILOT_FRAME = 2
EXPECTED_ERROR = FAILURE + ": independent payload route unavailable; provider=codex_subscription"


def eligible(ep: Path, item: dict, payload: dict, controller: dict,
             *, queue: dict | None = None, blocked: bool = False) -> bool:
    """Read-only exact identity fence; only the existing second paid Attempt."""
    try:
        ep = Path(ep).resolve()
        if (not ep.is_relative_to(ROOT / "episodes")
                or ep.parent.name != "00_独立篇"
                or ep.name != "13_失物归还的那扇门"
                or int(item.get("frame") or 0) != PILOT_FRAME
                or item.get("scope") != "repair" or item.get("kind") != "repair"
                or item.get("model") != "gpt-image-2.5-flare"
                or payload.get("model") != "gpt-image-2.5-flare"
                or payload.get("quality") != "high"
                or controller.get("model") != "gpt-6-luna"
                or controller.get("reasoning_effort") != "high"):
            return False
        request = runtime_request.effective_for_episode(ep) or {}
        db = storage_config.mysql_connection_kwargs()
        if (request.get("mode") != "full_auto"
                or (request.get("runtime") or {}).get("execution_mode") != "dag"
                or runtime_router.image_execution_runtime()[0] != "CODEX"
                or (episode_state_persistence.load(ep) or {}).get("current_state")
                   != "VISUAL_CALIBRATED"
                or db.get("host") not in {"127.0.0.1", "localhost"}
                or int(db.get("port") or 0) not in {3307, 13307}
                or image_payload_transport.selected_route(1).get("provider")
                   != "codex_subscription"):
            return False
        q = queue if queue is not None else scheduler_core.load_queue(ep)
        repair = [x for x in q.get("items") or [] if x.get("kind") == "repair"
                  and x.get("scope") == "repair"]
        if (len(repair) != 13 or
                {int(x.get("frame") or 0) for x in repair} != REPAIR_FRAMES or
                len({x.get("id") for x in repair}) != 13):
            return False
        actual = next((x for x in repair if x.get("id") == item.get("id")), None)
        if actual is None or actual.get("frame") != PILOT_FRAME:
            return False
        other = [x for x in repair if x is not actual]
        if any(x.get("status") != "blocked" or
               x.get("technical_failure_code") != FAILURE or
               x.get("last_error") != EXPECTED_ERROR for x in other):
            return False
        if blocked:
            if (actual.get("status") != "blocked" or
                    actual.get("technical_failure_code") != FAILURE or
                    actual.get("last_error") != EXPECTED_ERROR or
                    actual.get(FLAG) or
                    int(actual.get("native_repair_pilot_rearm_count") or 0) != 0):
                return False
        elif (actual.get("status") not in {"queued", "running", "generating"}
              or actual.get(FLAG) is not True
              or actual.get("native_repair_pilot_rearm_count") != 1
              or not re.fullmatch(r"[0-9a-f]{64}",
                                  str(actual.get("native_repair_visibility_sha256") or ""))):
            return False
        if actual.get("output_path") or actual.get("candidate_output_path"):
            return False

        plan = story_json.read_json(ep / "meta/runtime/repair-wave-1.json")
        if (plan.get("status") != "STARTED"
                or not str(plan.get("repair_wave_id") or "").endswith("/production/repair-wave-1")
                or plan.get("source_review_scope") != "CANDIDATE_FULL_FRAME_SET"
                or int((plan.get("summary") or {}).get("eligible_repairs") or 0) != 13):
            return False
        reviewed = ep / "meta/frame-semantic-candidate-attempt-1.json"
        receipt = (plan.get("source_review_receipts") or [{}])[0]
        if (receipt.get("path") != "meta/frame-semantic-candidate-attempt-1.json"
                or not reviewed.is_file()
                or receipt.get("sha256") != hashlib.sha256(reviewed.read_bytes()).hexdigest()):
            return False
        repair_rows = {int(x.get("frame_id") or 0): x for x in plan.get("frames") or []
                       if x.get("repairable")}
        if set(repair_rows) != REPAIR_FRAMES:
            return False
        for queued in repair:
            row = repair_rows[int(queued["frame"])]
            if (row.get("repair_status") != "ENQUEUED"
                    or row.get("repair_queue_item_id") != queued.get("id")
                    or row.get("source_generation_key") != queued.get("source_generation_key")
                    or row.get("source_artifact_sha256") != queued.get("source_artifact_sha256")
                    or not row.get("repair_prompt_task_fingerprint")
                    or row.get("repair_prompt_task_fingerprint")
                       != queued.get("repair_prompt_task_fingerprint")
                    or row.get("review_receipt_sha256") != receipt["sha256"]
                    or int(row.get("remaining_generation_attempts") or 0) != 1
                    or queued.get("repair_wave_id") != plan["repair_wave_id"]):
                return False
        row = repair_rows[PILOT_FRAME]
        ledger = production_ledger.load_authority(ep, default={}) or {}
        current = (ledger.get("frames") or {}).get("02") or {}
        candidate = current.get("current_candidate") or {}
        if (current.get("status") not in {"TECH_FAILED", "REPAIRING"}
                or candidate.get("sha256") != row.get("source_artifact_sha256")
                or not row.get("source_generation_key")):
            return False
        asset = Path(str(candidate.get("path") or ""))
        asset = asset if asset.is_absolute() else (ROOT / asset).resolve()
        if (not asset.is_relative_to(ep) or not asset.is_file()
                or hashlib.sha256(asset.read_bytes()).hexdigest()
                   != row["source_artifact_sha256"]):
            return False
        key = logical_asset_identity.frame_asset_key(ep, PILOT_FRAME)
        state = attempts.load_asset_state(ep, key) or {}
        return bool(int(state.get("attempts_consumed") or 0) == 1
                    and state.get("active_attempt_index") is None
                    and int(state.get("outcome_unknown_count") or 0) == 0
                    and int(attempts.remaining(ep, key)) == 1)
    except Exception:
        return False


def rearm_one(ep: Path, *, acknowledged: bool = False) -> dict:
    """CAS twice around a real non-pixel session probe; never reserve Attempt."""
    ep = Path(ep).resolve()
    if not acknowledged:
        return {"status": "BLOCKED", "reason": "ACK_REQUIRED"}
    payload = model_policy.resolve("image.payload", episode=ep)
    controller = model_policy.resolve("image.controller", episode=ep)
    try:
        with scheduler_core.queue_transaction(ep):
            q = scheduler_core.load_queue(ep)
            rows = [x for x in q.get("items") or [] if
                    x.get("scope") == "repair" and x.get("kind") == "repair"]
            if len(rows) != 13:
                return {"status": "BLOCKED", "reason": "REPAIR_WAVE_UNVERIFIED"}
            first = min(rows, key=lambda x: int(x.get("frame") or 0))
            if not eligible(ep, first, payload, controller, queue=q, blocked=True):
                return {"status": "BLOCKED", "reason": "AUTHORITIES_UNVERIFIED"}
            item_id = first["id"]
    except scheduler_core.QueueMutationBusy:
        return {"status": "BLOCKED", "reason": "QUEUE_MUTATION_BUSY"}
    try:
        strict = image_payload_transport.payload_capability_preflight(
            model=payload["model"], quality=payload["quality"])
        secondary = baseline.attest_secondary(strict, payload, controller, None)
    except Exception:
        return {"status": "BLOCKED", "reason": "SESSION_PROBE_FAILED"}
    if secondary is None:
        return {"status": "BLOCKED", "reason": "SESSION_TOOL_UNVERIFIED"}
    try:
        with scheduler_core.queue_transaction(ep):
            q = scheduler_core.load_queue(ep)
            first = next((x for x in q.get("items") or [] if x.get("id") == item_id), None)
            if first is None or not eligible(ep, first, payload, controller,
                                             queue=q, blocked=True):
                return {"status": "BLOCKED", "reason": "AUTHORITIES_CHANGED"}
            first[FLAG] = True
            first["native_repair_pilot_rearm_count"] = 1
            first["native_repair_visibility_sha256"] = baseline.evidence_sha(secondary)
            first["status"] = "queued"
            first["last_error"] = None
            first.pop("technical_failure_code", None)
            scheduler_core.save_queue(ep, q)
            return {"status": "PASS", "rearmed_frames": [PILOT_FRAME],
                    "other_repair_frames_unchanged": 12,
                    "provider_calls": 0, "attempts_reserved": 0}
    except scheduler_core.QueueMutationBusy:
        return {"status": "BLOCKED", "reason": "QUEUE_MUTATION_BUSY"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("episode_dir", type=Path)
    parser.add_argument("--ack-real-production", action="store_true")
    args = parser.parse_args()
    result = rearm_one(args.episode_dir, acknowledged=args.ack_real_production)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
