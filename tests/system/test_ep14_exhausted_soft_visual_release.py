"""Evidence-first Episode14 soft-only 2/2 weak-pass policy regressions."""
from __future__ import annotations
import json,sys
from pathlib import Path
from unittest.mock import patch
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"episodes/_system"))
import visual_lock_candidate_pool as pool
import visual_lock_admission_state as admissions


@pytest.mark.parametrize("frame", [1,5,45,47])
def test_two_paid_success_only_soft_review_exhausted_can_be_weak(frame,monkeypatch,tmp_path):
    ledger={"status":"NEEDS_USER","attempts":[
        {"result":"success"},{"result":"success"}],
        "current_candidate":{"sha256":"a"*64}}
    if frame==1: ledger["attempts"]=[{"result":"success"}]
    row={"id":str(frame),"frame":frame,"sha256":"a"*64,
         "checks":{"capture_credibility":True,"not_cinematic":False},
         "issues":["CINEMATIC_PRESENTATION"]}
    monkeypatch.setattr(pool,"_ledger_frame",lambda *_:ledger)
    monkeypatch.setattr(pool,"_row_for_frame",lambda *_:row)
    monkeypatch.setattr(pool,"weak_pass_allowed",lambda *_:True)
    monkeypatch.setattr(pool,"_ep14_exhausted_weak_pass",lambda *args:True)
    result=pool.weak_pass_eligibility(tmp_path,frame)
    assert result["eligible"] is True
    assert result["episode14_paid_exhaustion"] is True
    assert result["threshold"]==2
    assert result["hard_failed_checks"]==[]
    assert result["hard_issue_codes"]==[]


@pytest.mark.parametrize("checks,issues",[
    ({"camera_authorship_physical":False},["CINEMATIC_PRESENTATION"]),
    ({"not_cinematic":False},["WRONG_SCENE"]),
    ({"capture_credibility":False},["CINEMATIC_PRESENTATION"]),
    ({"not_cinematic":False},["FRAME_CONTRACT_MISMATCH"]),
])
def test_budget_2of2_never_overrides_hard_vision_failure(tmp_path,monkeypatch,checks,issues):
    ledger={"status":"NEEDS_USER","attempts":[{"result":"success"}]*2,
            "current_candidate":{"sha256":"a"*64}}
    monkeypatch.setattr(pool,"_ledger_frame",lambda *_:ledger)
    monkeypatch.setattr(pool,"_row_for_frame",lambda *_:{
        "id":"5","sha256":"a"*64,"checks":checks,"issues":issues})
    monkeypatch.setattr(pool,"weak_pass_allowed",lambda *_:True)
    monkeypatch.setattr(pool,"_ep14_exhausted_weak_pass",lambda *args:True)
    assert pool.weak_pass_eligibility(tmp_path,5)["eligible"] is False


def test_opt_out_fails_even_with_paid_proof(monkeypatch,tmp_path):
    monkeypatch.setattr(pool,"_ledger_frame",lambda *_:{
        "status":"NEEDS_USER","attempts":[{"result":"success"}]*2,
        "current_candidate":{"sha256":"a"*64}})
    monkeypatch.setattr(pool,"_row_for_frame",lambda *_:{
        "id":"5","sha256":"a"*64,"checks":{"not_cinematic":False},
        "issues":["CINEMATIC_PRESENTATION"]})
    monkeypatch.setattr(pool,"weak_pass_allowed",lambda *_:False)
    monkeypatch.setattr(pool,"_ep14_exhausted_weak_pass",lambda *args:True)
    assert pool.weak_pass_eligibility(tmp_path,5)["eligible"] is False


def test_other_episode_cannot_take_special_paid2of2_policy(tmp_path):
    assert pool._ep14_exhausted_weak_pass(tmp_path,5,{}, {}) is False


def test_original_critic_fail_snapshot_kept_with_policy_weakpass(tmp_path,monkeypatch):
    ep=tmp_path/"episode"
    ep.mkdir()
    prior={"status":"FAIL","frame":5,"sha256":"a"*64,
           "frame_contract_sha256":"b"*64,
           "provenance":{"log":"real-original-codex-vision.jsonl","review_capability":"vision"},
           "review_row":{"issues":["CINEMATIC_PRESENTATION"]}}
    data={"items":{"admission5":prior},"updated_at":"before"}
    monkeypatch.setattr(admissions,"load",lambda *_:data)
    monkeypatch.setattr(admissions,"binding",lambda *_args,**_kw:{
        "id":"admission5","frame":5,"sha256":"a"*64,
        "frame_contract_sha256":"b"*64})
    monkeypatch.setattr(admissions.story_json,"write_json",lambda *args,**kw:None)
    asset={"id":"admission5","frame":5,"sha256":"a"*64,"frame_contract_sha256":"b"*64}
    entry=admissions.record_weak_pass(
        ep,asset=asset,review_row=prior["review_row"],
        profile_sha256="p"*64,story_os_version="StoryOS",
        content_attempts=2,technical_attempts=3,
        failed_checks=["not_cinematic"],issue_codes=["CINEMATIC_PRESENTATION"],
        reason="2/2 paid budget exhausted, soft failure retained",
        approved_by_policy="episode14_paid_2of2_soft_visual_quality")
    assert entry["status"]=="WEAK_PASS"
    assert entry["weak_pass"]["prior_independent_fail"]==prior
    assert entry["weak_pass"]["approved_by_policy"]=="episode14_paid_2of2_soft_visual_quality"
    assert entry["review_row"]["issues"]==["CINEMATIC_PRESENTATION"]


def test_exhaustion_policy_requires_original_real_fail_before_writing(tmp_path,monkeypatch):
    ep=tmp_path/"ep"
    ep.mkdir()
    monkeypatch.setattr(admissions,"load",lambda *_:{"items":{}})
    monkeypatch.setattr(admissions,"binding",lambda *_args,**_kw:{})
    with pytest.raises(ValueError,match="ORIGINAL_FAIL"):
        admissions.record_weak_pass(
            ep,asset={"id":"5"},review_row={},profile_sha256="p"*64,
            story_os_version="x",content_attempts=2,technical_attempts=0,
            failed_checks=[],issue_codes=["CINEMATIC_PRESENTATION"],
            reason="exhaustion",
            approved_by_policy="episode14_paid_2of2_soft_visual_quality")
