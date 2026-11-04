"""EP14 canonical activation: preserve safety refusals and atomic row identity."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import sys
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "episodes/_system"))
import production_ep14_canonical_activation as act


@pytest.fixture
def state(monkeypatch, tmp_path):
    ep=tmp_path/"ep14"
    ep.mkdir()
    records=[]
    items=[]
    for f in act.FRAMES:
        original={
            "id":f"old_{f}","frame":f,"kind":"original","scope":"batch",
            "status":"external_blocked","attempts":1,
            "no_automatic_original_prompt_retry":True,
            "requires_content_revision":True,
            "prompt_file":f"prompts/production/{f:02d}.txt",
            "prompt_package":{"package_sha256":f"{f:064x}"},
            "model":"gpt-image-2.5-flare","quality":"high","references":[],
        }
        items.append(original)
        payload={
            "frame":f"{f:02d}",
            "frame_contract_sha256":"a"*64,"scene_prompt_sha256":"b"*64,
            "scene_prompt":"safe revised image","frame_prompt_contract":"new render contract",
            "render_content_sha256":f"{f:064x}",
            "final_render_bundle_sha256":act.BUNDLE,
            "storyboard_source":{"render_original_text_injected":False},
            "canonical_activation":False,"production_dispatch_authorized":False,
            "postimage_pixel_review_required":True,
            "independent_preimage_text_approved":True,
        }
        records.append({"frame":f,"sha":payload["render_content_sha256"],"payload":payload})
    q={"items":items,"ep14_render_revision_stage":{
        "state":"STAGED_BLOCKED",
        "binding_sha256":"c"*64,
        "production_dispatch_authorized":False,
        "canonical_prompt_packages_activated":False,
    },"updated_at":"before"}
    state={"queue":deepcopy(q),"files":{},"sql":{},"fail_frame":None,
           "sql_writes":0,"provider_status":"BLOCKED","lock_count":0}
    monkeypatch.setattr(act.reviewed,"verify",lambda ep:{
        "status":"VERIFIED_THREE_REVIEWED_FINAL_MYSQL_PACKAGES_NOT_ACTIVATED",
        "final_render_bundle_sha256":act.BUNDLE,"frames":list(act.FRAMES)})
    monkeypatch.setattr(act.reviewed,"_safe_state",lambda ep:{
        "final_render_bundle_sha256":act.BUNDLE,
        "expected_queue_sha256":act.staged._sha(state["queue"]),
        "records":deepcopy(records)})
    monkeypatch.setattr(act.reviewed,"_verify_row",lambda repo,ep,record:None)
    monkeypatch.setattr(act.candidates,"_episode_id",lambda ep:"00_独立篇/14_深渊疗愈所")
    monkeypatch.setattr(act.identity,"frame_asset_key",lambda ep,f:f"episode/frame-{f:02d}")
    monkeypatch.setattr(act.attempts,"load_asset_state",lambda ep,key:{
        "attempts_consumed":1,"remaining_attempts":1,"active_attempt_index":None})
    monkeypatch.setattr(act.attempts,"load_attempt",lambda ep,key,n:(
        {"status":"FAILED_AFTER_DISPATCH",
         "failure_class":"IMAGE_PROVIDER_SAFETY_REJECTED"} if n==1 else None))
    monkeypatch.setattr(act.scheduler_core,"load_queue",lambda ep:deepcopy(state["queue"]))
    def save(ep,q):
        state["queue"]=deepcopy(q)
    monkeypatch.setattr(act.scheduler_core,"save_queue",save)
    @contextmanager
    def lock(ep):
        state["lock_count"]+=1
        try:yield
        finally:state["lock_count"]-=1
    monkeypatch.setattr(act.scheduler_core,"queue_transaction",lock)
    monkeypatch.setattr(act.runtime_workspace,"read_json",
                        lambda ep,rel,default=None:deepcopy(state["files"].get(str(rel),default)))
    monkeypatch.setattr(act.runtime_workspace,"write_json",
                        lambda ep,rel,value:state["files"].__setitem__(str(rel),deepcopy(value)))
    monkeypatch.setattr(act.backend,"payload_capability_preflight",lambda **kwargs:{
        "status":("BLOCKED" if state["provider_status"] == "TRIAL_UNKNOWN" else state["provider_status"]),
        "failure_class":("LOGIN_AUTH_IMAGE_TOOL_CAPABILITY_UNKNOWN" if state["provider_status"] == "TRIAL_UNKNOWN" else None),
        "tool_capability_state":"EXPLICIT_SUPPORTED" if state["provider_status"]=="PASS" else "UNKNOWN",
        "tool_visibility_evidence_level":None,
        "payload_model":"gpt-image-2.5-flare","payload_quality":"high",
        "image_generation_called":False,"image_attempt_authority_called":False,
    })
    import model_policy
    import production_ep14_native_pilot_proof as pilot
    monkeypatch.setattr(model_policy,"resolve",lambda role,episode=None: (
        {"model":"gpt-image-2.5-flare","quality":"high"} if role=="image.payload" else
        {"model":"gpt-6-luna","reasoning_effort":"high"}))
    monkeypatch.setattr(pilot,"attest_one_frame",lambda strict,payload,controller,codex=None:{
        "trial_scope":pilot.PILOT_STATUS,
        "native_provider_capability_sha256":"f"*64,
        "image_generation_called":False,"image_attempt_authority_called":False,
    })
    class Connection:
        def query_one(self,sql,args):
            assert "TB_PRODUCTION_REVISION" in sql
            return None
        @contextmanager
        def transaction(self):
            assert state["lock_count"]==1
            old=deepcopy(state["sql"])
            try:yield self
            except Exception:
                state["sql"]=old
                raise
        def execute(self,query,args):
            assert query.startswith("INSERT IGNORE INTO TB_PROMPT_PACKAGE ")
            id,episode,frame,kind,sha,payload=args
            if frame==state["fail_frame"]:
                raise RuntimeError("MYSQL_INSERT_INTERRUPTED")
            state["sql_writes"]+=1
            if id not in state["sql"]:
                state["sql"][id]={
                    "PROMPT_PACKAGE_ID":id,"EPISODE_ID":episode,"FRAME_NO":frame,
                    "PACKAGE_TYPE":kind,"SHA256":sha,"PAYLOAD":json.loads(payload)}
        def close(self):pass
    db=Connection()
    from platform.repository.mysql.mysql_prompt_package_repository import MySqlPromptPackageRepository
    class Repo:
        def __init__(self,conn):pass
        def get_by_id(self,id):
            return MySqlPromptPackageRepository._decode(state["sql"].get(id))
    monkeypatch.setattr(act,"MySqlPromptPackageRepository",Repo)
    monkeypatch.setattr(act.candidates,"_open_db",lambda:db)
    return ep,state


def _commit(ep):
    s=act.plan(ep)
    return act.activate(ep,expected_queue_sha256=s["expected_queue_sha256"],
                        expected_final_render_bundle_sha256=s["final_render_bundle_sha256"])


def test_capability_unknown_never_mutates_queue_mysql_or_attempt(state):
    ep,data=state
    old=deepcopy(data["queue"])
    with pytest.raises(act.ActivationDenied,match="REAL_PROVIDER"):
        _commit(ep)
    assert data["queue"]==old
    assert data["sql"]=={}
    assert data["files"]=={}
    assert act.plan(ep)["production_dispatch_authorized"] is False


@pytest.mark.parametrize("bad",["READY_FOR_REAL_CAPABILITY_PROOF","BLOCKED","UNVERIFIED"])
def test_secondary_and_unknown_are_never_provider_authority(state,bad):
    ep,data=state
    data["provider_status"]=bad
    with pytest.raises(act.ActivationDenied,match="REAL_PROVIDER"):
        _commit(ep)
    assert data["sql"]=={}


def test_explicit_provider_ready_activates_three_new_rows_and_leaves_old_unchanged(state):
    ep,data=state
    data["provider_status"]="PASS"
    previous=deepcopy(data["queue"]["items"])
    r=_commit(ep)
    assert r["status"]=="ACTIVATED_THREE_NEW_REVIEWED_REPAIR_IDENTITIES"
    assert r["attempts_reserved"]==0 and r["image_generation_called"] is False
    queue=data["queue"]
    assert queue["items"][:3]==previous
    assert len(queue["items"])==6 and len(data["sql"])==3
    for f in act.FRAMES:
        new=next(x for x in queue["items"] if x["kind"]=="repair" and x["frame"]==f)
        assert new["id"]==act.item_id(f)
        assert new["batch_id"]==f"EP14_F{f:03d}_PIXELS_V1"
        assert new["status"]=="queued"
        assert "no_automatic_original_prompt_retry" not in new
        assert "requires_content_revision" not in new
        package=act.load_for_dispatch(ep,new)
        assert package["canonical_activation"] is True
        assert package["package_sha256"]==f"{f:064x}"
        assert package["original_safety_refusal_preserved"] is True
    assert queue[act.QUEUE_KEY]["postimage_pixel_review_required"] is True


@pytest.mark.parametrize("change",[
    "edited_queue","bad_bundle","missing_original_safety_flag",
    "collision_existing_queue_id","sql_insert_failure","active_file_forged",
])
def test_fail_closed_cas_or_transaction_before_dispatch(state,change):
    ep,data=state
    data["provider_status"]="PASS"
    planned=act.plan(ep)
    if change=="edited_queue":
        data["queue"]["updated_at"]="concurrent"
    elif change=="bad_bundle":
        planned["final_render_bundle_sha256"]="0"*64
    elif change=="missing_original_safety_flag":
        data["queue"]["items"][0].pop("requires_content_revision")
    elif change=="collision_existing_queue_id":
        data["queue"]["items"].append({"id":act.item_id(9),"frame":9})
    elif change=="sql_insert_failure":
        data["fail_frame"]=29
    elif change=="active_file_forged":
        rec=act._active_records(ep,act.reviewed._safe_state(ep)["records"])[0]
        data["files"][rec["reference"]["rel"]]={"forged":True}
    old=deepcopy(data["queue"])
    before=deepcopy(data["sql"])
    with pytest.raises((act.ActivationDenied,act.staged.StageDenied,RuntimeError)):
        act.activate(ep,expected_queue_sha256=planned["expected_queue_sha256"],
                     expected_final_render_bundle_sha256=planned["final_render_bundle_sha256"])
    assert data["queue"]==old
    assert data["sql"]==before


def test_active_queue_refuses_old_original_and_forged_worker_snapshot(state):
    ep,data=state
    data["provider_status"]="PASS"
    _commit(ep)
    old=data["queue"]["items"][0]
    with pytest.raises(act.ActivationDenied):
        act.load_for_dispatch(ep,old)
    new=deepcopy(data["queue"]["items"][3])
    new["prompt_package"]["scene_prompt_sha256"]="0"*64
    with pytest.raises(act.ActivationDenied):
        act.load_for_dispatch(ep,new)
    new=deepcopy(data["queue"]["items"][3])
    new["ep14_active_package_id"]="PP_forged"
    with pytest.raises(act.ActivationDenied):
        act.load_for_dispatch(ep,new)
    assert all(row["status"]=="external_blocked" for row in data["queue"]["items"][:3])


def test_stale_live_row_and_old_preview_backend_both_fail_closed(state,monkeypatch):
    ep,data=state
    data["provider_status"]="PASS"
    _commit(ep)
    import production_ep14_render_queue_stage as legacy
    old=data["queue"]["items"][0]
    new=deepcopy(data["queue"]["items"][3])
    with pytest.raises(legacy.StageDenied):
        legacy.load_for_dispatch(ep,old)
    assert legacy.load_for_dispatch(ep,new)["canonical_activation"] is True
    data["sql"].pop(new["ep14_active_package_id"])
    with pytest.raises(legacy.StageDenied):
        legacy.load_for_dispatch(ep,new)


@pytest.mark.parametrize("bad",["no_budget","attempt_already_active","first_not_safety_refusal","second_attempt_exists"])
def test_historical_paid_attempt_integrity_required_before_provider(state,monkeypatch,bad):
    ep,data=state
    data["provider_status"]="PASS"
    if bad=="no_budget":
        monkeypatch.setattr(act.attempts,"load_asset_state",lambda ep,key:{
            "attempts_consumed":2,"remaining_attempts":0,"active_attempt_index":None})
    elif bad=="attempt_already_active":
        monkeypatch.setattr(act.attempts,"load_asset_state",lambda ep,key:{
            "attempts_consumed":1,"remaining_attempts":1,"active_attempt_index":2})
    elif bad=="first_not_safety_refusal":
        monkeypatch.setattr(act.attempts,"load_attempt",lambda ep,key,n:{
            "status":"SUCCEEDED","failure_class":None} if n==1 else None)
    else:
        monkeypatch.setattr(act.attempts,"load_attempt",lambda ep,key,n:{
            "status":"FAILED_AFTER_DISPATCH","failure_class":"IMAGE_PROVIDER_SAFETY_REJECTED"}
            if n==1 else {"status":"OUTCOME_UNKNOWN"})
    with pytest.raises(act.ActivationDenied,match="SECOND_ATTEMPT_NOT_AUTHORIZED"):
        act.plan(ep)
    assert data["sql"]=={}


def test_worker_denies_historical_refusal_while_allowing_only_verified_repair(state,monkeypatch):
    ep,data=state
    data["provider_status"]="PASS"
    _commit(ep)
    import image_worker_pool as worker
    monkeypatch.setattr(worker.production_native_batch_followon,"_is_ep14",lambda ep:True)
    old=data["queue"]["items"][0]
    new=data["queue"]["items"][3]
    assert worker._content_revision_dispatch_denied(ep,old) is True
    assert worker._content_revision_dispatch_denied(ep,new) is False
    forged=deepcopy(new)
    forged["ep14_active_bundle_sha256"]="0"*64
    assert worker._content_revision_dispatch_denied(ep,forged) is True
    # The entire three-frame binding must agree, even for another frame.
    data["queue"]["items"][4]["ep14_active_package_id"]="PP_forged"
    assert worker._content_revision_dispatch_denied(ep,new) is True


def test_real_backend_consumes_exact_activated_render_not_old_prompt(state,monkeypatch):
    ep,data=state
    data["provider_status"]="PASS"
    _commit(ep)
    import argparse
    import codex_subscription_image as image
    import production_native_batch_followon as batch
    import logical_asset_identity as identities
    monkeypatch.setattr(batch,"_is_ep14",lambda ep:True)
    new=deepcopy(data["queue"]["items"][3])
    frame=new["frame"]
    source=act.load_for_dispatch(ep,new)
    args=argparse.Namespace(frame=str(frame),_queue_item_id=new["id"],
        _activated_render_package=source,_canonical_payload_request={
            "frame_contract_sha256":source["frame_contract_sha256"],
            "logical_asset_key":identities.frame_asset_key(ep,frame)})
    result=image._effective_frame_prompt_package(ep,args,ep/"prompts/old.txt")
    assert result["package_sha256"]==source["package_sha256"]
    assert result["scene_prompt"]==source["scene_prompt"]
    args._activated_render_package={**source,"scene_prompt":"original denied prompt"}
    with pytest.raises(image.BackendError):
        image._effective_frame_prompt_package(ep,args,ep/"prompts/old.txt")


def test_native_unknown_capability_may_only_queue_f009_after_dual_native_attestation(state):
    ep,data=state
    data["provider_status"]="TRIAL_UNKNOWN"
    original=deepcopy(data["queue"]["items"])
    result=_commit(ep)
    assert result["provider_trial_only"] is True
    assert result["pilot_frame"]==9
    assert result["held_frames"]==[29,48]
    assert data["queue"]["items"][:3]==original
    repaired={x["frame"]:x for x in data["queue"]["items"][3:]}
    assert repaired[9]["status"]=="queued"
    assert repaired[29]["status"]=="pilot_hold"
    assert repaired[48]["status"]=="pilot_hold"
    assert data["queue"][act.QUEUE_KEY]["pilot_mode"]=="PILOT_FRAME_09_ONLY_REAL_PROVIDER_PROOF"
    assert len(data["sql"])==3
    assert result["attempts_reserved"]==0
    with pytest.raises(act.ActivationDenied):
        act.load_for_dispatch(ep,repaired[29])
    assert act.load_for_dispatch(ep,repaired[9])["canonical_activation"] is True


def test_f009_superseded_only_with_real_pixel_proof_for_other_reviewed_frames(state,monkeypatch):
    ep,data=state
    data["provider_status"]="PASS"
    _commit(ep)
    import production_ep14_followon_release as followon
    data["queue"]["items"][0]["status"]="superseded"
    f29=deepcopy(data["queue"]["items"][4])
    proofs=[]
    def approve_previous(ep,rows):
        proofs.append(sorted(rows))
        return {"real_provider_frame":9,"native_attempt2_status":"SUCCEEDED"}
    monkeypatch.setattr(followon,"_previous_provider_and_review",approve_previous)
    assert act.load_for_dispatch(ep,f29)["canonical_activation"] is True
    assert proofs and 9 in proofs[0]
    # Never allow redispatch of the original or bypass without genuine proof.
    with pytest.raises(act.ActivationDenied):
        act.load_for_dispatch(ep,data["queue"]["items"][0])
    def no_pixel_proof(*args):
        raise followon.FollowonDenied("F009_SHA_MISMATCH")
    monkeypatch.setattr(followon,"_previous_provider_and_review",no_pixel_proof)
    with pytest.raises(act.ActivationDenied,match="SUPERSEDED_F009_REAL_PIXEL"):
        act.load_for_dispatch(ep,f29)
