"""Stage three EP14 *reviewed* final render packages, without activating them.

The PREIMAGE text authority is now independently approved. This stores the
exact three render contracts in immutable MySQL rows plus SHA-addressed files.
Original IMAGE records, queue safety flags and Generation Attempts are untouched.

This is the last artifact-staging step, NOT a Provider entitlement or image
dispatch authorization. A separate final activation must recheck these SHAs.
"""
from __future__ import annotations

from pathlib import Path

import production_ep14_final_render_subject as final_subject
import production_ep14_preimage_text_review_evidence as independent
import production_ep14_mysql_candidate_stage as candidates
import production_ep14_render_queue_stage as queue_stage
import runtime_workspace
import scheduler_core

from platform.repository.mysql.payload_policy import (
    bounded_json, document_reference, payload_sha256, prompt_package_projection,
)
from platform.repository.mysql.mysql_prompt_package_repository import (
    MySqlPromptPackageRepository, _package_id,
)

PACKAGE_TYPE = "IMAGE_RENDER_APPROVED"
STATUS = "THREE_REVIEWED_FINAL_MYSQL_PACKAGES_STAGED_NOT_ACTIVATED"


class ReviewedStageDenied(ValueError):
    pass


def _safe_state(ep: Path) -> dict:
    ep = Path(ep).resolve()
    proof = independent.inspect(ep)
    final = final_subject.prepare(ep)
    queue = scheduler_core.load_queue(ep)
    marker = queue.get(queue_stage.QUEUE_KEY) or {}
    if (proof.get("status") !=
            "VERIFIED_INDEPENDENT_PREIMAGE_TEXT_REVIEW_POSTIMAGE_REQUIRED"
            or proof.get("independent_preimage_text_approved") is not True
            or proof.get("postimage_pixel_review_required") is not True
            or proof.get("production_dispatch_authorized") is not False
            or final.get("production_dispatch_authorized") is not False
            or marker.get("state") != "STAGED_BLOCKED"
            or marker.get("production_dispatch_authorized") is not False
            or final.get("final_render_bundle_sha256") !=
                proof.get("final_render_bundle_sha256")):
        raise ReviewedStageDenied("EP14_FINAL_INDEPENDENT_PREIMAGE_APPROVAL_REQUIRED")
    by_frame = {int(x["frame"]): x for x in final.get("frames", [])}
    by_review = {int(x["frame"]): x for x in proof.get("frames", [])}
    if set(by_frame) != {9,29,48} or set(by_review) != set(by_frame):
        raise ReviewedStageDenied("EP14_REVIEWED_FINAL_THREE_FRAMES_REQUIRED")
    episode_id = candidates._episode_id(ep)
    records = []
    for frame in sorted(by_frame):
        subject = by_frame[frame]
        review = by_review[frame]
        content_sha = subject["render_content_sha256"]
        if (review.get("decision") != "APPROVE"
                or review.get("render_content_sha256") != content_sha
                or subject.get("canonical_activation") is not False
                or subject.get("production_dispatch_authorized") is not False
                or not queue_stage._is_sha(content_sha)
                or subject.get("frame_contract_sha256") is None
                or "text" in subject.get("storyboard_source", {})
                or subject["storyboard_source"].get("render_original_text_injected") is not False):
            raise ReviewedStageDenied("EP14_FINAL_FRAME_ORIGINAL_OR_REVIEW_SHA_INVALID")
        # The approved exact contract is a durable immutable artifact. Its
        # original source and approved per-frame render SHA remain enumerable.
        payload = {
            "schema_version": "ep14_reviewed_final_image_package_v1",
            "frame": f"{frame:02d}",
            "render_content_sha256": content_sha,
            "final_render_bundle_sha256": final["final_render_bundle_sha256"],
            "controller_runner_log_sha256": proof["controller_runner_log_sha256"],
            "independent_runner_log_sha256": proof["independent_runner_log_sha256"],
            "frame_contract_sha256": subject["frame_contract_sha256"],
            "render_variant_sha256": subject["render_variant_sha256"],
            "source_candidate_package_sha256": subject["source_candidate_package_sha256"],
            "storyboard_source": subject["storyboard_source"],
            "scene_prompt": subject["scene_prompt"],
            "scene_prompt_sha256": subject["scene_prompt_sha256"],
            "frame_prompt_contract": subject["frame_prompt_contract"],
            "image_model": subject["image_model"],
            "independent_preimage_text_approved": True,
            "postimage_pixel_review_required": True,
            "canonical_activation": False,
            "production_dispatch_authorized": False,
            "provider_entitlement_verified": False,
        }
        rel = (
            f"meta/runtime/prompt-packages/reviewed-final/"
            f"{frame:02d}-{payload_sha256(payload)}.json"
        )
        reference = document_reference(payload, rel)
        projection = prompt_package_projection(payload, reference)
        bounded_json(projection, entity="EP14 reviewed final package projection")
        records.append({
            "frame": frame,
            "id": _package_id(episode_id, frame, PACKAGE_TYPE, content_sha),
            "sha": content_sha,
            "payload": payload,
            "reference": reference,
            "projection": projection,
        })
    return {
        "status": "REVIEWED_FINAL_MYSQL_STAGE_ELIGIBLE_NOT_ACTIVATED",
        "expected_queue_sha256": queue_stage._sha(queue),
        "final_render_bundle_sha256": final["final_render_bundle_sha256"],
        "candidate_bundle_sha256": final["candidate_bundle_sha256"],
        "independent_runner_log_sha256": proof["independent_runner_log_sha256"],
        "records": records,
        "production_dispatch_authorized": False,
        "image_generation_called": False,
        "mysql_writes": 0,
    }


def plan(ep: Path) -> dict:
    data = _safe_state(Path(ep))
    return {
        "status": data["status"],
        "expected_queue_sha256": data["expected_queue_sha256"],
        "final_render_bundle_sha256": data["final_render_bundle_sha256"],
        "candidate_bundle_sha256": data["candidate_bundle_sha256"],
        "independent_runner_log_sha256": data["independent_runner_log_sha256"],
        "reviewed_final_ids": [r["id"] for r in data["records"]],
        "production_dispatch_authorized": False,
        "mysql_writes": 0,
    }


def _verify_row(repo, ep: Path, record: dict) -> None:
    row = repo.get_by_id(record["id"])
    if (not row
            or row.get("prompt_package_id") != record["id"]
            or row.get("episode_id") != candidates._episode_id(ep)
            or int(row.get("frame_no") or 0) != record["frame"]
            or row.get("package_type") != PACKAGE_TYPE
            or row.get("sha256") != record["sha"]
            or row.get("payload") != record["projection"]):
        raise ReviewedStageDenied("EP14_REVIEWED_FINAL_MYSQL_RECORD_DRIFT")
    ref = row["payload"].get("document") or {}
    full = runtime_workspace.read_json(ep, ref.get("rel"), default=None)
    if (not isinstance(full, dict)
            or full != record["payload"]
            or payload_sha256(full) != record["reference"]["sha256"]):
        raise ReviewedStageDenied("EP14_REVIEWED_FINAL_DOCUMENT_SHA_MISMATCH")


def persist(ep: Path, *, expected_queue_sha256: str,
            expected_final_render_bundle_sha256: str) -> dict:
    ep = Path(ep).resolve()
    if (not queue_stage._is_sha(expected_queue_sha256)
            or not queue_stage._is_sha(expected_final_render_bundle_sha256)):
        raise ReviewedStageDenied("EP14_REVIEWED_FINAL_EXPLICIT_CAS_REQUIRED")
    # IMPORTANT: independent.inspect calls final_subject.prepare which uses
    # queue_transaction internally, so obtain review proof OUTSIDE this lock.
    state = _safe_state(ep)
    if (state["expected_queue_sha256"] != expected_queue_sha256
            or state["final_render_bundle_sha256"] !=
                expected_final_render_bundle_sha256):
        raise ReviewedStageDenied("EP14_REVIEWED_FINAL_INPUT_VERSION_CHANGED")
    with scheduler_core.queue_transaction(ep):
        queue = scheduler_core.load_queue(ep)
        marker = queue.get(queue_stage.QUEUE_KEY) or {}
        if (queue_stage._sha(queue) != expected_queue_sha256
                or marker.get("state") != "STAGED_BLOCKED"
                or marker.get("production_dispatch_authorized") is not False):
            raise ReviewedStageDenied("EP14_REVIEWED_FINAL_QUEUE_CAS_CHANGED")
        for record in state["records"]:
            rel = record["reference"]["rel"]
            previous = runtime_workspace.read_json(ep, rel, default=None)
            if previous is not None and previous != record["payload"]:
                raise ReviewedStageDenied("EP14_REVIEWED_FINAL_IMMUTABLE_DOCUMENT_COLLISION")
            if previous is None:
                runtime_workspace.write_json(ep, rel, record["payload"])
            if runtime_workspace.read_json(ep, rel, default=None) != record["payload"]:
                raise ReviewedStageDenied("EP14_REVIEWED_FINAL_DOCUMENT_WRITE_NOT_VERIFIED")
        db = candidates._open_db()
        try:
            with db.transaction():
                repo = MySqlPromptPackageRepository(db)
                for record in state["records"]:
                    db.execute(
                        "INSERT IGNORE INTO TB_PROMPT_PACKAGE "
                        "(PROMPT_PACKAGE_ID,EPISODE_ID,FRAME_NO,PACKAGE_TYPE,SHA256,PAYLOAD) "
                        "VALUES (%s,%s,%s,%s,%s,%s)",
                        (record["id"], candidates._episode_id(ep), record["frame"],
                         PACKAGE_TYPE, record["sha"],
                         bounded_json(record["projection"], entity="EP14 reviewed final")),
                    )
                    _verify_row(repo, ep, record)
            if queue_stage._sha(scheduler_core.load_queue(ep)) != expected_queue_sha256:
                raise ReviewedStageDenied("EP14_REVIEWED_FINAL_QUEUE_DRIFT_AFTER_COMMIT")
            return {
                "status": STATUS,
                "frames": [r["frame"] for r in state["records"]],
                "final_render_bundle_sha256": state["final_render_bundle_sha256"],
                "reviewed_final_ids": [r["id"] for r in state["records"]],
                "canonical_activation": False,
                "production_dispatch_authorized": False,
                "image_generation_called": False,
                "paid_attempts_reserved": 0,
            }
        finally:
            db.close()


def verify(ep: Path) -> dict:
    ep = Path(ep).resolve()
    data = _safe_state(ep)
    db = candidates._open_db()
    try:
        repo = MySqlPromptPackageRepository(db)
        for record in data["records"]:
            _verify_row(repo, ep, record)
        return {
            "status": "VERIFIED_THREE_REVIEWED_FINAL_MYSQL_PACKAGES_NOT_ACTIVATED",
            "frames": [r["frame"] for r in data["records"]],
            "final_render_bundle_sha256": data["final_render_bundle_sha256"],
            "reviewed_final_ids": [r["id"] for r in data["records"]],
            "production_dispatch_authorized": False,
            "mysql_writes": 0,
        }
    finally:
        db.close()
