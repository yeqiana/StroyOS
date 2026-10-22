"""Negative/positive exact latest PROMPT_AUTHORING rc4 proof."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[2]
for d in [ROOT/"episodes/_system",ROOT/"scripts"]:
    if str(d) not in sys.path:sys.path.insert(0,str(d))
import storyos_prompt_contract_rc4_readonly as proof
import runtime_driver,runtime_checkpoint,episode_state_persistence
import storyos_driver_exit_remediation as exit_authority
import visual_lock_contract_bridge as bridge


def setup(tmp_path,monkeypatch):
    ep=tmp_path/"episodes"/"demo"/"title"
    logdir=ep/"meta/runtime/driver-logs";logdir.mkdir(parents=True)
    trace=ep/"meta/runtime/trace-events.jsonl"
    log=logdir/"driver_20261022_101354.log"
    log.write_bytes(b"DRIVER TASK CARRIER pid=34720 task=StoryOSDriver-xyz\nDRIVER EXIT rc=4 \n")
    record={"episode":str(ep.resolve()),"pid":0,
            "log":str(log.resolve()),"carrier_task":"StoryOSDriver-xyz",
            "rc":"4 2026-10-22T10:18:45+08:00",
            "started_at":"2026-10-22T10:13:54+08:00",
            "exited_at":"2026-10-22T10:18:45+08:00"}
    driver={"record":record,"driver_state":"EXITED","exit_code":"4",
            "liveness":"DEAD","pid":0,"log":str(log.resolve())}
    step={"step":"PROMPT_AUTHORING","status":"BLOCKED","returncode":4,
          "finished_at":"2026-10-22T10:18:43+08:00",
          "note":"LOCKED STORY PROMPT AUTHORING FAIL: frame contracts invalid: frame contract index stale"}
    trace.write_text(json.dumps({"event_type":"STEP_FAILED","step":"PROMPT_AUTHORING",
                    "failure_class":"4","timestamp":"2026-10-22T10:18:43+08:00"})+"\n")
    monkeypatch.setattr(proof,"ROOT",tmp_path)
    monkeypatch.setattr(runtime_driver,"status",lambda _:driver)
    monkeypatch.setattr(runtime_checkpoint,"load",lambda *a:{"step_runs":[step]})
    monkeypatch.setattr(episode_state_persistence,"load",
                        lambda ep:{"current_state":"STORYBOARD_LOCKED"})
    monkeypatch.setattr(exit_authority,"canonical_sha",lambda row:"f"*64)
    probe={"status":"DERIVED_REBIND_READONLY_READY",
           "frames_requiring_projection":list(range(1,49)),
           "visual_frames":[1,45,5,47]}
    monkeypatch.setattr(bridge,"reconcile",lambda _,dry_run=False:probe)
    return ep,driver,step,log,trace,probe


def test_exact_old_index_rc4_proves_only_readonly_recovery(tmp_path,monkeypatch):
    ep,*_=setup(tmp_path,monkeypatch)
    result=proof.inspect(ep)
    assert result["status"]==proof.STATUS,result
    assert result["affected_frames"]==48
    assert result["image_generation_called"] is False
    assert result["production_authorization"] is False
    assert result["model_calls"]==result["sql_writes"]==result["attempts_reserved"]==0


@pytest.mark.parametrize("failure",[
    "driver_live","wrong_rc","bad_note","different_step","unrelated_time",
    "spoofed_log","other_trace","semantic_change",
])
def test_proof_fails_closed_on_any_unrelated_rc4(tmp_path,monkeypatch,failure):
    ep,driver,step,log,trace,probe=setup(tmp_path,monkeypatch)
    if failure=="driver_live":driver["liveness"]="ALIVE"
    if failure=="wrong_rc":driver["exit_code"]="3"
    if failure=="bad_note":step["note"]="Visual critic content failed"
    if failure=="different_step":step["step"]="VISUAL_LOCK"
    if failure=="unrelated_time":step["finished_at"]="2026-10-21T10:18:43+08:00"
    if failure=="spoofed_log":log.write_text("wrong")
    if failure=="other_trace":trace.write_text(json.dumps({"event_type":"STEP_FAILED",
        "step":"CREATIVE_STORY","failure_class":"4",
        "timestamp":"2026-10-22T10:18:43+08:00"})+"\n")
    if failure=="semantic_change":probe["status"]="NOT_A_MONOTONIC_VISUAL_PROJECTION"
    assert proof.inspect(ep)["status"]!=proof.STATUS


def test_bridge_dryrun_does_not_write_or_replay(tmp_path,monkeypatch):
    from test_visual_lock_contract_bridge import fixture
    ep,flags=fixture(tmp_path,monkeypatch)
    out=bridge.reconcile(ep,dry_run=True)
    assert out["status"]=="DERIVED_REBIND_READONLY_READY"
    assert out["sql_writes"]==out["model_calls"]==out["image_attempts_reserved"]==0
    assert flags["compile"]==0
    assert not (ep/"meta/runtime/visual-lock-contract-rebind.json").exists()

def test_native_preflight_accepts_exact_prompt_index_exit_but_not_image_ready(monkeypatch):
    import storyos_codex_managed as managed
    driver_record={"pid":0,"rc":"4","episode":"test"}
    digest=exit_authority.canonical_sha(driver_record)
    driver={"driver_state":"EXITED","exit_code":"4","pid":0,
            "liveness":"DEAD","record":driver_record}
    def fake(_env,script,args,**kwargs):
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
            return 0,{"status":"STAGE_ELIGIBLE","stage":"STORYBOARD_LOCKED","source":"mysql"}
        if script.endswith("storyos_creative_recovery_readonly.py"):
            return 0,{"status":"CONTRACT_ALREADY_LOCKED_VERIFY_STORY_GATES"}
        if script.endswith("storyos_attempt_readonly_preflight.py"):
            return 0,{"status":"ATTEMPT_HISTORY_READ_ONLY",
                     "active_attempt_assets":[],"outcome_unknown_assets":[]}
        if script.endswith("runtime_driver.py"):
            return 0,driver
        if script.endswith("storyos_prompt_contract_rc4_readonly.py"):
            return 0,{"status":proof.STATUS,"driver_record_sha256":digest}
        if script.endswith("storyos_visual_lock_readonly.py"):
            return 0,{"status":"BLOCKED","tool_generation_proven":False,
                "reason":"REAL_NATIVE_IMAGE_PIXEL_PROOF_NOT_YET_ESTABLISHED"}
        return 2,{"status":"NOT_THIS_RECOVERY"}
    monkeypatch.setattr(managed,"_probe",fake)
    result=managed.preflight({"STORYOS_MYSQL_HOST":"127.0.0.1",
                              "STORYOS_MYSQL_PORT":"13307"},episode=ROOT/"episodes")
    assert result["status"]=="READY_TO_START",result
    assert result["driver_recovery"]["status"]==proof.STATUS
    assert result["production_admission"]["image_ready"] is False
    assert result["driver_recovery"]["production_authorization"] is False
