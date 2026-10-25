"""Episode14-only: one nonpaying recovery from an in-flight Ledger eligibility bug.

The prior queued repair was allowed at TECH_FAILED, but the Worker performed
its authority check after MySQL began REPAIRING. The old guard rejected every
legitimate repair before any paid Attempt was reserved. Keep that old block,
its counters, and original review/PNG intact. Never rearm twice.
"""
from __future__ import annotations
import argparse
import json
import sys
import platform as _stdlib_platform
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
_repo_platform=str(ROOT/"platform")
if not hasattr(_stdlib_platform,"__path__"):
    _stdlib_platform.__path__=[_repo_platform]
elif _repo_platform not in _stdlib_platform.__path__:
    _stdlib_platform.__path__.append(_repo_platform)
for entry in (ROOT,ROOT/"scripts"):
    if str(entry) not in sys.path:sys.path.insert(0,str(entry))

import generation_attempt_authority as ga
import logical_asset_identity as identity
import model_policy
import production_ep14_visual_repair as original
import runtime_driver
import scheduler_core

FRAME_SET=(5,45,47)
BLOCK="LOGIN_AUTH_IMAGE_TOOL_CAPABILITY_UNKNOWN"
MARK="ep14_inflight_ledger_bug_rearm_count"
ERROR="EP14_INFLIGHT_REPAIR_HISTORY_OR_SOURCE_NOT_ELIGIBLE"

def inspect(ep):
    ep=Path(ep).resolve()
    if ep!=(original.ROOT/"episodes"/"00_独立篇"/original.EPISODE).resolve():
        return {"status":"BLOCKED","reason":"WRONG_EPISODE"}
    d=runtime_driver.status(ep)
    if (d.get("driver_state")!="EXITED" or d.get("liveness")!="DEAD"
        or d.get("pid")!=0 or str(d.get("exit_code"))!="22"):
        return {"status":"BLOCKED","reason":"DRIVER_NOT_EXITED_RC22"}
    q=scheduler_core.load_queue(ep)
    reps=[x for x in q.get("items") or []
          if x.get("kind")=="repair" and int(x.get("frame") or 0) in FRAME_SET]
    if len(reps)!=3 or {int(x["frame"]) for x in reps}!=set(FRAME_SET):
        return {"status":"BLOCKED","reason":"REPAIR_SET_DRIFT"}
    reviewed=original.sha(ep/original.REVIEW)
    expected_visibility="86cb921fbbf79e955ff5128eb953049e35341168d4b5cf5c37bc8c23af3717b4"
    for x in reps:
        frame=int(x["frame"])
        state=ga.load_asset_state(ep,identity.frame_asset_key(ep,frame))
        if (x.get("id")!=original.FRAMES[frame]
            or x.get("status")!="blocked"
            or x.get("technical_failure_code")!=BLOCK
            or str(x.get("last_error") or "")!=
                BLOCK+": independent payload route unavailable; provider=codex_subscription"
            or int(x.get("attempts") or 0)!=2
            or x.get(original.FLAG)!=1
            or int(x.get(MARK) or 0)!=0
            or x.get("native_repair_visibility_sha256")!=expected_visibility
            or x.get("ep14_review_sha256")!=reviewed
            or state.get("attempts_consumed")!=1
            or state.get("remaining_attempts")!=1
            or state.get("active_attempt_index") is not None
            or ga.load_attempt(ep,identity.frame_asset_key(ep,frame),2) is not None):
            return {"status":"BLOCKED","reason":ERROR,"frame":frame}
    proposed=json.loads(json.dumps(q,ensure_ascii=False))
    for x in proposed["items"]:
        if x.get("kind")=="repair" and int(x.get("frame") or 0) in FRAME_SET:
            x["status"]="queued"
            x["technical_failure_code"]=None
            x["last_error"]=None
    payload=model_policy.resolve("image.payload",episode=ep)
    controller=model_policy.resolve("image.controller",episode=ep)
    if not all(original.eligible(ep,x,payload,controller,queue=proposed)
               for x in proposed["items"]
               if x.get("kind")=="repair" and int(x.get("frame") or 0) in FRAME_SET):
        return {"status":"BLOCKED","reason":"SOURCE_PROOF_OR_PAID_ATTEMPT_DRIFT"}
    return {
        "status":"EP14_INFLIGHT_LEDGER_REPAIR_ONE_SHOT_ELIGIBLE",
        "frames":list(FRAME_SET),
        "review_sha256":reviewed,
        "visibility_sha256":expected_visibility,
        "model_calls":0,"new_paid_attempts":0,"f001_attempts_consumed":2
    }

def commit(ep,*,expected_review_sha,ack=False):
    if not ack:return {"status":"BLOCKED","reason":"EXPLICIT_NO_THIRD_F001_ACK_REQUIRED"}
    ep=Path(ep).resolve()
    with scheduler_core.queue_transaction(ep):
        proof=inspect(ep)
        if proof.get("status")!="EP14_INFLIGHT_LEDGER_REPAIR_ONE_SHOT_ELIGIBLE":
            return proof
        if proof["review_sha256"]!=expected_review_sha:
            return {"status":"BLOCKED","reason":"REVIEW_SHA_CHANGED"}
        q=scheduler_core.load_queue(ep)
        for x in q["items"]:
            if x.get("kind")=="repair" and int(x.get("frame") or 0) in FRAME_SET:
                error=x["last_error"]
                x["status"]="queued"
                x["last_error"]=None
                x.pop("technical_failure_code",None)
                x.pop("execution",None)
                x[MARK]=1
                x["ep14_inflight_ledger_bug_prior_block"]=error
                x["ep14_inflight_ledger_bug_review_sha256"]=expected_review_sha
        scheduler_core.save_queue(ep,q)
        return {"status":"PASS","frames":list(FRAME_SET),
                "new_paid_attempts":0,"f001_attempts_consumed":2}

def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--episode",required=True)
    p.add_argument("--commit",action="store_true")
    p.add_argument("--ack-no-extra-f001-generation",action="store_true")
    p.add_argument("--expected-review-sha256")
    a=p.parse_args(argv)
    try:
        if a.commit:
            out=commit(a.episode,expected_review_sha=a.expected_review_sha256,
                       ack=a.ack_no_extra_f001_generation)
        else:out=inspect(a.episode)
    except Exception as e:
        out={"status":"BLOCKED","reason":str(e),"class":type(e).__name__}
    print(json.dumps(out,ensure_ascii=False,sort_keys=True))
    return 0 if out.get("status") in ("PASS","EP14_INFLIGHT_LEDGER_REPAIR_ONE_SHOT_ELIGIBLE") else 2

if __name__=="__main__":raise SystemExit(main())
