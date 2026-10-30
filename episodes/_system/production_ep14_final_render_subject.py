"""Prepare the EXACT three EP14 Controller render subjects for final review.

The input is the immutable MySQL candidate bundle, not a mutable preview
fragment. Preapproval markers are removed only from render bytes; no historical
Frame Contract or Provider refusal is changed. These are not activated packages.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re

import production_ep14_mysql_candidate_stage as mysql_candidates
import production_ep14_render_queue_stage as queue_stage
import production_ep14_render_package as render_package
import scheduler_core

SCHEMA = "ep14_final_controller_render_subject_v1"
HEADER = re.compile(
    r"\APROPOSED RENDER TREATMENT \| frame=(09|29|48)"
    r" \| sha256=([0-9a-f]{64}) \| NOT YET AUTHORIZED\n"
)
REVIEW_LINE = "[ALTERNATIVE VISUAL TREATMENT, REVIEW PENDING]"
FINAL_LINE = "[DERIVED VISUAL TREATMENT]"
EXPLANATION = (
    "Treat this section as a proposed visual interpretation only; "
    "source story and exact dialogue remain under separate locked authority."
)
FINAL_EXPLANATION = (
    "The visual treatment applies only to render pixels; "
    "the locked authored story and dialogue remain separate immutable sources."
)


class FinalRenderDenied(ValueError):
    pass


def prepare_one(candidate: dict) -> dict:
    frame = int(candidate.get("frame") or 0)
    if (frame not in queue_stage.FRAMES
            or candidate.get("canonical_activation") is not False
            or candidate.get("production_dispatch_authorized") is not False
            or candidate.get("status") != "REVIEWED_PROPOSED_PACKAGE_NOT_ACTIVATED"
            or candidate.get("canonical_prompt_package_written") is not False):
        raise FinalRenderDenied("EP14_ORIGINAL_PREVIEW_CANDIDATE_REQUIRED")
    original_package_sha = candidate.get("package_sha256")
    if (not queue_stage._is_sha(original_package_sha)
            or not queue_stage._is_sha(candidate.get("frame_contract_sha256"))
            or not queue_stage._is_sha(candidate.get("render_variant_sha256"))
            or not isinstance(candidate.get("storyboard_source"), dict)
            or "text" in candidate["storyboard_source"]
            or candidate["storyboard_source"].get("render_original_text_injected") is not False):
        raise FinalRenderDenied("EP14_RENDER_ORIGINAL_STORY_PROVENANCE_INVALID")
    prompt = candidate.get("frame_prompt_contract")
    if not isinstance(prompt, str):
        raise FinalRenderDenied("EP14_REVIEW_SUBJECT_PROMPT_MISSING")
    hit = HEADER.match(prompt)
    if not hit or int(hit.group(1)) != frame:
        raise FinalRenderDenied("EP14_PREVIEW_RENDER_HEADER_MISMATCH")
    if (prompt.count(REVIEW_LINE) != 1 or prompt.count(EXPLANATION) != 1
            or prompt.count("NOT YET AUTHORIZED") != 1
            or prompt.count("REVIEW PENDING") != 1):
        raise FinalRenderDenied("EP14_RENDER_REVIEW_MARKER_NOT_UNIQUE")
    adjusted = (
        f"DERIVED RENDER CONTRACT | frame={frame:02d}"
        f" | original_candidate_render_sha256={hit.group(2)}\n"
        + prompt[hit.end():]
    )
    adjusted = adjusted.replace(REVIEW_LINE, FINAL_LINE).replace(
        EXPLANATION, FINAL_EXPLANATION)
    if ("NOT YET AUTHORIZED" in adjusted or "REVIEW PENDING" in adjusted
            or "PROPOSED RENDER TREATMENT" in adjusted
            or "LOCKED ORIGINAL STORYBOARD FRAME" in adjusted):
        raise FinalRenderDenied("EP14_UNREVIEWED_OR_ORIGINAL_PROMPT_LEAK")
    if (not isinstance(candidate.get("scene_prompt"), str)
            or not candidate["scene_prompt"].strip()
            or candidate.get("scene_prompt_sha256") !=
                render_package._hash_bytes(candidate["scene_prompt"].encode("utf8"))):
        raise FinalRenderDenied("EP14_DERIVED_SCENE_SHA_DRIFT")
    render_content = {
        "frame": f"{frame:02d}",
        "frame_contract_sha256": candidate["frame_contract_sha256"],
        "storyboard_source": deepcopy(candidate["storyboard_source"]),
        "scene_prompt": candidate["scene_prompt"],
        "scene_prompt_sha256": candidate["scene_prompt_sha256"],
        "frame_prompt_contract": adjusted,
        "image_model": deepcopy(candidate["image_model"]),
        "render_variant_sha256": candidate["render_variant_sha256"],
        "source_candidate_package_sha256": original_package_sha,
    }
    render_sha = render_package._hash_json(render_content)
    return {
        **render_content,
        "render_content_sha256": render_sha,
        "status": "READY_FOR_FINAL_CONTROLLER_OUTPUT_AND_INDEPENDENT_REVIEW",
        "schema_version": SCHEMA,
        "canonical_activation": False,
        "production_dispatch_authorized": False,
        "provider_entitlement_verified": False,
        "final_controller_review_approved": False,
        "mysql_writes": 0,
        "paid_attempts_reserved": 0,
    }


def prepare(ep: Path) -> dict:
    """Read-only, queue-CAS-fenced proof of three MySQL-backed render subjects."""
    ep = Path(ep).resolve()
    with scheduler_core.queue_transaction(ep):
        queue_before = scheduler_core.load_queue(ep)
        expected_queue_sha = queue_stage._sha(queue_before)
        mysql_proof = mysql_candidates.verify(ep)
        state = mysql_candidates._candidate_plan(ep, queue_before)
        if (mysql_proof.get("status") != "VERIFIED_THREE_MYSQL_CANDIDATES_NOT_ACTIVATED"
                or mysql_proof.get("bundle_sha256") != state.get("bundle_sha256")
                or mysql_proof.get("frames") != [9, 29, 48]):
            raise FinalRenderDenied("EP14_MYSQL_CANDIDATE_BUNDLE_NOT_VERIFIED")
        records = state["records"]
        if len(records) != 3:
            raise FinalRenderDenied("EP14_THREE_CANDIDATES_REQUIRED")
        subjects = [prepare_one(row["payload"]) for row in records]
        binding = {
            "schema_version": SCHEMA,
            "candidate_bundle_sha256": state["bundle_sha256"],
            "stage_binding_sha256": state["stage_binding_sha256"],
            "frames": [
                {
                    "frame": int(row["frame"]),
                    "mysql_candidate_id": record["id"],
                    "candidate_package_sha256": record["sha"],
                    "render_content_sha256": row["render_content_sha256"],
                }
                for row, record in zip(subjects, records)
            ],
        }
        final_bundle_sha = render_package._hash_json(binding)
        if queue_stage._sha(scheduler_core.load_queue(ep)) != expected_queue_sha:
            raise FinalRenderDenied("EP14_FINAL_SUBJECT_QUEUE_CHANGED")
        return {
            "schema_version": SCHEMA,
            "status": "THREE_FINAL_CONTROLLER_SUBJECTS_READY_NOT_APPROVED",
            "candidate_bundle_sha256": state["bundle_sha256"],
            "final_render_bundle_sha256": final_bundle_sha,
            "stage_binding_sha256": state["stage_binding_sha256"],
            "frames": subjects,
            "canonical_activation": False,
            "production_dispatch_authorized": False,
            "provider_entitlement_verified": False,
            "final_controller_review_approved": False,
            "mysql_writes": 0,
            "paid_attempts_reserved": 0,
        }
