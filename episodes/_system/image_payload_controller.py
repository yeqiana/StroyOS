#!/usr/bin/env python3
"""Run the policy-bound Image Controller and build a canonical Payload Request.

This module does not reserve generation attempts and never enables or calls an
image-generation tool.  Its output is evidence plus a validated request for a
separate Payload Provider to consume.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
from pathlib import Path
from typing import Any

import codex_critic_runner
import image_payload_request
import image_payload_hard_constraints
import m00_style_guard
import m00_scene_fidelity_guard
import m00_episode_state_delta
import logical_asset_identity
import model_policy
import runtime_observability
import scoped_codex_worker


class ImagePayloadControllerError(RuntimeError):
    def __init__(self, code: str, detail: str = "") -> None:
        self.code = str(code)
        self.detail = str(detail)
        super().__init__(self.code + (f": {self.detail}" if self.detail else ""))

# Include validator identity in the Controller input fingerprint. Otherwise a
# SUCCESS receipt created under older semantic rules can be mistaken for a
# validated current Payload Request.
CONTROLLER_VALIDATION_VERSION = "source-apparent-age-v2"


def separate_execution_required(ep) -> bool:
    """Whether legacy batch execution would bypass the bound Controller lane.

    The check is descriptive only; it grants no authority and changes no Policy.
    Any Episode with distinct image.controller and image.payload roles must use
    the per-frame Controller → canonical request → Payload path.
    """
    try:
        controller = model_policy.resolve("image.controller", episode=Path(ep).resolve())
        payload = model_policy.resolve("image.payload", episode=Path(ep).resolve())
    except Exception:
        return True  # fail closed: never route an unknown binding through legacy batch
    return (
        str(controller.get("role") or "") == "image.controller"
        and str(controller.get("profile") or "") == "image_controller"
        and str(payload.get("role") or "") == "image.payload"
        and str(payload.get("profile") or "") == "image_payload"
    )


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _controller_telemetry(ep: Path, event: str, *, call_id: str, binding: dict,
                          input_fingerprint: str, status: str,
                          output_sha256: str | None = None,
                          payload_request_fingerprint: str | None = None) -> None:
    try:
        runtime_observability.safe_record_runtime_event(
            ep, event, source="image_payload_controller", step="IMAGE_PAYLOAD_REQUEST",
            call_id=call_id, model_role="image.controller", profile=binding.get("profile"),
            requested_model=binding.get("model"), effective_model_source="EXPLICIT_RUNTIME_BINDING",
            reasoning_effort=binding.get("reasoning_effort"),
            model_policy_version=binding.get("policy_version"),
            model_policy_sha256=binding.get("model_policy_sha256"), status=status,
            controller_input_fingerprint=input_fingerprint,
            controller_output_sha256=output_sha256,
            payload_request_fingerprint=payload_request_fingerprint,
        )
    except Exception:
        return


def _receipt_path(ep: Path, call_id: str) -> Path:
    return ep / "meta/provider-receipts/model-executions" / f"{call_id}.json"


def _binding_for_episode(ep: Path) -> dict:
    errors = model_policy.validate_bound_policy(ep)
    if errors:
        raise ImagePayloadControllerError("IMAGE_CONTROLLER_POLICY_INVALID", ",".join(errors))
    try:
        binding = model_policy.resolve("image.controller", episode=ep)
        payload = model_policy.resolve("image.payload", episode=ep)
    except Exception as exc:
        raise ImagePayloadControllerError("IMAGE_CONTROLLER_POLICY_UNAVAILABLE", str(exc)) from exc

    expected = {
        "role": "image.controller",
        "profile": "image_controller",
        "model": "gpt-6-luna",
        "reasoning_effort": "high",
    }
    for field, value in expected.items():
        if str(binding.get(field) or "").strip() != value:
            raise ImagePayloadControllerError("IMAGE_CONTROLLER_FROZEN_BINDING_MISMATCH", field)
    if not str(binding.get("model_policy_sha256") or "").strip():
        raise ImagePayloadControllerError("IMAGE_CONTROLLER_POLICY_SHA_MISSING")
    if not str(binding.get("policy_version") or "").strip():
        raise ImagePayloadControllerError("IMAGE_CONTROLLER_POLICY_VERSION_MISSING")
    if str(payload.get("profile") or "").strip() != "image_payload":
        raise ImagePayloadControllerError("IMAGE_PAYLOAD_FROZEN_PROFILE_MISMATCH")
    if str(payload.get("model") or "") != image_payload_request.PAYLOAD_MODEL:
        raise ImagePayloadControllerError("IMAGE_PAYLOAD_FROZEN_MODEL_MISMATCH")
    if str(payload.get("quality") or "").lower() != image_payload_request.PAYLOAD_QUALITY:
        raise ImagePayloadControllerError("IMAGE_PAYLOAD_FROZEN_QUALITY_MISMATCH")
    if str(payload.get("model_policy_sha256") or "") != str(binding["model_policy_sha256"]):
        raise ImagePayloadControllerError("IMAGE_CONTROLLER_PAYLOAD_POLICY_SHA_MISMATCH")
    if str(payload.get("policy_version") or "") != str(binding.get("policy_version") or ""):
        raise ImagePayloadControllerError("IMAGE_CONTROLLER_PAYLOAD_POLICY_VERSION_MISMATCH")
    return {"controller": binding, "payload": payload}


def _controller_prompt(*, controller_input: dict, identity: dict, binding: dict,
                       payload: dict, canvas: str | dict,
                       references: list[dict]) -> str:
    task = {
        "task": "Return exactly one JSON object with one field: scene_prompt.",
        "role": "image.controller",
        "instructions": [
            "Produce the final scene prompt from the supplied frozen StoryOS inputs.",
            "Preserve all frame, visual, identity, continuity, and source constraints.",
            "If source_scene_prompt explicitly specifies a visual/apparent age (e.g. 47岁), keep that exact age in the generated scene prompt; never replace it with a generic character biography age (e.g. 56岁).",
            "Do not choose or change the image model, quality, canvas, references, or policy.",
            "Do not call tools, image_generation, or any image provider.",
            "Return only JSON shaped as {\"scene_prompt\":\"...\"}; no markdown or extra keys.",
        ],
        "locked_binding": {
            "controller_model": binding["model"],
            "controller_effort": binding["reasoning_effort"],
            "payload_model": payload["model"],
            "payload_quality": payload["quality"],
            "model_policy_version": binding.get("policy_version"),
            "model_policy_sha256": binding["model_policy_sha256"],
        },
        "payload_identity": identity,
        "canvas": canvas,
        "references": references,
        "controller_input": controller_input,
    }
    return json.dumps(task, ensure_ascii=False, sort_keys=True, indent=2)


def _input_fingerprint(*, prompt: str, binding: dict, identity: dict, references: list[dict]) -> str:
    value = {
        "controller_step": "IMAGE_PAYLOAD_REQUEST",
        "controller_role": "image.controller",
        "profile": binding["profile"],
        "requested_model": binding["model"],
        "reasoning_effort": binding["reasoning_effort"],
        "model_policy_version": binding.get("policy_version"),
        "model_policy_sha256": binding["model_policy_sha256"],
        "identity": identity,
        "references": references,
        "prompt": prompt,
        "controller_validation_version": CONTROLLER_VALIDATION_VERSION,
    }
    return _sha256_bytes(_canonical_bytes(value))


def _parse_controller_output(stream_text: str) -> dict:
    result = codex_critic_runner.recover_completed_agent_json(stream_text)
    if not isinstance(result, dict) or set(result) != {"scene_prompt"}:
        raise ImagePayloadControllerError("IMAGE_CONTROLLER_OUTPUT_SCHEMA_INVALID")
    scene_prompt = result.get("scene_prompt")
    if not isinstance(scene_prompt, str) or not scene_prompt.strip():
        raise ImagePayloadControllerError("IMAGE_CONTROLLER_SCENE_PROMPT_EMPTY")
    return {"scene_prompt": scene_prompt.strip()}


def _validate_frame_age(*, controller_input: dict, scene_prompt: str) -> None:
    """Reject per-frame apparent-age drift before creating the payload request.

    The character-wide age may reflect the final timeline (e.g. 56), while a
    locked 2017 storyboard frame explicitly depicts a 47-year-old appearance.
    Only the supplied per-frame source prompt is authoritative for this test.
    """
    source_scene = str(controller_input.get("source_scene_prompt") or "")
    locked_ages = set(re.findall(r"(?<!\d)(\d{1,3})\s*岁", source_scene))
    if not locked_ages:
        return
    generated_ages = set(re.findall(r"(?<!\d)(\d{1,3})\s*岁", scene_prompt))
    if generated_ages != locked_ages:
        raise ImagePayloadControllerError(
            "IMAGE_CONTROLLER_SOURCE_AGE_DRIFT",
            f"frame_source_ages={sorted(locked_ages)},output_ages={sorted(generated_ages)}",
        )


def _build_validated_request(*, ep: Path, identity: dict, fields: dict,
                             binding: dict, payload: dict, call_id: str,
                             controller_output: dict, controller_input: dict) -> dict:
    _validate_frame_age(controller_input=controller_input,
                        scene_prompt=controller_output["scene_prompt"])
    output_sha = _sha256_bytes(_canonical_bytes(controller_output))
    # Retain documentary capture constraints even when Controller compresses them.
    # The effective prompt is part of the canonical Payload SHA/fingerprint.
    effective_scene_prompt = m00_style_guard.enforce(
        scene_prompt=controller_output["scene_prompt"],
        visual_contract=str(controller_input.get("visual_contract") or ""),
    )
    # The controller may omit the event when polishing style. Keep the original
    # Story-owned event observable without inventing content or forcing motion.
    effective_scene_prompt = m00_scene_fidelity_guard.enforce_event(
        scene_prompt=effective_scene_prompt,
        source_scene_prompt=str(controller_input.get("source_scene_prompt") or ""),
        visual_contract=str(controller_input.get("visual_contract") or ""),
    )
    effective_scene_prompt = m00_scene_fidelity_guard.enforce_motion(
        scene_prompt=effective_scene_prompt,
        visual_contract=str(controller_input.get("visual_contract") or ""),
    )
    effective_scene_prompt = m00_episode_state_delta.project_final_prompt(
        scene_prompt=effective_scene_prompt,
        controller_input=controller_input,
        is_m00=m00_style_guard.is_m00(str(controller_input.get("visual_contract") or "")),
    )
    # The Controller may compress or omit immutable facts. Project exactly the
    # frozen Frame Contract obligations into the final provider scene prompt.
    # image_payload_request fingerprints these transmitted bytes.
    frozen_frame = str(controller_input.get("frame_prompt_contract") or "")
    # Legacy direct Controller clients can supply synthetic fragments; the
    # canonical image_worker_pool requires a fully compiled Frame Contract.
    # Never pretend that an unbound fragment is a frozen authority.
    if frozen_frame.startswith("RESOLVED FRAME CONTRACT |"):
        effective_scene_prompt = image_payload_hard_constraints.inject(
            effective_scene_prompt, frozen_frame,
            original_scene=str(controller_input.get("source_scene_prompt") or ""),
            m00=m00_style_guard.is_m00(str(controller_input.get("visual_contract") or "")),
        )
    request = image_payload_request.build_request(
        **identity,
        controller_receipt_id=call_id,
        controller_output_sha256=output_sha,
        payload_model=payload["model"],
        payload_quality=payload["quality"],
        canvas=fields["canvas"],
        references=fields["references"],
        scene_prompt=effective_scene_prompt,
        model_policy_version=binding.get("policy_version"),
        model_policy_sha256=binding["model_policy_sha256"],
    )
    errors = image_payload_request.validate_request(
        request, expected_policy_sha256=binding["model_policy_sha256"]
    )
    if errors:
        raise ImagePayloadControllerError("IMAGE_PAYLOAD_REQUEST_INVALID", ",".join(errors))
    return request


def _reuse_existing_receipt(*, ep: Path, path: Path, call_id: str,
                             input_fingerprint: str, binding: dict,
                             identity: dict, fields: dict, payload: dict,
                             controller_input: dict) -> dict | None:
    if not path.is_file():
        return None
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ImagePayloadControllerError("IMAGE_CONTROLLER_RECEIPT_INVALID", "unreadable") from exc
    valid = (
        isinstance(receipt, dict)
        and receipt.get("status") == "SUCCESS"
        and receipt.get("step") == "IMAGE_PAYLOAD_REQUEST"
        and receipt.get("call_id") == call_id
        and receipt.get("model_role") == "image.controller"
        and receipt.get("profile") == "image_controller"
        and receipt.get("requested_model") == "gpt-6-luna"
        and receipt.get("reasoning_effort") == "high"
        and receipt.get("model_policy_sha256") == binding.get("model_policy_sha256")
        and receipt.get("controller_input_fingerprint") == input_fingerprint
        and receipt.get("image_generation_enabled") is False
        and receipt.get("effective_model_source") == "EXPLICIT_RUNTIME_BINDING"
        and bool(receipt.get("scoped_output_stream"))
    )
    if not valid:
        raise ImagePayloadControllerError("IMAGE_CONTROLLER_RECEIPT_NOT_REUSABLE", call_id)
    output = _parse_controller_output(receipt["scoped_output_stream"])
    request = _build_validated_request(
        ep=ep, identity=identity, fields=fields, binding=binding, payload=payload,
        call_id=call_id, controller_output=output, controller_input=controller_input,
    )
    output_sha = _sha256_bytes(_canonical_bytes(output))
    if receipt.get("controller_output_sha256") != output_sha:
        raise ImagePayloadControllerError("IMAGE_CONTROLLER_RECEIPT_OUTPUT_SHA_MISMATCH", call_id)
    rebound_from_legacy = False
    if receipt.get("payload_request_fingerprint") != request.get("request_fingerprint"):
        # A historical SUCCESS receipt binds the same immutable Controller
        # output but predates deterministic frozen-constraint projection.
        # Reconstruct exactly the previous payload fingerprint (no model call),
        # and only rebind the existing text receipt when its previous request
        # matches byte-for-byte. Anything else remains a hard mismatch.
        scene = str(request.get("scene_prompt") or "")
        suffix = "\n\n" + image_payload_hard_constraints.BEGIN + "\n"
        if not (str(controller_input.get("frame_prompt_contract") or "").startswith(
                "RESOLVED FRAME CONTRACT |") and suffix in scene):
            raise ImagePayloadControllerError("IMAGE_CONTROLLER_RECEIPT_REQUEST_MISMATCH", call_id)
        legacy_fields = {key: val for key, val in request.items()
                         if key not in ("request_fingerprint", "scene_prompt_sha256")}
        legacy_fields["scene_prompt"] = scene.split(suffix, 1)[0]
        old_request = image_payload_request.build_request(**legacy_fields)
        if receipt.get("payload_request_fingerprint") != old_request.get("request_fingerprint"):
            raise ImagePayloadControllerError("IMAGE_CONTROLLER_RECEIPT_REQUEST_MISMATCH", call_id)
        rebound_from_legacy = True
    return {
        "status": "SUCCESS", "request": request, "request_fingerprint": request["request_fingerprint"],
        "controller_call_id": call_id, "receipt": receipt, "receipt_path": str(path),
        "reused": True, "legacy_payload_rebound": rebound_from_legacy,
    }


def build_payload_request(ep, *, logical_asset_key: str, frame_id: str,
                          authority_input_sha256: str, source_prompt_sha256: str,
                          frame_contract_sha256: str, visual_contract_sha256: str,
                          canvas: str | dict, references: list[dict], controller_input: dict,
                          codex_raw=None, timeout=None, run_id=None, trace_id=None) -> dict:
    """Execute/reuse Luna Controller output and return a validated Flare/high request.

    This function intentionally has no Attempt Authority or Provider dependency.
    The caller may reserve an image Attempt only after this returns successfully.
    """
    ep = Path(ep).resolve()
    if not isinstance(controller_input, dict) or not controller_input:
        raise ImagePayloadControllerError("IMAGE_CONTROLLER_INPUT_REQUIRED")
    if not isinstance(references, list):
        raise ImagePayloadControllerError("IMAGE_CONTROLLER_REFERENCES_INVALID")
    resolved = _binding_for_episode(ep)
    binding, payload = resolved["controller"], resolved["payload"]
    episode_id = logical_asset_identity.episode_id(ep)
    identity = {
        "episode_id": episode_id,
        "logical_asset_key": str(logical_asset_key or "").strip(),
        "frame_id": str(frame_id or "").strip(),
        "authority_input_sha256": str(authority_input_sha256 or "").strip(),
        "source_prompt_sha256": str(source_prompt_sha256 or "").strip(),
        "frame_contract_sha256": str(frame_contract_sha256 or "").strip(),
        "visual_contract_sha256": str(visual_contract_sha256 or "").strip(),
    }
    fields = {"canvas": canvas, "references": references}
    prompt = _controller_prompt(
        controller_input=controller_input, identity=identity, binding=binding, payload=payload,
        canvas=canvas, references=references,
    )
    input_fingerprint = _input_fingerprint(
        prompt=prompt, binding=binding, identity=identity, references=references
    )
    call_id = "imgctrl-" + input_fingerprint[:32]
    receipt_path = _receipt_path(ep, call_id)
    superseded_call_id = None
    try:
        reused = _reuse_existing_receipt(
            ep=ep, path=receipt_path, call_id=call_id, input_fingerprint=input_fingerprint,
            binding=binding, identity=identity, fields=fields, payload=payload,
            controller_input=controller_input,
        )
    except ImagePayloadControllerError as exc:
        retryable_failed_execution = False
        if exc.code == "IMAGE_CONTROLLER_RECEIPT_NOT_REUSABLE":
            try:
                stale = json.loads(receipt_path.read_text(encoding="utf-8"))
                argv = stale.get("codex_argv") if isinstance(stale, dict) else []
                retryable_failed_execution = (
                    isinstance(stale, dict)
                    and stale.get("status") == "FAILED"
                    and stale.get("controller_input_fingerprint") == input_fingerprint
                    and stale.get("image_generation_enabled") is False
                    and not any("image_generation" in str(arg) or str(arg) == "--image" for arg in (argv or []))
                )
            except Exception:
                retryable_failed_execution = False
        if exc.code != "IMAGE_CONTROLLER_SOURCE_AGE_DRIFT" and not retryable_failed_execution:
            raise
        # Preserve the rejected receipt as immutable evidence. A failed,
        # text-only controller call may be retried once under a new call id;
        # successful stale-age output receives the existing one-replacement
        # path and remains subject to the per-frame age validator.
        superseded_call_id = call_id
        stale_digest = _sha256_bytes(receipt_path.read_bytes())
        call_id = "imgctrl-" + _sha256_bytes(_canonical_bytes({
            "input_fingerprint": input_fingerprint,
            "validator": CONTROLLER_VALIDATION_VERSION,
            "superseded_receipt_sha256": stale_digest,
        }))[:32]
        receipt_path = _receipt_path(ep, call_id)
        reused = _reuse_existing_receipt(
            ep=ep, path=receipt_path, call_id=call_id, input_fingerprint=input_fingerprint,
            binding=binding, identity=identity, fields=fields, payload=payload,
            controller_input=controller_input,
        )
    if reused is not None:
        return reused

    stream = io.StringIO()
    _controller_telemetry(ep, "CONTROLLER_EXECUTION_STARTED", call_id=call_id,
                          binding=binding, input_fingerprint=input_fingerprint,
                          status="RUNNING")
    receipt_fields = {
        "controller_input_fingerprint": input_fingerprint,
        "image_generation_enabled": False,
        "effective_model_source": "EXPLICIT_RUNTIME_BINDING",
        "provider": "codex_cli_configured_transport",
        "provider_source": "CODEX_CLI_CONFIG",
        "transport_provider_attestation": "UNCONFIRMED",
        "runner": "codex_user_runner",
        "controller_validation_version": CONTROLLER_VALIDATION_VERSION,
        "supersedes_controller_call_id": superseded_call_id,
    }
    try:
        rc, receipt = scoped_codex_worker.execute_model_call(
            ep, "IMAGE_PAYLOAD_REQUEST", binding, prompt,
            codex_raw=codex_raw, timeout=timeout, run_id=run_id, trace_id=trace_id,
            logical_asset_key=identity["logical_asset_key"], call_id=call_id,
            output_handle=stream, sandbox="read-only", receipt_fields=receipt_fields,
            persist_output_stream=True,
        )
    except Exception as exc:
        _controller_telemetry(ep, "CONTROLLER_EXECUTION_FINISHED", call_id=call_id,
                              binding=binding, input_fingerprint=input_fingerprint,
                              status="FAILED")
        raise ImagePayloadControllerError("IMAGE_CONTROLLER_EXECUTION_FAILED", str(exc)) from exc
    receipt_path = _receipt_path(ep, call_id)
    if rc != 0 or receipt.get("status") != "SUCCESS":
        _controller_telemetry(ep, "CONTROLLER_EXECUTION_FINISHED", call_id=call_id,
                              binding=binding, input_fingerprint=input_fingerprint,
                              status=str(receipt.get("status") or "FAILED"))
        raise ImagePayloadControllerError("IMAGE_CONTROLLER_EXECUTION_FAILED", f"returncode={rc}")
    argv = receipt.get("codex_argv") or []
    if "--enable" in argv or "image_generation" in argv or any(
        arg == "--image" for arg in argv
    ):
        raise ImagePayloadControllerError("IMAGE_CONTROLLER_IMAGE_TOOL_FORBIDDEN")
    try:
        output = _parse_controller_output(stream.getvalue())
        request = _build_validated_request(
            ep=ep, identity=identity, fields=fields, binding=binding, payload=payload,
            call_id=call_id, controller_output=output, controller_input=controller_input,
        )
    except Exception:
        _controller_telemetry(ep, "CONTROLLER_EXECUTION_FINISHED", call_id=call_id,
                              binding=binding, input_fingerprint=input_fingerprint,
                              status="INVALID_OUTPUT")
        raise
    output_sha = _sha256_bytes(_canonical_bytes(output))
    receipt.update({
        "controller_input_fingerprint": input_fingerprint,
        "controller_output_sha256": output_sha,
        "payload_request_fingerprint": request["request_fingerprint"],
        "image_generation_enabled": False,
        "effective_model_source": "EXPLICIT_RUNTIME_BINDING",
        "provider": "codex_cli_configured_transport",
        "provider_source": "CODEX_CLI_CONFIG",
        "transport_provider_attestation": "UNCONFIRMED",
        "runner": "codex_user_runner",
        "controller_validation_version": CONTROLLER_VALIDATION_VERSION,
        "supersedes_controller_call_id": superseded_call_id,
    })
    runtime_observability.write_model_execution_receipt(ep, receipt=receipt)
    _controller_telemetry(ep, "CONTROLLER_EXECUTION_FINISHED", call_id=call_id,
                          binding=binding, input_fingerprint=input_fingerprint,
                          status="SUCCESS", output_sha256=output_sha,
                          payload_request_fingerprint=request["request_fingerprint"])
    return {
        "status": "SUCCESS", "request": request,
        "request_fingerprint": request["request_fingerprint"],
        "controller_call_id": call_id, "receipt": receipt,
        "receipt_path": str(receipt_path), "reused": False,
    }
