"""Atomic EP14 reviewed-revision activation with a fail-closed real Provider gate.

Original safety-refused queue items are immutable. Only three new, hash-bound
repair queue IDs may dispatch after live EXPLICIT_SUPPORTED capability proof.
MySQL active package rows commit before the queue is exposed. Failed queue
commits leave inert SQL records, never a live worker or image Attempt.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path

import codex_subscription_image as backend
import generation_attempt_authority as attempts
import logical_asset_identity as identity
import production_ep14_reviewed_final_mysql_stage as reviewed
import production_ep14_render_queue_stage as staged
import production_ep14_mysql_candidate_stage as candidates
import runtime_workspace
import scheduler_core

from platform.repository.mysql.payload_policy import (
    bounded_json, document_reference, payload_sha256, prompt_package_projection,
)
from platform.repository.mysql.mysql_prompt_package_repository import (
    MySqlPromptPackageRepository, _package_id,
)

QUEUE_KEY = "ep14_approved_render_activation_v1"
ACTIVE_TYPE = "IMAGE_RENDER_ACTIVE"
FRAMES = (9, 29, 48)
BUNDLE = "459256f325b44c6d21d497a0c758acfb66fac31eaaac93c122b854b7662cd6a2"


class ActivationDenied(ValueError):
    pass


def item_id(frame):
    return hashlib.sha256(f"ep14-reviewed:{BUNDLE}:{frame}".encode()).hexdigest()[:12]


def _active_records(ep, rows):
    episode_id = candidates._episode_id(ep)
    result = []
    for record in rows:
        frame = int(record["frame"])
        source = record["payload"]
        if (frame not in FRAMES
                or record["sha"] != source.get("render_content_sha256")
                or source.get("final_render_bundle_sha256") != BUNDLE
                or source.get("canonical_activation") is not False
                or source.get("production_dispatch_authorized") is not False
                or source.get("postimage_pixel_review_required") is not True
                or source.get("independent_preimage_text_approved") is not True
                or "text" in source.get("storyboard_source", {})
                or source.get("storyboard_source", {}).get("render_original_text_injected") is not False):
            raise ActivationDenied("EP14_UNREVIEWED_OR_ORIGINAL_RENDER_PACKAGE")
        payload = {
            **deepcopy(source),
            "package_sha256": record["sha"],
            "canonical_activation": True,
            "production_dispatch_authorized": True,
            "provider_entitlement_verified": True,
            "original_safety_refusal_preserved": True,
        }
        rel = f"meta/runtime/prompt-packages/activated/{frame:02d}-{payload_sha256(payload)}.json"
        ref = document_reference(payload, rel)
        projection = prompt_package_projection(payload, ref)
        bounded_json(projection, entity="EP14 active reviewed prompt")
        result.append({
            "frame": frame,
            "id": _package_id(episode_id, frame, ACTIVE_TYPE, record["sha"]),
            "sha": record["sha"],
            "payload": payload,
            "reference": ref,
            "projection": projection,
        })
    if len(result) != 3 or [x["frame"] for x in result] != list(FRAMES):
        raise ActivationDenied("EP14_ACTIVE_REQUIRES_EXACT_THREE_FRAMES")
    return result


def _plan(ep):
    ep = Path(ep).resolve()
    # One expensive native-review derivation; do not recompute the full
    # Controller and independent SHA chain a second time for the same plan.
    state = reviewed._safe_state(ep)
    if (state.get("final_render_bundle_sha256") != BUNDLE
            or [int(x["frame"]) for x in state.get("records", [])] != list(FRAMES)):
        raise ActivationDenied("EP14_THREE_FINAL_REVIEWED_MYSQL_PACKAGES_REQUIRED")
    q = scheduler_core.load_queue(ep)
    if state.get("expected_queue_sha256") != staged._sha(q):
        raise ActivationDenied("EP14_FINAL_REVIEWED_QUEUE_VERSION_CHANGED")
    if QUEUE_KEY in q:
        raise ActivationDenied("EP14_ALREADY_ACTIVATED_RECONCILE_ONLY")
    originals = staged._queue_rows(q)
    marker = q.get(staged.QUEUE_KEY) or {}
    if (marker.get("state") != "STAGED_BLOCKED"
            or marker.get("production_dispatch_authorized") is not False
            or marker.get("canonical_prompt_packages_activated") is not False
            or not staged._is_sha(marker.get("binding_sha256"))):
        raise ActivationDenied("EP14_ORIGINAL_REFUSAL_QUEUE_BINDING_REQUIRED")
    # Each historic Provider safety refusal must be a verified terminal first
    # Attempt with exactly one remaining paid slot. Never reset or mask it.
    for f in FRAMES:
        key = identity.frame_asset_key(ep, f)
        budget = attempts.load_asset_state(ep, key)
        prior = attempts.load_attempt(ep, key, 1) or {}
        following = attempts.load_attempt(ep, key, 2)
        if (budget.get("attempts_consumed") != 1
                or budget.get("remaining_attempts") != 1
                or budget.get("active_attempt_index") is not None
                or prior.get("status") != "FAILED_AFTER_DISPATCH"
                or prior.get("failure_class") != "IMAGE_PROVIDER_SAFETY_REJECTED"
                or following is not None):
            raise ActivationDenied(f"EP14_FRAME_{f:02d}_SECOND_ATTEMPT_NOT_AUTHORIZED")
    # The complete-Episode Revision authority must not be silently bypassed
    # by a local three-frame activation. This Episode currently has no head.
    db = candidates._open_db()
    try:
        episode_id = candidates._episode_id(ep)
        head = db.query_one(
            "SELECT ACTIVE_REVISION_ID FROM TB_PRODUCTION_REVISION_HEAD WHERE EPISODE_ID=%s",
            (episode_id,))
        older = db.query_one(
            "SELECT PRODUCTION_REVISION_ID FROM TB_PRODUCTION_REVISION WHERE EPISODE_ID=%s LIMIT 1",
            (episode_id,))
        if head is not None or older is not None:
            raise ActivationDenied("EP14_FULL_EPISODE_REVISION_AUTHORITY_MUST_BE_RECONCILED")
        # Validate the three persisted immutable MySQL final packages within
        # this one DB read, with no second 100KiB model-evidence recompilation.
        repo = MySqlPromptPackageRepository(db)
        for record in state["records"]:
            reviewed._verify_row(repo, ep, record)
    finally:
        db.close()
    records = _active_records(ep, state["records"])
    return {
        "queue_sha256": staged._sha(q),
        "final_render_bundle_sha256": BUNDLE,
        "records": records,
        "originals": {f: deepcopy(originals[f]) for f in FRAMES},
        "original_stage_binding_sha256": marker["binding_sha256"],
    }


def plan(ep):
    state = _plan(ep)
    return {
        "status": "READY_FOR_EXPLICIT_PROVIDER_PROOF_NOT_ACTIVATED",
        "expected_queue_sha256": state["queue_sha256"],
        "final_render_bundle_sha256": BUNDLE,
        "mysql_active_ids": [x["id"] for x in state["records"]],
        "production_dispatch_authorized": False,
        "paid_attempts_reserved": 0,
    }


def _require_live_provider_proof(ep=None):
    # Never accept caller-provided JSON, login-only proof or a visibility
    # assertion. Only the real installed native preflight is authoritative.
    proof = backend.payload_capability_preflight(
        model="gpt-image-2.5-flare", quality="high")
    if (proof.get("status") == "BLOCKED"
            and proof.get("failure_class") == "LOGIN_AUTH_IMAGE_TOOL_CAPABILITY_UNKNOWN"):
        # Distinct from a PASS: live native capability RPC + authenticated
        # secondary visibility allow only ONE exactly reviewed F009 Attempt.
        import model_policy
        import production_ep14_native_pilot_proof as pilot
        payload = model_policy.resolve("image.payload", episode=ep)
        controller = model_policy.resolve("image.controller", episode=ep)
        try:
            return pilot.attest_one_frame(proof, payload, controller)
        except pilot.PilotDenied as exc:
            raise ActivationDenied(str(exc)) from exc
    if (proof.get("status") != "PASS"
            or proof.get("tool_capability_state") != "EXPLICIT_SUPPORTED"
            or proof.get("tool_visibility_evidence_level") == "SECONDARY_ATTESTATION"
            or proof.get("payload_model") != "gpt-image-2.5-flare"
            or proof.get("payload_quality") != "high"
            or proof.get("image_generation_called") is not False
            or proof.get("image_attempt_authority_called") is not False):
        raise ActivationDenied("EP14_REAL_PROVIDER_CAPABILITY_NOT_PROVEN:"
                               + str(proof.get("failure_class") or proof.get("status")))
    return proof


def _verify_row(repo, ep, record):
    row = repo.get_by_id(record["id"])
    if (not row or row.get("prompt_package_id") != record["id"]
            or row.get("episode_id") != candidates._episode_id(ep)
            or int(row.get("frame_no") or 0) != record["frame"]
            or row.get("package_type") != ACTIVE_TYPE
            or row.get("sha256") != record["sha"]
            or row.get("payload") != record["projection"]):
        raise ActivationDenied("EP14_ACTIVE_MYSQL_ROW_DRIFT")
    rel = (row["payload"].get("document") or {}).get("rel")
    value = runtime_workspace.read_json(ep, rel, default=None)
    if (value != record["payload"]
            or payload_sha256(value) != record["reference"]["sha256"]):
        raise ActivationDenied("EP14_ACTIVE_PAYLOAD_DOCUMENT_SHA_DRIFT")


def _new_repair_row(original, record, *, pilot_only=False):
    row = deepcopy(original)
    row.update({
        "id": item_id(record["frame"]),
        "kind": "repair",
        "scope": "batch",
        "status": ("pilot_hold" if pilot_only and record["frame"] != 9 else "queued"),
        "attempts": 1,
        "output_path": None,
        "log_path": None,
        "last_error": None,
        "generation_attempt_reason": "REVIEWED_CONTENT_REVISION_AFTER_PROVIDER_REFUSAL",
        "prompt_package": {
            "package_sha256": record["sha"],
            "frame_contract_sha256": record["payload"]["frame_contract_sha256"],
            "scene_prompt_sha256": record["payload"]["scene_prompt_sha256"],
        },
        "ep14_active_package_id": record["id"],
        "ep14_active_bundle_sha256": BUNDLE,
    })
    for key in ("no_automatic_original_prompt_retry", "requires_content_revision",
                staged.ROW_KEY, "technical_failure_code", "technical_retry_source_code"):
        row.pop(key, None)
    return row


def activate(ep, *, expected_queue_sha256, expected_final_render_bundle_sha256):
    ep = Path(ep).resolve()
    if (not staged._is_sha(expected_queue_sha256)
            or expected_final_render_bundle_sha256 != BUNDLE):
        raise ActivationDenied("EP14_ACTIVATION_REQUIRES_EXACT_QUEUE_AND_BUNDLE_SHA")
    initial = _plan(ep)
    if initial["queue_sha256"] != expected_queue_sha256:
        raise ActivationDenied("EP14_ACTIVATION_STALE_QUEUE")
    admission = _require_live_provider_proof(ep)
    pilot_mode = admission.get("trial_scope") == "PILOT_FRAME_09_ONLY_REAL_PROVIDER_PROOF"
    with scheduler_core.queue_transaction(ep):
        q = scheduler_core.load_queue(ep)
        if staged._sha(q) != expected_queue_sha256 or QUEUE_KEY in q:
            raise ActivationDenied("EP14_ACTIVATION_QUEUE_CAS_CHANGED")
        originals = staged._queue_rows(q)
        if any(originals[f] != initial["originals"][f] for f in FRAMES):
            raise ActivationDenied("EP14_ACTIVATION_ORIGINAL_REFUSAL_CHANGED")
        ids = {item_id(f) for f in FRAMES}
        if any(x.get("id") in ids for x in q.get("items", [])):
            raise ActivationDenied("EP14_ACTIVATION_QUEUE_ID_COLLISION")
        for record in initial["records"]:
            rel = record["reference"]["rel"]
            previous = runtime_workspace.read_json(ep, rel, default=None)
            if previous is not None and previous != record["payload"]:
                raise ActivationDenied("EP14_ACTIVATION_DOCUMENT_COLLISION")
            if previous is None:
                runtime_workspace.write_json(ep, rel, record["payload"])
            if runtime_workspace.read_json(ep, rel, default=None) != record["payload"]:
                raise ActivationDenied("EP14_ACTIVATION_DOCUMENT_WRITE_FAILED")
        db = candidates._open_db()
        try:
            with db.transaction():
                repo = MySqlPromptPackageRepository(db)
                for record in initial["records"]:
                    db.execute(
                        "INSERT IGNORE INTO TB_PROMPT_PACKAGE "
                        "(PROMPT_PACKAGE_ID,EPISODE_ID,FRAME_NO,PACKAGE_TYPE,SHA256,PAYLOAD) "
                        "VALUES (%s,%s,%s,%s,%s,%s)",
                        (record["id"], candidates._episode_id(ep), record["frame"],
                         ACTIVE_TYPE, record["sha"],
                         bounded_json(record["projection"], entity="EP14 active")),
                    )
                    _verify_row(repo, ep, record)
            # MySQL rows alone grant nothing. The queue is the final commit.
            new_queue = deepcopy(q)
            for record in initial["records"]:
                new_queue["items"].append(
                    _new_repair_row(originals[record["frame"]], record, pilot_only=pilot_mode))
            new_queue[QUEUE_KEY] = {
                "state": "ACTIVE_THREE_REVIEWED_CONTENT_REVISIONS",
                "final_render_bundle_sha256": BUNDLE,
                "original_queue_sha256": expected_queue_sha256,
                "original_stage_binding_sha256":
                    initial["original_stage_binding_sha256"],
                "frames": [
                    {"frame": r["frame"], "queue_item_id": item_id(r["frame"]),
                     "mysql_active_id": r["id"], "render_sha256": r["sha"]}
                    for r in initial["records"]
                ],
                "historical_safety_refusals_preserved": True,
                "pilot_mode": ("PILOT_FRAME_09_ONLY_REAL_PROVIDER_PROOF" if pilot_mode else None),
                "pilot_frame": (9 if pilot_mode else None),
                "native_provider_capability_sha256": (
                    admission.get("native_provider_capability_sha256") if pilot_mode else None),
                "postimage_pixel_review_required": True,
                "production_dispatch_authorized": True,
            }
            scheduler_core.save_queue(ep, new_queue)
            if scheduler_core.load_queue(ep) != new_queue:
                raise ActivationDenied("EP14_ACTIVATION_QUEUE_COMMIT_UNVERIFIED")
            return {
                "status": "ACTIVATED_THREE_NEW_REVIEWED_REPAIR_IDENTITIES",
                "frames": list(FRAMES),
                "final_render_bundle_sha256": BUNDLE,
                "historical_safety_refusals_preserved": True,
                "production_dispatch_authorized": True,
                "image_generation_called": False,
                "attempts_reserved": 0,
                "provider_trial_only": pilot_mode,
                "pilot_frame": (9 if pilot_mode else None),
                "held_frames": ([29,48] if pilot_mode else []),
            }
        finally:
            db.close()


def load_for_dispatch(ep, item, *, for_ledger_rearm=False):
    ep = Path(ep).resolve()
    frame = int(item.get("frame") or 0)
    allowed_status = {"blocked"} if for_ledger_rearm else {"queued", "running"}
    if (for_ledger_rearm
            and (frame != 9 or item.get("last_error") !=
                 "PROMPT_SOURCE_DRIFT: queue scene prompt changed after admission; rebuild queue item")):
        raise ActivationDenied("EP14_LEDGER_REARM_REQUIRES_EXACT_FRAME09_SOURCE_DRIFT")
    if (frame not in FRAMES or item.get("kind") != "repair"
            or item.get("scope") != "batch"
            or item.get("status") not in allowed_status):
        raise ActivationDenied("EP14_DISPATCH_REQUIRES_NEW_ACTIVATED_REPAIR_ROW")
    q = scheduler_core.load_queue(ep)
    marker = q.get(QUEUE_KEY) or {}
    if (marker.get("state") != "ACTIVE_THREE_REVIEWED_CONTENT_REVISIONS"
            or marker.get("final_render_bundle_sha256") != BUNDLE
            or marker.get("production_dispatch_authorized") is not True
            or marker.get("historical_safety_refusals_preserved") is not True
            or marker.get("postimage_pixel_review_required") is not True):
        raise ActivationDenied("EP14_CANONICAL_QUEUE_ACTIVATION_NOT_FOUND")
    rows = [r for r in q.get("items", []) if
            r.get("scope") == "batch"
            and int(r.get("frame") or 0) in FRAMES]
    old = [r for r in rows if r.get("kind") == "original"]
    active = [r for r in rows if r.get("kind") == "repair"]
    if (len(old) != 3 or len(active) != 3
            or {int(x["frame"]) for x in old} != set(FRAMES)
            or {int(x["frame"]) for x in active} != set(FRAMES)
            or any(x.get("status") != "external_blocked"
                   or x.get("requires_content_revision") is not True
                   or x.get("no_automatic_original_prompt_retry") is not True
                   for x in old)):
        raise ActivationDenied("EP14_ORIGINAL_REFUSAL_OR_REPAIR_ROW_SET_DRIFT")
    bindings = marker.get("frames") or []
    if (not isinstance(bindings, list) or len(bindings) != 3
            or {int(x.get("frame") or 0) for x in bindings} != set(FRAMES)):
        raise ActivationDenied("EP14_ACTIVE_THREE_FRAME_BINDINGS_INCOMPLETE")
    by_frame = {int(x["frame"]): x for x in active}
    for entry in bindings:
        other = by_frame.get(int(entry["frame"]))
        if (not other or other.get("id") != entry.get("queue_item_id")
                or other.get("ep14_active_package_id") != entry.get("mysql_active_id")
                or other.get("ep14_active_bundle_sha256") != BUNDLE
                or other.get("prompt_package", {}).get("package_sha256") != entry.get("render_sha256")):
            raise ActivationDenied("EP14_ACTIVE_THREE_FRAME_ATOMIC_BINDING_DRIFT")
    row = [x for x in active if x.get("id") == item.get("id")
           and int(x["frame"]) == frame]
    binding = [x for x in marker.get("frames", []) if x.get("frame") == frame]
    if (len(row) != 1 or row[0] != item or len(binding) != 1
            or binding[0].get("queue_item_id") != item.get("id")
            or binding[0].get("mysql_active_id") != item.get("ep14_active_package_id")
            or item.get("ep14_active_bundle_sha256") != BUNDLE):
        raise ActivationDenied("EP14_ACTIVE_WORKER_ID_OR_BUNDLE_SHA_DRIFT")
    db = candidates._open_db()
    try:
        record = MySqlPromptPackageRepository(db).get_by_id(
            item["ep14_active_package_id"])
        if (not record or record.get("episode_id") != candidates._episode_id(ep)
                or int(record.get("frame_no") or 0) != frame
                or record.get("package_type") != ACTIVE_TYPE
                or record.get("sha256") != binding[0].get("render_sha256")):
            raise ActivationDenied("EP14_ACTIVE_MYSQL_REVIEWED_ID_NOT_FOUND")
        ref = record["payload"].get("document") or {}
        package = runtime_workspace.read_json(ep, ref.get("rel"), default=None)
        if (not isinstance(package, dict)
                or payload_sha256(package) != ref.get("sha256")
                or package.get("package_sha256") != record.get("sha256")
                or package.get("render_content_sha256") != record.get("sha256")
                or package.get("canonical_activation") is not True
                or package.get("production_dispatch_authorized") is not True
                or package.get("original_safety_refusal_preserved") is not True
                or package.get("postimage_pixel_review_required") is not True
                or package.get("storyboard_source", {}).get(
                    "render_original_text_injected") is not False
                or "text" in package.get("storyboard_source", {})
                or package.get("frame_contract_sha256") !=
                   item.get("prompt_package", {}).get("frame_contract_sha256")
                or package.get("scene_prompt_sha256") !=
                   item.get("prompt_package", {}).get("scene_prompt_sha256")):
            raise ActivationDenied("EP14_ACTIVE_RENDER_SHA_OR_PROVENANCE_DRIFT")
        return package
    finally:
        db.close()
