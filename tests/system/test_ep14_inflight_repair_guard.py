"""Episode14 image repair in-flight Ledger guard, one-time no-charge recovery."""
from __future__ import annotations
import copy
import sys
from contextlib import nullcontext
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"episodes"/"_system"))
import production_ep14_visual_repair as guard
import production_ep14_inflight_repair_rearm as recovery


@pytest.mark.parametrize("status,blocked,accepted",[
    ("TECH_FAILED",False,True),
    ("REPAIRING",False,True),
    ("TECH_FAILED",True,True),
    ("REPAIRING",True,False),
    ("PASSED",False,False),
    ("OUTCOME_UNKNOWN",False,False),
    ("REPAIRING",True,False),
    ("NOT_INVOKED",False,False),
])
def test_exact_in_flight_ledger_transition(status,blocked,accepted):
    assert guard._allowed_target_ledger_status(status,blocked=blocked) is accepted


@pytest.fixture
def source(monkeypatch):
    ep=(guard.ROOT/"episodes"/"00_独立篇"/guard.EPISODE).resolve()
    q={"items":[]}
    for frame,item_id in guard.FRAMES.items():
        q["items"].append({
            "frame":frame,"kind":"repair","scope":"repair","id":item_id,
            "status":"blocked","attempts":2,
            "technical_failure_code":recovery.BLOCK,
            "last_error":recovery.BLOCK+
                 ": independent payload route unavailable; provider=codex_subscription",
            guard.FLAG:1,
            "native_repair_visibility_sha256":
                "86cb921fbbf79e955ff5128eb953049e35341168d4b5cf5c37bc8c23af3717b4",
            "ep14_review_sha256":"d"*64,
        })
    monkeypatch.setattr(recovery.runtime_driver,"status",lambda *_:{
        "driver_state":"EXITED","liveness":"DEAD","pid":0,"exit_code":"22"})
    monkeypatch.setattr(recovery.scheduler_core,"load_queue",lambda *_:q)
    monkeypatch.setattr(recovery.ga,"load_asset_state",lambda *_:{
        "attempts_consumed":1,"remaining_attempts":1,"active_attempt_index":None})
    monkeypatch.setattr(recovery.ga,"load_attempt",lambda *_:None)
    monkeypatch.setattr(recovery.identity,"frame_asset_key",lambda _,f:str(f))
    monkeypatch.setattr(recovery.original,"sha",lambda *_:"d"*64)
    monkeypatch.setattr(recovery.original,"eligible",lambda *_args,**_kwargs:True)
    monkeypatch.setattr(recovery.model_policy,"resolve",lambda *_args,**_kwargs:{})
    return ep,q


def test_exact_technical_nonpaid_retry_is_readonly(source):
    ep,q=source
    prior=copy.deepcopy(q)
    proof=recovery.inspect(ep)
    assert proof["status"]=="EP14_INFLIGHT_LEDGER_REPAIR_ONE_SHOT_ELIGIBLE"
    assert proof["new_paid_attempts"]==0
    assert proof["f001_attempts_consumed"]==2
    assert q==prior


@pytest.mark.parametrize("field,value",[
    ("status","running"),("attempts",3),
    ("technical_failure_code","429"),
    (recovery.MARK,1),
    ("native_repair_visibility_sha256","e"*64),
    ("ep14_review_sha256","c"*64),
])
def test_second_rearm_or_wrong_proof_cannot_reenter(source,field,value):
    ep,q=source
    q["items"][0][field]=value
    assert recovery.inspect(ep)["status"]=="BLOCKED"


def test_paid_second_attempt_disallows_unpaid_rearm(source,monkeypatch):
    ep,q=source
    monkeypatch.setattr(recovery.ga,"load_attempt",lambda *_:{"status":"OUTCOME_UNKNOWN"})
    assert recovery.inspect(ep)["status"]=="BLOCKED"
    monkeypatch.setattr(recovery.ga,"load_attempt",lambda *_:None)
    monkeypatch.setattr(recovery.ga,"load_asset_state",lambda *_:{
        "attempts_consumed":2,"remaining_attempts":0,"active_attempt_index":None})
    assert recovery.inspect(ep)["status"]=="BLOCKED"


def test_no_ack_or_wrong_review_does_not_change_redis(source):
    ep,q=source
    old=copy.deepcopy(q)
    assert recovery.commit(ep,expected_review_sha="d"*64,ack=False)["status"]=="BLOCKED"
    assert q==old


def test_requeue_stores_original_failure_and_never_refunds_paid_attempt(source,monkeypatch):
    ep,q=source
    saved=[]
    monkeypatch.setattr(recovery.scheduler_core,"queue_transaction",lambda *_:nullcontext())
    monkeypatch.setattr(recovery.scheduler_core,"save_queue",
                        lambda ep,queue:saved.append(copy.deepcopy(queue)))
    proof=recovery.commit(ep,expected_review_sha="d"*64,ack=True)
    assert proof["status"]=="PASS" and proof["new_paid_attempts"]==0
    assert len(saved)==1
    assert all(x["status"]=="queued" and x[recovery.MARK]==1
               and x["ep14_inflight_ledger_bug_prior_block"].startswith(recovery.BLOCK)
               and x["attempts"]==2 for x in q["items"])
    assert recovery.inspect(ep)["status"]=="BLOCKED"
