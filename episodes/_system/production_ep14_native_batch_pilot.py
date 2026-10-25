"""Exact Episode14 first Batch-native paid-attempt pilot; no bulk UNKNOWN bypass."""
from __future__ import annotations
import argparse,hashlib,json,re
from pathlib import Path
import episode_state_persistence as stage
import generation_attempt_authority as attempts
import image_payload_transport as transport
import logical_asset_identity as identity
import model_policy
import production_native_baseline_proof as native
import runtime_driver,runtime_request,runtime_router,scheduler_core,storage_config,story_json

ROOT=Path(__file__).resolve().parents[2]
EP=ROOT/"episodes"/"00_独立篇"/"14_深渊疗愈所_第一集_净土生命还原"
BATCH=set(range(1,49))-{1,5,45,47}
FAIL="LOGIN_AUTH_IMAGE_TOOL_CAPABILITY_UNKNOWN"
FLAG="native_single_batch_proof"
RECOVERY="VISUAL_LOCK_RC22_EP14_FIRST_BATCH_PILOT_RECOVERABLE"

def checked(ep,q,payload,controller,*,rearmed=False):
    try:
        ep=Path(ep).resolve()
        req=runtime_request.effective_for_episode(ep) or {}
        db=storage_config.mysql_connection_kwargs()
        gates=(story_json.read_json(ep/"meta/story-gates.json") or {}).get("reviews") or {}
        if (ep!=EP.resolve() or stage.load_with_source(ep)[1]!="mysql"
            or (stage.load(ep) or {}).get("current_state")!="VISUAL_CALIBRATED"
            or req.get("mode")!="full_auto" or (req.get("runtime") or {}).get("execution_mode")!="dag"
            or runtime_router.image_execution_runtime()[0]!="CODEX"
            or str(db.get("host")) not in {"127.0.0.1","localhost"}
            or not 1<=int(db.get("port") or 0)<=65535
            or transport.selected_route(1).get("provider")!="codex_subscription"
            or payload.get("model")!="gpt-image-2.5-flare" or payload.get("quality")!="high"
            or controller.get("model")!="gpt-6-luna" or controller.get("reasoning_effort")!="high"
            or gates.get("visual_admission")!="passed" or gates.get("story")!="passed"
            or len(q.get("items") or [])!=55):
            return None
        batch=[x for x in q["items"] if x.get("scope")=="batch"]
        if (len(batch)!=44 or len({x.get("id") for x in batch})!=44
            or {int(x.get("frame") or 0) for x in batch}!=BATCH):
            return None
        pilot=next(x for x in batch if int(x["frame"])==2)
        for row in batch:
            frame=int(row["frame"])
            if (row.get("kind")!="original" or row.get("model")!=payload["model"]
                or row.get("quality")!=payload["quality"]
                or row.get("output_path") or row.get("candidate_output_path")):
                return None
            if frame==2 and rearmed:
                if (row.get("status") not in {"queued","running","generating"} or row.get(FLAG) is not True
                    or row.get("native_batch_pilot_rearm_count")!=1
                    or not re.fullmatch(r"[0-9a-f]{64}",str(row.get("native_visibility_sha256") or ""))):
                    return None
            elif (row.get("status")!="blocked"
                  or row.get("technical_failure_code")!=FAIL
                  or not str(row.get("last_error") or "").startswith(FAIL+":")
                  or row.get(FLAG) is True):
                return None
            key=identity.frame_asset_key(ep,frame)
            s=attempts.load_asset_state(ep,key) or {}
            if (int(s.get("attempts_consumed") or 0)!=0
                or s.get("active_attempt_index") is not None
                or int(s.get("outcome_unknown_count") or 0)!=0
                or attempts.load_attempt(ep,key,1) is not None):
                return None
        old=[x for x in q["items"] if x.get("scope")!="batch"]
        if (len(old)!=11
            or {int(x["frame"]) for x in old if x.get("scope")=="visual_lock"
                and x.get("status")=="generated"}!={1,5,45,47}
            or len([x for x in old if x.get("kind")=="baseline_candidate"
                    and x.get("status")=="superseded"])!=3):
            return None
        return pilot
    except Exception:
        return None

def eligible(ep,item,payload,controller,*,queue=None,blocked=False):
    q=queue if queue is not None else scheduler_core.load_queue(ep)
    pilot=checked(ep,q,payload,controller,rearmed=not blocked)
    return bool(pilot and item.get("id")==pilot.get("id")
                and int(item.get("frame") or 0)==2)

def rearm_one(ep,*,acknowledged=False):
    ep=Path(ep).resolve()
    if not acknowledged:return {"status":"BLOCKED","reason":"ACK_REQUIRED"}
    payload=model_policy.resolve("image.payload",episode=ep)
    controller=model_policy.resolve("image.controller",episode=ep)
    try:
        with scheduler_core.queue_transaction(ep):
            p=checked(ep,scheduler_core.load_queue(ep),payload,controller)
            if p is None:return {"status":"BLOCKED","reason":"EXACT_44_PRE_DISPATCH_SOURCE_UNVERIFIED"}
            item_id=p["id"]
    except scheduler_core.QueueMutationBusy:
        return {"status":"BLOCKED","reason":"QUEUE_BUSY"}
    strict=transport.payload_capability_preflight(model=payload["model"],quality=payload["quality"])
    proof=native.attest_secondary(strict,payload,controller,None)
    if proof is None:return {"status":"BLOCKED","reason":"LIVE_NATIVE_TOOL_UNVERIFIED",
                              "new_model_calls":0,"new_paid_attempts":0}
    try:
        with scheduler_core.queue_transaction(ep):
            q=scheduler_core.load_queue(ep)
            row=checked(ep,q,payload,controller)
            if row is None or row["id"]!=item_id:
                return {"status":"BLOCKED","reason":"SOURCE_CHANGED"}
            row[FLAG]=True
            row["native_batch_pilot_rearm_count"]=1
            row["native_visibility_sha256"]=native.evidence_sha(proof)
            row["status"]="queued"
            row["last_error"]=None
            row.pop("technical_failure_code",None)
            scheduler_core.save_queue(ep,q)
        return {"status":"PASS","rearmed_frames":[2],"other_batch_frames_unchanged":43,
                "new_model_calls":0,"new_paid_attempts":0}
    except scheduler_core.QueueMutationBusy:
        return {"status":"BLOCKED","reason":"QUEUE_BUSY"}

def inspect_rc22(ep):
    import storyos_driver_exit_remediation as exit_tools
    ep=Path(ep).resolve()
    d=runtime_driver.status(ep)
    if (ep!=EP.resolve() or d.get("driver_state")!="EXITED"
        or d.get("liveness")!="DEAD" or d.get("pid")!=0
        or str(d.get("exit_code"))!="22"):
        return {"status":"BLOCKED","reason":"EXACT_RC22_NOT_DEAD"}
    rec=d.get("record") or {}
    log=Path(str(d.get("log") or "")).resolve()
    if (not log.is_relative_to((ep/"meta/runtime/driver-logs").resolve())
        or not log.is_file() or "DRIVER EXIT rc=22" not in log.read_text("utf-8",errors="replace")):
        return {"status":"BLOCKED","reason":"RC22_LOG_UNVERIFIED"}
    payload=model_policy.resolve("image.payload",episode=ep)
    controller=model_policy.resolve("image.controller",episode=ep)
    q=scheduler_core.load_queue(ep)
    row=checked(ep,q,payload,controller,rearmed=True)
    if row is None or row.get("status")!="queued":return {"status":"BLOCKED","reason":"PILOT_NOT_READY"}
    stable=[{k:x.get(k) for k in ("id","frame","scope","status","technical_failure_code",
         "output_path","native_single_batch_proof","native_visibility_sha256")}
        for x in q.get("items") or []]
    digest=hashlib.sha256(json.dumps(stable,sort_keys=True,ensure_ascii=False,
                      separators=(",",":")).encode("utf-8")).hexdigest()
    return {"status":RECOVERY,"driver_record_sha256":exit_tools.canonical_sha(rec),
            "queue_fingerprint":digest,"pilot_id":row["id"],
            "new_model_calls":0,"new_paid_attempts":0,
            "read_only":True,"production_authorization":False}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--episode",required=True)
    parser.add_argument("--verify-rearmed",action="store_true")
    parser.add_argument("--ack-real-production",action="store_true")
    a=parser.parse_args()
    result=(inspect_rc22(a.episode) if a.verify_rearmed else
            rearm_one(a.episode,acknowledged=a.ack_real_production))
    print(json.dumps(result,ensure_ascii=False))
    return 0 if result.get("status") in ("PASS",RECOVERY) else 2

if __name__=="__main__":raise SystemExit(main())
