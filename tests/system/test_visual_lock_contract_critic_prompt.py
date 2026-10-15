"""Visual Lock critic must see locked per-frame evidence, not role-only spectacle."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "episodes/_system"))
import visual_lock_v21 as visual


def test_visual_critic_includes_locked_frame_cues_and_capture_limit(monkeypatch):
    monkeypatch.setattr(visual, "episode_version", lambda _ep: "2.2.1")
    rows = [{
        "id": "V-W", "role": "worst_capture_condition", "frame": 8,
        "frame_mode": "anomaly_reveal", "impact_level": 2,
        "scale_reference": "third-floor staircase",
        "frame_contract_sha256": "a" * 64,
        "required_visual_cues": ["门已回到三楼", "不表现移动瞬间"],
        "capture_constraint": {"why_capture_now": "确认门已复位", "framing_constraint": "第三层楼道"},
    }]
    prompt = visual.critic_prompt(ROOT, {"text": "realistic phone photography"}, rows, ROOT / "review.json", 2)
    assert "门已回到三楼" in prompt
    assert "不表现移动瞬间" in prompt
    assert "确认门已复位" in prompt
    assert "Do not require an impossible transition/motion" in prompt
    assert "if a required cue is not visible, FAIL" in prompt
    assert "frame_contract_sha=" + "a" * 64 in prompt
