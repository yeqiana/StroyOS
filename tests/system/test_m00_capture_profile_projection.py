from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "episodes/_system"))
import m00_capture_profile_contract as dev
import visual_profile_bridge_v224
import m00_style_guard


def test_all_device_profiles_compile_without_mutating_sources():
    for profile in ("CP01", "CP02", "CP03", "CP04", "CP05", "CP06", "CP07", "CP08"):
        compiled = dev.compile_device_contract(profile)
        source = ROOT / compiled["path"]
        assert source.is_file()
        assert hashlib.sha256(source.read_bytes()).hexdigest() == compiled["sha256"]
        assert "capture_device_id=" + profile in compiled["text"]


def test_auto_means_configured_default_not_old_digital():
    device = dev.compile_device_contract("auto")
    registry = json.loads((ROOT / "standards/capture_profiles/index.json").read_text(encoding="utf-8"))
    assert device["profile_id"] == registry["default_profile_id"] == "CP01"
    assert dev.compile_device_contract("CP02_cheap_android_2015")["profile_id"] == "CP02"


def test_2008_and_2015_physics_differ_and_no_forced_film_grain():
    older = dev.compile_device_contract("CP03")["text"]
    budget = dev.compile_device_contract("CP02")["text"]
    assert "small_sensor_noise_flash_dependency" in older
    assert "older_jpeg" in older
    assert "2012-2018 budget Android" in budget
    assert "not_decorative_filters" in older
    assert older != budget


def test_selected_device_reaches_final_m00_payload_prompt():
    visual = visual_profile_bridge_v224.compile_prompt_contract(ROOT / "episodes")
    assert visual["capture_device_contract"]["profile_id"] == "CP01"
    assert "capture_device_sha256=" in visual["text"]
    prompt = m00_style_guard.enforce(scene_prompt="一人平静地坐在餐桌边。", visual_contract=visual["text"])
    assert "capture_device_id=CP01" in prompt
    assert "capture_device_defect_policy=only_physically_explained_defects_not_decorative_filters" in prompt
    assert prompt.startswith("一人平静地坐在餐桌边。")


def test_unknown_device_is_blocked_not_silently_fallback():
    with pytest.raises(ValueError, match="M00_CAPTURE_PROFILE_UNKNOWN"):
        dev.compile_device_contract("iPhone-6-fake-2008")

def test_actual_episode_cp02_cp03_selections_reach_different_provider_prompts(monkeypatch):
    base = visual_profile_bridge_v224.resolve_profile(ROOT / "episodes")
    fingerprints = set()
    for device_id, characteristic in (("CP02", "2012-2018 budget Android"),
                                      ("CP03", "small_sensor_noise_flash_dependency")):
        monkeypatch.setattr(visual_profile_bridge_v224, "resolve_profile",
                            lambda _episode, choice=device_id: {**base, "capture_profile": choice})
        contract = visual_profile_bridge_v224.compile_prompt_contract(ROOT / "episodes")
        assert contract["capture_device_contract"]["profile_id"] == device_id
        prompt = m00_style_guard.enforce(
            scene_prompt="一个成年人在室内安静阅读。", visual_contract=contract["text"])
        assert "capture_device_id=" + device_id in prompt
        assert characteristic in prompt
        fingerprints.add(__import__("hashlib").sha256(prompt.encode("utf-8")).hexdigest())
    assert len(fingerprints) == 2
