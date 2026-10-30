"""Final Controller evidence must be a native one-turn result on exact three SHAs."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"episodes/_system"))
import production_ep14_final_controller_evidence as proof


@pytest.fixture
def valid():
    frames=[]
    for f in (9,29,48):
        frames.append({
            "frame":f,"render_content_sha256":f"{f:064x}",
            "frame_contract_sha256":"a"*64,
            "render_variant_sha256":"b"*64,
            "source_candidate_package_sha256":"c"*64,
            "scene_prompt":f"safe final frame {f}",
            "frame_prompt_contract":f"DERIVED RENDER CONTRACT frame {f}",
            "image_model":{"model":"gpt-image-2.5-flare","quality":"high"},
        })
    frozen={
        "final_render_bundle_sha256":proof.BUNDLE,
        "candidate_bundle_sha256":"d"*64,
        "production_dispatch_authorized":False,
        "canonical_activation":False,
        "final_controller_review_approved":False,
        "frames":frames,
    }
    req={
        "schema_version":"ep14_native_final_controller_output_request_v1",
        "role":"image.controller","controller_model":"gpt-6-luna",
        "controller_effort":"high","final_render_bundle_sha256":proof.BUNDLE,
        "candidate_bundle_sha256":"d"*64,
        "not_image_generation":True,"production_dispatch_authorized":False,
        "must_have_independent_review":True,
        "frame_contracts":frames,
    }
    answer={
        "scope":proof.SCHEMA,
        "final_render_bundle_sha256":proof.BUNDLE,
        "production_dispatch_authorized":False,
        "frames":[{
            "frame":f["frame"],
            "render_content_sha256":f["render_content_sha256"],
            "decision":"APPROVE","scene_prompt":f["scene_prompt"],"issues":[],
        }for f in frames],
    }
    return frozen,req,answer


def encode(req,answer):
    req_bytes=("PROMPT\n"+proof.INPUT_MARKER+
               json.dumps(req,ensure_ascii=False,sort_keys=True)).encode("utf8")
    events=[
        {"type":"thread.started","thread_id":"thread-example"},
        {"type":"turn.started"},
        {"type":"item.completed","item":{
            "type":"agent_message","text":json.dumps(answer,ensure_ascii=False)}},
        {"type":"turn.completed","usage":{"input_tokens":200}},
    ]
    log=("\n".join(json.dumps(x,ensure_ascii=False) for x in events)+"\n").encode("utf8")
    return req_bytes,log


def call(valid):
    frozen,req,answer=valid
    a,b=encode(req,answer)
    return proof.validate(frozen,a,b,require_exact_request_sha=False)


def test_valid_sha_review_never_grants_production(valid):
    result=call(valid)
    assert result["status"]=="FINAL_CONTROLLER_TEXT_OUTPUT_VERIFIED_NEEDS_INDEPENDENT_REVIEW"
    assert result["all_frames_controller_approved"] is True
    assert result["production_dispatch_authorized"] is False
    assert result["independent_final_review_approved"] is False
    assert result["provider_entitlement_verified"] is False
    assert result["paid_attempts_reserved"]==0
    assert [r["frame"] for r in result["frames"]]==[9,29,48]


@pytest.mark.parametrize("bad",[
    "frozen_not_auth","changed_bundle","changed_candidate","model",
    "request_can_dispatch","source_scene_changed","request_missing_frame",
    "answer_wrong_bundle","answer_can_dispatch","answer_wrong_scene",
    "answer_wrong_sha","answer_duplicate_frame","answer_extra_key",
    "answer_revise_no_issues","answer_approve_with_issues",
    "answer_tool_call","answer_missing_complete","answer_malformed_json",
])
def test_all_tampered_source_or_output_fails_closed(valid,bad):
    frozen,req,answer=deepcopy(valid)
    if bad=="frozen_not_auth":
        frozen["canonical_activation"]=True
    elif bad=="changed_bundle":
        frozen["final_render_bundle_sha256"]="0"*64
    elif bad=="changed_candidate":
        req["candidate_bundle_sha256"]="e"*64
    elif bad=="model":
        req["controller_model"]="other"
    elif bad=="request_can_dispatch":
        req["production_dispatch_authorized"]=True
    elif bad=="source_scene_changed":
        req["frame_contracts"][0]["scene_prompt"]="old provider refused"
    elif bad=="request_missing_frame":
        req["frame_contracts"].pop()
    elif bad=="answer_wrong_bundle":
        answer["final_render_bundle_sha256"]="e"*64
    elif bad=="answer_can_dispatch":
        answer["production_dispatch_authorized"]=True
    elif bad=="answer_wrong_scene":
        answer["frames"][0]["scene_prompt"]="unsafe modified"
    elif bad=="answer_wrong_sha":
        answer["frames"][0]["render_content_sha256"]="f"*64
    elif bad=="answer_duplicate_frame":
        answer["frames"][1]["frame"]=9
    elif bad=="answer_extra_key":
        answer["safety_refusal_cleared"]=True
    elif bad=="answer_revise_no_issues":
        answer["frames"][0]["decision"]="REVISE"
    elif bad=="answer_approve_with_issues":
        answer["frames"][0]["issues"]=["issue"]
    req_bytes,log=encode(req,answer)
    if bad=="answer_tool_call":
        log=log.replace(b'"type": "agent_message"',b'"type": "tool_call"')
    elif bad=="answer_missing_complete":
        log=log.rsplit(b"\n",2)[0]+b"\n"
    elif bad=="answer_malformed_json":
        log=log.replace(b'"thread.started"',b'"thread.started')
    with pytest.raises(proof.ControllerDenied):
        proof.validate(frozen,req_bytes,log,require_exact_request_sha=False)


def test_revision_is_reported_and_not_marked_approved(valid):
    frozen,req,answer=deepcopy(valid)
    answer["frames"][1]["decision"]="REVISE"
    answer["frames"][1]["issues"]=["physical staging unclear"]
    raw,log=encode(req,answer)
    result=proof.validate(frozen,raw,log,require_exact_request_sha=False)
    assert result["all_frames_controller_approved"] is False
    assert result["frames"][1]["decision"]=="REVISE"
    assert result["production_dispatch_authorized"] is False


def test_request_sha_must_match_exact_persisted_native_request(valid):
    frozen,req,answer=deepcopy(valid)
    raw,log=encode(req,answer)
    with pytest.raises(proof.ControllerDenied,match="REQUEST_SHA"):
        proof.validate(frozen,raw,log)
