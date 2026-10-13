"""R14 slot3: mutated historical Review source SHA cannot admit a new paid Critic."""
import sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"episodes"/"_system"))
import story_review
import story_review_rubric_migration as epoch
import product_review_adapter as req

def setup_mock(tmp_path,monkeypatch,standard_sha):
    ep=tmp_path/"episodes"/"fiction"
    ep.mkdir(parents=True)
    prior=ep/story_review.REVIEW_REL
    prior.parent.mkdir(parents=True,exist_ok=True)
    prior.write_text("{}")
    story=ep/"story.md";story.write_text("story")
    board=ep/"board.md";board.write_text("board")
    monkeypatch.setattr(story_review,"ROOT",tmp_path)
    monkeypatch.setattr(story_review,"load_review",lambda ep:None)
    monkeypatch.setattr(story_review,"read_json",
        lambda path:{"summary":{"passed":True},
                     "critic_provenance":{"attempt":2,"request_id":"req2"},
                     "story_sha256":"a"*64,
                     "storyboard_sha256":"a"*64})
    monkeypatch.setattr(story_review,"story_paths",lambda ep:(story,board))
    monkeypatch.setattr(story_review,"sha256_file",lambda path:"a"*64)
    monkeypatch.setattr(story_review,"validate_payload",lambda *a,**k:[])
    monkeypatch.setattr(story_review,"episode_contract_version",lambda ep:"v")
    monkeypatch.setattr(req,"_request_exists",lambda path:True)
    monkeypatch.setattr(req,"request_path",lambda *a,**k:ep/"request.json")
    frozen=[
        {"path":epoch.FORMAL_STANDARD,"sha256":standard_sha},
        {"path":"episodes/legacy/story.md","sha256":"a"*64},
        {"path":"episodes/legacy/board.md","sha256":"a"*64},
        {"path":"standards/other.md","sha256":"a"*64},
    ]
    monkeypatch.setattr(req,"_read_json",lambda path:{
        "status":"FINALIZED","attempt":2,"review_kind":"story-semantic",
        "request_id":"req2","source_files":frozen})
    return ep

@pytest.mark.parametrize("bad",["not-a-sha","0"*63,"z"*64])
def test_frozen_rubric_digest_must_be_valid_sha256(tmp_path,monkeypatch,bad):
    ep=setup_mock(tmp_path,monkeypatch,bad)
    assert epoch.plan(ep)["status"]=="FROZEN_SOURCE_SHA_MALFORMED"

def test_missing_review_source_is_refused_without_paid_call(tmp_path,monkeypatch):
    ep=setup_mock(tmp_path,monkeypatch,"a"*64)
    (ep/story_review.REVIEW_REL).unlink()
    result=epoch.plan(ep)
    assert result["status"]=="HISTORICAL_PAYLOAD_MISSING"
    assert result["provider_calls"]==result["sql_writes"]==0
