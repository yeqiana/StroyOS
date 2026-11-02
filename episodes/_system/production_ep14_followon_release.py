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


def dispatch_authorized(ep, frame, item, marker):
    """Called independently from each real Worker immediately before reserve."""
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
        return bool(ledger_row.get("status") == "REPAIR_AUTHORIZED"
                    and ledger_row.get("repair_authorization", {}).get("approval_basis") == AUTHORITY)
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
