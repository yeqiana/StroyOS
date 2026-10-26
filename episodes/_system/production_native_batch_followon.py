#!/usr/bin/env python3
"""Fail-closed automatic Batch continuation after a real native Codex pixel.

Authority: M00 review + first Batch SUCCEEDED MySQL Attempt + verified PNG
and current, non-generating native session visibility. No Provider work here.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image

import episode_state_persistence
import generation_attempt_authority as attempts
import image_payload_transport
import logical_asset_identity
import model_policy
import production_native_baseline_proof as baseline
import production_native_batch_reentry as first_proof
import runtime_request
import runtime_router
import scheduler_core
import storage_config

ROOT = Path(__file__).resolve().parents[2]
FAILURE = "LOGIN_AUTH_IMAGE_TOOL_CAPABILITY_UNKNOWN"
FLAG = "native_batch_verified_followon"
FRAMES = {2, 4, 5, 6, 7, 9, 10, 11, 12, 13, 14, 15, 16, 17, 19, 20}
EP14_NAME = "14_深渊疗愈所_第一集_净土生命还原"
EP14_FRAMES = set(range(1, 49)) - {1, 5, 45, 47}

def _is_ep14(ep):
    ep=Path(ep).resolve()
    return ep.name==EP14_NAME and ep.parent.name=="00_独立篇" and ep.is_relative_to(ROOT/"episodes")


def _policies(ep):
    return (model_policy.resolve("image.payload", episode=ep),
            model_policy.resolve("image.controller", episode=ep))


def _episode_authorized(ep, payload, controller) -> bool:
    try:
        ep = Path(ep).resolve()
        req = runtime_request.effective_for_episode(ep) or {}
        db = storage_config.mysql_connection_kwargs()
        ep14=_is_ep14(ep)
        if ep14:
            import production_ep14_visual_profile_rc9
            import visual_profile_gate
            if (production_ep14_visual_profile_rc9.eligible(ep).get("status")
                    != "CONFIRMED_BY_EXISTING_DELEGATION"
                    or visual_profile_gate.validate_visual_profile_for_production(
                        ep,stage="release").get("status")!="pass"):
                return False
        return bool(
            (ep.name == "13_失物归还的那扇门" or ep14)
            and ep.parent.name == "00_独立篇"
            and ep.is_relative_to(ROOT / "episodes")
            and (episode_state_persistence.load(ep) or {}).get("current_state") == "VISUAL_CALIBRATED"
            and req.get("mode") == "full_auto"
            and (req.get("runtime") or {}).get("execution_mode") == "dag"
            and runtime_router.image_execution_runtime()[0] == "CODEX"
            and str(db.get("host")) in {"127.0.0.1", "localhost"}
            and (int(db.get("port") or 0) == 3307 or
                 (ep14 and 1<=int(db.get("port") or 0)<=65535))
            and image_payload_transport.selected_route(1).get("provider") == "codex_subscription"
            and payload.get("model") == "gpt-image-2.5-flare"
            and payload.get("quality") == "high"
            and controller.get("model") == "gpt-6-luna"
            and controller.get("reasoning_effort") == "high"
        )
    except Exception:
        return False


def _batch(q, ep=None):
    rows = [x for x in q.get("items", []) if x.get("scope") == "batch"]
    expected = EP14_FRAMES if ep is not None and _is_ep14(ep) else FRAMES
    if len(rows) != len(expected) or {int(x.get("frame") or 0) for x in rows} != expected:
        return []
    if len({x.get("id") for x in rows}) != len(expected):
        return []
    return rows


def _anchor(ep, q, payload, controller) -> str | None:
    """Never accept a generated queue label without its original MySQL and PNG."""
    try:
        if not _episode_authorized(ep, payload, controller):
            return None
        if not _is_ep14(ep) and not first_proof._reviewed(ep, q):
            return None
        rows = _batch(q,ep)
        success = next(x for x in rows if int(x["frame"]) == 2)
        if success.get("status") != "generated" or success.get("model") != payload["model"]:
            return None
        if success.get("quality") != payload["quality"]:
            return None
        triage = success.get("local_visual_triage") or {}
        if triage.get("status") != "PASS" or triage.get("block_commit") is not False:
            return None
        key = logical_asset_identity.frame_asset_key(ep, 2)
        state = attempts.load_asset_state(ep, key) or {}
        if (int(state.get("attempts_consumed") or 0) != 1
                or state.get("active_attempt_index") is not None
                or int(state.get("outcome_unknown_count") or 0) != 0):
            return None
        attempt = attempts.load_attempt(ep, key, 1) or {}
        if (attempt.get("status") != "SUCCEEDED"
                or attempt.get("provider") != "codex_subscription"
                or attempt.get("payload_model") != payload["model"]
                or attempt.get("payload_quality") != payload["quality"]
                or attempt.get("generation_key") != success.get("generation_key")
                or int(success.get("attempt_index") or 0) != 1
                or not attempt.get("result_ref")):
            return None
        path = (ROOT / str(success.get("output_path") or "")).resolve()
        if not path.is_relative_to(ep / "media/candidates") or not path.is_file():
            return None
        data_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        if data_sha != triage.get("candidate_sha256"):
            return None
        with Image.open(path) as image:
            image.verify()
        return data_sha
    except Exception:
        return None


def admissible(ep, q, payload=None, controller=None) -> bool:
    """Read-only: one real finished frame, 15 identical historical capability blocks."""
    try:
        if payload is None or controller is None:
            payload, controller = _policies(ep)
        if not _anchor(ep, q, payload, controller):
            return False
        rows = _batch(q,ep)
        blocked = [x for x in rows if int(x["frame"]) != 2]
        if len(blocked) != (43 if _is_ep14(ep) else 15) or any(
            x.get("status") != "blocked"
            or x.get("technical_failure_code") != FAILURE
            or x.get("kind") != "original"
            or x.get("model") != payload["model"]
            or x.get("output_path") or x.get("candidate_output_path")
            for x in blocked
        ):
            return False
        for item in blocked:
            state = attempts.load_asset_state(
                ep, logical_asset_identity.frame_asset_key(ep, int(item["frame"]))) or {}
            if (int(state.get("attempts_consumed") or 0) != 0
                    or state.get("active_attempt_index") is not None
                    or int(state.get("outcome_unknown_count") or 0) != 0):
                return False
        return True
    except Exception:
        return False


def worker_eligible(ep, item, payload, controller, *, queue=None) -> bool:
    """Re-validate every released frame before the canonical capacity/Attempt claim."""
    try:
        if (item.get(FLAG) is not True
                or item.get("scope") != "batch"
                or item.get("kind") != "original"
                or item.get("status") not in {"queued", "running", "generating"}
                or item.get("model") != payload.get("model")
                or item.get("output_path") or item.get("candidate_output_path")):
            return False
        q = queue if queue is not None else scheduler_core.load_queue(ep)
        rows = _batch(q,ep)
        current = next((x for x in rows if x.get("id") == item.get("id")), None)
        if current is None or current.get(FLAG) is not True or int(current["frame"]) == 2:
            return False
        proof_sha = str(item.get("native_batch_success_anchor_sha256") or "")
        if len(proof_sha) != 64 or current.get("native_batch_success_anchor_sha256") != proof_sha:
            return False
        session_sha = str(item.get("native_batch_followon_evidence_sha256") or "")
        if len(session_sha) != 64 or current.get("native_batch_followon_evidence_sha256") != session_sha:
            return False
        if not _episode_authorized(ep, payload, controller) or _anchor(ep, q, payload, controller) != proof_sha:
            return False
        state = attempts.load_asset_state(
            ep, logical_asset_identity.frame_asset_key(ep, int(item["frame"]))) or {}
        consumed = int(state.get("attempts_consumed") or 0)
        if state.get("active_attempt_index") is not None:
            return False
        if consumed == 0:
            return int(state.get("outcome_unknown_count") or 0) == 0
        if consumed == 1:
            # Exactly one proved local network-terminal first Attempt is
            # re-admitted for its remaining second paid Attempt. The native
            # original Runner receipt, MySQL CAS, queue id, frame and source
            # hashes are re-verified; no generic UNKNOWN is accepted.
            import native_network_failure_rearm
            return native_network_failure_rearm.remaining_second_attempt(ep, current)
        return False
    except Exception:
        return False


def resume(ep, *, acknowledged=False):
    """Two short queue transactions; live Codex session check outside the lock."""
    ep = Path(ep).resolve()
    if not acknowledged:
        return {"status": "BLOCKED", "reason": "ACK_REQUIRED"}
    try:
        payload, controller = _policies(ep)
        with scheduler_core.queue_transaction(ep):
            q = scheduler_core.load_queue(ep)
            if not admissible(ep, q, payload, controller):
                return {"status": "BLOCKED", "reason": "SUCCESS_OR_ATTEMPT_UNVERIFIED"}
            anchor = _anchor(ep, q, payload, controller)
            ids = {x["id"] for x in _batch(q,ep) if int(x["frame"]) != 2}
        strict = image_payload_transport.payload_capability_preflight(
            model=payload["model"], quality=payload["quality"])
        secondary = baseline.attest_secondary(strict, payload, controller, None)
        if secondary is None:
            return {"status": "BLOCKED", "reason": "FRESH_NATIVE_SESSION_UNVERIFIED"}
        with scheduler_core.queue_transaction(ep):
            q = scheduler_core.load_queue(ep)
            if (not admissible(ep, q, payload, controller)
                    or _anchor(ep, q, payload, controller) != anchor
                    or {x["id"] for x in _batch(q,ep) if int(x["frame"]) != 2} != ids):
                return {"status": "BLOCKED", "reason": "AUTHORITIES_CHANGED"}
            frame_list = []
            evidence_sha = baseline.evidence_sha(secondary)
            for row in _batch(q,ep):
                if int(row["frame"]) == 2:
                    continue
                row[FLAG] = True
                row["native_batch_success_anchor_sha256"] = anchor
                row["native_batch_followon_evidence_sha256"] = evidence_sha
                row["status"] = "queued"
                row["last_error"] = None
                row.pop("technical_failure_code", None)
                frame_list.append(int(row["frame"]))
            scheduler_core.save_queue(ep, q)
        return {"status": "PASS", "rearmed_frames": sorted(frame_list),
                "provider_calls": 0, "attempts_reserved": 0,
                "proof": "FIRST_REAL_NATIVE_BATCH_SUCCESS_AND_FRESH_TOOL_VISIBILITY"}
    except scheduler_core.QueueMutationBusy:
        return {"status": "BLOCKED", "reason": "QUEUE_MUTATION_BUSY"}
    except Exception:
        return {"status": "BLOCKED", "reason": "NATIVE_PROOF_OR_QUEUE_UNAVAILABLE"}