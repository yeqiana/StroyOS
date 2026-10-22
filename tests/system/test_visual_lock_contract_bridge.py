"""No-pixel PREIMAGE -> Visual Lock SHA rebind regressions."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[2]
SYSTEM=ROOT/"episodes/_system"
if str(SYSTEM) not in sys.path:sys.path.insert(0,str(SYSTEM))
import visual_lock_contract_bridge as bridge
import frame_contract as fc
import episode_state_persistence
import visual_lock_v21
import image_scheduler
import preimage_protocol
import preimage_authority_snapshot as snapshot

OLD="a"*64
NEW="b"*64
REAL_QUEUE_GUARD=bridge._queue_guard
ROLES=("ordinary_baseline","worst_capture_condition",
       "first_major_anomaly","high_impact_admission")


def fixture(tmp_path,monkeypatch):
    ep=tmp_path/"ep"
    meta=ep/"meta"
    meta.mkdir(parents=True)
    (meta/"runtime").mkdir()
    (meta/"runtime/preimage-committed-snapshot.json").write_text(
        json.dumps({"snapshot_kind":"PREIMAGE_COMMITTED_SNAPSHOT",
                    "snapshot_id":"frozen-owned"}),encoding="utf-8")
    items=[{"role":r,"frame":i,"id":f"V{i}",
            "contract_sha256":OLD,"depends_on":[]}
           for i,r in enumerate(ROLES,start=1)]
    (meta/"visual-lock-plan.json").write_text(json.dumps({"items":items}),encoding="utf-8")
    gates={"visual":{"calibration":{"items":[
               {"role":r,"frame":i,"decision":"pending",
                "frame_contract_sha256":OLD,"asset_path":None,"sha256":None}
               for i,r in enumerate(ROLES,start=1)]}},
           "reviews":{"visual_admission":"pending","authenticity":"pending"}}
    (meta/"story-gates.json").write_text(json.dumps(gates),encoding="utf-8")
    oldrows=[{"frame":f"{i:02d}","contract_sha256":OLD} for i in range(1,5)]
    ix=ep/fc.INDEX_REL;ix.parent.mkdir(parents=True)
    ix.write_text(json.dumps({"frames":oldrows,"index_sha256":fc.sha256_json(oldrows)}))
    flags={"compile":0,"owned_stale":False,"equiv":True}
    monkeypatch.setattr(episode_state_persistence,"load",
                        lambda ep:{"current_state":"STORYBOARD_LOCKED"})
    monkeypatch.setattr(preimage_protocol,"barrier_ready",lambda ep:True)
    monkeypatch.setattr(snapshot,"stale_owned",lambda ep,s:flags["owned_stale"])
    monkeypatch.setattr(fc,"frame_count",lambda ep:4)
    monkeypatch.setattr(fc,"compile_frame",
                        lambda ep,n,write_cache=False:{"contract_sha256":NEW,"frame":f"{int(n):02d}"})
    monkeypatch.setattr(fc,"equivalent_to_current",lambda ep,n,sha,current=None:flags["equiv"])
    monkeypatch.setattr(fc,"verify_all",
                        lambda ep:[] if flags["compile"] else ["frame contract index stale"])
    monkeypatch.setattr(bridge,"_queue_guard",lambda ep,plan,shas:{"rows_reused":4,"attempts_reserved":0})
    def compile_all(_):
        flags["compile"]+=1
        rows=[{"frame":f"{i:02d}","contract_sha256":NEW} for i in range(1,5)]
        ix.write_text(json.dumps({"frames":rows,"index_sha256":fc.sha256_json(rows)}))
    monkeypatch.setattr(fc,"compile_all",compile_all)
    monkeypatch.setattr(visual_lock_v21,"choose_plan",lambda ep:{
        "items":[{**row,"contract_sha256":NEW} for row in items]})
    def prepare(_):
        plan=bridge._read(meta/"visual-lock-plan.json")
        plan["items"]=[{**row,"contract_sha256":NEW} for row in plan["items"]]
        (meta/"visual-lock-plan.json").write_text(json.dumps(plan),encoding="utf-8")
        g=bridge._read(meta/"story-gates.json")
        for r in g["visual"]["calibration"]["items"]:r["frame_contract_sha256"]=NEW
        (meta/"story-gates.json").write_text(json.dumps(g),encoding="utf-8")
    monkeypatch.setattr(visual_lock_v21,"prepare",prepare)
    return ep,flags


def test_derived_rebind_only_and_idempotent_after_pixels(tmp_path,monkeypatch):
    ep,state=fixture(tmp_path,monkeypatch)
    out=bridge.reconcile(ep)
    assert out["status"]=="REBOUND_DERIVED_ONLY",out
    assert out["frames_rebound"]==[1,2,3,4]
    assert out["rows_reused"]==4
    assert out["image_generation_called"] is False
    assert out["authority_edited"] is False
    assert state["compile"]==1
    g=bridge._read(ep/"meta/story-gates.json")
    assert g["reviews"]=={"visual_admission":"pending","authenticity":"pending"}
    assert (ep/"meta/runtime/visual-lock-contract-rebind.json").is_file()
    # Resume after baseline generated/reviewed should never re-enter
    # predispatch-only migration or emit a duplicate generated image.
    g["reviews"]["visual_admission"]="passed"
    (ep/"meta/story-gates.json").write_text(json.dumps(g))
    again=bridge.reconcile(ep)
    assert again["status"]=="ALREADY_CURRENT"
    assert state["compile"]==1


@pytest.mark.parametrize("hazard,code",[
    ("owned","PREIMAGE_OWNED_AUTHORITY_NOT_FROZEN"),
    ("semantic","NOT_A_MONOTONIC_VISUAL_PROJECTION"),
    ("stage","VISUAL_STAGE_NOT_STORYBOARD_LOCKED"),
    ("pixel","VISUAL_PIXELS_OR_REVIEW_ALREADY_STARTED"),
    ("corrupt_index","OLD_FRAME_INDEX_NOT_CANONICAL"),
])
def test_fail_closed_before_derived_writes(tmp_path,monkeypatch,hazard,code):
    ep,state=fixture(tmp_path,monkeypatch)
    if hazard=="owned":state["owned_stale"]=True
    if hazard=="semantic":state["equiv"]=False
    if hazard=="stage":
        monkeypatch.setattr(episode_state_persistence,"load",
                            lambda _:{"current_state":"PRODUCTION_PASSED"})
    if hazard=="pixel":
        g=bridge._read(ep/"meta/story-gates.json")
        g["visual"]["calibration"]["items"][0]["decision"]="passed"
        (ep/"meta/story-gates.json").write_text(json.dumps(g))
    if hazard=="corrupt_index":
        ix=ep/fc.INDEX_REL
        data=bridge._read(ix)
        data["index_sha256"]="0"*64
        ix.write_text(json.dumps(data))
    with pytest.raises(bridge.RebindBlocked,match=code):
        bridge.reconcile(ep)
    assert state["compile"]==0


def test_queue_guard_retains_blocked_predispatch_without_rearm(tmp_path,monkeypatch):
    ep,_=fixture(tmp_path,monkeypatch)
    import scheduler_core,generation_attempt_authority as attempts,prompt_package
    # The shared fixture stubs _queue_guard to avoid DB reads; this specific
    # unit test exercises the real implementation.
    monkeypatch.setattr(bridge,"_queue_guard",REAL_QUEUE_GUARD)
    q=[]
    for n in range(1,5):
        row={"frame":n,"scope":"visual_lock","kind":"original",
             "status":"blocked" if n==1 else "queued",
             "technical_failure_code":"LOGIN_AUTH_IMAGE_TOOL_CAPABILITY_UNKNOWN" if n==1 else None,
             "execution":{"phase":"BLOCKED"} if n==1 else {},
             "frame_contract":{"contract_sha256":NEW},
             "prompt_package":{"frame_contract_sha256":NEW,"package_sha256":"p"*64},
             "prompt_file":f"scene/{n:02d}.txt"}
        q.append(row)
    monkeypatch.setattr(scheduler_core,"load_queue",lambda _:{"items":q})
    monkeypatch.setattr(attempts,"load_asset_state",
                        lambda *a:{"attempts_consumed":0,"active_attempt_index":None})
    monkeypatch.setattr(attempts,"frame_key",lambda *a:"key")
    monkeypatch.setattr(prompt_package,"compile_frame",
                        lambda *a,**k:{"package_sha256":"p"*64})
    monkeypatch.setattr(Path,"is_file",lambda self:True)
    plan={"items":[{"frame":i} for i in range(1,5)]}
    assert bridge._queue_guard(ep,plan,{i:NEW for i in range(1,5)})["rows_reused"]==4
    q[0]["prompt_package"]["frame_contract_sha256"]=OLD
    with pytest.raises(bridge.RebindBlocked,match="VISUAL_QUEUE_CONTRACT_STALE"):
        bridge._queue_guard(ep,plan,{i:NEW for i in range(1,5)})
    q[0]["prompt_package"]["frame_contract_sha256"]=NEW
    monkeypatch.setattr(attempts,"load_asset_state",
                        lambda *a:{"attempts_consumed":1,"active_attempt_index":None})
    with pytest.raises(bridge.RebindBlocked,match="IMAGE_ATTEMPT_NOT_PREDISPATCH"):
        bridge._queue_guard(ep,plan,{i:NEW for i in range(1,5)})


def test_blocked_original_is_reused_not_second_queue_request(tmp_path,monkeypatch):
    ep,_=fixture(tmp_path,monkeypatch)
    prom=ep/"prompts/production";prom.mkdir(parents=True)
    for f in range(1,5):(prom/f"{f:02d}.txt").write_text("scene",encoding="utf-8")
    blocked={"frame":1,"scope":"visual_lock","kind":"original",
             "status":"blocked","production_revision_id":None,
             "frame_contract":{"contract_sha256":NEW},
             "prompt_package":{"frame_contract_sha256":NEW},
             "id":"existing-f001"}
    saved=[]
    monkeypatch.setattr(image_scheduler,"init_queue",lambda ep:{"items":[blocked]})
    monkeypatch.setattr(image_scheduler,"load_queue",lambda ep:{"items":[blocked]})
    monkeypatch.setattr(image_scheduler.frame_contract,"compile_frame",
                        lambda *a,**k:{"contract_sha256":NEW})
    monkeypatch.setattr(image_scheduler,"contract_references",lambda *a,**k:[])
    monkeypatch.setattr(image_scheduler,"add_item",
                        lambda *a,**k:saved.append(k) or {"id":f"new-{k['frame']}","prompt_package":{"frame_contract_sha256":NEW}})
    monkeypatch.setattr(image_scheduler.image_model_policy,"for_episode",
                        lambda *a:{"model":"fixture","quality":"high"})
    # Bridge test fixture has all 4 rows, but only F001 is blocked:
    # only remaining 3 new queue requests may be added.
    res=image_scheduler.import_visual_lock(ep,prom)
    assert len(saved)==3
    assert saved[0]["frame"]==2
    assert "existing-f001" in res["added"]

@pytest.mark.parametrize("crash_after",["index","plan"])
def test_partial_commit_retry_repairs_only_missing_derived_binding(tmp_path,monkeypatch,crash_after):
    ep,flags=fixture(tmp_path,monkeypatch)
    index=ep/fc.INDEX_REL
    rows=[{"frame":f"{i:02d}","contract_sha256":NEW} for i in range(1,5)]
    index.write_text(json.dumps({"frames":rows,"index_sha256":fc.sha256_json(rows)}))
    # Simulate the committed derived index after an abrupt Driver stop.
    flags["compile"]=1
    if crash_after=="plan":
        plan_file=ep/"meta/visual-lock-plan.json"
        plan=bridge._read(plan_file)
        for row in plan["items"]:row["contract_sha256"]=NEW
        plan_file.write_text(json.dumps(plan))
    result=bridge.reconcile(ep)
    assert result["status"]=="REBOUND_DERIVED_ONLY"
    assert result["frames_rebound"]==[]
    assert flags["compile"]==1,"never regenerate the already-current index"
    assert all(row["contract_sha256"]==NEW
        for row in bridge._read(ep/"meta/visual-lock-plan.json")["items"])
    assert all(row["frame_contract_sha256"]==NEW
        for row in bridge._read(ep/"meta/story-gates.json")["visual"]["calibration"]["items"])
