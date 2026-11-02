"""F029 may run despite F009 content FAIL; prior real Provider proof required."""
from __future__ import annotations
from contextlib import contextmanager
from copy import deepcopy
import hashlib
from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/"episodes/_system"))
import production_ep14_followon_release as r


@pytest.fixture
def live(monkeypatch, tmp_path):
    ep=tmp_path/"episodes"/"00_独立篇"/"14_深渊疗愈所_第一集_净土生命还原"
    ep.mkdir(parents=True)
    raw=ep/"media/candidates/scheduled/09-8eefd4854826-a2.png"
    raw.parent.mkdir(parents=True)
    raw.write_bytes(b"actual-pixels-for-model-review")
    sha=hashlib.sha256(raw.read_bytes()).hexdigest()
    monkeypatch.setattr(r, "PREVIOUS_SHA", sha)
    q={"items":[
        {"frame":9,"id":r.PREVIOUS_ITEM_ID,"kind":"repair","scope":"batch",
         "status":"scout_repair","batch_id":r.PIXEL_BATCH,
         "vision_batch_review":{"decision":"REPAIR_NOW"},
         "normalization_recovery":{"pixel_review_completed":False}},
        {"frame":29,"id":r.NEXT_FRAME_ID,"kind":"repair","scope":"batch",
         "status":"pilot_hold","ep14_active_package_id":"PP_29",
         "prompt_package":{"package_sha256":"c"*64}},
        {"frame":48,"id":"held48","kind":"repair","scope":"batch",
         "status":"pilot_hold"},
        {"frame":29,"id":"original29","kind":"original","scope":"batch",
         "status":"external_blocked","requires_content_revision":True,
         "no_automatic_original_prompt_retry":True},
    ],r.active.QUEUE_KEY:{
        "pilot_mode":"PILOT_FRAME_09_ONLY_REAL_PROVIDER_PROOF",
        "pilot_frame":9,"state":"ACTIVE_THREE_REVIEWED_CONTENT_REVISIONS",
        "final_render_bundle_sha256":r.active.BUNDLE,
        "production_dispatch_authorized":True,
        "historical_safety_refusals_preserved":True,
        "postimage_pixel_review_required":True,
    }}
    review={"batch_id":r.PIXEL_BATCH,"review_scope":"EARLY_BATCH_ACTUAL_PIXELS",
        "final_pass_authority":False,
        "critic_provenance":{"runtime":"CODEX_ISOLATED",
                             "session_reused_from_generation":False},
        "frames":[{"frame":"09","candidate_sha256":sha,
                   "decision":"REPAIR_NOW","issue_codes":["ANOMALY_CARRIER_PLACEMENT"]}]}
    doc={"frames":{
        "09":{"status":"NEEDS_USER","content_repairs_used":1,
              "current_candidate":{"sha256":sha}},
        "29":{"status":"TECH_FAILED","content_repairs_used":0,
              "attempts":[{"kind":"original","result":"technical_failure"},
                          {"kind":"original","result":"technical_failure"}]},
    }}
    state={"q":q,"doc":doc,"review":review,"writes":[],"f29_second":None,
           "f9_status":"SUCCEEDED"}
    monkeypatch.setattr(r.scheduler_core,"load_queue",lambda ep:deepcopy(state["q"]))
    monkeypatch.setattr(r.scheduler_core,"save_queue",
                        lambda ep,x:(state["writes"].append("queue"),
                                     state.__setitem__("q",deepcopy(x))))
    @contextmanager
    def transaction(ep):
        yield
    monkeypatch.setattr(r.scheduler_core,"queue_transaction",transaction)
    monkeypatch.setattr(r.pixel,"read_json",lambda path:deepcopy(state["review"]))
    monkeypatch.setattr(r.identity,"frame_asset_key",lambda ep,f:f"frame-{f}")
    monkeypatch.setattr(r.ga,"load_asset_state",lambda ep,key:
        {"attempts_consumed":2,"remaining_attempts":0,"active_attempt_index":None}
        if key=="frame-9" else
        {"attempts_consumed":1,"remaining_attempts":1,"active_attempt_index":None})
    monkeypatch.setattr(r.ga,"load_attempt",lambda ep,key,idx:
        {"status":state["f9_status"],"provider":"codex_subscription"}
        if key=="frame-9" and idx==2 else
        {"status":"FAILED_AFTER_DISPATCH","failure_class":"IMAGE_PROVIDER_SAFETY_REJECTED"}
        if key=="frame-29" and idx==1 else state["f29_second"])
    monkeypatch.setattr(r.ledger,"get_ledger",lambda ep:(ep/"ledger.json",deepcopy(state["doc"])))
    monkeypatch.setattr(r.ledger,"frame_obj",lambda doc,f:(str(f).zfill(2),doc["frames"][str(f).zfill(2)]))
    monkeypatch.setattr(r.ledger,"content_repair_limit",lambda doc:1)
    monkeypatch.setattr(r.ledger,"now_iso",lambda:"2026-11-02T12:00:00Z")
    monkeypatch.setattr(r.ledger,"save_json",
                        lambda path,data:(state["writes"].append("ledger"),
                                          state.__setitem__("doc",deepcopy(data))))
    monkeypatch.setattr(r.active,"load_for_dispatch",lambda ep,item,for_followon=False:
                        {"postimage_pixel_review_required":True,
                         "independent_preimage_text_approved":True,
                         "render_content_sha256":"c"*64,
                         "package_sha256":"c"*64,"scene_prompt_sha256":"d"*64}
                        if for_followon else None)
    return ep,state


def test_independent_f029_queues_without_forging_f009_pixel_review(live):
    ep,s=live
    p=r.plan(ep)
    assert p["prior_provider_and_review"]["pixel_review_decision"]=="REPAIR_NOW"
    assert p["prior_provider_and_review"]["final_review_passed"] is False
    previous=deepcopy(s["q"]["items"])
    out=r.release(ep,expected_queue_sha256=p["expected_queue_sha256"],
                  expected_ledger_sha256=p["expected_ledger_sha256"])
    assert out["queued_frame"]==29 and out["held_frames"]==[48]
    assert out["paid_attempts_reserved"]==0
    assert s["writes"]==["ledger","queue"]
    assert s["q"]["items"][0]==previous[0]
    assert s["q"]["items"][2]==previous[2]
    assert s["q"]["items"][3]==previous[3]
    assert s["q"]["items"][1]["status"]=="queued"
    assert s["doc"]["frames"]["09"]["status"]=="NEEDS_USER"
    assert s["doc"]["frames"]["29"]["status"]=="REPAIR_AUTHORIZED"
    assert s["doc"]["frames"]["29"]["attempts"]==previous_attempts()
    assert r.dispatch_authorized(ep,29,s["q"]["items"][1],s["q"][r.active.QUEUE_KEY]) is True
    assert r.dispatch_authorized(ep,48,s["q"]["items"][2],s["q"][r.active.QUEUE_KEY]) is False


def previous_attempts():
    return [{"kind":"original","result":"technical_failure"},
            {"kind":"original","result":"technical_failure"}]


@pytest.mark.parametrize("tamper",[
    "f009_lacks_pixel","f009_has_unverified_pass","f009_model_failed",
    "f009_sha_drift","f009_status_changed","f029_budget_used",
    "f029_held_changed","f048_unheld","original_unblocked",
    "f029_first_not_safety","stale_queue","stale_ledger",
])
def test_no_unaudited_paid_followon_when_gate_drift(live,monkeypatch,tamper):
    ep,s=live
    p=r.plan(ep)
    if tamper=="f009_lacks_pixel":
        s["review"]["frames"][0]["candidate_sha256"]="0"*64
    elif tamper=="f009_has_unverified_pass":
        s["review"]["frames"][0]["decision"]="PASS_PREVIEW"
    elif tamper=="f009_model_failed":
        s["f9_status"]="OUTCOME_UNKNOWN"
    elif tamper=="f009_sha_drift":
        (ep/"media/candidates/scheduled/09-8eefd4854826-a2.png").write_bytes(b"tampered")
    elif tamper=="f009_status_changed":s["doc"]["frames"]["09"]["status"]="APPROVED"
    elif tamper=="f029_budget_used":s["f29_second"]={"status":"DISPATCH_COMMITTED"}
    elif tamper=="f029_held_changed":s["q"]["items"][1]["status"]="queued"
    elif tamper=="f048_unheld":s["q"]["items"][2]["status"]="queued"
    elif tamper=="original_unblocked":s["q"]["items"][3]["status"]="queued"
    elif tamper=="f029_first_not_safety":
        previous=r.ga.load_attempt
        monkeypatch.setattr(r.ga,"load_attempt",lambda ep,key,idx:
            {"status":"FAILED_AFTER_DISPATCH","failure_class":"TIMEOUT"}
            if key=="frame-29" and idx==1 else previous(ep,key,idx))
    elif tamper=="stale_queue":p["expected_queue_sha256"]="0"*64
    elif tamper=="stale_ledger":p["expected_ledger_sha256"]="0"*64
    with pytest.raises(r.FollowonDenied):
        r.release(ep,expected_queue_sha256=p["expected_queue_sha256"],
                  expected_ledger_sha256=p["expected_ledger_sha256"])
    assert s["writes"]==[]


def test_cannot_replay_second_authorization(live):
    ep,s=live
    p=r.plan(ep)
    r.release(ep,expected_queue_sha256=p["expected_queue_sha256"],
              expected_ledger_sha256=p["expected_ledger_sha256"])
    with pytest.raises(r.FollowonDenied):
        r.plan(ep)


def test_ledger_failure_keeps_f029_pilot_hold(live,monkeypatch):
    ep,s=live
    p=r.plan(ep)
    def fail(path,doc):
        raise RuntimeError("MYSQL_DENIED")
    monkeypatch.setattr(r.ledger,"save_json",fail)
    with pytest.raises(RuntimeError):
        r.release(ep,expected_queue_sha256=p["expected_queue_sha256"],
                  expected_ledger_sha256=p["expected_ledger_sha256"])
    assert s["q"]["items"][1]["status"]=="pilot_hold"
