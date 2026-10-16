#!/usr/bin/env python3
"""Single-frame native Codex Batch proof; never dispatches Provider itself."""
import argparse, hashlib, json
from pathlib import Path
import codex_user_runner, episode_state_persistence, generation_attempt_authority as attempts
import image_payload_transport, logical_asset_identity, model_policy
import production_native_baseline_proof as baseline
import runtime_request, runtime_router, scheduler_core, storage_config, story_json

ROOT=Path(__file__).resolve().parents[2]
FAILURE="LOGIN_AUTH_IMAGE_TOOL_CAPABILITY_UNKNOWN"
FLAG="native_single_batch_proof"

def _reviewed(ep,q):
    try:
        import visual_lock_baseline_gate
        visual=[r for r in q["items"] if r.get("scope")=="visual_lock"]
        report=story_json.read_json(ep/"meta/visual-lock-final-report.json")
        if (not visual_lock_baseline_gate.approved(ep) or report.get("decision")!="PASS"
            or len(visual)!=4 or {int(r["frame"]) for r in visual}!={1,3,8,18}
            or any(r.get("status")!="generated" for r in visual)): return False
        proof=story_json.read_json(ep/"meta/runtime/native-baseline-frame01-tool-proof.json")
        old=attempts.load_attempt(ep,logical_asset_identity.frame_asset_key(ep,1),2) or {}
        if (proof.get("proof_kind")!="TRUSTED_NATIVE_RUNNER_THREAD_SCOPED_IMAGE_SHA"
            or proof.get("attempt_index")!=2 or proof.get("provider_model_attested") is not False
            or old.get("status")!="SUCCEEDED" or old.get("provider")!="codex_subscription"
            or old.get("generation_key")!=proof.get("generation_key")): return False
        raw=list((ep/"media/raw").glob("01-*.png"))
        expected=str(proof.get("raw_png_sha256") or "")
        rid=str(proof.get("runner_request_id") or "")
        if len(rid)!=32 or any(c not in "0123456789abcdef" for c in rid.lower()):
            return False
        receipt=ROOT/"runtime/codex-user-runner/task-results"/(rid+".json")
        def sha(f): return hashlib.sha256(f.read_bytes()).hexdigest()
        matching=[p for p in raw if p.is_file() and sha(p)==expected]
        if len(matching)!=1 or matching[0].read_bytes()[:8]!=bytes.fromhex("89504e470d0a1a0a"):
            return False
        if not receipt.is_file() or sha(receipt)!=proof.get("runner_receipt_sha256"):
            return False
        record=json.loads(receipt.read_text(encoding="utf-8"))
        ev=record.get("evidence") or {}
        thread=str(proof.get("native_codex_thread_id") or "")
        artifact=str(proof.get("exported_artifact_relative_path") or "")
        if (record.get("request_id")!=rid or record.get("returncode")!=0
            or ev.get("request_id")!=rid or ev.get("returncode")!=0
            or ev.get("task_type")!="image" or ev.get("transport_route")!="native_codex"
            or ev.get("thread_ids")!=[thread] or ev.get("generated_artifacts")!=[artifact]):
            return False
        home,_=codex_user_runner.codex_home()
        base=(Path(home).resolve()/"generated_images").resolve()
        pixel=(base/artifact).resolve()
        if not pixel.is_relative_to(base): return False
        # A GC'd ephemeral cache cannot erase existing durable native provenance.
        return not pixel.is_file() or sha(pixel)==expected
    except Exception: return False

def eligible(ep,item,payload,controller,*,queue=None,blocked=False):
    try:
        ep=Path(ep).resolve()
        req=runtime_request.effective_for_episode(ep) or {}
        db=storage_config.mysql_connection_kwargs()
        if (ep.name!="13_失物归还的那扇门" or ep.parent.name!="00_独立篇"
            or not ep.is_relative_to(ROOT/"episodes")
            or (episode_state_persistence.load(ep) or {}).get("current_state")!="VISUAL_CALIBRATED"
            or req.get("mode")!="full_auto" or (req.get("runtime") or {}).get("execution_mode")!="dag"
            or runtime_router.image_execution_runtime()[0]!="CODEX"
            or str(db.get("host")) not in {"127.0.0.1","localhost"} or int(db.get("port") or 0)!=3307
            or image_payload_transport.selected_route(1).get("provider")!="codex_subscription"
            or payload.get("model")!="gpt-image-2.5-flare" or payload.get("quality")!="high"
            or controller.get("model")!="gpt-6-luna" or controller.get("reasoning_effort")!="high"
            or item.get("scope")!="batch" or item.get("kind")!="original"
            or item.get("model")!="gpt-image-2.5-flare"): return False
        q=queue if queue is not None else scheduler_core.load_queue(ep)
        rows=[r for r in q.get("items",[]) if r.get("scope")=="batch"]
        if len(rows)!=16 or len({r.get("id") for r in rows})!=16: return False
        first=min(rows,key=lambda r:int(r.get("frame") or 0))
        if item.get("id")!=first.get("id"): return False
        if any(r.get("status")!="blocked" or r.get("technical_failure_code")!=FAILURE
               for r in rows if r.get("id")!=first["id"]): return False
        current=next((r for r in rows if r.get("id")==first["id"]),{})
        if blocked:
            initial = (current.get("status")=="blocked"
                       and current.get("technical_failure_code")==FAILURE)
            # Legacy pre-dispatch user-Runner outage was misclassified as a
            # paid image backend error. A single explicitly acknowledged
            # recovery is allowed only with ZERO MySQL paid attempts below.
            legacy_runner_outage = (
                current.get("status")=="tech_failed"
                and current.get("technical_failure_code")=="IMAGE_BACKEND_ERROR"
                and str(current.get("last_error") or "")==
                    "LOGIN_AUTH_RUNNER_UNAVAILABLE: independent payload route unavailable; provider=codex_subscription"
                and current.get(FLAG) is True
                and 1 <= int(current.get("attempts") or 0) <= 2
                and int(current.get("native_pre_dispatch_rearm_count") or 0)==0
                and not current.get("output_path")
                and not current.get("candidate_output_path")
            )
            if not (initial or legacy_runner_outage): return False
        elif current.get("status") not in {"queued","running","generating"} or current.get(FLAG) is not True: return False
        state=attempts.load_asset_state(ep,logical_asset_identity.frame_asset_key(ep,int(item["frame"])))
        return (int(state.get("attempts_consumed") or 0)==0
                and state.get("active_attempt_index") is None and _reviewed(ep,q))
    except Exception: return False

def rearm_one(ep,*,acknowledged=False):
    """Two short locked checks with untrusted live Codex probe OUTSIDE lock."""
    ep=Path(ep).resolve()
    if not acknowledged: return {"status":"BLOCKED","reason":"ACK_REQUIRED"}
    payload=model_policy.resolve("image.payload",episode=ep)
    controller=model_policy.resolve("image.controller",episode=ep)
    try:
        with scheduler_core.queue_transaction(ep):
            q=scheduler_core.load_queue(ep)
            rows=[r for r in q.get("items",[]) if r.get("scope")=="batch"]
            if not rows: return {"status":"BLOCKED","reason":"NO_BATCH"}
            item=min(rows,key=lambda r:int(r.get("frame") or 0))
            if not eligible(ep,item,payload,controller,queue=q,blocked=True):
                return {"status":"BLOCKED","reason":"AUTHORITIES_UNVERIFIED"}
            item_id=item["id"]
    except scheduler_core.QueueMutationBusy:
        return {"status":"BLOCKED","reason":"QUEUE_MUTATION_BUSY"}
    # Never hold the queue lock over a model request or network timeout.
    try:
        strict=image_payload_transport.payload_capability_preflight(
            model=payload["model"],quality=payload["quality"])
        secondary=baseline.attest_secondary(strict,payload,controller,None)
    except Exception:
        return {"status":"BLOCKED","reason":"SESSION_PROBE_FAILED"}
    if secondary is None: return {"status":"BLOCKED","reason":"SESSION_TOOL_UNVERIFIED"}
    try:
        with scheduler_core.queue_transaction(ep):
            q=scheduler_core.load_queue(ep)
            current=next((r for r in q.get("items",[]) if r.get("id")==item_id),None)
            if current is None or not eligible(ep,current,payload,controller,queue=q,blocked=True):
                return {"status":"BLOCKED","reason":"AUTHORITIES_CHANGED"}
            if current.get("status")=="tech_failed":
                current["native_pre_dispatch_rearm_count"]=1
                current["native_pre_dispatch_rearm_source_attempts"]=int(current.get("attempts") or 0)
            current[FLAG]=True
            current["status"]="queued"
            current["last_error"]=None
            current.pop("technical_failure_code",None)
            current["native_visibility_sha256"]=baseline.evidence_sha(secondary)
            scheduler_core.save_queue(ep,q)
            return {"status":"PASS","rearmed_frames":[int(current["frame"])],
                    "other_batch_frames_unchanged":15,"provider_calls":0,"attempts_reserved":0}
    except scheduler_core.QueueMutationBusy:
        return {"status":"BLOCKED","reason":"QUEUE_MUTATION_BUSY"}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("episode_dir",type=Path)
    parser.add_argument("--ack-real-production",action="store_true")
    a=parser.parse_args()
    result=rearm_one(a.episode_dir,acknowledged=a.ack_real_production)
    print(json.dumps(result,ensure_ascii=False))
    return 0 if result["status"]=="PASS" else 2

if __name__=="__main__": raise SystemExit(main())
