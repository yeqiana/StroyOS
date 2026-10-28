"""Version-bound candidate for Episode14's three safety-refused render alternatives.

This prepares the future canonical revision without writing an image Attempt,
a queue row, a Frame Contract, or a prompt package. It deliberately cannot
promote an unreviewed text preview. The image worker still rejects all three
frames until independently verified review and a separate atomic activation.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import production_ep14_review_staging_package as staging
import production_ep14_visual_treatment_preview as treatment

SCHEMA="ep14_reviewed_render_binding_proposal_v1"
FRAMES=frozenset({9,29,48})


def _sha(data:bytes)->str:
    return hashlib.sha256(data).hexdigest()


def _json_sha(data:dict)->str:
    return _sha(json.dumps(data,ensure_ascii=False,sort_keys=True,
                           separators=(",",":")).encode("utf-8"))


def draft_binding(staged:dict)->dict:
    """Construct a versioned NEW render identity; no old contract substitution."""
    frame=int(staged.get("frame") or 0)
    if (frame not in FRAMES
        or staged.get("review_approved") is not False
        or staged.get("dispatch_authorized") is not False
        or staged.get("review_status")!="AWAITING_INDEPENDENT_SEMANTIC_AND_CONTENT_REVIEW"
        or staged.get("render_contract_status")!="DRAFT_NOT_CANONICAL"
        or staged.get("live_source_authority_verified") is not True
        or staged.get("episode_model_policy_verified") is not True):
        raise ValueError("LIVE_UNAPPROVED_SOURCE_REQUIRED_FOR_RELOCK_DRAFT")
    original_contract,original_scene,original_excerpt=treatment.ORIGINAL[frame]
    if (staged.get("original_frame_contract_sha256")!=original_contract
        or staged.get("original_scene_prompt_sha256")!=original_scene
        or staged.get("original_storyboard_excerpt_sha256")!=original_excerpt):
        raise ValueError("ORIGINAL_NARRATIVE_AUTHORITY_MISMATCH")
    prompt=str(staged.get("full_native_worker_prompt") or "")
    candidate_scene=str(staged.get("scene_prompt") or "")
    candidate_scene_sha=str(staged.get("candidate_scene_prompt_sha256") or "")
    candidate_contract_sha=str(staged.get("candidate_render_contract_sha256") or "")
    if (not prompt or not candidate_scene
        or "NOT YET AUTHORIZED" not in prompt
        or "脱敏生图 Prompt" in prompt
        or _sha(candidate_scene.encode("utf8"))!=candidate_scene_sha
        or _sha(prompt.encode("utf8"))!=staged.get("full_native_worker_prompt_sha256")
        or not all(len(str(x))==64 for x in (
            candidate_contract_sha,staged.get("staging_package_sha256") or ""))):
        raise ValueError("PROPOSED_NATIVE_PROMPT_SHA_OR_REVIEW_MARKER_INVALID")
    material={
        "schema_version":SCHEMA,
        "frame":frame,
        "original_frame_contract_sha256":original_contract,
        "original_storyboard_frame_sha256":original_excerpt,
        "original_scene_prompt_sha256":original_scene,
        "alternative_render_contract_sha256":candidate_contract_sha,
        "alternative_scene_prompt_sha256":candidate_scene_sha,
        "staging_package_sha256":staged["staging_package_sha256"],
        "model":staged.get("model"),
        "quality":staged.get("quality"),
        "canvas":staged.get("canvas"),
    }
    # This names a proposed NEW render variant. Never replace the historical
    # Resolved Frame Contract SHA (it remains the narrative authority).
    version_sha=_json_sha(material)
    return {
        **material,
        "render_variant_sha256":version_sha,
        "binding_proposal_sha256":_json_sha({**material,"version":version_sha}),
        "scene_prompt":candidate_scene,
        "proposed_render_contract_sha256":candidate_contract_sha,
        "producer_preview_prompt_sha256":staged["full_native_worker_prompt_sha256"],
        "required_independent_review": {
            "subject_staging_package_sha256":staged["staging_package_sha256"],
            "subject_full_native_worker_prompt_sha256":staged["full_native_worker_prompt_sha256"],
            "subject_render_variant_sha256":version_sha,
            "must_review_final_model_controller_output":True,
            "must_reverify_actual_image_references":True,
            "approved":False,
        },
        "status":"READY_FOR_SEPARATE_INDEPENDENT_REVIEW",
        "authoritative_frame_contract_modified":False,
        "canonical_prompt_package_written":False,
        "production_dispatch_authorized":False,
        "model_calls":0,"mysql_writes":0,"paid_attempts_reserved":0,
    }


def attach_verified_review_evidence(materials: list[dict], reviewed: dict) -> list[dict]:
    """Read-only, SHA-bound per-variant text-review evidence; never production approval."""
    for material in materials:
        material.pop("verified_text_review_receipt", None)
    if not isinstance(reviewed,dict):
        return materials
    if (reviewed.get("status") !=
            "VERIFIED_INDEPENDENT_TEXT_REVIEW_NOT_PRODUCTION_ADMISSION"
            or reviewed.get("reviewed_frame_count") != len(FRAMES)
            or reviewed.get("production_dispatch_authorized") is not False):
        return materials
    records = reviewed.get("frames") or []
    if not isinstance(records,list):
        return materials
    if (len(records) != len(FRAMES)
            or {x.get("frame") for x in records} != FRAMES):
        return materials
    by_frame = {x["frame"]: x for x in records}
    for material in materials:
        row = by_frame[material["frame"]]
        expected_scope = ("EP14_INDEPENDENT_NATIVE_REVIEW_V7_F029"
                          if material["frame"] == 29 else
                          "EP14_F048_V8_FULL_NATIVE_WORKER_INDEPENDENT_REVIEW"
                          if material["frame"] == 48 else "EP14_INDEPENDENT_NATIVE_REVIEW_V4")
        if (row.get("scope") != expected_scope
                or not all(isinstance(row.get(k), str)
                           and len(row[k]) == 64
                           and all(c in "0123456789abcdef" for c in row[k])
                           for k in ("request_sha256", "runner_log_sha256"))):
            return materials
        if (row.get("subject_full_native_worker_prompt_sha256") !=
                material["producer_preview_prompt_sha256"]
                or not all(len(str(row.get(x) or "")) == 64
                           for x in ("request_sha256", "runner_log_sha256"))
                or material["production_dispatch_authorized"] is not False):
            return materials
    for material in materials:
        row = by_frame[material["frame"]]
        binding = {
            "render_variant_sha256": material["render_variant_sha256"],
            "review_request_sha256": row["request_sha256"],
            "native_runner_log_sha256": row["runner_log_sha256"],
            "reviewed_worker_prompt_sha256": row[
                "subject_full_native_worker_prompt_sha256"],
            "scope": row["scope"],
        }
        material["verified_text_review_receipt"] = {
            **binding,
            "text_review_binding_sha256": _json_sha(binding),
            "status": "TEXT_REVIEW_VERIFIED_NOT_FINAL_CONTROLLER_APPROVAL",
            "production_dispatch_authorized": False,
        }
    return materials


def inspect_episode(ep:Path)->dict:
    ep=Path(ep).resolve()
    if ep!=treatment.EP.resolve():
        raise ValueError("EXACT_EP14_SCOPE_REQUIRED")
    import scheduler_core
    import generation_attempt_authority as attempts
    import logical_asset_identity
    import runtime_driver
    q=scheduler_core.load_queue(ep)
    rows=[x for x in q.get("items") or [] if x.get("scope")=="batch"]
    if (len(rows)!=44
        or sum(x.get("status")=="generated" for x in rows)!=41
        or {int(x.get("frame") or 0) for x in rows
            if x.get("status")=="external_blocked"}!=FRAMES):
        raise ValueError("HISTORICAL_45_IMAGE_QUEUE_NOT_INTACT")
    d=runtime_driver.status(ep)
    if d.get("liveness")!="DEAD" or int(d.get("pid") or 0)!=0:
        raise ValueError("DRIVER_MUST_BE_STOPPED_FOR_REVIEW")
    materials=[]
    staged_rows=[]
    for frame in sorted(FRAMES):
        row=next(x for x in rows if int(x.get("frame") or 0)==frame)
        key=logical_asset_identity.frame_asset_key(ep,frame)
        state=attempts.load_asset_state(ep,key) or {}
        old=attempts.load_attempt(ep,key,1) or {}
        if (row.get("no_automatic_original_prompt_retry") is not True
            or row.get("requires_content_revision") is not True
            or int(state.get("attempts_consumed") or 0)!=1
            or state.get("active_attempt_index") is not None
            or bool(attempts.load_attempt(ep,key,2))
            or old.get("status")!="FAILED_AFTER_DISPATCH"
            or old.get("failure_class")!="IMAGE_PROVIDER_SAFETY_REJECTED"):
            raise ValueError("SAFETY_REVIEW_OR_ATTEMPT_HISTORY_DRIFT")
        staged=staging.stage(ep,frame)
        staged_rows.append(staged)
        materials.append(draft_binding(staged))
    import production_ep14_independent_review_evidence as evidence
    reviewed=evidence.inspect(ep,staged_rows)
    materials=attach_verified_review_evidence(materials,reviewed)
    return {
        "schema_version":SCHEMA,
        "status":"REVIEW_HANDOFF_READY_NOT_PRODUCTION_READY",
        "independent_text_review_evidence":reviewed,
        "independent_text_review_verified":(
            len(materials)==len(FRAMES) and all(
                item.get("verified_text_review_receipt",{}).get("status")==
                "TEXT_REVIEW_VERIFIED_NOT_FINAL_CONTROLLER_APPROVAL"
                for item in materials)),
        "remaining_production_gates":[
            "FINAL_MODEL_CONTROLLER_OUTPUT_INDEPENDENT_APPROVAL",
            "CANONICAL_RENDER_VARIANT_AND_PROMPT_PACKAGE_ATOMIC_ACTIVATION",
            "ACTUAL_IMAGE_REFERENCES_AND_PROVIDER_ENTITLEMENT",
            "DRIVER_RC24_RECOVERY_AND_ATTEMPT2_AUTHORIZATION",
        ],
        "frames":materials,
        "bundle_sha256":_json_sha({str(x["frame"]):x["binding_proposal_sha256"] for x in materials}),
        "historical_generated_frames_preserved":45,
        "independent_review_approved":False,
        "production_dispatch_authorized":False,
        "model_calls":0,"mysql_writes":0,"paid_attempts_reserved":0,
    }