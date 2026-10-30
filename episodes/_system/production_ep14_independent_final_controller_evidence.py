"""Verify distinct independent native review against actual final Controller receipts."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import production_ep14_final_controller_evidence as controller
import production_ep14_final_render_subject as final_render

SCHEMA = "EP14_INDEPENDENT_FINAL_CONTROLLER_OUTPUT_REVIEW_V1"
REQUEST_MARKER = "Untrusted final Controller evidence follows:\n"
RUN = "ep14_independent_final_controller_bundle_459256f3_native_v1_20261030"
REQUEST_SHA = "587c1aa52f01dda6d402982c66849e71a96437338ec8d30f5f03f9b6c6e92cd7"
FRAMES = {9,29,48}


class IndependentDenied(ValueError):
    pass


def sha(raw:bytes)->str:
    return hashlib.sha256(raw).hexdigest()


def verify_bytes(frozen:dict,controller_proof:dict,request_raw:bytes,log_raw:bytes,
                 *,strict_sha=True)->dict:
    if (strict_sha and sha(request_raw)!=REQUEST_SHA):
        raise IndependentDenied("INDEPENDENT_REQUEST_SHA_CHANGED")
    if (frozen.get("final_render_bundle_sha256")!=controller.BUNDLE
            or controller_proof.get("status")!=
                "FINAL_CONTROLLER_TEXT_OUTPUT_VERIFIED_NEEDS_INDEPENDENT_REVIEW"
            or controller_proof.get("reviewed_final_bundle_sha256")!=controller.BUNDLE
            or controller_proof.get("all_frames_controller_approved") is not True
            or controller_proof.get("production_dispatch_authorized") is not False):
        raise IndependentDenied("CONTROLLER_SOURCE_NOT_NATIVE_VERIFIED")
    try: text=request_raw.decode("utf8").replace("\r\n","\n")
    except UnicodeDecodeError as exc:raise IndependentDenied("INDEPENDENT_REQUEST_NOT_UTF8") from exc
    if text.count(REQUEST_MARKER)!=1:
        raise IndependentDenied("INDEPENDENT_SUBJECT_MARKER_NOT_UNIQUE")
    try: req=json.loads(text.split(REQUEST_MARKER,1)[1])
    except json.JSONDecodeError as exc:raise IndependentDenied("INDEPENDENT_SOURCE_NOT_JSON") from exc
    if (req.get("schema_version")!="ep14_native_independent_final_controller_review_request_v1"
            or req.get("role")!="independent.image.controller.review"
            or req.get("separate_runner_request") is not True
            or req.get("final_render_bundle_sha256")!=controller.BUNDLE
            or req.get("controller_request_sha256")!=controller_proof.get("request_sha256")
            or req.get("controller_runner_log_sha256")!=controller_proof.get("runner_log_sha256")
            or req.get("user_authorized_workflow") is not True
            or req.get("production_dispatch_authorized") is not False
            or req.get("image_generation_requested") is not False):
        raise IndependentDenied("INDEPENDENT_SOURCE_AUTHORITY_MISMATCH")
    submitted=req.get("frames")
    current={int(x["frame"]):x for x in frozen.get("frames") or []}
    by_ctrl={x["frame"]:x for x in controller_proof.get("frames") or []}
    if (not isinstance(submitted,list) or len(submitted)!=3
            or {x.get("frame") for x in submitted}!=FRAMES
            or set(current)!=FRAMES or set(by_ctrl)!=FRAMES):
        raise IndependentDenied("INDEPENDENT_FRAME_SCOPE_INVALID")
    mapping=("render_content_sha256","scene_prompt","frame_prompt_contract",
             "render_variant_sha256","source_candidate_package_sha256")
    named={"render_content_sha256":"final_render_content_sha256",
           "frame_prompt_contract":"render_contract"}
    for x in submitted:
        f=x["frame"]; original=current[f]; prior=by_ctrl[f]
        if (x.get("controller_decision")!="APPROVE"
                or x.get("controller_issues")!=[]
                or prior["decision"]!="APPROVE"
                or prior["render_content_sha256"]!=original["render_content_sha256"]
                or x.get("original_frame_contract_sha256")!=original["frame_contract_sha256"]
                or any(x.get(named.get(k,k))!=original[k] for k in mapping)):
            raise IndependentDenied(f"INDEPENDENT_FRAME_{f:02d}_REVIEWED_CONTRACT_CHANGED")
    try: result=controller._one_controller_text_turn(log_raw)
    except controller.ControllerDenied as exc:
        raise IndependentDenied("INDEPENDENT_NATIVE_NON_TEXT_RESULT") from exc
    if (set(result)!={"scope","final_render_bundle_sha256",
                      "controller_runner_log_sha256","production_dispatch_authorized","frames"}
            or result["scope"]!=SCHEMA
            or result["final_render_bundle_sha256"]!=controller.BUNDLE
            or result["controller_runner_log_sha256"]!=controller_proof["runner_log_sha256"]
            or result["production_dispatch_authorized"] is not False):
        raise IndependentDenied("INDEPENDENT_RESULT_AUTHORITY_INVALID")
    decisions=result["frames"]
    if (not isinstance(decisions,list) or len(decisions)!=3
            or {x.get("frame") for x in decisions}!=FRAMES):
        raise IndependentDenied("INDEPENDENT_RESULT_FRAME_SET_INVALID")
    outcome=[]
    for x in sorted(decisions,key=lambda r:r["frame"]):
        f=x["frame"]
        if (set(x)!={"frame","render_content_sha256","decision","issues"}
                or x["render_content_sha256"]!=current[f]["render_content_sha256"]
                or x["decision"] not in {"APPROVE","REVISE"}
                or not isinstance(x["issues"],list)
                or not all(isinstance(v,str) and v.strip() for v in x["issues"])
                or (x["decision"]=="APPROVE" and x["issues"])
                or (x["decision"]=="REVISE" and not x["issues"])):
            raise IndependentDenied(f"INDEPENDENT_FRAME_{f:02d}_DECISION_MISMATCH")
        outcome.append({"frame":f,"decision":x["decision"],
                        "issues":x["issues"],"render_content_sha256":x["render_content_sha256"]})
    return {
        "status":"VERIFIED_INDEPENDENT_FINAL_CONTROLLER_REVIEW_NOT_PRODUCTION_ADMISSION",
        "final_render_bundle_sha256":controller.BUNDLE,
        "controller_runner_log_sha256":controller_proof["runner_log_sha256"],
        "independent_request_sha256":sha(request_raw),
        "independent_runner_log_sha256":sha(log_raw),
        "independent_final_review_approved":all(x["decision"]=="APPROVE" for x in outcome),
        "frames":outcome,
        "production_dispatch_authorized":False,
        "provider_entitlement_verified":False,
        "paid_attempts_reserved":0,
        "mysql_writes":0,
    }


def inspect(ep:Path)->dict:
    ep=Path(ep).resolve()
    base=ep/"meta/runtime"
    req=base/(RUN+"_request.txt")
    log=base/(RUN+".jsonl")
    if not req.is_file() or not log.is_file():
        raise IndependentDenied("NATIVE_INDEPENDENT_REQUEST_OR_LOG_NOT_PERSISTED")
    frozen=final_render.prepare(ep)
    proof=controller.inspect(ep)
    return verify_bytes(frozen,proof,req.read_bytes(),log.read_bytes())
