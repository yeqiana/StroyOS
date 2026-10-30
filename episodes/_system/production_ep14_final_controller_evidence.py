"""Verify the real native Final Controller transcript; never mint production authority."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import production_ep14_final_render_subject as final_render

SCHEMA = "EP14_FORMAL_FINAL_CONTROLLER_TEXT_OUTPUT_V1"
INPUT_MARKER = "Untrusted render-subject data follows:\n"
RUN = "ep14_final_controller_bundle_459256f3_native_v2_20261030"
BUNDLE = "459256f325b44c6d21d497a0c758acfb66fac31eaaac93c122b854b7662cd6a2"
REQUEST_SHA = "934d79bd1dbf3061c28e26843b997d536de9c29c7f506897d975a1e8832ed0bc"
FRAMES = {9,29,48}


class ControllerDenied(ValueError):
    pass


def _hex(value):
    return isinstance(value,str) and len(value)==64 and all(x in "0123456789abcdef" for x in value)


def _sha(data: bytes):
    return hashlib.sha256(data).hexdigest()


def _one_controller_text_turn(raw: bytes) -> dict:
    events=[]
    for row in raw.decode("utf8").splitlines():
        line=row.strip()
        if not line:continue
        try: item=json.loads(line)
        except json.JSONDecodeError:
            if line.startswith(("{","[")):
                raise ControllerDenied("NATIVE_CONTROLLER_MALFORMED_EVENT")
            continue
        if not isinstance(item,dict):
            raise ControllerDenied("NATIVE_CONTROLLER_NON_OBJECT_EVENT")
        events.append(item)
    if [x.get("type") for x in events] != [
        "thread.started","turn.started","item.completed","turn.completed"
    ]:
        raise ControllerDenied("NATIVE_CONTROLLER_NOT_EXACTLY_ONE_COMPLETED_TEXT_TURN")
    body=events[2].get("item")
    if not isinstance(body,dict) or body.get("type")!="agent_message":
        raise ControllerDenied("NATIVE_CONTROLLER_NON_TEXT_OR_TOOL_RESULT")
    try: answer=json.loads(body.get("text",""))
    except (ValueError,TypeError) as exc:
        raise ControllerDenied("NATIVE_CONTROLLER_RESPONSE_NOT_VALID_JSON") from exc
    if not isinstance(answer,dict):
        raise ControllerDenied("NATIVE_CONTROLLER_RESPONSE_NOT_OBJECT")
    return answer


def validate(frozen: dict, request_bytes: bytes, log_bytes: bytes,
             *, require_exact_request_sha:bool=True) -> dict:
    if (frozen.get("final_render_bundle_sha256")!=BUNDLE
            or frozen.get("production_dispatch_authorized") is not False
            or frozen.get("canonical_activation") is not False
            or frozen.get("final_controller_review_approved") is not False):
        raise ControllerDenied("FINAL_RENDER_SUBJECT_NOT_FROZEN")
    if require_exact_request_sha and _sha(request_bytes)!=REQUEST_SHA:
        raise ControllerDenied("NATIVE_CONTROLLER_REQUEST_SHA_CHANGED")
    try: raw=request_bytes.decode("utf8").replace("\r\n","\n")
    except UnicodeDecodeError as exc:raise ControllerDenied("REQUEST_NOT_UTF8") from exc
    if raw.count(INPUT_MARKER)!=1:
        raise ControllerDenied("REQUEST_UNTRUSTED_SUBJECT_AMBIGUOUS")
    try: req=json.loads(raw.split(INPUT_MARKER,1)[1])
    except json.JSONDecodeError as exc:
        raise ControllerDenied("NATIVE_CONTROLLER_REQUEST_BODY_INVALID") from exc
    if (not isinstance(req,dict)
            or req.get("schema_version")!="ep14_native_final_controller_output_request_v1"
            or req.get("role")!="image.controller"
            or req.get("controller_model")!="gpt-6-luna"
            or req.get("controller_effort")!="high"
            or req.get("final_render_bundle_sha256")!=BUNDLE
            or req.get("candidate_bundle_sha256")!=frozen.get("candidate_bundle_sha256")
            or req.get("not_image_generation") is not True
            or req.get("production_dispatch_authorized") is not False
            or req.get("must_have_independent_review") is not True):
        raise ControllerDenied("FINAL_CONTROLLER_INPUT_OR_TRANSPORT_IDENTITY_INVALID")
    expected={int(row["frame"]):row for row in frozen.get("frames") or []}
    supplied=req.get("frame_contracts") or []
    if (len(expected)!=3 or set(expected)!=FRAMES
            or not isinstance(supplied,list) or len(supplied)!=3
            or {x.get("frame") for x in supplied}!=FRAMES):
        raise ControllerDenied("FINAL_CONTROLLER_REQUIRED_THREE_FRAME_SET")
    identity=("frame_contract_sha256","render_variant_sha256",
              "render_content_sha256","source_candidate_package_sha256",
              "scene_prompt","frame_prompt_contract","image_model")
    for frame in supplied:
        source=expected[frame["frame"]]
        if any(frame.get(k)!=source.get(k) for k in identity):
            raise ControllerDenied(f"FINAL_CONTROLLER_FRAME_{frame['frame']:02d}_INPUT_CHANGED")
    answer=_one_controller_text_turn(log_bytes)
    if (set(answer)!={
            "scope","final_render_bundle_sha256",
            "production_dispatch_authorized","frames"}
            or answer["scope"]!=SCHEMA
            or answer["final_render_bundle_sha256"]!=BUNDLE
            or answer["production_dispatch_authorized"] is not False):
        raise ControllerDenied("FINAL_CONTROLLER_OUTPUT_SCOPE_OR_AUTHORITY_INVALID")
    decisions=answer["frames"]
    if not isinstance(decisions,list) or len(decisions)!=3 or \
            {x.get("frame") for x in decisions}!=FRAMES:
        raise ControllerDenied("FINAL_CONTROLLER_OUTPUT_FRAME_SET_INVALID")
    outcome=[]
    for row in sorted(decisions,key=lambda x:x["frame"]):
        frame=row["frame"]
        subject=expected[frame]
        if (set(row)!={"frame","render_content_sha256","decision","scene_prompt","issues"}
                or row["render_content_sha256"]!=subject["render_content_sha256"]
                or row["scene_prompt"]!=subject["scene_prompt"]
                or row["decision"] not in {"APPROVE","REVISE"}
                or not isinstance(row["issues"],list)
                or not all(isinstance(x,str) and x.strip() for x in row["issues"])
                or (row["decision"]=="APPROVE" and row["issues"])
                or (row["decision"]=="REVISE" and not row["issues"])):
            raise ControllerDenied(f"FINAL_CONTROLLER_FRAME_{frame:02d}_OUTPUT_NOT_BOUND")
        outcome.append({
            "frame":frame,"decision":row["decision"],
            "issues":row["issues"],
            "render_content_sha256":row["render_content_sha256"],
        })
    return {
        "status":"FINAL_CONTROLLER_TEXT_OUTPUT_VERIFIED_NEEDS_INDEPENDENT_REVIEW",
        "reviewed_final_bundle_sha256":BUNDLE,
        "request_sha256":_sha(request_bytes),
        "runner_log_sha256":_sha(log_bytes),
        "all_frames_controller_approved":all(x["decision"]=="APPROVE" for x in outcome),
        "frames":outcome,
        "independent_final_review_approved":False,
        "production_dispatch_authorized":False,
        "provider_entitlement_verified":False,
        "image_generation_called":False,
        "paid_attempts_reserved":0,
        "mysql_writes":0,
    }


def inspect(ep:Path):
    ep=Path(ep).resolve()
    base=ep/"meta/runtime"
    req=base/(RUN+"_request.txt")
    log=base/(RUN+".jsonl")
    if not req.is_file() or not log.is_file():
        raise ControllerDenied("FINAL_NATIVE_CONTROLLER_REQUEST_OR_LOG_NOT_FOUND")
    return validate(final_render.prepare(ep),req.read_bytes(),log.read_bytes())
