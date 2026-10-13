#!/usr/bin/env python3
"""Canonical, deterministic contract for a frozen image payload request.

This module describes the output of the Image Controller.  It does not execute
models, reserve generation attempts, route providers, or grant production
authority.  The payload provider must consume the validated request verbatim.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any


SCHEMA_VERSION = 1
PAYLOAD_MODEL = "gpt-image-2.5-flare"
PAYLOAD_QUALITY = "high"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_FRAME_RE = re.compile(r"^(?:frame[-_ ]?)?(\d{1,4})$", re.IGNORECASE)

# Fingerprint inputs are deliberately explicit.  Receipt timestamps, runner
# identity, worker IDs, queue state, and local output paths are not request
# semantics and must never make an otherwise identical request dirty.
_FINGERPRINT_FIELDS = (
    "schema_version",
    "episode_id",
    "logical_asset_key",
    "frame_id",
    "authority_input_sha256",
    "source_prompt_sha256",
    "frame_contract_sha256",
    "visual_contract_sha256",
    "controller_receipt_id",
    "controller_output_sha256",
    "payload_model",
    "payload_quality",
    "canvas",
    "references",
    "scene_prompt_sha256",
    "model_policy_version",
    "model_policy_sha256",
)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(_SHA256_RE.fullmatch(value.lower()))


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"IMAGE_PAYLOAD_REQUEST_FIELD_REQUIRED:{field}")
    return value.strip()


def _stable_identity(value: Any, field: str) -> str:
    text = _text(value, field).replace("\\", "/")
    win = PureWindowsPath(text)
    posix = PurePosixPath(text)
    if win.is_absolute() or win.drive or posix.is_absolute():
        raise ValueError(f"IMAGE_PAYLOAD_REQUEST_UNSTABLE_PATH:{field}")
    if any(part in {"", ".", ".."} for part in text.split("/")):
        raise ValueError(f"IMAGE_PAYLOAD_REQUEST_UNSTABLE_PATH:{field}")
    lowered = text.lower()
    if any(marker in lowered for marker in (".codex_tmp", "story-os-image-", "\\temp\\", "/temp/", "/tmp/")):
        raise ValueError(f"IMAGE_PAYLOAD_REQUEST_TEMP_PATH:{field}")
    return text


def _normalize_canvas(canvas: Any) -> dict[str, Any]:
    if isinstance(canvas, str):
        match = re.fullmatch(r"\s*(\d{2,5})[xX](\d{2,5})\s*", canvas)
        if not match:
            raise ValueError("IMAGE_PAYLOAD_REQUEST_CANVAS_INVALID")
        width, height = int(match.group(1)), int(match.group(2))
        supplied_ratio = None
    elif isinstance(canvas, dict):
        width, height = canvas.get("width"), canvas.get("height")
        supplied_ratio = canvas.get("aspect_ratio")
    else:
        raise ValueError("IMAGE_PAYLOAD_REQUEST_CANVAS_INVALID")

    if type(width) is not int or type(height) is not int or width <= 0 or height <= 0:
        raise ValueError("IMAGE_PAYLOAD_REQUEST_CANVAS_INVALID")
    divisor = math.gcd(width, height)
    ratio = f"{width // divisor}:{height // divisor}"
    if supplied_ratio is not None and str(supplied_ratio).strip() != ratio:
        raise ValueError("IMAGE_PAYLOAD_REQUEST_CANVAS_ASPECT_RATIO_MISMATCH")
    return {"width": width, "height": height, "aspect_ratio": ratio}


def _normalize_references(references: Any) -> list[dict[str, str | None]]:
    if not isinstance(references, list):
        raise ValueError("IMAGE_PAYLOAD_REQUEST_REFERENCES_INVALID")
    result: list[dict[str, str | None]] = []
    seen: set[str] = set()
    for index, row in enumerate(references):
        if not isinstance(row, dict):
            raise ValueError(f"IMAGE_PAYLOAD_REQUEST_REFERENCE_INVALID:{index}")
        authority_id = row.get("authority_id")
        path = row.get("path")
        if authority_id is None and path is None:
            raise ValueError(f"IMAGE_PAYLOAD_REQUEST_REFERENCE_ID_REQUIRED:{index}")
        normalized_authority = (
            _stable_identity(authority_id, f"references[{index}].authority_id")
            if authority_id is not None else None
        )
        normalized_path = (
            _stable_identity(path, f"references[{index}].path")
            if path is not None else None
        )
        digest = row.get("sha256")
        if not _is_sha256(digest):
            raise ValueError(f"IMAGE_PAYLOAD_REQUEST_REFERENCE_SHA_INVALID:{index}")
        digest = digest.lower()
        identity = normalized_authority or normalized_path or ""
        if identity in seen:
            raise ValueError(f"IMAGE_PAYLOAD_REQUEST_REFERENCE_DUPLICATE:{index}")
        seen.add(identity)
        normalized = {
            "authority_id": normalized_authority,
            "path": normalized_path,
            "sha256": digest,
        }
        # Reference semantics are business request data, not a model hint that
        # the transport may reinterpret. Preserve them in the fingerprint.
        if row.get("kind") is not None:
            kind = str(row["kind"])
            if kind not in {"identity", "prop", "location", "capture_style"}:
                raise ValueError(f"IMAGE_PAYLOAD_REQUEST_REFERENCE_KIND_INVALID:{index}")
            normalized["kind"] = kind
        if row.get("role") is not None:
            role = str(row["role"]).strip()
            if not role or len(role) > 120 or any(ch in role for ch in "\r\n"):
                raise ValueError(f"IMAGE_PAYLOAD_REQUEST_REFERENCE_ROLE_INVALID:{index}")
            normalized["role"] = role
        result.append(normalized)
    return result


def _normalized_semantics(request: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(request, dict):
        raise ValueError("IMAGE_PAYLOAD_REQUEST_INVALID")
    version = request.get("schema_version", SCHEMA_VERSION)
    if type(version) is not int or version != SCHEMA_VERSION:
        raise ValueError("IMAGE_PAYLOAD_REQUEST_SCHEMA_VERSION_UNSUPPORTED")

    episode_id = _stable_identity(request.get("episode_id"), "episode_id")
    asset_key = _stable_identity(request.get("logical_asset_key"), "logical_asset_key")
    frame_raw = _text(request.get("frame_id"), "frame_id")
    frame_match = _FRAME_RE.fullmatch(frame_raw)
    if not frame_match:
        raise ValueError("IMAGE_PAYLOAD_REQUEST_FRAME_ID_INVALID")
    frame_id = f"{int(frame_match.group(1)):02d}"

    sha_fields = (
        "authority_input_sha256",
        "source_prompt_sha256",
        "frame_contract_sha256",
        "visual_contract_sha256",
        "controller_output_sha256",
        "model_policy_sha256",
    )
    digests: dict[str, str] = {}
    for field in sha_fields:
        value = request.get(field)
        if not _is_sha256(value):
            raise ValueError(f"IMAGE_PAYLOAD_REQUEST_SHA_INVALID:{field}")
        digests[field] = str(value).lower()

    controller_receipt_id = _stable_identity(
        request.get("controller_receipt_id"), "controller_receipt_id"
    )
    payload_model = _text(request.get("payload_model"), "payload_model")
    payload_quality = _text(request.get("payload_quality"), "payload_quality").lower()
    if payload_model != PAYLOAD_MODEL:
        raise ValueError("IMAGE_PAYLOAD_REQUEST_PAYLOAD_MODEL_MISMATCH")
    if payload_quality != PAYLOAD_QUALITY:
        raise ValueError("IMAGE_PAYLOAD_REQUEST_PAYLOAD_QUALITY_MISMATCH")

    scene_prompt = _text(request.get("scene_prompt"), "scene_prompt")
    scene_prompt_sha = _sha256(scene_prompt.encode("utf-8"))
    supplied_scene_sha = request.get("scene_prompt_sha256")
    if supplied_scene_sha is not None and (
        not _is_sha256(supplied_scene_sha) or str(supplied_scene_sha).lower() != scene_prompt_sha
    ):
        raise ValueError("IMAGE_PAYLOAD_REQUEST_SCENE_PROMPT_SHA_MISMATCH")

    policy_version = _text(request.get("model_policy_version"), "model_policy_version")
    canvas = _normalize_canvas(request.get("canvas"))
    references = _normalize_references(request.get("references", []))

    return {
        "schema_version": SCHEMA_VERSION,
        "episode_id": episode_id,
        "logical_asset_key": asset_key,
        "frame_id": frame_id,
        **digests,
        "controller_receipt_id": controller_receipt_id,
        "payload_model": payload_model,
        "payload_quality": payload_quality,
        "canvas": canvas,
        "references": references,
        "scene_prompt": scene_prompt,
        "scene_prompt_sha256": scene_prompt_sha,
        "model_policy_version": policy_version,
        "model_policy_sha256": digests["model_policy_sha256"],
    }


def request_fingerprint(request: dict[str, Any]) -> str:
    """Hash only canonical business request identity, never runtime metadata."""
    semantic = _normalized_semantics(request)
    fingerprint_input = {key: semantic[key] for key in _FINGERPRINT_FIELDS}
    return _sha256(_canonical_bytes(fingerprint_input))


def build_request(**fields: Any) -> dict[str, Any]:
    """Build and validate a canonical Flare/high request with stable identity."""
    normalized = _normalized_semantics(fields)
    request = dict(normalized)
    request["request_fingerprint"] = request_fingerprint(request)
    return request


def validate_request(
    request: dict[str, Any], *, expected_policy_sha256: str | None = None
) -> list[str]:
    """Return contract errors; an empty list means the request is valid."""
    try:
        semantic = _normalized_semantics(request)
        fingerprint = request_fingerprint(request)
    except (TypeError, ValueError) as exc:
        return [str(exc)]
    errors: list[str] = []
    if request.get("request_fingerprint") != fingerprint:
        errors.append("IMAGE_PAYLOAD_REQUEST_FINGERPRINT_MISMATCH")
    if request.get("scene_prompt_sha256") != semantic["scene_prompt_sha256"]:
        errors.append("IMAGE_PAYLOAD_REQUEST_SCENE_PROMPT_SHA_MISMATCH")
    if expected_policy_sha256 is not None:
        if not _is_sha256(expected_policy_sha256):
            errors.append("IMAGE_PAYLOAD_REQUEST_EXPECTED_POLICY_SHA_INVALID")
        elif semantic["model_policy_sha256"] != expected_policy_sha256.lower():
            errors.append("IMAGE_PAYLOAD_REQUEST_POLICY_SHA_MISMATCH")
    return errors


def self_test() -> None:
    digest = "a" * 64
    request = build_request(
        episode_id="episodes/canary-01",
        logical_asset_key="episodes/canary-01/frame-01",
        frame_id="frame-1",
        authority_input_sha256=digest,
        source_prompt_sha256=digest,
        frame_contract_sha256=digest,
        visual_contract_sha256=digest,
        controller_receipt_id="call-01",
        controller_output_sha256=digest,
        payload_model=PAYLOAD_MODEL,
        payload_quality=PAYLOAD_QUALITY,
        canvas={"width": 1080, "height": 1350, "aspect_ratio": "4:5"},
        references=[{"authority_id": "refs/style/M00", "path": "assets/refs/m00.png", "sha256": digest}],
        scene_prompt="locked prompt",
        model_policy_version="v1",
        model_policy_sha256=digest,
    )
    assert validate_request(request, expected_policy_sha256=digest) == []
    assert request["request_fingerprint"] == request_fingerprint(request)
    assert request["frame_id"] == "01"

    runtime_only = dict(request, worker_pid=100, queue_wait_ms=20, timestamp="ignored")
    assert request_fingerprint(runtime_only) == request["request_fingerprint"]

    changed_prompt = "changed prompt"
    changed = dict(
        request,
        scene_prompt=changed_prompt,
        scene_prompt_sha256=_sha256(changed_prompt.encode("utf-8")),
    )
    assert "IMAGE_PAYLOAD_REQUEST_FINGERPRINT_MISMATCH" in validate_request(changed)
    try:
        build_request(**{**request, "payload_model": "gpt-image-2.5-sunburst"})
    except ValueError as exc:
        assert "PAYLOAD_MODEL_MISMATCH" in str(exc)
    else:
        raise AssertionError("non-Flare payload must be rejected")
    try:
        build_request(**{**request, "references": [{"path": r"C:\\temp\\ref.png", "sha256": digest}]})
    except ValueError as exc:
        assert "UNSTABLE_PATH" in str(exc) or "TEMP_PATH" in str(exc)
    else:
        raise AssertionError("absolute reference path must be rejected")
    print("IMAGE PAYLOAD REQUEST SELF-TEST PASS")


if __name__ == "__main__":
    self_test()
