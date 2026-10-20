from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
SYSTEM = ROOT / "episodes" / "_system"
if str(SYSTEM) not in sys.path:
    sys.path.insert(0, str(SYSTEM))

import image_payload_controller
import model_policy
import runtime_observability
import scoped_codex_worker


POLICY_SHA = "d" * 64
CONTROLLER_BINDING = {
    "role": "image.controller",
    "profile": "image_controller",
    "model": "gpt-6-luna",
    "reasoning_effort": "high",
    "policy_version": "phase5a-frozen-v1",
    "model_policy_sha256": POLICY_SHA,
}
PAYLOAD_BINDING = {
    "role": "image.payload",
    "profile": "image_payload",
    "model": "gpt-image-2.5-flare",
    "quality": "high",
    "policy_version": "phase5a-frozen-v1",
    "model_policy_sha256": POLICY_SHA,
}


def _completed_jsonl(scene_prompt="P01 stands at the doorway, holding the red folder"):
    answer = json.dumps({"scene_prompt": scene_prompt}, ensure_ascii=False)
    return "\n".join((
        json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": answer}}),
        json.dumps({"type": "turn.completed"}),
        "",
    ))


def _inputs(**overrides):
    values = {
        "logical_asset_key": "canary-phase5a/frame-01",
        "frame_id": "frame-01",
        "authority_input_sha256": "a" * 64,
        "source_prompt_sha256": "b" * 64,
        "frame_contract_sha256": "c" * 64,
        "visual_contract_sha256": "e" * 64,
        "canvas": {"width": 1080, "height": 1350, "aspect_ratio": "4:5"},
        "references": [{"authority_id": "style/M00", "sha256": "f" * 64}],
        "controller_input": {"frame_contract": {"character": "P01"}, "scene": "doorway"},
    }
    values.update(overrides)
    return values


def _policy_patches():
    def resolve(role, *, episode):
        assert Path(episode).exists()
        if role == "image.controller":
            return dict(CONTROLLER_BINDING)
        if role == "image.payload":
            return dict(PAYLOAD_BINDING)
        raise AssertionError(f"unexpected role: {role}")

    return (
        patch.object(model_policy, "validate_bound_policy", return_value=[]),
        patch.object(model_policy, "resolve", side_effect=resolve),
    )


def _fake_executor(calls, *, argv=None, scene_prompt=None):
    stream_text = _completed_jsonl(scene_prompt or "P01 stands at the doorway, holding the red folder")

    def execute(ep, step, binding, prompt_text, *, call_id, output_handle, receipt_fields, **kwargs):
        calls.append({"step": step, "binding": dict(binding), "prompt": prompt_text,
                      "call_id": call_id, "kwargs": dict(kwargs)})
        output_handle.write(stream_text)
        receipt = {
            "receipt_schema_version": 1,
            "episode_id": "canary/phase5a-test",
            "run_id": "test-run",
            "trace_id": "test-trace",
            "step": step,
            "call_id": call_id,
            "model_role": binding["role"],
            "profile": binding["profile"],
            "requested_model": binding["model"],
            "effective_model": binding["model"],
            "reasoning_effort": binding["reasoning_effort"],
            "model_policy_version": binding["policy_version"],
            "model_policy_sha256": binding["model_policy_sha256"],
            "provider": "codex_subscription",
            "runner": "codex exec",
            "started_at": "2026-10-01T00:00:00+00:00",
            "finished_at": "2026-10-01T00:00:01+00:00",
            "duration_ms": 1000,
            "status": "SUCCESS",
            "model_binding_source": "EPISODE_BOUND_MODEL_POLICY",
            "effective_model_source": "EXPLICIT_RUNTIME_BINDING",
            "codex_argv": list(argv if argv is not None else [
                "codex", "exec", "-m", binding["model"], "-c",
                'model_reasoning_effort="high"', "-s", kwargs["sandbox"], "--json", "-",
            ]),
            "scoped_output_stream": stream_text,
            **receipt_fields,
        }
        runtime_observability.write_model_execution_receipt(ep, receipt=receipt)
        return 0, receipt

    return execute


def _run(ep, **overrides):
    return image_payload_controller.build_payload_request(ep, **_inputs(**overrides))


def test_controller_uses_frozen_luna_high_and_read_only_child(tmp_path):
    calls = []
    with _policy_patches()[0] as _, _policy_patches()[1] as _, \
         patch.object(scoped_codex_worker, "execute_model_call", side_effect=_fake_executor(calls)):
        result = _run(tmp_path)

    assert result["status"] == "SUCCESS"
    assert result["receipt"]["model_role"] == "image.controller"
    assert result["receipt"]["profile"] == "image_controller"
    assert result["receipt"]["requested_model"] == "gpt-6-luna"
    assert result["receipt"]["reasoning_effort"] == "high"
    assert result["receipt"]["model_policy_sha256"] == POLICY_SHA
    assert result["receipt"]["effective_model_source"] == "EXPLICIT_RUNTIME_BINDING"
    assert calls[0]["kwargs"]["sandbox"] == "read-only"
    assert "--enable" not in result["receipt"]["codex_argv"]
    assert "image_generation" not in result["receipt"]["codex_argv"]
    assert result["request"]["payload_model"] == "gpt-image-2.5-flare"
    assert result["request"]["payload_quality"] == "high"


def test_controller_rejects_frozen_binding_mismatch_before_execution(tmp_path):
    calls = []
    wrong = dict(CONTROLLER_BINDING, reasoning_effort="medium")

    def resolve(role, *, episode):
        return wrong if role == "image.controller" else dict(PAYLOAD_BINDING)

    with patch.object(model_policy, "validate_bound_policy", return_value=[]), \
         patch.object(model_policy, "resolve", side_effect=resolve), \
         patch.object(scoped_codex_worker, "execute_model_call", side_effect=_fake_executor(calls)):
        with pytest.raises(image_payload_controller.ImagePayloadControllerError) as exc:
            _run(tmp_path)

    assert exc.value.code == "IMAGE_CONTROLLER_FROZEN_BINDING_MISMATCH"
    assert calls == []


def test_controller_rejects_image_generation_argv(tmp_path):
    calls = []
    forbidden_argv = ["codex", "exec", "--enable", "image_generation", "-m", "gpt-6-luna"]
    with _policy_patches()[0] as _, _policy_patches()[1] as _, \
         patch.object(scoped_codex_worker, "execute_model_call",
                      side_effect=_fake_executor(calls, argv=forbidden_argv)):
        with pytest.raises(image_payload_controller.ImagePayloadControllerError) as exc:
            _run(tmp_path)

    assert exc.value.code == "IMAGE_CONTROLLER_IMAGE_TOOL_FORBIDDEN"
    assert len(calls) == 1


def test_structured_controller_output_is_bound_into_canonical_request(tmp_path):
    calls = []
    scene = "P01 keeps the same coat and camera angle; only the red folder is prominent"
    with _policy_patches()[0] as _, _policy_patches()[1] as _, \
         patch.object(scoped_codex_worker, "execute_model_call",
                      side_effect=_fake_executor(calls, scene_prompt=scene)):
        result = _run(tmp_path)

    request = result["request"]
    assert request["scene_prompt"] == scene
    assert request["controller_receipt_id"] == result["controller_call_id"]
    assert request["controller_output_sha256"]
    assert request["model_policy_sha256"] == POLICY_SHA
    assert request["request_fingerprint"] == result["request_fingerprint"]
    assert result["receipt"]["payload_request_fingerprint"] == request["request_fingerprint"]


def test_frame_specific_age_47_overrides_generic_56_and_is_preserved(tmp_path):
    calls = []
    frame_input = {
        "source_scene_prompt": "2017年，一个47岁精干强壮的中年男人在山上喝水。",
        "frame_prompt_contract": "This frame's visible appearance is 47, not the character's later age.",
    }
    scene = "2017年春，一个47岁精干强壮的男子喝白开水，自然纪实镜头。"
    with _policy_patches()[0] as _, _policy_patches()[1] as _, \
         patch.object(scoped_codex_worker, "execute_model_call",
                      side_effect=_fake_executor(calls, scene_prompt=scene)):
        result = _run(tmp_path, controller_input=frame_input)
        reused = _run(tmp_path, controller_input=frame_input)
    assert result["status"] == "SUCCESS"
    assert result["request"]["scene_prompt"] == scene
    assert reused["reused"] is True
    assert len(calls) == 1
    assert "never replace" in calls[0]["prompt"]


@pytest.mark.parametrize("scene", [
    "2017年正午，一个56岁男子在山坡上喝水，不采用源提示中47岁外观。",
    "2017年正午，一个56岁男子在山坡上喝水。",
    "2017年正午，一个中年男子在山坡上喝水。",
])
def test_controller_blocks_wrong_or_missing_locked_apparent_age(tmp_path, scene):
    calls = []
    frame_input = {"source_scene_prompt": "2017年，一个47岁精干强壮的中年男人在山上喝水。"}
    with _policy_patches()[0] as _, _policy_patches()[1] as _, \
         patch.object(scoped_codex_worker, "execute_model_call",
                      side_effect=_fake_executor(calls, scene_prompt=scene)):
        with pytest.raises(image_payload_controller.ImagePayloadControllerError) as exc:
            _run(tmp_path, controller_input=frame_input)
    assert exc.value.code == "IMAGE_CONTROLLER_SOURCE_AGE_DRIFT"
    assert len(calls) == 1


def test_legacy_success_receipt_age_drift_is_superseded_without_overwriting(tmp_path):
    calls = []
    source = {"source_scene_prompt": "2017年，一名47岁男子在山地劳作。"}
    scene = "2017年，一名47岁男子在山地劳作。"
    with _policy_patches()[0] as _, _policy_patches()[1] as _, \
         patch.object(scoped_codex_worker, "execute_model_call",
                      side_effect=_fake_executor(calls, scene_prompt=scene)):
        result = _run(tmp_path, controller_input=source)
    receipt_path = Path(result["receipt_path"])
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    wrong = _completed_jsonl("2017年，一名56岁男子在山地劳作。")
    receipt["scoped_output_stream"] = wrong
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False), encoding="utf-8")
    stale = receipt_path.read_bytes()
    with _policy_patches()[0] as _, _policy_patches()[1] as _, \
         patch.object(scoped_codex_worker, "execute_model_call",
                      side_effect=_fake_executor(calls, scene_prompt=scene)):
        regenerated = _run(tmp_path, controller_input=source)
        reused = _run(tmp_path, controller_input=source)
    assert regenerated["reused"] is False
    assert reused["reused"] is True
    assert len(calls) == 2
    assert regenerated["controller_call_id"] != result["controller_call_id"]
    assert regenerated["receipt"]["supersedes_controller_call_id"] == result["controller_call_id"]
    assert receipt_path.read_bytes() == stale


def test_failed_text_only_receipt_is_preserved_and_retried_once(tmp_path):
    calls = []
    source = {"source_scene_prompt": "2017年，一个47岁男子在山上喝水。"}
    scene = "2017年，一个47岁男子在山上喝白开水。"
    with _policy_patches()[0] as _, _policy_patches()[1] as _, \
         patch.object(scoped_codex_worker, "execute_model_call",
                      side_effect=_fake_executor(calls, scene_prompt=scene)):
        first = _run(tmp_path, controller_input=source)
    failed_path = Path(first["receipt_path"])
    failed = json.loads(failed_path.read_text(encoding="utf-8"))
    failed["status"] = "FAILED"
    failed["scoped_output_stream"] = ""
    failed_path.write_text(json.dumps(failed, ensure_ascii=False), encoding="utf-8")
    preserved = failed_path.read_bytes()

    with _policy_patches()[0] as _, _policy_patches()[1] as _, \
         patch.object(scoped_codex_worker, "execute_model_call",
                      side_effect=_fake_executor(calls, scene_prompt=scene)):
        retried = _run(tmp_path, controller_input=source)

    assert retried["status"] == "SUCCESS"
    assert retried["reused"] is False
    assert retried["controller_call_id"] != first["controller_call_id"]
    assert failed_path.read_bytes() == preserved
    assert len(calls) == 2


def test_invalid_replacement_does_not_retry_unboundedly(tmp_path):
    calls = []
    source = {"source_scene_prompt": "2017年，一个47岁男子在山上。"}
    with _policy_patches()[0] as _, _policy_patches()[1] as _, \
         patch.object(scoped_codex_worker, "execute_model_call",
                      side_effect=_fake_executor(calls, scene_prompt="2017年，一个47岁男子在山上。")):
        result = _run(tmp_path, controller_input=source)
    path = Path(result["receipt_path"])
    data = json.loads(path.read_text(encoding="utf-8"))
    data["scoped_output_stream"] = _completed_jsonl("2017年，一个56岁男子在山上。")
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with _policy_patches()[0] as _, _policy_patches()[1] as _, \
         patch.object(scoped_codex_worker, "execute_model_call",
                      side_effect=_fake_executor(calls, scene_prompt="2017年，一个56岁男子在山上。")):
        with pytest.raises(image_payload_controller.ImagePayloadControllerError) as exc:
            _run(tmp_path, controller_input=source)
    assert exc.value.code == "IMAGE_CONTROLLER_SOURCE_AGE_DRIFT"
    assert len(calls) == 2
    with _policy_patches()[0] as _, _policy_patches()[1] as _, \
         patch.object(scoped_codex_worker, "execute_model_call") as no_reexec:
        with pytest.raises(image_payload_controller.ImagePayloadControllerError):
            _run(tmp_path, controller_input=source)
    no_reexec.assert_not_called()


def test_controller_receipt_reused_for_same_inputs_and_reexecuted_after_input_drift(tmp_path):
    calls = []
    with _policy_patches()[0] as _, _policy_patches()[1] as _, \
         patch.object(scoped_codex_worker, "execute_model_call", side_effect=_fake_executor(calls)):
        first = _run(tmp_path)
        reused = _run(tmp_path)
        changed = _run(tmp_path, controller_input={"frame_contract": {"character": "P01"},
                                                   "scene": "different source scene"})

    assert first["reused"] is False
    assert reused["reused"] is True
    assert changed["reused"] is False
    assert first["controller_call_id"] == reused["controller_call_id"]
    assert changed["controller_call_id"] != first["controller_call_id"]
    assert len(calls) == 2


def test_legacy_success_receipt_rebinds_frozen_hard_context_without_another_model_call(tmp_path):
    import image_payload_hard_constraints as hard
    calls = []
    frame_input = {
        "source_scene_prompt": "P01在门口签字",
        "frame_prompt_contract": (
            "RESOLVED FRAME CONTRACT | frame=01 | sha256=" + "b"*64 +
            "\n[CHARACTER / POV CONTRACT]\nP01为第一人称摄影者" +
            "\n[SCENE-AWARE WARDROBE]\nP01白色短袖"
        ),
        "visual_contract": "profile=other",
    }
    with _policy_patches()[0] as _, _policy_patches()[1] as _, \
         patch.object(scoped_codex_worker, "execute_model_call",
                      side_effect=_fake_executor(calls)), \
         patch.object(hard, "inject", side_effect=lambda scene, *a, **kw: scene):
        old = _run(tmp_path, controller_input=frame_input)
    with _policy_patches()[0] as _, _policy_patches()[1] as _, \
         patch.object(scoped_codex_worker, "execute_model_call",
                      side_effect=AssertionError("previous text Controller receipt must be reused")):
        new = _run(tmp_path, controller_input=frame_input)
    assert len(calls) == 1
    assert new["reused"] is True
    assert new["legacy_payload_rebound"] is True
    assert old["request_fingerprint"] != new["request_fingerprint"]
    assert "P01白色短袖" in new["request"]["scene_prompt"]
