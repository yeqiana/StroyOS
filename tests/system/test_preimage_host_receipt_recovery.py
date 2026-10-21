"""PREIMAGE Host envelope: model payload, native evidence and rc4 resume guards."""
from __future__ import annotations
from datetime import datetime,timezone
from pathlib import Path
import hashlib
import json
import os
import sys
import pytest

SYSTEM=Path(__file__).resolve().parents[2]/"episodes"/"_system"
if str(SYSTEM) not in sys.path:sys.path.insert(0,str(SYSTEM))
import preimage_task_contract as tasks
import preimage_host_receipt_recovery as recovery
import preimage_protocol

def case(tmp_path,monkeypatch,*,extra_turn=False):
    root=tmp_path
    ep=root/"episodes"/"00"/"14_trial"
    logdir=ep/"meta/scoped-workers"
    cdir=ep/"meta/runtime/preimage-candidates"
    rdir=ep/"meta/provider-receipts/model-executions"
    for p in (logdir,cdir,rdir):p.mkdir(parents=True,exist_ok=True)
    monkeypatch.setattr(recovery,"ROOT",root)
    t={"task_type":"CHARACTER_FINALIZE","task_id":"preimage-char-snapshot-A",
       "node_id":"character_finalize","snapshot_id":"snapshot-A",
       "candidate_output":"meta/runtime/preimage-candidates/character-finalize.json",
       "authority_scope":["character.finalize"],
       "input_contract":{"source_authority_sha256":{"character":"a"*64}},
       "verifier":"verify_character_finalize_candidate","status":"RETRY"}
    payload={"character.finalize":{
        "character":{"visible_cast":["P01"],"relationship":"team"},
        "identity":{"P01":{"name":"A"}},"pov":{"character_id":"P01","capture_rule":"POV"},
        "appearance":{"P01":{"anchor":"locked"}}}}
    candidate={"schema_version":1,"task_id":t["task_id"],"task_type":t["task_type"],
               "node_id":t["node_id"],"snapshot_id":t["snapshot_id"],"payload":payload}
    cp=cdir/"character-finalize.json"
    cp.write_text(json.dumps(candidate),encoding="utf-8")
    stamp=datetime(2026,10,21,13,56,51,tzinfo=timezone.utc).timestamp()
    os.utime(cp,(stamp,stamp))
    event=[{"type":"thread.started","thread_id":"thread-one"},
           {"type":"item.completed","item":{"type":"file_change","status":"completed",
            "changes":[{"path":cp.resolve().as_posix(),"kind":"add"}]}},
           {"type":"turn.completed"}]
    if extra_turn:event.extend([{"type":"thread.started","thread_id":"thread-two"},{"type":"turn.completed"}])
    log=logdir/"preimage_character_finalize.jsonl"
    log.write_text("".join(json.dumps(x)+"\n" for x in event),encoding="utf-8")
    for i in range(2 if extra_turn else 1):
        ident=f"receipt{i}"
        receipt={"episode_id":"00/14_trial","step":"PREIMAGE_CHARACTER_FINALIZE",
                 "call_id":ident,"status":"SUCCESS","runner":"codex exec",
                 "model_binding_source":"EPISODE_BOUND_MODEL_POLICY",
                 "started_at":"2026-10-21T21:54:55+08:00" if i==0 else "2026-10-21T22:00:00+08:00",
                 "finished_at":"2026-10-21T21:58:02+08:00" if i==0 else "2026-10-21T22:01:56+08:00"}
        (rdir/f"{ident}.json").write_text(json.dumps(receipt))
    (ep/tasks.STATE_REL).write_text(json.dumps({"snapshot_id":"snapshot-A",
        "tasks":{"CHARACTER_FINALIZE":{"task_id":t["task_id"],"status":"FAILED",
        "reason":"candidate missing status"}}}))
    return ep,t,cp,log,payload

def test_host_seals_all_metadata_and_preserves_original(tmp_path,monkeypatch):
    ep,t,cp,log,payload=case(tmp_path,monkeypatch,extra_turn=True)
    monkeypatch.setattr("agent_shadow_compare.compare_character_finalize_semantics",
                        lambda *args:{"pass":True,"errors":[]})
    before=cp.read_bytes()
    proof=recovery.inspect(ep,t)
    assert proof["status"]=="ELIGIBLE",proof
    assert proof["receipt_call_id"]=="receipt0"
    assert proof["log_end_offset"]<log.stat().st_size
    result=recovery.seal_verified(ep,t,proof)
    assert result["status"]=="PASS",result
    sealed=json.loads(cp.read_text("utf-8"))
    assert sealed["payload"]==payload
    assert sealed["source_authority_sha256"]==t["input_contract"]["source_authority_sha256"]
    assert sealed["authority_scope"]==["character.finalize"]
    assert sealed["status"]=="COMPLETED" and sealed["generated_at"]
    assert tasks.verify_candidate(sealed,t)==[]
    provenance=sealed["evidence"][0]
    assert (ep/provenance["original_candidate_path"]).read_bytes()==before
    assert provenance["host_bound_fields"]==[
        "generated_at","status","authority_scope","source_authority_sha256"]

@pytest.mark.parametrize("tamper",[
    "identity","receipt","mtime","writer","state","file_after_proof","log_after_proof"])
def test_host_recovery_fails_closed_for_stale_evidence(tmp_path,monkeypatch,tamper):
    ep,t,cp,log,_=case(tmp_path,monkeypatch,extra_turn=True)
    prior=recovery.inspect(ep,t)
    assert prior["status"]=="ELIGIBLE",prior
    if tamper=="identity":
        obj=json.loads(cp.read_text());obj["snapshot_id"]="wrong";cp.write_text(json.dumps(obj))
    elif tamper=="receipt":
        receipt=ep/"meta/provider-receipts/model-executions/receipt0.json"
        r=json.loads(receipt.read_text());r["status"]="FAILED";receipt.write_text(json.dumps(r))
    elif tamper=="mtime":
        stamp=datetime(2026,10,21,14,30,tzinfo=timezone.utc).timestamp()
        os.utime(cp,(stamp,stamp))
    elif tamper=="writer":
        log.write_text(log.read_text().replace("character-finalize.json","different.json"))
    elif tamper=="state":
        sp=ep/tasks.STATE_REL
        r=json.loads(sp.read_text());r["tasks"]["CHARACTER_FINALIZE"]["status"]="COMPLETED"
        sp.write_text(json.dumps(r))
    elif tamper=="file_after_proof":cp.write_text(cp.read_text()+" ")
    elif tamper=="log_after_proof":log.write_text(log.read_text()+"{}\n")
    result=recovery.seal_verified(ep,t,prior)
    assert result["status"]=="REFUSED",result
    assert not (ep/"meta/runtime/native-host-envelope-archive").exists()

def test_all_four_preimage_workers_reuse_without_dispatch(tmp_path,monkeypatch):
    ep,t,cp,log,_=case(tmp_path,monkeypatch,extra_turn=True)
    monkeypatch.setattr("agent_shadow_compare.compare_character_finalize_semantics",
                        lambda *args:{"pass":True,"errors":[]})
    snapshot={"snapshot_id":"snapshot-A"}
    others=[{"task_type":kind,"task_id":"done-"+kind,"status":"REUSED",
             "snapshot_id":"snapshot-A","candidate_output":"meta/runtime/preimage-candidates/"+kind}
            for kind in ("ENVIRONMENT_PREPARE","WORLD_PREPARE","VISUAL_NARRATIVE_PREPARE")]
    monkeypatch.setattr(preimage_protocol.preimage_authority_snapshot,"build",
                        lambda *a,**k:snapshot)
    monkeypatch.setattr(tasks,"plan_tasks",lambda *a,**k:[*others,t])
    states=[]
    monkeypatch.setattr(tasks,"update_task_state",
                        lambda ep,task,status,**kw:states.append((task["task_type"],status)))
    commits=[]
    monkeypatch.setattr(preimage_protocol,"commit_candidates",
                        lambda *a,**k:commits.append(True) or {"status":"PASS"})
    output=preimage_protocol.execute_local(ep,lambda task:pytest.fail("no new model calls"))
    assert output["status"]=="PASS"
    assert len(commits)==1
    assert ("CHARACTER_FINALIZE","REUSED") in states



def test_rc4_evidence_is_exact_latest_event_and_never_grants_paid_start(
    tmp_path,monkeypatch
):
    scripts = str(Path(__file__).resolve().parents[2] / "scripts")
    if scripts not in sys.path: sys.path.insert(0, scripts)
    import storyos_preimage_host_envelope_rc4_readonly as admission
    import runtime_driver
    import runtime_checkpoint
    import episode_state_persistence
    import preimage_authority_snapshot
    import storyos_driver_exit_remediation
    ep,char,cp,log,payload=case(tmp_path,monkeypatch,extra_turn=True)
    monkeypatch.setattr(admission,"ROOT",tmp_path)
    carrier=ep/"meta/runtime/driver-logs/driver_20261021_215446.log"
    carrier.parent.mkdir(parents=True)
    carrier.write_bytes(
        b"DRIVER TASK CARRIER pid=35204 task=StoryOSDriver-abc123\n"
        b"DRIVER EXIT rc=4 \n"
    )
    record={"pid":0,"episode":str(ep.resolve()),"carrier_task":"StoryOSDriver-abc123",
            "log":str(carrier.resolve()),"rc":"4 2026-10-21T22:05:55+08:00",
            "started_at":"2026-10-21T21:54:46+08:00",
            "exited_at":"2026-10-21T22:05:55+08:00"}
    driver={"record":record,"driver_state":"EXITED","exit_code":"4",
            "pid":0,"liveness":"DEAD","log":str(carrier.resolve())}
    monkeypatch.setattr(runtime_driver,"status",lambda _:driver)
    monkeypatch.setattr(episode_state_persistence,"load",
                        lambda _:{"current_state":"STORYBOARD_LOCKED"})
    checkpoint={"step_runs":[{
        "step":"PREIMAGE_COMPILE","status":"BLOCKED","returncode":4,
        "finished_at":"2026-10-21T22:05:54+08:00",
        "note":json.dumps({"status":"FAILED","tasks":[
            {"task_type":"CHARACTER_FINALIZE","status":"FAILED"}]})
    }]}
    monkeypatch.setattr(runtime_checkpoint,"load",lambda *a:checkpoint)
    trace=ep/"meta/runtime/trace-events.jsonl"
    trace.write_text(json.dumps({"event_type":"STEP_FAILED",
        "step":"PREIMAGE_COMPILE","failure_class":"4",
        "timestamp":"2026-10-21T22:05:54+08:00"})+"\n")
    snapshot={"snapshot_id":"snapshot-A"}
    monkeypatch.setattr(preimage_authority_snapshot,"build",lambda *a,**k:snapshot)
    monkeypatch.setattr(preimage_authority_snapshot,"stale_owned",lambda *a:False)
    other=[]
    state=json.loads((ep/tasks.STATE_REL).read_text("utf-8"))
    for kind in ("ENVIRONMENT_PREPARE","WORLD_PREPARE","VISUAL_NARRATIVE_PREPARE"):
        task={"task_type":kind,"task_id":"done-"+kind,
              "snapshot_id":"snapshot-A","status":"REUSED",
              "candidate_output":"meta/runtime/preimage-candidates/fake-"+kind}
        other.append(task)
        state["tasks"][kind]={"task_id":task["task_id"],"status":"COMPLETED"}
    (ep/tasks.STATE_REL).write_text(json.dumps(state))
    monkeypatch.setattr(tasks,"plan_tasks",lambda *a,**k:[*other,char])
    read_original=tasks.read_candidate
    monkeypatch.setattr(tasks,"read_candidate",lambda ep,t:(
        {"status":"COMPLETED"} if t["task_type"]!="CHARACTER_FINALIZE"
        else read_original(ep,t)))
    monkeypatch.setattr(tasks,"verify_candidate",lambda c,t:[])
    monkeypatch.setattr(storyos_driver_exit_remediation,"canonical_sha",lambda rec:"f"*64)
    good=admission.inspect(ep)
    assert good["status"]==admission.STATUS,good
    assert good["driver_record_sha256"]=="f"*64
    assert good["candidate_sha256"]==recovery.inspect(ep,char)["candidate_sha256"]
    assert good["model_calls"]==good["sql_writes"]==0
    assert good["production_authorization"] is False
    assert good["image_entitlement_verified"] is False

    checkpoint["step_runs"][0]["step"]="PRODUCTION"
    assert admission.inspect(ep)["status"]!=admission.STATUS
    checkpoint["step_runs"][0]["step"]="PREIMAGE_COMPILE"
    checkpoint["step_runs"][0]["note"]=json.dumps({"status":"FAILED","tasks":[
        {"task_type":"WORLD_PREPARE","status":"FAILED"},
        {"task_type":"CHARACTER_FINALIZE","status":"FAILED"}]})
    assert admission.inspect(ep)["status"]!=admission.STATUS
