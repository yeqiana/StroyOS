"""One-frame native repair pilot: failing closed on image capability UNKNOWN."""
import sys
from pathlib import Path
from contextlib import nullcontext
from unittest.mock import patch
import pytest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"episodes/_system"))
import production_native_repair_pilot as pilot

def test_no_ack_never_probes_or_mutates():
    with patch.object(pilot.image_payload_transport,"payload_capability_preflight") as probe:
        assert pilot.rearm_one(Path(".")) == {"status":"BLOCKED","reason":"ACK_REQUIRED"}
        probe.assert_not_called()

def test_one_pilot_only_and_secondary_proof_required(tmp_path):
    ep=tmp_path/"episodes/00_独立篇/13_失物归还的那扇门"
    ep.mkdir(parents=True)
    rows=[{"id":f"repair-{i}","frame":i,"scope":"repair","kind":"repair",
            "status":"blocked","technical_failure_code":pilot.FAILURE,
            "last_error":pilot.FAILURE+": independent payload route unavailable; provider=codex_subscription"}
          for i in pilot.REPAIR_FRAMES]
    queue={"items":rows}
    payload={"model":"gpt-image-2.5-flare","quality":"high"}
    controller={"model":"gpt-6-luna","reasoning_effort":"high"}
    with (patch.object(pilot.model_policy,"resolve",side_effect=[payload,controller]*3),
          patch.object(pilot.scheduler_core,"queue_transaction",return_value=nullcontext()),
          patch.object(pilot.scheduler_core,"load_queue",return_value=queue),
          patch.object(pilot.scheduler_core,"save_queue") as saved,
          patch.object(pilot,"eligible",side_effect=lambda _ep,item,*a,**k:item is rows[0] and item["status"]=="blocked"),
          patch.object(pilot.image_payload_transport,"payload_capability_preflight",return_value={"status":"BLOCKED"}),
          patch.object(pilot.baseline,"attest_secondary",side_effect=[None,{"status":"READY_FOR_REAL_CAPABILITY_PROOF"}]),
          patch.object(pilot.baseline,"evidence_sha",return_value="a"*64)):
        assert pilot.rearm_one(ep,acknowledged=True)["status"]=="BLOCKED"
        saved.assert_not_called()
        result=pilot.rearm_one(ep,acknowledged=True)
        assert result["status"]=="PASS"
        assert result["rearmed_frames"]==[2]
        assert result["provider_calls"]==0 and result["attempts_reserved"]==0
        assert rows[0][pilot.FLAG] is True and rows[0]["status"]=="queued"
        assert rows[0]["native_repair_pilot_rearm_count"]==1
        assert all(row["status"]=="blocked" for row in rows[1:])
        assert saved.call_count==1
        assert pilot.rearm_one(ep,acknowledged=True)["status"]=="BLOCKED"

def test_worker_only_accepts_verified_pilot_and_new_visibility(tmp_path):
    worker=(ROOT/"episodes/_system/image_worker_pool.py").read_text(encoding="utf-8")
    assert "production_native_repair_pilot.eligible(" in worker
    assert "native_repair_probe is not None" in worker
    assert "PRODUCTION_NATIVE_REPAIR_SINGLE_FRAME_PROOF" in worker

def test_unverified_blocked_queue_does_not_touch_model_or_db(tmp_path):
    ep=tmp_path/"episode"
    with (patch.object(pilot.model_policy,"resolve",side_effect=[{},{}]),
          patch.object(pilot.scheduler_core,"queue_transaction",return_value=nullcontext()),
          patch.object(pilot.scheduler_core,"load_queue",return_value={"items":[]}),
          patch.object(pilot.image_payload_transport,"payload_capability_preflight") as proof,
          patch.object(pilot.scheduler_core,"save_queue") as save):
        assert pilot.rearm_one(ep,acknowledged=True)["status"]=="BLOCKED"
        proof.assert_not_called()
        save.assert_not_called()


def _authoritative_fixture(tmp_path,monkeypatch):
    import json
    import hashlib
    import production_ledger
    ep=tmp_path/"episodes/00_独立篇/13_失物归还的那扇门"
    (ep/"meta/runtime").mkdir(parents=True)
    photo=ep/"media/candidates/02-original.png"
    photo.parent.mkdir(parents=True)
    photo.write_bytes(b"synthetic-original-pixel"*5)
    sha=hashlib.sha256(photo.read_bytes()).hexdigest()
    review=ep/"meta/frame-semantic-candidate-attempt-1.json"
    review.write_text('{"review_scope":"CANDIDATE_FULL_FRAME_SET"}',encoding="utf-8")
    review_sha=hashlib.sha256(review.read_bytes()).hexdigest()
    wave_id="00_独立篇/13_失物归还的那扇门/production/repair-wave-1"
    rows=[]
    qr=[]
    for frame in sorted(pilot.REPAIR_FRAMES):
        identity=str(frame)
        rows.append({"frame_id":str(frame).zfill(2),"repairable":True,
            "repair_status":"ENQUEUED","repair_queue_item_id":"repair-"+identity,
            "source_generation_key":"generation-"+identity,
            "source_artifact_sha256":sha,
            "repair_prompt_task_fingerprint":"a"*64,
            "review_receipt_sha256":review_sha,"remaining_generation_attempts":1})
        qr.append({"id":"repair-"+identity,"frame":frame,"kind":"repair",
            "scope":"repair","model":"gpt-image-2.5-flare","status":"blocked",
            "technical_failure_code":pilot.FAILURE,"last_error":pilot.EXPECTED_ERROR,
            "repair_wave_id":wave_id,"source_generation_key":"generation-"+identity,
            "source_artifact_sha256":sha,"repair_prompt_task_fingerprint":"a"*64})
    wave={"status":"STARTED","repair_wave_id":wave_id,
          "source_review_scope":"CANDIDATE_FULL_FRAME_SET",
          "source_review_receipts":[{"path":"meta/frame-semantic-candidate-attempt-1.json",
                                     "sha256":review_sha}],
          "summary":{"eligible_repairs":13},"frames":rows}
    (ep/"meta/runtime/repair-wave-1.json").write_text(json.dumps(wave),encoding="utf-8")
    ledger={"frames":{"02":{"status":"TECH_FAILED",
                              "current_candidate":{"sha256":sha,"path":str(photo)},
                              "attempts":[{"kind":"repair"}]}}}
    state={"attempts_consumed":1,"active_attempt_index":None,"outcome_unknown_count":0}
    monkeypatch.setattr(pilot,"ROOT",tmp_path)
    monkeypatch.setattr(pilot.runtime_request,"effective_for_episode",
                        lambda _:{"mode":"full_auto","runtime":{"execution_mode":"dag"}})
    monkeypatch.setattr(pilot.runtime_router,"image_execution_runtime",
                        lambda:("CODEX",{}))
    monkeypatch.setattr(pilot.episode_state_persistence,"load",
                        lambda _:{"current_state":"VISUAL_CALIBRATED"})
    monkeypatch.setattr(pilot.storage_config,"mysql_connection_kwargs",
                        lambda:{"host":"127.0.0.1","port":13307})
    monkeypatch.setattr(pilot.image_payload_transport,"selected_route",
                        lambda _:{"provider":"codex_subscription"})
    monkeypatch.setattr(pilot.production_ledger,"load_authority",lambda *_a,**_k:ledger)
    monkeypatch.setattr(pilot.logical_asset_identity,"frame_asset_key",
                        lambda *_a:str(pilot.PILOT_FRAME))
    monkeypatch.setattr(pilot.attempts,"load_asset_state",lambda *_a:state)
    monkeypatch.setattr(pilot.attempts,"remaining",lambda *_a:1)
    payload={"model":"gpt-image-2.5-flare","quality":"high"}
    controller={"model":"gpt-6-luna","reasoning_effort":"high"}
    return ep,{"items":qr},wave,ledger,state,payload,controller


def test_real_verified_wave_and_original_pixel_are_required(tmp_path,monkeypatch):
    ep,q,w,l,state,payload,controller=_authoritative_fixture(tmp_path,monkeypatch)
    pilot_item=q["items"][0]
    assert pilot.eligible(ep,pilot_item,payload,controller,queue=q,blocked=True)
    # Worker still cannot run until exactly this repair row is rearmed.
    assert not pilot.eligible(ep,pilot_item,payload,controller,queue=q)
    pilot_item[pilot.FLAG]=True
    pilot_item["native_repair_pilot_rearm_count"]=1
    pilot_item["native_repair_visibility_sha256"]="b"*64
    pilot_item["status"]="queued"
    pilot_item["last_error"]=None
    pilot_item.pop("technical_failure_code")
    assert pilot.eligible(ep,pilot_item,payload,controller,queue=q)
    # Ledger begin transitions TECH_FAILED -> REPAIRING before the worker runs.
    l["frames"]["02"]["status"]="REPAIRING"
    assert pilot.eligible(ep,pilot_item,payload,controller,queue=q)


@pytest.mark.parametrize("tamper",["unknown","active","budget","sha","queue_id","missing_review","wrong_model","missing_original","other_frame","other_mysql"])
def test_real_guard_denies_stale_or_unauthorized_repair(tmp_path,monkeypatch,tamper):
    ep,q,w,l,state,payload,controller=_authoritative_fixture(tmp_path,monkeypatch)
    item=q["items"][0]
    if tamper=="unknown":state["outcome_unknown_count"]=1
    if tamper=="active":state["active_attempt_index"]=2
    if tamper=="budget":state["attempts_consumed"]=2
    if tamper=="sha":
        r=ep/"meta/runtime/repair-wave-1.json"
        x=__import__("json").loads(r.read_text(encoding="utf-8"))
        x["source_review_receipts"][0]["sha256"]="c"*64
        r.write_text(__import__("json").dumps(x),encoding="utf-8")
    if tamper=="queue_id":item["id"]="tampered"
    if tamper=="missing_review":
        (ep/"meta/frame-semantic-candidate-attempt-1.json").unlink()
    if tamper=="wrong_model":payload["model"]="wrong"
    if tamper=="missing_original":
        (ep/"media/candidates/02-original.png").unlink()
    if tamper=="other_frame":item=q["items"][1]
    if tamper=="other_mysql":
        monkeypatch.setattr(pilot.storage_config,"mysql_connection_kwargs",
                            lambda:{"host":"192.168.1.20","port":3307})
    assert not pilot.eligible(ep,item,payload,controller,queue=q,blocked=True)
