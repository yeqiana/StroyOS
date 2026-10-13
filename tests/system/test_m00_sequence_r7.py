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
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "episodes/_system"))
import storyos_m00_sequence_r7 as seq
import visual_profile_bridge_v224


def _make_image(folder: Path, name: str, *, shade=100) -> tuple[Path, str]:
    folder.mkdir(parents=True, exist_ok=True)
    image = folder / name
    Image.new("RGB", (1122, 1402), (shade, 130, 110)).save(image)
    return image, hashlib.sha256(image.read_bytes()).hexdigest()


def _make_anchor(root: Path, name: str) -> None:
    target = root / ".storyos/user-visual-references/test-only-calibration" / name
    image, sha = _make_image(target, "generated.png")
    (target / "test-only-record.json").write_text(
        json.dumps({
            "frame": name, "status": "IMAGE_CREATED", "capture_profile": "CP02",
            "mock": {"production_authority": False},
            "request_id": "anchor-" + name,
            "request_fingerprint": "f" * 64,
            "output": str(image.relative_to(root)).replace("\\", "/"),
            "output_sha256": sha, "dimensions": [1122, 1402], "codex_returncode": 0,
        }), encoding="utf-8")


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "standards/capture_profiles").mkdir(parents=True)
    for fn in ("index.json", "CP02_cheap_android_2015.json"):
        shutil.copy2(ROOT / "standards/capture_profiles" / fn,
                     tmp_path / "standards/capture_profiles" / fn)
    shutil.copy2(ROOT / "standards/m00_sequence_canary_r7.json",
                 tmp_path / "standards/m00_sequence_canary_r7.json")
    shutil.copy2(ROOT / "standards/m00_calibration_cases_r2.json",
                 tmp_path / "standards/m00_calibration_cases_r2.json")
    ref_root = tmp_path / ".storyos/user-visual-references"
    style, sha = _make_image(ref_root, "style.png")
    plan = ref_root / "calibration-plans/m00-four-scene-20261013.json"
    plan.parent.mkdir(parents=True)
    plan.write_text(json.dumps({
        "frames": [{"id": "C02", "capture_profile": "CP02_cheap_android_2015",
                    "references": [{"kind": "capture_style",
                                    "sha256": sha,
                                    "path": style.relative_to(tmp_path).as_posix()}]}],
    }), encoding="utf-8")
    _make_anchor(tmp_path, "C02-R2")
    return tmp_path


def _bundle(root, frame):
    visual = visual_profile_bridge_v224.compile_prompt_contract(ROOT / "episodes")["text"]
    return seq.build_bundle(frame, repo=root, base_visual=visual)


def test_slot1_anchor_identity_and_capture_style_share_two_slots(workspace):
    bundle = _bundle(workspace, "S01")
    assert bundle["identity"]["previous_frame_id"] == "C02-R2"
    assert bundle["device"]["profile_id"] == "CP02"
    assert [x["kind"] for x in bundle["request"]["references"]] == ["identity", "capture_style"]
    assert "EXACT_REFERENCE_COUNT: 2" in bundle["prompt"]
    assert "REFERENCE_1_KIND: identity" in bundle["prompt"]
    assert "REFERENCE_2_KIND: capture_style" in bundle["prompt"]
    assert bundle["identity"]["previous_image_sha256"] == bundle["request"]["references"][0]["sha256"]
    assert "capture_device_id=CP02" in bundle["request"]["scene_prompt"]
    assert "capture_device_id=CP01" not in bundle["request"]["scene_prompt"]


def test_slot2_story_does_not_replace_production_or_static_contract(workspace):
    b = _bundle(workspace, "S01")
    s = b["request"]["scene_prompt"]
    for evidence in ("车把", "车座", "摄影者", "后货架", "不要强制动态模糊"):
        assert evidence in s
    assert "M00 PHYSICAL ACTION EVIDENCE" in s
    assert "M00 LOCKED VISIBLE EVENT" in s
    assert "TEST_ONLY sequence canary" in b["prompt"]
    assert b["case"]["new_frame_id"] == "C02-S01"


def _pass_first_pair_review(workspace):
    first = _bundle(workspace, "S01")
    folder = workspace / ".storyos/user-visual-references/test-only-calibration/C02-S01"
    receipt = folder / "test-only-record.json"
    data = json.loads(receipt.read_text("utf-8"))
    data["request_fingerprint"] = first["fingerprint"]
    data["request_identity"] = first["identity"]
    receipt.write_text(json.dumps(data), encoding="utf-8")
    state = seq.review_pair("S01", repo=workspace)
    review = {
        "reviewer": "Full-image test fixture", "reviewed_with": "both_full_images",
        "anchor_sha256": state["anchor_sha256"],
        "current_sha256": state["current_sha256"],
        "observations": "Fixture reviewer checked person, camera, bicycle and motion differences in both originals.",
        "checks": {key: "PASS" for key in seq.CHECKS},
    }
    (folder / "pair-review.json").write_text(json.dumps(review), encoding="utf-8")
    return folder / "pair-review.json"


def test_second_frame_needs_verified_previous_image_and_passed_pair_review(workspace):
    with pytest.raises((FileNotFoundError, ValueError)):
        _bundle(workspace, "S02")
    _make_anchor(workspace, "C02-S01")
    with pytest.raises(ValueError, match="PAIR_REVIEW_MISSING"):
        _bundle(workspace, "S02")
    review_path = _pass_first_pair_review(workspace)
    second = _bundle(workspace, "S02")
    assert second["identity"]["previous_frame_id"] == "C02-S01"
    assert second["identity"]["predecessor_review_sha256"] == hashlib.sha256(review_path.read_bytes()).hexdigest()
    assert "街巷中间" in second["request"]["scene_prompt"]
    assert second["fingerprint"] != _bundle(workspace, "S01")["fingerprint"]


def test_failed_previous_pair_blocks_future_generation_even_if_png_is_valid(workspace):
    _make_anchor(workspace, "C02-S01")
    review_path = _pass_first_pair_review(workspace)
    review = json.loads(review_path.read_text("utf-8"))
    review["checks"]["contact_balance_and_motion_progression"] = "FAIL"
    review_path.write_text(json.dumps(review), encoding="utf-8")
    with pytest.raises(ValueError, match="PREDECESSOR_PAIR_REVIEW_NOT_PASSED"):
        _bundle(workspace, "S02")


def test_source_image_tamper_fails_before_model(workspace):
    b = _bundle(workspace, "S01")
    parent = workspace / b["request"]["references"][0]["path"]
    parent.write_bytes(b"bad")
    with pytest.raises(ValueError, match="ANCHOR_SHA_OR_RECEIPT_INVALID"):
        _bundle(workspace, "S01")


def test_sequence_config_drift_changes_fingerprint(workspace):
    first = _bundle(workspace, "S01")["fingerprint"]
    path = workspace / "standards/m00_sequence_canary_r7.json"
    config = json.loads(path.read_text("utf-8"))
    config["frames"][0]["scene"] += " 更远处有一块旧窗框。"
    path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    assert _bundle(workspace, "S01")["fingerprint"] != first


def test_slot3_pair_review_requires_both_real_sha_and_explicit_human_full_images(workspace):
    b = _bundle(workspace, "S01")
    pending = seq.review_pair("S01", repo=workspace)
    assert not pending["both_real_images_verified"]
    assert pending["pixel_review_status"] == "PENDING_ACTUAL_PAIR_REVIEW"
    _make_anchor(workspace, "C02-S01")
    receipt = workspace / ".storyos/user-visual-references/test-only-calibration/C02-S01/test-only-record.json"
    doc = json.loads(receipt.read_text("utf-8"))
    doc["request_fingerprint"] = b["fingerprint"]
    doc["request_identity"] = b["identity"]
    receipt.write_text(json.dumps(doc), encoding="utf-8")
    incomplete = seq.review_pair("S01", repo=workspace)
    assert incomplete["both_real_images_verified"] is True
    assert incomplete["pixel_review_status"] == "PENDING_ACTUAL_PAIR_REVIEW"
    checks = {check: "PASS" for check in seq.CHECKS}
    review = {
        "reviewer": "M00 Manual Test", "reviewed_with": "both_full_images",
        "anchor_sha256": b["identity"]["previous_image_sha256"],
        "current_sha256": hashlib.sha256(
            (receipt.parent / "generated.png").read_bytes()).hexdigest(),
        "observations": "Both complete images show matched adult, clothes, bike and street.",
        "checks": checks,
    }
    done = seq.review_pair("S01", repo=workspace, review=review)
    assert done["pixel_review_status"] == "ADVISORY_PAIR_PASS"
    assert done["production_approved"] is False
    review["checks"]["contact_balance_and_motion_progression"] = "FAIL"
    assert seq.review_pair("S01", repo=workspace, review=review)["pixel_review_status"] == "REPAIR_RECOMMENDED"
    review["current_sha256"] = "1" * 64
    assert seq.review_pair("S01", repo=workspace, review=review)["pixel_review_status"] == "REVIEW_INVALID_OR_INCOMPLETE"


def test_slot4_one_shot_shared_capacity_not_called_twice(workspace, monkeypatch):
    bundle = _bundle(workspace, "S01")
    bundle["out"].mkdir(parents=True)
    (bundle["out"] / "test-only-record.json").write_text("{}", encoding="utf-8")
    with patch.object(seq.r2.codex_user_runner, "run_model_codex") as provider:
        with pytest.raises(ValueError, match="NO_RETRY"):
            seq.r2.execute_bundle(bundle)
        provider.assert_not_called()


def test_r7_not_prod_owner_or_runtime_driver():
    source = (ROOT / "scripts/storyos_m00_sequence_r7.py").read_text("utf-8")
    assert 'choices=("plan", "run", "pair-review")' in source
    assert "mysql_attempt" not in source.lower()
    assert "r2.execute_bundle" in source


def _record_bundle(workspace, frame, bundle):
    folder = workspace / ".storyos/user-visual-references/test-only-calibration" / ("C02-" + frame)
    record_path = folder / "test-only-record.json"
    data = json.loads(record_path.read_text("utf-8"))
    data["request_fingerprint"] = bundle["fingerprint"]
    data["request_identity"] = bundle["identity"]
    record_path.write_text(json.dumps(data), encoding="utf-8")


def test_historical_image_review_survives_new_visual_contract_version(workspace):
    _make_anchor(workspace, "C02-S01")
    _pass_first_pair_review(workspace)
    old = _bundle(workspace, "S02")
    _make_anchor(workspace, "C02-S02")
    _record_bundle(workspace, "S02", old)
    config_path = workspace / "standards/m00_sequence_canary_r7.json"
    cfg = json.loads(config_path.read_text("utf-8"))
    cfg["frames"][1]["scene"] += " 故事画面中的远处屋檐应连续。"
    config_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    assert _bundle(workspace, "S02")["fingerprint"] != old["fingerprint"]
    recovered = seq.review_pair("S02", repo=workspace)
    assert recovered["both_real_images_verified"]
    assert recovered["request_fingerprint"] == old["fingerprint"]
    assert recovered["pixel_review_status"] == "PENDING_ACTUAL_PAIR_REVIEW"
    assert not recovered["production_approved"]


def test_historical_second_frame_remains_reviewable_after_prior_failure(workspace):
    _make_anchor(workspace, "C02-S01")
    review_path = _pass_first_pair_review(workspace)
    old = _bundle(workspace, "S02")
    _make_anchor(workspace, "C02-S02")
    _record_bundle(workspace, "S02", old)
    review = json.loads(review_path.read_text("utf-8"))
    review["checks"]["contact_balance_and_motion_progression"] = "FAIL"
    review_path.write_text(json.dumps(review), encoding="utf-8")
    with pytest.raises(ValueError, match="REVIEW_NOT_PASSED"):
        _bundle(workspace, "S02")
    historic = seq.review_pair("S02", repo=workspace)
    assert historic["both_real_images_verified"]
    assert historic["pixel_review_status"] == "PENDING_ACTUAL_PAIR_REVIEW"


def test_forged_historic_fingerprint_is_rejected(workspace):
    _make_anchor(workspace, "C02-S01")
    _pass_first_pair_review(workspace)
    receipt_path = workspace / ".storyos/user-visual-references/test-only-calibration/C02-S01/test-only-record.json"
    doc = json.loads(receipt_path.read_text("utf-8"))
    doc["request_identity"]["previous_image_sha256"] = "b" * 64
    receipt_path.write_text(json.dumps(doc), encoding="utf-8")
    audit = seq.review_pair("S01", repo=workspace)
    assert audit["pixel_review_status"] == "RECEIPT_OR_PARENT_SHA_DRIFT"
