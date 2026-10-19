"""RC4 is resumable only if fixed native routing proves one authorized frozen repair."""
import hashlib
import json
import sys
from pathlib import Path
from unittest import mock
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
import storyos_driver_exit_remediation as remedy
import storyos_codex_managed as managed


def _case(tmp_path,monkeypatch):
    ep=tmp_path/"episodes/test"
    log_dir=ep/"meta/runtime/driver-logs"
    log_dir.mkdir(parents=True)
    log=log_dir/"driver_20261019_135445.log"
    log.write_text("DRIVER TASK CARRIER pid=26664\nDRIVER EXIT rc=4 \n",encoding="utf-8")
    source=tmp_path/"episodes/_system/next_action.py"
    source.parent.mkdir(parents=True)
    source.write_text('def _frozen_authorized_repair_frames(ep, ledger):\n'
                      '    action="MATERIALIZE_REPAIR_WAVE"\n',encoding="utf-8")
    second=tmp_path/"episodes/_system/vision_review_executor.py"
    second.write_text('MATERIALIZE_REPAIR_WAVE = True\n',encoding="utf-8")
    driver={"driver_state":"EXITED","pid":0,"liveness":"DEAD","exit_code":"4",
            "log":str(log),"record":{"pid":0,"rc":"4 2026-10-19T14:17:48+08:00",
              "log":str(log),"episode":str(ep),"started_at":"2026-10-19T13:54:45+08:00"}}
    monkeypatch.setattr(remedy,"APPROVED_REVIEWED_REPAIR_BLOB",remedy.git_blob_sha(source.read_bytes()))
    monkeypatch.setattr(remedy,"APPROVED_REVIEWED_VISION_BLOB",remedy.git_blob_sha(second.read_bytes()))
    expected={"driver_sha256":remedy.canonical_sha(driver["record"]),
              "log_sha256":hashlib.sha256(log.read_bytes()).hexdigest(),
              "fix_sha256":hashlib.sha256(source.read_bytes()).hexdigest()}
    state={"blockers":sorted(remedy.HISTORICAL_EXIT_BLOCKERS),
           "episode_stage":{"status":"STAGE_ELIGIBLE"},
           "mysql":{"schema_status":"READY_FOR_FURTHER_ADMISSION"},
           "attempt":{"status":"ATTEMPT_HISTORY_READ_ONLY",
                      "outcome_unknown_assets":[],"active_attempt_assets":[]},
           "codex":{"bridge_ok":True,"mode_ok":True,"model_client_version_ok":True},
           "driver_evidence":{k:driver[k] for k in ("driver_state","pid","liveness","exit_code")}}
    action={"action":"MATERIALIZE_REPAIR_WAVE","executor":"CODEX_VISION","attempt":1,
            "auto_recoverable":True,"hard_stop":False,"frames":[2,4]}
    return ep,source,driver,expected,state,action


def test_genuine_four_exit_requires_fixed_code_and_distinct_one_shot_ticket(monkeypatch,tmp_path):
    ep,src,driver,expected,state,action=_case(tmp_path,monkeypatch)
    proof=remedy.verify_exit(ep,driver,source=src,expected=expected,
                             kind="reviewed_repair_handoff")
    assert proof["exit_code"]=="4"
    assert proof["remediation_kind"]=="reviewed_repair_handoff"
    assert remedy.reserve_once(ep,proof).is_file()
    with pytest.raises(remedy.RemediationDenied,match="ALREADY_REMEDIATION_RESERVED"):
        remedy.reserve_once(ep,proof)


def test_old_900_repair_kinds_do_not_override_quality_gate_rc4(monkeypatch,tmp_path):
    ep,src,driver,expected,state,action=_case(tmp_path,monkeypatch)
    for kind in ("source_binding","repair_wave_signature"):
        with pytest.raises(remedy.RemediationDenied):
            remedy.verify_exit(ep,driver,source=src,expected=expected,kind=kind)


@pytest.mark.parametrize("invalid",["wrong_log","wrong_source","wrong_exit","live_pid"])
def test_four_exit_does_not_admit_wrong_evidence(monkeypatch,tmp_path,invalid):
    ep,src,driver,expected,state,action=_case(tmp_path,monkeypatch)
    if invalid=="wrong_log":
        Path(driver["log"]).write_text("DRIVER EXIT rc=4 but unknown cause",encoding="utf-8")
        expected["log_sha256"]=hashlib.sha256(Path(driver["log"]).read_bytes()).hexdigest()
    if invalid=="wrong_source":
        src.write_text("generic rc4 override",encoding="utf-8")
        expected["fix_sha256"]=hashlib.sha256(src.read_bytes()).hexdigest()
    if invalid=="wrong_exit":
        driver["exit_code"]="900"
    if invalid=="live_pid":
        driver["pid"]=1234
    with pytest.raises(remedy.RemediationDenied):
        remedy.verify_exit(ep,driver,source=src,expected=expected,
                           kind="reviewed_repair_handoff")


def test_managed_qualifies_only_current_formal_repair_action(monkeypatch,tmp_path):
    ep,src,driver,expected,state,action=_case(tmp_path,monkeypatch)
    monkeypatch.setattr(managed,"ROOT",tmp_path)
    def probe(_env,path,_args):
        if path=="episodes/_system/next_action.py":
            return 0,action
        return 0,driver
    monkeypatch.setattr(managed,"_probe",probe)
    with mock.patch.object(managed.subprocess,"call",return_value=0) as launched:
        assert managed.dispatch_remediated_start(
            {},ep,state,expected,kind="reviewed_repair_handoff")==0
        assert launched.call_count==1
        with pytest.raises(remedy.RemediationDenied):
            managed.dispatch_remediated_start(
                {},ep,state,expected,kind="reviewed_repair_handoff")
        assert launched.call_count==1


@pytest.mark.parametrize("bad",[
    {"action":"USER_DECISION_REQUIRED"},
    {"executor":"WORK"},
    {"hard_stop":True},
    {"auto_recoverable":False},
    {"frames":[]},
])
def test_managed_rc4_denies_nonrepairable_next_action(monkeypatch,tmp_path,bad):
    ep,src,driver,expected,state,action=_case(tmp_path,monkeypatch)
    action.update(bad)
    monkeypatch.setattr(managed,"ROOT",tmp_path)
    monkeypatch.setattr(managed,"_probe",lambda _env,path,_args:(0,action if
        path=="episodes/_system/next_action.py" else driver))
    with mock.patch.object(managed.subprocess,"call") as launched:
        with pytest.raises(remedy.RemediationDenied):
            managed.dispatch_remediated_start(
                {},ep,state,expected,kind="reviewed_repair_handoff")
        assert not launched.called
    assert not list((ep/"meta/runtime").glob("driver-remediation-*.json"))
