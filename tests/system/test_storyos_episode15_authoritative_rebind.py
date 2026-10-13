"""Four minimal checks for re-binding Episode 15 source without replaying A9."""
from pathlib import Path
import json
import sys
ROOT=Path(__file__).resolve().parents[2]
EP=ROOT/"episodes/15_天界生活日常/01_天界普通女生的一天"
sys.path.insert(0,str(ROOT/"scripts"))
sys.path.insert(0,str(ROOT/"episodes/_system"))
import storyos_a9_receipt_reconcile as a9
import story_review
import story_review_rubric_migration as migration
import text_audit

import pytest
from hashlib import sha256

@pytest.fixture
def frozen(tmp_path, monkeypatch):
    ep = tmp_path / "episodes" / "fixture"
    docs = ep / "docs"
    docs.mkdir(parents=True)
    story = docs / "02_StoryLock_V1.0.md"
    before = docs / "03_board_V1.0.md"
    after = docs / "03_board_V1.1.md"
    story.write_text("story v1", encoding="utf-8")
    before.write_text("board v1", encoding="utf-8")
    after.write_text("board v1.1", encoding="utf-8")
    stamp = {
        "story_sha256": sha256(story.read_bytes()).hexdigest(),
        "storyboard_sha256": sha256(before.read_bytes()).hexdigest(),
    }
    ticket = ep / migration.EPOCH_REL
    ticket.parent.mkdir(parents=True)
    ticket.write_text(json.dumps(stamp), encoding="utf-8")
    return ep, stamp, story, before, after

def test_v11_source_candidate_and_captions_are_manifest_bound_without_pass():
    m=json.loads((EP/"meta/release-manifest.json").read_text("utf-8-sig"))
    paths=m["artifacts"]
    assert paths["storyboard"].endswith("20张分镜修订草稿_V1.1.md")
    assert paths["captions"].endswith("docs/subtitles.yaml")
    assert m["quality"]["production_gate"]=="pending"
    assert m["quality"]["publish_decision"]=="hold"
    assert sorted(text_audit.parse_simple_subtitles_yaml(EP/"docs/subtitles.yaml")["frames"])==list(range(1,21))

def test_original_v1_a9_review_source_sha_can_still_be_recovered(frozen):
    ep, stamp, story, board, revised = frozen
    s, b = a9.frozen_story_paths(ep, stamp)
    assert s == story and b == board and b != revised
    assert story_review.sha256_file(s) == stamp["story_sha256"]
    assert story_review.sha256_file(b) == stamp["storyboard_sha256"]

def test_a9_prompt_sha_is_not_taken_from_new_manifest(frozen, monkeypatch):
    ep, stamp, story, board, revised = frozen
    monkeypatch.setattr(story_review, "critic_prompt",
                        lambda ep, s, b, candidate, attempt:
                        f"{s.name}|{b.name}|{attempt}")
    expected = f"{story.name}|{board.name}|9"
    assert a9.expected_prompt_sha(ep) == a9.sha256(
        (expected + story_review.DIRECT_CODEX_EXECUTION_OVERRIDE).encode("utf-8"))
    assert "V1.1" not in expected

def test_rebinding_does_not_grant_image_or_an_a9_retry():
    d=a9.decide(epoch_present=True,candidate={"summary":{"passed":False}},
                candidate_exists=True,
                evidence_status="PAID_CRITIC_TIMEOUT_NO_AUTORETRY",
                official_review_present=False)
    assert d["may_retry_attempt_9"] is False
    assert d["can_mark_review_pass"] is False
    assert d["can_dispatch_image"] is False
    assert d["sql_writes"]==d["model_calls"]==0
