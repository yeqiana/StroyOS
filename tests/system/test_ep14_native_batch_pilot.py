"""Bounded Episode14 F002 native pilot regression."""
import sys
from pathlib import Path
from contextlib import nullcontext
import pytest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"episodes/_system"))
import production_ep14_native_batch_pilot as pilot

@pytest.fixture
def fixture(tmp_path,monkeypatch):
    ep=tmp_path/"episodes"/"00_独立篇"/pilot.EP.name
    ep.mkdir(parents=True)
    monkeypatch.setattr(pilot,"EP",ep)
    monkeypatch.setattr(pilot,"ROOT",tmp_path)
    q={"items":[{"id":f"id{f}","frame":f,"scope":"batch","kind":"original",
                 "status":"blocked","technical_failure_code":pilot.FAIL,
                 "last_error":pilot.FAIL+": predispatch",
                 "model":"gpt-image-2.5-flare","quality":"high"} for f in sorted(pilot.BATCH)]}
    q["items"]+= [{"id":f"v{f}","frame":f,"scope":"visual_lock","status":"generated"} for f in (1,5,45,47)]
    q["items"]+= [{"id":f"r{f}","frame":f,"scope":"repair",
                    "status":"superseded" if f==1 else "generated"} for f in (1,5,45,47)]
    q["items"]+= [{"id":f"x{f}","frame":f,"scope":"repair",
                    "kind":"baseline_candidate","status":"superseded"} for f in (5,45,47)]
    monkeypatch.setattr(pilot.runtime_request,"effective_for_episode",
                        lambda *_:{"mode":"full_auto","runtime":{"execution_mode":"dag"}})
    monkeypatch.setattr(pilot.stage,"load_with_source",lambda *_:({},"mysql"))
    monkeypatch.setattr(pilot.stage,"load",
                        lambda *_:{"current_state":"VISUAL_CALIBRATED"})
    monkeypatch.setattr(pilot.storage_config,"mysql_connection_kwargs",
                        lambda:{"host":"127.0.0.1","port":13307})
    monkeypatch.setattr(pilot.runtime_router,"image_execution_runtime",
                        lambda:("CODEX",None))
    monkeypatch.setattr(pilot.transport,"selected_route",
                        lambda *_:{"provider":"codex_subscription"})
    monkeypatch.setattr(pilot.story_json,"read_json",
                        lambda *_:{"reviews":{"visual_admission":"passed","story":"passed"}})
    monkeypatch.setattr(pilot.identity,"frame_asset_key",lambda _ep,f:str(f))
    states={str(f):{"attempts_consumed":0,"active_attempt_index":None}
            for f in pilot.BATCH}
    monkeypatch.setattr(pilot.attempts,"load_asset_state",
                        lambda _ep,key:states[key])
    monkeypatch.setattr(pilot.attempts,"load_attempt",lambda *_:None)
    monkeypatch.setattr(pilot.model_policy,"resolve",
                        lambda role,episode=None:
                        {"model":"gpt-image-2.5-flare","quality":"high"}
                        if role=="image.payload" else
                        {"model":"gpt-6-luna","reasoning_effort":"high"})
    monkeypatch.setattr(pilot.scheduler_core,"load_queue",lambda *_:q)
    monkeypatch.setattr(pilot.scheduler_core,"queue_transaction",
                        lambda *_:nullcontext())
    writes=[]
    monkeypatch.setattr(pilot.scheduler_core,"save_queue",
                        lambda *_:writes.append("saved"))
    return ep,q,states,writes

def policies():
    return ({"model":"gpt-image-2.5-flare","quality":"high"},
            {"model":"gpt-6-luna","reasoning_effort":"high"})

def test_44_precise_source(fixture):
    ep,q,_,_=fixture
    a,b=policies()
    row=pilot.checked(ep,q,a,b)
    assert row and row["frame"]==2
    assert pilot.eligible(ep,row,a,b,queue=q,blocked=True)
    assert not pilot.eligible(ep,{"frame":3},a,b,queue=q,blocked=True)

@pytest.mark.parametrize("drift",["paid","active","unknown","output","failure","missing"])
def test_any_untrusted_source_drifts_fail_closed(fixture,drift):
    ep,q,states,_=fixture
    a,b=policies()
    first=q["items"][0]
    if drift=="paid":states["3"]["attempts_consumed"]=1
    if drift=="active":states["2"]["active_attempt_index"]=1
    if drift=="unknown":states["2"]["outcome_unknown_count"]=1
    if drift=="output":first["output_path"]="fabricated.png"
    if drift=="failure":first["technical_failure_code"]="OTHER"
    if drift=="missing":q["items"].pop()
    assert pilot.checked(ep,q,a,b) is None

def test_only_pilot_rearmed_zero_paid_attempts(fixture,monkeypatch):
    ep,q,_,writes=fixture
    monkeypatch.setattr(pilot.transport,"payload_capability_preflight",
                        lambda **kwargs:{"status":"BLOCKED"})
    monkeypatch.setattr(pilot.native,"attest_secondary",lambda *_:{"visible":True})
    monkeypatch.setattr(pilot.native,"evidence_sha",lambda *_:"a"*64)
    r=pilot.rearm_one(ep,acknowledged=True)
    assert r["status"]=="PASS" and r["new_paid_attempts"]==0
    assert len(writes)==1
    assert [x["frame"] for x in q["items"] if x.get("status")=="queued"]==[2]
    assert sum(x.get("scope")=="batch" and x.get("status")=="blocked" for x in q["items"])==43
    a,b=policies()
    assert pilot.eligible(ep,next(x for x in q["items"] if x["frame"]==2),a,b,queue=q)
    assert pilot.rearm_one(ep,acknowledged=True)["status"]=="BLOCKED"

def test_no_session_visibility_no_write(fixture,monkeypatch):
    ep,q,_,writes=fixture
    monkeypatch.setattr(pilot.transport,"payload_capability_preflight",
                        lambda **kwargs:{"status":"BLOCKED"})
    monkeypatch.setattr(pilot.native,"attest_secondary",lambda *_:None)
    assert pilot.rearm_one(ep,acknowledged=True)["status"]=="BLOCKED"
    assert not writes
