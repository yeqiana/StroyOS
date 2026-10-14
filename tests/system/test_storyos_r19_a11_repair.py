"""R19 independent A11 material source repair and one-shot safety."""
from __future__ import annotations
import json
from pathlib import Path
import pytest
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/"episodes/_system"),str(ROOT/"scripts")]
import story_review as sr
import story_review_a10_source_revision as a10
import story_review_a11_source_repair as a11
import story_review_attempt_admission as admit
import review_record_persistence as store
from text_audit import parse_simple_subtitles_yaml

EP=ROOT/a11.EXPECTED_EPISODE


def test_r19_real_content_all_20_and_source_not_formally_passed():
    story,board=sr.story_paths(EP)
    old=EP/"docs/03_天界普通女生的一天_20张分镜修订草稿_V1.1.md"
    assert board.name.endswith("V1.2.md") and old.exists()
    assert sr.sha256_file(old)!=sr.sha256_file(board)
    caption=EP/"docs/subtitles.yaml"
    before=EP/"docs/subtitles_V1.1.yaml"
    assert before.exists() and sr.sha256_file(before)!=sr.sha256_file(caption)
    frames=parse_simple_subtitles_yaml(caption)["frames"]
    assert sorted(frames)==list(range(1,21))
    for i,tokens in {
        3:("留","热糕"),4:("留","热糕"),8:("窗边","端盘子"),
        9:("窗边","点心"),18:("主动","点心")
    }.items():
        assert all(s in frames[i] for s in tokens),i
    txt=board.read_text("utf-8-sig")
    assert all(s in txt for s in ("3. **专门留早餐**",
        "4. **P04 看见为自己留的早餐**",
        "8. **抢窗边位置的小习惯**",
        "9. **又想抢最后一块点心**","18. **这回先给朋友**"))
    manifest=json.loads((EP/"meta/release-manifest.json").read_text("utf-8-sig"))
    assert manifest["quality"]["publish_decision"]=="hold"
    assert manifest["artifacts"]["storyboard"].endswith("V1.2.md")


@pytest.fixture()
def fixture(tmp_path,monkeypatch):
    root=tmp_path
    (root/".git").mkdir()
    ep=root/a11.EXPECTED_EPISODE
    doc=ep/"docs"
    doc.mkdir(parents=True)
    story=doc/"02_StoryLock_V1.0.md"
    old_board=doc/"03_天界普通女生的一天_20张分镜修订草稿_V1.1.md"
    new_board=doc/"03_天界普通女生的一天_20张分镜修订草稿_V1.2.md"
    old_cap=doc/"subtitles_V1.1.yaml"
    cap=doc/"subtitles.yaml"
    story.write_text("unchanged story",encoding="utf-8")
    old_board.write_text("prior storyboard",encoding="utf-8")
    new_board.write_text("\n".join([
        "3. **专门留早餐**","4. **P04 看见为自己留的早餐**",
        "8. **抢窗边位置的小习惯**",
        "9. **又想抢最后一块点心**","18. **这回先给朋友**"
    ]),encoding="utf-8")
    old_cap.write_text("frames:\n  1: \"before\"\n",encoding="utf-8")
    cap.write_text("frames:\n"+"".join(
        f'  {i}: "第{i}帧补足信息的剧情字幕"\n' for i in range(1,21)),encoding="utf-8")
    old_ticket=ep/a10.EPOCH_REL
    old_ticket.parent.mkdir(parents=True)
    old_ticket.write_text(json.dumps({
        "global_review_attempt":10,
        "story_sha256":a11.sha(story),
        "storyboard_sha256":a11.sha(old_board),
        "subtitle_source_sha256":a11.sha(old_cap),
    }),encoding="utf-8")
    candidate=ep/a10.CANDIDATE_REL
    candidate.write_text('{"summary":{"passed":false},"issue_codes":["DELETE_FRAME_TEST_FAIL"]}',encoding="utf-8")
    prior={"story_sha256":a11.sha(story),
           "storyboard_sha256":a11.sha(old_board),
           "subtitle_source_sha256":a11.sha(old_cap),
           "critic_provenance":{"attempt":10,"review_scope":a10.REVIEW_SCOPE},
           "summary":{"passed":False},"issue_codes":["DELETE_FRAME_TEST_FAIL"]}
    monkeypatch.setattr(sr,"ROOT",root)
    monkeypatch.setattr(sr,"story_paths",lambda ep:(story,new_board))
    monkeypatch.setattr(sr,"load_review",lambda ep:prior)
    monkeypatch.setattr(sr,"_review_rubric_digest",lambda source:"e"*64)
    monkeypatch.setattr(a11,"_previous_mysql_a10",
        lambda ep:(1,prior,store._payload_content_sha(prior)))
    monkeypatch.setattr(store,"load_attempt",lambda *args,**kwargs:prior)
    return ep,prior,story,old_board,new_board,old_cap,cap,candidate


def test_r19_one_shot_plan_readonly_and_old_fail_sha_binds(fixture):
    ep,prior,*_=fixture
    status=a11.plan(ep)
    assert status["status"]=="ONE_SHOT_A11_SOURCE_REPAIR_READY"
    assert status["attempt"]==11
    assert status["model_calls"]==status["sql_writes"]==0
    assert status["can_dispatch_image"] is False
    assert status["previous_review_sha256"]==store._payload_content_sha(prior)


def test_r19_a11_durable_ticket_only_once_prior_candidate_intact(fixture):
    ep,prior,*_,candidate=fixture
    original=candidate.read_bytes()
    stamp=a11.authorize(ep,attempt=11,current_rubric_sha256="e"*64)
    assert stamp["review_epoch"]==10
    assert stamp["previous_review_sha256"]==store._payload_content_sha(prior)
    assert a11.validate_epoch(ep,{**stamp,"attempt":11})
    assert candidate.read_bytes()==original
    with pytest.raises(RuntimeError):
        a11.authorize(ep,attempt=11,current_rubric_sha256="e"*64)
    candidate.write_text("tampered",encoding="utf-8")
    assert not a11.validate_epoch(ep,{**stamp,"attempt":11})


def test_r19_old_requests_not_replayed_and_driver_still_blocked():
    old={"critic_provenance":{"attempt":10,"review_scope":a10.REVIEW_SCOPE},
         "summary":{"passed":False},"issue_codes":["DELETE_FRAME_TEST_FAIL"]}
    rows={1:{"status":"AWAITING_PRODUCT_REVIEW"},2:{"status":"FINALIZED"}}
    d=admit.decide(dag_attempt=162,official_review=old,
                   request_rows=rows,candidate_exists={})
    assert d["status"]=="A10_FAIL_REQUIRES_NEW_SOURCE_REVIEW_AUTHORITY"
    assert d["may_dispatch"] is False
    assert d["model_calls"]==d["sql_writes"]==0
    pass_prov={"attempt":11,"review_scope":a11.REVIEW_SCOPE,
          "review_epoch":10,"epoch_attempt":1,"direct_user_continuation_review":True}
    gated=admit.decide(dag_attempt=162,official_review={
        "critic_provenance":pass_prov,"summary":{"passed":True}},
        request_rows=rows,candidate_exists={})
    assert gated["status"]=="EXISTING_REVIEW_MUST_BE_REVALIDATED"
    assert gated["may_dispatch"] is False
