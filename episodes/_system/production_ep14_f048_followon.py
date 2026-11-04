"""EP14 F048 independent reviewed render release, after F029 real pixel preview.

Never promote F009 REPAIR_NOW or F029 PASS_PREVIEW to final approval. A
single SHA- and ledger-bound release preserves historical Provider refusals.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import generation_attempt_authority as attempts
import logical_asset_identity as identity
import production_batch_review as review
import production_ep14_canonical_activation as activation
import production_ep14_followon_release as f029
import production_ledger as ledger
import scheduler_core

FRAME = 48
ITEM_ID = "04977a8a5c30"
F029_BATCH = "EP14_F029_PIXELS_V1"
F048_BATCH = "EP14_F048_PIXELS_V1"
F029_PIXEL_SHA = "d040df9dacc4f2018b41b728a3ed20bcbe0322d6fb4d47d8ed8ad012e50d7842"
AUTHORITY = "EP14_F048_INDEPENDENT_REVIEWED_RENDER_FOLLOWON_V1"


class ReleaseDenied(ValueError):
    pass


def _digest(data):
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def _episode(ep):
    ep = Path(ep).resolve()
    if ep.name != "14_深渊疗愈所_第一集_净土生命还原" or ep.parent.name != "00_独立篇":
        raise ReleaseDenied("EP14_F048_EXACT_EPISODE_REQUIRED")
    return ep


def _source(ep, rows, marker):
    """Require unchanged F009 failure and independent, pixel-bound F029 preview."""
    f029._previous_provider_and_review(ep, rows)
    preceding = rows[29]
    if (preceding.get("id") != f029.NEXT_FRAME_ID
            or preceding.get("status") != "generated"
            or preceding.get("batch_id") != F029_BATCH
            or (preceding.get("vision_batch_review") or {}).get("decision") != "PASS_PREVIEW"
            or marker.get("followon_active_frame") != 29
            or marker.get("followon_authority") != f029.AUTHORITY
            or marker.get("followon_pending_final_review") is not True):
        raise ReleaseDenied("EP14_F048_F029_PREVIEW_NOT_BOUND")
    output = preceding.get("output_path")
    source = Path(output or "")
    if not source.is_absolute():
        source = review.ROOT / source
    source = source.resolve()
    if (not source.is_relative_to(ep)
            or source != (ep / "media/candidates/scheduled/29-6f4a6433f2b9-a5.png").resolve()
            or not source.is_file()
            or hashlib.sha256(source.read_bytes()).hexdigest() != F029_PIXEL_SHA):
        raise ReleaseDenied("EP14_F048_F029_SOURCE_PIXEL_DRIFT")
    final = review.read_json(review.final_path(ep, F029_BATCH))
    units = final.get("frames") or []
    provenance = final.get("critic_provenance") or {}
    if (final.get("batch_id") != F029_BATCH
            or final.get("review_scope") != "EARLY_BATCH_ACTUAL_PIXELS"
            or final.get("final_pass_authority") is not False
            or len(units) != 1
            or units[0].get("frame") != "29"
            or units[0].get("decision") != "PASS_PREVIEW"
            or units[0].get("candidate_sha256") != F029_PIXEL_SHA
            or provenance.get("runtime") != "CODEX_ISOLATED"
            or provenance.get("session_reused_from_generation") is not False
            or review.unit_binding(ep, preceding).get("frame_contract_sha256")
                != units[0].get("frame_contract_sha256")
            or not review._valid_unit(units[0])):
        raise ReleaseDenied("EP14_F048_F029_INDEPENDENT_VISION_NOT_VERIFIED")
    result = attempts.load_attempt(ep, identity.frame_asset_key(ep, 29), 2) or {}
    state = attempts.load_asset_state(ep, identity.frame_asset_key(ep, 29))
    f029_frame = ledger.frame_obj(ledger.get_ledger(ep)[1], "29")[1]
    if (result.get("status") != "SUCCEEDED"
            or result.get("provider") != "codex_subscription"
            or int(state.get("attempts_consumed") or 0) != 2
            or state.get("active_attempt_index") is not None
            or f029_frame.get("status") != "REPAIR_READY"
            or (f029_frame.get("current_candidate") or {}).get("sha256") != F029_PIXEL_SHA):
        raise ReleaseDenied("EP14_F048_F029_REAL_PROVIDER_AND_LEDGER_NOT_VERIFIED")
    return {"frame": 29, "pixel_sha256": F029_PIXEL_SHA, "review": "PASS_PREVIEW",
            "final_pass": False, "f009_status": "NEEDS_USER"}


def _budget(ep):
    key = identity.frame_asset_key(ep, FRAME)
    state = attempts.load_asset_state(ep, key)
    first = attempts.load_attempt(ep, key, 1) or {}
    second = attempts.load_attempt(ep, key, 2)
    if (int(state.get("attempts_consumed") or 0) != 1
            or int(state.get("remaining_attempts") or 0) != 1
            or state.get("active_attempt_index") is not None
            or first.get("status") != "FAILED_AFTER_DISPATCH"
            or first.get("failure_class") != "IMAGE_PROVIDER_SAFETY_REJECTED"
            or second is not None):
        raise ReleaseDenied("EP14_F048_PAID_ATTEMPT2_NOT_SAFE")


def _inspect(ep):
    ep = _episode(ep)
    q = scheduler_core.load_queue(ep)
    marker = q.get(activation.QUEUE_KEY) or {}
    rows = f029._queue_selected(q)
    row = rows[FRAME]
    if (marker.get("state") != "ACTIVE_THREE_REVIEWED_CONTENT_REVISIONS"
            or marker.get("final_render_bundle_sha256") != activation.BUNDLE
            or marker.get("production_dispatch_authorized") is not True
            or marker.get("historical_safety_refusals_preserved") is not True
            or marker.get("postimage_pixel_review_required") is not True
            or marker.get("f048_followon_authority") is not None
            or marker.get("f048_active_frame") is not None
            or row.get("id") != ITEM_ID
            or row.get("kind") != "repair"
            or row.get("scope") != "batch"
            or row.get("status") != "pilot_hold"
            or row.get("output_path")
            or int(row.get("attempts") or 0) != 1
            or row.get("f048_followon_authority")
            or rows[9].get("status") != "scout_repair"):
        raise ReleaseDenied("EP14_F048_HELD_QUEUE_OR_MARKER_DRIFT")
    originals = [x for x in q.get("items", [])
                 if x.get("kind") == "original"
                 and x.get("scope") == "batch"
                 and int(x.get("frame") or 0) == FRAME]
    if (len(originals) != 1
            or originals[0].get("status") != "external_blocked"
            or originals[0].get("requires_content_revision") is not True
            or originals[0].get("no_automatic_original_prompt_retry") is not True):
        raise ReleaseDenied("EP14_F048_HISTORICAL_REFUSAL_MUST_REMAIN_BLOCKED")
    source = _source(ep, rows, marker)
    package = activation.load_for_dispatch(ep, row, for_followon=True)
    if (package.get("independent_preimage_text_approved") is not True
            or package.get("postimage_pixel_review_required") is not True
            or package.get("package_sha256") != (row.get("prompt_package") or {}).get("package_sha256")
            or row.get("ep14_active_bundle_sha256") != activation.BUNDLE):
        raise ReleaseDenied("EP14_F048_RENDER_PACKAGE_NOT_REVIEWED")
    _budget(ep)
    path, doc = ledger.get_ledger(ep)
    key, frame = ledger.frame_obj(doc, str(FRAME))
    history = frame.get("attempts") or []
    if (frame.get("status") != "TECH_FAILED"
            or int(frame.get("content_repairs_used") or 0) != 0
            or ledger.content_repair_limit(doc) != 1
            or frame.get("repair_authorization")
            or len(history) != 2
            or any(event.get("kind") != "original"
                   or event.get("result") != "technical_failure" for event in history)):
        raise ReleaseDenied("EP14_F048_HISTORICAL_LEDGER_DRIFT")
    return {"ep": ep, "queue": q, "queue_sha": _digest(q),
            "ledger": doc, "ledger_sha": _digest(doc), "ledger_path": path,
            "frame_key": key, "history": deepcopy(history), "row": row,
            "package": package, "source": source}


def plan(ep):
    s = _inspect(ep)
    return {"status": "EP14_F048_INDEPENDENT_PIXEL_BOUND_RELEASE_ELIGIBLE",
            "expected_queue_sha256": s["queue_sha"],
            "expected_ledger_sha256": s["ledger_sha"],
            "source_pixel_sha256": F029_PIXEL_SHA,
            "target_frame": FRAME, "preserved_f009": "REPAIR_NOW_NEEDS_USER",
            "f029_final_pass": False, "paid_attempt2_exists": False,
            "image_generation_called": False}


def release(ep, *, expected_queue_sha256, expected_ledger_sha256):
    ep = _episode(ep)
    if (not isinstance(expected_queue_sha256, str) or len(expected_queue_sha256) != 64
            or not isinstance(expected_ledger_sha256, str) or len(expected_ledger_sha256) != 64):
        raise ReleaseDenied("EP14_F048_EXPLICIT_CAS_REQUIRED")
    with scheduler_core.queue_transaction(ep):
        s = _inspect(ep)
        if (s["queue_sha"] != expected_queue_sha256
                or s["ledger_sha"] != expected_ledger_sha256):
            raise ReleaseDenied("EP14_F048_QUEUE_OR_LEDGER_STALE")
        auth = {"at": ledger.now_iso(),
                "approval_basis": AUTHORITY,
                "direct_user_production_authorized": True,
                "reviewed_frame": FRAME, "queue_item_id": ITEM_ID,
                "mysql_active_package_id": s["row"]["ep14_active_package_id"],
                "render_content_sha256": s["package"]["render_content_sha256"],
                "scene_prompt_sha256": s["package"]["scene_prompt_sha256"],
                "final_render_bundle_sha256": activation.BUNDLE,
                "source_pixel_sha256": F029_PIXEL_SHA,
                "source_pixel_review": "PASS_PREVIEW",
                "source_final_pass": False,
                "f009_content_review_unresolved": True,
                "historical_original_attempts_preserved": True,
                "postimage_pixel_review_required": True,
                "paid_attempt2_reserved": False}
        doc = deepcopy(s["ledger"])
        frame = doc["frames"][s["frame_key"]]
        frame["status"] = "REPAIR_AUTHORIZED"
        frame["repair_authorization"] = auth
        frame.setdefault("reviewed_revision_authorizations", []).append(auth)
        doc["updated_at"] = ledger.now_iso()
        ledger.save_json(s["ledger_path"], doc)
        verified = ledger.frame_obj(ledger.get_ledger(ep)[1], str(FRAME))[1]
        if (verified.get("status") != "REPAIR_AUTHORIZED"
                or verified.get("attempts") != s["history"]
                or verified.get("repair_authorization") != auth):
            raise ReleaseDenied("EP14_F048_LEDGER_AUTHORIZATION_NOT_COMMITTED")
        current = scheduler_core.load_queue(ep)
        if _digest(current) != s["queue_sha"]:
            raise ReleaseDenied("EP14_F048_QUEUE_CHANGED_AFTER_LEDGER_COMMIT")
        q = deepcopy(current)
        row = next(x for x in q["items"] if x.get("id") == ITEM_ID)
        row["status"] = "queued"
        row["batch_id"] = F048_BATCH
        row["f048_followon_authority"] = AUTHORITY
        row["f048_followon_source_pixel_sha256"] = F029_PIXEL_SHA
        marker = q[activation.QUEUE_KEY]
        marker["f048_active_frame"] = FRAME
        marker["f048_followon_authority"] = AUTHORITY
        marker["f048_previous_pixel_sha256"] = F029_PIXEL_SHA
        marker["f048_previous_review_decision"] = "PASS_PREVIEW"
        marker["f048_pending_final_review"] = True
        scheduler_core.save_queue(ep, q)
        after = scheduler_core.load_queue(ep)
        selected = f029._queue_selected(after)
        if (selected[FRAME].get("status") != "queued"
                or selected[FRAME].get("batch_id") != F048_BATCH
                or selected[29].get("status") != "generated"
                or selected[9].get("status") != "scout_repair"
                or after[activation.QUEUE_KEY].get("f048_active_frame") != FRAME):
            raise ReleaseDenied("EP14_F048_QUEUE_COMMIT_NOT_VERIFIED")
        return {"status": "EP14_F048_REVIEWED_FOLLOWON_QUEUED",
                "queued_frame": FRAME, "f009_content_review": "NEEDS_USER",
                "f029_pixel_review": "PASS_PREVIEW",
                "paid_attempts_reserved": 0, "image_generation_called": False}




def _ledger_binding_rearm_inspect(ep):
    """One-time retry of a deterministic *pre-Ledger* activation rejection."""
    ep = _episode(ep)
    q = scheduler_core.load_queue(ep)
    marker = q.get(activation.QUEUE_KEY) or {}
    rows = f029._queue_selected(q)
    row = rows[FRAME]
    if (row.get("id") != ITEM_ID
            or row.get("scope") != "batch" or row.get("kind") != "repair"
            or row.get("status") != "blocked"
            or row.get("last_error") != "EP14_REVIEWED_LEDGER_BINDING_DENIED: ActivationDenied"
            or int(row.get("attempts") or 0) != 1
            or int(row.get("f048_ledger_binding_rearm_count") or 0) != 0
            or row.get("output_path")
            or row.get("batch_id") != F048_BATCH
            or row.get("f048_followon_authority") != AUTHORITY
            or row.get("f048_followon_source_pixel_sha256") != F029_PIXEL_SHA
            or marker.get("f048_active_frame") != FRAME
            or marker.get("f048_followon_authority") != AUTHORITY
            or marker.get("f048_previous_pixel_sha256") != F029_PIXEL_SHA
            or marker.get("f048_previous_review_decision") != "PASS_PREVIEW"
            or marker.get("f048_pending_final_review") is not True
            or rows[29].get("status") != "generated"
            or rows[9].get("status") != "scout_repair"):
        raise ReleaseDenied("EP14_F048_LEDGER_BINDING_REARM_QUEUE_DRIFT")
    _source(ep, rows, marker)
    _budget(ep)
    path, doc = ledger.get_ledger(ep)
    _, frame = ledger.frame_obj(doc, str(FRAME))
    auth = frame.get("repair_authorization") or {}
    history = frame.get("attempts") or []
    if (frame.get("status") != "REPAIR_AUTHORIZED"
            or int(frame.get("content_repairs_used") or 0) != 0
            or len(history) != 2
            or any(h.get("kind") != "original" or h.get("result") != "technical_failure"
                   for h in history)
            or auth.get("approval_basis") != AUTHORITY
            or auth.get("queue_item_id") != ITEM_ID
            or auth.get("source_pixel_sha256") != F029_PIXEL_SHA
            or auth.get("postimage_pixel_review_required") is not True
            or auth.get("paid_attempt2_reserved") is not False):
        raise ReleaseDenied("EP14_F048_LEDGER_BINDING_REARM_LEDGER_DRIFT")
    if list((ep / "meta/image-workers").glob(f"48-{ITEM_ID}-a*.lifecycle.json")):
        raise ReleaseDenied("EP14_F048_WORKER_LIFECYCLE_ALREADY_EXISTS")
    if not row.get("f048_ledger_binding_rearm_count") in (None, 0):
        raise ReleaseDenied("EP14_F048_LEDGER_BINDING_REARM_ALREADY_USED")
    candidate = deepcopy(row)
    candidate["status"] = "queued"
    candidate["last_error"] = None
    proposed = deepcopy(q)
    chosen = next(x for x in proposed["items"] if x.get("id") == ITEM_ID)
    chosen.update(candidate)
    # Validate the prospective snapshot without mutating global loaders.
    # The actual queue/ledger CAS below remains the write authority.
    activation.load_for_dispatch(ep, deepcopy(chosen), queue_snapshot=proposed)
    return {"queue": q, "queue_sha": _digest(q),
            "ledger_sha": _digest(doc)}


def ledger_binding_rearm_plan(ep):
    s = _ledger_binding_rearm_inspect(ep)
    return {"status": "EP14_F048_VERIFIED_PRELEDGER_BINDING_REARM_ELIGIBLE",
            "expected_queue_sha256": s["queue_sha"],
            "expected_ledger_sha256": s["ledger_sha"],
            "provider_image_calls": 0, "paid_attempt2_exists": False}


def ledger_binding_rearm(ep, *, expected_queue_sha256, expected_ledger_sha256):
    ep = _episode(ep)
    if any(not isinstance(value, str) or len(value) != 64
           for value in (expected_queue_sha256, expected_ledger_sha256)):
        raise ReleaseDenied("EP14_F048_LEDGER_BINDING_REARM_CAS_REQUIRED")
    with scheduler_core.queue_transaction(ep):
        s = _ledger_binding_rearm_inspect(ep)
        if (s["queue_sha"] != expected_queue_sha256
                or s["ledger_sha"] != expected_ledger_sha256):
            raise ReleaseDenied("EP14_F048_LEDGER_BINDING_REARM_STALE_CAS")
        q = deepcopy(s["queue"])
        row = next(x for x in q["items"] if x.get("id") == ITEM_ID)
        row["status"] = "queued"
        row["f048_ledger_binding_rearm_count"] = 1
        row["f048_ledger_binding_rearm"] = {
            "approval_basis": AUTHORITY,
            "previous_failure": "EP14_REVIEWED_LEDGER_BINDING_DENIED: ActivationDenied",
            "prior_ledger_attempt_count": 2,
            "source_pixel_sha256": F029_PIXEL_SHA,
            "paid_attempt2_reserved": False,
            "authorized_at": ledger.now_iso(),
        }
        row["last_error"] = None
        row.pop("technical_failure_code", None)
        row.pop("completed_at", None)
        row.pop("execution", None)
        row.pop("external_block", None)
        scheduler_core.save_queue(ep, q)
        after = scheduler_core.load_queue(ep)
        selected = next(x for x in after["items"] if x.get("id") == ITEM_ID)
        if (selected.get("status") != "queued"
                or selected.get("f048_ledger_binding_rearm_count") != 1
                or not dispatch_authorized(ep, selected,
                                           after.get(activation.QUEUE_KEY) or {})):
            raise ReleaseDenied("EP14_F048_LEDGER_BINDING_REARM_COMMIT_INVALID")
        return {"status": "EP14_F048_PRELEDGER_REQUEUED",
                "queued_frame": FRAME, "paid_attempts_reserved": 0,
                "image_generation_called": False}

def dispatch_authorized(ep, item, marker):
    """Worker gate for F048, independently checked before provider reserve."""
    if (item.get("id") != ITEM_ID or int(item.get("frame") or 0) != FRAME
            or item.get("status") not in {"queued", "running"}
            or item.get("kind") != "repair" or item.get("scope") != "batch"
            or item.get("batch_id") != F048_BATCH
            or item.get("f048_followon_authority") != AUTHORITY
            or item.get("f048_followon_source_pixel_sha256") != F029_PIXEL_SHA
            or marker.get("f048_active_frame") != FRAME
            or marker.get("f048_followon_authority") != AUTHORITY
            or marker.get("f048_previous_pixel_sha256") != F029_PIXEL_SHA
            or marker.get("f048_previous_review_decision") != "PASS_PREVIEW"
            or marker.get("f048_pending_final_review") is not True):
        return False
    try:
        ep = _episode(ep)
        q = scheduler_core.load_queue(ep)
        rows = f029._queue_selected(q)
        if rows[FRAME] != item:
            return False
        _source(ep, rows, q.get(activation.QUEUE_KEY) or {})
        frame = ledger.frame_obj(ledger.get_ledger(ep)[1], str(FRAME))[1]
        auth = frame.get("repair_authorization") or {}
        if (auth.get("approval_basis") != AUTHORITY
                or auth.get("queue_item_id") != ITEM_ID
                or auth.get("source_pixel_sha256") != F029_PIXEL_SHA
                or auth.get("final_render_bundle_sha256") != activation.BUNDLE
                or auth.get("postimage_pixel_review_required") is not True):
            return False
        history = frame.get("attempts") or []
        if item.get("status") == "queued":
            return bool(frame.get("status") == "REPAIR_AUTHORIZED"
                        and len(history) == 2 and all(
                            event.get("kind") == "original" for event in history))
        pending = history[-1] if history else {}
        transaction = str((item.get("execution") or {}).get("transaction_id") or "")
        return bool(frame.get("status") == "REPAIRING"
                    and len(history) == 3
                    and int(item.get("attempts") or 0) == 2
                    and transaction
                    and pending.get("runtime_transaction_id") == transaction
                    and pending.get("kind") == "repair"
                    and pending.get("result") == "pending"
                    and (pending.get("provider_attempt") or {}).get("status") == "NOT_INVOKED"
                    and all(event.get("kind") == "original" for event in history[:-1]))
    except Exception:
        return False
