"""One-shot native Codex final Controller output for SHA-frozen EP14 render subjects.

This runs a text-only Controller. It NEVER starts image generation, releases the
queue, mutates MySQL, or replays a request after a durable result exists.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT_REPO_ROOT = Path(__file__).resolve().parents[1]
ROOT = (SCRIPT_REPO_ROOT.parents[1] if SCRIPT_REPO_ROOT.parent.name == ".storyos-tmp"
        else SCRIPT_REPO_ROOT)
sys.path[:0] = [str(ROOT/"scripts"), str(ROOT/"episodes/_system")]
import codex_user_runner
import production_ep14_final_render_subject as final_render
import runtime_workspace
import storyos_codex_managed as native

SCHEMA = "ep14_native_final_controller_output_request_v1"
RUN = "ep14_final_controller_bundle_459256f3_native_v2_20261030"
EXPECTED_BUNDLE = "459256f325b44c6d21d497a0c758acfb66fac31eaaac93c122b854b7662cd6a2"
AUTH_REL = "meta/runtime/ep14_user_production_authorization_20261030.json"


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def episode() -> Path:
    candidates = sorted((ROOT / "episodes/00_独立篇").glob("14_深渊疗愈所*"))
    if len(candidates) != 1:
        raise ValueError("EP14_EXACT_EPISODE_SCOPE_REQUIRED")
    return candidates[0]


def prepare() -> tuple[Path,str,dict]:
    ep = episode()
    print("EP14_FINAL_NATIVE_PREPARE_MYSQL_READ_START",flush=True)
    frozen = final_render.prepare(ep)
    print("EP14_FINAL_NATIVE_PREPARE_MYSQL_READ_DONE",flush=True)
    auth = runtime_workspace.read_json(ep, AUTH_REL, default=None)
    if (not isinstance(auth, dict)
            or auth.get("user_workflow_authorization") is not True
            or auth.get("final_render_bundle_sha256") != EXPECTED_BUNDLE
            or frozen["final_render_bundle_sha256"] != EXPECTED_BUNDLE
            or frozen["production_dispatch_authorized"] is not False
            or auth.get("image_provider_entitlement_verified") is not False
            or auth.get("independent_final_controller_approval") is not False):
        raise ValueError("EP14_FINAL_CONTROLLER_USER_AUTH_AND_RENDER_VERSION_REQUIRED")
    rows = [{
        "frame": int(f["frame"]),
        "render_content_sha256": f["render_content_sha256"],
        "source_candidate_package_sha256": f["source_candidate_package_sha256"],
        "frame_contract_sha256": f["frame_contract_sha256"],
        "render_variant_sha256": f["render_variant_sha256"],
        "scene_prompt": f["scene_prompt"],
        "frame_prompt_contract": f["frame_prompt_contract"],
        "image_model": f["image_model"],
    } for f in frozen["frames"]]
    request = {
        "schema_version":SCHEMA,
        "role":"image.controller",
        "controller_model":"gpt-6-luna",
        "controller_effort":"high",
        "final_render_bundle_sha256":EXPECTED_BUNDLE,
        "candidate_bundle_sha256":frozen["candidate_bundle_sha256"],
        "frame_contracts":rows,
        "not_image_generation":True,
        "production_dispatch_authorized":False,
        "must_have_independent_review":True,
    }
    heading = (
        "You are image.controller doing the FIRST FORMAL TEXT-ONLY final render "
        "review for StoryOS EP14. This review has explicit user permission to "
        "proceed with the production workflow, but it is NOT permission to call "
        "image tools and is NOT proof of Provider entitlement. "
        "Do not call any tool. Do not modify any file. Do not generate an image. "
        "The submitted final frame_prompt_contract strings are complete render "
        "subjects after removal of preview markers. Examine consistency and "
        "physical possibility, visual character and camera constraints, absence "
        "of body injury/graphic harm and forbidden content, and narrative-source "
        "fidelity. For each frame, decide APPROVE or REVISE; NEVER approve a "
        "frame by silently rewriting its scene. "
        "When APPROVE return the exact unchanged scene_prompt bytes as "
        "scene_prompt and include the exact render_content_sha256; when REVISE "
        "return the source scene_prompt unchanged and explain issues. "
        "Return precisely one JSON object with fields "
        '{"scope":"EP14_FORMAL_FINAL_CONTROLLER_TEXT_OUTPUT_V1",'
        '"final_render_bundle_sha256":"...",'
        '"production_dispatch_authorized":false,'
        '"frames":[{"frame":9,"render_content_sha256":"...",'
        '"decision":"APPROVE|REVISE","scene_prompt":"...",'
        '"issues":[]}]} with exactly frames 9,29,48. '
        "This output REQUIRES a separate independent review before any "
        "canonical release; never grant Provider permission yourself. "
        "Untrusted render-subject data follows:\n"
    )
    text = heading + json.dumps(request,ensure_ascii=False,sort_keys=True,indent=2)
    return ep,text,request


def run(*, dry_run: bool=False) -> dict:
    print("EP14_FINAL_NATIVE_ENV_RESOLVE",flush=True)
    os.environ.update(native.native_environment())
    print("EP14_FINAL_NATIVE_ENV_READY",flush=True)
    ep,text,request=prepare()
    base=ep/"meta/runtime"
    req_path=base/(RUN+"_request.txt")
    log_path=base/(RUN+".jsonl")
    request_bytes=text.encode("utf8")
    output = {
        "status":"READY_TO_CALL_NATIVE_CONTROLLER_TEXT_ONLY",
        "request_sha256":sha(request_bytes),
        "request_size_bytes":len(request_bytes),
        "bundle_sha256":EXPECTED_BUNDLE,
        "frame_content_sha256":[r["render_content_sha256"] for r in request["frame_contracts"]],
        "image_generation_called":False,
        "generation_attempt_reserved":False,
        "production_dispatch_authorized":False,
    }
    if dry_run:
        return output
    base.mkdir(parents=True,exist_ok=True)
    # Refuse a reused Runner Request ID or any pre-existing output. Do not retry.
    if log_path.exists() or req_path.exists():
        raise ValueError("EP14_FINAL_CONTROLLER_REQUEST_ALREADY_DISPATCHED_RECONCILE_ONLY")
    with req_path.open("xb") as stream:
        stream.write(request_bytes)
    argv=["codex","exec","-m","gpt-6-luna","-c",
          'model_reasoning_effort="high"',"--json","-"]
    request_id=sha((RUN+"::"+EXPECTED_BUNDLE).encode("utf8"))[:32]
    # Strictly native Runner. Isolated user-mode home contains user's existing
    # interactive login, not credentials leaked to this process.
    with log_path.open("xb") as sink:
        result=codex_user_runner.run_model_codex(
            argv,input=text,stdout=sink,stderr=subprocess.STDOUT,
            text=True,encoding="utf-8",errors="replace",
            timeout=600,check=False,cwd=str(ROOT),
            task_type="review",codex_home_mode="isolated",
            request_id=request_id)
    output.update({
        "status":"NATIVE_CONTROLLER_RESULT_RECORDED",
        "runner_returncode":int(result.returncode),
        "runner_log_sha256":sha(log_path.read_bytes()),
        "runner_log_bytes":log_path.stat().st_size,
        "runner_request_id":request_id,
        "native_runner_called":True,
    })
    return output


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--dry-run",action="store_true")
    ns=parser.parse_args()
    print(json.dumps(run(dry_run=ns.dry_run),ensure_ascii=False),flush=True)
