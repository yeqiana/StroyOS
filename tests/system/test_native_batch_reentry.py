from pathlib import Path
import sys
from unittest.mock import patch
from contextlib import nullcontext

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"episodes/_system"))
import production_native_batch_reentry as b

def test_no_ack_cannot_rearm():
    assert b.rearm_one(Path("."))=={"status":"BLOCKED","reason":"ACK_REQUIRED"}

def test_rearm_requires_real_secondary_evidence_and_preserves_other_15():
    rows=[{"id":f"batch-{i}","frame":i,"scope":"batch","kind":"original",
           "status":"blocked","technical_failure_code":b.FAILURE} for i in range(2,18)]
    q={"items":rows}
    payload={"model":"gpt-image-2.5-flare","quality":"high"}
    controller={"model":"gpt-6-luna","reasoning_effort":"high"}
    def admissible(_ep,item,_payload,_controller,*,queue,blocked):
        return bool(blocked and item is rows[0] and item.get("status")=="blocked")
    with (patch.object(b.model_policy,"resolve",side_effect=[payload,controller]*2),
          patch.object(b.scheduler_core,"queue_transaction",return_value=nullcontext()),
          patch.object(b.scheduler_core,"load_queue",return_value=q),
          patch.object(b.scheduler_core,"save_queue") as saved,
          patch.object(b,"eligible",side_effect=admissible),
          patch.object(b.image_payload_transport,"payload_capability_preflight",return_value={"status":"BLOCKED"}),
          patch.object(b.baseline,"attest_secondary",side_effect=[None,{"status":"READY_FOR_REAL_CAPABILITY_PROOF"}]),
          patch.object(b.baseline,"evidence_sha",return_value="a"*64)):
        assert b.rearm_one(Path("."),acknowledged=True)["status"]=="BLOCKED"
        saved.assert_not_called()
        result=b.rearm_one(Path("."),acknowledged=True)
        assert result["rearmed_frames"]==[2]
        assert saved.call_count==1
        assert rows[0]["status"]=="queued" and rows[0][b.FLAG] is True
        assert all(r["status"]=="blocked" for r in rows[1:])

def test_no_bypass_for_unverified_eligibility():
    with (patch.object(b.model_policy,"resolve",side_effect=[{"model":"x"},{"model":"y"}]),
          patch.object(b.scheduler_core,"queue_transaction",return_value=nullcontext()),
          patch.object(b.scheduler_core,"load_queue",return_value={"items":[{"frame":2,"id":"x","scope":"batch","status":"blocked"}]}),
          patch.object(b,"eligible",return_value=False),
          patch.object(b.image_payload_transport,"payload_capability_preflight") as probe):
        assert b.rearm_one(Path("."),acknowledged=True)["status"]=="BLOCKED"
        probe.assert_not_called()

def test_worker_requires_native_batch_specific_gate():
    worker=(ROOT/"episodes/_system/image_worker_pool.py").read_text(encoding="utf-8")
    assert "production_native_batch_reentry.eligible(" in worker
    assert "or native_batch_probe is not None" in worker
    assert "PRODUCTION_NATIVE_BATCH_SINGLE_FRAME_PROOF" in worker


def test_rearm_cannot_duplicate_after_first_queued(monkeypatch):
    row={"id":"batch-2","frame":2,"scope":"batch","status":"queued","native_single_batch_proof":True}
    with (patch.object(b.model_policy,"resolve",side_effect=[{"model":"x"},{"model":"y"}]),
          patch.object(b.scheduler_core,"queue_transaction",return_value=nullcontext()),
          patch.object(b.scheduler_core,"load_queue",return_value={"items":[row]}),
          patch.object(b.scheduler_core,"save_queue") as save,
          patch.object(b,"eligible",return_value=False),
          patch.object(b.baseline,"attest_secondary") as probe):
        assert b.rearm_one(Path("."),acknowledged=True)["status"]=="BLOCKED"
        save.assert_not_called()
        probe.assert_not_called()

def test_first_batch_only_and_active_attempt_never_eligible(tmp_path):
    ep=tmp_path/"episodes"/"00_独立篇"/"13_失物归还的那扇门"
    ep.mkdir(parents=True)
    originals=[{"id":f"visual-{i}","frame":i,"scope":"visual_lock","status":"generated"}
               for i in (1,3,8,18)]
    batch=[{"id":f"batch-{i}","frame":i,"scope":"batch","kind":"original",
            "model":"gpt-image-2.5-flare","status":"blocked",
            "technical_failure_code":b.FAILURE} for i in range(2,18)]
    q={"items":originals+batch}
    payload={"model":"gpt-image-2.5-flare","quality":"high"}
    controller={"model":"gpt-6-luna","reasoning_effort":"high"}
    with (patch.object(b,"ROOT",tmp_path),
          patch.object(b.episode_state_persistence,"load",
                       return_value={"current_state":"VISUAL_CALIBRATED"}),
          patch.object(b.runtime_request,"effective_for_episode",
                       return_value={"mode":"full_auto","runtime":{"execution_mode":"dag"}}),
          patch.object(b.runtime_router,"image_execution_runtime",return_value=("CODEX",{})),
          patch.object(b.storage_config,"mysql_connection_kwargs",
                       return_value={"host":"127.0.0.1","port":3307}),
          patch.object(b.image_payload_transport,"selected_route",
                       return_value={"provider":"codex_subscription"}),
          patch.object(b.attempts,"load_asset_state",
                       return_value={"attempts_consumed":0,"active_attempt_index":None}) as authority,
          patch.object(b,"_reviewed",return_value=True)):
        assert b.eligible(ep,batch[0],payload,controller,queue=q,blocked=True)
        assert not b.eligible(ep,batch[1],payload,controller,queue=q,blocked=True)
        assert not b.eligible(ep,batch[0],payload,controller,queue=q,blocked=False)
        batch[0]["status"]="queued"
        batch[0].pop("technical_failure_code")
        batch[0][b.FLAG]=True
        assert b.eligible(ep,batch[0],payload,controller,queue=q)
        authority.return_value={"attempts_consumed":0,"active_attempt_index":1}
        assert not b.eligible(ep,batch[0],payload,controller,queue=q)
        authority.return_value={"attempts_consumed":1,"active_attempt_index":None}
        assert not b.eligible(ep,batch[0],payload,controller,queue=q)


def test_native_historical_pixel_and_runner_receipt_sha_must_match(tmp_path):
    import hashlib
    ep=tmp_path/"episodes"/"00_独立篇"/"13_失物归还的那扇门"
    (ep/"media/raw").mkdir(parents=True)
    raw=ep/"media/raw/01-original.png"
    raw.write_bytes(bytes.fromhex("89504e470d0a1a0a")+b"valid-pixel-evidence"*3)
    (ep/"media/raw/01-repair.png").write_bytes(b"repair-frame01")
    home=tmp_path/"codex-home"
    exported=home/"generated_images"/"thread-id"/"pixel.png"
    exported.parent.mkdir(parents=True)
    exported.write_bytes(raw.read_bytes())
    rid="a"*32
    receipt=tmp_path/"runtime/codex-user-runner/task-results"/(rid+".json")
    receipt.parent.mkdir(parents=True)
    import json
    receipt.write_text(json.dumps({"request_id":rid,"returncode":0,
        "evidence":{"request_id":rid,"returncode":0,"task_type":"image",
                    "transport_route":"native_codex","thread_ids":["thread-id"],
                    "generated_artifacts":["thread-id/pixel.png"]}}),encoding="utf-8")
    sha=lambda data:hashlib.sha256(data).hexdigest()
    proof={"proof_kind":"TRUSTED_NATIVE_RUNNER_THREAD_SCOPED_IMAGE_SHA",
           "attempt_index":2,"provider_model_attested":False,
           "generation_key":"fixed-key","runner_request_id":rid,
           "exported_artifact_relative_path":"thread-id/pixel.png",
           "native_codex_thread_id":"thread-id",
           "raw_png_sha256":sha(raw.read_bytes()),
           "runner_receipt_sha256":sha(receipt.read_bytes())}
    queue={"items":[{"scope":"visual_lock","frame":i,"status":"generated"}
                    for i in (1,3,8,18)]}
    def read_json(path):
        return proof if "native-baseline" in str(path) else {"decision":"PASS"}
    import visual_lock_baseline_gate
    with (patch.object(b,"ROOT",tmp_path),
          patch.object(visual_lock_baseline_gate,"approved",return_value=True),
          patch.object(b.story_json,"read_json",side_effect=read_json),
          patch.object(b.attempts,"load_attempt",
                       return_value={"status":"SUCCEEDED","provider":"codex_subscription",
                                     "generation_key":"fixed-key"}),
          patch.object(b.codex_user_runner,"codex_home",return_value=(home,"native"))):
        assert b._reviewed(ep,queue)
        exported.unlink()
        assert b._reviewed(ep,queue)
        raw.write_bytes(raw.read_bytes()+b"tampered")
        assert not b._reviewed(ep,queue)
        raw.write_bytes(bytes.fromhex("89504e470d0a1a0a")+b"valid-pixel-evidence"*3)
        receipt.write_bytes(receipt.read_bytes()+b"tampered")
        assert not b._reviewed(ep,queue)

def test_live_codex_probe_runs_outside_queue_lock():
    from contextlib import contextmanager
    busy={"locked":False}
    row={"id":"2","frame":2,"status":"blocked","scope":"batch",
         "technical_failure_code":b.FAILURE}
    q={"items":[row]}
    @contextmanager
    def transaction(_ep):
        assert busy["locked"] is False
        busy["locked"]=True
        try:
            yield
        finally:
            busy["locked"]=False
    def probe(**kwargs):
        assert not busy["locked"], "never hold the Queue transaction across Codex network call"
        return {"status":"BLOCKED"}
    with (patch.object(b.model_policy,"resolve",side_effect=[
              {"model":"gpt-image-2.5-flare","quality":"high"},
              {"model":"gpt-6-luna","reasoning_effort":"high"}]),
          patch.object(b.scheduler_core,"queue_transaction",side_effect=transaction),
          patch.object(b.scheduler_core,"load_queue",return_value=q),
          patch.object(b,"eligible",return_value=True),
          patch.object(b.image_payload_transport,"payload_capability_preflight",side_effect=probe),
          patch.object(b.baseline,"attest_secondary",return_value=None)):
        assert b.rearm_one(Path("."),acknowledged=True)["reason"]=="SESSION_TOOL_UNVERIFIED"
    assert not busy["locked"]
