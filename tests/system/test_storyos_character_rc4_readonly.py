"""Strict post-PASS character binding rc4 proof. No paid model or DB writes."""
from __future__ import annotations
from datetime import datetime
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
sys.path.insert(0,str(ROOT/"episodes"/"_system"))
import storyos_character_rc4_readonly as proof
import runtime_driver
import runtime_checkpoint
import episode_state_persistence
import character_contract
import storyos_driver_exit_remediation as exits
import storyos_codex_managed as native


def fixture(tmp_path,monkeypatch):
    ep=tmp_path/"episodes"/"00"/"01"
    ep.mkdir(parents=True)
    d=ep/"meta/runtime/driver-logs"
    d.mkdir(parents=True)
    logfile=d/"driver_20261021_040634.log"
    logfile.write_bytes(
        b"DRIVER TASK CARRIER pid=32336 task=StoryOSDriver-42\n"
        b"DRIVER EXIT rc=4 \n")
    trace=ep/"meta/runtime/trace-events.jsonl"
    trace.write_text(json.dumps({
        "event_type":"STEP_FAILED","step":"CREATIVE_STORY",
        "failure_class":"4","timestamp":"2026-10-21T04:15:18.943+08:00"
    })+"\n",encoding="utf-8")
    record={
        "pid":0,"rc":"4 2026-10-21T04:15:19+08:00",
        "episode":str(ep.resolve()),"log":str(logfile.resolve()),
        "carrier_task":"StoryOSDriver-42",
        "started_at":"2026-10-21T04:06:34+08:00",
        "exited_at":"2026-10-21T04:15:19+08:00",
    }
    driver={
        "record":record,"driver_state":"EXITED","exit_code":"4",
        "pid":0,"liveness":"DEAD","log":str(logfile.resolve())}
    checkpoint={"step_runs":[{
        "step":"CREATIVE_STORY","status":"BLOCKED",
        "returncode":4,
        "finished_at":"2026-10-21T04:15:18+08:00",
        "note":"log=story.jsonl\nCHARACTER CONTRACT FAIL\n"
               "final Story review source SHA drift",
    }]}
    approved={"status":"VERIFIED_REBIND_READY",
        "bind":{"story_sha256":"a"*64,"previous_story_sha256":"b"*64,
                "review_attempt":15}}
    state={"driver":driver,"checkpoint":checkpoint,
           "approval":approved,"stage":"IDEA_LOCKED"}
    monkeypatch.setattr(proof,"ROOT",tmp_path)
    monkeypatch.setattr(runtime_driver,"status",lambda _:state["driver"])
    monkeypatch.setattr(runtime_checkpoint,"load",lambda _,default=None:state["checkpoint"])
    monkeypatch.setattr(episode_state_persistence,"load",
                        lambda _:{"current_state":state["stage"]})
    monkeypatch.setattr(character_contract,"approved_story_rebind",
                        lambda ep,*,write=False:(
                            pytest.fail("readonly rc4 proof may not update a contract")
                            if write else state["approval"]))
    monkeypatch.setattr(exits,"canonical_sha",lambda _: "c"*64)
    return ep,state,logfile,trace


def test_exact_post_a15_rc4_character_sha_only_is_recoverable_readonly(tmp_path,monkeypatch):
    ep,state,_,_=fixture(tmp_path,monkeypatch)
    report=proof.inspect(ep)
    assert report["status"]==proof.STATUS,report
    assert report["driver_record_sha256"]=="c"*64
    assert report["production_authorization"] is False
    assert report["image_entitlement_verified"] is False
    assert report["model_calls"]==report["sql_writes"]==0


@pytest.mark.parametrize("fault",[
    "driver_running","driver_rc_other","driver_identity","gate_pass_unknown",
    "driver_log_edit","trace_other","checkpoint_unrelated","checkpoint_transport",
    "checkpoint_old","stage_changed",
])
def test_proof_fails_closed_on_unrelated_or_unverified_event(
    tmp_path,monkeypatch,fault
):
    ep,state,log,trace=fixture(tmp_path,monkeypatch)
    if fault=="driver_running":state["driver"]["liveness"]="ALIVE"
    if fault=="driver_rc_other":state["driver"]["exit_code"]="3"
    if fault=="driver_identity":state["driver"]["record"]["episode"]=str(tmp_path)
    if fault=="gate_pass_unknown":state["approval"]["status"]="OFFICIAL_PASS_INVALID"
    if fault=="driver_log_edit":log.write_bytes(b"DRIVER CRASH\nDRIVER EXIT rc=4")
    if fault=="trace_other":trace.write_text('{"event_type":"STEP_FAILED","step":"PRODUCTION","failure_class":"4"}')
    if fault=="checkpoint_unrelated":
        state["checkpoint"]["step_runs"][0]["note"]="POSTCONDITION FAIL"
    if fault=="checkpoint_transport":
        state["checkpoint"]["step_runs"][0]["returncode"]=124
    if fault=="checkpoint_old":
        state["checkpoint"]["step_runs"][0]["finished_at"]="2026-10-20T20:21:00+08:00"
    if fault=="stage_changed":state["stage"]="STORYBOARD_LOCKED"
    report=proof.inspect(ep)
    assert report["status"]!=proof.STATUS
    assert report["production_authorization"] is False


def test_no_unbounded_restart_by_forging_a_review_status(monkeypatch):
    # Native entry still requires the independent read-only event proof.
    fake_driver={"driver_state":"EXITED","exit_code":"4","pid":0,
                 "liveness":"DEAD","record":{"pid":0,"rc":"4"}}
    token=exits.canonical_sha(fake_driver["record"])
    requests=[]
    def fake_probe(_env,script,args,**kwargs):
        requests.append(script)
        if script.endswith("runtime_router.py"):
            return 0,{"effective_production_mode":"CODEX_MANAGED",
                "effective_runtime":"CODEX","image_execution_runtime":"CODEX",
                "local_codex_spawn_allowed":True,
                "local_codex_image_spawn_allowed":True,
                "text_review_runtime":"CODEX","vision_review_runtime":"CODEX",
                "governance_review_runtime":"CODEX"}
        if script.endswith("codex_user_runner.py"):
            return 0,{"status":"ok","codex_available":True,"codex_auth_present":True}
        if script.endswith("storyos_native_model_readiness.py"):
            return 0,{"status":"CLIENT_VERSION_COMPATIBLE"}
        if script.endswith("storyos_revision_schema_readonly.py"):
            return 0,{"status":"READY_FOR_FURTHER_ADMISSION"}
        if script.endswith("storyos_episode_stage_readonly.py"):
            return 0,{"status":"STAGE_ELIGIBLE","stage":"IDEA_LOCKED","source":"mysql"}
        if script.endswith("storyos_creative_recovery_readonly.py"):
            return 0,{"status":"CONTRACT_ALREADY_LOCKED_VERIFY_STORY_GATES"}
        if script.endswith("storyos_attempt_readonly_preflight.py"):
            return 0,{"status":"ATTEMPT_HISTORY_READ_ONLY",
                      "outcome_unknown_assets":[],"active_attempt_assets":[]}
        if script.endswith("runtime_driver.py"):return 0,fake_driver
        if script.endswith("storyos_post_review_rc4_readonly.py"):
            return 2,{"status":"OFFICIAL_A15_PASS_NOT_NEWER_THAN_OLD_EXIT"}
        if script.endswith("storyos_character_rc4_readonly.py"):
            return 0,{"status":proof.STATUS,"story_gate_verified":True,
                      "driver_record_sha256":token}
        raise AssertionError(script)
    monkeypatch.setattr(native,"_probe",fake_probe)
    report=native.preflight({"STORYOS_MYSQL_HOST":"127.0.0.1",
                             "STORYOS_MYSQL_PORT":"13307"},
                            episode=ROOT/"episodes")
    assert report["status"]=="READY_TO_START"
    assert report["driver_recovery"]["status"]==proof.STATUS
    assert report["production_admission"]["image_ready"] is False
    assert not report["production_authorization"]
    assert "scripts/storyos_character_rc4_readonly.py" in requests
