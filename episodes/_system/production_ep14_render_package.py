
"""Compile EP14 render-revision Prompt Package proposals, never write production."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from typing import Any

import frame_contract
import image_model_policy

SCHEMA = "ep14_render_variant_prompt_package_v1"
FRAMES = frozenset((9, 29, 48))


def _hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _hash_json(value: dict) -> str:
    return _hash_bytes(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                  separators=(",", ":")).encode("utf8"))


def compile_preview(ep: Path, staged: dict, variant: dict,
                    controller_receipt: dict) -> dict[str, Any]:
    """Build a noncanonical package from reviewed DERIVED render-only content.

    This intentionally does not call prompt_package.compile_frame(), which
    would re-inject the original, safety-refused locked Frame Contract as a
    render prompt. All original authored sources and MySQL history stay intact.
    No caller may use the returned package for Provider dispatch until the
    separately controlled canonical activation/review is implemented.
    """
    import production_ep14_visual_treatment_preview as treatment
    ep = Path(ep).resolve()
    frame = int(staged.get("frame") or 0)
    if (ep != treatment.EP.resolve() or frame not in FRAMES
            or int(variant.get("frame") or 0) != frame):
        raise ValueError("EP14_REVIEWED_RENDER_VARIANT_SCOPE_REQUIRED")
    if (staged.get("review_approved") is not False
            or staged.get("dispatch_authorized") is not False
            or variant.get("production_dispatch_authorized") is not False
            or variant.get("canonical_prompt_package_written") is not False):
        raise ValueError("EP14_RENDER_VARIANT_MUST_REMAIN_NONCANONICAL")
    receipt = variant.get("verified_text_review_receipt")
    if (not isinstance(receipt, dict)
            or receipt.get("status") !=
            "TEXT_REVIEW_VERIFIED_NOT_FINAL_CONTROLLER_APPROVAL"
            or receipt.get("production_dispatch_authorized") is not False
            or receipt.get("reviewed_worker_prompt_sha256") !=
                staged.get("full_native_worker_prompt_sha256")):
        raise ValueError("EP14_RENDER_VARIANT_INDEPENDENT_REVIEW_REQUIRED")
    reviewed = variant.get("verified_noncanonical_controller_draft_receipt")
    if (not isinstance(reviewed, dict)
            or reviewed.get("status") != "REVIEWED_PREVIEW_ONLY_NOT_CANONICAL"
            or reviewed.get("production_dispatch_authorized") is not False
            or reviewed.get("render_variant_sha256") != variant.get("render_variant_sha256")
            or reviewed.get("reviewed_native_worker_prompt_sha256") !=
                staged.get("full_native_worker_prompt_sha256")
            or reviewed.get("controller_scene_sha256") !=
                controller_receipt.get("controller_draft_scene_sha256")
            or reviewed.get("controller_runner_log_sha256") !=
                controller_receipt.get("controller_draft_runner_log_sha256")):
        raise ValueError("EP14_RENDER_VARIANT_CONTROLLER_REVIEW_REQUIRED")
    original = frame_contract.compile_frame(ep, frame, write_cache=False)
    original_sha = str(original.get("contract_sha256") or "")
    storyboard = original.get("storyboard_frame") or {}
    original_excerpt = storyboard.get("text")
    original_frame_sha = str(storyboard.get("sha256") or "")
    if (not original_sha
            or original_sha != variant.get("original_frame_contract_sha256")
            or original_sha != staged.get("original_frame_contract_sha256")
            or original_frame_sha != variant.get("original_storyboard_frame_sha256")
            or original_frame_sha != staged.get("original_storyboard_excerpt_sha256")
            or not isinstance(original_excerpt, str)
            or not original_excerpt):
        raise ValueError("EP14_RENDER_ORIGINAL_STORY_AUTHORITY_DRIFT")
    render = treatment.compile_candidate(ep, frame)
    candidate_scene = render.get("proposed_scene_prompt")
    render_text = render.get("proposed_render_contract_text")
    if (not isinstance(candidate_scene, str)
            or not isinstance(render_text, str)
            or candidate_scene != staged.get("scene_prompt")
            or variant.get("alternative_scene_prompt_sha256") !=
                _hash_bytes(candidate_scene.encode("utf8"))
            or render.get("proposed_render_contract_sha256") !=
                variant.get("alternative_render_contract_sha256")
            or render.get("proposed_render_contract_sha256") !=
                staged.get("candidate_render_contract_sha256")):
        raise ValueError("EP14_DERIVED_RENDER_CONTRACT_DRIFT")
    if (original_excerpt in render_text
            or original.get("prompt_contract") == render_text
            or "NOT YET AUTHORIZED" not in render_text
            or "[ALTERNATIVE VISUAL TREATMENT, REVIEW PENDING]" not in render_text):
        raise ValueError("EP14_REJECTED_ORIGINAL_PROMPT_LEAK_OR_FALSE_AUTHORITY")
    model = image_model_policy.for_episode(ep)
    content = {
        "schema_version": 1, "frame": f"{frame:02d}",
        "scene_prompt": candidate_scene,
        "scene_prompt_sha256": _hash_bytes(candidate_scene.encode("utf8")),
        # The original storyboard text may contain the provider-refused
        # instruction. Only its immutable identity survives into Controller
        # input; the historical authored source remains untouched on disk.
        "storyboard_source": {
            "sha256": original_frame_sha,
            "frame": f"{frame:02d}",
            "authority": "LOCKED_ORIGINAL_STORYBOARD_HASH_ONLY",
            "render_original_text_injected": False,
        },
        "frame_contract_sha256": original_sha,
        "frame_prompt_contract": render_text,
        "image_model": model,
        "source_prompt": "EP14_DERIVED_RENDER_VARIANT_NONCANONICAL",
        "render_variant_sha256": variant["render_variant_sha256"],
        "reviewed_native_worker_prompt_sha256": staged["full_native_worker_prompt_sha256"],
        "reviewed_noncanonical_controller_draft_scene_sha256":
            reviewed["controller_scene_sha256"],
        "canonical_activation": False,
        "production_dispatch_authorized": False,
    }
    return {
        **content, "package_sha256": _hash_json(content),
        "status": "REVIEWED_PROPOSED_PACKAGE_NOT_ACTIVATED",
        "canonical_prompt_package_written": False,
        "mysql_writes": 0,
        "paid_attempts_reserved": 0,
    }


def compile_bundle(ep: Path, staged_rows: list[dict],
                   variants: list[dict], verified_controller: dict) -> dict:
    """Deterministic proposed Package bundle, never an activation or dispatch."""
    if (not isinstance(staged_rows, list) or not isinstance(variants, list)
            or len(staged_rows) != 3 or len(variants) != 3
            or not isinstance(verified_controller, dict)
            or verified_controller.get("status") !=
                "VERIFIED_NONCANONICAL_CONTROLLER_REVIEW_NOT_PRODUCTION_ADMISSION"
            or verified_controller.get("production_dispatch_authorized") is not False):
        raise ValueError("EP14_PROMPT_PACKAGE_REVIEW_BUNDLE_INCOMPLETE")
    audited = verified_controller.get("frames")
    if (not isinstance(audited, list) or len(audited) != 3
            or {x.get("frame") for x in staged_rows} != FRAMES
            or {x.get("frame") for x in variants} != FRAMES
            or {x.get("frame") for x in audited} != FRAMES):
        raise ValueError("EP14_PROMPT_PACKAGE_THREE_FRAME_ATOMIC_SCOPE_REQUIRED")
    by_stage = {x["frame"]: x for x in staged_rows}
    by_variant = {x["frame"]: x for x in variants}
    by_audit = {x["frame"]: x for x in audited}
    packages = [compile_preview(ep, by_stage[f], by_variant[f], by_audit[f])
                for f in sorted(FRAMES)]
    binding = {
        "schema_version": SCHEMA,
        "frames": [
            {
                "frame": f,
                "package_sha256": row["package_sha256"],
                "original_frame_contract_sha256": row["frame_contract_sha256"],
                "render_variant_sha256": row["render_variant_sha256"],
                "native_worker_sha256": row["reviewed_native_worker_prompt_sha256"],
                "preview_controller_scene_sha256":
                    row["reviewed_noncanonical_controller_draft_scene_sha256"],
            }
            for f, row in zip(sorted(FRAMES), packages)
        ],
    }
    return {
        "schema_version": SCHEMA,
        "status": "THREE_FRAME_REVIEWED_PACKAGE_PROPOSAL_NOT_CANONICAL",
        "bundle_sha256": _hash_json(binding),
        "frames": packages,
        "canonical_prompt_packages_written": False,
        "production_dispatch_authorized": False,
        "mysql_writes": 0,
        "paid_attempts_reserved": 0,
    }
