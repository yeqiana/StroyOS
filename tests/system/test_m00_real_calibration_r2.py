from __future__ import annotations
import contextlib
import hashlib
import json
import shutil
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "episodes/_system"))
import storyos_m00_calibration_r2 as cal
import visual_profile_bridge_v224


@pytest.fixture()
def sandbox(tmp_path):
    registry = tmp_path / "standards/capture_profiles"
    registry.mkdir(parents=True)
    for filename in ("index.json", "CP02_cheap_android_2015.json", "CP03_compact_digital_2008.json"):
        shutil.copy2(ROOT / "standards/capture_profiles" / filename, registry / filename)
    config = tmp_path / "standards/m00_calibration_cases_r2.json"
    shutil.copy2(ROOT / "standards/m00_calibration_cases_r2.json", config)
    private = tmp_path / ".storyos/user-visual-references"
    private.mkdir(parents=True)
    refs = []
    for name in ("r1.png", "r2.png"):
        image = private / name
        Image.new("RGB", (18, 22), (70, 85, 102)).save(image)
        refs.append({"path": image.relative_to(tmp_path).as_posix(),
                     "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
                     "kind": "capture_style"})
    old = {"purpose": "M00_CROSS_GENRE_PIXEL_CALIBRATION_NOT_PRODUCTION",
           "frames": [
               {"id": "C02", "capture_profile": "CP02_cheap_android_2015",
                "references": refs},
               {"id": "C04", "capture_profile": "CP03_compact_digital_2008",
                "references": refs},
           ]}
    plan = private / "calibration-plans/m00-four-scene-20261013.json"
    plan.parent.mkdir(parents=True)
    plan.write_text(json.dumps(old), encoding="utf-8")
    return tmp_path, refs


def build(sandbox, case):
    repo, _ = sandbox
    visual = visual_profile_bridge_v224.compile_prompt_contract(ROOT / "episodes")["text"]
    return cal.make_bundle(case, repo=repo, base_visual=visual)


def test_cp02_and_cp03_really_bind_into_distinct_native_requests(sandbox):
    a = build(sandbox, "C02")
    b = build(sandbox, "C04")
    assert a["device"]["profile_id"] == "CP02"
    assert b["device"]["profile_id"] == "CP03"
    assert a["fingerprint"] != b["fingerprint"]
    assert "capture_device_id=CP02" in a["request"]["scene_prompt"]
    assert "capture_device_id=CP03" in b["request"]["scene_prompt"]
    assert "capture_device_id=CP01" not in a["request"]["scene_prompt"]
    assert "capture_device_id=CP01" not in b["request"]["scene_prompt"]
    assert "TRANSPORT_REQUEST_FINGERPRINT: " + b["fingerprint"] in b["prompt"]
    assert "EXACT_REFERENCE_COUNT: 2" in b["prompt"]
    assert "REFERENCE_1_KIND: capture_style" in b["prompt"]


def test_v2_scenes_present_actual_observable_action_and_anomaly(sandbox):
    c02 = build(sandbox, "C02")
    c04 = build(sandbox, "C04")
    for signal in ("车把", "车座", "前轮", "重心", "积水"):
        assert signal in c02["request"]["scene_prompt"]
    for signal in ("悬浮", "8厘米", "空气缝隙", "阴影", "目光"):
        assert signal in c04["request"]["scene_prompt"]
    assert "由故事定义" not in c04["request"]["scene_prompt"]
    assert "do not add movement" in c04["request"]["scene_prompt"]
    assert c04["case"]["new_frame_id"] == "C04-R2"


def test_reference_sha_drift_prevents_dispatch(sandbox):
    repo, refs = sandbox
    (repo / refs[0]["path"]).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="REFERENCE_SHA_DRIFT"):
        build(sandbox, "C02")


def test_capture_profile_selection_cannot_drift(sandbox):
    repo, _ = sandbox
    path = repo / "standards/m00_calibration_cases_r2.json"
    content = json.loads(path.read_text(encoding="utf-8"))
    content["cases"][0]["capture_profile"] = "CP03_compact_digital_2008"
    path.write_text(json.dumps(content), encoding="utf-8")
    with pytest.raises(ValueError, match="PROFILE_DRIFT"):
        build(sandbox, "C02")


def test_no_placeholder_anomaly(sandbox):
    repo, _ = sandbox
    path = repo / "standards/m00_calibration_cases_r2.json"
    content = json.loads(path.read_text(encoding="utf-8"))
    content["cases"][1]["scene_prompt"] = "窗边有人看到一处由故事定义的微小异常现象。" * 4
    path.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="UNDERDEFINED"):
        build(sandbox, "C04")


def test_testonly_guard_fails_closed_on_visual_profile_loss(sandbox):
    with pytest.raises(ValueError, match="VISUAL_BASE_INVALID"):
        cal.rebind_capture_device("profile=M01 | other", "device=CP02")


def test_bundle_tamper_changes_request_fingerprint(sandbox):
    repo, _ = sandbox
    first = build(sandbox, "C02")["fingerprint"]
    path = repo / "standards/m00_calibration_cases_r2.json"
    content = json.loads(path.read_text(encoding="utf-8"))
    content["cases"][0]["scene_prompt"] += " 一块新地砖。"
    path.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
    assert build(sandbox, "C02")["fingerprint"] != first


def test_one_shot_receipt_exists_blocks_real_invocation(monkeypatch, tmp_path):
    fake = {"out": tmp_path / "C02-R2", "case": {"new_frame_id": "C02-R2"},
            "device": {"profile_id": "CP02", "sha256": "a" * 64},
            "identity": {}, "fingerprint": "f" * 64, "request": {"references": []},
            "ref_paths": [], "prompt": "unused"}
    fake["out"].mkdir()
    (fake["out"] / "test-only-record.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(cal, "make_bundle", lambda frame: fake)
    with patch.object(cal.codex_user_runner, "run_model_codex") as model:
        with pytest.raises(ValueError, match="NO_RETRY"):
            cal.execute("C02")
        model.assert_not_called()


def test_only_test_receipt_no_forged_approval():
    assert "grants_visual_lock_pass" in cal.m00_calibration_receipts.inspect_batch(
        ROOT / ".storyos/user-visual-references/test-only-calibration"
    )

def test_original_timeout_artifact_recovery_never_triggers_second_provider(monkeypatch, tmp_path):
    frame = "C04-R2"
    folder = tmp_path / ".storyos/user-visual-references/test-only-calibration" / frame
    folder.mkdir(parents=True)
    mock = {"out": folder, "case": {"new_frame_id": frame}, "fingerprint": "f" * 64}
    monkeypatch.setattr(cal, "make_bundle", lambda case: mock)
    monkeypatch.setattr(cal, "ROOT", tmp_path)
    receipt = {"frame": frame, "status": "OUTCOME_UNKNOWN", "request_id": "original-id",
               "request_fingerprint": "f" * 64, "mock": {"production_authority": False}}
    (folder / "test-only-record.json").write_text(json.dumps(receipt), encoding="utf-8")
    cache = tmp_path / "generated"
    image = cache / "thread-unique/one.png"
    image.parent.mkdir(parents=True)
    Image.new("RGB", (1122, 1402), (150, 120, 80)).save(image)
    durable = {"request_id": "original-id", "returncode": 124,
               "evidence": {"thread_ids": ["thread-unique"],
                            "generated_artifacts": ["thread-unique/one.png"]}}
    monkeypatch.setattr(cal.codex_user_runner, "read_task_result", lambda _id: durable)
    with patch.object(cal.codex_user_runner, "run_model_codex") as model:
        recovered = cal.recover("C04", generated_images_root=cache)
        model.assert_not_called()
    assert recovered["status"] == "IMAGE_RECOVERED_AFTER_RUNNER_TIMEOUT"
    assert recovered["recovery"]["different_from_clean_completion"] is True
    assert recovered["recovery"]["request_id"] == "original-id"
    assert recovered["output_sha256"] == hashlib.sha256(
        (folder / "generated.png").read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="RECOVERY_NOT_ALLOWED"):
        cal.recover("C04", generated_images_root=cache)


def test_recovery_rejects_thread_traversal(monkeypatch, tmp_path):
    folder = tmp_path / "C02-R2"
    folder.mkdir()
    (folder / "test-only-record.json").write_text(
        json.dumps({"frame": "C02-R2", "status": "OUTCOME_UNKNOWN",
                    "request_fingerprint": "a" * 64, "request_id": "id"}),
        encoding="utf-8")
    monkeypatch.setattr(cal, "make_bundle", lambda case: {"out": folder, "fingerprint": "a" * 64})
    monkeypatch.setattr(cal.codex_user_runner, "read_task_result",
                        lambda rid: {"request_id": "id", "returncode": 124,
                                     "evidence": {"thread_ids": ["thread"], "generated_artifacts":
                                                  ["thread/../../wrong.png"]}})
    with pytest.raises(ValueError, match="ARTIFACT_PATH_INVALID"):
        cal.recover("C02", generated_images_root=tmp_path)
