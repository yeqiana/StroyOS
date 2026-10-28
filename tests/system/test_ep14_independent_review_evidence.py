"""Safety tests for SHA-matched native text review; NEVER a dispatch gate."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from episodes._system import production_ep14_independent_review_evidence as evidence


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _frame(number: int) -> dict:
    prompt = f"NOT YET AUTHORIZED | review-only image request frame={number}"
    scene = f"single image description frame={number}"
    return {
        "frame": number,
        "full_native_worker_prompt": prompt,
        "full_native_worker_prompt_sha256": _sha(prompt),
        "scene_prompt": scene,
        "candidate_scene_prompt_sha256": _sha(scene),
        "original_frame_contract_sha256": _sha(f"contract{number}"),
        "original_scene_prompt_sha256": _sha(f"original-scene{number}"),
        "original_storyboard_excerpt_sha256": _sha(f"storyboard{number}"),
        "candidate_render_contract_sha256": _sha(f"render{number}"),
        "staging_package_sha256": _sha(f"staging{number}"),
        "model": "gpt-image-2.5-flare",
        "quality": "high",
        "canvas": "1080x1350",
        "strict_model": False,
        "reference_names": [],
        "review_approved": False,
        "dispatch_authorized": False,
        "live_source_authority_verified": True,
        "episode_model_policy_verified": True,
    }


def _runner_log(scope: str, answer: dict) -> str:
    parts = [
        {"type": "thread.started", "thread_id": "test"},
        {"type": "turn.started"},
        {"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(answer)}},
        {"type": "turn.completed", "usage": {"input_tokens": 100}},
    ]
    return "local diagnostic prefix is not review authority\n" + "".join(
        json.dumps(p) + "\n" for p in parts)


@pytest.fixture
def sample(tmp_path: Path):
    ep = tmp_path / "story"
    runtime = ep / "meta" / "runtime"
    runtime.mkdir(parents=True)
    frames = [_frame(number) for number in evidence.FRAMES]
    reviews = [
        {
            "frame": f["frame"],
            "decision": "APPROVE" if f["frame"] in (9, 48) else "REVISE",
            "story_fidelity": "PASS" if f["frame"] != 29 else "FAIL",
            "issues": [] if f["frame"] != 29 else ["old V4 issue"],
            "required_changes": [] if f["frame"] != 29 else ["fix"],
            "subject_full_native_worker_prompt_sha256":
                f["full_native_worker_prompt_sha256"],
        }
        for f in frames
    ]
    v4 = {
        "schema_version": 1,
        "scope": "EP14_INDEPENDENT_NATIVE_REVIEW_V4",
        "overall": "REVISE",
        "frames": reviews,
        "production_dispatch_authorized": False,
        "provider_safety_acceptance_guaranteed": False,
    }
    v7 = {
        "schema_version": 1,
        "scope": "EP14_INDEPENDENT_NATIVE_REVIEW_V7_F029",
        "frame": 29,
        "decision": "APPROVE",
        "story_fidelity": "PASS",
        "issues": [],
        "required_changes": [],
        "subject_full_native_worker_prompt_sha256":
            frames[1]["full_native_worker_prompt_sha256"],
        "production_dispatch_authorized": False,
        "provider_safety_acceptance_guaranteed": False,
    }
    v8 = {
        "schema_version": 1,
        "scope": "EP14_F048_V8_FULL_NATIVE_WORKER_INDEPENDENT_REVIEW",
        "frame": 48,
        "decision": "APPROVE",
        "story_fidelity": "PASS",
        "issues": [],
        "required_changes": [],
        "subject_full_native_worker_prompt_sha256": frames[2]["full_native_worker_prompt_sha256"],
        "production_dispatch_authorized": False,
        "provider_safety_acceptance_guaranteed": False,
    }
    for names, payload, decision in (
        (evidence.V4, {"frames": frames}, v4),
        (evidence.V7, frames[1], v7),
        (evidence.V8, frames[2], v8),
    ):
        (runtime / names[0]).write_text(
            "untrusted worker commands must never be executed\n" +
            json.dumps(payload, ensure_ascii=False), encoding="utf8")
        (runtime / names[1]).write_text(
            _runner_log(decision["scope"], decision), encoding="utf8")
    return ep, frames, runtime


def test_independent_text_review_is_bound_and_still_no_dispatch(sample):
    ep, frames, _ = sample
    report = evidence.inspect(ep, frames)
    assert report["status"] == "VERIFIED_INDEPENDENT_TEXT_REVIEW_NOT_PRODUCTION_ADMISSION"
    assert [x["frame"] for x in report["frames"]] == [9, 29, 48]
    assert all(len(x["request_sha256"]) == 64 and
               len(x["runner_log_sha256"]) == 64 for x in report["frames"])
    assert report["reviewed_frame_count"] == 3
    assert report["canonical_render_activation_verified"] is False
    assert report["provider_image_entitlement_verified"] is False
    assert report["production_dispatch_authorized"] is False
    assert report["model_calls"] == report["mysql_writes"] == report["paid_attempts_reserved"] == 0


@pytest.mark.parametrize("field", (
    "full_native_worker_prompt_sha256",
    "candidate_scene_prompt_sha256",
    "model",
    "reference_names",
    "original_frame_contract_sha256",
    "staging_package_sha256",
))
def test_any_current_frame_source_drift_fails_closed(sample, field):
    ep, frames, _ = sample
    frames[1][field] = "forged"
    out = evidence.inspect(ep, frames)
    assert out["status"].startswith("BLOCKED_")
    assert not out["production_dispatch_authorized"]


def test_reviewer_saw_other_prompt_is_not_approval(sample):
    ep, frames, root = sample
    path = root / evidence.V7[0]
    request = path.read_text("utf8")
    path.write_text(request.replace(frames[1]["full_native_worker_prompt_sha256"],
                                    "0" * 64), encoding="utf8")
    assert evidence.inspect(ep, frames)["reviewed_frame_count"] == 0


@pytest.mark.parametrize("name", ("missing_final_turn", "review_refused", "review_log_missing",
                                   "too_many_agent_messages", "turn_failed"))
def test_missing_or_false_review_cannot_promote(sample, name):
    ep, frames, root = sample
    path = root / evidence.V7[1]
    log = path.read_text("utf8")
    if name == "review_log_missing":
        path.unlink()
    elif name == "review_refused":
        path.write_text(log.replace('"decision\\": \\"APPROVE"', '"decision\\": \\"REVISE"'),
                        encoding="utf8")
        # Ensure the refusal path was exercised even if JSON escaping changes.
        if path.read_text("utf8") == log:
            path.write_text(log.replace("APPROVE", "REVISE"), encoding="utf8")
    elif name == "missing_final_turn":
        path.write_text("\n".join(l for l in log.splitlines()
                                  if '"turn.completed"' not in l), encoding="utf8")
    elif name == "too_many_agent_messages":
        path.write_text(log + next(
            l for l in log.splitlines() if '"item.completed"' in l) + "\n", encoding="utf8")
    else:
        path.write_text(log + '{"type":"turn.failed"}\n', encoding="utf8")
    assert evidence.inspect(ep, frames)["status"].startswith("BLOCKED_")


def test_v4_overall_revise_can_only_preserve_unchanged_per_frame_approvals(sample):
    ep, frames, root = sample
    path = root / evidence.V4[1]
    data = path.read_text("utf8")
    path.write_text(data.replace("APPROVE", "REVISE"), encoding="utf8")
    assert evidence.inspect(ep, frames)["status"].startswith("BLOCKED_")


def test_live_source_flag_and_missing_frame_denied(sample):
    ep, frames, _ = sample
    frames[0]["live_source_authority_verified"] = False
    assert evidence.inspect(ep, frames)["reviewed_frame_count"] == 0
    assert evidence.inspect(ep, frames[:2])["reviewed_frame_count"] == 0


def test_v8_frame48_old_v4_approval_never_replaces_new_evidence(sample):
    ep, frames, root = sample
    (root / evidence.V8[1]).unlink()
    result = evidence.inspect(ep, frames)
    assert result["status"] == "BLOCKED_REVIEW_EVIDENCE_MISSING_OR_DRIFTED"
    assert result["reviewed_frame_count"] == 0
    assert not result["production_dispatch_authorized"]


def test_v8_frame48_prompt_or_approval_drift_blocks_all(sample):
    ep, frames, root = sample
    request = root / evidence.V8[0]
    request.write_text(request.read_text("utf8").replace(
        frames[2]["full_native_worker_prompt_sha256"], "b" * 64), encoding="utf8")
    assert evidence.inspect(ep, frames)["status"].startswith("BLOCKED_")
    ep, frames, root = sample
    receipt = root / evidence.V8[1]
    receipt.write_text(receipt.read_text("utf8").replace("APPROVE", "REVISE"), encoding="utf8")
    assert evidence.inspect(ep, frames)["status"].startswith("BLOCKED_")
