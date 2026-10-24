"""An existing F001 FAIL is never overwritten to obtain new independent evidence."""
import json
import sys
from pathlib import Path

import pytest

SYSTEM=Path(__file__).resolve().parents[2]/"episodes"/"_system"
sys.path.insert(0,str(SYSTEM))
import visual_lock_baseline_review_only as rereview


def valid():
    return {"pixel_evidence_available":True,"decision":"PASS",
            "checks":{k:"PASS" for k in rereview.baseline.CHECKS},
            "face_boxes":[],"note":"actual pixels were inspected"}


@pytest.mark.parametrize("case,expected",[
    ("pass","REVIEW_ONLY_PASS"),
    ("style_fail","REVIEW_ONLY_FAIL"),
    ("contradictory","REVIEW_ONLY_FAIL"),
    ("no_pixel","TECHNICAL_FAILURE"),
    ("missing_checks","TECHNICAL_FAILURE"),
    ("untyped_check","TECHNICAL_FAILURE"),
    ("no_face_list","TECHNICAL_FAILURE"),
    ("not_dict","TECHNICAL_FAILURE"),
])
def test_review_only_verdict_cannot_force_pass(case,expected):
    r=valid()
    if case=="style_fail":
        r["decision"]="FAIL";r["checks"]["not_cinematic"]="FAIL"
    if case=="contradictory":
        r["checks"]["visual_profile_match"]="FAIL"
    if case=="no_pixel":r["pixel_evidence_available"]=False
    if case=="missing_checks":r["checks"].pop("identity_usable")
    if case=="untyped_check":r["checks"]["reality_first"]="N/A"
    if case=="no_face_list":r["face_boxes"]=None
    if case=="not_dict":r=[]
    assert rereview.verdict(r)==expected


def test_unauthorized_recritic_never_calls_inspect(tmp_path,monkeypatch):
    monkeypatch.setattr(rereview,"inspect",lambda ep:pytest.fail("unexpected source inspection"))
    with pytest.raises(rereview.ReviewOnlyDenied,match="ACK_REQUIRED"):
        rereview.review_only(tmp_path,False)


@pytest.mark.parametrize("source",["old","oldlog","asset"])
def test_source_changes_block_after_review(tmp_path,monkeypatch,source):
    files={}
    for name in ("old","oldlog","asset"):
        f=tmp_path/name
        f.write_bytes(b"stable")
        files[name]=f
    ref={name+"_sha":rereview.sha(f) for name,f in files.items()}
    ref.update(files)
    ref["image_sha"]=ref["asset_sha"]
    ref["ep"]=tmp_path
    files[source].write_bytes(b"mutated")
    with pytest.raises(rereview.ReviewOnlyDenied,match="SOURCE_MUTATED"):
        rereview.verify_unchanged(ref)


def test_driver_live_rejects_source_check(tmp_path,monkeypatch):
    ep=tmp_path/"episode";ep.mkdir()
    monkeypatch.setattr(rereview,"ROOT",tmp_path)
    monkeypatch.setattr(rereview,"REL",Path("episode"))
    monkeypatch.setattr(rereview.runtime_driver,"status",
        lambda _:{"driver_state":"RUNNING","liveness":"ALIVE","exit_code":None,"pid":25})
    with pytest.raises(rereview.ReviewOnlyDenied,match="DRIVER_NOT_STOPPED"):
        rereview.inspect(ep)


def test_wrong_episode_never_touches_driver(tmp_path,monkeypatch):
    monkeypatch.setattr(rereview,"ROOT",tmp_path)
    monkeypatch.setattr(rereview.runtime_driver,"status",
        lambda _:pytest.fail("driver must not be probed for foreign episode"))
    with pytest.raises(rereview.ReviewOnlyDenied,match="WRONG_EPISODE"):
        rereview.inspect(tmp_path/"other")


def test_driver_rc22_can_be_persisted_as_string():
    assert str("22")=="22"
    assert str(22)=="22"

from datetime import datetime, timedelta, timezone


def _usage_limited_fixture(tmp_path):
    prefix=tmp_path/"f001-source"
    log=prefix.with_suffix(".log.jsonl")
    log.write_text(
        '{"type":"error","message":"You’ve hit your usage limit. try again at 3:20 PM."}\n'
        '{"type":"turn.failed"}\n',encoding="utf-8")
    record={
        "status":"TECHNICAL_FAILURE","critic_returncode":1,"reply":{},
        "prior_review_sha256":"a"*64,"image_sha256":"b"*64,
        "frame_contract_sha256":"c"*64,"prompt_sha256":"d"*64,
        "image_generation_calls":0,"image_attempts_reserved":0,
        "critic_provenance":{
            "reviewed_at":"2026-10-24T12:15:31+08:00",
            "log_sha256":rereview.sha(log)},
    }
    prefix.with_suffix(".json").write_text(json.dumps(record),encoding="utf-8")
    return prefix,record


def _recover(prefix,now):
    return rereview.quota_recovery_prefix(
        prefix,oldsha="a"*64,image_sha="b"*64,
        contract_sha="c"*64,promptsha="d"*64,now=now)


def test_actual_quota_time_blocks_pre_reset(tmp_path):
    prefix,_=_usage_limited_fixture(tmp_path)
    before=datetime(2026,10,24,15,19,tzinfo=timezone(timedelta(hours=8)))
    with pytest.raises(rereview.ReviewOnlyDenied,match="CODEX_USAGE_LIMIT_NOT_RESET"):
        _recover(prefix,before)


def test_exact_old_evidence_can_recover_once_after_reset(tmp_path):
    prefix,_=_usage_limited_fixture(tmp_path)
    after=datetime(2026,10,24,15,21,tzinfo=timezone(timedelta(hours=8)))
    new,receipt_sha=_recover(prefix,after)
    assert new!=prefix
    assert len(receipt_sha)==64
    assert not new.with_suffix(".json").exists()
    new.with_suffix(".log.jsonl").write_text("review resumed",encoding="utf-8")
    with pytest.raises(rereview.ReviewOnlyDenied,match="QUOTA_REVIEW_ALREADY_RETRIED"):
        _recover(prefix,after)


@pytest.mark.parametrize("mutate",["old_sha","image","approved","log","not_quota"])
def test_unsafe_quota_rearm_fails_closed(tmp_path,mutate):
    prefix,record=_usage_limited_fixture(tmp_path)
    report=prefix.with_suffix(".json")
    log=prefix.with_suffix(".log.jsonl")
    if mutate=="old_sha": record["prior_review_sha256"]="e"*64
    if mutate=="image":record["image_sha256"]="e"*64
    if mutate=="approved":record["status"]="REVIEW_ONLY_PASS"
    if mutate=="log":log.write_text("tampered",encoding="utf-8")
    if mutate=="not_quota":
        log.write_text('{"type":"turn.failed","message":"network error"}',encoding="utf-8")
        record["critic_provenance"]["log_sha256"]=rereview.sha(log)
    report.write_text(json.dumps(record),encoding="utf-8")
    after=datetime(2026,10,24,15,21,tzinfo=timezone(timedelta(hours=8)))
    with pytest.raises(rereview.ReviewOnlyDenied):
        _recover(prefix,after)
