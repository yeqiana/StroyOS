from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "episodes/_system"))
sys.path.insert(0, str(ROOT / "scripts"))
import frame_contract
import m00_episode_state_delta as episode_delta
import m00_storyboard_delta_sources as sources
import storyos_m00_storyboard_delta_drafts_r10 as drafts
import story_review

LOCK_VALUES = {
    "identity": "同一个成年男生一路推着旧车经过雨后的县城小巷",
    "wardrobe": "灰色防水外套和深蓝裤子以及磨损明显的旧运动鞋",
    "props": "后货架旧自行车车架和前轮的挡泥板都保持一样",
    "geography": "右侧旧墙上的水平灰砖缝和店门旁的绿色盆栽",
    "photographer": "同一位路人摄影者始终站在男子左后方举着旧手机",
    "lighting": "持续阴天的自然漫射光照亮潮湿的街巷路面",
}
BEFORE = "上一幅自行车前轮仍停留在第一道旧砖缝旁边"
AFTER = "下一幅自行车前轮已经越过水洼旁第二道砖缝"
EVIDENCE = "轮胎位置改变但同一辆车的后货架和挡泥板未变"


@pytest.fixture
def ep(tmp_path, monkeypatch):
    parent = tmp_path / "episodes/case"
    docs = parent / "docs"
    docs.mkdir(parents=True)
    story = docs / "story.md"
    story.write_text("故事中唯一同一条真实小巷：\n" + "\n".join(LOCK_VALUES.values()), encoding="utf-8")
    board = docs / "storyboard.md"
    board.write_text(
        "# 逐帧剧本\n| 帧 | 场景与动作 | 叙事功能 |\n|---|---|---|\n"
        f"| 01 | {BEFORE}，男生缓缓调整姿势。 | 记录前一状态。 |\n"
        f"| 02 | {AFTER}，{EVIDENCE}。 | 新的具体证据。 |\n",
        encoding="utf-8")
    monkeypatch.setattr(frame_contract, "artifact_paths", lambda _ep: (story, board))
    # Only the isolated test fixture mocks real Story Review; production code
    # must obtain the canonical review authority SHA from the Episode store.
    monkeypatch.setattr(story_review, "review_required", lambda _ep: True)
    monkeypatch.setattr(story_review, "verify", lambda _ep: [])
    monkeypatch.setattr(story_review, "review_authority_sha256", lambda _ep: "f" * 64)
    return parent, story, board


def attested(ep):
    folder, story, board = ep
    raw = sources.proposal(story=story, storyboard=board, frame=2)
    raw["status"] = "SOURCE_ATTESTED"
    raw["delta"] = {
        "schema_version": 1,
        "mode": "action",
        "locked": LOCK_VALUES.copy(),
        "observable_changes": [{"id": "wheel_progression",
                                "before": BEFORE, "after": AFTER,
                                "pixel_evidence": EVIDENCE},
                               {"id": "moment", "before": BEFORE,
                                "after": AFTER, "pixel_evidence": EVIDENCE}],
    }
    raw["editorial_attestation"] = {
        "decision": "ACCEPT", "reviewer": "Editorial fixture",
        "reason": "All before and after claims are exact existing source quotes.",
        "source_storyboard_sha256": raw["source"]["storyboard_sha256"],
        "story_review_authority_sha256": "f" * 64,
    }
    return raw


def test_slot1_true_markdown_table_exact_beat_extraction_and_draft_no_claim(ep):
    folder, story, board = ep
    raw = sources.proposal(story=story, storyboard=board, frame=2)
    assert raw["status"] == "DRAFT_ONLY"
    assert raw["authority"] == "SOURCE_QUOTATIONS_ONLY_NOT_A_REVIEW_PASS"
    assert BEFORE in raw["evidence"]["previous"]
    assert AFTER in raw["evidence"]["current"]
    assert not any(raw["delta"]["locked"].values())
    assert raw["delta"]["observable_changes"] == []
    assert sources.candidate_path(folder, 2).name == "02.json"


def test_slot2_attested_markdown_derives_source_bound_frame_contract(ep):
    folder, story, board = ep
    raw = attested(ep)
    target = sources.candidate_path(folder, 2)
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    admitted = episode_delta.source_transition(board, 2, "M00", episode=folder)
    assert admitted["source_format"] == "source_attested_markdown_table"
    assert admitted["delta"]["observable_changes"][0]["before"] == BEFORE
    assert admitted["source_attestation_sha256"]
    assert len(admitted["source_document_sha256"]) == 64
    assert admitted["storyboard_sha256"] == sources.digest(board)
    assert admitted["previous_frame_excerpt_sha256"] == raw["source"]["previous_excerpt_sha256"]


def test_no_forged_story_review_authority_even_if_source_quotes_pass(ep, monkeypatch):
    folder, story, board = ep
    raw = attested(ep)
    raw["editorial_attestation"]["story_review_authority_sha256"] = "e" * 64
    target = sources.candidate_path(folder, 2)
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="STORY_REVIEW_AUTHORITY_SHA_MISMATCH"):
        episode_delta.source_transition(board, 2, "M00", episode=folder)
    raw["editorial_attestation"]["story_review_authority_sha256"] = "f" * 64
    target.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(story_review, "verify", lambda _ep: ["current storyboard SHA drift"])
    with pytest.raises(ValueError, match="CANONICAL_STORY_REVIEW_INVALID"):
        episode_delta.source_transition(board, 2, "M00", episode=folder)


def test_slot3_wrong_or_forged_text_in_lock_and_actions_fails(ep):
    folder, story, board = ep
    raw = attested(ep)
    raw["delta"]["locked"]["props"] = "不存在的全新大型摩托车顶着自行车向前滑动"
    with pytest.raises(ValueError, match="UNSUPPORTED_LOCK"):
        sources.approve_source_bound(document=raw, story=story, storyboard=board, frame=2)
    raw = attested(ep)
    raw["delta"]["observable_changes"][0]["after"] = "下一幅男子走到凭空出现的现代高架桥下面"
    with pytest.raises(ValueError, match="UNSUPPORTED_ACTION"):
        sources.approve_source_bound(document=raw, story=story, storyboard=board, frame=2)


def test_action_cannot_borrow_quote_from_unrelated_story_moment(ep):
    folder, story, board = ep
    raw = attested(ep)
    # Real source quote, but not the authorized *current* storyboard beat.
    raw["delta"]["observable_changes"][0]["after"] = LOCK_VALUES["geography"]
    with pytest.raises(ValueError, match="UNSUPPORTED_ACTION"):
        sources.approve_source_bound(document=raw, story=story, storyboard=board, frame=2)


def test_slot3_authority_attestation_missing_never_promotes_draft(ep):
    folder, story, board = ep
    raw = sources.proposal(story=story, storyboard=board, frame=2)
    with pytest.raises(ValueError, match="SOURCE_SHA_OR_EXCERPT_DRIFT"):
        sources.approve_source_bound(document=raw, story=story, storyboard=board, frame=2)
    raw = attested(ep)
    raw["editorial_attestation"] = {"decision": "PASS"}
    with pytest.raises(ValueError, match="EDITORIAL_ATTESTATION_REQUIRED"):
        sources.approve_source_bound(document=raw, story=story, storyboard=board, frame=2)


def test_slot2_source_drift_stops_acceptance_before_provider(ep):
    folder, story, board = ep
    original = attested(ep)
    board.write_text(board.read_text("utf-8") + "\n| 03 | 另一街口 | 转场 |\n", encoding="utf-8")
    with pytest.raises(ValueError, match="SOURCE_SHA_OR_EXCERPT_DRIFT"):
        sources.approve_source_bound(document=original, story=story, storyboard=board, frame=2)
    board.write_text(board.read_text("utf-8").replace("下一幅自行车", "新场景自行车"), encoding="utf-8")
    with pytest.raises(ValueError, match="SOURCE_SHA_OR_EXCERPT_DRIFT"):
        sources.approve_source_bound(document=original, story=story, storyboard=board, frame=2)


def test_slot1_no_optin_retains_legacy_m00_and_nonm00(ep):
    folder, story, board = ep
    assert episode_delta.source_transition(board, 2, "M00", episode=folder) is None
    assert episode_delta.source_transition(board, 2, "M01", episode=folder) is None


def test_slot4_drafts_plan_and_apply_never_overwrite(ep, monkeypatch):
    folder, story, board = ep
    monkeypatch.setattr(drafts, "ROOT", folder.parent.parent)
    monkeypatch.setattr(drafts.frame_contract, "frame_count", lambda _: 2)
    monkeypatch.setattr(drafts.visual_profile, "compile_prompt_contract", lambda _: {"profile_id": "M00"})
    initial = drafts.prepare(folder, apply=False)
    assert initial["status"] == "DRY_RUN"
    assert initial["created"] == 0
    assert not sources.candidate_path(folder, 2).exists()
    produced = drafts.prepare(folder, apply=True)
    assert produced["created"] == 1
    assert produced["formal_generation_calls"] == 0
    first = sources.candidate_path(folder, 2).read_bytes()
    assert drafts.prepare(folder, apply=True)["existing_untouched"] == 1
    assert sources.candidate_path(folder, 2).read_bytes() == first
    assert episode_delta.source_transition(board, 2, "M00", episode=folder) is None
    # No source approval and no production Frame Contract hash change.


def test_multi_frame_preflight_does_not_partial_write(ep, monkeypatch):
    folder, story, board = ep
    monkeypatch.setattr(drafts, "ROOT", folder.parent.parent)
    monkeypatch.setattr(drafts.frame_contract, "frame_count", lambda _: 3)
    monkeypatch.setattr(drafts.visual_profile, "compile_prompt_contract", lambda _: {"profile_id": "M00"})
    with pytest.raises(ValueError, match="FRAME_NOT_FOUND"):
        drafts.prepare(folder, apply=True)
    assert not sources.candidate_path(folder, 2).exists()


def test_unrecognized_sidecar_status_blocks_but_draft_only_never_blocks(ep):
    folder, story, board = ep
    candidate = sources.candidate_path(folder, 2)
    candidate.parent.mkdir(parents=True)
    raw = sources.proposal(story=story, storyboard=board, frame=2)
    candidate.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    assert episode_delta.source_transition(board, 2, "M00", episode=folder) is None
    raw["status"] = "MANUALLY_PRETENDED_PASS"
    candidate.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="UNKNOWN_SIDECAR_STATUS"):
        episode_delta.source_transition(board, 2, "M00", episode=folder)


def test_missing_frame_and_duplicate_markdown_rows_fail_closed(ep):
    folder, story, board = ep
    with pytest.raises(ValueError, match="FRAME_NOT_FOUND"):
        sources.proposal(story=story, storyboard=board, frame=3)
    board.write_text(board.read_text("utf-8") +
                     f"| 02 | {AFTER} | 另一个不受权威许可的版本 |\n", encoding="utf-8")
    with pytest.raises(ValueError, match="DUPLICATE_STORYBOARD_FRAME"):
        sources.proposal(story=story, storyboard=board, frame=2)


def test_static_requires_no_invented_action(ep):
    folder, story, board = ep
    raw = attested(ep)
    raw["delta"]["mode"] = "static"
    raw["delta"]["observable_changes"] = []
    verified = sources.approve_source_bound(document=raw, story=story, storyboard=board, frame=2)
    assert verified["delta"]["mode"] == "static"
    assert verified["delta"]["observable_changes"] == []


def test_markdown_undocumented_storyboard_changes_never_silently_accepted(ep):
    folder, story, board = ep
    approved = attested(ep)
    board.write_text(board.read_text("utf-8").replace("第二道砖缝", "第三道砖缝"), encoding="utf-8")
    with pytest.raises(ValueError, match="SOURCE_SHA_OR_EXCERPT_DRIFT"):
        sources.approve_source_bound(document=approved, story=story, storyboard=board, frame=2)
