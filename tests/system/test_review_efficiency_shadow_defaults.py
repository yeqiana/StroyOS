from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SYSTEM = ROOT / "episodes" / "_system"
if str(SYSTEM) not in sys.path:
    sys.path.insert(0, str(SYSTEM))
import storyos_config


def test_advisory_semantic_shadows_are_opt_in_not_production_defaults():
    cfg = storyos_config.load_config()
    adapters = cfg["agent_runtime"]["adapters"]
    for name in ("story_semantic_critic", "preimage_semantic_critic", "final_semantic_critic"):
        assert adapters[name]["shadow_enabled"] is False
        assert adapters[name]["production_enabled"] is False
        assert adapters[name]["bounded_reflection"]["max_auto_repairs"] == 1
    assert cfg["execution"]["vision_review"]["executor"] == "CODEX"
