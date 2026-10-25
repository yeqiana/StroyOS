"""Exact Episode14 2/2 weak-pass routing, blocked candidate retirement, rc22 safety."""
from __future__ import annotations
import copy
import json
import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"episodes/_system"))
import visual_lock_candidate_pool as pool
import production_ep14_exhausted_weakpass_reentry as reentry


@pytest.fixture
def retirement_fixture(tmp_path,monkeypatch):
    folder=tmp_path/"episodes"/"00_独立篇"/"14_深渊疗愈所_第一集_净土生命还原"
    folder.mkdir(parents=True)
    monkeypatch.setattr(pool,"__file__",str(tmp_path/"episodes"/"_system"/"visual_lock_candidate_pool.py"))
    registry={"items":{str(n):{
        "frame":n,"status":"WEAK_PASS",
        "weak_pass":{"approved_by_policy":"episode14_paid_2of2_soft_visual_quality",
                     "prior_independent_fail":{"status":"FAIL"}}
    } for n in (1,5,45,47)}}
    monkeypatch.setattr(pool.visual_lock_admission_state,"load",lambda *_:registry)
    queue={"items":[
        {"id":id,"frame":n,"kind":"baseline_candidate","scope":"repair",
         "status":"blocked","output_path":None,
         "technical_failure_code":"LOGIN_AUTH_IMAGE_TOOL_CAPABILITY_UNKNOWN",
         "last_error":"LOGIN_AUTH_IMAGE_TOOL_CAPABILITY_UNKNOWN: original failed predispatch"}
        for n,id in ((5,"771048aed8ca"),(45,"42ca8cbc3884"),(47,"ae074a3d3c27"))
    ]}
    written=[]
    monkeypatch.setattr(pool.scheduler_core,"queue_transaction",lambda *_:nullcontext())
    monkeypatch.setattr(pool.scheduler_core,"load_queue",lambda *_:queue)
    monkeypatch.setattr(pool.scheduler_core,"save_queue",
                        lambda ep,q:written.append(copy.deepcopy(q)))
    return folder,queue,written,registry


def test_candidate_retirement_supersedes_exact_three_without_deleting_audit(retirement_fixture):
    ep,q,written,_=retirement_fixture
    result=pool._retire_ep14_exhausted_candidate_blocks(ep,{"all_passed":True})
    assert result["status"]=="PASS" and result["new_model_calls"]==0
    assert len(written)==1
    assert all(r["status"]=="superseded"
               and r["last_error"].startswith("LOGIN_AUTH")
               and r["technical_failure_code"]=="LOGIN_AUTH_IMAGE_TOOL_CAPABILITY_UNKNOWN"
               and r["superseded_reason"]=="ep14_2of2_soft_vision_weak_pass"
               for r in q["items"])


@pytest.mark.parametrize("field,value",[
    ("id","different-candidate"),
    ("status","running"),
    ("technical_failure_code","GENERATION_UNKNOWN"),
    ("output_path","media/unauthorized.png"),
])
def test_retirement_fails_closed_if_historical_candidate_drift(retirement_fixture,field,value):
    ep,q,written,_=retirement_fixture
    q["items"][0][field]=value
    report=pool._retire_ep14_exhausted_candidate_blocks(ep,{"all_passed":True})
    assert report["status"]=="BLOCKED"
    assert not written
    assert all(x["status"]!="superseded" for x in q["items"])


def test_cannot_supersede_when_any_hard_or_original_review_not_accepted(retirement_fixture):
    ep,q,written,registry=retirement_fixture
    assert pool._retire_ep14_exhausted_candidate_blocks(ep,{"all_passed":False})["status"]=="NOT_READY"
    registry["items"]["47"]["weak_pass"]["prior_independent_fail"]["status"]="PASS"
    assert pool._retire_ep14_exhausted_candidate_blocks(ep,{"all_passed":True})["status"]=="BLOCKED"
    assert not written


def test_unrelated_episode_never_eligible_for_current_safety_override(tmp_path):
    assert pool._retire_ep14_exhausted_candidate_blocks(tmp_path,{"all_passed":True})["status"]=="NOT_APPLICABLE"
    with pytest.raises(reentry.SourceUnverified,match="WRONG_EPISODE"):
        reentry.inspect(tmp_path)


def test_explicit_rc22_driver_gate_requires_dead_real_owner(monkeypatch):
    monkeypatch.setattr(reentry.runtime_driver,"status",lambda *_:{
        "driver_state":"RUNNING","liveness":"ALIVE","pid":123,"exit_code":None})
    with pytest.raises(reentry.SourceUnverified,match="DRIVER_RC22_NOT_DEAD"):
        reentry.inspect(reentry.EPISODE)


def test_direct_rc22_cli_imports_stdlib_and_project_platform():
    result=subprocess.run(
        [sys.executable,str(ROOT/"episodes/_system"/"production_ep14_exhausted_weakpass_reentry.py"),
         "--episode",str(ROOT/"episodes"/"unrelated"),"--verify-rearmed"],
        cwd=ROOT,capture_output=True,text=True,timeout=25)
    assert result.returncode==2
    assert "ModuleNotFoundError" not in result.stderr
    assert json.loads(result.stdout)["status"]=="BLOCKED"


def test_next_action_preempts_only_precise_exhausted_visual_queue():
    code=(ROOT/"episodes/_system"/"next_action.py").read_text("utf-8")
    first=code.index('action="APPLY_VISUAL_LOCK_WEAK_PASS"')
    later=code.index('action="IMAGE_ATTEMPT_BLOCKED"')
    assert first<later
    for item in ("771048aed8ca","42ca8cbc3884","ae074a3d3c27"):
        assert item in code
