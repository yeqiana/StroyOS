from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "episodes/_system"))
import m00_episode_delta_review as review
import m00_sequence_state_delta as state


def locks():
    return json.loads((ROOT / "standards/m00_sequence_delta_canary_r8.json").read_text("utf-8"))["delta"]


def _images(tmp_path):
    base = tmp_path / "episode"
    base.mkdir()
    prev = base / "media/approved/01.png"
    curr = base / "media/approved/02.png"
    prev.parent.mkdir(parents=True)
    Image.new("RGB", (200, 260), (120, 121, 124)).save(prev)
    Image.new("RGB", (200, 260), (119, 121, 125)).save(curr)
    return base, prev, curr


def test_slot3_real_sha_two_images_required_no_automatic_pass(tmp_path):
    ep, prev, curr = _images(tmp_path)
    result = review.inspect_pair(episode=ep, previous_image=prev,
                                current_image=curr, locked_delta=locks())
    assert result["status"] == "PENDING_FULL_PIXEL_REVIEW"
    assert result["previous"]["sha256"] == hashlib.sha256(prev.read_bytes()).hexdigest()
    assert result["grants_visual_lock_pass"] is False
    assert result["grants_production_attempt"] is False
    assert "change:foot_contact" in result["required_checks"]


def test_review_does_not_turn_uncertain_or_fail_into_success(tmp_path):
    ep, prev, curr = _images(tmp_path)
    result = review.inspect_pair(episode=ep, previous_image=prev,
                                current_image=curr, locked_delta=locks())
    note = {"delta_sha256": state.contract_sha256(locks()),
            "previous_sha256": result["previous"]["sha256"],
            "current_sha256": result["current"]["sha256"],
            "reviewed_with": "both_full_images", "reviewer": "Test-only reviewer",
            "observations": "Images checked for costume, bicycle and exact physical state.",
            "checks": {x: "PASS" for x in result["required_checks"]}}
    assert review.inspect_pair(episode=ep, previous_image=prev, current_image=curr,
                              locked_delta=locks(), review=note)["status"] == "ADVISORY_PIXEL_PASS"
    note["checks"]["change:foot_contact"] = "UNCERTAIN"
    assert review.inspect_pair(episode=ep, previous_image=prev, current_image=curr,
                              locked_delta=locks(), review=note)["status"] == "UNCERTAIN_NEEDS_FULL_REVIEW"
    note["checks"]["geography"] = "FAIL"
    assert review.inspect_pair(episode=ep, previous_image=prev, current_image=curr,
                              locked_delta=locks(), review=note)["status"] == "REPAIR_RECOMMENDED"
    note["current_sha256"] = "0" * 64
    assert review.inspect_pair(episode=ep, previous_image=prev, current_image=curr,
                              locked_delta=locks(), review=note)["status"] == "REVIEW_SHA_OR_CHECKS_INVALID"


def test_equal_files_never_prove_progress(tmp_path):
    ep, prev, curr = _images(tmp_path)
    curr.write_bytes(prev.read_bytes())
    result = review.inspect_pair(episode=ep, previous_image=prev,
                                current_image=curr, locked_delta=locks())
    assert result["status"] == "DUPLICATE_ACTION_PIXELS"
    assert not result["grants_visual_lock_pass"]


def test_static_mode_does_not_require_action_proof(tmp_path):
    ep, prev, curr = _images(tmp_path)
    cfg = locks()
    cfg["mode"] = "static"
    cfg["observable_changes"] = []
    curr.write_bytes(prev.read_bytes())
    result = review.inspect_pair(episode=ep, previous_image=prev,
                                current_image=curr, locked_delta=cfg)
    assert result["status"] == "PENDING_FULL_PIXEL_REVIEW"
    assert "change:foot_contact" not in result["required_checks"]


def test_external_image_or_corruption_fails_before_review(tmp_path):
    ep, prev, curr = _images(tmp_path)
    outsider = tmp_path / "outside.png"
    Image.new("RGB", (200, 260), (3, 4, 5)).save(outsider)
    with pytest.raises(ValueError, match="OUTSIDE_EPISODE"):
        review.inspect_pair(episode=ep, previous_image=prev,
                            current_image=outsider, locked_delta=locks())
    curr.write_bytes(b"not an image")
    with pytest.raises((OSError, ValueError)):
        review.inspect_pair(episode=ep, previous_image=prev,
                            current_image=curr, locked_delta=locks())
