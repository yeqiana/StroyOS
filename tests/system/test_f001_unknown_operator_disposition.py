"""Strict F001 operator disposition: no fake success, no unapproved paid replay."""
from __future__ import annotations
import base64
import copy
import hashlib
import json
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

SYSTEM=Path(__file__).resolve().parents[2]/"episodes/_system"
sys.path.insert(0,str(SYSTEM))
import f001_unknown_operator_disposition as recovery

GEN="ga1-"+hashlib.sha256(("00_独立篇/14_深渊疗愈所_第一集_净土生命还原"+
     "\x1f"+"00_独立篇/14_深渊疗愈所_第一集_净土生命还原/frame-01").encode()).hexdigest()[:48]+"-a1"


class FakeDb:
    def __init__(self, row, state):
        self.row=row
        self.state=state
        self.updates=0
    @contextmanager
    def transaction(self):
        old=copy.deepcopy(self.row)
        try:
            yield self
        except Exception:
            self.row.clear()
            self.row.update(old)
            raise
    def query_one(self,statement,values):
        if "STATUS,FAILURE_CLASS,CONTEXT" in statement:
            return {k:self.row[k] for k in ("STATUS","FAILURE_CLASS","CONTEXT")}
        return self.row
    def execute(self,statement,params):
        assert "AND STATUS='OUTCOME_UNKNOWN'" in statement
        if self.row["STATUS"]!="OUTCOME_UNKNOWN":
            return 0
        self.updates+=1
        self.row["STATUS"]="FAILED_AFTER_DISPATCH"
        self.row["FAILURE_CLASS"]=params[0]
        self.row["CONTEXT"]=params[1]
        return 1
    def close(self):
        pass


def fixture(tmp_path,monkeypatch):
    import runtime_driver
    monkeypatch.setattr(runtime_driver,"status",lambda _:{"driver_state":"EXITED",
        "exit_code":"24","pid":0,"liveness":"DEAD","record":{}})
    monkeypatch.setattr(recovery.episode_state_persistence,"load_with_source",
                        lambda _:({"current_state":"STORYBOARD_LOCKED"},"mysql"))
    monkeypatch.setattr(recovery,"ROOT",tmp_path)
    ep=tmp_path/recovery.EPISODE_REL
    ep.mkdir(parents=True)
    raw=ep/"media/raw/01-1792765368.png"
    can=ep/"media/candidates/scheduled/01-ead88592f160-a2.png"
    log=ep/"meta/image-workers/01-ead88592f160-a2.jsonl"
    for path in (raw,can,log):path.parent.mkdir(parents=True,exist_ok=True)
    raw.write_bytes(b"\x89PNG\r\n\x1a\n"+b"png-fixture"*11)
    can.write_bytes(raw.read_bytes()+b"candidate")
    log.write_bytes(b'{"type":"thread.started","thread_id":"example"}\n'
                    b'{"type":"turn.completed"}\n')
    monkeypatch.setattr(recovery,"RAW_SHA",recovery.sha(raw))
    monkeypatch.setattr(recovery,"CANDIDATE_SHA",recovery.sha(can))
    receipt=tmp_path/"runtime/codex-user-runner/task-results"/(recovery.REQUEST+".json")
    receipt.parent.mkdir(parents=True)
    receipt.write_text(json.dumps({
        "request_id":recovery.REQUEST,"returncode":0,
        "output_bytes":len(log.read_bytes()),
        "output_sha256":recovery.sha(log),
        "output_base64":base64.b64encode(log.read_bytes()).decode(),
        "evidence":{"task_type":"image","transport_route":"native_codex"},
    }),encoding="utf-8")
    items=[{"id":recovery.ITEM_ID,"frame":1,"status":"external_blocked",
            "scope":"visual_lock","kind":"original",
            "model":"gpt-image-2.5-flare","quality":"high","depends_on":[]},
           *[{"id":str(i),"frame":i,"status":"queued","scope":"visual_lock",
               "depends_on":[1]} for i in (5,45,47)]]
    queue={"items":items}
    attempt={"generation_key":GEN,"attempt_index":1,
             "runner_request_id":recovery.REQUEST,"provider":"codex_subscription",
             "payload_model":"gpt-image-2.5-flare","payload_quality":"high",
             "dispatch_committed_at":"old_dispatch","generation_observed_at":"old_observation",
             "result_ref":None,"status":"OUTCOME_UNKNOWN",
             "failure_class":recovery.EXPECTED_ERROR}
    state={"attempts_consumed":1,"fencing_counter":1,"active_attempt_index":None}
    row={"STATUS":"OUTCOME_UNKNOWN","FAILURE_CLASS":recovery.EXPECTED_ERROR,
         "GENERATION_KEY":GEN,"FENCING_TOKEN":1,
         "RESULT_REF":None,"PROVIDER":"codex_subscription",
         "PAYLOAD_MODEL":"gpt-image-2.5-flare","PAYLOAD_QUALITY":"high",
         "DISPATCH_COMMITTED_AT":"previous_dispatch","GENERATION_OBSERVED_AT":"previous_obs",
         "CONTEXT":json.dumps({"runner_request_id":recovery.REQUEST})}
    db_state={"ATTEMPTS_CONSUMED":1,"FENCING_COUNTER":1,
              "ACTIVE_ATTEMPT_INDEX":None}
    db=FakeDb(row,db_state)
    monkeypatch.setattr(recovery.authority,"load_attempt",lambda *_: {
        **attempt,"status":db.row["STATUS"],"failure_class":db.row["FAILURE_CLASS"]})
    monkeypatch.setattr(recovery.authority,"load_asset_state",lambda *_:state)
    monkeypatch.setattr(recovery.authority,"_row",lambda *_:db.state)
    monkeypatch.setattr(recovery.authority,"_connect",lambda:db)
    monkeypatch.setattr(recovery.authority,"_episode_id",lambda _: "official-episode")
    monkeypatch.setattr(recovery.authority,"stable_generation_key",lambda *_:GEN)
    monkeypatch.setattr(recovery.logical_asset_identity,"frame_asset_key",lambda *_:"frame-key")
    monkeypatch.setattr(recovery.logical_asset_identity,"episode_id",lambda *_:"official-episode")
    monkeypatch.setattr(recovery.production_recovery,"lifecycle_path",lambda *_:ep/"any.json")
    monkeypatch.setattr(recovery.production_recovery,"_read",lambda *_:{
        "item_id":recovery.ITEM_ID,"state":"BLOCKED","runner_request_id":recovery.REQUEST,
        "generation_key":GEN,"error":recovery.EXPECTED_ERROR})
    monkeypatch.setattr(recovery.scheduler_core,"load_queue",lambda *_:queue)
    monkeypatch.setattr(recovery.scheduler_core,"save_queue",lambda *_:None)
    @contextmanager
    def lock(_):
        yield None
    monkeypatch.setattr(recovery.scheduler_core,"queue_transaction",lock)
    return ep,queue,attempt,state,db,receipt,raw,can,log


def test_f001_initial_inspection_only_is_read_only(tmp_path,monkeypatch):
    ep,q,attempt,state,db,receipt,raw,can,log=fixture(tmp_path,monkeypatch)
    proof=recovery.source_report(ep)
    assert proof["status"]=="F001_UNKNOWN_MANUAL_DISPOSITION_ELIGIBLE"
    assert proof["upstream_billing_outcome_verified"] is False
    assert proof["attempts_refunded"]==0
    assert db.updates==0

def test_f001_requires_explicit_cost_risk_ack(tmp_path,monkeypatch):
    ep,q,a,state,db,*_=fixture(tmp_path,monkeypatch)
    assert recovery.commit(ep)["reason"]=="DUPLICATE_BILLING_RISK_ACK_REQUIRED"
    assert db.updates==0 and a["status"]=="OUTCOME_UNKNOWN"
    assert q["items"][0]["status"]=="external_blocked"

def test_f001_exact_disposition_keeps_budget_and_rearms_once(tmp_path,monkeypatch):
    ep,q,a,state,db,receipt,raw,can,log=fixture(tmp_path,monkeypatch)
    original={p:recovery.sha(p) for p in (receipt,raw,can,log)}
    out=recovery.commit(ep,acknowledged=True)
    assert out["status"]=="PASS" and out["provider_calls"]==0
    assert out["attempts_consumed"]==1 and out["remaining_real_attempt_budget"]==1
    assert db.updates==1 and db.row["STATUS"]=="FAILED_AFTER_DISPATCH"
    assert db.row["FAILURE_CLASS"]==recovery.DISPOSITION_CLASS
    ack=json.loads(db.row["CONTEXT"])[recovery.RECOVERY_FIELD]
    assert ack["upstream_generation_outcome_unverified"] is True
    assert ack["upstream_billing_outcome_unverified"] is True
    assert ack["ack"]==recovery.ACK
    assert q["items"][0]["status"]=="queued"
    assert q["items"][0]["generation_attempt_reason"]=="TECHNICAL_RETRY"
    assert all(x["status"]=="queued" for x in q["items"][1:])
    assert state["attempts_consumed"]==1
    assert all(recovery.sha(p)==sha for p,sha in original.items())
    assert recovery.commit(ep,acknowledged=True)["status"]=="PASS"
    assert db.updates==1

@pytest.mark.parametrize("tamper",[
    "candidate","receipt","log","attempt_status","unknown_failure","attempt_budget",
    "active_attempt","queue_id","missing_child","already_rearmed","foreign_episode"
])
def test_f001_disposition_fails_closed_without_db_or_queue_mutation(
        tmp_path,monkeypatch,tamper):
    ep,q,a,state,db,receipt,raw,can,log=fixture(tmp_path,monkeypatch)
    if tamper=="candidate":can.write_bytes(b"changed")
    if tamper=="receipt":receipt.write_text('{"request_id":"wrong"}')
    if tamper=="log":log.write_bytes(b'{"type":"turn.failed"}')
    if tamper=="attempt_status":db.row["STATUS"]="SUCCEEDED"
    if tamper=="unknown_failure":db.row["FAILURE_CLASS"]="NETWORK_ERROR"
    if tamper=="attempt_budget":state["attempts_consumed"]=2
    if tamper=="active_attempt":state["active_attempt_index"]=1
    if tamper=="queue_id":q["items"][0]["id"]="foreign"
    if tamper=="missing_child":q["items"].pop()
    if tamper=="already_rearmed":q["items"][0]["status"]="queued"
    if tamper=="foreign_episode":ep=tmp_path/"foreign";ep.mkdir()
    with pytest.raises(recovery.DispositionDenied):
        recovery.commit(ep,acknowledged=True)
    assert db.updates==0


def test_driver_recovery_rejects_nonrc24(tmp_path,monkeypatch):
    ep,q,a,state,db,*_=fixture(tmp_path,monkeypatch)
    assert recovery.commit(ep,acknowledged=True)["status"]=="PASS"
    with pytest.raises(recovery.DispositionDenied,match="F001_DRIVER_RC24_NOT_PROVEN"):
        recovery.verify_rearmed(ep,record={"driver_state":"EXITED",
            "exit_code":"4","pid":0,"liveness":"DEAD","record":{}})


def test_driver_rc24_exact_ack_is_read_only(tmp_path,monkeypatch):
    ep,q,a,state,db,*_=fixture(tmp_path,monkeypatch)
    assert recovery.commit(ep,acknowledged=True)["status"]=="PASS"
    proof=recovery.verify_rearmed(ep,record={"driver_state":"EXITED",
        "exit_code":"24","pid":0,"liveness":"DEAD","record":{"marker":"a"}})
    assert proof["status"]=="VISUAL_LOCK_RC24_OPERATOR_DISPOSITION_REARM_RECOVERABLE"
    assert proof["production_authorization"] is False
    assert db.updates==1


def test_second_paid_attempt_eligibility_requires_signed_mysql_source(tmp_path,monkeypatch):
    ep,q,a,state,db,*_=fixture(tmp_path,monkeypatch)
    item=q["items"][0]
    assert recovery.operator_second_attempt_source(ep,item) is False
    assert recovery.commit(ep,acknowledged=True)["status"]=="PASS"
    assert recovery.operator_second_attempt_source(ep,item) is True
    assert state["attempts_consumed"]==1
    item["operator_unknown_disposition_v1"]="f"*64
    assert recovery.operator_second_attempt_source(ep,item) is False


def test_second_paid_attempt_eligibility_will_not_spread_to_other_frames(tmp_path,monkeypatch):
    ep,q,a,state,db,*_=fixture(tmp_path,monkeypatch)
    assert recovery.commit(ep,acknowledged=True)["status"]=="PASS"
    other=copy.deepcopy(q["items"][0])
    other["frame"]=5
    assert recovery.operator_second_attempt_source(ep,other) is False


def test_disposition_refuses_live_driver(tmp_path,monkeypatch):
    import runtime_driver
    ep,q,a,state,db,*_=fixture(tmp_path,monkeypatch)
    monkeypatch.setattr(runtime_driver,"status",lambda _:{"driver_state":"RUNNING",
        "exit_code":"","pid":999,"liveness":"ALIVE"})
    with pytest.raises(recovery.DispositionDenied,match="F001_LIVE_OR_DIFFERENT_DRIVER"):
        recovery.commit(ep,acknowledged=True)
    assert db.updates==0 and q["items"][0]["status"]=="external_blocked"


def test_worker_baseline_lease_requires_verified_manual_cost_disposition(tmp_path,monkeypatch):
    import production_native_baseline_proof as proof
    ep,q,a,state,db,*_=fixture(tmp_path,monkeypatch)
    item=q["items"][0]
    lease={"attempt_index":2,"fencing_token":2,"generation_key":"next","lease_token":"secret"}
    assert proof.admitted_baseline_lease(ep,item,lease) is False
    assert recovery.commit(ep,acknowledged=True)["status"]=="PASS"
    assert proof.verified_second_baseline_retry(ep,item) is True
    assert proof.admitted_baseline_lease(ep,item,lease) is True
    assert proof.admitted_baseline_lease(ep,item,{**lease,"attempt_index":3}) is False
    item["quality"]="low"
    assert proof.admitted_baseline_lease(ep,item,lease) is False


def test_disposition_refuses_non_mysql_stage(tmp_path,monkeypatch):
    ep,q,a,state,db,*_=fixture(tmp_path,monkeypatch)
    monkeypatch.setattr(recovery.episode_state_persistence,"load_with_source",
                        lambda _:({"current_state":"STORYBOARD_LOCKED"},"json"))
    with pytest.raises(recovery.DispositionDenied,match="F001_MYSQL_STAGE"):
        recovery.commit(ep,acknowledged=True)
    assert db.updates==0
