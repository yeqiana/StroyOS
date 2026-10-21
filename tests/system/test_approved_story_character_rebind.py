"""General approved Story -> frozen Character Contract SHA rebind, fail-closed."""
from __future__ import annotations
from copy import deepcopy
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"episodes"/"_system"))
import character_contract as cc
import story_narrative_form
import scoped_codex_worker
import runtime_dag
import story_review
import episode_state_persistence


def fixture(tmp_path,monkeypatch,attempt=15):
    ep=tmp_path/"episode"
    docs=ep/"docs"
    docs.mkdir(parents=True)
    (docs/"story.md").write_text(
        "Aze and Lin go walking. Lin calls Aze. Aze checks Lin is safe. "*8,
        encoding="utf-8")
    gate=ep/"meta/story-gates.json"
    gate.parent.mkdir()
    gate.write_text(json.dumps({"reviews":{"story":"passed"},"story":{"task_closed":True}}))
    sha=hashlib.sha256((docs/"story.md").read_bytes()).hexdigest()
    contract={"schema_version":1,"status":"LOCKED",
              "cast":{"size":2,"members":[{"id":"a","name":"Aze"},{"id":"b","name":"Lin"}]},
              "no_anomaly_test":{"pass":True,"rechecked_against_final_story":True,
                                 "ordinary_day_plan":"Aze and Lin are friends."},
              "entry":{"type":"travel"},"world_identity":{"effective_sha256":"same"},
              "final_story_review":{"source":"old_attestation",
                  "story_path":"docs/story.md",
                  "story_sha256":"b"*64,"review_reason":"original review attested"},
              "source_revision":{"scope":"HISTORICAL_INITIAL_REVIEW",
                                 "immutable_token":"preserved"},
              "locked_at":"old"}
    current={"contract":contract,"authority":"a"*64,"stage":"IDEA_LOCKED",
             "review_valid":True,"gate":True,"save_calls":[],
             "expected_review_sha":"c"*64}
    review={"summary":{"passed":True},"issue_codes":[],
            "story_sha256":sha,
            "critic_provenance":{"attempt":attempt,"review_scope":"OFFICIAL_PRODUCTION",
                                 "isolated_session":True}}
    monkeypatch.setattr(story_review,"load_review",lambda e:review)
    monkeypatch.setattr(story_review,"review_required",lambda e:True)
    monkeypatch.setattr(story_review,"review_authority_sha256",
                        lambda e:current["expected_review_sha"])
    monkeypatch.setattr(story_review,"verify",
                        lambda e: [] if current["review_valid"] else ["review source mismatch"])
    monkeypatch.setattr(episode_state_persistence,"load",
                        lambda e: {"current_state":current["stage"]})
    monkeypatch.setattr(cc,"load",lambda e:deepcopy(current["contract"]))
    monkeypatch.setattr(cc,"authority_sha256",lambda e:current["authority"])
    monkeypatch.setattr(cc.story_json,"read_json",
                        lambda path,default=None: (
                            {"reviews":{"story":"passed" if current["gate"] else "pending"},
                             "story":{"task_closed":True}}))
    def validate(ep,require_locked=False,*,candidate=None):
        data=candidate if candidate is not None else current["contract"]
        return ([] if data["final_story_review"]["story_sha256"]==sha
                else ["final Story review source SHA drift"])
    monkeypatch.setattr(cc,"validate",validate)
    def save(ep,value,*,expected_sha256=None):
        if expected_sha256 != current["authority"]:raise ValueError("CAS_CONFLICT")
        current["save_calls"].append(deepcopy(value))
        current["contract"]=deepcopy(value)
        current["authority"]="d"*64
    monkeypatch.setattr(cc,"save",save)
    return ep,current,review


def test_plan_is_readonly_and_generic_across_review_attempts(tmp_path,monkeypatch):
    ep,c,_=fixture(tmp_path,monkeypatch,attempt=41)
    plan=cc.approved_story_rebind(ep)
    assert plan["status"]=="VERIFIED_REBIND_READY"
    assert plan["bind"]["review_attempt"]==41
    assert plan["model_calls"]==plan["image_calls"]==0
    assert plan["read_only"] is True
    assert c["save_calls"]==[]


def test_authoritative_pass_auto_rebind_appends_immutable_version_and_is_idempotent(tmp_path,monkeypatch):
    ep,c,_=fixture(tmp_path,monkeypatch)
    first=cc.approved_story_rebind(ep,write=True)
    assert first["status"]=="REBOUND_VERIFIED"
    assert len(c["save_calls"])==1
    updated=c["contract"]
    assert updated["source_revision"]["immutable_token"]=="preserved"
    assert updated["cast"]["members"][0]["name"]=="Aze"
    assert updated["locked_at"]=="old"
    assert updated["approved_story_rebindings"][0]["previous_character_sha256"]=="a"*64
    assert updated["approved_story_rebindings"][0]["review_attempt"]==15
    assert updated["final_story_review"]["source"]=="verified_official_story_pass_rebind"
    assert cc.approved_story_rebind(ep,write=True)["status"]=="ALREADY_BOUND"
    assert len(c["save_calls"])==1


@pytest.mark.parametrize("fault",[
    "gate","review","name","stage","source","invalid",
])
def test_refuse_uncertain_new_story_without_cast_rewrite_or_sql(tmp_path,monkeypatch,fault):
    ep,c,r=fixture(tmp_path,monkeypatch)
    if fault=="gate":c["gate"]=False
    elif fault=="review":c["review_valid"]=False
    elif fault=="name":c["contract"]["cast"]["members"][1]["name"]="UnknownUser"
    elif fault=="stage":c["stage"]="PRODUCTION_PASSED"
    elif fault=="source":(ep/"docs/story.md").write_text("changed content",encoding="utf-8")
    elif fault=="invalid":c["contract"]["final_story_review"]["story_sha256"]=None
    row=cc.approved_story_rebind(ep,write=True)
    assert row["status"] not in {"REBOUND_VERIFIED","ALREADY_BOUND"}
    assert not c["save_calls"]


def test_cas_race_cannot_become_success(tmp_path,monkeypatch):
    ep,c,_=fixture(tmp_path,monkeypatch)
    orig=cc.authority_sha256
    calls=[]
    def changed(ep):
        calls.append(1)
        return "f"*64 if len(calls)>1 else "a"*64
    monkeypatch.setattr(cc,"authority_sha256",changed)
    result=cc.approved_story_rebind(ep,write=True)
    assert result["status"]=="APPROVED_STORY_AUTHORITY_CHANGED_BEFORE_CAS"
    assert not c["save_calls"]


def test_review_pass_never_reauthorizes_model_after_stage_drift(tmp_path,monkeypatch):
    ep,c,_=fixture(tmp_path,monkeypatch)
    assert story_narrative_form.approved_review_dispatch_block(ep)==(
        "OFFICIAL_STORY_ALREADY_PASS_DETERMINISTIC_RESUME_ONLY")
    monkeypatch.setattr(scoped_codex_worker,"resolved_model",
                        lambda *a,**k:pytest.fail("Model must not resolve"))
    rc,reason=scoped_codex_worker.run_step(ep,"CREATIVE_STORY")
    assert rc==22
    assert "DETERMINISTIC_RESUME_ONLY" in reason
    assert c["save_calls"]==[]


def test_invalid_pass_must_not_enter_paid_worker(tmp_path,monkeypatch):
    ep,c,_=fixture(tmp_path,monkeypatch)
    c["review_valid"]=False
    rc,reason=scoped_codex_worker.run_step(ep,"CREATIVE_STORY")
    assert rc==22
    assert "UNVERIFIED" in reason


def test_dag_recovery_uses_existing_stage_validator_and_no_model(tmp_path,monkeypatch):
    ep,c,_=fixture(tmp_path,monkeypatch,attempt=27)
    calls=[]
    def run(argv):
        calls.append([str(x) for x in argv])
        assert "episode_state.py" in str(argv[1])
        assert str(argv[4])=="STORYBOARD_LOCKED"
        c["stage"]="STORYBOARD_LOCKED"
        return SimpleNamespace(returncode=0,stdout="ok")
    monkeypatch.setattr(runtime_dag,"run",run)
    assert runtime_dag._recover_verified_story_without_model(ep,"IDEA_LOCKED")==(
        0,"VERIFIED_OFFICIAL_STORY_REUSED_NO_AUTHORING_MODEL")
    assert len(c["save_calls"])==1
    assert len(calls)==1
    assert c["stage"]=="STORYBOARD_LOCKED"


def test_dag_recovery_gate_failure_blocks_without_model(tmp_path,monkeypatch):
    ep,c,_=fixture(tmp_path,monkeypatch)
    monkeypatch.setattr(runtime_dag,"run",
                        lambda argv:SimpleNamespace(returncode=2,stdout="real gate FAILED"))
    result=runtime_dag._recover_verified_story_without_model(ep,"IDEA_LOCKED")
    assert result[0]==22 and "STAGE_GATE_BLOCKED" in result[1]
    assert len(c["save_calls"])==1
    assert c["stage"]=="IDEA_LOCKED"


def test_no_story_pass_leaves_initial_authoring_path(tmp_path,monkeypatch):
    ep,c,review=fixture(tmp_path,monkeypatch)
    review["summary"]["passed"]=False
    c["gate"]=False
    assert cc.approved_story_rebind(ep)["status"]=="NO_OFFICIAL_STORY_PASS"
    assert runtime_dag._recover_verified_story_without_model(ep,"IDEA_LOCKED")[0] is None
    assert story_narrative_form.approved_review_dispatch_block(ep) is None
    assert not c["save_calls"]


def test_gate_pass_review_missing_cannot_replay_authoring(tmp_path,monkeypatch):
    ep,c,review=fixture(tmp_path,monkeypatch)
    review["summary"]["passed"]=False
    assert cc.approved_story_rebind(ep)["status"]=="NO_OFFICIAL_STORY_PASS"
    rc,reason=runtime_dag._recover_verified_story_without_model(ep,"IDEA_LOCKED")
    assert rc==22 and "REVIEW_AUTHORITY_MISSING" in reason
    assert story_narrative_form.approved_review_dispatch_block(ep)==(
        "STORY_GATE_PASS_REVIEW_CONFLICT_NO_MODEL_REPLAY")
    assert not c["save_calls"]
