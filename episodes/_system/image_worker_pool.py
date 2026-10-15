#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Warm Python image worker adapter.

Reuses the scheduler Python process/module imports, but deliberately does NOT reuse Codex
conversation state. Current Codex transport remains ephemeral until the CLI exposes a safe
persistent image-generation daemon/session contract.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import uuid
from pathlib import Path

import codex_subscription_image as backend
import image_model_policy
import model_policy
import prompt_package
import runtime_trace
import raw_candidate_budget  # STORY_OS_V2_6_0_PERFORMANCE_RUNTIME
import runtime_circuit_breaker
import time
import runtime_router
import product_runtime_adapter
import resource_library
import production_recovery
import runtime_timeout_policy
import image_payload_controller
import image_payload_request
import image_payload_transport
import logical_asset_identity
import canvas_normalize
import global_image_capacity
import production_native_baseline_proof

MODE="python_warm_pool_codex_ephemeral"
CODEX_SESSION_REUSE=False

def model_policy_for_item(ep,item):
    episode_model_policy=image_model_policy.for_episode(ep)
    model=str(item.get("model") or episode_model_policy["model"])
    quality=str(item.get("quality") or episode_model_policy["quality"])
    return {**episode_model_policy,"model":model,"quality":quality,"strict_model":bool(item.get("strict_model",episode_model_policy.get("strict_model")))}

def generation_attempt_context(ep, item, payload_policy):
    """Capture the Episode-bound execution request before reserving an Attempt.

    These values describe the requested/bound execution context; they are not
    Provider confirmation.  The Attempt Authority persists this mapping in the
    durable row's CONTEXT before the Gateway can commit dispatch.
    """
    controller = model_policy.resolve("image.controller", episode=ep)
    payload = model_policy.resolve("image.payload", episode=ep)
    provider_candidate = str(item.get("provider_candidate") or item.get("provider") or "codex_subscription")
    runner_candidate = str(item.get("runner_candidate") or item.get("runner") or "codex_user_runner")
    return {
        "scope": item.get("scope"),
        "queue_item_id": item.get("id"),
        "production_revision_id": item.get("production_revision_id"),
        "frame_contract_sha256": (item.get("prompt_package") or {}).get("frame_contract_sha256"),
        "prompt_package_sha256": (item.get("prompt_package") or {}).get("package_sha256"),
        "generation_attempt_reason": item.get("generation_attempt_reason") or "PRIMARY_GENERATION",
        "technical_retry_source_code": item.get("technical_retry_source_code"),
        "model_role": "image.controller",
        "profile": controller.get("profile"),
        "controller_model": controller.get("model"),
        "controller_effort": controller.get("reasoning_effort"),
        "payload_model": str(payload_policy.get("model") or payload.get("model") or ""),
        "payload_quality": str(payload_policy.get("quality") or payload.get("quality") or ""),
        "model_policy_version": controller.get("policy_version"),
        "model_policy_sha256": controller.get("model_policy_sha256"),
        "provider": provider_candidate,
        "provider_candidate": provider_candidate,
        "runner_candidate": runner_candidate,
        "controller_model_source": "EPISODE_BOUND_RUNTIME_POLICY",
        "payload_model_source": "EXPLICIT_RUNTIME_BINDING",
    }


def _payload_reference_evidence(ep: Path, root: Path, refs: list[Path],
                                declarations: list[dict] | None = None) -> list[dict]:
    rows = []
    if declarations is not None and len(declarations) != len(refs):
        raise ValueError("IMAGE_PAYLOAD_REFERENCE_DECLARATION_COUNT_MISMATCH")
    for index, path in enumerate(refs):
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(root.resolve()).as_posix()
        except ValueError as exc:
            raise ValueError("IMAGE_PAYLOAD_REFERENCE_OUTSIDE_REPOSITORY") from exc
        if not resolved.is_file():
            raise ValueError("IMAGE_PAYLOAD_REFERENCE_MISSING")
        digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
        if declarations is not None:
            declared = declarations[index]
            if not isinstance(declared, dict):
                raise ValueError("IMAGE_PAYLOAD_REFERENCE_DECLARATION_INVALID")
            if str(declared.get("path") or "") != relative:
                raise ValueError("IMAGE_PAYLOAD_REFERENCE_DECLARED_PATH_MISMATCH")
            expected_sha = str(declared.get("sha256") or "").lower()
            if expected_sha and expected_sha != digest:
                raise ValueError("IMAGE_PAYLOAD_REFERENCE_SOURCE_SHA_DRIFT")
        reference = {"path": relative, "authority_id": None, "sha256": digest}
        if declarations is not None:
            for key in ("kind", "role"):
                value = declarations[index].get(key)
                if value is not None:
                    reference[key] = value
        rows.append(reference)
    return rows


def _canonical_controller_request(ep: Path, item: dict, package: dict,
                                  prompt_path: Path, refs: list[Path],
                                  visual: dict, width: int, height: int,
                                  aspect: str, timeout: int, codex: str | None) -> dict:
    root = Path(__file__).resolve().parents[2]
    frame = int(item["frame"])
    scene = str(package.get("scene_prompt") or "").strip()
    frame_prompt = str(package.get("frame_prompt_contract") or "").strip()
    visual_text = str(visual.get("text") or "").strip()
    if not scene or not frame_prompt or not visual_text:
        raise ValueError("IMAGE_PAYLOAD_SOURCE_CONTRACT_MISSING")
    reference_evidence = _payload_reference_evidence(
        ep, root, refs, declarations=item.get("references") or [])
    canonical_data = {
        "scene_prompt_sha256": package.get("scene_prompt_sha256"),
        "frame_contract_sha256": package.get("frame_contract_sha256"),
        "frame_prompt_contract": frame_prompt,
        "visual_profile_sha256": visual.get("profile_sha256"),
        "visual_contract": visual_text,
        "references": reference_evidence,
    }
    if package.get("m00_adjacent_state_delta_sha256") is not None:
        canonical_data["m00_adjacent_state_delta_sha256"] = package["m00_adjacent_state_delta_sha256"]
    canonical = json.dumps(canonical_data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    authority_sha = hashlib.sha256(canonical).hexdigest()
    visual_sha = hashlib.sha256(json.dumps({
        "profile_sha256": visual.get("profile_sha256"),
        "capture_grammar": visual.get("capture_grammar"),
        "text": visual_text,
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    controller_fields = {
        "source_scene_prompt": scene,
        "frame_prompt_contract": frame_prompt,
        "visual_contract": visual_text,
        "storyboard_source": package.get("storyboard_source") or {},
        "source_prompt_path": prompt_path.relative_to(root).as_posix(),
    }
    if package.get("m00_adjacent_state_delta") is not None or package.get("m00_adjacent_state_delta_sha256") is not None:
        controller_fields["m00_adjacent_state_delta"] = package.get("m00_adjacent_state_delta")
        controller_fields["m00_adjacent_state_delta_sha256"] = package.get("m00_adjacent_state_delta_sha256")
    request_result = image_payload_controller.build_payload_request(
        ep,
        logical_asset_key=logical_asset_identity.frame_asset_key(ep, frame),
        frame_id=f"{frame:02d}",
        authority_input_sha256=authority_sha,
        source_prompt_sha256=str(package.get("scene_prompt_sha256") or ""),
        frame_contract_sha256=str(package.get("frame_contract_sha256") or ""),
        visual_contract_sha256=visual_sha,
        canvas={"width": int(width), "height": int(height), "aspect_ratio": str(aspect)},
        references=reference_evidence,
        controller_input=controller_fields,
        codex_raw=codex,
        timeout=timeout,
        run_id=str(item.get("run_id") or ""),
        trace_id=str(item.get("trace_id") or ""),
    )
    request = request_result.get("request") if isinstance(request_result, dict) else None
    errors = image_payload_request.validate_request(request or {})
    if errors:
        raise ValueError("IMAGE_PAYLOAD_REQUEST_INVALID:" + ",".join(errors))
    return {**request_result, "reference_paths": refs}

# Every canonical image worker shares five machine-wide Provider slots.
# ContextDecorator acquires before this function can reserve any Attempt.
def execute(ep,item,timeout,codex):
    # Claim before Controller/Provider execution and MySQL Attempt reserve.
    with global_image_capacity.image_permits(1):
        resource_library.ensure_fresh(ep)
        runtime,_=runtime_router.detect()
        image_runtime,_=runtime_router.image_execution_runtime()
        if runtime in {"WORK","WEB"} and not codex and image_runtime != "CODEX":
            request=product_runtime_adapter.build_image_request(
                ep,runtime=runtime,queue_items=[item],source="image_worker_pool")
            return {
                "returncode":product_runtime_adapter.HOST_ACTION_REQUIRED_RC,
                "stdout":"HOST_ACTION_REQUIRED: product runtime image generation required; Codex image execution is not selected",
                "payload":{"product_runtime_request":request},
                "output":None,"log":None,"attempt":max(1,int(item.get("attempts") or 1)),"scout":None,
                "worker_pool":{"mode":"product_runtime_host","codex_session_reuse":False},
            }
        frame=int(item["frame"]); attempt=max(1,int(item.get("attempts") or 1))
        out=ep/"media/candidates/scheduled"/f"{frame:02d}-{item['id']}-a{attempt}.png"
        log=ep/"meta/image-workers"/f"{frame:02d}-{item['id']}-a{attempt}.jsonl"
        out.parent.mkdir(parents=True,exist_ok=True); log.parent.mkdir(parents=True,exist_ok=True)
        production_recovery.write_lifecycle(ep, item, "WORKER_STARTED", worker_pid=os.getpid(),
                                            expected_output=str(out), expected_log=str(log))
        root=Path(__file__).resolve().parents[2]
        prompt=(root/item["prompt_file"]).resolve()
        refs=[(root/x["path"]).resolve() for x in item.get("references") or []]
        effective_model_policy=model_policy_for_item(ep,item)
        model=str(effective_model_policy["model"])
        quality=str(effective_model_policy["quality"])
        package=prompt_package.compile_frame(ep,frame,prompt,write=True)
        visual=backend.compile_prompt_contract(ep)
        blocked=runtime_circuit_breaker.blocking(ep,"image")
        if blocked:
            result={"returncode":97,"stdout":"RUNTIME_CIRCUIT_OPEN: "+str(blocked),"payload":None,"output":None,"log":log,"attempt":attempt,"scout":None}
            production_recovery.write_lifecycle(ep, item, "FAILED", worker_pid=os.getpid(), error=result["stdout"], result=result)
            return result

        # The image Controller is a text-only, Episode-policy-bound step. It emits
        # the canonical prompt request before the independent Pixel route is checked.
        try:
            width,height,aspect=canvas_normalize.read_canvas(ep)
            controller_result = _canonical_controller_request(
                ep,item,package,prompt,refs,visual,width,height,aspect,timeout,codex)
            canonical_request=controller_result["request"]
        except Exception as exc:
            message=f"IMAGE_CONTROLLER_OR_PAYLOAD_REQUEST_BLOCKED: {type(exc).__name__}: {str(exc)[:500]}"
            result={"returncode":93,"stdout":message,"payload":None,"output":None,
                    "log":log,"attempt":attempt,"scout":None,
                    "image_attempt_reserve_called":False}
            production_recovery.write_lifecycle(ep,item,"BLOCKED",worker_pid=os.getpid(),error=message,result=result)
            return result
        # Provider selection is configuration-authoritative. Preflight the selected
        # transport before reserving an image Attempt so an unavailable login/API
        # lane cannot burn generation budget.
        payload_policy = model_policy.resolve("image.payload", episode=ep)
        controller_policy = model_policy.resolve("image.controller", episode=ep)
        phase5a_grant_evidence = backend.consume_phase5a_payload_dispatch_grant(
            ep, item,
            payload_model=str(payload_policy.get("model") or ""),
            payload_quality=str(payload_policy.get("quality") or ""),
            policy_sha256=str(controller_policy.get("model_policy_sha256") or ""),
        )
        if phase5a_grant_evidence is not None:
            # The dedicated Phase 5A harness already completed the same live,
            # non-generating session-start attestation. Reuse that evidence once;
            # never turn UNKNOWN into a general production PASS.
            payload_preflight = phase5a_grant_evidence
        else:
            payload_preflight = image_payload_transport.payload_capability_preflight(
                model=str(payload_policy.get("model") or ""),
                quality=str(payload_policy.get("quality") or ""),
                codex_raw=codex,
                proof_transport_model=str(controller_policy.get("model") or ""),
                proof_transport_effort=str(controller_policy.get("reasoning_effort") or ""),
            )
        # Strict preflight stays the default. One narrowly scoped, one-time
        # production baseline proof may use a second *non-generating* native
        # visibility attestation before reserving the canonical MySQL Attempt.
        # This is not Phase5A (which remains TEST_ONLY) and not a blanket PASS.
        native_baseline_probe = None
        if (phase5a_grant_evidence is None
                and production_native_baseline_proof.eligible(
                    ep, item, payload_policy, controller_policy)):
            native_baseline_probe = production_native_baseline_proof.attest_secondary(
                payload_preflight, payload_policy, controller_policy, codex)
            if native_baseline_probe is not None:
                payload_preflight = native_baseline_probe
        payload_preflight_status = str(payload_preflight.get("status") or "")
        payload_gate_pass = (
            payload_preflight_status == "PASS"
            or (payload_preflight_status == "READY_FOR_REAL_CAPABILITY_PROOF"
                and payload_preflight.get("phase5a_dispatch_grant_consumed") is True
                and phase5a_grant_evidence is not None
                and payload_preflight.get("image_generation_called") is False
                and payload_preflight.get("image_attempt_authority_called") is False)
            or (native_baseline_probe is not None
                and payload_preflight_status == "READY_FOR_REAL_CAPABILITY_PROOF"
                and payload_preflight.get("image_generation_called") is False
                and payload_preflight.get("image_attempt_authority_called") is False)
        )
        if not payload_gate_pass:
            code=str(payload_preflight.get("failure_class") or "NO_AUTOMATABLE_IMAGE_PAYLOAD_PROVIDER")
            message=f"{code}: independent payload route unavailable; provider={payload_preflight.get('provider')}"
            result={"returncode":94,"stdout":message,"payload":None,"output":None,
                    "log":log,"attempt":attempt,"scout":None,
                    "payload_preflight":payload_preflight,"image_attempt_reserve_called":False}
            production_recovery.write_lifecycle(ep,item,"BLOCKED",worker_pid=os.getpid(),error=message,result=result)
            return result
        budget_kind=raw_candidate_budget.kind_for_queue_item(item)
        budget_token=str(item["id"])
        budget_semantic_key=raw_candidate_budget.semantic_key_for_queue_item(item)
        selected_provider = str(payload_preflight.get("provider") or "")
        selected_runner = str(
            payload_preflight.get("runner")
            or ("codex_user_runner" if selected_provider == "codex_subscription"
                else "python-openai-images-http" if selected_provider == "openai_images_api"
                else selected_provider)
        )
        attempt_context = generation_attempt_context(ep, item, effective_model_policy)
        attempt_context.update({
            "provider": selected_provider,
            "provider_candidate": selected_provider,
            "runner": selected_runner,
            "runner_candidate": selected_runner,
            "transport_model": payload_preflight.get("transport_model"),
            "transport_effort": payload_preflight.get("transport_effort"),
            "controller_receipt_id": controller_result.get("controller_call_id"),
            "controller_output_sha256": canonical_request.get("controller_output_sha256"),
            "payload_request_fingerprint": canonical_request.get("request_fingerprint"),
        })
        if native_baseline_probe is not None:
            attempt_context.update({
                "image_capability_proof_purpose": production_native_baseline_proof.REASON,
                "native_visibility_evidence_sha256": production_native_baseline_proof.evidence_sha(
                    native_baseline_probe),
                "visual_lock_frame": 1,
                "tool_capability_claim": "UNKNOWN_NOT_YET_PROVEN",
            })
        budget_ok,budget_row=raw_candidate_budget.claim(ep,frame,budget_kind,reason=f"formal_generation_entrypoint scope={item.get('scope')} attempt={attempt}",token=budget_token,semantic_key=budget_semantic_key,
            generation_context=attempt_context)
        if not budget_ok:
            result={"returncode":98,"stdout":"RAW_CANDIDATE_BUDGET_EXHAUSTED: "+str(budget_row),"payload":None,"output":None,"log":log,"attempt":attempt,"scout":None,"budget":budget_row}
            production_recovery.write_lifecycle(ep, item, "FAILED", worker_pid=os.getpid(), error=result["stdout"], result=result)
            return result
        generation_lease = budget_row.get("lease") or {}
        # MySQL serializes concurrent reserves; a late second process can
        # never use Attempt #2 as another first-frame entitlement probe.
        if (native_baseline_probe is not None
                and not production_native_baseline_proof.admitted_baseline_lease(
                    ep, item, generation_lease)):
            raw_candidate_budget.release(ep, budget_token,
                                         reason="native_baseline_proof_requires_first_attempt")
            message = "NATIVE_VISUAL_BASELINE_PROOF_FIRST_ATTEMPT_ONLY"
            result = {"returncode": 94, "stdout": message, "payload": None,
                      "output": None, "log": log, "attempt": attempt,
                      "image_generation_called": False}
            production_recovery.write_lifecycle(
                ep, item, "BLOCKED", worker_pid=os.getpid(), error=message, result=result)
            return result
        item["generation_key"] = generation_lease.get("generation_key")
        item["attempt_index"] = generation_lease.get("attempt_index")
        production_recovery.write_lifecycle(
            ep, item, "ATTEMPT_RESERVED", generation_key=generation_lease.get("generation_key"),
            attempt_index=generation_lease.get("attempt_index"), fencing_token=generation_lease.get("fencing_token"),
            lease_token_hash=generation_lease.get("lease_token_hash"),
        )
        runner_request_id = uuid.uuid4().hex
        item.setdefault("execution", {})["runner_request_id"] = runner_request_id
        ns=argparse.Namespace(
            episode_dir=ep,frame=f"{frame:02d}",prompt_file=prompt,output=out,log=log,
            reference=refs,timeout=timeout,codex=codex,image_model=model,image_quality=quality,overwrite=False,
            _image_model_policy=effective_model_policy,
            _raw_candidate_budget_preclaimed=True,_raw_candidate_token=budget_token,candidate_kind=budget_kind,
            _generation_attempt_lease=generation_lease,
            _runner_request_id=runner_request_id,
            _canonical_payload_request=canonical_request,
            _payload_reference_paths=refs,
            _payload_provider_route=selected_provider,
            _payload_transport_model=payload_preflight.get("transport_model"),
            _payload_transport_effort=payload_preflight.get("transport_effort"))
        # Resident Runner image workers do not always inherit a workflow trace
        # context. Keep the span evidence correlated instead of turning a missing
        # observability context into a false worker failure.
        trace_context = runtime_trace.current(ep)
        trace_id = str(trace_context.get("trace_id") or ("ST_" + uuid.uuid4().hex[:16]))
        trace_run_id = trace_context.get("run_id")
        trace_span=runtime_trace.start_span(
            ep,f"image.generate.frame.{frame:02d}",category="image_generation",
            trace_id=trace_id,run_id=trace_run_id,
            attrs={"frame":frame,"model":model,"quality":quality})
        trace_started=time.monotonic()
        try:
            production_recovery.write_lifecycle(ep, item, "BACKEND_INVOKED", worker_pid=os.getpid(),
                                                expected_output=str(out), expected_log=str(log),
                                                runner_request_id=runner_request_id)
            payload=backend.generate_for_frame(ns)
        except Exception as exc:
            code=runtime_circuit_breaker.classify_text(str(exc))
            if code:runtime_circuit_breaker.record_failure(ep,"image",code)
            raw_candidate_budget.release(ep,budget_token,reason="generation_failed_before_candidate_commit")
            runtime_trace.end_span(ep,trace_span,name=f"image.generate.frame.{frame:02d}",category="image_generation",status="FAILED",started_monotonic=trace_started,trace_id=trace_id,run_id=trace_run_id,attrs={"frame":frame,"error":str(exc)})
            result={"returncode":99,"stdout":str(exc),"payload":None,"output":None,"log":log,"attempt":attempt,"scout":None,"worker_pool":{"mode":MODE,"codex_session_reuse":False}}
            production_recovery.write_lifecycle(ep, item, "FAILED", worker_pid=os.getpid(), error=str(exc), result=result)
            return result

        # A backend return is not success by itself.  Historical workers could
        # return rc=0 while producing no usable artifact, which let the scheduler
        # commit budget and only discover the missing file later.  Fail closed at
        # the worker boundary so technical retry/failover sees an explicit cause.
        if not out.is_file() or out.stat().st_size <= 0:
            code="IMAGE_BACKEND_NO_OUTPUT"
            raw_candidate_budget.release(ep,budget_token,reason="backend_returned_without_output")
            runtime_trace.end_span(ep,trace_span,name=f"image.generate.frame.{frame:02d}",category="image_generation",
                                   status="FAILED",started_monotonic=trace_started,
                                   trace_id=trace_id,run_id=trace_run_id,
                                   attrs={"frame":frame,"error":code,"runner_request_id":runner_request_id})
            result={"returncode":95,"stdout":f"{code}: expected={out}","payload":payload,"output":None,"log":log,
                    "attempt":attempt,"scout":None,"worker_pool":{"mode":MODE,"codex_session_reuse":False}}
            production_recovery.write_lifecycle(ep,item,"FAILED",worker_pid=os.getpid(),error=result["stdout"],result=result)
            return result

        if native_baseline_probe is not None:
            # Text-only tool visibility is never proof of a generated image.
            # Require an actual provider image tool item, completed Codex turn,
            # and PNG before any downstream review can see this first frame.
            try:
                production_native_baseline_proof.record_unreviewed_pixel(
                    ep, item, generation_lease, log, out, runner_request_id)
            except Exception as exc:
                # IMPORTANT: post-dispatch unverifiable provider evidence is
                # OUTCOME_UNKNOWN, NOT SUCCEEDED and NOT free to regenerate.
                # The authority.release() path dispatches atomically to
                # GenerationAttempt.mark_outcome_unknown() when the gateway
                # already committed dispatch. It is NOT a pre-dispatch refund.
                release_ok,release_row = raw_candidate_budget.release(
                    ep, budget_token, reason="NATIVE_BASELINE_PIXEL_TOOL_PROOF_UNVERIFIED")
                if not release_ok:
                    raise RuntimeError(
                        "NATIVE_BASELINE_ATTEMPT_RECONCILIATION_REQUIRED: "
                        + str(release_row.get("decision") or "unknown")) from exc
                message = f"NATIVE_BASELINE_PIXEL_TOOL_PROOF_UNVERIFIED: {type(exc).__name__}"
                result = {"returncode": 94, "stdout": message, "payload": payload,
                          "output": out, "log": log, "attempt": attempt,
                          "generation_key": generation_lease.get("generation_key"),
                          "image_generation_called": "UNVERIFIED"}
                production_recovery.write_lifecycle(
                    ep, item, "BLOCKED", worker_pid=os.getpid(),
                    error=message, result=result)
                return result
        commit_ok,commit_row=raw_candidate_budget.commit(ep,budget_token,reason="normalized_candidate_exists")
        if not commit_ok:
            runtime_trace.end_span(ep,trace_span,name=f"image.generate.frame.{frame:02d}",category="image_generation",status="FAILED",started_monotonic=trace_started,trace_id=trace_id,run_id=trace_run_id,attrs={"frame":frame,"error":"candidate commit failed"})
            result={"returncode":96,"stdout":"CANDIDATE_COMMIT_FAILED: "+str(commit_row),"payload":payload,"output":out,"log":log,"attempt":attempt,"scout":None}
            production_recovery.write_lifecycle(ep, item, "FAILED", worker_pid=os.getpid(), error=result["stdout"], result=result)
            return result
        runtime_circuit_breaker.record_success(ep,"image")

        # Review belongs to the independent durable Review Lane. Keep the worker
        # critical path limited to generation and artifact commit.
        scout=None
        runtime_trace.end_span(ep,trace_span,name=f"image.generate.frame.{frame:02d}",category="image_generation",status="PASS",started_monotonic=trace_started,trace_id=trace_id,run_id=trace_run_id,attrs={"frame":frame,"backend":payload.get("backend"),"candidate_committed":True})
        result={"returncode":0,"stdout":"","payload":payload,"output":out,"log":log,"attempt":attempt,"scout":scout,"candidate_budget":commit_row,"prompt_package":{"package_sha256":package["package_sha256"],"scene_prompt_sha256":package["scene_prompt_sha256"],"frame_contract_sha256":package["frame_contract_sha256"]},"worker_pool":{"mode":MODE,"codex_session_reuse":False}}
        production_recovery.write_lifecycle(ep, item, "SUCCEEDED", worker_pid=os.getpid(), result=result)
        return result

def self_test():
    assert MODE=="python_warm_pool_codex_ephemeral"
    assert CODEX_SESSION_REUSE is False
    print("IMAGE WORKER POOL SELF-TEST PASS")

if __name__=="__main__": self_test()

# STORY_OS_V2_5_1_1_FORCED_CANDIDATE_GATE

# STORY_OS_V2_6_0_PERFORMANCE_RUNTIME
