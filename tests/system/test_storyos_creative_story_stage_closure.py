"""Story authoring instructions must allow genuine gate and text-review closure."""
from __future__ import annotations

import sys
from pathlib import Path

SYSTEM = Path(__file__).resolve().parents[2] / "episodes" / "_system"
sys.path.insert(0, str(SYSTEM))
from scoped_codex_worker import STEP_DIRECTIVES


def test_creative_story_asks_for_evidence_not_default_pass():
    instructions = STEP_DIRECTIVES["CREATIVE_STORY"]
    assert "project-verified-recent5" in instructions
    assert "SHA-bound binding" in instructions
    assert "story.four_locks_diff_count" in instructions
    assert "do not ask the user for another permission" in instructions


def test_text_only_caption_source_is_allowed_not_image_subtitles():
    instructions = STEP_DIRECTIVES["CREATIVE_STORY"]
    assert "plain-text per-frame caption/source text" in instructions
    assert "docs/subtitles.yaml" in instructions
    assert "rendered/burned subtitles" in instructions
    assert "visual Lock images" not in instructions
