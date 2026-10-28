"""Read-only SHA binding of EP14 native Codex independent text-review artifacts.

A review decision does not activate a canonical render variant, reserve an
Attempt, or prove the provider can generate an image. Fail closed on every
artifact or source drift.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

FRAMES = (9, 29, 48)
V4 = (
    "ep14_independent_native_content_review_v4_request_20261028.txt",
    "ep14_independent_native_content_review_v4_20261028.jsonl",
)
V7 = (
    "ep14_independent_native_content_review_v7_frame29_request_20261028.txt",
    "ep14_independent_native_content_review_v7_frame29_20261028.jsonl",
)
V8 = (
    "ep14_independent_native_content_review_v8_frame48_request_20261028.txt",
    "ep14_independent_native_content_review_v8_frame48_20261028.jsonl",
)
FRAME_FIELDS = (
    "frame", "full_native_worker_prompt_sha256",
    "original_frame_contract_sha256", "original_scene_prompt_sha256",
    "original_storyboard_excerpt_sha256",
    "candidate_render_contract_sha256", "candidate_scene_prompt_sha256",
    "staging_package_sha256", "model", "quality", "canvas", "strict_model",
    "reference_names",
)


class ReviewEvidenceDenied(ValueError):
    """The text review cannot be bound to the current live render request."""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_last_line(data: bytes) -> dict:
    lines = data.decode("utf-8").splitlines()
    if not lines:
        raise ReviewEvidenceDenied("REVIEW_REQUEST_EMPTY")
    try:
        payload = json.loads(lines[-1])
    except ValueError as exc:
        raise ReviewEvidenceDenied("REVIEW_REQUEST_PAYLOAD_INVALID") from exc
    if not isinstance(payload, dict):
        raise ReviewEvidenceDenied("REVIEW_REQUEST_PAYLOAD_INVALID")
    return payload


def _response(raw: bytes, scope: str) -> dict:
    events = []
    for line in raw.decode("utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except ValueError:
            # Native Codex may prepend diagnostic warnings, never interpreted
            # as review authority.
            continue
        if isinstance(event, dict) and "type" in event:
            events.append(event)
    types = [event["type"] for event in events]
    if (types.count("thread.started") != 1
            or types.count("turn.started") != 1
            or types.count("turn.completed") != 1
            or "turn.failed" in types):
        raise ReviewEvidenceDenied("NATIVE_REVIEW_TURN_NOT_COMPLETED")
    messages = [
        event["item"].get("text")
        for event in events
        if event["type"] == "item.completed"
        and isinstance(event.get("item"), dict)
        and event["item"].get("type") == "agent_message"
    ]
    if len(messages) != 1:
        raise ReviewEvidenceDenied("NATIVE_REVIEW_SINGLE_AGENT_MESSAGE_REQUIRED")
    try:
        answer = json.loads(messages[0])
    except (TypeError, ValueError) as exc:
        raise ReviewEvidenceDenied("NATIVE_REVIEW_ANSWER_INVALID") from exc
    if (not isinstance(answer, dict) or answer.get("scope") != scope
            or answer.get("schema_version") != 1
            or answer.get("production_dispatch_authorized") is not False
            or answer.get("provider_safety_acceptance_guaranteed") is not False):
        raise ReviewEvidenceDenied("NATIVE_REVIEW_SCOPE_OR_AUTHORITY_INVALID")
    return answer


def _match_subject(current: dict, archived: dict) -> None:
    for field in FRAME_FIELDS:
        if field not in current or field not in archived or current[field] != archived[field]:
            raise ReviewEvidenceDenied("NATIVE_REVIEW_SUBJECT_DRIFT:" + field)
    prompt = str(archived.get("full_native_worker_prompt") or "")
    scene = str(archived.get("scene_prompt") or "")
    if (_sha(prompt.encode("utf-8")) != current["full_native_worker_prompt_sha256"]
            or _sha(scene.encode("utf-8")) != current["candidate_scene_prompt_sha256"]
            or current.get("review_approved") is not False
            or current.get("dispatch_authorized") is not False
            or "NOT YET AUTHORIZED" not in prompt):
        raise ReviewEvidenceDenied("NATIVE_REVIEW_PROMPT_CONTENT_OR_ADMISSION_INVALID")


def _require_approval(row: dict, current: dict, frame: int) -> None:
    if (not isinstance(row, dict)
            or row.get("frame") != frame
            or row.get("decision") != "APPROVE"
            or row.get("story_fidelity") != "PASS"
            or row.get("issues") != []
            or row.get("required_changes") != []
            or row.get("subject_full_native_worker_prompt_sha256")
                != current["full_native_worker_prompt_sha256"]):
        raise ReviewEvidenceDenied("FRAME_TEXT_REVIEW_NOT_APPROVED_OR_SHA_DRIFT")


def inspect(ep: Path, staged: list[dict]) -> dict:
    """Verify archived review against CURRENT live-produced stage() records.

    Missing or mismatched evidence is a read-only BLOCKED result. No reviewer
    decision is granted new production/Attempt authority by this routine.
    """
    ep = Path(ep)
    base = ep / "meta" / "runtime"
    try:
        frame_map = {row["frame"]: row for row in staged}
        if (sorted(frame_map) != list(FRAMES) or len(staged) != len(FRAMES)):
            raise ReviewEvidenceDenied("EXACT_THREE_FRAMES_REQUIRED")
        for row in staged:
            if (row.get("live_source_authority_verified") is not True
                    or row.get("episode_model_policy_verified") is not True):
                raise ReviewEvidenceDenied("LIVE_SOURCE_AND_MODEL_POLICY_REQUIRED")
        output = {}
        for filenames, scope in (
            (V4, "EP14_INDEPENDENT_NATIVE_REVIEW_V4"),
            (V7, "EP14_INDEPENDENT_NATIVE_REVIEW_V7_F029"),
            (V8, "EP14_F048_V8_FULL_NATIVE_WORKER_INDEPENDENT_REVIEW"),
        ):
            request_path, log_path = (base / name for name in filenames)
            request = request_path.read_bytes()
            log = log_path.read_bytes()
            source = _json_last_line(request)
            decision = _response(log, scope)
            if scope.endswith("V4"):
                originals = source.get("frames")
                if (not isinstance(originals, list) or len(originals) != 3
                        or decision.get("overall") != "REVISE"
                        or decision.get("frames") is None):
                    raise ReviewEvidenceDenied("V4_REVIEW_BATCH_INVALID")
                reviews = decision["frames"]
                if (not isinstance(reviews, list) or
                        sorted(x.get("frame") for x in reviews) != list(FRAMES)):
                    raise ReviewEvidenceDenied("V4_REVIEW_ROSTER_INVALID")
                for frame in (9,):
                    matches = [x for x in originals if x.get("frame") == frame]
                    if len(matches) != 1:
                        raise ReviewEvidenceDenied("V4_REQUEST_FRAME_MISSING")
                    _match_subject(frame_map[frame], matches[0])
                    _require_approval(next(x for x in reviews if x["frame"] == frame),
                                      frame_map[frame], frame)
                    output[frame] = {
                        "scope": scope,
                        "request_sha256": _sha(request),
                        "runner_log_sha256": _sha(log),
                        "subject_full_native_worker_prompt_sha256":
                            frame_map[frame]["full_native_worker_prompt_sha256"],
                    }
            elif scope.endswith("V7_F029"):
                if source.get("frame") != 29 or decision.get("frame") != 29:
                    raise ReviewEvidenceDenied("V7_FRAME_SCOPE_INVALID")
                _match_subject(frame_map[29], source)
                _require_approval(decision, frame_map[29], 29)
                output[29] = {
                    "scope": scope,
                    "request_sha256": _sha(request),
                    "runner_log_sha256": _sha(log),
                    "subject_full_native_worker_prompt_sha256":
                        frame_map[29]["full_native_worker_prompt_sha256"],
                }
            else:
                if source.get("frame") != 48 or decision.get("frame") != 48:
                    raise ReviewEvidenceDenied("V8_FRAME_SCOPE_INVALID")
                _match_subject(frame_map[48], source)
                _require_approval(decision, frame_map[48], 48)
                output[48] = {
                    "scope": scope,
                    "request_sha256": _sha(request),
                    "runner_log_sha256": _sha(log),
                    "subject_full_native_worker_prompt_sha256":
                        frame_map[48]["full_native_worker_prompt_sha256"],
                }
        return {
            "status": "VERIFIED_INDEPENDENT_TEXT_REVIEW_NOT_PRODUCTION_ADMISSION",
            "frames": [dict(frame=frame, **output[frame]) for frame in FRAMES],
            "reviewed_frame_count": 3,
            "canonical_render_activation_verified": False,
            "provider_image_entitlement_verified": False,
            "production_dispatch_authorized": False,
            "model_calls": 0,
            "mysql_writes": 0,
            "paid_attempts_reserved": 0,
        }
    except (ReviewEvidenceDenied, OSError, UnicodeError, TypeError, KeyError, ValueError) as exc:
        return {
            "status": "BLOCKED_REVIEW_EVIDENCE_MISSING_OR_DRIFTED",
            "reason": str(exc)[:200],
            "reviewed_frame_count": 0,
            "canonical_render_activation_verified": False,
            "production_dispatch_authorized": False,
            "model_calls": 0,
            "mysql_writes": 0,
            "paid_attempts_reserved": 0,
        }
