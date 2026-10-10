"""Immutable reviewer #7/#8 continuation manifests must be SHA-verified."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SYSTEM = ROOT / "episodes/_system"
if str(SYSTEM) not in sys.path:
    sys.path.insert(0, str(SYSTEM))

import character_contract
import story_review


def _fixture(tmp_path, monkeypatch, attempt):
    ep = tmp_path / "episode"
    (ep / "docs").mkdir(parents=True)
    (ep / "meta/runtime").mkdir(parents=True)
    story = ep / "docs/story.md"
    board = ep / "docs/storyboard.md"
    caption = ep / "docs/subtitles.yaml"
    story.write_text("valid Story source", encoding="utf-8")
    board.write_text("valid Storyboard", encoding="utf-8")
    caption.write_text("frames:\n  1: 'cap'\n", encoding="utf-8")
    ssha = story_review.sha256_file(story)
    bsha = story_review.sha256_file(board)
    csha = story_review.sha256_file(caption)
    scope = ("CHARACTER_STORY_SOURCE_REPAIR_AFTER_FAIL"
             if attempt == 8 else "PHOTO_TEXT_SOURCE_REPAIR_AFTER_FAIL")
    evidence = {
        "global_review_attempt": attempt, "review_scope": scope,
        "review_epoch": 7 if attempt == 8 else 6,
        "epoch_attempt": 1, "previous_review_sha256": "a" * 64,
        "current_rubric_sha256": "b" * 64,
        "story_sha256": ssha, "storyboard_sha256": bsha,
        "subtitle_source_sha256": csha,
        "previous_storyboard_sha256": "c" * 64,
    }
    if attempt == 8:
        evidence.update({
            "previous_story_sha256": "d" * 64,
            "new_character_authority_sha256": "e" * 64,
            "character_attestation_sha256": "f" * 64,
        })
    name = ("story-review-character-source-repair-a8.json" if attempt == 8
            else "story-review-photo-text-source-repair-a7.json")
    path = ep / "meta/runtime" / name
    path.write_text(json.dumps(evidence), encoding="utf-8")
    provenance = {
        **evidence, "attempt": attempt, "direct_user_continuation_review": True,
    }
    data = {"critic_provenance": provenance, "story_sha256": ssha,
            "storyboard_sha256": bsha, "subtitle_source_sha256": csha,
            "summary": {"passed": True}}
    monkeypatch.setattr(story_review, "review_required", lambda _ep: True)
    monkeypatch.setattr(story_review, "load_review", lambda _ep: data)
    monkeypatch.setattr(story_review, "story_paths", lambda _ep: (story, board))
    monkeypatch.setattr(story_review, "episode_contract_version", lambda _ep: "2.6.1")
    monkeypatch.setattr(story_review, "validate_payload", lambda *args, **kw: [])
    monkeypatch.setattr(story_review, "_review_rubric_digest", lambda code: "b" * 64)
    monkeypatch.setattr(story_review.propagation_core_gate, "required", lambda _ep: False)
    if attempt == 8:
        revision = {
            "scope": "CHARACTER_STORY_SOURCE_REPAIR_AFTER_FAILED_A7",
            "previous_review_authority_sha256": "a" * 64,
            "previous_story_sha256": "d" * 64,
            "story_sha256": ssha, "storyboard_sha256": bsha,
            "attestation_sha256": "f" * 64,
        }
        monkeypatch.setattr(character_contract, "load", lambda _ep: {
            "source_revision": revision,
        })
        monkeypatch.setattr(character_contract, "validate", lambda *args, **kw: [])
        monkeypatch.setattr(character_contract, "authority_sha256", lambda _ep: "e" * 64)
    return ep, path, evidence


@pytest.mark.parametrize("attempt", [7, 8])
def test_valid_review_epoch_manifest_is_verified(tmp_path, monkeypatch, attempt):
    ep, path, evidence = _fixture(tmp_path, monkeypatch, attempt)
    assert story_review.verify(ep) == []
    evidence["current_rubric_sha256"] = "9" * 64
    path.write_text(json.dumps(evidence), encoding="utf-8")
    assert any("rubric SHA mismatch" in x for x in story_review.verify(ep))


def test_review_epoch_8_missing_manifest_is_blocked(tmp_path, monkeypatch):
    ep, path, evidence = _fixture(tmp_path, monkeypatch, 8)
    path.unlink()
    errors = story_review.verify(ep)
    assert "policy continuation manifest missing or invalid" in errors


def test_review_epoch_8_character_contract_drift_is_blocked(tmp_path, monkeypatch):
    ep, path, evidence = _fixture(tmp_path, monkeypatch, 8)
    monkeypatch.setattr(character_contract, "authority_sha256", lambda _ep: "0" * 64)
    assert any("Character Story source revision binding" in x for x in story_review.verify(ep))
