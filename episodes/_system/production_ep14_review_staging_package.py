"""Stage the exact native Codex image-worker prompt for independent content review.

This is intentionally NOT a canonical prompt package and never grants image
execution authority. Neither a draft nor a mere review file may transition a
safety-refused frame to paid Attempt #2. All bytes must be reverified against
the canonical locked storyboard before any future approved binding.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import production_ep14_visual_treatment_preview as treatment

SCHEMA="ep14_review_staging_package_v1"
CANVAS="1080x1350"
# Existing read-only reviewer preview saved after full live MySQL/contract
# verification on 2026-10-27, BEFORE current Docker service interruption.
# Offline fallback NEVER means current MySQL/source checks have passed.
SNAPSHOT_REL=Path("meta/runtime/ep14_visual_treatment_contract_previews_20261027.json")
SNAPSHOT_SHA="d69240759e57258b2278f5845eb8e8ac86a7fa56341a9aecf9557a21d4f2b2e1"

def sha(value:bytes)->str:
    return hashlib.sha256(value).hexdigest()

def canonical_sha(obj)->str:
    return sha(json.dumps(obj,ensure_ascii=False,sort_keys=True,
        separators=(",",":")).encode("utf8"))

def _stage_entry(ep:Path,entry:dict,*,reference_names:tuple[str,...]=(),
                 live_source_verified:bool)->dict:
    frame=int(entry.get("frame") or 0)
    if ep!=treatment.EP.resolve() or frame not in treatment.ORIGINAL:
        raise ValueError("EXACT_EP14_FRAME_SCOPE_REQUIRED")
    old_contract,old_prompt,old_excerpt=treatment.ORIGINAL[frame]
    if (entry.get("old_frame_contract_sha256")!=old_contract
        or entry.get("old_scene_prompt_sha256")!=old_prompt
        or entry.get("old_storyboard_excerpt_sha256")!=old_excerpt
        or entry.get("review_approved") is not False
        or entry.get("production_dispatch_authorized") is not False
        or entry.get("status")!="INDEPENDENT_REVIEW_REQUIRED"):
        raise ValueError("VISUAL_TREATMENT_NOT_EXACTLY_FROZEN_AND_UNAPPROVED")
    image_policy=__import__("image_model_policy")
    # An offline reference is never allowed to dereference MySQL authority.
    # Static repository default is informational until live Episode policy
    # can be reverified. It cannot authorize a paid generation.
    model_policy=(image_policy.for_episode(ep) if live_source_verified
                  else image_policy.resolve_model())
    model=str(model_policy["model"])
    quality=str(model_policy["quality"])
    # Native worker formatter is the authoritative formatting mechanism,
    # instead of inventing a second prompt and overlooking contract blocks.
    import codex_subscription_image as native
    refs=[Path(n) for n in reference_names]
    rendered=native.worker_prompt(
        entry["proposed_scene_prompt"],refs,CANVAS,
        visual_contract=None,
        frame_contract_text=entry["proposed_render_contract_text"],
        image_model=model,image_quality=quality,
        strict_model=bool(model_policy.get("strict_model")),
    )
    if live_source_verified:
        original_excerpt=treatment.frame_contract.compile_frame(
            ep,int(frame),write_cache=False)["storyboard_frame"]["text"]
        if original_excerpt in rendered:
            raise ValueError("REJECTED_ORIGINAL_STORYBOARD_LEAK_IN_WORKER_PROMPT")
    if "脱敏生图 Prompt" in rendered:
        raise ValueError("REJECTED_ORIGINAL_STORYBOARD_LEAK_IN_WORKER_PROMPT")
    if "NOT YET AUTHORIZED" not in rendered:
        raise ValueError("UNAPPROVED_RENDER_CONTRACT_MUST_REMAIN_VISIBLE")
    material={
        "schema_version":SCHEMA,
        "frame":int(frame),
        "original_frame_contract_sha256":entry["old_frame_contract_sha256"],
        "original_storyboard_excerpt_sha256":entry["old_storyboard_excerpt_sha256"],
        "original_scene_prompt_sha256":entry["old_scene_prompt_sha256"],
        "candidate_render_contract_sha256":entry["proposed_render_contract_sha256"],
        "candidate_scene_prompt_sha256":sha(entry["proposed_scene_prompt"].encode("utf8")),
        "full_native_worker_prompt_sha256":sha(rendered.encode("utf8")),
        "model":model,"quality":quality,"canvas":CANVAS,
        "strict_model":bool(model_policy.get("strict_model")),
        "reference_names":[x.name for x in refs],
    }
    return {
        **material,
        "staging_package_sha256":canonical_sha(material),
        "review_status":"AWAITING_INDEPENDENT_SEMANTIC_AND_CONTENT_REVIEW",
        "render_contract_status":"DRAFT_NOT_CANONICAL",
        "live_source_authority_verified":live_source_verified,
        "episode_model_policy_verified":live_source_verified,
        "scene_prompt":entry["proposed_scene_prompt"],
        "full_native_worker_prompt":rendered,
        "story_beats_to_preserve":entry["preserved_story_beats"],
        "independent_review_requirements":[
            "verify_original_episode_story_semantics_and_role_consistency",
            "verify_provider_content_policy_for_entire_native_prompt",
            "verify_reference_image_scope_and_text_overlay_authority",
            "freeze_reviewed_scene_and_render_contract_sha",
            "bind_canonical_frame_and_prompt_package_with_independent_approval",
            "confirm_billed_attempt_1_and_remaining_paid_attempt_2",
        ],
        "review_approved":False,
        "dispatch_authorized":False,
        "paid_generation_calls":0,
        "mysql_writes":0,
        "authority_writes":0,
    }

def stage(ep:Path,frame:int,*,reference_names:tuple[str,...]=())->dict:
    ep=Path(ep).resolve()
    # This path performs an independent live canonical Frame Contract check.
    entry=treatment.compile_candidate(ep,int(frame))
    return _stage_entry(ep,entry,reference_names=reference_names,
                        live_source_verified=True)


def stage_all_offline(ep:Path)->dict:
    """Read-only archived snapshot for offline semantic review, NEVER dispatch.

    The stored artifact was produced under the live authority earlier. It is
    SHA-pinned but cannot replace CURRENT Mysql/queue/Attempt verification.
    """
    ep=Path(ep).resolve()
    if ep!=treatment.EP.resolve():
        raise ValueError("EXACT_EP14_FRAME_SCOPE_REQUIRED")
    source=ep/SNAPSHOT_REL
    if not source.is_file() or sha(source.read_bytes())!=SNAPSHOT_SHA:
        raise ValueError("IMMUTABLE_REVIEW_SNAPSHOT_MISSING_OR_CHANGED")
    snapshot=json.loads(source.read_text("utf8"))
    entries=snapshot.get("frames") or []
    if (snapshot.get("review_status")!="PENDING" or len(entries)!=3
        or {int(x.get("frame") or 0) for x in entries}!={9,29,48}):
        raise ValueError("ARCHIVED_REVIEW_PREVIEW_NOT_EXACT_FRAME_SET")
    rows=[_stage_entry(ep,e,live_source_verified=False)
          for e in sorted(entries,key=lambda x:int(x["frame"]))]
    return _bundle(rows,offline=True)


def _bundle(rows:list[dict],*,offline:bool)->dict:
    return {
        "schema_version":SCHEMA,
        "scope":"EP14_F009_F029_F048_OFFLINE_REVIEW_ONLY",
        "frames":rows,
        "bundle_sha256":canonical_sha({str(x["frame"]):x["staging_package_sha256"] for x in rows}),
        "independent_review_status":"PENDING",
        "production_dispatch_authorized":False,
        "live_source_authority_verified":not offline,
        "archived_snapshot_sha256":SNAPSHOT_SHA if offline else None,
        "paid_generation_calls":0,
        "mysql_writes":0,
    }


def stage_all(ep:Path)->dict:
    rows=[stage(ep,f) for f in (9,29,48)]
    return _bundle(rows,offline=False)