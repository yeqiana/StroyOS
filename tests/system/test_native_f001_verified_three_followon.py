"""Three-frame bounded no-provider rearm of authentic F001 after review PASS."""
from __future__ import annotations
import copy
import sys
from contextlib import nullcontext
from pathlib import Path
import pytest

SYSTEM=Path(__file__).resolve().parents[2]/"episodes"/"_system"
sys.path.insert(0,str(SYSTEM))
import f001_verified_followon_queue_rearm as rearm
import production_native_f001_reviewed_followon as followon

def snapshot():
    rows=[
        {"id":"ead88592f160","frame":1,"kind":"original",
         "scope":"visual_lock","status":"generated"},
        {"id":"c006c22820c9","frame":1,"kind":"repair",
         "scope":"repair","status":"superseded"}]
    for f in (5,45,47):
        rows.append({"id":f"q{f}","frame":f,"kind":"original",
           "scope":"visual_lock","status":"blocked","attempts":1,
           "technical_failure_code":rearm.REASON,
           "last_error":rearm.REASON+": no image-tool registry",
           "depends_on":[1]})
    return {"items":rows}

def setup(monkeypatch,ep):
    q=snapshot()
    monkeypatch.setattr(rearm.baseline_cas,"inspect",
        lambda *_:{"current_status":"PASSED","witness_sha":"b"*64})
    monkeypatch.setattr(rearm.scheduler_core,"load_queue",lambda *_:q)
    monkeypatch.setattr(rearm.model_policy,"resolve",
        lambda _name,**kw:{"model":"gpt-image-2.5-flare","quality":"high"})
    monkeypatch.setattr(rearm.identity,"frame_asset_key",lambda _ep,f:f"k-{f}")
    monkeypatch.setattr(rearm.attempts,"load_asset_state",
        lambda _ep,_key:{"attempts_consumed":0,"active_attempt_index":None})
    monkeypatch.setattr(rearm.attempts,"load_attempt",lambda *_:None)
    monkeypatch.setattr(rearm.followon,"eligible",lambda *args,**kw:True)
    return q

def test_prefight_requires_three_exact_blocked_rows(tmp_path,monkeypatch):
    ep=tmp_path/"episode";ep.mkdir();q=setup(monkeypatch,ep)
    result=rearm.inspect(ep)
    assert result["status"]=="FOLLOWON_THREE_PREDISPATCH_REQUEUE_ELIGIBLE"
    assert result["frames"]==[5,45,47]
    assert result["paid_attempts_reserved"]==0
    assert all(r["status"]=="blocked" for r in q["items"] if r["frame"]!=1)

@pytest.mark.parametrize("drift",["wrong_error","already_rearmed","wrong_count","previous_attempt"])
def test_rearm_denies_unverified_sibling(tmp_path,monkeypatch,drift):
    ep=tmp_path/"episode";ep.mkdir();q=setup(monkeypatch,ep)
    sibling=next(r for r in q["items"] if r["frame"]==5)
    if drift=="wrong_error":sibling["technical_failure_code"]="429"
    if drift=="already_rearmed":sibling["reviewed_baseline_followon_rearm_count"]=1
    if drift=="wrong_count":sibling["attempts"]=2
    if drift=="previous_attempt":
        monkeypatch.setattr(rearm.attempts,"load_attempt",lambda *_:{"status":"OUTCOME_UNKNOWN"})
    with pytest.raises(rearm.FollowonDenied):
        rearm.inspect(ep)

def test_without_ack_no_queue_mutation(tmp_path,monkeypatch):
    ep=tmp_path/"episode";ep.mkdir();q=setup(monkeypatch,ep)
    before=copy.deepcopy(q)
    with pytest.raises(rearm.FollowonDenied,match="ACK_REQUIRED"):
        rearm.commit(ep,proof_sha="b"*64,ack=False)
    assert q==before

def test_one_shot_commit_only_restores_three_queue_rows(tmp_path,monkeypatch):
    ep=tmp_path/"episode";ep.mkdir();q=setup(monkeypatch,ep)
    monkeypatch.setattr(rearm.scheduler_core,"queue_transaction",lambda ep:nullcontext())
    writes=[]
    monkeypatch.setattr(rearm.scheduler_core,"save_queue",lambda *_args:writes.append(copy.deepcopy(q)))
    result=rearm.commit(ep,proof_sha="b"*64,ack=True)
    assert result["status"]=="PASS" and result["paid_attempts_reserved"]==0
    assert len(writes)==1
    assert all(r["status"]=="queued" and r["reviewed_baseline_followon_rearm_count"]==1
               for r in q["items"] if r.get("scope")=="visual_lock" and r["frame"]!=1)
    assert q["items"][0]["status"]=="generated"
    assert q["items"][1]["status"]=="superseded"
    with pytest.raises(rearm.FollowonDenied):
        rearm.inspect(ep)

def test_scoped_native_followon_never_globalizes_unknown(monkeypatch,tmp_path):
    item={"frame":5,"scope":"visual_lock","kind":"original",
          "status":"running","model":"gpt-image-2.5-flare","quality":"high"}
    assert followon.eligible(tmp_path,item,{}, {}) is False
    assert followon.eligible(tmp_path,{**item,"frame":99},{},{}) is False
