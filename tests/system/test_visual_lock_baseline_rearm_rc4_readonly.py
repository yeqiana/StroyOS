"""Fail-closed proof of only the latest F001 pre-dispatch Visual Lock rc4."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SYSTEM = ROOT / "episodes/_system"
SCRIPTS = ROOT / "scripts"
for folder in (str(SYSTEM), str(SCRIPTS)):
    if folder not in sys.path:
        sys.path.insert(0, folder)

import storyos_visual_lock_baseline_rearm_rc4_readonly as proof
import episode_state_persistence
import generation_attempt_authority
import image_scheduler
import model_policy
import production_native_baseline_proof
import production_native_baseline_predispatch_rearm
import runtime_checkpoint
import runtime_driver


@pytest.fixture
def authority(monkeypatch, tmp_path):
    ep = tmp_path/"episodes"/"00_独立篇"/"episode14"
    log_dir = ep/"meta/runtime/driver-logs"
    log_dir.mkdir(parents=True)
    log = log_dir/"driver_20261023_1442.log"
    task = "storyos-test-validated"
    log.write_text("DRIVER TASK CARRIER pid=12345 task="+task+"\n"
                   "DRIVER EXIT rc=4\n", encoding="utf-8")
    started = "2026-10-23T14:32:22+08:00"
    finished = "2026-10-23T14:42:04+08:00"
    exited = "2026-10-23T14:42:05+08:00"
    record = {"episode":str(ep.resolve()), "pid":0,"rc":"4","log":str(log.resolve()),
              "carrier_task":task,"started_at":started,"exited_at":exited}
    driver = {"driver_state":"EXITED","liveness":"DEAD","exit_code":"4",
              "pid":0, "log":str(log.resolve()), "record":record}
    row = {"step":"VISUAL_LOCK","status":"BLOCKED","returncode":4,
           "finished_at":finished,"note":proof.HOST_NOTE}
    queue = {"items":[
        {"id":"real-f001","frame":1,"scope":"visual_lock","kind":"original",
         "status":"queued","attempts":1,
         production_native_baseline_predispatch_rearm.REARM_FLAG:1,
         "native_baseline_original_error":production_native_baseline_predispatch_rearm.PREFIX,
         "native_baseline_visibility_sha256":"a"*64}
    ] + [
        {"id":f"f{f}","frame":f,"scope":"visual_lock","kind":"original",
         "status":"queued","attempts":0,"depends_on":[1]}
        for f in (45,5,47)
    ]}
    trace = ep/"meta/runtime/trace-events.jsonl"
    trace.write_text(json.dumps({"event_type":"STEP_FAILED","step":"VISUAL_LOCK",
                                "failure_class":"4","timestamp":finished})+"\n",encoding="utf8")
    monkeypatch.setattr(proof,"ROOT",tmp_path)
    monkeypatch.setattr(episode_state_persistence,"load",lambda *_:{"current_state":"STORYBOARD_LOCKED"})
    monkeypatch.setattr(runtime_driver,"status",lambda *_:copy.deepcopy(driver))
    monkeypatch.setattr(runtime_checkpoint,"load",lambda *_:{"step_runs":[copy.deepcopy(row)]})
    monkeypatch.setattr(image_scheduler,"load_queue",lambda *_:copy.deepcopy(queue))
    monkeypatch.setattr(model_policy,"resolve",lambda *_a,**_kw:{})
    monkeypatch.setattr(production_native_baseline_proof,"eligible",lambda *_a,**_kw:True)
    monkeypatch.setattr(production_native_baseline_predispatch_rearm.logical_asset_identity,
                        "frame_asset_key",lambda *_:"asset1")
    monkeypatch.setattr(generation_attempt_authority,"load_attempt",lambda *_:None)
    return {"ep":ep,"driver":driver,"row":row,"queue":queue}


def test_once_only_f001_rearm_licenses_driver_start_but_no_image(authority):
    result = proof.inspect(authority["ep"])
    assert result["status"] == proof.STATUS
    assert result["f001_queue_item_id"] == "real-f001"
    assert result["f001_reattest_proof_sha256"] == "a"*64
    assert result["production_authorization"] is False
    assert result["image_entitlement_verified"] is False
    assert result["image_generation_called"] is False
    assert result["sql_writes"] == 0
    assert result["paid_attempts_reserved"] == 0


@pytest.mark.parametrize("tamper", [
    "latest_driver_alive","exit_wrong","checkpoint_wrong_step","checkpoint_wrong_note",
    "missing_rearm","rearm_twice","missing_session_proof","f001_blocked_again",
    "paid_attempt","queue_drift","unauthorized_baseline","trace_wrong_rc"
])
def test_wrong_authority_denied(authority,monkeypatch,tamper):
    driver=authority["driver"];row=authority["row"];queue=authority["queue"]
    f001=queue["items"][0]
    if tamper=="latest_driver_alive":
        driver["driver_state"]="RUNNING"
    elif tamper=="exit_wrong":
        driver["exit_code"]="900"
    elif tamper=="checkpoint_wrong_step":
        row["step"]="PROMPT_AUTHORING"
    elif tamper=="checkpoint_wrong_note":
        row["note"]="VISUAL_LOCK_SCHEDULER_BASELINE_BLOCKED:rc=429"
    elif tamper=="missing_rearm":
        f001.pop(production_native_baseline_predispatch_rearm.REARM_FLAG)
    elif tamper=="rearm_twice":
        f001[production_native_baseline_predispatch_rearm.REARM_FLAG]=2
    elif tamper=="missing_session_proof":
        f001["native_baseline_visibility_sha256"]=""
    elif tamper=="f001_blocked_again":
        f001["status"]="blocked"
    elif tamper=="paid_attempt":
        monkeypatch.setattr(generation_attempt_authority,"load_attempt",
                            lambda *_:{"status":"UNKNOWN"})
    elif tamper=="queue_drift":
        queue["items"][2]["status"]="blocked"
        monkeypatch.setattr(production_native_baseline_proof,"eligible",lambda *_a,**_kw:False)
    elif tamper=="unauthorized_baseline":
        monkeypatch.setattr(production_native_baseline_proof,"eligible",lambda *_a,**_kw:False)
    elif tamper=="trace_wrong_rc":
        trace=authority["ep"]/"meta/runtime/trace-events.jsonl"
        trace.write_text(json.dumps({"event_type":"STEP_FAILED","step":"VISUAL_LOCK",
                                     "failure_class":"429","timestamp":"2026-10-23T14:42:04+08:00"})+"\n",encoding="utf8")
    assert proof.inspect(authority["ep"])["status"] != proof.STATUS


def test_different_last_driver_record_denied_during_check(authority,monkeypatch):
    calls=[0]
    def drift(_ep):
        calls[0]+=1
        d=copy.deepcopy(authority["driver"])
        if calls[0]>=2:
            d["record"]["carrier_task"]="newer-other-job"
        return d
    monkeypatch.setattr(runtime_driver,"status",drift)
    assert proof.inspect(authority["ep"])["status"] == "DRIVER_OR_QUEUE_CHANGED_DURING_PROOF"


def test_queue_changes_during_check_denied(authority,monkeypatch):
    calls=[0]
    def drift(_ep):
        calls[0]+=1
        q=copy.deepcopy(authority["queue"])
        if calls[0]>=2:
            q["items"][0]["native_baseline_visibility_sha256"]="b"*64
        return q
    monkeypatch.setattr(image_scheduler,"load_queue",drift)
    assert proof.inspect(authority["ep"])["status"] == "DRIVER_OR_QUEUE_CHANGED_DURING_PROOF"
