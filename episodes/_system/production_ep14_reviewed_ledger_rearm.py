"""Rearm EP14 F009 after audited historical technical failure, without losing history.

This is a scoped one-shot Production Ledger authorization, not a third image
Attempt or a Provider entitlement. The source of repair remains the immutable
three-frame MySQL activation and its independently approved image contract.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import generation_attempt_authority as attempts
import logical_asset_identity as identity
import production_ep14_canonical_activation as active
import production_ledger as ledger
import scheduler_core

FRAME = 9
EXPECTED_ERROR = (
    "PROMPT_SOURCE_DRIFT: queue scene prompt changed after admission; rebuild queue item"
)
STATUS = "EP14_F009_REVIEWED_REPAIR_LEDGER_AUTHORIZED_AND_QUEUED"
AUTHORITY = "EP14_F009_FINAL_REVIEWED_CONTENT_REVISION_V1"


class RearmDenied(ValueError):
    pass


def _sha(document):
    return hashlib.sha256(json.dumps(
        document, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()


def _require_budget(ep):
    key = identity.frame_asset_key(ep, FRAME)
    state = attempts.load_asset_state(ep, key)
    first = attempts.load_attempt(ep, key, 1) or {}
    second = attempts.load_attempt(ep, key, 2)
    if (state.get("attempts_consumed") != 1
            or state.get("remaining_attempts") != 1
            or state.get("active_attempt_index") is not None
            or first.get("status") != "FAILED_AFTER_DISPATCH"
            or first.get("failure_class") != "IMAGE_PROVIDER_SAFETY_REJECTED"
            or second is not None):
        raise RearmDenied("EP14_F009_PAID_ATTEMPT2_NOT_ELIGIBLE")


def _inspect(ep):
    ep = Path(ep).resolve()
    q = scheduler_core.load_queue(ep)
    marker = q.get(active.QUEUE_KEY) or {}
    if (marker.get("state") != "ACTIVE_THREE_REVIEWED_CONTENT_REVISIONS"
            or marker.get("final_render_bundle_sha256") != active.BUNDLE
            or marker.get("pilot_mode") != "PILOT_FRAME_09_ONLY_REAL_PROVIDER_PROOF"
            or marker.get("pilot_frame") != FRAME
            or marker.get("historical_safety_refusals_preserved") is not True
            or marker.get("postimage_pixel_review_required") is not True):
        raise RearmDenied("EP14_F009_SINGLE_FRAME_PILOT_NOT_ACTIVATED")
    chosen = [x for x in q["items"] if x.get("kind") == "repair"
              and x.get("scope") == "batch" and int(x.get("frame") or 0) == FRAME]
    other = [x for x in q["items"] if x.get("kind") == "repair"
             and x.get("scope") == "batch" and int(x.get("frame") or 0) in (29, 48)]
    if (len(chosen) != 1 or chosen[0].get("id") != active.item_id(FRAME)
            or len(other) != 2 or {int(x["frame"]) for x in other} != {29, 48}
            or any(x.get("status") != "pilot_hold" for x in other)):
        raise RearmDenied("EP14_F009_PILOT_ONLY_QUEUE_ROWS_REQUIRED")
    row = chosen[0]
    if row.get("status") != "blocked" or row.get("last_error") != EXPECTED_ERROR:
        raise RearmDenied("EP14_F009_EXPECTED_SOURCE_DRIFT_BLOCK_NOT_FOUND")
    original = [x for x in q["items"] if x.get("scope") == "batch"
                and x.get("kind") == "original"
                and int(x.get("frame") or 0) == FRAME]
    if (len(original) != 1 or original[0].get("status") != "external_blocked"
            or original[0].get("no_automatic_original_prompt_retry") is not True
            or original[0].get("requires_content_revision") is not True):
        raise RearmDenied("EP14_F009_HISTORICAL_REFUSED_QUEUE_ROW_DRIFT")
    try:
        package = active.load_for_dispatch(ep, row, for_ledger_rearm=True)
    except active.ActivationDenied as exc:
        raise RearmDenied("EP14_F009_ACTIVATED_MYSQL_RENDER_PACKAGE_NOT_VERIFIED") from exc
    _require_budget(ep)
    path, document = ledger.get_ledger(ep)
    key, frame = ledger.frame_obj(document, str(FRAME))
    past = frame.get("attempts") or []
    if (frame.get("status") != "TECH_FAILED"
            or frame.get("content_repairs_used") != 0
            or ledger.content_repair_limit(document) != 1
            or not past
            or past[-1].get("kind") != "original"
            or past[-1].get("result") != "technical_failure"
            or (frame.get("repair_authorization") or {})
            or not package.get("independent_preimage_text_approved")
            or not package.get("postimage_pixel_review_required")
            or package.get("package_sha256") !=
               (row.get("prompt_package") or {}).get("package_sha256")):
        raise RearmDenied("EP14_F009_HISTORICAL_LEDGER_OR_REVIEW_VERSION_DRIFT")
    return {
        "episode": ep, "queue": q, "queue_sha256": _sha(q),
        "ledger_path": path, "ledger": document, "ledger_sha256": _sha(document),
        "row": row, "frame_key": key, "package": package,
        "historical_attempt_ids": [str(x.get("attempt_id")) for x in past],
    }


def plan(ep):
    state = _inspect(ep)
    return {
        "status": "ELIGIBLE_FOR_EP14_F009_REVIEWED_LEDGER_REARM",
        "expected_queue_sha256": state["queue_sha256"],
        "expected_ledger_sha256": state["ledger_sha256"],
        "approved_render_sha256": state["package"]["package_sha256"],
        "queue_item_id": state["row"]["id"],
        "historical_ledger_attempt_count":
            len(state["historical_attempt_ids"]),
        "paid_attempt2_exists": False, "image_generation_called": False,
        "mysql_writes": 0,
    }


def rearm(ep, *, expected_queue_sha256, expected_ledger_sha256):
    if (not isinstance(expected_queue_sha256, str)
            or len(expected_queue_sha256) != 64
            or not isinstance(expected_ledger_sha256, str)
            or len(expected_ledger_sha256) != 64):
        raise RearmDenied("EP14_F009_EXPLICIT_LEDGER_QUEUE_SHA_CAS_REQUIRED")
    ep = Path(ep).resolve()
    with scheduler_core.queue_transaction(ep):
        # The queue lock protects ordinary image scheduling. Re-read all
        # authorities inside the lock; external edited ledgers fail SHA CAS.
        state = _inspect(ep)
        if (state["queue_sha256"] != expected_queue_sha256
                or state["ledger_sha256"] != expected_ledger_sha256):
            raise RearmDenied("EP14_F009_LEDGER_OR_QUEUE_STALE_CAS")
        approved = state["package"]
        frame = state["ledger"]["frames"][state["frame_key"]]
        history_before = deepcopy(frame["attempts"])
        auth = {
            "at": ledger.now_iso(),
            "approval_basis": AUTHORITY,
            "direct_user_production_authorized": True,
            "reviewed_frame": FRAME,
            "new_queue_item_id": state["row"]["id"],
            "mysql_active_package_id": state["row"]["ep14_active_package_id"],
            "render_content_sha256": approved["render_content_sha256"],
            "final_render_bundle_sha256": active.BUNDLE,
            "scene_prompt_sha256": approved["scene_prompt_sha256"],
            "original_provider_safety_rejection_preserved": True,
            "postimage_pixel_review_required": True,
            "historical_attempt_ids": state["historical_attempt_ids"],
            "previous_status": "TECH_FAILED",
            "paid_attempt2_exists_at_authorization": False,
        }
        next_ledger = deepcopy(state["ledger"])
        target = next_ledger["frames"][state["frame_key"]]
        target["status"] = "REPAIR_AUTHORIZED"
        target["repair_authorization"] = auth
        target.setdefault("reviewed_revision_authorizations", []).append(auth)
        next_ledger["updated_at"] = ledger.now_iso()
        if target["attempts"] != history_before:
            raise RearmDenied("EP14_F009_HISTORICAL_LEDGER_ATTEMPTS_CHANGED")
        # MySQL ledger authority is committed before the newly queued worker
        # becomes observable. Failure leaves a blocked queue, not an unproved
        # paid generation. The ledger history is never deleted or rewritten.
        ledger.save_json(state["ledger_path"], next_ledger)
        written = ledger.get_ledger(ep)[1]
        if (written["frames"][state["frame_key"]].get("status") != "REPAIR_AUTHORIZED"
                or written["frames"][state["frame_key"]].get("attempts") != history_before
                or written["frames"][state["frame_key"]].get("repair_authorization") != auth):
            raise RearmDenied("EP14_F009_LEDGER_AUTHORITY_COMMIT_UNVERIFIED")
        latest = scheduler_core.load_queue(ep)
        if _sha(latest) != state["queue_sha256"]:
            raise RearmDenied("EP14_F009_QUEUE_CHANGED_AFTER_LEDGER_WRITE")
        next_queue = deepcopy(latest)
        selected = next(x for x in next_queue["items"] if x.get("id") == state["row"]["id"])
        selected["status"] = "queued"
        selected["last_error"] = None
        selected["ep14_ledger_rearm"] = {
            "approval_basis": AUTHORITY,
            "approved_render_sha256": approved["render_content_sha256"],
            "old_queue_sha256": expected_queue_sha256,
            "old_ledger_sha256": expected_ledger_sha256,
        }
        scheduler_core.save_queue(ep, next_queue)
        after = scheduler_core.load_queue(ep)
        repair = next(x for x in after["items"] if x.get("id") == state["row"]["id"])
        if (repair.get("status") != "queued"
                or repair.get("ep14_ledger_rearm") != selected["ep14_ledger_rearm"]
                or any(x.get("status") != "pilot_hold" for x in after["items"]
                       if x.get("kind") == "repair" and x.get("scope") == "batch"
                       and int(x.get("frame") or 0) in (29, 48))):
            raise RearmDenied("EP14_F009_QUEUE_REARM_COMMIT_UNVERIFIED")
        return {
            "status": STATUS, "frame": FRAME, "queued": True,
            "original_safety_refusal_preserved": True,
            "historical_ledger_attempt_count": len(history_before),
            "other_frames_held": [29, 48],
            "paid_attempts_reserved": 0, "image_generation_called": False,
        }
