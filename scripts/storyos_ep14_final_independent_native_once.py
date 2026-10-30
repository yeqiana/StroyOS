"""One-shot truly independent native Codex review of final Controller output.

The reviewer receives exact frozen final render text, hash-bound previous
Controller result and its native transcript SHA. It cannot activate images.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT_REPO_ROOT=Path(__file__).resolve().parents[1]
ROOT=(SCRIPT_REPO_ROOT.parents[1] if SCRIPT_REPO_ROOT.parent.name==".storyos-tmp"
      else SCRIPT_REPO_ROOT)
sys.path[:0]=[str(ROOT/"scripts"),str(ROOT/"episodes/_system")]
import storyos_codex_managed as native
import codex_user_runner
import production_ep14_final_render_subject as final_render

VALIDATOR_PATH=Path(__file__).resolve().parents[1]/"episodes/_system/production_ep14_final_controller_evidence.py"
spec=importlib.util.spec_from_file_location("isolated_ep14_controller_evidence",VALIDATOR_PATH)
controller_evidence=importlib.util.module_from_spec(spec)
spec.loader.exec_module(controller_evidence)

BUNDLE=controller_evidence.BUNDLE
SCHEMA="ep14_native_independent_final_controller_review_request_v1"
RUN="ep14_independent_final_controller_bundle_459256f3_native_v1_20261030"
REQUEST_MARKER="Untrusted final Controller evidence follows:\n"


def sha(b:bytes)->str:
    return hashlib.sha256(b).hexdigest()


def episode():
    eps=list((ROOT/"episodes/00_独立篇").glob("14_深渊疗愈所*"))
    if len(eps)!=1:raise ValueError("SINGLE_EP14_REQUIRED")
    return eps[0]


def prepare():
    ep=episode()
    proof=controller_evidence.inspect(ep)
    if (proof["status"]!="FINAL_CONTROLLER_TEXT_OUTPUT_VERIFIED_NEEDS_INDEPENDENT_REVIEW"
            or proof["all_frames_controller_approved"] is not True
            or proof["production_dispatch_authorized"] is not False):
        raise ValueError("CONTROLLER_NATIVE_FINAL_OUTPUT_NOT_READY_FOR_INDEPENDENT_REVIEW")
    final=final_render.prepare(ep)
    if final["final_render_bundle_sha256"]!=BUNDLE:
        raise ValueError("FINAL_RENDER_SHA_CHANGED_SINCE_NATIVE_CONTROLLER")
    ctx=[]
    for frame in final["frames"]:
        f=int(frame["frame"])
        result=next((row for row in proof["frames"] if row["frame"]==f),None)
        if not result or result["decision"]!="APPROVE":
            raise ValueError("CONTROLLER_FRAME_UNAPPROVED")
        ctx.append({
            "frame":f,
            "final_render_content_sha256":frame["render_content_sha256"],
            "controller_decision":result["decision"],
            "controller_issues":result["issues"],
            "scene_prompt":frame["scene_prompt"],
            "render_contract":frame["frame_prompt_contract"],
            "original_frame_contract_sha256":frame["frame_contract_sha256"],
            "render_variant_sha256":frame["render_variant_sha256"],
            "source_candidate_package_sha256":frame["source_candidate_package_sha256"],
        })
    request={
        "schema_version":SCHEMA,
        "role":"independent.image.controller.review",
        "separate_runner_request":True,
        "final_render_bundle_sha256":BUNDLE,
        "controller_request_sha256":proof["request_sha256"],
        "controller_runner_log_sha256":proof["runner_log_sha256"],
        "frames":ctx,
        "user_authorized_workflow":True,
        "production_dispatch_authorized":False,
        "image_generation_requested":False,
    }
    instruction=(
        "You are a SEPARATE independent reviewer from the final image "
        "Controller. Do not call tools, alter files or generate any images. "
        "Evaluate the actual APPROVE decisions from a completed native "
        "Controller task against the immutable final 3 frame render contracts. "
        "Challenge physical camera staging, safety, non-graphic presentation, "
        "unintentional historical-story or dialogue alterations and consistency. "
        "Check the controller's exact source scene and hash-bounded provenance, "
        "but do not blindly accept Controller decisions. "
        "You may return APPROVE or REVISE for each frame; REVISE requires "
        "nonempty concrete issues. Return exactly one JSON object "
        '{"scope":"EP14_INDEPENDENT_FINAL_CONTROLLER_OUTPUT_REVIEW_V1",'
        '"final_render_bundle_sha256":"...",'
        '"controller_runner_log_sha256":"...",'
        '"production_dispatch_authorized":false,'
        '"frames":[{"frame":9,"render_content_sha256":"...",'
        '"decision":"APPROVE|REVISE","issues":[]}]} '
        "with all three frame IDs. Even if all pass, only an independent "
        "evidence receipt is produced: no Provider entitlement or image "
        "authorization is granted by this model. Untrusted final Controller "
        "evidence follows:\n"
    )
    return ep,instruction+json.dumps(request,ensure_ascii=False,sort_keys=True,indent=2),request


def run(*,dry_run=False):
    os.environ.update(native.native_environment())
    ep,prompt,req=prepare()
    raw=prompt.encode("utf8")
    info={
        "status":"INDEPENDENT_NATIVE_CONTROLLER_REVIEW_READY",
        "request_sha256":sha(raw),
        "request_bytes":len(raw),
        "final_render_bundle_sha256":BUNDLE,
        "controller_runner_log_sha256":req["controller_runner_log_sha256"],
        "frames":[x["frame"] for x in req["frames"]],
        "production_dispatch_authorized":False,
        "image_generation_called":False,
        "paid_attempts_reserved":0,
    }
    if dry_run:return info
    req_path=ep/"meta/runtime"/(RUN+"_request.txt")
    log_path=ep/"meta/runtime"/(RUN+".jsonl")
    if req_path.exists() or log_path.exists():
        raise ValueError("INDEPENDENT_REVIEW_ALREADY_DISPATCHED_RECONCILE_FIRST")
    req_path.parent.mkdir(parents=True,exist_ok=True)
    with req_path.open("xb") as f:
        f.write(raw)
    request_id=sha((RUN+"::"+BUNDLE).encode("utf8"))[:32]
    with log_path.open("xb") as sink:
        proc=codex_user_runner.run_model_codex(
            ["codex","exec","-m","gpt-6-luna","-c",
             'model_reasoning_effort="high"',"--json","-"],
            input=prompt,stdout=sink,stderr=subprocess.STDOUT,
            timeout=600,check=False,cwd=str(ROOT),text=True,
            encoding="utf-8",errors="replace",task_type="review",
            codex_home_mode="isolated",request_id=request_id,
        )
    info.update({
        "status":"NATIVE_INDEPENDENT_CONTROLLER_REVIEW_RESULT_RECORDED",
        "runner_returncode":int(proc.returncode),
        "runner_request_id":request_id,
        "runner_log_sha256":sha(log_path.read_bytes()),
        "runner_log_bytes":log_path.stat().st_size,
    })
    return info


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--dry-run",action="store_true")
    args=parser.parse_args()
    print(json.dumps(run(dry_run=args.dry_run),ensure_ascii=False),flush=True)
