from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "episodes/_system"))
import frame_contract
import m00_storyboard_delta_sources as source
import production_prompt_materializer as prepare
import story_review
import visual_profile

STORY = "成年男子穿着旧夹克和旧鞋，沿雨后真实街巷推着旧自行车走。"
PREV = "成年男子推着旧自行车来到雨后街边旧砖墙，前轮停在浅水洼旁边。"
CURR = "同一个成年男子推着原来的旧自行车，前轮已经滚过旁边的第二道砖缝。"


@pytest.fixture
def scene(tmp_path, monkeypatch):
    ep = tmp_path / "episode"
    docs = ep / "docs"
    docs.mkdir(parents=True)
    story = docs / "story.md"
    board = docs / "storyboard.md"
    story.write_text(STORY, encoding="utf-8")
    board.write_text("# frames\n|帧|场景|叙事|\n|---|---|---|\n"
                     f"|01|{PREV}|开始|\n|02|{CURR}|继续|\n", encoding="utf-8")
    monkeypatch.setattr(frame_contract, "artifact_paths", lambda _: (story, board))
    monkeypatch.setattr(frame_contract, "frame_count", lambda _: 2)
    monkeypatch.setattr(visual_profile, "compile_prompt_contract",
                        lambda _: {"profile_id": "M00"})
    monkeypatch.setattr(story_review, "review_required", lambda _: True)
    monkeypatch.setattr(story_review, "verify", lambda _: [])
    monkeypatch.setattr(story_review, "review_authority_sha256", lambda _: "a" * 64)
    return ep, story, board


def test_slot3_reviewed_m00_queue_source_drafts_created_but_not_review_authority(scene):
    ep, story, board = scene
    result = prepare._prepare_reviewed_m00_source_drafts(ep)
    assert result["status"] == "DRAFTS_CREATED_NO_AUTHORITY"
    assert result["created"] == 1
    evidence = json.loads(source.candidate_path(ep, 2).read_text("utf-8"))
    assert evidence["source_suggestions"]["status"] == "ADVISORY_SOURCE_QUOTES_ONLY"
    assert evidence["status"] == "DRAFT_ONLY"
    assert evidence["editorial_attestation"] is None
    assert result["formal_authority_granted"] is False
    assert result["formal_generation_calls"] == 0
    assert story.read_text("utf-8") == STORY
    assert f"|01|{PREV}|开始|" in board.read_text("utf-8")
    assert prepare._prepare_reviewed_m00_source_drafts(ep)["existing_untouched"] == 1


def test_slot3_non_m00_and_unreviewed_sources_never_create(scene, monkeypatch):
    ep, story, board = scene
    monkeypatch.setattr(visual_profile, "compile_prompt_contract",
                        lambda _: {"profile_id": "M01"})
    assert prepare._prepare_reviewed_m00_source_drafts(ep)["status"] == "SKIPPED_OTHER_PROFILE"
    assert not source.candidate_path(ep, 2).exists()
    monkeypatch.setattr(visual_profile, "compile_prompt_contract",
                        lambda _: {"profile_id": "M00"})
    monkeypatch.setattr(story_review, "review_required", lambda _: False)
    assert prepare._prepare_reviewed_m00_source_drafts(ep)["status"] == "SKIPPED_NO_CANONICAL_REVIEW"
    monkeypatch.setattr(story_review, "review_required", lambda _: True)
    monkeypatch.setattr(story_review, "verify", lambda _: ["STORYBOARD_SHA_INVALID"])
    assert prepare._prepare_reviewed_m00_source_drafts(ep)["status"] == "SKIPPED_CANONICAL_REVIEW_NOT_READY"
    monkeypatch.setattr(story_review, "verify", lambda _: [])
    monkeypatch.setattr(story_review, "review_authority_sha256", lambda _: None)
    assert prepare._prepare_reviewed_m00_source_drafts(ep)["status"] == "SKIPPED_CANONICAL_REVIEW_SHA_MISSING"
    assert not source.candidate_path(ep, 2).exists()


def test_slot4_legacy_non_table_source_shape_never_blocks_production(scene):
    ep, story, board = scene
    board.write_text("# 唯一一次大段剧本\n老人的舞台表演，没有分镜编号。", encoding="utf-8")
    status = prepare._prepare_reviewed_m00_source_drafts(ep)
    assert status["status"] == "SKIPPED_DRAFT_EXTRACTION_UNSUPPORTED"
    assert not source.candidate_path(ep, 2).exists()


def test_queue_preparation_keeps_existing_queue_path_and_adds_draft_report(scene, monkeypatch):
    ep, story, board = scene
    observed = []
    monkeypatch.setattr(prepare, "ensure",
                        lambda _ep: observed.append("materialize") or {"total": 2, "created": []})
    import image_scheduler
    monkeypatch.setattr(image_scheduler, "import_batch",
                        lambda _ep, _path: observed.append("import") or {"status": "already-approved"})
    result = prepare.prepare_queue(ep)
    assert result["status"] == "PASS"
    assert observed == ["materialize", "import"]
    assert result["queue"]["status"] == "already-approved"
    assert result["m00_source_drafts"]["created"] == 1
    assert result["m00_source_drafts"]["formal_authority_granted"] is False
    original = source.candidate_path(ep, 2).read_bytes()
    result = prepare.prepare_queue(ep)
    assert result["m00_source_drafts"]["existing_untouched"] == 1
    assert source.candidate_path(ep, 2).read_bytes() == original


def test_missing_source_refuses_all_drafts_not_half_episode(scene):
    ep, story, board = scene
    board.write_text("# Storyboard\n|帧|场景|叙事|\n|---|---|---|\n"
                     f"|01|{PREV}|开始|\n|02|{CURR}|继续|\n|03|缺少第四帧|错误|\n",
                     encoding="utf-8")
    with pytest.raises(ValueError, match="FRAME_NOT_FOUND"):
        source.prepare_drafts(episode=ep, story=story, storyboard=board,
                              count=4, apply=True)
    assert not source.candidate_path(ep, 2).exists()
    assert not source.candidate_path(ep, 3).exists()
