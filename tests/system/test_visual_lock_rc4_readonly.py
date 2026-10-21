"""Latest Visual Lock rc4 recovery is immutable, exact and read-only."""
from __future__ import annotations
import json
import sys
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[2]
for directory in (ROOT/"episodes/_system",ROOT/"scripts"):
    if str(directory) not in sys.path:sys.path.insert(0,str(directory))
import storyos_visual_lock_rc4_readonly as proof
import episode_state_persistence
import runtime_driver
import runtime_checkpoint
import storyos_driver_exit_remediation as exits


def case(tmp_path,monkeypatch):
    ep=tmp_path/"episodes"/"00"/"visual_rc4"
    ep.mkdir(parents=True)
    monkeypatch.setattr(proof,"ROOT",tmp_path)
    logdir=ep/"meta/runtime/driver-logs"
    logdir.mkdir(parents=True)
    logfile=logdir/"driver_20261021_234255.log"
    logfile.write_bytes(
        b"DRIVER TASK CARRIER pid=2346 task=StoryOSDriver-abc123\n"
        b"DRIVER EXIT rc=4 \n")
    record={
        "pid":0,"rc":"4 2026-10-21T23:56:07+08:00",
        "episode":str(ep.resolve()),"carrier_task":"StoryOSDriver-abc123",
        "log":str(logfile.resolve()),"started_at":"2026-10-21T23:42:55+08:00",
        "exited_at":"2026-10-21T23:56:07+08:00"}
    driver={"record":record,"driver_state":"EXITED","exit_code":"4",
            "pid":0,"liveness":"DEAD","log":str(logfile.resolve())}
    monkeypatch.setattr(runtime_driver,"status",lambda _:driver)
    monkeypatch.setattr(episode_state_persistence,"load",
                        lambda _:{"current_state":"STORYBOARD_LOCKED"})
    row={"step":"VISUAL_LOCK","status":"BLOCKED","returncode":4,
         "finished_at":"2026-10-21T23:56:05+08:00",
         "note":"log=visual_lock.jsonl\nPOSTCONDITION FAIL\n"
                "visual_admission_frames:\ncontinuity_anchor_missing\n"
                "visual_lock_v21_gate: meta/visual-profile-review.json missing"}
    cp={"step_runs":[row]}
    monkeypatch.setattr(runtime_checkpoint,"load",lambda *_:cp)
    trace=ep/"meta/runtime/trace-events.jsonl"
    trace.write_text(json.dumps({"event_type":"STEP_FAILED","step":"VISUAL_LOCK",
        "failure_class":"4","timestamp":"2026-10-21T23:56:05+08:00"})+"\n")
    gates={"visual":{"calibration":{"items":[]}},
           "reviews":{"visual_admission":"pending","authenticity":"pending"}}
    (ep/"meta/story-gates.json").write_text(json.dumps(gates))
    monkeypatch.setattr(exits,"canonical_sha",lambda _:"a"*64)
    return ep,driver,cp,trace,gates


def test_exact_postcondition_rc4_recovered_readonly(tmp_path,monkeypatch):
    ep,_,_,_,_=case(tmp_path,monkeypatch)
    r=proof.inspect(ep)
    assert r["status"]==proof.STATUS,r
    assert r["driver_record_sha256"]=="a"*64
    assert r["image_generation_called"] is False
    assert r["production_authorization"] is False
    assert r["model_calls"]==r["sql_writes"]==0


@pytest.mark.parametrize("change",[
    "running","other_rc","other_step","outside_time","pixel_review_exists",
    "calibration_exists","fake_pass","trace_other","log_corrupt",
])
def test_not_an_unbounded_image_rc4_retry(tmp_path,monkeypatch,change):
    ep,driver,cp,trace,gates=case(tmp_path,monkeypatch)
    if change=="running":driver["liveness"]="ALIVE"
    if change=="other_rc":driver["exit_code"]="3"
    if change=="other_step":cp["step_runs"][0]["step"]="PRODUCTION"
    if change=="outside_time":cp["step_runs"][0]["finished_at"]="2026-10-20T10:00:00+08:00"
    if change=="pixel_review_exists":(ep/"meta/visual-profile-review.json").write_text("{}")
    if change=="calibration_exists":(ep/"meta/visual-lock-plan.json").write_text("{}")
    if change=="fake_pass":
        gates["reviews"]["visual_admission"]="passed"
        (ep/"meta/story-gates.json").write_text(json.dumps(gates))
    if change=="trace_other":
        trace.write_text(json.dumps({"event_type":"STEP_FAILED",
                     "step":"PRODUCTION","failure_class":"4",
                     "timestamp":"2026-10-21T23:56:05+08:00"})+"\n")
    if change=="log_corrupt":
        (ep/"meta/runtime/driver-logs/driver_20261021_234255.log").write_text("wrong")
    r=proof.inspect(ep)
    assert r["status"]!=proof.STATUS,r
    assert r["production_authorization"] is False


def test_native_preflight_accepts_only_the_exact_visual_rc4_proof(monkeypatch):
    import storyos_codex_managed as managed
    record={"pid":0,"rc":"4","episode":"some","log":"log"}
    token=exits.canonical_sha(record)
    driver={"driver_state":"EXITED","exit_code":"4","pid":0,
            "liveness":"DEAD","record":record}
    queries=[]
    def fake(_env, script, args, **kwargs):
        queries.append(script)
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
        if script.endswith("storyos_visual_lock_rc4_readonly.py"):
            return 0,{"status":proof.STATUS,"driver_record_sha256":token}
        if script.endswith("storyos_visual_lock_readonly.py"):
            return 0,{"status":"BLOCKED",
                "reason":"OFFICIAL_VISUAL_LOCK_FOUR_FRAME_PLAN_MISSING_OR_DRIFTED",
                "read_only":True,"tool_generation_proven":False}
        return 2,{"status":"UNRELATED_EXIT_PROOF"}
    monkeypatch.setattr(managed,"_probe",fake)
    report=managed.preflight({"STORYOS_MYSQL_HOST":"127.0.0.1",
                              "STORYOS_MYSQL_PORT":"13307"},
                             episode=ROOT/"episodes")
    assert report["status"]=="READY_TO_START",report
    assert report["driver_recovery"]["status"]==proof.STATUS
    assert report["production_admission"]["image_ready"] is False
    assert report["production_authorization"] is False
    assert report["model_calls"]==0
    assert "scripts/storyos_visual_lock_rc4_readonly.py" in queries
