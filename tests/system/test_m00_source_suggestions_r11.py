from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "episodes/_system"))
sys.path.insert(0, str(ROOT / "scripts"))
import m00_storyboard_source_suggestions as suggest
import m00_storyboard_delta_sources as source
import m00_episode_state_delta as episode_delta
import storyos_m00_storyboard_delta_drafts_r10 as drafts
import frame_contract

BASE = ("同一位穿深灰外套和旧运动鞋的成年男子推着自行车，"
        "从背后手机摄影视角可见雨后小巷右侧旧墙和原有店门。"
        "车轮停在旧砖缝旁的水洼边缘。")
NEXT = ("同一位男子穿深灰外套，仍推着原来的旧自行车走向小巷尽头。"
        "新画面中的前轮已经滚过水洼附近的第二道砖缝，"
        "右侧旧墙和原有店门保持在原处。")
STORY = ("同一个成年男子穿深灰外套与旧运动鞋，推着原有通勤自行车走在雨后小巷。"
         "摄影者站在其左后方，阴天自然散射光照亮湿地，右侧旧墙和店门始终未变化。")


@pytest.fixture
def local_storyboard(tmp_path):
    root = tmp_path / "episode"
    doc = root / "docs"
    doc.mkdir(parents=True)
    story = doc / "story.md"
    board = doc / "storyboard.md"
    story.write_text(STORY, encoding="utf-8")
    board.write_text(
        "# Storyboard\n| 帧 | 场景与动作 | 叙事意义 |\n|---|---|---|\n"
        f"| 01 | {BASE} | 建立身份与原始状态 |\n"
        f"| 02 | {NEXT} | 前轮已经发生有依据的推进 |\n", encoding="utf-8")
    return root, story, board


def test_slot1_literal_suggestions_from_approved_story_and_adjacent_frames(local_storyboard):
    ep, story, board = local_storyboard
    proposal = source.proposal(story=story, storyboard=board, frame=2)
    hints = proposal["source_suggestions"]
    assert hints["status"] == "ADVISORY_SOURCE_QUOTES_ONLY"
    assert hints["story_sha256"] == hashlib.sha256(story.read_bytes()).hexdigest()
    assert hints["storyboard_sha256"] == hashlib.sha256(board.read_bytes()).hexdigest()
    assert hints["ready_for_source_attestation"] is False
    assert hints["grants_review_authority"] is False
    assert not hints["generates_images"]
    assert hints["locked_quote_candidates"]["props"]
    assert hints["locked_quote_candidates"]["geography"]
    assert hints["locked_quote_candidates"]["lighting"]
    for key, suggestions in hints["locked_quote_candidates"].items():
        for item in suggestions:
            owner = {
                "story": story.read_text("utf-8"), "current": proposal["evidence"]["current"],
                "previous": proposal["evidence"]["previous"]}[item["source"]]
            assert item["text"] in owner
            assert item["sha256"] == hashlib.sha256(item["text"].encode("utf-8")).hexdigest()


def test_slot2_action_candidate_before_and_after_are_true_source_excerpts(local_storyboard):
    ep, story, board = local_storyboard
    evidence = source.proposal(story=story, storyboard=board, frame=2)
    hints = evidence["source_suggestions"]
    assert hints["mode_hint"] == "action"
    assert hints["observable_change_candidates"]
    row = hints["observable_change_candidates"][0]
    assert row["before"]["text"] in evidence["evidence"]["previous"]
    assert row["after"]["text"] in evidence["evidence"]["current"]
    assert row["pixel_evidence_hint"]["text"] in evidence["evidence"]["current"]
    assert row["status"] == "CANDIDATE_NEEDS_CAUSAL_REVIEW"
    assert evidence["delta"]["observable_changes"] == []
    assert all(not x for x in evidence["delta"]["locked"].values())


def test_slot2_missing_actual_causal_photographer_evidence_does_not_invent(local_storyboard):
    ep, story, board = local_storyboard
    # Conflicting story entities are NOT forced into successive frames.
    hints = suggest.analyze(
        story="故事只有猫在室内睡觉，没有其他事实。",
        previous="窗台上有一只猫静静地晒太阳，画面不涉及人物移动。",
        current="窗台上仍是猫，家具摆设静止但没有摄影者。",
        source=source.proposal(story=story, storyboard=board, frame=2)["source"])
    assert hints["ready_for_source_attestation"] is False
    assert not hints["observable_change_candidates"]
    assert "observable_changes:2_distinct_evidence_pairs" not in hints["missing_evidence"]


def test_static_mode_is_hint_only_with_explicit_both_frame_cues(local_storyboard):
    ep, story, board = local_storyboard
    p = source.proposal(story=story, storyboard=board, frame=2)
    hints = suggest.analyze(
        story=STORY,
        previous="路边的老人保持不动，只观察雨后的街巷。",
        current="路边的老人仍保持不动，光线与场景未变。",
        source=p["source"])
    assert hints["mode_hint"] == "static"
    assert hints["observable_change_candidates"] == []
    assert not hints["ready_for_source_attestation"]


def test_slots3_4_no_auto_attestation_or_production_after_draft(tmp_path, local_storyboard, monkeypatch):
    ep, story, board = local_storyboard
    monkeypatch.setattr(drafts, "ROOT", tmp_path)
    monkeypatch.setattr(drafts.frame_contract, "artifact_paths", lambda _: (story, board))
    monkeypatch.setattr(drafts.frame_contract, "frame_count", lambda _: 2)
    monkeypatch.setattr(drafts.visual_profile, "compile_prompt_contract", lambda _: {"profile_id": "M00"})
    planned = drafts.prepare(ep, apply=False)
    assert planned["status"] == "DRY_RUN"
    assert not source.candidate_path(ep, 2).exists()
    created = drafts.prepare(ep, apply=True)
    assert created["created"] == 1
    doc = json.loads(source.candidate_path(ep, 2).read_text("utf-8"))
    assert doc["source_suggestions"]["status"] == "ADVISORY_SOURCE_QUOTES_ONLY"
    assert doc["status"] == "DRAFT_ONLY"
    assert doc["editorial_attestation"] is None
    assert episode_delta.source_transition(board, 2, "M00", episode=ep) is None
    assert created["formal_generation_calls"] == 0


def test_source_suggestion_is_not_a_credential_to_promote(local_storyboard):
    ep, story, board = local_storyboard
    p = source.proposal(story=story, storyboard=board, frame=2)
    p["status"] = "SOURCE_ATTESTED"
    p["editorial_attestation"] = {
        "decision": "ACCEPT", "reviewer": "not real", "reason": "not authoritative",
        "source_storyboard_sha256": p["source"]["storyboard_sha256"],
    }
    with pytest.raises(ValueError, match="LOCK_INVALID"):
        source.approve_source_bound(document=p, story=story, storyboard=board, frame=2)


def test_changed_storyboard_updates_source_sha_and_no_stale_copy(local_storyboard):
    ep, story, board = local_storyboard
    initial = source.proposal(story=story, storyboard=board, frame=2)
    board.write_text(board.read_text("utf-8").replace("第二道砖缝", "第三道砖缝"), encoding="utf-8")
    refreshed = source.proposal(story=story, storyboard=board, frame=2)
    assert refreshed["source"] != initial["source"]
    assert refreshed["source_suggestions"]["storyboard_sha256"] != initial["source_suggestions"]["storyboard_sha256"]


def test_json_storyboard_also_yields_literal_suggestions(local_storyboard):
    ep, story, board = local_storyboard
    board_json = board.with_suffix(".json")
    board_json.write_text(json.dumps({"frames": [
        {"frame": 1, "scene": BASE}, {"frame": 2, "scene": NEXT},
    ]}, ensure_ascii=False), encoding="utf-8")
    document = source.proposal(story=story, storyboard=board_json, frame=2)
    assert document["source"]["format"] == "json_frame"
    assert document["source_suggestions"]["status"] == "ADVISORY_SOURCE_QUOTES_ONLY"
    assert document["source_suggestions"]["locked_quote_candidates"]["props"]


def test_unknown_mode_never_auto_assumes_motion(local_storyboard):
    ep, story, board = local_storyboard
    p = source.proposal(story=story, storyboard=board, frame=2)
    hints = suggest.analyze(
        story="主人公无具体活动。",
        previous="摄影机里的窗帘颜色保持原样。",
        current="窗帘还是相同的颜色和材质。",
        source=p["source"])
    assert hints["mode_hint"] == "UNKNOWN_NEEDS_REVIEW"
    assert "mode:explicit_movement_or_stillness" in hints["missing_evidence"]
