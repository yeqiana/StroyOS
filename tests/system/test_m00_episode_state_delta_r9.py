from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "episodes/_system"))
import frame_contract
import image_payload_controller
import image_payload_request
import m00_episode_state_delta as episode_delta
import m00_sequence_state_delta as delta
import prompt_package
import visual_profile_bridge_v224

M00 = visual_profile_bridge_v224.compile_prompt_contract(ROOT / "episodes")["text"]
SHA = "a" * 64


def example():
    return json.loads((ROOT / "standards/m00_sequence_delta_canary_r8.json").read_text("utf-8"))["delta"]


def story_source(tmp_path: Path, *, frame_two=None):
    story = tmp_path / "storyboard.json"
    data = {"frames": [
        {"frame": 1, "scene": "A photographer watches a resident move a bicycle on a wet street."},
        {"frame": 2, "scene": "The same person moves a step ahead with the same bicycle.",
         **({"m00_adjacent_state_delta": frame_two} if frame_two is not None else {})},
    ]}
    story.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return story


def _full_contract(transition):
    return "FRAME LOCK\n" + delta.prompt_suffix(transition["delta"]) + "\nEND FRAME LOCK"


def _provider(transition, *, scene="同一名成年人向前推着自行车，前轮跨过积水。"):
    controller_input = {
        "source_scene_prompt": scene,
        "visual_contract": M00,
        "frame_prompt_contract": _full_contract(transition) if transition else "ordinary Frame Contract",
        "m00_adjacent_state_delta": transition["delta"] if transition else None,
        "m00_adjacent_state_delta_sha256": transition["delta_sha256"] if transition else None,
    }
    identity = {
        "episode_id": "episodes/m00-offline-frame-02",
        "logical_asset_key": "episodes/m00-offline-frame-02/frame-02",
        "frame_id": "02", "authority_input_sha256": SHA,
        "source_prompt_sha256": SHA, "frame_contract_sha256": SHA,
        "visual_contract_sha256": SHA,
    }
    return image_payload_controller._build_validated_request(
        ep=ROOT / "episodes", identity=identity, fields={"canvas":
            {"width": 1080, "height": 1350, "aspect_ratio": "4:5"}, "references": []},
        binding={"policy_version": "test", "model_policy_sha256": SHA},
        payload={"model": image_payload_request.PAYLOAD_MODEL,
                 "quality": image_payload_request.PAYLOAD_QUALITY},
        call_id="offline-only", controller_output={"scene_prompt": "普通街道有一人推车。"},
        controller_input=controller_input,
    )


def test_slot1_locked_storyboard_json_only_opt_in_no_new_authority(tmp_path):
    source = story_source(tmp_path, frame_two=example())
    current = episode_delta.source_transition(source, 2, "M00")
    assert current is not None
    assert current["delta_sha256"] == delta.contract_sha256(example())
    assert current["previous_frame"] == "01"
    assert current["frame_excerpt_sha256"] == frame_contract.extract_frame_excerpt(source, 2)["sha256"]
    assert current["previous_frame_excerpt_sha256"] == frame_contract.extract_frame_excerpt(source, 1)["sha256"]
    assert episode_delta.source_transition(source, 1, "M00") is None
    assert episode_delta.source_transition(source, 2, "M01") is None
    assert episode_delta.source_transition(story_source(tmp_path), 2, "M00") is None


def test_previous_storyboard_frame_changes_source_binding(tmp_path):
    source = story_source(tmp_path, frame_two=example())
    first = episode_delta.source_transition(source, 2, "M00")
    content = json.loads(source.read_text("utf-8"))
    content["frames"][0]["scene"] += " New causal evidence."
    source.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
    after = episode_delta.source_transition(source, 2, "M00")
    assert first["previous_frame_excerpt_sha256"] != after["previous_frame_excerpt_sha256"]
    assert first["delta_sha256"] == after["delta_sha256"]


def test_opt_in_m00_first_frame_and_undefined_action_blocked(tmp_path):
    source = story_source(tmp_path, frame_two=example())
    content = json.loads(source.read_text("utf-8"))
    content["frames"][0]["m00_adjacent_state_delta"] = example()
    source.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="REQUIRES_PREDECESSOR"):
        episode_delta.source_transition(source, 1, "M00")
    content["frames"][1]["m00_adjacent_state_delta"]["observable_changes"][0]["after"] = (
        content["frames"][1]["m00_adjacent_state_delta"]["observable_changes"][0]["before"])
    source.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="NO_STATE_CHANGE"):
        episode_delta.source_transition(source, 2, "M00")


def test_slot2_final_provider_payload_contains_authorized_delta_and_sha_changes(tmp_path):
    t = episode_delta.source_transition(story_source(tmp_path, frame_two=example()), 2, "M00")
    request = _provider(t)
    assert request["request_fingerprint"]
    assert "CHANGE_foot_contact" in request["scene_prompt"]
    assert "[M00 LOCKED ADJACENT STATE TRANSITION]" in request["scene_prompt"]
    assert request["scene_prompt"].count("[M00 LOCKED ADJACENT STATE TRANSITION]") == 1
    assert image_payload_request.validate_request(request) == []
    old = _provider(None)
    assert "CHANGE_foot_contact" not in old["scene_prompt"]
    assert old["request_fingerprint"] != request["request_fingerprint"]


def test_controller_cannot_invent_or_forge_state_delta(tmp_path):
    t = episode_delta.source_transition(story_source(tmp_path, frame_two=example()), 2, "M00")
    bad = {"frame_prompt_contract": _full_contract(t),
           "m00_adjacent_state_delta": t["delta"],
           "m00_adjacent_state_delta_sha256": "b" * 64}
    with pytest.raises(ValueError, match="SHA_MISMATCH"):
        episode_delta.project_final_prompt(scene_prompt="Normal scene.", controller_input=bad, is_m00=True)
    with pytest.raises(ValueError, match="AUTHORITY_PROJECTION_MISSING"):
        episode_delta.project_final_prompt(
            scene_prompt="Normal scene.",
            controller_input={"frame_prompt_contract": _full_contract(t)},
            is_m00=True)
    with pytest.raises(ValueError, match="FRAME_CONTRACT_MISMATCH"):
        episode_delta.project_final_prompt(
            scene_prompt="Normal scene.",
            controller_input={**bad, "m00_adjacent_state_delta_sha256": t["delta_sha256"],
                              "frame_prompt_contract": "no source delta"},
            is_m00=True)
    with pytest.raises(ValueError, match="CONTROLLER_INJECTION"):
        episode_delta.project_final_prompt(
            scene_prompt=delta.prompt_suffix(t["delta"]),
            controller_input={**bad, "m00_adjacent_state_delta_sha256": t["delta_sha256"]},
            is_m00=True)


def test_non_m00_or_legacy_scene_is_not_overridden():
    assert episode_delta.project_final_prompt(
        scene_prompt="static scene", controller_input={"frame_prompt_contract": "unchanged"},
        is_m00=False) == "static scene"
    assert episode_delta.project_final_prompt(
        scene_prompt="static scene", controller_input={"frame_prompt_contract": "unchanged"},
        is_m00=True) == "static scene"


def test_slot1_static_storyboard_never_forces_action(tmp_path):
    static = example()
    static["mode"] = "static"
    static["observable_changes"] = []
    t = episode_delta.source_transition(story_source(tmp_path, frame_two=static), 2, "M00")
    request = _provider(t, scene="夜晚一名住户静静阅读。")
    assert "BEAT_MODE=static" in request["scene_prompt"]
    assert "preserve stillness" in request["scene_prompt"]
    assert "CHANGE_foot_contact" not in request["scene_prompt"]


def test_slot2_prompt_package_transmits_source_projection_without_db(tmp_path, monkeypatch):
    t = episode_delta.source_transition(story_source(tmp_path, frame_two=example()), 2, "M00")
    content = {"contract_sha256": "c" * 64, "prompt_contract": _full_contract(t),
               "storyboard_frame": {"sha256": t["frame_excerpt_sha256"]},
               "m00_adjacent_state_delta": t}
    monkeypatch.setattr(prompt_package.frame_contract, "compile_frame", lambda *a, **k: content)
    monkeypatch.setattr(prompt_package.prompt_package_persistence, "load_latest", lambda *a, **k: None)
    monkeypatch.setattr(prompt_package.image_model_policy, "for_episode", lambda *a, **k: {"model": "offline"})
    source = tmp_path / "02.txt"
    source.write_text("成年男子从湿地上推车往前行走。", encoding="utf-8")
    pack = prompt_package.compile_frame(tmp_path, 2, source, write=False)
    assert pack["m00_adjacent_state_delta_sha256"] == t["delta_sha256"]
    assert pack["m00_adjacent_state_delta"] == t["delta"]
    assert pack["package_sha256"] and pack["frame_contract_sha256"] == "c" * 64


def test_slot4_legacy_worker_controller_identity_remains_bitwise_unchanged(monkeypatch):
    import image_worker_pool
    seen = []
    def fake_controller(_ep, **kwargs):
        seen.append(kwargs)
        return {"request": {"request_fingerprint": "offline-fingerprint"}}
    monkeypatch.setattr(image_worker_pool.image_payload_controller, "build_payload_request", fake_controller)
    monkeypatch.setattr(image_worker_pool.image_payload_request, "validate_request", lambda _: [])
    monkeypatch.setattr(image_worker_pool.logical_asset_identity, "frame_asset_key", lambda *_: "offline-key")
    prompt_path = ROOT / "README.md"
    visual = {"profile_sha256": SHA, "capture_grammar": {},
              "text": "M00 visual documented capture texture"}
    ordinary = {
        "scene_prompt": "ordinary authorized scene",
        "scene_prompt_sha256": SHA, "frame_contract_sha256": SHA,
        "frame_prompt_contract": "Resolved Frame Contract without explicit delta",
        "storyboard_source": {},
    }
    kwargs = dict(ep=ROOT / "episodes", item={"frame": 2, "references": []},
                  prompt_path=prompt_path, refs=[], visual=visual,
                  width=1080, height=1350, aspect="4:5", timeout=60, codex=None)
    image_worker_pool._canonical_controller_request(
        package=ordinary, **kwargs)
    legacy_fields = seen[-1]
    assert "m00_adjacent_state_delta" not in legacy_fields["controller_input"]
    assert "m00_adjacent_state_delta_sha256" not in legacy_fields["controller_input"]
    import image_worker_pool as pool
    fingerprint_source = {
        "scene_prompt_sha256": SHA, "frame_contract_sha256": SHA,
        "frame_prompt_contract": ordinary["frame_prompt_contract"],
        "visual_profile_sha256": SHA, "visual_contract": visual["text"],
        "references": [],
    }
    expected_hash = hashlib.sha256(json.dumps(
        fingerprint_source, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8")).hexdigest()
    assert legacy_fields["authority_input_sha256"] == expected_hash
    altered = {**ordinary, "m00_adjacent_state_delta": example(),
               "m00_adjacent_state_delta_sha256": delta.contract_sha256(example())}
    image_worker_pool._canonical_controller_request(package=altered, **kwargs)
    new_fields = seen[-1]
    assert new_fields["authority_input_sha256"] != legacy_fields["authority_input_sha256"]
    assert new_fields["controller_input"]["m00_adjacent_state_delta_sha256"] == delta.contract_sha256(example())
