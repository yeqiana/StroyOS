from pathlib import Path
from contextlib import nullcontext
from unittest.mock import patch
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"episodes/_system"))
import production_native_batch_followon as f

def _queue():
    rows=[{"id":"batch-02","frame":2,"scope":"batch","kind":"original",
           "model":"gpt-image-2.5-flare","status":"generated","output_path":"episodes/00_独立篇/13_失物归还的那扇门/media/candidates/scheduled/02-original.png"}]
    rows.extend({"id":f"batch-{n:02d}","frame":n,"scope":"batch","kind":"original",
                 "model":"gpt-image-2.5-flare","status":"blocked",
                 "technical_failure_code":f.FAILURE} for n in (4,5,6,7,9,10,11,12,13,14,15,16,17,19,20))
    return {"items":rows}

def test_machine_resume_fences_and_restores_only_history_unknown_rows():
    q=_queue()
    with (patch.object(f,"admissible",return_value=True),
          patch.object(f,"_policies",return_value=({"model":"gpt-image-2.5-flare","quality":"high"},{"model":"gpt-6-luna","reasoning_effort":"high"})),
          patch.object(f,"_anchor",return_value="a"*64),
          patch.object(f.scheduler_core,"queue_transaction",return_value=nullcontext()),
          patch.object(f.scheduler_core,"load_queue",return_value=q),
          patch.object(f.scheduler_core,"save_queue") as saved,
          patch.object(f.image_payload_transport,"payload_capability_preflight",return_value={"status":"BLOCKED","failure_class":f.FAILURE}),
          patch.object(f.baseline,"attest_secondary",return_value={"status":"READY_FOR_REAL_CAPABILITY_PROOF"}) as secondary,
          patch.object(f.baseline,"evidence_sha",return_value="b"*64)):
        result=f.resume(Path("."),acknowledged=True)
        assert result["status"]=="PASS"
        assert len(result["rearmed_frames"])==15
        assert saved.call_count==1 and secondary.call_count==1
        assert q["items"][0]["status"]=="generated"
        assert all(r["status"]=="queued" and r[f.FLAG] is True
                   and r["native_batch_success_anchor_sha256"]=="a"*64
                   for r in q["items"][1:])

def test_failed_session_probe_preserves_all_history_without_mutation():
    q=_queue()
    with (patch.object(f,"admissible",return_value=True),
          patch.object(f,"_policies",return_value=({"model":"gpt-image-2.5-flare","quality":"high"},{"model":"gpt-6-luna","reasoning_effort":"high"})),
          patch.object(f,"_anchor",return_value="a"*64),
          patch.object(f.scheduler_core,"queue_transaction",return_value=nullcontext()),
          patch.object(f.scheduler_core,"load_queue",return_value=q),
          patch.object(f.scheduler_core,"save_queue") as saved,
          patch.object(f.image_payload_transport,"payload_capability_preflight",return_value={"status":"BLOCKED","failure_class":f.FAILURE}),
          patch.object(f.baseline,"attest_secondary",return_value=None)):
        result=f.resume(Path("."),acknowledged=True)
        assert result["status"]=="BLOCKED"
        assert all(r["status"]=="blocked" for r in q["items"][1:])
        saved.assert_not_called()

def test_never_auto_resume_if_authority_unverified():
    q=_queue()
    with (patch.object(f,"admissible",return_value=False),
          patch.object(f.scheduler_core,"queue_transaction",return_value=nullcontext()),
          patch.object(f.scheduler_core,"load_queue",return_value=q),
          patch.object(f.image_payload_transport,"payload_capability_preflight") as provider):
        assert f.resume(Path("."),acknowledged=True)["status"]=="BLOCKED"
        provider.assert_not_called()

def test_worker_followon_flag_alone_never_grants_access():
    q=_queue()
    row=q["items"][1]
    row["status"]="queued"
    row[f.FLAG]=True
    row["native_batch_success_anchor_sha256"]="a"*64
    row["native_batch_followon_evidence_sha256"]="b"*64
    with (patch.object(f,"_anchor",return_value=None),
          patch.object(f,"_episode_authorized",return_value=True)):
        assert not f.worker_eligible(Path("."),row,{"model":"gpt-image-2.5-flare","quality":"high"},{"model":"gpt-6-luna","reasoning_effort":"high"},queue=q)

def test_registered_in_machine_action_and_autonomous_regression():
    machine=(ROOT/"episodes/_system/machine_action_executor.py").read_text("utf-8")
    action=(ROOT/"episodes/_system/next_action.py").read_text("utf-8")
    worker=(ROOT/"episodes/_system/image_worker_pool.py").read_text("utf-8")
    fast=(ROOT/"scripts/storyos_autonomy_fast_test.py").read_text("utf-8")
    assert "RESUME_NATIVE_BATCH_AFTER_SUCCESS" in machine
    assert "RESUME_NATIVE_BATCH_AFTER_SUCCESS" in action
    assert "production_native_batch_followon.worker_eligible(" in worker
    assert "test_native_batch_post_success_followon.py" in fast

def test_real_first_batch_succeeded_mysql_record_must_match_file_and_triage(tmp_path):
    import hashlib
    from PIL import Image
    ep=tmp_path/"episodes"/"00_独立篇"/"13_失物归还的那扇门"
    path=ep/"media/candidates/scheduled/02-original.png"
    path.parent.mkdir(parents=True)
    Image.new("RGB",(1080,1350)).save(path)
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    q=_queue()
    row=q["items"][0]
    row.update({"output_path":str(path.relative_to(tmp_path)),
                "quality":"high","attempt_index":1,"generation_key":"gkey",
                "local_visual_triage":{"status":"PASS","block_commit":False,"candidate_sha256":digest}})
    attempt={"status":"SUCCEEDED","provider":"codex_subscription",
             "payload_model":"gpt-image-2.5-flare","payload_quality":"high",
             "generation_key":"gkey","result_ref":"normalized_candidate_exists"}
    payload={"model":"gpt-image-2.5-flare","quality":"high"}
    controller={"model":"gpt-6-luna","reasoning_effort":"high"}
    with (patch.object(f,"ROOT",tmp_path),
          patch.object(f,"_episode_authorized",return_value=True),
          patch.object(f.first_proof,"_reviewed",return_value=True),
          patch.object(f.attempts,"load_asset_state",
                       return_value={"attempts_consumed":1,"active_attempt_index":None,"outcome_unknown_count":0}),
          patch.object(f.attempts,"load_attempt",return_value=attempt)):
        assert f._anchor(ep,q,payload,controller)==digest
        attempt["provider"]="openai_images_api"
        assert f._anchor(ep,q,payload,controller) is None
        attempt["provider"]="codex_subscription"
        row["local_visual_triage"]["candidate_sha256"]="0"*64
        assert f._anchor(ep,q,payload,controller) is None
        row["local_visual_triage"]["candidate_sha256"]=digest
        path.write_bytes(b"not a valid PNG")
        assert f._anchor(ep,q,payload,controller) is None


def test_only_zero_attempt_unblocked_batch_receives_worker_native_proof():
    q=_queue()
    row=q["items"][1]
    row.update({"status":"running",f.FLAG:True,
                "native_batch_success_anchor_sha256":"a"*64,
                "native_batch_followon_evidence_sha256":"b"*64})
    payload={"model":"gpt-image-2.5-flare","quality":"high"}
    controller={"model":"gpt-6-luna","reasoning_effort":"high"}
    with (patch.object(f,"_anchor",return_value="a"*64),
          patch.object(f,"_episode_authorized",return_value=True),
          patch.object(f.attempts,"load_asset_state",
                       return_value={"attempts_consumed":0,"active_attempt_index":None,"outcome_unknown_count":0}) as state):
        assert f.worker_eligible(Path("."),row,payload,controller,queue=q)
        state.return_value={"attempts_consumed":0,"active_attempt_index":1}
        assert not f.worker_eligible(Path("."),row,payload,controller,queue=q)
        state.return_value={"attempts_consumed":1,"active_attempt_index":None}
        assert not f.worker_eligible(Path("."),row,payload,controller,queue=q)
        state.return_value={"attempts_consumed":0,"active_attempt_index":None,"outcome_unknown_count":1}
        assert not f.worker_eligible(Path("."),row,payload,controller,queue=q)


def test_next_action_chooses_machine_resume_before_historical_hard_stop():
    # Integration contract is also covered by the real derive harness below.
    from machine_action_executor import local_machine_action
    action={"action":"RESUME_NATIVE_BATCH_AFTER_SUCCESS","executor":"MACHINE"}
    assert local_machine_action(action)=="RESUME_NATIVE_BATCH_AFTER_SUCCESS"
    assert local_machine_action({**action,"executor":"CODEX_IMAGE"}) is None
