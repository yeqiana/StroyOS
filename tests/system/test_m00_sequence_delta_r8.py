from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "episodes/_system"))
sys.path.insert(0, str(ROOT / "scripts"))
import m00_sequence_state_delta as delta
import storyos_m00_sequence_r8 as r8
import visual_profile_bridge_v224


@pytest.fixture
def sample(tmp_path):
    repo = tmp_path
    (repo / "standards/capture_profiles").mkdir(parents=True)
    for name in ("index.json", "CP02_cheap_android_2015.json"):
        shutil.copy2(ROOT / "standards/capture_profiles" / name,
                     repo / "standards/capture_profiles" / name)
    shutil.copy2(ROOT / "standards/m00_sequence_delta_canary_r8.json",
                 repo / "standards/m00_sequence_delta_canary_r8.json")
    base = repo / ".storyos/user-visual-references"
    image = base / "test-only-calibration/C02-R2/generated.png"
    image.parent.mkdir(parents=True)
    Image.new("RGB", (1122, 1402), (110, 115, 117)).save(image)
    digest = hashlib.sha256(image.read_bytes()).hexdigest()
    (image.parent / "test-only-record.json").write_text(json.dumps({
        "frame": "C02-R2", "status": "IMAGE_CREATED", "capture_profile": "CP02",
        "request_fingerprint": "1" * 64, "mock": {"production_authority": False},
        "request_id": "original-real-image-request", "codex_returncode": 0,
        "output": image.relative_to(repo).as_posix(),
        "output_sha256": digest, "dimensions": [1122, 1402],
    }), encoding="utf-8")
    style = base / "original-style.png"
    style.parent.mkdir(parents=True,exist_ok=True)
    Image.new("RGB", (35, 40), (54, 68, 75)).save(style)
    style_sha = hashlib.sha256(style.read_bytes()).hexdigest()
    plan = base / "calibration-plans/m00-four-scene-20261013.json"
    plan.parent.mkdir()
    plan.write_text(json.dumps({
        "frames": [{"id": "C02", "capture_profile": "CP02_cheap_android_2015",
                    "references": [{"kind": "capture_style", "sha256": style_sha,
                                    "path": style.relative_to(repo).as_posix()}]}],
    }), encoding="utf-8")
    return repo


def build(sample):
    visual = visual_profile_bridge_v224.compile_prompt_contract(ROOT / "episodes")["text"]
    return r8.make_bundle(repo=sample, base_visual=visual)


def test_slot1_explicit_invariants_and_capture_device_are_sha_bound(sample):
    bundle = build(sample)
    identity = bundle["identity"]
    assert identity["revision"] == "R8_NEW_CASE_NOT_R7_RETRY"
    assert identity["state_delta_sha256"] == delta.contract_sha256(json.loads(
        (sample / "standards/m00_sequence_delta_canary_r8.json").read_text("utf-8"))["delta"])
    assert "capture_device_id=CP02" in bundle["request"]["scene_prompt"]
    assert len(bundle["ref_paths"]) == 2
    assert [x["kind"] for x in bundle["request"]["references"]] == ["identity", "capture_style"]
    for term in ("LOCKED_GEOGRAPHY", "LOCKED_PHOTOGRAPHER", "LOCKED_WARDROBE"):
        assert term in bundle["request"]["scene_prompt"]


def test_slot2_motion_requires_actual_before_after_and_physical_evidence(sample):
    prompt = build(sample)["request"]["scene_prompt"]
    for item in ("CHANGE_foot_contact", "CHANGE_bike_position", "CHANGE_wheel_water",
                 "VERIFY_IN_PIXELS", "duplicating their prior pose"):
        assert item in prompt
    assert "Never replace fixed building geometry" in prompt
    cfg = json.loads((sample / "standards/m00_sequence_delta_canary_r8.json").read_text("utf-8"))
    cfg["delta"]["observable_changes"][0]["after"] = cfg["delta"]["observable_changes"][0]["before"]
    with pytest.raises(ValueError, match="NO_STATE_CHANGE"):
        delta.canonical(cfg["delta"])


def test_static_is_valid_without_invented_motion(sample):
    c = json.loads((sample / "standards/m00_sequence_delta_canary_r8.json").read_text("utf-8"))["delta"]
    c["mode"] = "static"
    c["observable_changes"] = []
    assert "preserve stillness" in delta.prompt_suffix(c)
    c["observable_changes"] = [{
        "id": "movement", "before": "still standing", "after": "running away",
        "pixel_evidence": "shoes flying over street",
    }]
    with pytest.raises(ValueError, match="STATIC_SHOULD_NOT_FORCE"):
        delta.canonical(c)


def test_missing_action_or_undefined_delta_fails_closed(sample):
    c = json.loads((sample / "standards/m00_sequence_delta_canary_r8.json").read_text("utf-8"))["delta"]
    c["observable_changes"] = []
    with pytest.raises(ValueError, match="OBSERVABLE_ACTION_REQUIRED"):
        delta.canonical(c)
    c["observable_changes"] = [{
        "id": "a", "before": "待定义的原始位置", "after": "走到一个新的地方",
        "pixel_evidence": "可以看到某个东西的不同",
    }, {
        "id": "b", "before": "前轮在旧地面上", "after": "前轮已经滚到另一侧",
        "pixel_evidence": "轮胎在新的砖缝旁边",
    }]
    with pytest.raises(ValueError, match="UNDEFINED_CHANGE"):
        delta.canonical(c)


def test_source_sha_change_blocks_new_dispatch(sample):
    b = build(sample)
    src = sample / b["request"]["references"][0]["path"]
    src.write_bytes(b"wrong")
    with pytest.raises(ValueError, match="PARENT_REAL_IMAGE_NOT_VERIFIED"):
        build(sample)


def test_revision_has_new_frame_and_no_duplicate_paid_attempt(sample):
    b = build(sample)
    assert b["case"]["new_frame_id"] == "C02-T01"
    assert b["out"].name == "C02-T01"
    b["out"].mkdir()
    (b["out"] / "test-only-record.json").write_text("{}", encoding="utf-8")
    with patch.object(r8.r2.codex_user_runner, "run_model_codex") as run:
        with pytest.raises(ValueError, match="NO_RETRY"):
            r8.r2.execute_bundle(b)
        run.assert_not_called()


def test_slot3_only_sha_bound_full_image_review_can_produce_advisory(sample):
    bundle = build(sample)
    out = bundle["out"]
    before = r8.pixel_pair_advisory(repo=sample)
    assert not before["both_verified"]
    out.mkdir()
    photo = out / "generated.png"
    Image.new("RGB", (1122, 1402), (90, 95, 97)).save(photo)
    new_sha = hashlib.sha256(photo.read_bytes()).hexdigest()
    (out / "test-only-record.json").write_text(json.dumps({
        "frame": "C02-T01", "status": "IMAGE_CREATED", "codex_returncode": 0,
        "mock": {"production_authority": False}, "output": photo.relative_to(sample).as_posix(),
        "output_sha256": new_sha, "dimensions": [1122, 1402],
        "request_identity": bundle["identity"], "request_fingerprint": bundle["fingerprint"],
    }), encoding="utf-8")
    pending = r8.pixel_pair_advisory(repo=sample)
    assert pending["both_verified"] and pending["status"] == "PENDING_FULL_IMAGE_PAIR_REVIEW"
    review = {
        "reviewer": "fixture reviewer", "reviewed_with": "both_full_images",
        "source_sha256": pending["source_sha256"], "new_sha256": pending["new_sha256"],
        "observations": "Fixture of two exact PNG files was examined with full images.",
        "checks": {key: "PASS" for key in r8.REVIEW_CHECKS},
    }
    assert r8.pixel_pair_advisory(repo=sample, review=review)["status"] == "ADVISORY_PAIR_PASS"
    assert not r8.pixel_pair_advisory(repo=sample, review=review)["production_approved"]
    assert r8.pixel_pair_advisory(repo=sample)["pixel_diagnostics"]["proves_story_progression"] is False
    review["checks"]["observable_state_delta_vs_previous"] = "FAIL"
    assert r8.pixel_pair_advisory(repo=sample, review=review)["status"] == "REPAIR_RECOMMENDED"
    review["new_sha256"] = "0" * 64
    assert r8.pixel_pair_advisory(repo=sample, review=review)["status"] == "REVIEW_INVALID_OR_INCOMPLETE"


def test_exact_duplicate_pixels_cannot_be_reviewed_as_progress(sample):
    b = build(sample)
    b["out"].mkdir(parents=True)
    source = sample / ".storyos/user-visual-references/test-only-calibration/C02-R2/generated.png"
    target = b["out"] / "generated.png"
    shutil.copy2(source, target)
    sha = hashlib.sha256(target.read_bytes()).hexdigest()
    (b["out"] / "test-only-record.json").write_text(json.dumps({
        "frame": "C02-T01", "status": "IMAGE_CREATED", "codex_returncode": 0,
        "mock": {"production_authority": False},
        "output": target.relative_to(sample).as_posix(),
        "output_sha256": sha, "dimensions": [1122, 1402],
        "request_identity": b["identity"], "request_fingerprint": b["fingerprint"],
    }), encoding="utf-8")
    audit = r8.pixel_pair_advisory(repo=sample)
    assert audit["status"] == "IDENTICAL_PIXELS_DO_NOT_PROVE_NEW_ACTION"
    assert audit["production_approved"] is False


def test_config_changes_are_visible_in_fingerprint(sample):
    b1 = build(sample)["fingerprint"]
    p = sample / "standards/m00_sequence_delta_canary_r8.json"
    d = json.loads(p.read_text("utf-8"))
    d["delta"]["locked"]["lighting"] += " 不添加任何新影子。"
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    assert build(sample)["fingerprint"] != b1


def test_controller_keeps_native_model_and_testonly_authority(sample):
    b = build(sample)
    assert "TEST_ONLY_NEW_REVISION" in b["prompt"]
    assert "TRANSPORT_REQUEST_FINGERPRINT: " + b["fingerprint"] in b["prompt"]
    assert "EXACT_REFERENCE_COUNT: 2" in b["prompt"]
    assert "C02-S01" not in b["identity"]["revision"]
