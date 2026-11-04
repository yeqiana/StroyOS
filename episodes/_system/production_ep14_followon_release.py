"""EP14: authorize reviewed F029 after F009 proved native provider capability.

F009's independent actual-pixel review is a legitimate REPAIR_NOW, NOT PASS.
That content rejection remains NEEDS_USER and is not overridden by the
separate question of native image-tool functionality. This gate permits
exactly one other independently PREIMAGE-approved render F029, not F048 or
the old safety-refused Prompt; final review never gets auto-approved.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import generation_attempt_authority as ga
import logical_asset_identity as identity
import production_batch_review as pixel
import production_ep14_canonical_activation as active
import production_ledger as ledger
import scheduler_core

FRAME = 29
NEXT_FRAME_ID = "6f4a6433f2b9"
PREVIOUS_FRAME = 9
PREVIOUS_ITEM_ID = "8eefd4854826"
PREVIOUS_SHA = "e3b9075d16ecc8f2b27e39bbcdc640381b4ae8ae30bac31f130209c2718b86a9"
PIXEL_BATCH = "EP14_F009_PIXELS_V1"
AUTHORITY = "EP14_F029_INDEPENDENT_REVIEWED_RENDER_FOLLOWON_V1"


class FollowonDenied(ValueError):
    pass


def _sha(data):
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def _queue_selected(queue):
    rows = [x for x in queue.get("items", [])
            if x.get("kind") == "repair" and x.get("scope") == "batch"
            and int(x.get("frame") or 0) in (9, 29, 48)]
    if len(rows) != 3 or {int(x["frame"]) for x in rows} != {9, 29, 48}:
        raise FollowonDenied("EP14_EXACT_THREE_REVISED_QUEUE_ROWS_REQUIRED")
    return {int(x["frame"]): x for x in rows}


def _previous_provider_and_review(ep, by_frame):
    old = by_frame[PREVIOUS_FRAME]
    if (old.get("id") != PREVIOUS_ITEM_ID
            or old.get("status") != "scout_repair"
            or old.get("vision_batch_review", {}).get("decision") != "REPAIR_NOW"
            or old.get("batch_id") != PIXEL_BATCH
            or old.get("normalization_recovery", {}).get("pixel_review_completed") is not False):
        raise FollowonDenied("EP14_F009_CONTENT_REJECTED_BUT_PROVIDER_SUCCESS_EVIDENCE_REQUIRED")
    source = Path(ep) / "media/candidates/scheduled/09-8eefd4854826-a2.png"
    if not source.is_file():
        raise FollowonDenied("EP14_F009_REAL_PIXEL_FILE_MISSING")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if digest != PREVIOUS_SHA:
        raise FollowonDenied("EP14_F009_REAL_PIXEL_SHA_CHANGED")
    reviews = pixel.read_json(pixel.final_path(ep, PIXEL_BATCH))
    units = reviews.get("frames") or []
    provenance = reviews.get("critic_provenance") or {}
    if (reviews.get("batch_id") != PIXEL_BATCH
            or reviews.get("review_scope") != "EARLY_BATCH_ACTUAL_PIXELS"
            or reviews.get("final_pass_authority") is not False
            or len(units) != 1
            or units[0].get("frame") != "09"
            or units[0].get("candidate_sha256") != PREVIOUS_SHA
            or units[0].get("decision") != "REPAIR_NOW"
            or not units[0].get("issue_codes")
            or provenance.get("runtime") != "CODEX_ISOLATED"
            or provenance.get("session_reused_from_generation") is not False):
        raise FollowonDenied("EP14_F009_REAL_VISION_REPAIR_NOW_NOT_PERSISTED")
    key = identity.frame_asset_key(ep, PREVIOUS_FRAME)
    success = ga.load_attempt(ep, key, 2) or {}
    state = ga.load_asset_state(ep, key)
    if (success.get("status") != "SUCCEEDED"
            or success.get("provider") != "codex_subscription"
            or int(state.get("attempts_consumed") or 0) != 2
            or state.get("active_attempt_index") is not None):
        raise FollowonDenied("EP14_F009_SUCCESSFUL_REAL_PROVIDER_SECOND_ATTEMPT_NOT_VERIFIED")
    l = ledger.frame_obj(ledger.get_ledger(ep)[1], "09")[1]
    if (l.get("status") != "NEEDS_USER"
            or (l.get("current_candidate") or {}).get("sha256") != PREVIOUS_SHA
            or l.get("content_repairs_used") != 1):
        raise FollowonDenied("EP14_F009_REAL_PIXEL_NOT_BOUND_TO_REJECTED_LEDGER_REVIEW")
    # Returning REPAIR_NOW is NOT a content PASS. Keep it explicit in the
    # follow-on authorization; independent frames can still be generated.
    return {"real_provider_frame":9,
            "native_attempt2_status":"SUCCEEDED",
            "pixel_review_decision":"REPAIR_NOW",
            "pixel_review_sha256":PREVIOUS_SHA,
            "pixel_review_scope":"EARLY_BATCH_ACTUAL_PIXELS",
            "final_review_passed":False,
            "f009_requires_user":True}


def _budget(ep):
    key = identity.frame_asset_key(ep, FRAME)
    state = ga.load_asset_state(ep, key)
    first = ga.load_attempt(ep, key, 1) or {}
    second = ga.load_attempt(ep, key, 2)
    if (int(state.get("attempts_consumed") or 0) != 1
            or int(state.get("remaining_attempts") or 0) != 1
            or state.get("active_attempt_index") is not None
            or first.get("status") != "FAILED_AFTER_DISPATCH"
            or first.get("failure_class") != "IMAGE_PROVIDER_SAFETY_REJECTED"
            or second is not None):
        raise FollowonDenied("EP14_F029_SECOND_ATTEMPT_NOT_AUTHORIZED")


def _inspect(ep):
    ep = Path(ep).resolve()
    if ep.name != "14_深渊疗愈所_第一集_净土生命还原" or ep.parent.name != "00_独立篇":
        raise FollowonDenied("EP14_EXACT_EPISODE_ID_REQUIRED")
    q = scheduler_core.load_queue(ep)
    marker = q.get(active.QUEUE_KEY) or {}
    if (marker.get("pilot_mode") != "PILOT_FRAME_09_ONLY_REAL_PROVIDER_PROOF"
            or marker.get("pilot_frame") != PREVIOUS_FRAME
            or marker.get("state") != "ACTIVE_THREE_REVIEWED_CONTENT_REVISIONS"
            or marker.get("final_render_bundle_sha256") != active.BUNDLE
            or marker.get("production_dispatch_authorized") is not True
            or marker.get("historical_safety_refusals_preserved") is not True
            or marker.get("postimage_pixel_review_required") is not True
            or marker.get("followon_active_frame") is not None):
        raise FollowonDenied("EP14_SINGLE_FRAME_FOLLOWON_NOT_IN_READY_PHASE")
    rows = _queue_selected(q)
    target = rows[FRAME]
    if (target.get("id") != NEXT_FRAME_ID or target.get("status") != "pilot_hold"
            or rows[48].get("status") != "pilot_hold"):
        raise FollowonDenied("EP14_F029_EXACT_HELD_ROW_REQUIRED")
    old = [x for x in q.get("items", []) if x.get("frame") == FRAME
           and x.get("kind") == "original" and x.get("scope") == "batch"]
    if (len(old) != 1 or old[0].get("status") != "external_blocked"
            or old[0].get("requires_content_revision") is not True
            or old[0].get("no_automatic_original_prompt_retry") is not True):
        raise FollowonDenied("EP14_ORIGINAL_PROVIDER_REFUSAL_MUST_STAY_BLOCKED")
    package = active.load_for_dispatch(ep, target, for_followon=True)
    if (package.get("postimage_pixel_review_required") is not True
            or package.get("independent_preimage_text_approved") is not True
            or package.get("package_sha256") != target.get("prompt_package", {}).get("package_sha256")):
        raise FollowonDenied("EP14_F029_FINAL_INDEPENDENT_REVIEWED_RENDER_NOT_AUTHORIZED")
    previous_proof = _previous_provider_and_review(ep, rows)
    _budget(ep)
    ledger_path, doc = ledger.get_ledger(ep)
    key, frame = ledger.frame_obj(doc, str(FRAME))
    past = frame.get("attempts") or []
    if (frame.get("status") != "TECH_FAILED"
            or frame.get("content_repairs_used") != 0
            or ledger.content_repair_limit(doc) != 1
            or len(past) != 2
            or any(x.get("kind") != "original"
                   or x.get("result") != "technical_failure" for x in past)
            or frame.get("repair_authorization")):
        raise FollowonDenied("EP14_F029_HISTORICAL_LEDGER_NOT_ELIGIBLE")
    return {
        "queue": q, "queue_sha256": _sha(q),
        "ledger": doc, "ledger_sha256": _sha(doc), "ledger_path": ledger_path,
        "frame_key": key, "target": target, "package": package,
        "previous_proof": previous_proof,
        "attempt_history": deepcopy(past),
    }


def plan(ep):
    s = _inspect(ep)
    return {
        "status": "F029_REVIEWED_FOLLOWON_ELIGIBLE_F009_CONTENT_STILL_NEEDS_USER",
        "expected_queue_sha256": s["queue_sha256"],
        "expected_ledger_sha256": s["ledger_sha256"],
        "render_sha256": s["package"]["render_content_sha256"],
        "prior_provider_and_review": s["previous_proof"],
        "target_frame": FRAME,
        "held_frames": [29, 48],
        "paid_attempt2_exists": False,
        "provider_image_calls": 0,
    }



def _verified_predispatch_rearm(ep, item, frame):
    """One-time retry is valid only after a proven non-invoked provider attempt."""
    if item.get("status") not in {"queued", "running"}:
        return False
    record = item.get("ep14_capability_rearm") or {}
    if (record.get("approval_basis") != AUTHORITY
            or record.get("previous_provider_status") != "NOT_INVOKED"
            or record.get("source_lifecycle_sha256") != record.get("previous_lifecycle_sha256")
            or len(str(record.get("source_lifecycle_sha256") or "")) != 64
            or record.get("prior_ledger_attempt_count") != 3
            or record.get("f009_sha256") != PREVIOUS_SHA
            or record.get("f048_held") is not True
            or int(item.get("ep14_capability_rearm_count") or 0) != 1):
        return False
    attempts = frame.get("attempts") or []
    if (len(attempts) != 3
            or attempts[-1].get("kind") != "repair"
            or attempts[-1].get("result") != "technical_failure"
            or attempts[-1].get("error", {}).get("code") != "LOGIN_AUTH_IMAGE_TOOL_CAPABILITY_UNKNOWN"
            or attempts[-1].get("provider_attempt", {}).get("status") != "NOT_INVOKED"
            or attempts[-1].get("provider_attempt", {}).get("runner_request_id") is not None):
        return False
    try:
        _budget(ep)
    except FollowonDenied:
        return False
    return True


def _rearm_inspect(ep):
    ep = Path(ep).resolve()
    if ep.name != "14_深渊疗愈所_第一集_净土生命还原" or ep.parent.name != "00_独立篇":
        raise FollowonDenied("EP14_EXACT_EPISODE_ID_REQUIRED")
    q = scheduler_core.load_queue(ep)
    marker = q.get(active.QUEUE_KEY) or {}
    rows = _queue_selected(q)
    target = rows[FRAME]
    if (marker.get("pilot_mode") != "PILOT_FRAME_09_ONLY_REAL_PROVIDER_PROOF"
            or marker.get("pilot_frame") != 9
            or marker.get("state") != "ACTIVE_THREE_REVIEWED_CONTENT_REVISIONS"
            or marker.get("final_render_bundle_sha256") != active.BUNDLE
            or marker.get("production_dispatch_authorized") is not True
            or marker.get("historical_safety_refusals_preserved") is not True
            or marker.get("postimage_pixel_review_required") is not True
            or marker.get("followon_active_frame") != FRAME
            or marker.get("followon_authority") != AUTHORITY
            or marker.get("followon_previous_pixel_sha256") != PREVIOUS_SHA
            or marker.get("followon_previous_review_decision") != "REPAIR_NOW"
            or marker.get("followon_pending_final_review") is not True
            or target.get("id") != NEXT_FRAME_ID
            or target.get("scope") != "batch"
            or target.get("kind") != "repair"
            or target.get("status") != "blocked"
            or target.get("ep14_followon_authority") != AUTHORITY
            or target.get("ep14_followon_source_pixel_sha256") != PREVIOUS_SHA
            or target.get("technical_failure_code") != "LOGIN_AUTH_IMAGE_TOOL_CAPABILITY_UNKNOWN"
            or not str(target.get("last_error") or "").startswith(
                "LOGIN_AUTH_IMAGE_TOOL_CAPABILITY_UNKNOWN:")
            or int(target.get("attempts") or 0) != 2
            or int(target.get("ep14_capability_rearm_count") or 0) != 0
            or target.get("output_path")
            or rows[9].get("status") != "scout_repair"
            or rows[48].get("status") != "pilot_hold"):
        raise FollowonDenied("EP14_F029_REPAIR_PREFLIGHT_REARM_PROVENANCE_DRIFT")
    _previous_provider_and_review(ep, rows)
    _budget(ep)
    path, doc = ledger.get_ledger(ep)
    key, frame = ledger.frame_obj(doc, str(FRAME))
    history = frame.get("attempts") or []
    auth = frame.get("repair_authorization") or {}
    if (frame.get("status") != "TECH_FAILED"
            or int(frame.get("content_repairs_used") or 0) != 1
            or len(history) != 3
            or auth.get("approval_basis") != AUTHORITY
            or auth.get("queue_item_id") != NEXT_FRAME_ID
            or auth.get("render_content_sha256") !=
                target.get("prompt_package", {}).get("package_sha256")
            or auth.get("final_render_bundle_sha256") != active.BUNDLE
            or history[-1].get("kind") != "repair"
            or history[-1].get("result") != "technical_failure"
            or history[-1].get("error", {}).get("code") != "LOGIN_AUTH_IMAGE_TOOL_CAPABILITY_UNKNOWN"
            or history[-1].get("provider_attempt", {}).get("status") != "NOT_INVOKED"
            or history[-1].get("provider_attempt", {}).get("runner_request_id") is not None):
        raise FollowonDenied("EP14_F029_REPAIR_LEDGER_NOT_NON_INVOKED")
    lifecycle = ep / "meta/image-workers/29-6f4a6433f2b9-a2.lifecycle.json"
    if not lifecycle.is_file():
        raise FollowonDenied("EP14_F029_LIFECYCLE_MISSING")
    lifecycle_sha = hashlib.sha256(lifecycle.read_bytes()).hexdigest()
    evidence = json.loads(lifecycle.read_text(encoding="utf-8"))
    if (evidence.get("state") != "BLOCKED"
            or evidence.get("item_id") != NEXT_FRAME_ID
            or int(evidence.get("frame") or 0) != FRAME
            or int(evidence.get("attempt") or 0) != 2
            or evidence.get("error") != target.get("last_error")
            or (evidence.get("result") or {}).get("image_attempt_reserve_called") is not False
            or ((evidence.get("result") or {}).get("payload_preflight") or {}).get(
                "image_generation_called") is not False):
        raise FollowonDenied("EP14_F029_LIFECYCLE_PRE_DISPATCH_NOT_VERIFIED")
    return {"queue": q, "queue_sha256": _sha(q), "ledger": doc,
            "ledger_sha256": _sha(doc), "frame_key": key,
            "lifecycle_sha256": lifecycle_sha}


def rearm_plan(ep):
    state = _rearm_inspect(ep)
    return {"status": "F029_PRE_DISPATCH_CAPABILITY_FAILURE_REARM_ELIGIBLE",
            "expected_queue_sha256": state["queue_sha256"],
            "expected_ledger_sha256": state["ledger_sha256"],
            "lifecycle_sha256": state["lifecycle_sha256"],
            "paid_attempt2_exists": False, "image_generation_called": False}


def rearm_capability(ep, *, expected_queue_sha256, expected_ledger_sha256,
                     expected_lifecycle_sha256):
    ep = Path(ep).resolve()
    if any(not isinstance(x, str) or len(x) != 64 for x in (
            expected_queue_sha256, expected_ledger_sha256,
            expected_lifecycle_sha256)):
        raise FollowonDenied("EP14_F029_REARM_EXPLICIT_CAS_REQUIRED")
    with scheduler_core.queue_transaction(ep):
        state = _rearm_inspect(ep)
        if (state["queue_sha256"] != expected_queue_sha256
                or state["ledger_sha256"] != expected_ledger_sha256
                or state["lifecycle_sha256"] != expected_lifecycle_sha256):
            raise FollowonDenied("EP14_F029_REARM_STALE_CAS")
        queue = deepcopy(state["queue"])
        row = next(x for x in queue["items"] if x.get("id") == NEXT_FRAME_ID)
        row["status"] = "queued"
        row["ep14_capability_rearm_count"] = 1
        row["ep14_capability_rearm"] = {
            "approval_basis": AUTHORITY,
            "previous_provider_status": "NOT_INVOKED",
            "previous_lifecycle_sha256": state["lifecycle_sha256"],
            "source_lifecycle_sha256": expected_lifecycle_sha256,
            "prior_ledger_attempt_count": 3, "f009_sha256": PREVIOUS_SHA,
            "f048_held": True, "authorized_at": ledger.now_iso(),
        }
        row["native_network_preflight_error_before_requeue"] = row["last_error"]
        row["last_error"] = None
        row.pop("technical_failure_code", None)
        row.pop("completed_at", None)
        row.pop("execution", None)
        row.pop("external_block", None)
        scheduler_core.save_queue(ep, queue)
        after = scheduler_core.load_queue(ep)
        current = _queue_selected(after)
        if (current[FRAME].get("status") != "queued"
                or current[48].get("status") != "pilot_hold"
                or not _verified_predispatch_rearm(
                    ep, current[FRAME],
                    ledger.frame_obj(ledger.get_ledger(ep)[1], str(FRAME))[1])):
            raise FollowonDenied("EP14_F029_REARM_COMMIT_VERIFICATION_FAILED")
        return {"status": "F029_TECHNICAL_PREFLIGHT_REQUEUED",
                "queued_frame": FRAME, "held_frames": [48],
                "paid_attempts_reserved": 0, "image_generation_called": False}



def _second_noninvoked_valid(ep, item, frame):
    """One explicit F029 recovery only; never generalize to other frames."""
    first = item.get("ep14_capability_rearm") or {}
    second = item.get("ep14_second_capability_rearm") or {}
    if (item.get("status") not in {"queued", "running"}
            or int(item.get("ep14_capability_rearm_count") or 0) != 2
            or first.get("approval_basis") != AUTHORITY
            or first.get("prior_ledger_attempt_count") != 3
            or second.get("approval_basis") != AUTHORITY
            or second.get("prior_ledger_attempt_count") != 4
            or second.get("previous_provider_status") != "NOT_INVOKED"
            or second.get("source_lifecycle_sha256") != second.get("previous_lifecycle_sha256")
            or len(str(second.get("source_lifecycle_sha256") or "")) != 64
            or second.get("first_lifecycle_sha256") != first.get("source_lifecycle_sha256")
            or second.get("f009_sha256") != PREVIOUS_SHA
            or second.get("f048_held") is not True):
        return False
    history = frame.get("attempts") or []
    # The scheduler writes the current pending Ledger attempt *before* Worker
    # preflight. That provisional entry is not a paid MySQL provider Attempt.
    # Check it by the exact queue transaction instead of misclassifying it as
    # a fifth completed retry.
    running = item.get("status") == "running"
    if running:
        pending = history[-1] if history else {}
        tx = str((item.get("execution") or {}).get("transaction_id") or "")
        if (len(history) != 5 or frame.get("status") != "REPAIRING"
                or int(item.get("attempts") or 0) != 4
                or not tx or pending.get("runtime_transaction_id") != tx
                or pending.get("kind") != "repair"
                or pending.get("result") != "pending"
                or (pending.get("provider_attempt") or {}).get("status") != "NOT_INVOKED"):
            return False
        completed = history[:-1]
    else:
        if len(history) != 4 or frame.get("status") != "TECH_FAILED":
            return False
        completed = history
    if any(
        event.get("kind") != "repair"
        or event.get("result") != "technical_failure"
        or (event.get("error") or {}).get("code") != "LOGIN_AUTH_IMAGE_TOOL_CAPABILITY_UNKNOWN"
        or (event.get("provider_attempt") or {}).get("status") != "NOT_INVOKED"
        or (event.get("provider_attempt") or {}).get("runner_request_id") is not None
        for event in completed[-2:]):
        return False
    try:
        _budget(ep)
        return True
    except FollowonDenied:
        return False


def _second_inspect(ep):
    ep = Path(ep).resolve()
    if ep.name != "14_深渊疗愈所_第一集_净土生命还原" or ep.parent.name != "00_独立篇":
        raise FollowonDenied("EP14_SECOND_REARM_EPISODE_INVALID")
    q = scheduler_core.load_queue(ep)
    marker = q.get(active.QUEUE_KEY) or {}
    rows = _queue_selected(q)
    row = rows[FRAME]
    first = row.get("ep14_capability_rearm") or {}
    if (marker.get("state") != "ACTIVE_THREE_REVIEWED_CONTENT_REVISIONS"
            or marker.get("final_render_bundle_sha256") != active.BUNDLE
            or marker.get("production_dispatch_authorized") is not True
            or marker.get("postimage_pixel_review_required") is not True
            or marker.get("historical_safety_refusals_preserved") is not True
            or marker.get("pilot_mode") != "PILOT_FRAME_09_ONLY_REAL_PROVIDER_PROOF"
            or marker.get("pilot_frame") != 9
            or marker.get("followon_active_frame") != FRAME
            or marker.get("followon_authority") != AUTHORITY
            or marker.get("followon_previous_pixel_sha256") != PREVIOUS_SHA
            or marker.get("followon_previous_review_decision") != "REPAIR_NOW"
            or marker.get("followon_pending_final_review") is not True
            or row.get("id") != NEXT_FRAME_ID
            or row.get("kind") != "repair" or row.get("scope") != "batch"
            or row.get("status") != "blocked"
            or row.get("ep14_followon_authority") != AUTHORITY
            or row.get("ep14_followon_source_pixel_sha256") != PREVIOUS_SHA
            or row.get("technical_failure_code") != "LOGIN_AUTH_IMAGE_TOOL_CAPABILITY_UNKNOWN"
            or not str(row.get("last_error") or "").startswith("LOGIN_AUTH_IMAGE_TOOL_CAPABILITY_UNKNOWN:")
            or int(row.get("attempts") or 0) != 3
            or int(row.get("ep14_capability_rearm_count") or 0) != 1
            or row.get("ep14_second_capability_rearm") or row.get("output_path")
            or rows[9].get("status") != "scout_repair"
            or rows[48].get("status") != "pilot_hold"
            or first.get("approval_basis") != AUTHORITY
            or first.get("previous_provider_status") != "NOT_INVOKED"
            or first.get("prior_ledger_attempt_count") != 3
            or first.get("f009_sha256") != PREVIOUS_SHA
            or first.get("f048_held") is not True
            or first.get("source_lifecycle_sha256") != first.get("previous_lifecycle_sha256")
            or len(str(first.get("source_lifecycle_sha256") or "")) != 64):
        raise FollowonDenied("EP14_SECOND_REARM_QUEUE_DRIFT")
    _previous_provider_and_review(ep, rows)
    _budget(ep)
    _, doc = ledger.get_ledger(ep)
    _, frame = ledger.frame_obj(doc, str(FRAME))
    authorization = frame.get("repair_authorization") or {}
    if (frame.get("status") != "TECH_FAILED"
            or int(frame.get("content_repairs_used") or 0) != 1
            or authorization.get("approval_basis") != AUTHORITY
            or authorization.get("queue_item_id") != NEXT_FRAME_ID
            or authorization.get("render_content_sha256") != row.get("prompt_package", {}).get("package_sha256")
            or authorization.get("final_render_bundle_sha256") != active.BUNDLE):
        raise FollowonDenied("EP14_SECOND_REARM_AUTHORITY_DRIFT")
    a2 = ep / "meta/image-workers/29-6f4a6433f2b9-a2.lifecycle.json"
    a3 = ep / "meta/image-workers/29-6f4a6433f2b9-a3.lifecycle.json"
    if not a2.is_file() or not a3.is_file():
        raise FollowonDenied("EP14_SECOND_REARM_RECEIPTS_MISSING")
    if hashlib.sha256(a2.read_bytes()).hexdigest() != first["source_lifecycle_sha256"]:
        raise FollowonDenied("EP14_SECOND_REARM_FIRST_RECEIPT_CHANGED")
    digest = hashlib.sha256(a3.read_bytes()).hexdigest()
    receipt = json.loads(a3.read_text(encoding="utf-8"))
    result = receipt.get("result") or {}
    preflight = result.get("payload_preflight") or {}
    if (receipt.get("state") != "BLOCKED" or receipt.get("item_id") != NEXT_FRAME_ID
            or int(receipt.get("frame") or 0) != FRAME
            or int(receipt.get("attempt") or 0) != 3
            or receipt.get("error") != row.get("last_error")
            or result.get("image_attempt_reserve_called") is not False
            or preflight.get("image_generation_called") is not False
            or preflight.get("image_attempt_authority_called") is not False
            or preflight.get("failure_class") != "LOGIN_AUTH_IMAGE_TOOL_CAPABILITY_UNKNOWN"):
        raise FollowonDenied("EP14_SECOND_REARM_PROVIDER_MAY_HAVE_BEEN_CALLED")
    candidate = deepcopy(row)
    candidate["status"] = "queued"
    candidate["ep14_capability_rearm_count"] = 2
    candidate["ep14_second_capability_rearm"] = {
        "approval_basis": AUTHORITY, "prior_ledger_attempt_count": 4,
        "previous_provider_status": "NOT_INVOKED",
        "previous_lifecycle_sha256": digest,
        "source_lifecycle_sha256": digest,
        "first_lifecycle_sha256": first["source_lifecycle_sha256"],
        "f009_sha256": PREVIOUS_SHA, "f048_held": True,
    }
    if not _second_noninvoked_valid(ep, candidate, frame):
        raise FollowonDenied("EP14_SECOND_REARM_HISTORY_NOT_SAFE")
    return {"queue": q, "queue_sha256": _sha(q),
            "ledger_sha256": _sha(doc), "lifecycle_sha256": digest,
            "first_lifecycle_sha256": first["source_lifecycle_sha256"]}


def second_rearm_plan(ep):
    state = _second_inspect(ep)
    return {"status": "EP14_F029_SECOND_PRE_DISPATCH_REARM_ELIGIBLE",
            "expected_queue_sha256": state["queue_sha256"],
            "expected_ledger_sha256": state["ledger_sha256"],
            "lifecycle_sha256": state["lifecycle_sha256"],
            "paid_attempt2_exists": False, "image_generation_called": False}


def second_rearm_capability(ep, *, expected_queue_sha256, expected_ledger_sha256,
                            expected_lifecycle_sha256):
    ep = Path(ep).resolve()
    if any(not isinstance(x, str) or len(x) != 64 for x in (
            expected_queue_sha256, expected_ledger_sha256, expected_lifecycle_sha256)):
        raise FollowonDenied("EP14_SECOND_REARM_CAS_REQUIRED")
    with scheduler_core.queue_transaction(ep):
        state = _second_inspect(ep)
        if (state["queue_sha256"] != expected_queue_sha256
                or state["ledger_sha256"] != expected_ledger_sha256
                or state["lifecycle_sha256"] != expected_lifecycle_sha256):
            raise FollowonDenied("EP14_SECOND_REARM_STALE_CAS")
        queue = deepcopy(state["queue"])
        row = next(x for x in queue["items"] if x.get("id") == NEXT_FRAME_ID)
        row["status"] = "queued"
        row["ep14_capability_rearm_count"] = 2
        row["ep14_second_capability_rearm"] = {
            "approval_basis": AUTHORITY, "previous_provider_status": "NOT_INVOKED",
            "prior_ledger_attempt_count": 4,
            "previous_lifecycle_sha256": expected_lifecycle_sha256,
            "source_lifecycle_sha256": expected_lifecycle_sha256,
            "first_lifecycle_sha256": state["first_lifecycle_sha256"],
            "f009_sha256": PREVIOUS_SHA, "f048_held": True,
            "authorized_at": ledger.now_iso(),
        }
        row["last_error"] = None
        row.pop("technical_failure_code", None)
        row.pop("completed_at", None)
        row.pop("execution", None)
        row.pop("external_block", None)
        scheduler_core.save_queue(ep, queue)
        selected = _queue_selected(scheduler_core.load_queue(ep))
        if (selected[FRAME].get("status") != "queued"
                or selected[48].get("status") != "pilot_hold"
                or not _second_noninvoked_valid(
                    ep, selected[FRAME],
                    ledger.frame_obj(ledger.get_ledger(ep)[1], str(FRAME))[1])):
            raise FollowonDenied("EP14_SECOND_REARM_COMMIT_INVALID")
        return {"status": "EP14_F029_SECOND_PRE_DISPATCH_REQUEUED",
                "queued_frame": FRAME, "held_frames": [48],
                "paid_attempts_reserved": 0, "image_generation_called": False}



def _final_noninvoked_valid(ep, item, frame):
    """Single final F029 reentry. Every prior Worker attempt was pre-dispatch."""
    previous = item.get("ep14_capability_rearm") or {}
    second = item.get("ep14_second_capability_rearm") or {}
    final = item.get("ep14_final_capability_rearm") or {}
    if (item.get("status") not in {"queued", "running"}
            or int(item.get("ep14_capability_rearm_count") or 0) != 3
            or previous.get("approval_basis") != AUTHORITY
            or previous.get("prior_ledger_attempt_count") != 3
            or second.get("approval_basis") != AUTHORITY
            or second.get("prior_ledger_attempt_count") != 4
            or final.get("approval_basis") != AUTHORITY
            or final.get("prior_ledger_attempt_count") != 5
            or final.get("previous_provider_status") != "NOT_INVOKED"
            or final.get("f009_sha256") != PREVIOUS_SHA
            or final.get("f048_held") is not True
            or final.get("a2_sha256") != previous.get("source_lifecycle_sha256")
            or final.get("a3_sha256") != second.get("source_lifecycle_sha256")
            or len(str(final.get("a4_sha256") or "")) != 64):
        return False
    latest = Path(ep) / "meta/image-workers/29-6f4a6433f2b9-a4.lifecycle.json"
    if not latest.is_file() or hashlib.sha256(latest.read_bytes()).hexdigest() != final["a4_sha256"]:
        return False
    events = frame.get("attempts") or []
    running = item.get("status") == "running"
    if running:
        active = events[-1] if events else {}
        tx = str((item.get("execution") or {}).get("transaction_id") or "")
        if (len(events) != 6 or frame.get("status") != "REPAIRING"
                or int(item.get("attempts") or 0) != 5 or not tx
                or active.get("runtime_transaction_id") != tx
                or active.get("kind") != "repair"
                or active.get("result") != "pending"
                or (active.get("provider_attempt") or {}).get("status") != "NOT_INVOKED"):
            return False
        events = events[:-1]
    elif len(events) != 5 or frame.get("status") != "TECH_FAILED":
        return False
    if any(
        e.get("kind") != "repair"
        or e.get("result") != "technical_failure"
        or (e.get("error") or {}).get("code") != "LOGIN_AUTH_IMAGE_TOOL_CAPABILITY_UNKNOWN"
        or (e.get("provider_attempt") or {}).get("status") != "NOT_INVOKED"
        or (e.get("provider_attempt") or {}).get("runner_request_id") is not None
        for e in events[-3:]):
        return False
    try:
        _budget(ep)
        return True
    except FollowonDenied:
        return False


def _final_rearm_inspect(ep):
    ep = Path(ep).resolve()
    if ep.name != "14_深渊疗愈所_第一集_净土生命还原" or ep.parent.name != "00_独立篇":
        raise FollowonDenied("EP14_FINAL_REARM_EPISODE_INVALID")
    q = scheduler_core.load_queue(ep)
    marker = q.get(active.QUEUE_KEY) or {}
    rows = _queue_selected(q)
    item = rows[FRAME]
    previous = item.get("ep14_capability_rearm") or {}
    second = item.get("ep14_second_capability_rearm") or {}
    if (marker.get("state") != "ACTIVE_THREE_REVIEWED_CONTENT_REVISIONS"
            or marker.get("pilot_mode") != "PILOT_FRAME_09_ONLY_REAL_PROVIDER_PROOF"
            or marker.get("pilot_frame") != 9
            or marker.get("final_render_bundle_sha256") != active.BUNDLE
            or marker.get("production_dispatch_authorized") is not True
            or marker.get("historical_safety_refusals_preserved") is not True
            or marker.get("postimage_pixel_review_required") is not True
            or marker.get("followon_active_frame") != FRAME
            or marker.get("followon_authority") != AUTHORITY
            or marker.get("followon_previous_pixel_sha256") != PREVIOUS_SHA
            or marker.get("followon_previous_review_decision") != "REPAIR_NOW"
            or marker.get("followon_pending_final_review") is not True
            or item.get("id") != NEXT_FRAME_ID
            or item.get("kind") != "repair" or item.get("scope") != "batch"
            or item.get("status") != "blocked" or item.get("output_path")
            or item.get("ep14_followon_authority") != AUTHORITY
            or item.get("ep14_followon_source_pixel_sha256") != PREVIOUS_SHA
            or item.get("technical_failure_code") != "LOGIN_AUTH_IMAGE_TOOL_CAPABILITY_UNKNOWN"
            or not str(item.get("last_error") or "").startswith("LOGIN_AUTH_IMAGE_TOOL_CAPABILITY_UNKNOWN:")
            or int(item.get("attempts") or 0) != 4
            or int(item.get("ep14_capability_rearm_count") or 0) != 2
            or item.get("ep14_final_capability_rearm")
            or rows[9].get("status") != "scout_repair"
            or rows[48].get("status") != "pilot_hold"
            or previous.get("approval_basis") != AUTHORITY
            or previous.get("prior_ledger_attempt_count") != 3
            or previous.get("f009_sha256") != PREVIOUS_SHA
            or second.get("approval_basis") != AUTHORITY
            or second.get("prior_ledger_attempt_count") != 4
            or second.get("f009_sha256") != PREVIOUS_SHA):
        raise FollowonDenied("EP14_FINAL_REARM_QUEUE_DRIFT")
    _previous_provider_and_review(ep, rows)
    _budget(ep)
    _, doc = ledger.get_ledger(ep)
    _, frame = ledger.frame_obj(doc, str(FRAME))
    auth = frame.get("repair_authorization") or {}
    if (frame.get("status") != "TECH_FAILED"
            or int(frame.get("content_repairs_used") or 0) != 1
            or auth.get("approval_basis") != AUTHORITY
            or auth.get("queue_item_id") != NEXT_FRAME_ID
            or auth.get("render_content_sha256") != item.get("prompt_package", {}).get("package_sha256")
            or auth.get("final_render_bundle_sha256") != active.BUNDLE):
        raise FollowonDenied("EP14_FINAL_REARM_AUTHORITY_DRIFT")
    files = [ep / f"meta/image-workers/29-6f4a6433f2b9-a{number}.lifecycle.json"
             for number in (2, 3, 4)]
    if not all(x.is_file() for x in files):
        raise FollowonDenied("EP14_FINAL_REARM_LIFECYCLE_MISSING")
    digests = [hashlib.sha256(x.read_bytes()).hexdigest() for x in files]
    if (digests[0] != previous.get("source_lifecycle_sha256")
            or digests[1] != second.get("source_lifecycle_sha256")):
        raise FollowonDenied("EP14_FINAL_REARM_RECEIPT_DRIFT")
    receipt = json.loads(files[2].read_text(encoding="utf-8"))
    result = receipt.get("result") or {}
    preflight = result.get("payload_preflight") or {}
    if (receipt.get("state") != "BLOCKED"
            or receipt.get("item_id") != NEXT_FRAME_ID
            or int(receipt.get("frame") or 0) != FRAME
            or int(receipt.get("attempt") or 0) != 4
            or receipt.get("error") != item.get("last_error")
            or result.get("image_attempt_reserve_called") is not False
            or preflight.get("image_generation_called") is not False
            or preflight.get("image_attempt_authority_called") is not False
            or preflight.get("failure_class") != "LOGIN_AUTH_IMAGE_TOOL_CAPABILITY_UNKNOWN"):
        raise FollowonDenied("EP14_FINAL_REARM_PROVIDER_DISPATCH_UNCERTAIN")
    candidate = deepcopy(item)
    candidate["status"] = "queued"
    candidate["ep14_capability_rearm_count"] = 3
    candidate["ep14_final_capability_rearm"] = {
        "approval_basis": AUTHORITY, "prior_ledger_attempt_count": 5,
        "previous_provider_status": "NOT_INVOKED",
        "a2_sha256": digests[0], "a3_sha256": digests[1],
        "a4_sha256": digests[2], "f009_sha256": PREVIOUS_SHA, "f048_held": True,
    }
    if not _final_noninvoked_valid(ep, candidate, frame):
        raise FollowonDenied("EP14_FINAL_REARM_HISTORY_UNVERIFIED")
    return {"queue": q, "queue_sha256": _sha(q),
            "ledger_sha256": _sha(doc), "digests": digests}


def final_rearm_plan(ep):
    s = _final_rearm_inspect(ep)
    return {"status": "F029_FINAL_PRE_DISPATCH_COMPENSATION_ELIGIBLE",
            "expected_queue_sha256": s["queue_sha256"],
            "expected_ledger_sha256": s["ledger_sha256"],
            "expected_lifecycle_sha256": s["digests"][2],
            "paid_attempt2_exists": False, "image_generation_called": False}


def final_rearm_capability(ep, *, expected_queue_sha256, expected_ledger_sha256,
                           expected_lifecycle_sha256):
    ep = Path(ep).resolve()
    if any(not isinstance(v, str) or len(v) != 64 for v in (
            expected_queue_sha256, expected_ledger_sha256, expected_lifecycle_sha256)):
        raise FollowonDenied("EP14_FINAL_REARM_CAS_REQUIRED")
    with scheduler_core.queue_transaction(ep):
        s = _final_rearm_inspect(ep)
        if (s["queue_sha256"] != expected_queue_sha256
                or s["ledger_sha256"] != expected_ledger_sha256
                or s["digests"][2] != expected_lifecycle_sha256):
            raise FollowonDenied("EP14_FINAL_REARM_STALE_CAS")
        q = deepcopy(s["queue"])
        item = next(x for x in q["items"] if x.get("id") == NEXT_FRAME_ID)
        item["status"] = "queued"
        item["ep14_capability_rearm_count"] = 3
        item["ep14_final_capability_rearm"] = {
            "approval_basis": AUTHORITY, "previous_provider_status": "NOT_INVOKED",
            "prior_ledger_attempt_count": 5,
            "a2_sha256": s["digests"][0], "a3_sha256": s["digests"][1],
            "a4_sha256": s["digests"][2],
            "f009_sha256": PREVIOUS_SHA, "f048_held": True,
            "authorized_at": ledger.now_iso(),
        }
        item["last_error"] = None
        item.pop("technical_failure_code", None)
        item.pop("completed_at", None)
        item.pop("execution", None)
        item.pop("external_block", None)
        scheduler_core.save_queue(ep, q)
        rows = _queue_selected(scheduler_core.load_queue(ep))
        if (rows[FRAME].get("status") != "queued"
                or rows[48].get("status") != "pilot_hold"
                or not _final_noninvoked_valid(
                    ep, rows[FRAME],
                    ledger.frame_obj(ledger.get_ledger(ep)[1], str(FRAME))[1])):
            raise FollowonDenied("EP14_FINAL_REARM_COMMIT_INVALID")
        return {"status": "EP14_F029_FINAL_PRE_DISPATCH_REQUEUED",
                "queued_frame": FRAME, "held_frames": [48],
                "paid_attempts_reserved": 0, "image_generation_called": False}


def dispatch_authorized(ep, frame, item, marker):
    """Called independently from each real Worker immediately before reserve."""
    if int(frame) == 48:
        import production_ep14_f048_followon as f048
        return f048.dispatch_authorized(ep, item, marker)
    if int(frame) != FRAME or item.get("id") != NEXT_FRAME_ID:
        return False
    if (marker.get("followon_active_frame") != FRAME
            or marker.get("followon_authority") != AUTHORITY
            or marker.get("followon_previous_pixel_sha256") != PREVIOUS_SHA
            or marker.get("followon_previous_review_decision") != "REPAIR_NOW"
            or marker.get("followon_pending_final_review") is not True
            or item.get("ep14_followon_authority") != AUTHORITY):
        return False
    try:
        previous = _previous_provider_and_review(Path(ep), _queue_selected(scheduler_core.load_queue(ep)))
        if previous["final_review_passed"] is not False:
            return False
        ledger_row = ledger.frame_obj(ledger.get_ledger(ep)[1], str(FRAME))[1]
        return bool(ledger_row.get("status") in {"REPAIR_AUTHORIZED", "TECH_FAILED", "REPAIRING"}
                    and ledger_row.get("repair_authorization", {}).get("approval_basis") == AUTHORITY
                    and (ledger_row.get("status") == "REPAIR_AUTHORIZED"
                         or (ledger_row.get("status") == "TECH_FAILED" and
                             (_verified_predispatch_rearm(ep, item, ledger_row)
                              or _second_noninvoked_valid(ep, item, ledger_row)
                              or _final_noninvoked_valid(ep, item, ledger_row)))
                         or (ledger_row.get("status") == "REPAIRING" and
                             (_second_noninvoked_valid(ep, item, ledger_row)
                              or _final_noninvoked_valid(ep, item, ledger_row)))))
    except Exception:
        return False


def release(ep, *, expected_queue_sha256, expected_ledger_sha256):
    ep = Path(ep).resolve()
    if (not isinstance(expected_queue_sha256, str) or len(expected_queue_sha256) != 64
            or not isinstance(expected_ledger_sha256, str) or len(expected_ledger_sha256) != 64):
        raise FollowonDenied("EP14_F029_EXPLICIT_SHA_CAS_REQUIRED")
    with scheduler_core.queue_transaction(ep):
        s = _inspect(ep)
        if (s["queue_sha256"] != expected_queue_sha256
                or s["ledger_sha256"] != expected_ledger_sha256):
            raise FollowonDenied("EP14_F029_QUEUE_OR_LEDGER_CAS_CHANGED")
        new_doc = deepcopy(s["ledger"])
        new_frame = new_doc["frames"][s["frame_key"]]
        auth = {
            "at": ledger.now_iso(),
            "approval_basis": AUTHORITY,
            "direct_user_production_authorized": True,
            "reviewed_frame": FRAME,
            "queue_item_id": NEXT_FRAME_ID,
            "mysql_active_package_id": s["target"]["ep14_active_package_id"],
            "render_content_sha256": s["package"]["render_content_sha256"],
            "scene_prompt_sha256": s["package"]["scene_prompt_sha256"],
            "final_render_bundle_sha256": active.BUNDLE,
            "provider_proof": s["previous_proof"],
            "historical_original_attempts_preserved": True,
            "postimage_pixel_review_required": True,
            "f009_content_review_unresolved": True,
            "paid_attempt2_reserved": False,
        }
        new_frame["status"] = "REPAIR_AUTHORIZED"
        new_frame["repair_authorization"] = auth
        new_frame.setdefault("reviewed_revision_authorizations", []).append(auth)
        new_doc["updated_at"] = ledger.now_iso()
        ledger.save_json(s["ledger_path"], new_doc)
        verify = ledger.frame_obj(ledger.get_ledger(ep)[1], str(FRAME))[1]
        if (verify.get("status") != "REPAIR_AUTHORIZED"
                or verify.get("attempts") != s["attempt_history"]
                or verify.get("repair_authorization") != auth):
            raise FollowonDenied("EP14_F029_LEDGER_COMMIT_NOT_VERIFIED")
        latest = scheduler_core.load_queue(ep)
        if _sha(latest) != s["queue_sha256"]:
            raise FollowonDenied("EP14_F029_QUEUE_CHANGED_AFTER_LEDGER_COMMIT")
        next_queue = deepcopy(latest)
        row = next(x for x in next_queue["items"] if x.get("id") == NEXT_FRAME_ID)
        row["status"] = "queued"
        row["ep14_followon_authority"] = AUTHORITY
        row["ep14_followon_source_pixel_sha256"] = PREVIOUS_SHA
        m = next_queue[active.QUEUE_KEY]
        m["followon_active_frame"] = FRAME
        m["followon_authority"] = AUTHORITY
        m["followon_previous_pixel_sha256"] = PREVIOUS_SHA
        m["followon_previous_review_decision"] = "REPAIR_NOW"
        m["followon_pending_final_review"] = True
        scheduler_core.save_queue(ep, next_queue)
        after = scheduler_core.load_queue(ep)
        selected = _queue_selected(after)
        if (selected[FRAME].get("status") != "queued"
                or selected[48].get("status") != "pilot_hold"
                or selected[9].get("status") != "scout_repair"
                or after[active.QUEUE_KEY].get("followon_active_frame") != FRAME):
            raise FollowonDenied("EP14_F029_QUEUE_COMMIT_NOT_VERIFIED")
        return {
            "status":"F029_REVIEWED_FOLLOWON_AUTHORIZED_AND_QUEUED",
            "queued_frame": FRAME,
            "held_frames": [48],
            "f009_content_review": "REPAIR_NOW_NEEDS_USER_UNCHANGED",
            "paid_attempts_reserved": 0,
            "image_generation_called": False,
        }
