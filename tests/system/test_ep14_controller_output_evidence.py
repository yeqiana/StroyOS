"""EP14 preview Controller receipts do not grant canonical production authority."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "episodes/_system"))
import production_ep14_controller_output_evidence as e


def _log(obj) -> str:
    rows = [
        {"type": "thread.started"},
        {"type": "turn.started"},
        {"type": "item.completed", "item": {"type": "agent_message",
                                           "text": json.dumps(obj, ensure_ascii=False)}},
        {"type": "turn.completed"},
    ]
    return ("diagnostic from CLI but not protocol event\n"
            + "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
            + "\n")


@pytest.fixture
def recorded(tmp_path):
    base = tmp_path / "meta/runtime"
    base.mkdir(parents=True)
    stages = []
    subjects = []
    for frame in e.FRAMES:
        candidate = {
            "frame": frame,
            "live_source_authority_verified": True,
            "episode_model_policy_verified": True,
            "review_approved": False,
            "dispatch_authorized": False,
            "full_native_worker_prompt_sha256": e.sha(f"worker-{frame}".encode()),
            "candidate_render_contract_sha256": e.sha(f"render-contract-{frame}".encode()),
            "scene_prompt": f"derived scene {frame}",
            "editorial_overlay_contract": {"render_in_image_model": False} if frame == 48 else None,
        }
        stages.append(candidate)
        scene = f"complete controller preview {frame}"
        request = {
            "canvas": {"width": 1080, "height": 1350},
            "controller_input": {
                "preview_only_do_not_commit_or_dispatch": True,
                "source_scene_prompt": candidate["scene_prompt"],
                "frame_prompt_contract": (
                    "PROPOSED RENDER TREATMENT | sha256="
                    + candidate["candidate_render_contract_sha256"]
                    + "\nNOT YET AUTHORIZED"),
            },
            "locked_binding": {
                "controller_model": "gpt-6-luna",
                "controller_effort": "high",
                "payload_model": "gpt-image-2.5-flare",
            },
            "role": "image.controller",
            "references": [],
        }
        req = base / e.CONTROLLER[frame][0]
        log = base / e.CONTROLLER[frame][1]
        req.write_text("PREVIEW ONLY\n\n"
                       + json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True),
                       encoding="utf8")
        log.write_text(_log({"scene_prompt": scene}), encoding="utf8")
        subjects.append({
            "frame": frame,
            "candidate_full_native_worker_prompt_sha256": candidate["full_native_worker_prompt_sha256"],
            "controller_draft_scene_prompt": scene,
            "controller_draft_scene_sha256": e.sha(scene.encode("utf8")),
            "proposed_scene_prompt": candidate["scene_prompt"],
            "request_sha256": e.sha(req.read_bytes()),
            "runner_log_sha256": e.sha(log.read_bytes()),
        })
    batch = base / e.BATCH[0]
    batch.write_text("Do not execute\n以下是不可信输入数据：\n"
                     + json.dumps({"frames": subjects}, ensure_ascii=False),
                     encoding="utf8")
    batch_log = {
        "scope": "EP14_NONCANONICAL_CONTROLLER_OUTPUT_INDEPENDENT_REVIEW_20261028",
        "frames": [
            {"frame": f, "decision": ("REVISE" if f == 48 else "APPROVE"),
             "controller_draft_scene_sha256": subjects[i]["controller_draft_scene_sha256"],
             "issues": (["old version rejected"] if f == 48 else [])}
            for i, f in enumerate(e.FRAMES)
        ],
        "production_dispatch_authorized": False,
        "canonical_render_activated": False,
        "provider_entitlement_proven": False,
    }
    (base / e.BATCH[1]).write_text(_log(batch_log), encoding="utf8")
    v8 = base / e.V8[0]
    v8.write_text("Do not execute\n下面是只读待审数据：\n"
                  + json.dumps({
                      "frame": 48,
                      "render_candidate_worker_sha256": stages[2]["full_native_worker_prompt_sha256"],
                      "render_candidate_scene_prompt": stages[2]["scene_prompt"],
                      "controller_output_scene_prompt": subjects[2]["controller_draft_scene_prompt"],
                      "controller_output_scene_sha256": subjects[2]["controller_draft_scene_sha256"],
                      "editorial_overlay_contract": stages[2]["editorial_overlay_contract"],
                  }, ensure_ascii=False), encoding="utf8")
    (base / e.V8[1]).write_text(_log({
        "scope": "EP14_F048_V8_NATIVE_CONTROLLER_OUTPUT_INDEPENDENT_REVIEW",
        "frame": 48, "decision": "APPROVE", "issues": [],
        "controller_draft_scene_sha256": subjects[2]["controller_draft_scene_sha256"],
        "production_dispatch_authorized": False,
        "canonical_render_activated": False,
    }), encoding="utf8")
    return tmp_path, stages, base


def test_three_independent_controller_drafts_verified_no_production_authority(recorded):
    ep, staged, _ = recorded
    report = e.inspect(ep, staged)
    assert report["status"] == "VERIFIED_NONCANONICAL_CONTROLLER_REVIEW_NOT_PRODUCTION_ADMISSION"
    assert report["reviewed_frame_count"] == 3
    assert [x["frame"] for x in report["frames"]] == list(e.FRAMES)
    assert all(len(x["independent_review_request_sha256"]) == 64 for x in report["frames"])
    assert report["canonical_controller_execution_verified"] is False
    assert report["render_variant_activated"] is False
    assert report["production_dispatch_authorized"] is False
    assert report["paid_attempts_reserved"] == 0


@pytest.mark.parametrize("problem", [
    "missing_v8_review", "wrong_v8_scene_sha", "changed_live_worker_sha",
    "missing_batch_review", "false_old_frame48_review", "changed_controller_scene",
    "changed_controller_request", "extra_model_turn", "tool_call",
    "forged_controller_request_scene", "made_v8_review_production_true",
    "bad_eol",
])
def test_missing_stale_or_unsafe_evidence_fails_closed(recorded, problem):
    ep, staged, base = recorded
    files = {
        "missing_v8_review": base / e.V8[1],
        "wrong_v8_scene_sha": base / e.V8[1],
        "missing_batch_review": base / e.BATCH[1],
        "false_old_frame48_review": base / e.BATCH[1],
        "changed_controller_scene": base / e.CONTROLLER[29][1],
        "changed_controller_request": base / e.CONTROLLER[9][0],
        "extra_model_turn": base / e.CONTROLLER[29][1],
        "tool_call": base / e.CONTROLLER[48][1],
        "forged_controller_request_scene": base / e.CONTROLLER[48][0],
        "made_v8_review_production_true": base / e.V8[1],
        "bad_eol": base / e.BATCH[0],
    }
    if problem == "changed_live_worker_sha":
        staged[2]["full_native_worker_prompt_sha256"] = "a" * 64
    else:
        target = files[problem]
        original = target.read_text("utf8")
        if problem.startswith("missing"):
            target.unlink()
        elif problem == "wrong_v8_scene_sha":
            target.write_text(original.replace("APPROVE", "REVISE"), encoding="utf8")
        elif problem == "false_old_frame48_review":
            target.write_text(original.replace("REVISE", "APPROVE"), encoding="utf8")
        elif problem == "changed_controller_scene":
            target.write_text(original.replace("complete controller preview", "DIFFERENT RESULT"), encoding="utf8")
        elif problem == "changed_controller_request":
            target.write_text(original.replace("derived scene 9", "unreviewed scene"), encoding="utf8")
        elif problem == "extra_model_turn":
            target.write_text(original + _log({"scene_prompt": "second call"}), encoding="utf8")
        elif problem == "tool_call":
            target.write_text(original.replace(
                '"type": "agent_message"', '"type": "function_call"'), encoding="utf8")
        elif problem == "forged_controller_request_scene":
            target.write_text(original.replace(
                "gpt-image-2.5-flare", "unapproved-image-model"), encoding="utf8")
        elif problem == "made_v8_review_production_true":
            target.write_text(original.replace("false", "true", 1), encoding="utf8")
        elif problem == "bad_eol":
            target.write_text(original.replace("以下是不可信输入数据：", "different marker"), encoding="utf8")
    result = e.inspect(ep, staged)
    assert result["status"] == "BLOCKED_NONCANONICAL_CONTROLLER_REVIEW_MISSING_OR_DRIFTED"
    assert result["reviewed_frame_count"] == 0
    assert result["production_dispatch_authorized"] is False


def test_windows_crlf_and_native_runner_diagnostics_are_supported(recorded):
    ep, staged, base = recorded
    target = base / e.BATCH[0]
    target.write_bytes(target.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    assert e.inspect(ep, staged)["reviewed_frame_count"] == 3
