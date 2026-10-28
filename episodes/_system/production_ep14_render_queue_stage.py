"""Stage the EP14 three-frame render revision under the canonical queue lock.

This writes ONLY non-dispatchable SHA metadata. It does not activate a Prompt
Package, clear a Provider safety refusal, reserve an Attempt, or start a Driver.
That separate authority transition must be implemented and reviewed before
any image attempt can be dispatched.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import scheduler_core

FRAMES = frozenset((9, 29, 48))
SCHEMA = "ep14_render_bundle_queue_stage_v1"
ROW_KEY = "ep14_render_revision_stage"
QUEUE_KEY = "ep14_render_revision_stage"


class StageDenied(ValueError):
    pass


def _sha(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":")).encode("utf8")
    return hashlib.sha256(raw).hexdigest()


def _is_sha(value: object) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(ch in "0123456789abcdef" for ch in value))


def _queue_rows(q: dict) -> dict[int, dict]:
    rows = [r for r in q.get("items", []) if
            r.get("scope") == "batch" and int(r.get("frame") or 0) in FRAMES]
    if (len(rows) != 3 or {int(r["frame"]) for r in rows} != FRAMES
            or len({r.get("id") for r in rows}) != 3
            or any(r.get("kind") != "original"
                   or r.get("status") != "external_blocked"
                   or r.get("requires_content_revision") is not True
                   or r.get("no_automatic_original_prompt_retry") is not True
                   or not isinstance(r.get("prompt_package"), dict)
                   or not _is_sha(r["prompt_package"].get("package_sha256"))
                   for r in rows)):
        raise StageDenied("HISTORICAL_SAFETY_REFUSED_QUEUE_MUST_REMAIN_BLOCKED")
    return {int(r["frame"]): r for r in rows}


def _prepare(ep: Path, q: dict, evidence: dict) -> dict:
    if (evidence.get("status") != "REVIEW_HANDOFF_READY_NOT_PRODUCTION_READY"
            or evidence.get("independent_text_review_verified") is not True
            or evidence.get("noncanonical_controller_output_review_verified") is not True
            or evidence.get("production_dispatch_authorized") is not False
            or evidence.get("canonical_render_prompt_packages_activated") is not False
            or evidence.get("reviewed_render_prompt_package_proposal_status") !=
                "THREE_FRAME_REVIEWED_PACKAGE_PROPOSAL_NOT_CANONICAL"
            or not _is_sha(evidence.get("reviewed_render_prompt_package_bundle_sha256"))):
        raise StageDenied("EP14_THREE_FRAME_REVIEW_OR_PACKAGE_BUNDLE_MISSING")
    by_queue = _queue_rows(q)
    candidates = evidence.get("frames")
    if (not isinstance(candidates, list) or len(candidates) != 3
            or {int(c.get("frame") or 0) for c in candidates} != FRAMES):
        raise StageDenied("EP14_THREE_FRAME_CANDIDATES_INCOMPLETE")
    binding = []
    for material in sorted(candidates, key=lambda m: int(m["frame"])):
        frame = int(material["frame"])
        queue_row = by_queue[frame]
        old_package = queue_row["prompt_package"]
        text_review = material.get("verified_text_review_receipt") or {}
        controller_review = material.get("verified_noncanonical_controller_draft_receipt") or {}
        if (text_review.get("status") !=
                "TEXT_REVIEW_VERIFIED_NOT_FINAL_CONTROLLER_APPROVAL"
                or controller_review.get("status") != "REVIEWED_PREVIEW_ONLY_NOT_CANONICAL"
                or controller_review.get("production_dispatch_authorized") is not False
                or material.get("production_dispatch_authorized") is not False
                or not _is_sha(material.get("reviewed_render_prompt_package_proposal_sha256"))
                or not _is_sha(material.get("render_variant_sha256"))
                or not _is_sha(material.get("producer_preview_prompt_sha256"))
                or queue_row.get("prompt_package", {}).get("frame_contract_sha256") !=
                    material.get("original_frame_contract_sha256")
                or text_review.get("reviewed_worker_prompt_sha256") !=
                    material.get("producer_preview_prompt_sha256")
                or controller_review.get("render_variant_sha256") !=
                    material.get("render_variant_sha256")):
            raise StageDenied(f"FRAME_{frame:02d}_OLD_PACKAGE_OR_REVIEW_DRIFT")
        binding.append({
            "frame": frame,
            "queue_item_id": queue_row["id"],
            "original_prompt_package_sha256": old_package["package_sha256"],
            "render_variant_sha256": material["render_variant_sha256"],
            "reviewed_native_worker_sha256": material["producer_preview_prompt_sha256"],
            "reviewed_render_package_sha256":
                material["reviewed_render_prompt_package_proposal_sha256"],
            "controller_preview_sha256": controller_review["controller_scene_sha256"],
        })
    marker_body = {
        "schema_version": SCHEMA,
        "state": "STAGED_BLOCKED",
        "bundle_sha256": evidence["reviewed_render_prompt_package_bundle_sha256"],
        "frames": binding,
        "original_provider_refusals_preserved": True,
        "canonical_prompt_packages_activated": False,
        "production_dispatch_authorized": False,
        "paid_attempts_reserved": 0,
    }
    return {**marker_body, "binding_sha256": _sha(marker_body)}


def plan(ep: Path) -> dict:
    """Return read-only queue CAS input; no side effects."""
    import production_ep14_render_relock_preflight as relock
    ep = Path(ep).resolve()
    q = scheduler_core.load_queue(ep)
    evidence = relock.inspect_episode(ep)
    marker = _prepare(ep, q, evidence)
    return {
        "status": "READY_TO_STAGE_BUT_NOT_TO_PRODUCE",
        "expected_queue_sha256": _sha(q),
        "render_bundle_sha256": marker["bundle_sha256"],
        "stage_binding_sha256": marker["binding_sha256"],
        "already_staged": q.get(QUEUE_KEY) == marker,
        "production_dispatch_authorized": False,
        "image_generation_called": False,
        "mysql_writes": 0,
    }


def stage(ep: Path, *, expected_queue_sha256: str,
          expected_render_bundle_sha256: str) -> dict:
    """CAS one blocked queue document under the existing cross-process lock."""
    import production_ep14_render_relock_preflight as relock
    ep = Path(ep).resolve()
    if not _is_sha(expected_queue_sha256) or not _is_sha(expected_render_bundle_sha256):
        raise StageDenied("EXPLICIT_QUEUE_AND_BUNDLE_CAS_HASHES_REQUIRED")
    with scheduler_core.queue_transaction(ep):
        q = scheduler_core.load_queue(ep)
        if _sha(q) != expected_queue_sha256:
            raise StageDenied("EP14_QUEUE_CHANGED_SINCE_STAGING_PLAN")
        evidence = relock.inspect_episode(ep)
        marker = _prepare(ep, q, evidence)
        if marker["bundle_sha256"] != expected_render_bundle_sha256:
            raise StageDenied("EP14_RENDER_BUNDLE_CHANGED_SINCE_STAGING_PLAN")
        rows = _queue_rows(q)
        previously = q.get(QUEUE_KEY)
        if previously is not None:
            if previously != marker:
                raise StageDenied("EP14_EXISTING_QUEUE_STAGE_HAS_DIFFERENT_AUTHORITY")
            for bound in marker["frames"]:
                stored = rows[bound["frame"]].get(ROW_KEY)
                if stored != {
                    "status": "STAGED_BLOCKED",
                    "stage_binding_sha256": marker["binding_sha256"],
                    "render_package_sha256": bound["reviewed_render_package_sha256"],
                    "production_dispatch_authorized": False,
                }:
                    raise StageDenied("EP14_EXISTING_QUEUE_STAGE_FRAME_DRIFT")
            return {
                "status": "ALREADY_STAGED_BLOCKED",
                "stage_binding_sha256": marker["binding_sha256"],
                "bundle_sha256": marker["bundle_sha256"],
                "idempotent": True,
                "production_dispatch_authorized": False,
                "paid_attempts_reserved": 0,
            }
        if any(ROW_KEY in row for row in rows.values()):
            raise StageDenied("EP14_PARTIAL_QUEUE_STAGE_ALREADY_PRESENT")
        modified = deepcopy(q)
        by_frame = _queue_rows(modified)
        modified[QUEUE_KEY] = marker
        for bound in marker["frames"]:
            by_frame[bound["frame"]][ROW_KEY] = {
                "status": "STAGED_BLOCKED",
                "stage_binding_sha256": marker["binding_sha256"],
                "render_package_sha256": bound["reviewed_render_package_sha256"],
                "production_dispatch_authorized": False,
            }
        # No queue status, retry flag, prompt path, historical package or
        # Attempt is modified. The three SHA annotations commit together.
        scheduler_core.save_queue(ep, modified)
        saved = scheduler_core.load_queue(ep)
        if saved.get(QUEUE_KEY) != marker:
            raise StageDenied("EP14_STAGE_WRITE_NOT_VERIFIED")
        by_saved = _queue_rows(saved)
        if any(by_saved[b["frame"]].get(ROW_KEY) !=
               by_frame[b["frame"]][ROW_KEY] for b in marker["frames"]):
            raise StageDenied("EP14_STAGE_ROW_WRITE_NOT_VERIFIED")
        return {
            "status": "STAGED_BLOCKED_NOT_CANONICAL",
            "stage_binding_sha256": marker["binding_sha256"],
            "bundle_sha256": marker["bundle_sha256"],
            "frames": [r["frame"] for r in marker["frames"]],
            "production_dispatch_authorized": False,
            "paid_attempts_reserved": 0,
            "canonical_prompt_packages_activated": False,
        }


def preview_worker_source(ep: Path, item: dict) -> dict:
    """Read-only Worker handoff; verify the live queue, all three frames and SHAs.

    Caller MUST NOT dispatch with this material: only STAGED_BLOCKED is
    supported. A forged row flag, stale Worker copy, or a newer bundle fails
    closed instead of falling back to the old prompt file.
    """
    import production_ep14_render_relock_preflight as relock
    import production_ep14_render_package as render_package
    import production_ep14_review_staging_package as candidate_stage

    ep = Path(ep).resolve()
    frame = int(item.get("frame") or 0)
    if frame not in FRAMES or item.get("scope") != "batch":
        raise StageDenied("EP14_WORKER_STAGE_EXACT_FRAME_AND_SCOPE_REQUIRED")
    queue = scheduler_core.load_queue(ep)
    qrows = _queue_rows(queue)
    original = qrows[frame]
    if (original.get("id") != item.get("id")
            or original.get("prompt_file") != item.get("prompt_file")
            or original.get("prompt_package") != item.get("prompt_package")
            or original.get("status") != item.get("status")
            or item.get("no_automatic_original_prompt_retry") is not True
            or item.get("requires_content_revision") is not True):
        raise StageDenied("EP14_WORKER_SNAPSHOT_NOT_CURRENT_CANONICAL_QUEUE")
    evidence = relock.inspect_episode(ep)
    marker = _prepare(ep, queue, evidence)
    if queue.get(QUEUE_KEY) != marker:
        raise StageDenied("EP14_WORKER_QUEUE_STAGE_MARKER_CAS_DRIFT")
    bindings = {r["frame"]: r for r in marker["frames"]}
    bound = bindings[frame]
    expected_row = {
        "status": "STAGED_BLOCKED",
        "stage_binding_sha256": marker["binding_sha256"],
        "render_package_sha256": bound["reviewed_render_package_sha256"],
        "production_dispatch_authorized": False,
    }
    if original.get(ROW_KEY) != expected_row or item.get(ROW_KEY) != expected_row:
        raise StageDenied("EP14_WORKER_FRAME_STAGE_BINDING_DRIFT")
    for other_bound in marker["frames"]:
        expected_other = {
            "status": "STAGED_BLOCKED",
            "stage_binding_sha256": marker["binding_sha256"],
            "render_package_sha256": other_bound["reviewed_render_package_sha256"],
            "production_dispatch_authorized": False,
        }
        if qrows[other_bound["frame"]].get(ROW_KEY) != expected_other:
            raise StageDenied("EP14_WORKER_THREE_FRAME_ATOMIC_STAGE_DRIFT")
    stages = [candidate_stage.stage(ep, f) for f in sorted(FRAMES)]
    bundle = render_package.compile_bundle(
        ep, stages, evidence["frames"],
        evidence["noncanonical_controller_output_review_evidence"])
    if bundle.get("bundle_sha256") != marker["bundle_sha256"]:
        raise StageDenied("EP14_WORKER_RENDER_BUNDLE_CHANGED")
    package = next(
        (p for p in bundle["frames"] if int(p["frame"]) == frame), None)
    if (not package
            or package.get("package_sha256") != bound["reviewed_render_package_sha256"]
            or package.get("canonical_activation") is not False
            or package.get("production_dispatch_authorized") is not False
            or package.get("storyboard_source", {}).get("render_original_text_injected") is not False):
        raise StageDenied("EP14_WORKER_RENDER_PACKAGE_NOT_THE_REVIEWED_VARIANT")
    return {
        "status": "STAGED_BLOCKED_RENDER_PACKAGE_VERIFIED",
        "frame": frame,
        "bundle_sha256": marker["bundle_sha256"],
        "stage_binding_sha256": marker["binding_sha256"],
        "package_sha256": package["package_sha256"],
        "source": package,
        "canonical_render_activated": False,
        "production_dispatch_authorized": False,
        "image_generation_called": False,
        "mysql_writes": 0,
    }


def load_for_dispatch(ep: Path, item: dict) -> dict:
    """Actual Worker consumer boundary: never dispatch preview-only packages.

    When formal per-Episode canonical activation authority is implemented this
    is the only EP14 entrypoint allowed to return a render package to the
    image Controller. Until then it must not fall through to old Frame Contract.
    """
    preview_worker_source(ep, item)
    raise StageDenied("EP14_CANONICAL_RENDER_ACTIVATION_AND_PROVIDER_ADMISSION_REQUIRED")
