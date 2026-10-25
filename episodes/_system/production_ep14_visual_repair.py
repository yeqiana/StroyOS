"""One bounded Episode14 Visual Lock CONTENT repair wave after true pixel FAIL.

No general LOGIN_AUTH capability grants. Every repair has an original
MySQL SUCCEEDED paid Attempt #1 and a real independent actual-pixel FAIL.
The operator can only requeue existing predispatch-blocked rows, and each
image worker must repeat a native non-generating tool-visibility proof.
"""
from __future__ import annotations
import argparse,hashlib,json,re,sys
import platform as _stdlib_platform
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
_repo_platform=str(ROOT/"platform")
if not hasattr(_stdlib_platform,"__path__"):
    _stdlib_platform.__path__=[_repo_platform]
elif _repo_platform not in _stdlib_platform.__path__:
    _stdlib_platform.__path__.append(_repo_platform)
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
if str(ROOT/"scripts") not in sys.path:
    sys.path.insert(0,str(ROOT/"scripts"))
import episode_state_persistence
import frame_contract
import generation_attempt_authority as authority
import image_payload_transport
import logical_asset_identity as identity
import model_policy
import production_ledger_persistence as ledger_store
import runtime_driver
import runtime_request
import runtime_router
import scheduler_core
import storage_config
import visual_lock_baseline_gate as baseline
import production_native_baseline_proof as native

ROOT=Path(__file__).resolve().parents[2]
EPISODE="14_深渊疗愈所_第一集_净土生命还原"
FRAMES={5:"e5d1384d655e",45:"792802921372",47:"cea507d37802"}
ORIGINAL={1:"ead88592f160",5:"7fe4fd086543",45:"a1b0232cf35c",47:"f9f8fa8fa6ed"}
BLOCKS={5:"LOGIN_AUTH_IMAGE_TOOL_CAPABILITY_UNKNOWN",
        45:"IMAGE_CONTROLLER_OR_PAYLOAD_REQUEST_BLOCKED",
        47:"LOGIN_AUTH_IMAGE_TOOL_CAPABILITY_UNKNOWN"}
FLAG="native_ep14_repair_rearm_count"
ERROR="EP14_VISUAL_REPAIR_PROVENANCE_UNVERIFIED"
REVIEW="meta/visual-lock-admissions.json"
SOURCE="meta/visual-lock-critic-attempt-2.jsonl"

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def _is_sha(s):return isinstance(s,str) and bool(re.fullmatch(r"[0-9a-f]{64}",s))

def _allowed_target_ledger_status(status: str, *, blocked: bool) -> bool:
    # The scheduler already transitions to REPAIRING before image Worker
    # preflight. The historical blocked queue must remain TECH_FAILED.
    return status == "TECH_FAILED" if blocked else status in {"TECH_FAILED","REPAIRING"}


def eligible(ep,item,payload,controller,*,queue=None,blocked=False)->bool:
    try:
        ep=Path(ep).resolve()
        f=int(item.get("frame") or 0)
        if (ep!=(ROOT/"episodes"/"00_独立篇"/EPISODE).resolve()
            or f not in FRAMES or item.get("id")!=FRAMES[f]
            or item.get("kind")!="repair" or item.get("scope")!="repair"
            or item.get("model")!="gpt-image-2.5-flare"
            or item.get("quality")!="high"
            or item.get("output_path") or item.get("candidate_output_path")
            or payload.get("model")!="gpt-image-2.5-flare"
            or payload.get("quality")!="high"
            or controller.get("model")!="gpt-6-luna"
            or controller.get("reasoning_effort")!="high"):return False
        req=runtime_request.effective_for_episode(ep) or {}
        db=storage_config.mysql_connection_kwargs()
        if (req.get("mode")!="full_auto"
            or (req.get("runtime") or {}).get("execution_mode")!="dag"
            or runtime_router.image_execution_runtime()[0]!="CODEX"
            or (episode_state_persistence.load(ep) or {}).get("current_state")!="STORYBOARD_LOCKED"
            or db.get("host") not in {"localhost","127.0.0.1"}
            or int(db.get("port") or 0)!=13307
            or image_payload_transport.selected_route(1).get("provider")!="codex_subscription"
            or not baseline.approved(ep)):return False
        q=queue if queue is not None else scheduler_core.load_queue(ep)
        rows=q.get("items") or []
        originals={int(x.get("frame") or 0):x for x in rows
                   if x.get("scope")=="visual_lock" and x.get("kind")=="original"}
        repairs={int(x.get("frame") or 0):x for x in rows
                 if x.get("scope")=="repair" and x.get("kind")=="repair"}
        if (len(rows)!=8 or set(originals)!=set(ORIGINAL)
            or set(repairs)!={1,*FRAMES} or any(originals[n].get("id")!=iid
                  or originals[n].get("status")!="generated" for n,iid in ORIGINAL.items())
            or repairs[1].get("status")!="superseded"
            or any(repairs[n].get("id")!=iid for n,iid in FRAMES.items())):return False
        for n,row in repairs.items():
            if n==1:continue
            if (row.get("model")!="gpt-image-2.5-flare" or row.get("quality")!="high"
                or row.get("depends_on")!=[1]
                or row.get("frame_contract",{}).get("contract_sha256")
                    !=frame_contract.compile_frame(ep,n,write_cache=False)["contract_sha256"]
                or not (ep/row.get("prompt_file","")).is_file()
                    and not (ROOT/row.get("prompt_file","")).is_file()):return False
            if blocked:
                if (row.get("status")!="blocked"
                    or row.get("technical_failure_code")!=BLOCKS[n]
                    or not str(row.get("last_error") or "").startswith(BLOCKS[n]+":")
                    or int(row.get(FLAG) or 0)!=0
                    or int(row.get("attempts") or 0)!=1):return False
            else:
                permitted={"queued","running","generating"} if n==f else {
                    "queued","running","generating","generated","blocked"}
                if (row.get("status") not in permitted
                    or int(row.get(FLAG) or 0)!=1
                    or not _is_sha(row.get("native_repair_visibility_sha256"))
                    or not _is_sha(row.get("ep14_review_sha256"))):return False
        lp=ledger_store.load_authority(ep)
        frames=(lp or {}).get("frames") or {}
        review=ep/REVIEW;critic=ep/SOURCE
        if not review.is_file() or not critic.is_file():return False
        doc=json.loads(review.read_text(encoding="utf-8"))
        items=doc.get("items") or {}
        reviewsha=sha(review)
        if (not _is_sha(reviewsha)
            or frames.get("01",{}).get("status") not in {"PASSED","LOCKED"}):return False
        for n in (1,5,45,47):
            key=identity.frame_asset_key(ep,n)
            st=authority.load_asset_state(ep,key)
            idx=2 if n==1 else 1
            attempt=authority.load_attempt(ep,key,idx) or {}
            if (attempt.get("status")!="SUCCEEDED"
                or attempt.get("provider")!="codex_subscription"
                or attempt.get("generation_key")!=originals[n].get("generation_key")):
                return False
            # For a fresh target, its second paid Attempt must not exist.
            # Another sibling may concurrently consume its own second slot.
            if (blocked or n in {1,f}):
                if (st.get("attempts_consumed")!=idx
                    or st.get("active_attempt_index") is not None
                    or authority.load_attempt(ep,key,idx+1) is not None):
                    return False
            png=(ROOT/str(originals[n].get("output_path") or "")).resolve()
            if not png.is_relative_to(ep) or not png.is_file():return False
            original_sha=sha(png)
            row=frames.get(f"{n:02d}") or {}
            candidate=row.get("current_candidate") or {}
            if n==1:
                if original_sha!=candidate.get("sha256"):return False
                continue
            admission=next((a for a in items.values()
                            if int(a.get("frame") or 0)==n),{})
            witness=admission.get("provenance") or {}
            if (admission.get("status")!="FAIL"
                or admission.get("sha256")!=original_sha
                or admission.get("frame_contract_sha256")!=repairs[n]["frame_contract"]["contract_sha256"]
                or witness.get("review_capability")!="vision"
                or witness.get("review_scope")!="VISUAL_LOCK_DIRTY_ADMISSION"
                or witness.get("log")!=str((ep/SOURCE).relative_to(ROOT)).replace(chr(92),"/")
                or not (admission.get("review_row") or {}).get("issues")
                or int(row.get("content_repairs_used") or 0)!=1
                or repairs[n].get("source_artifact_sha256") not in (None,original_sha)):
                return False
            if n==f or blocked:
                # The scheduler transitions to REPAIRING before the Worker
                # rechecks native visibility. A blocked predispatch rearm
                # must still have the terminal TECH_FAILED state.
                if (not _allowed_target_ledger_status(row.get("status"),blocked=blocked)
                    or candidate.get("sha256")!=original_sha):
                    return False
            if not blocked and repairs[n].get("ep14_review_sha256")!=reviewsha:
                return False
        return True
    except Exception:return False

def inspect(ep):
    ep=Path(ep).resolve()
    p=model_policy.resolve("image.payload",episode=ep)
    c=model_policy.resolve("image.controller",episode=ep)
    q=scheduler_core.load_queue(ep)
    blocked=[x for x in q.get("items") or []
             if x.get("scope")=="repair" and int(x.get("frame") or 0) in FRAMES]
    if (len(blocked)!=3 or not all(eligible(ep,x,p,c,queue=q,blocked=True) for x in blocked)):
        return {"status":"BLOCKED","reason":ERROR}
    drv=runtime_driver.status(ep)
    if (drv.get("driver_state")!="EXITED" or str(drv.get("exit_code"))!="22"
        or drv.get("liveness")!="DEAD" or drv.get("pid")!=0):
        return {"status":"BLOCKED","reason":"DRIVER_NOT_STOPPED_RC22"}
    return {"status":"EP14_VISUAL_REPAIR_PREDISPATCH_REQUEUE_ELIGIBLE",
            "review_sha256":sha(ep/REVIEW),"frames":sorted(FRAMES),
            "new_paid_attempts":0,"f001_attempts_consumed":2}

def rearm(ep,*,ack=False):
    if not ack:return {"status":"BLOCKED","reason":"OPERATOR_ACK_REQUIRED"}
    ep=Path(ep).resolve()
    original=inspect(ep)
    if original["status"]!="EP14_VISUAL_REPAIR_PREDISPATCH_REQUEUE_ELIGIBLE":return original
    p=model_policy.resolve("image.payload",episode=ep)
    c=model_policy.resolve("image.controller",episode=ep)
    # Three separate non-image Codex session visibility attestations.
    import codex_subscription_image
    proofs={}
    for f in sorted(FRAMES):
        strict=codex_subscription_image.payload_capability_preflight(
            model=p["model"],quality=p["quality"])
        secondary=native.attest_secondary(strict,p,c,None)
        if secondary is None:
            return {"status":"BLOCKED","reason":"SECONDARY_IMAGE_TOOL_PROOF_MISSING",
                    "frame":f,"paid_attempts_reserved":0}
        proofs[f]=native.evidence_sha(secondary)
    try:
        with scheduler_core.queue_transaction(ep):
            new=inspect(ep)
            if new!=original:
                return {"status":"BLOCKED","reason":"QUEUE_OR_REVIEW_CHANGED"}
            q=scheduler_core.load_queue(ep)
            for row in q["items"]:
                n=int(row.get("frame") or 0)
                if row.get("scope")!="repair" or n not in FRAMES:continue
                row["status"]="queued"
                row[FLAG]=1
                row["native_repair_visibility_sha256"]=proofs[n]
                row["ep14_review_sha256"]=original["review_sha256"]
                row["ep14_previous_technical_block"]=str(row.get("last_error") or "")
                row["last_error"]=None
                row.pop("technical_failure_code",None)
                row.pop("execution",None)
            if not all(eligible(ep,x,p,c,queue=q) for x in q["items"]
                       if x.get("scope")=="repair" and int(x.get("frame") or 0) in FRAMES):
                return {"status":"BLOCKED","reason":"REARMED_WITNESS_FENCE_INVALID"}
            scheduler_core.save_queue(ep,q)
            return {"status":"PASS","frames":sorted(FRAMES),
                    "review_sha256":original["review_sha256"],
                    "new_provider_calls":0,"new_paid_attempts":0}
    except scheduler_core.QueueMutationBusy:
        return {"status":"BLOCKED","reason":"QUEUE_MUTATION_BUSY"}

def verify_rearmed(ep):
    ep=Path(ep).resolve()
    if ep!=(ROOT/"episodes"/"00_独立篇"/EPISODE).resolve():
        return {"status":"BLOCKED","reason":"WRONG_EPISODE"}
    p=model_policy.resolve("image.payload",episode=ep)
    c=model_policy.resolve("image.controller",episode=ep)
    q=scheduler_core.load_queue(ep)
    rows=[x for x in q.get("items") or []
          if x.get("scope")=="repair" and int(x.get("frame") or 0) in FRAMES]
    drv=runtime_driver.status(ep)
    if (len(rows)!=3
        or not all(eligible(ep,x,p,c,queue=q) for x in rows)
        or drv.get("driver_state")!="EXITED"
        or drv.get("liveness")!="DEAD"
        or drv.get("pid")!=0
        or str(drv.get("exit_code"))!="22"):
        return {"status":"BLOCKED","reason":"REARMED_REPAIR_SOURCE_OR_RC22_INVALID"}
    import storyos_driver_exit_remediation as exit_remediation
    stable=[{k:x.get(k) for k in ("id","frame","kind","status",
            FLAG,"native_repair_visibility_sha256","ep14_review_sha256",
            "prompt_package","frame_contract")} for x in rows]
    sha_queue=hashlib.sha256(json.dumps(stable,sort_keys=True,
        ensure_ascii=False,separators=(",",":")).encode("utf-8")).hexdigest()
    return {"status":"VISUAL_LOCK_RC22_EP14_REPAIR_REARMED",
            "driver_record_sha256":exit_remediation.canonical_sha(drv.get("record") or {}),
            "review_sha256":sha(ep/REVIEW),
            "repair_queue_sha256":sha_queue,
            "frames":sorted(FRAMES),
            "f001_attempts_consumed":2,
            "new_paid_attempts":0,"read_only":True,
            "production_authorization":False}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--episode",required=True)
    ap.add_argument("--commit",action="store_true")
    ap.add_argument("--verify-rearmed",action="store_true")
    ap.add_argument("--ack-no-extra-f001-generation",action="store_true")
    args=ap.parse_args()
    d=(verify_rearmed(args.episode) if args.verify_rearmed
       else rearm(args.episode,ack=args.ack_no_extra_f001_generation)
       if args.commit else inspect(args.episode))
    print(json.dumps(d,ensure_ascii=False,sort_keys=True))
    return 0 if d.get("status") in (
        "PASS","EP14_VISUAL_REPAIR_PREDISPATCH_REQUEUE_ELIGIBLE",
        "VISUAL_LOCK_RC22_EP14_REPAIR_REARMED") else 2
if __name__=="__main__":raise SystemExit(main())
