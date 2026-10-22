"""Visual Lock Host 1+3 barrier and 48-frame plan regression (offline only)."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT=Path(__file__).resolve().parents[2]
SYSTEM=ROOT/"episodes"/"_system"
SCRIPTS=ROOT/"scripts"
for x in (SYSTEM,SCRIPTS):
    if str(x) not in sys.path:sys.path.insert(0,str(x))
import visual_lock_host_lane as lane
import visual_lock_v21
import image_scheduler
import vision_review_executor
import machine_action_executor
import episode_state_persistence
import visual_lock_baseline_gate
import storyos_visual_lock_readonly as triage


def prepared(tmp_path,monkeypatch):
    # This unit fixture tests image/pixel ordering, not PREIMAGE SHA migration.
    import visual_lock_contract_bridge
    monkeypatch.setattr(visual_lock_contract_bridge,"reconcile",
                        lambda ep: {"status":"ALREADY_CURRENT"})
    ep=tmp_path/"episode"
    (ep/"meta").mkdir(parents=True)
    (ep/"prompts/production").mkdir(parents=True)
    (ep/"meta/world-state.json").write_text(json.dumps({
        "status":"LOCKED","initial_state":{
            "location":"mountain_road","time":"night",
            "weather":"cold rain","recorder":{"active_device":"Sony A7S3"},
            "props":{}
        }}),encoding="utf-8")
    (ep/"meta/temporal-continuity.json").write_text(json.dumps({
        "status":"LOCKED","frames":[{"frame":"01","daypart":"night",
                                     "weather":"cold rain"}]
    }),encoding="utf-8")
    (ep/"meta/story-gates.json").write_text(json.dumps({
        "visual":{"admission_frames":[],"continuity":{
            "required":["location","key_prop","weather_time"],
            "anchors":{"location":None,"key_prop":None,"weather_time":None}
        }},
        "reviews":{"visual_admission":"pending","authenticity":"pending"}}),encoding="utf-8")
    frames=[1,30,8,47]
    plan={"schema_version":1,"items":[
        {"id":id,"role":role,"frame":frame,"contract_sha256":str(i+1)*64}
        for i,(id,role,frame) in enumerate(zip(
            ("V-B","V-W","V-A","V-H"),lane.ROLES,frames))
    ]}
    monkeypatch.setattr(visual_lock_v21,"choose_plan",lambda e:plan)
    prepared_count=[]
    def prepare(e):
        prepared_count.append(1)
        (ep/"meta/visual-lock-plan.json").write_text(json.dumps(plan))
        gates=json.loads((ep/"meta/story-gates.json").read_text())
        gates["visual"]["calibration"]={"items":[
            {"role":r["role"],"frame":r["frame"],"decision":"pending"}
            for r in plan["items"]]}
        (ep/"meta/story-gates.json").write_text(json.dumps(gates))
        return plan
    monkeypatch.setattr(visual_lock_v21,"prepare",prepare)
    return ep,frames,prepared_count,plan


def test_48_frame_plan_host_materialized_once_without_review_forgery(tmp_path,monkeypatch):
    ep,frames,counts,_=prepared(tmp_path,monkeypatch)
    result=lane.ensure_plan(ep)
    assert result["status"]=="PLANNED"
    assert result["frames"]==frames
    assert result["model_calls"]==0
    assert counts==[1]
    g=json.loads((ep/"meta/story-gates.json").read_text())
    assert g["visual"]["admission_frames"]==sorted(frames)
    assert g["visual"]["continuity"]["anchors"]=={
        "location":"mountain_road","key_prop":"Sony A7S3",
        "weather_time":"night; cold rain"}
    assert g["reviews"]=={"visual_admission":"pending","authenticity":"pending"}
    assert lane.ensure_plan(ep)["status"]=="REUSED"
    assert counts==[1]


def test_readonly_plan_uses_actual_episode_count_not_20():
    plan={"items":[{"frame":f,"role":r} for f,r in
                   zip([1,30,8,47],lane.ROLES)]}
    assert triage.valid_four_frame_plan(plan,frame_count=48)==(1,30,8,47)
    assert triage.valid_four_frame_plan(plan,frame_count=25)==()
    assert triage.valid_four_frame_plan({
        "items":[{"frame":f,"role":r} for f,r in zip([2,30,8,47],lane.ROLES)]
    },frame_count=48)==(2,30,8,47)
    assert triage.valid_four_frame_plan({
        "items":[{"frame":f,"role":r} for f,r in zip([1,30,30,47],lane.ROLES)]
    },frame_count=48)==()


def test_drift_and_missing_frozen_anchor_fail_before_model_or_pixels(tmp_path,monkeypatch):
    ep,frames,counts,plan=prepared(tmp_path,monkeypatch)
    anchor=ep/"meta/world-state.json"
    data=json.loads(anchor.read_text())
    data["initial_state"]["location"]=""
    anchor.write_text(json.dumps(data))
    with pytest.raises(lane.VisualLockHostBlocked,match="ANCHOR"):
        lane.ensure_plan(ep)
    assert counts==[]
    data["initial_state"]["location"]="mountain_road"
    anchor.write_text(json.dumps(data))
    lane.ensure_plan(ep)
    drift={**plan,"items":[*plan["items"][:1],
                           {**plan["items"][1],"frame":22},
                           *plan["items"][2:]]}
    monkeypatch.setattr(visual_lock_v21,"choose_plan",lambda e:drift)
    with pytest.raises(lane.VisualLockHostBlocked,match="DRIFT"):
        lane.ensure_plan(ep)
    assert counts==[1]


def test_scheduler_uses_real_baseline_barrier_and_review_then_three(tmp_path,monkeypatch):
    ep,frames,_,_=prepared(tmp_path,monkeypatch)
    for f in frames:(ep/"prompts/production"/f"{f:02d}.txt").write_text("real source scene")
    monkeypatch.setattr(episode_state_persistence,"load",
                        lambda _:{"current_state":"STORYBOARD_LOCKED"
                         if not finished else "VISUAL_CALIBRATED"})
    finished=[]
    calls=[]
    monkeypatch.setattr(image_scheduler,"import_visual_lock",
                        lambda *a:calls.append("import"))
    def scheduler(*args,**kwargs):
        n=calls.count("scheduler")
        calls.append("scheduler")
        return 20 if n==0 else 0
    monkeypatch.setattr(lane,"_run_native_image_scheduler",scheduler)
    monkeypatch.setattr(visual_lock_baseline_gate,"approved",
                        lambda _:calls.count("baseline_review")>0)
    monkeypatch.setattr(visual_lock_baseline_gate,"generated_baseline",
                        lambda _:{"asset_path":"real.png","sha256":"f"*64})
    monkeypatch.setattr(visual_lock_v21,"bind_from_queue",
                        lambda _:calls.append("bind"))
    monkeypatch.setattr(visual_lock_v21,"verify",
                        lambda _: [] if calls.count("four_review") else ["not reviewed"])
    def review(ep,action):
        calls.append("baseline_review" if action["action"]=="REVIEW_ORDINARY_BASELINE"
                     else "four_review")
        return {"status":"PASS"}
    monkeypatch.setattr(vision_review_executor,"execute",review)
    def final(ep,action):
        assert action["action"]=="FINALIZE_VISUAL_LOCK"
        calls.append("final")
        finished.append(True)
        return {"status":"PASS","report":"PASS"}
    monkeypatch.setattr(machine_action_executor,"execute",final)
    report=lane.run(ep)
    assert report["status"]=="PASS"
    assert calls==["import","scheduler","baseline_review","scheduler",
                   "bind","four_review","final"]


def test_baseline_unavailable_blocks_before_three_or_vision(tmp_path,monkeypatch):
    ep,frames,_,_=prepared(tmp_path,monkeypatch)
    for f in frames:(ep/"prompts/production"/f"{f:02d}.txt").write_text("source")
    monkeypatch.setattr(episode_state_persistence,"load",
                        lambda _:{"current_state":"STORYBOARD_LOCKED"})
    monkeypatch.setattr(image_scheduler,"import_visual_lock",lambda *a:None)
    count=[]
    monkeypatch.setattr(lane,"_run_native_image_scheduler",
                        lambda *a,**kw:count.append(1) or 20)
    monkeypatch.setattr(visual_lock_baseline_gate,"approved",lambda _:False)
    monkeypatch.setattr(visual_lock_baseline_gate,"generated_baseline",
                        lambda _:(_ for _ in ()).throw(ValueError("no pixels")))
    monkeypatch.setattr(vision_review_executor,"execute",
                        lambda *a:pytest.fail("no review without pixels"))
    with pytest.raises(lane.VisualLockHostBlocked,match="BASELINE_ACTUAL_PIXELS_NOT_READY"):
        lane.run(ep)
    assert len(count)==1


def test_review_fail_cannot_advance_to_fake_pass(tmp_path,monkeypatch):
    ep,frames,_,_=prepared(tmp_path,monkeypatch)
    for f in frames:(ep/"prompts/production"/f"{f:02d}.txt").write_text("source")
    monkeypatch.setattr(episode_state_persistence,"load",
                        lambda _:{"current_state":"STORYBOARD_LOCKED"})
    monkeypatch.setattr(image_scheduler,"import_visual_lock",lambda *a:None)
    count=[]
    monkeypatch.setattr(lane,"_run_native_image_scheduler",
                        lambda *a,**kw:count.append(1) or 20)
    monkeypatch.setattr(visual_lock_baseline_gate,"approved",lambda _:False)
    monkeypatch.setattr(visual_lock_baseline_gate,"generated_baseline",
                        lambda _:{"sha256":"f"*64})
    monkeypatch.setattr(vision_review_executor,"execute",
                        lambda *a:{"status":"NEEDS_USER"})
    monkeypatch.setattr(machine_action_executor,"execute",
                        lambda *a:pytest.fail("never finalize on nonPASS"))
    with pytest.raises(lane.VisualLockHostBlocked,match="BASELINE_REVIEW_NOT_PASSED"):
        lane.run(ep)
    assert len(count)==1
    assert json.loads((ep/"meta/story-gates.json").read_text())["reviews"]["visual_admission"]=="pending"

def test_direct_native_text_worker_cannot_repeat_visual_lock_call(tmp_path,monkeypatch):
    import scoped_codex_worker
    monkeypatch.setattr(scoped_codex_worker.runtime_router,"detect",
                        lambda:("CODEX",{}))
    monkeypatch.setattr(scoped_codex_worker.runtime_router,"image_execution_runtime",
                        lambda:("CODEX",{}))
    monkeypatch.setattr(scoped_codex_worker,"execute_model_call",
                        lambda *a,**k:pytest.fail("no text model replay"))
    rc,note=scoped_codex_worker.run_step(tmp_path,"VISUAL_LOCK")
    assert rc==22
    assert note=="VISUAL_LOCK_NATIVE_HOST_PIXEL_LANE_REQUIRED"
