"""Read-only SHA-bound review of three provider-rejected Episode14 frames.
No generation, authority rewrite, automatic review PASS or new paid Attempt.
"""
from __future__ import annotations
import hashlib,json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
EP=ROOT/"episodes"/"00_独立篇"/"14_深渊疗愈所_第一集_净土生命还原"
DRAFT="meta/runtime/ep14-safety-content-revision-drafts-20261026.json"
FRAMES={9,29,48}
def sha(b): return hashlib.sha256(b).hexdigest()

def evaluate(draft,queue,prompts,contracts,first,states,driver):
    items=[x for x in queue.get("items",[]) if x.get("scope")=="batch"]
    errors=[]
    if (draft.get("type")!="NON_EXECUTABLE_SAFETY_CONTENT_REVISION_CANDIDATES"
        or draft.get("paid_attempts_authorized")!=0
        or len(draft.get("frames") or [])!=3
        or {int(x.get("frame") or 0) for x in draft.get("frames") or []}!=FRAMES):
        errors.append("DRAFT_SET_OR_AUTHORIZATION_DRIFT")
    if (len(items)!=44 or len({int(x["frame"]) for x in items})!=44
        or sum(x.get("status")=="generated" for x in items)!=41
        or {int(x["frame"]) for x in items if x.get("status")=="external_blocked"}!=FRAMES):
        errors.append("EXISTING_45_IMAGE_QUEUE_DRIFT")
    if (driver.get("driver_state")!="EXITED" or driver.get("liveness")!="DEAD"
        or int(driver.get("pid") or 0)!=0):
        errors.append("DRIVER_NOT_STOPPED")
    rows=[]
    for e in sorted(draft.get("frames") or [],key=lambda x:int(x.get("frame") or 0)):
        f=int(e.get("frame") or 0)
        if f not in FRAMES:continue
        matches=[x for x in items if int(x.get("frame") or 0)==f]
        item=matches[0] if len(matches)==1 else {}
        con=contracts.get(f) or {};old=first.get(f) or {};st=states.get(f) or {}
        problems=[]
        if (prompts.get(f) is None or sha(prompts[f])!=e.get("previous_prompt_sha256")):
            problems.append("ORIGINAL_PROMPT_SHA_MISMATCH")
        if (con.get("contract_sha256")!=e.get("locked_frame_contract_sha256")
            or (item.get("frame_contract") or {}).get("contract_sha256")!=e.get("locked_frame_contract_sha256")
            or (item.get("prompt_package") or {}).get("package_sha256")!=e.get("old_package_sha256")):
            problems.append("LOCKED_FRAME_OR_PROMPT_PACKAGE_DRIFT")
        if (item.get("status")!="external_blocked"
            or item.get("no_automatic_original_prompt_retry") is not True
            or item.get("requires_content_revision") is not True
            or not item.get("provider_safety_refusal_receipt_sha256")):
            problems.append("REFUSAL_QUEUE_GUARD_MISSING")
        if (old.get("status")!="FAILED_AFTER_DISPATCH"
            or old.get("failure_class")!="IMAGE_PROVIDER_SAFETY_REJECTED"
            or int(st.get("attempts_consumed") or 0)!=1
            or st.get("active_attempt_index") is not None
            or st.get("second_exists")):
            problems.append("FIRST_ATTEMPT_NOT_STRICTLY_TERMINAL")
        candidate=str(e.get("candidate_scene_prompt") or "")
        if len(candidate.strip())<65:problems.append("CANDIDATE_EMPTY")
        excerpt=(con.get("storyboard_frame") or {})
        if not excerpt.get("text"):problems.append("STORYBOARD_EXCERPT_MISSING")
        rows.append({
            "frame":f,"problems":problems,
            "status":"SOURCE_DRIFT_BLOCKED" if problems else "AWAITING_INDEPENDENT_REVIEW",
            "old_contract_sha256":e.get("locked_frame_contract_sha256"),
            "old_storyboard_excerpt_sha256":excerpt.get("sha256"),
            "candidate_prompt_sha256":sha(candidate.encode("utf8")),
            "candidate_scene_prompt":candidate,
            "narrative_intent":e.get("semantic_reason"),
            "blocked_root_cause":"OLD_LOCKED_STORYBOARD_STILL_IN_MODEL_PROMPT",
            "required":["independent_semantics_review",
                "new_render_contract_without_old_rejected_visual_description",
                "new_frame_contract_prompt_package_and_sha",
                "preserve_first_attempt_evidence",
                "explicit_paid_attempt_2_authorization"],
            "review_approved":False,"can_dispatch":False,
        })
    return {"schema_version":1,"status":(
        "SOURCE_DRIFT_BLOCKED" if errors or any(x["problems"] for x in rows)
        else "CONTENT_REVIEW_REQUIRED"),"errors":errors,"frames":rows,
        "existing_images":45 if not errors else None,
        "model_calls":0,"new_attempts":0,"sql_writes":0,"can_dispatch":False}

def compile_review(ep):
    ep=Path(ep).resolve()
    if ep!=EP.resolve():
        return {"status":"BLOCKED","reason":"WRONG_EPISODE","model_calls":0}
    import scheduler_core,frame_contract,logical_asset_identity
    import generation_attempt_authority as a
    import runtime_driver
    path=ep/DRAFT
    if not path.is_file():
        return {"status":"BLOCKED","reason":"NO_DRAFT","model_calls":0}
    d=json.loads(path.read_text("utf8"))
    prompts={};contracts={};first={};states={}
    for f in sorted(FRAMES):
        prompt=ep/"prompts/production"/f"{f:02d}.txt"
        if prompt.is_file():prompts[f]=prompt.read_bytes()
        contracts[f]=frame_contract.compile_frame(ep,f,write_cache=False)
        key=logical_asset_identity.frame_asset_key(ep,f)
        first[f]=a.load_attempt(ep,key,1) or {}
        states[f]=dict(a.load_asset_state(ep,key) or {})
        states[f]["second_exists"]=bool(a.load_attempt(ep,key,2))
    report=evaluate(d,scheduler_core.load_queue(ep),prompts,contracts,
                    first,states,runtime_driver.status(ep))
    report["draft_sha256"]=sha(path.read_bytes())
    report["report_sha256"]=sha(json.dumps(report,ensure_ascii=False,
        sort_keys=True,separators=(",",":")).encode("utf8"))
    return report

if __name__=="__main__":
    import sys
    print(json.dumps(compile_review(Path(sys.argv[1])),ensure_ascii=False,indent=2))
