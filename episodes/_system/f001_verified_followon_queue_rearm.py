"""One-shot F005/F045/F047 non-paying requeue after validated F001 baseline PASS.

The existing Worker performs a fresh text-only image tool visibility probe.
This operation only restores predispatch BLOCKED queue items, never reserves
paid Generation Attempts and never runs a provider.
"""
from __future__ import annotations
import argparse
import copy
import json
from pathlib import Path

import f001_independent_baseline_pass_cas as baseline_cas
import generation_attempt_authority as attempts
import logical_asset_identity as identity
import model_policy
import production_native_f001_reviewed_followon as followon
import scheduler_core

ROOT=Path(__file__).resolve().parents[2]
FRAMES=(5,45,47)
REASON="LOGIN_AUTH_IMAGE_TOOL_CAPABILITY_UNKNOWN"

class FollowonDenied(RuntimeError):pass
def deny(reason):raise FollowonDenied(reason)

def inspect(ep):
    ep=Path(ep).resolve()
    source=baseline_cas.inspect(ep)
    if source["current_status"] not in {"PASSED","LOCKED"}:
        deny("INDEPENDENT_BASELINE_NOT_CANONICALLY_PASSED")
    q=scheduler_core.load_queue(ep)
    payload=model_policy.resolve("image.payload",episode=ep)
    controller=model_policy.resolve("image.controller",episode=ep)
    proposed=copy.deepcopy(q)
    rows=[]
    for frame in FRAMES:
        current=next((r for r in q.get("items") or []
            if r.get("scope")=="visual_lock" and int(r.get("frame") or 0)==frame),None)
        if (not current or current.get("kind")!="original"
            or current.get("status")!="blocked"
            or current.get("technical_failure_code")!=REASON
            or not str(current.get("last_error") or "").startswith(REASON+":")
            or int(current.get("attempts") or 0)!=1
            or int(current.get("reviewed_baseline_followon_rearm_count") or 0)!=0):
            deny("DEPENDENT_FRAME_NOT_UNCONSUMED_PREFLIGHT_BLOCK")
        key=identity.frame_asset_key(ep,frame)
        st=attempts.load_asset_state(ep,key)
        if (st.get("attempts_consumed")!=0
            or st.get("active_attempt_index") is not None
            or attempts.load_attempt(ep,key,1)):
            deny("DEPENDENT_PAID_ATTEMPT_ALREADY_RESERVED")
        changing=next(x for x in proposed["items"] if x.get("id")==current.get("id"))
        changing["status"]="running"
        changing.pop("technical_failure_code",None)
        changing["last_error"]=None
        rows.append((frame,current["id"],current.get("last_error")))
    if not all(
        followon.eligible(ep,next(x for x in proposed["items"]
              if x.get("scope")=="visual_lock" and int(x["frame"])==frame),
              payload,controller,queue_override=proposed)
        for frame in FRAMES):
        deny("FRESH_F001_PROVENANCE_OR_FOLLOWON_POLICY_NOT_ELIGIBLE")
    return {"status":"FOLLOWON_THREE_PREDISPATCH_REQUEUE_ELIGIBLE",
        "ep":ep,"queue":q,"rows":rows,
        "proof_sha256":source["witness_sha"],
        "frames":list(FRAMES),"model_calls":0,"paid_attempts_reserved":0,
        "f001_attempts_consumed":2}

def commit(ep,*,proof_sha:str,ack=False):
    if not ack:deny("EXPLICIT_NO_EXTRA_F001_IMAGE_ACK_REQUIRED")
    ep=Path(ep).resolve()
    with scheduler_core.queue_transaction(ep):
        source=inspect(ep)
        if source["proof_sha256"]!=proof_sha:deny("REVIEW_REPORT_SHA_FENCE_CHANGED")
        q=scheduler_core.load_queue(ep)
        for frame,item_id,previous_error in source["rows"]:
            row=next(x for x in q["items"] if x.get("id")==item_id)
            if row.get("frame")!=frame or row.get("status")!="blocked":
                deny("QUEUE_CAS_CHANGED")
            row.update(status="queued",last_error=None,
                reviewed_baseline_followon_rearm_count=1,
                reviewed_baseline_followon_proof_sha256=proof_sha,
                reviewed_baseline_followon_previous_block=previous_error)
            row.pop("technical_failure_code",None)
            row.pop("external_block",None)
            row.pop("execution",None)
        scheduler_core.save_queue(ep,q)
        return {"status":"PASS","frames":list(FRAMES),
            "proof_sha256":proof_sha,"model_calls":0,"paid_attempts_reserved":0,
            "f001_attempts_consumed":2}

def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--episode",required=True)
    p.add_argument("--commit",action="store_true")
    p.add_argument("--ack-no-extra-f001-generation",action="store_true")
    p.add_argument("--expected-review-sha256")
    a=p.parse_args(argv)
    try:
        ep=Path(a.episode).resolve()
        if a.commit:
            out=commit(ep,proof_sha=a.expected_review_sha256 or "",
                ack=a.ack_no_extra_f001_generation)
        else:
            src=inspect(ep)
            out={k:src[k] for k in
                ("status","proof_sha256","frames","model_calls",
                 "paid_attempts_reserved","f001_attempts_consumed")}
    except Exception as exc:
        out={"status":"BLOCKED","reason":str(exc),"exception":type(exc).__name__}
    print(json.dumps(out,ensure_ascii=False,sort_keys=True))
    return 0 if out.get("status") in {"PASS","FOLLOWON_THREE_PREDISPATCH_REQUEUE_ELIGIBLE"} else 2
if __name__=="__main__":raise SystemExit(main())
