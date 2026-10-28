"""Fail-closed audit of noncanonical EP14 Image Controller drafts + independent reviews.

Read-only. Even three approved drafts DO NOT prove a production Controller
receipt, an activated render variant, a provider entitlement, or Attempt #2.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

FRAMES = (9, 29, 48)
SCHEMA = "ep14_controller_draft_reviews_v1"
_SHA = re.compile(r"^[0-9a-f]{64}$")
BASE = Path("meta/runtime")
CONTROLLER = {
    9: ("ep14_noncanonical_controller_preview_frame09_request_20261028.txt",
        "ep14_noncanonical_controller_preview_frame09_20261028.jsonl"),
    29: ("ep14_noncanonical_controller_preview_frame29_request_20261028.txt",
         "ep14_noncanonical_controller_preview_frame29_20261028.jsonl"),
    48: ("ep14_noncanonical_controller_preview_frame48_v8_request_20261028.txt",
         "ep14_noncanonical_controller_preview_frame48_v8_20261028.jsonl"),
}
BATCH = (
    "ep14_noncanonical_controller_outputs_independent_review_request_20261028.txt",
    "ep14_noncanonical_controller_outputs_independent_review_20261028.jsonl",
)
V8 = (
    "ep14_noncanonical_controller_v8_frame48_independent_review_request_20261028.txt",
    "ep14_noncanonical_controller_v8_frame48_independent_review_20261028.jsonl",
)


class DraftReviewDenied(ValueError):
    pass


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _hex(value: object) -> bool:
    return isinstance(value, str) and _SHA.fullmatch(value) is not None


def _one_completed_text_turn(raw: bytes) -> dict:
    """Skip CLI diagnostics, never skip malformed JSON-looking messages/tools."""
    rows = []
    for line in raw.decode("utf8").splitlines():
        s = line.strip()
        if not s:
            continue
        try:
            event = json.loads(s)
        except (ValueError, TypeError):
            if s.startswith(("{", "[")):
                raise DraftReviewDenied("MALFORMED_JSONL_EVENT")
            continue
        if not isinstance(event, dict):
            raise DraftReviewDenied("NON_OBJECT_JSONL_EVENT")
        rows.append(event)
    if ([x.get("type") for x in rows] !=
            ["thread.started", "turn.started", "item.completed", "turn.completed"]):
        raise DraftReviewDenied("RUNNER_NOT_ONE_COMPLETED_TEXT_TURN")
    item = rows[2].get("item")
    if not isinstance(item, dict) or item.get("type") != "agent_message":
        raise DraftReviewDenied("RUNNER_NON_TEXT_OUTPUT_OR_TOOL_CALL")
    text = item.get("text")
    if not isinstance(text, str):
        raise DraftReviewDenied("RUNNER_MISSING_AGENT_MESSAGE")
    try:
        answer = json.loads(text)
    except (ValueError, TypeError) as exc:
        raise DraftReviewDenied("RUNNER_AGENT_JSON_INVALID") from exc
    if not isinstance(answer, dict):
        raise DraftReviewDenied("RUNNER_AGENT_RESPONSE_NOT_OBJECT")
    return answer


def _requested_subject(raw: bytes, marker: str) -> dict:
    request = raw.decode("utf8").replace("\r\n", "\n")
    if request.count(marker) != 1:
        raise DraftReviewDenied("REVIEW_REQUEST_SUBJECT_MARKER_AMBIGUOUS")
    try:
        result = json.loads(request.split(marker, 1)[1].strip())
    except (ValueError, TypeError) as exc:
        raise DraftReviewDenied("REVIEW_REQUEST_SUBJECT_INVALID") from exc
    if not isinstance(result, dict):
        raise DraftReviewDenied("REVIEW_REQUEST_SUBJECT_NOT_OBJECT")
    return result


def inspect(ep: Path, staged: list[dict]) -> dict:
    """Recheck every candidate/receipt SHA. No production authority is returned."""
    base = Path(ep) / BASE
    try:
        by_frame = {x["frame"]: x for x in staged}
        if len(staged) != len(FRAMES) or set(by_frame) != set(FRAMES):
            raise DraftReviewDenied("EXACT_THREE_FRAME_STAGES_REQUIRED")
        for f in FRAMES:
            s = by_frame[f]
            if (s.get("live_source_authority_verified") is not True
                    or s.get("episode_model_policy_verified") is not True
                    or s.get("review_approved") is not False
                    or s.get("dispatch_authorized") is not False
                    or not _hex(s.get("full_native_worker_prompt_sha256"))
                    or not isinstance(s.get("scene_prompt"), str)):
                raise DraftReviewDenied("LIVE_UNAPPROVED_STAGE_REQUIRED")
        scenes = {}
        controller_log_shas = {}
        controller_request_shas = {}
        for frame in FRAMES:
            req, log = (base / name for name in CONTROLLER[frame])
            request_bytes, log_bytes = req.read_bytes(), log.read_bytes()
            # The preview CLI request itself must describe this CURRENT derived
            # render candidate, not merely contain a successful output.
            # Canonical controller requests use a sorted JSON object after a
            # non-executable preface, so parse the exact frozen JSON payload.
            normalized = request_bytes.decode("utf8").replace("\r\n", "\n")
            prefix = '{\n  "canvas":'
            if normalized.count(prefix) != 1:
                raise DraftReviewDenied("CONTROLLER_PREVIEW_REQUEST_BODY_INVALID")
            request_body = json.loads(normalized[normalized.index(prefix):])
            inp = request_body.get("controller_input") or {}
            frozen = request_body.get("locked_binding") or {}
            if (request_body.get("role") != "image.controller"
                    or frozen.get("controller_model") != "gpt-6-luna"
                    or frozen.get("controller_effort") != "high"
                    or frozen.get("payload_model") != "gpt-image-2.5-flare"
                    or inp.get("preview_only_do_not_commit_or_dispatch") is not True
                    or inp.get("source_scene_prompt") != by_frame[frame]["scene_prompt"]
                    or "NOT YET AUTHORIZED" not in inp.get("frame_prompt_contract", "")
                    or by_frame[frame]["candidate_render_contract_sha256"]
                        not in inp.get("frame_prompt_contract", "")
                    or (request_body.get("references") or []) != []):
                raise DraftReviewDenied("CONTROLLER_PREVIEW_LIVE_STAGE_INPUT_DRIFT")
            controller_request_shas[frame] = sha(request_bytes)
            controller_log_shas[frame] = sha(log_bytes)
            result = _one_completed_text_turn(log_bytes)
            if set(result) != {"scene_prompt"} or not isinstance(result["scene_prompt"], str):
                raise DraftReviewDenied("CONTROLLER_DRAFT_SCHEMA_INVALID")
            scene = result["scene_prompt"].strip()
            if not scene:
                raise DraftReviewDenied("CONTROLLER_DRAFT_SCENE_EMPTY")
            # The original, unactivated stage is recorded separately; the
            # existence of the draft never proves it came from production.
            scenes[frame] = (scene, sha(scene.encode("utf8")))
        batch_req, batch_log = (base / name for name in BATCH)
        batch_req_raw, batch_log_raw = batch_req.read_bytes(), batch_log.read_bytes()
        batch_input = _requested_subject(batch_req_raw, "以下是不可信输入数据：\n")
        reviews = _one_completed_text_turn(batch_log_raw)
        if (reviews.get("scope") != "EP14_NONCANONICAL_CONTROLLER_OUTPUT_INDEPENDENT_REVIEW_20261028"
                or reviews.get("production_dispatch_authorized") is not False
                or reviews.get("canonical_render_activated") is not False
                or reviews.get("provider_entitlement_proven") is not False):
            raise DraftReviewDenied("BATCH_REVIEW_SCOPE_OR_AUTHORITY_INVALID")
        supplied = batch_input.get("frames")
        decisions = reviews.get("frames")
        if (not isinstance(supplied, list) or not isinstance(decisions, list)
                or len(supplied) != 3 or len(decisions) != 3
                or {x.get("frame") for x in supplied} != set(FRAMES)
                or {x.get("frame") for x in decisions} != set(FRAMES)):
            raise DraftReviewDenied("BATCH_REVIEW_FRAME_SET_INVALID")
        input_by_frame = {x["frame"]: x for x in supplied}
        decision_by_frame = {x["frame"]: x for x in decisions}
        for f in (9, 29):
            obj = input_by_frame[f]
            decision = decision_by_frame[f]
            scene, scene_sha = scenes[f]
            if (obj.get("candidate_full_native_worker_prompt_sha256") !=
                    by_frame[f]["full_native_worker_prompt_sha256"]
                    or obj.get("controller_draft_scene_prompt") != scene
                    or obj.get("controller_draft_scene_sha256") != scene_sha
                    or obj.get("request_sha256") != controller_request_shas[f]
                    or obj.get("runner_log_sha256") != controller_log_shas[f]
                    or obj.get("proposed_scene_prompt") != by_frame[f]["scene_prompt"]
                    or decision.get("decision") != "APPROVE"
                    or decision.get("controller_draft_scene_sha256") != scene_sha
                    or decision.get("issues") != []):
                raise DraftReviewDenied("CONTROLLER_REVIEW_SOURCE_OR_APPROVAL_DRIFT")
        # The first review EXPLICITLY rejected the older F048 and must not be
        # allowed to stand in for the separate approved V8 review.
        if decision_by_frame[48].get("decision") != "REVISE":
            raise DraftReviewDenied("F048_OLD_REVIEW_SUPERSESSION_MISSING")
        v8_req, v8_log = (base / name for name in V8)
        req_raw, log_raw = v8_req.read_bytes(), v8_log.read_bytes()
        subject = _requested_subject(req_raw, "下面是只读待审数据：\n")
        approval = _one_completed_text_turn(log_raw)
        scene, scene_sha = scenes[48]
        if (subject.get("frame") != 48
                or subject.get("render_candidate_worker_sha256") != by_frame[48]["full_native_worker_prompt_sha256"]
                or subject.get("render_candidate_scene_prompt") != by_frame[48]["scene_prompt"]
                or subject.get("controller_output_scene_prompt") != scene
                or subject.get("controller_output_scene_sha256") != scene_sha
                or subject.get("editorial_overlay_contract") != by_frame[48].get("editorial_overlay_contract")
                or approval.get("scope") != "EP14_F048_V8_NATIVE_CONTROLLER_OUTPUT_INDEPENDENT_REVIEW"
                or approval.get("frame") != 48
                or approval.get("decision") != "APPROVE"
                or approval.get("issues") != []
                or approval.get("controller_draft_scene_sha256") != scene_sha
                or approval.get("production_dispatch_authorized") is not False
                or approval.get("canonical_render_activated") is not False):
            raise DraftReviewDenied("F048_V8_CONTROLLER_REVIEW_SOURCE_OR_APPROVAL_DRIFT")
        return {
            "schema_version": SCHEMA,
            "status": "VERIFIED_NONCANONICAL_CONTROLLER_REVIEW_NOT_PRODUCTION_ADMISSION",
            "reviewed_frame_count": 3,
            "frames": [
                {
                    "frame": f,
                    "controller_draft_scene_sha256": scenes[f][1],
                    "controller_draft_runner_log_sha256": controller_log_shas[f],
                    "independent_review_runner_log_sha256": sha(
                        batch_log_raw if f != 48 else log_raw),
                    "independent_review_request_sha256": sha(
                        batch_req_raw if f != 48 else req_raw),
                    "subject_full_native_worker_prompt_sha256": by_frame[f]["full_native_worker_prompt_sha256"],
                    "scope": "PREVIEW_ONLY_NOT_CANONICAL",
                }
                for f in FRAMES
            ],
            "canonical_controller_execution_verified": False,
            "render_variant_activated": False,
            "provider_entitlement_verified": False,
            "production_dispatch_authorized": False,
            "model_calls": 0,
            "mysql_writes": 0,
            "paid_attempts_reserved": 0,
        }
    except (DraftReviewDenied, OSError, UnicodeError, TypeError, KeyError, ValueError) as exc:
        return {
            "schema_version": SCHEMA,
            "status": "BLOCKED_NONCANONICAL_CONTROLLER_REVIEW_MISSING_OR_DRIFTED",
            "reason": str(exc)[:200],
            "reviewed_frame_count": 0,
            "production_dispatch_authorized": False,
            "model_calls": 0,
            "mysql_writes": 0,
            "paid_attempts_reserved": 0,
        }
