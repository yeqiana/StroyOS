"""F009 reviewed ledger recovery must not erase prior Provider refusals."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/"episodes/_system"))
import production_ep14_reviewed_ledger_rearm as rearm


@pytest.fixture
def fixture(monkeypatch, tmp_path):
    ep = tmp_path/"ep14"
    ep.mkdir()
    approved = {"render_content_sha256": "a"*64, "package_sha256":"a"*64,
                "scene_prompt_sha256":"b"*64,
                "independent_preimage_text_approved":True,
                "postimage_pixel_review_required":True}
    original = {"id":"old09","kind":"original","frame":9,
                "scope":"batch","status":"external_blocked",
                "no_automatic_original_prompt_retry":True,
                "requires_content_revision":True}
    row = {"id":"new09","kind":"repair","scope":"batch","frame":9,
           "status":"blocked","last_error":rearm.EXPECTED_ERROR,
           "ep14_active_package_id":"PP_approved",
           "prompt_package":{"package_sha256":"a"*64}}
    held = [{"id":f"held-{i}","kind":"repair","scope":"batch",
             "frame":i,"status":"pilot_hold"} for i in (29,48)]
    state={
        "q":{"items":[original,row,*held],rearm.active.QUEUE_KEY:{
            "state":"ACTIVE_THREE_REVIEWED_CONTENT_REVISIONS",
            "final_render_bundle_sha256":rearm.active.BUNDLE,
            "pilot_mode":"PILOT_FRAME_09_ONLY_REAL_PROVIDER_PROOF",
            "pilot_frame":9,
            "historical_safety_refusals_preserved":True,
            "postimage_pixel_review_required":True,
        }},
        "ledger":{"frames":{"09":{"status":"TECH_FAILED","content_repairs_used":0,
            "attempts":[
                {"attempt_id":"a1","kind":"original","result":"technical_failure"},
                {"attempt_id":"a2","kind":"original","result":"technical_failure"}]}}},
        "paid_state":{"attempts_consumed":1,"remaining_attempts":1,
                      "active_attempt_index":None},
        "first":{"status":"FAILED_AFTER_DISPATCH",
                 "failure_class":"IMAGE_PROVIDER_SAFETY_REJECTED"},
        "second":None,
        "approved":approved,
        "writes":[],
    }
    monkeypatch.setattr(rearm.scheduler_core, "load_queue",lambda ep:deepcopy(state["q"]))
    monkeypatch.setattr(rearm.scheduler_core, "save_queue",lambda ep,q:(
        state["writes"].append("queue"),state.__setitem__("q",deepcopy(q))))
    @contextmanager
    def transaction(ep):
        yield
    monkeypatch.setattr(rearm.scheduler_core,"queue_transaction",transaction)
    monkeypatch.setattr(rearm.active,"item_id",lambda f:"new09")
    monkeypatch.setattr(rearm.active,"load_for_dispatch",
                        lambda ep,item,for_ledger_rearm=False:(
                            deepcopy(state["approved"]) if for_ledger_rearm
                            else (_ for _ in ()).throw(rearm.active.ActivationDenied("NOT_DISPATCHABLE"))))
    monkeypatch.setattr(rearm.identity,"frame_asset_key",lambda ep,f:"frame09")
    monkeypatch.setattr(rearm.attempts,"load_asset_state",lambda ep,k:deepcopy(state["paid_state"]))
    monkeypatch.setattr(rearm.attempts,"load_attempt",
                        lambda ep,k,n:deepcopy(state["first"] if n==1 else state["second"]))
    monkeypatch.setattr(rearm.ledger,"get_ledger",
                        lambda ep:(ep/"production-ledger.json",deepcopy(state["ledger"])))
    monkeypatch.setattr(rearm.ledger,"frame_obj",
                        lambda d,f:("09",d["frames"]["09"]))
    monkeypatch.setattr(rearm.ledger,"content_repair_limit",lambda d:1)
    monkeypatch.setattr(rearm.ledger,"now_iso",lambda:"2026-11-02T08:00:00Z")
    monkeypatch.setattr(rearm.ledger,"save_json",
                        lambda path,d:(state["writes"].append("ledger"),
                                       state.__setitem__("ledger",deepcopy(d))))
    return ep,state


def submit(ep):
    p=rearm.plan(ep)
    return rearm.rearm(ep,expected_queue_sha256=p["expected_queue_sha256"],
                       expected_ledger_sha256=p["expected_ledger_sha256"])


def test_legitimate_f009_rearm_keeps_all_original_attempts_and_only_one_queue_row(fixture):
    ep,s=fixture
    before_q=deepcopy(s["q"])
    prior=deepcopy(s["ledger"]["frames"]["09"]["attempts"])
    plan=rearm.plan(ep)
    assert plan["paid_attempt2_exists"] is False
    result=submit(ep)
    assert result["status"]==rearm.STATUS
    assert result["paid_attempts_reserved"]==0
    assert s["writes"] == ["ledger","queue"]
    assert s["q"]["items"][0]==before_q["items"][0]
    assert s["q"]["items"][1]["status"]=="queued"
    assert all(x["status"]=="pilot_hold" for x in s["q"]["items"][2:])
    fr=s["ledger"]["frames"]["09"]
    assert fr["attempts"]==prior
    assert fr["status"]=="REPAIR_AUTHORIZED"
    assert fr["content_repairs_used"]==0
    assert fr["repair_authorization"]["render_content_sha256"]=="a"*64
    assert fr["repair_authorization"]["historical_attempt_ids"]==["a1","a2"]


@pytest.mark.parametrize("changed",[
    "queue_sha","ledger_sha","other_repair_unheld","original_unblocked",
    "rejected_attempt2","wrong_paid_count","no_old_safety_rejection",
    "wrong_previous_ledger_status","content_repairs_used",
    "not_a_tech_failure","no_independent_approval","bad_package_sha",
    "wrong_old_reason","forged_item_id",
])
def test_drift_and_second_paid_attempt_are_denied_without_writes(fixture,changed):
    ep,s=fixture
    plan=rearm.plan(ep)
    if changed=="queue_sha":plan["expected_queue_sha256"]="0"*64
    elif changed=="ledger_sha":plan["expected_ledger_sha256"]="0"*64
    elif changed=="other_repair_unheld":s["q"]["items"][2]["status"]="queued"
    elif changed=="original_unblocked":s["q"]["items"][0]["status"]="queued"
    elif changed=="rejected_attempt2":s["second"]={"status":"DISPATCH_COMMITTED"}
    elif changed=="wrong_paid_count":s["paid_state"]["attempts_consumed"]=2
    elif changed=="no_old_safety_rejection":s["first"]["failure_class"]="TIMEOUT"
    elif changed=="wrong_previous_ledger_status":s["ledger"]["frames"]["09"]["status"]="CONTENT_FAILED"
    elif changed=="content_repairs_used":s["ledger"]["frames"]["09"]["content_repairs_used"]=1
    elif changed=="not_a_tech_failure":s["ledger"]["frames"]["09"]["attempts"][-1]["result"]="success"
    elif changed=="no_independent_approval":s["approved"]["independent_preimage_text_approved"]=False
    elif changed=="bad_package_sha":s["approved"]["package_sha256"]="c"*64
    elif changed=="wrong_old_reason":s["q"]["items"][1]["last_error"]="SOME_OTHER_ERROR"
    elif changed=="forged_item_id":s["q"]["items"][1]["id"]="forged"
    with pytest.raises(rearm.RearmDenied):
        rearm.rearm(ep,expected_queue_sha256=plan["expected_queue_sha256"],
                    expected_ledger_sha256=plan["expected_ledger_sha256"])
    assert s["writes"] == []


def test_second_dispatch_rearm_refused_after_successful_rearm(fixture):
    ep,s=fixture
    submit(ep)
    with pytest.raises(rearm.RearmDenied):
        rearm.plan(ep)


def test_partial_ledger_commit_does_not_requeue_without_proof(fixture, monkeypatch):
    ep,s=fixture
    def failing_commit(path,data):
        s["writes"].append("ledger_attempted")
        raise RuntimeError("MYSQL_AUTHORITY_UNAVAILABLE")
    monkeypatch.setattr(rearm.ledger,"save_json",failing_commit)
    with pytest.raises(RuntimeError):
        submit(ep)
    assert s["q"]["items"][1]["status"]=="blocked"
    assert s["writes"]==["ledger_attempted"]
