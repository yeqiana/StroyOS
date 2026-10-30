"""An independent Model review must match actual final Controller and bundle hashes."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"episodes/_system"))
import production_ep14_independent_final_controller_evidence as mod


@pytest.fixture
def complete():
    frames=[]
    subjects=[]
    controller_rows=[]
    for frame in (9,29,48):
        row={
            "frame":f"{frame:02d}",
            "render_content_sha256":f"{frame:064x}",
            "frame_contract_sha256":"a"*64,
            "render_variant_sha256":"b"*64,
            "source_candidate_package_sha256":"c"*64,
            "scene_prompt":f"reviewed render scene {frame}",
            "frame_prompt_contract":f"DERIVED RENDER CONTRACT {frame}",
        }
        frames.append(row)
        controller_rows.append({
            "frame":frame,
            "decision":"APPROVE",
            "issues":[],
            "render_content_sha256":row["render_content_sha256"],
        })
        subjects.append({
            "frame":frame,
            "final_render_content_sha256":row["render_content_sha256"],
            "controller_decision":"APPROVE",
            "controller_issues":[],
            "scene_prompt":row["scene_prompt"],
            "render_contract":row["frame_prompt_contract"],
            "render_variant_sha256":row["render_variant_sha256"],
            "source_candidate_package_sha256":row["source_candidate_package_sha256"],
            "original_frame_contract_sha256":row["frame_contract_sha256"],
        })
    frozen={
        "final_render_bundle_sha256":mod.controller.BUNDLE,
        "frames":frames,
    }
    controller={
        "status":"FINAL_CONTROLLER_TEXT_OUTPUT_VERIFIED_NEEDS_INDEPENDENT_REVIEW",
        "reviewed_final_bundle_sha256":mod.controller.BUNDLE,
        "all_frames_controller_approved":True,
        "production_dispatch_authorized":False,
        "request_sha256":"d"*64,
        "runner_log_sha256":"e"*64,
        "frames":controller_rows,
    }
    req={
        "schema_version":"ep14_native_independent_final_controller_review_request_v1",
        "role":"independent.image.controller.review",
        "separate_runner_request":True,
        "final_render_bundle_sha256":mod.controller.BUNDLE,
        "controller_request_sha256":"d"*64,
        "controller_runner_log_sha256":"e"*64,
        "user_authorized_workflow":True,
        "production_dispatch_authorized":False,
        "image_generation_requested":False,
        "frames":subjects,
    }
    answer={
        "scope":mod.SCHEMA,
        "final_render_bundle_sha256":mod.controller.BUNDLE,
        "controller_runner_log_sha256":"e"*64,
        "production_dispatch_authorized":False,
        "frames":[{"frame":f,"render_content_sha256":f"{f:064x}",
                   "decision":"APPROVE","issues":[]} for f in (9,29,48)],
    }
    return frozen,controller,req,answer


def encode(req,answer):
    raw=("Instructions:\n"+mod.REQUEST_MARKER+
         json.dumps(req,ensure_ascii=False,sort_keys=True)).encode("utf8")
    events=[
        {"type":"thread.started","thread_id":"independent"},
        {"type":"turn.started"},
        {"type":"item.completed","item":{"type":"agent_message",
            "text":json.dumps(answer,ensure_ascii=False)}},
        {"type":"turn.completed"},
    ]
    out=("\n".join(json.dumps(x,ensure_ascii=False) for x in events)+"\n").encode("utf8")
    return raw,out


def validate(parts):
    frozen,controller,req,answer=parts
    raw,log=encode(req,answer)
    return mod.verify_bytes(frozen,controller,raw,log,strict_sha=False)


def test_second_native_review_still_requires_provider_and_activation(complete):
    result=validate(complete)
    assert result["status"]=="VERIFIED_INDEPENDENT_FINAL_CONTROLLER_REVIEW_NOT_PRODUCTION_ADMISSION"
    assert result["independent_final_review_approved"] is True
    assert result["production_dispatch_authorized"] is False
    assert result["provider_entitlement_verified"] is False
    assert result["paid_attempts_reserved"]==0


@pytest.mark.parametrize("drift",[
    "controller_not_approved","controller_log_changed",
    "controller_frame_not_approved","bad_request_bundle","not_separate_session",
    "bad_request_log_sha","user_auth_missing","dispatched",
    "image_generation_requested","review_source_scene_changed",
    "review_source_render_changed","review_source_frame_sha_changed",
    "model_wrong_log_sha","model_dispatch_granted","model_bad_frame_id",
    "model_wrong_frame_sha","model_extra_key","model_revise_without_issues",
    "model_approve_with_issues","model_tool_call","model_missing_turn",
])
def test_independent_result_cannot_forge_authority_or_source(complete,drift):
    frozen,controller,req,answer=deepcopy(complete)
    if drift=="controller_not_approved":
        controller["all_frames_controller_approved"]=False
    elif drift=="controller_log_changed":
        controller["runner_log_sha256"]="f"*64
    elif drift=="controller_frame_not_approved":
        controller["frames"][1]["decision"]="REVISE"
    elif drift=="bad_request_bundle":
        req["final_render_bundle_sha256"]="1"*64
    elif drift=="not_separate_session":
        req["separate_runner_request"]=False
    elif drift=="bad_request_log_sha":
        req["controller_runner_log_sha256"]="0"*64
    elif drift=="user_auth_missing":
        req["user_authorized_workflow"]=False
    elif drift=="dispatched":
        req["production_dispatch_authorized"]=True
    elif drift=="image_generation_requested":
        req["image_generation_requested"]=True
    elif drift=="review_source_scene_changed":
        req["frames"][0]["scene_prompt"]="forged"
    elif drift=="review_source_render_changed":
        req["frames"][0]["render_contract"]="wrong"
    elif drift=="review_source_frame_sha_changed":
        req["frames"][0]["final_render_content_sha256"]="0"*64
    elif drift=="model_wrong_log_sha":
        answer["controller_runner_log_sha256"]="3"*64
    elif drift=="model_dispatch_granted":
        answer["production_dispatch_authorized"]=True
    elif drift=="model_bad_frame_id":
        answer["frames"][1]["frame"]=9
    elif drift=="model_wrong_frame_sha":
        answer["frames"][1]["render_content_sha256"]="2"*64
    elif drift=="model_extra_key":
        answer["provider_entitlement_verified"]=True
    elif drift=="model_revise_without_issues":
        answer["frames"][0]["decision"]="REVISE"
    elif drift=="model_approve_with_issues":
        answer["frames"][0]["issues"]=["an issue"]
    raw,log=encode(req,answer)
    if drift=="model_tool_call":
        log=log.replace(b'"type": "agent_message"',b'"type": "function_call"')
    elif drift=="model_missing_turn":
        log=log.splitlines(keepends=True)[0]
    with pytest.raises(mod.IndependentDenied):
        mod.verify_bytes(frozen,controller,raw,log,strict_sha=False)


def test_independent_revise_is_honored_and_not_promoted(complete):
    frozen,controller,req,answer=deepcopy(complete)
    answer["frames"][2]["decision"]="REVISE"
    answer["frames"][2]["issues"]=["incorrect camera staging"]
    raw,log=encode(req,answer)
    result=mod.verify_bytes(frozen,controller,raw,log,strict_sha=False)
    assert result["independent_final_review_approved"] is False
    assert result["frames"][2]["decision"]=="REVISE"
    assert result["production_dispatch_authorized"] is False


def test_actual_request_hash_is_required(complete):
    frozen,controller,req,answer=complete
    raw,log=encode(req,answer)
    with pytest.raises(mod.IndependentDenied,match="REQUEST_SHA"):
        mod.verify_bytes(frozen,controller,raw,log)
