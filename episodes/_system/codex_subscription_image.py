#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate exactly one image via the current Codex ChatGPT sign-in, then normalize it to the Story OS canvas."""
from __future__ import annotations
import argparse
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
import base64
import hashlib
import hmac
import json
import os
import re
import shutil
import secrets
import subprocess
import codex_user_runner  # STORY_OS_V2_7_CODEX_USER_MODE_BRIDGE
import sys
import tempfile
import time
import uuid
import tomllib
from pathlib import Path
from PIL import Image

from canvas_normalize import NormalizeError, normalize, normalize_provider_crop_exception, read_canvas
from visual_profile_bridge_v224 import compile_prompt_contract
import frame_contract as resolved_frame_contract
import image_model_policy
import model_policy
import provider_capability
import image_artifact_collector
import image_generation_gateway
import global_image_capacity
import image_payload_request
import openai_images_provider
import raw_candidate_budget  # STORY_OS_V2_5_1_1_FORCED_CANDIDATE_GATE
import runtime_log_policy
import runtime_router
import storyos_config
import runtime_timeout_policy

ROOT = Path(__file__).resolve().parents[2]
_CONFIG = storyos_config.load_config()
_IMAGE_CONTROLLER_POLICY = model_policy.resolve("image.controller")
CODEX_IMAGE_CONTROLLER_MODEL = str(_IMAGE_CONTROLLER_POLICY["model"])
CODEX_IMAGE_REASONING_EFFORT = str(_IMAGE_CONTROLLER_POLICY["reasoning_effort"])
# 图片 Payload 模型、质量与回落候选的唯一业务配置源是 storyos.yaml 的 models profiles；
# 不在函数默认值里复制字面量，避免改 yaml 后 worker 仍按旧模型生成。
DEFAULT_IMAGE_MODEL = image_model_policy.DEFAULT_MODEL
DEFAULT_IMAGE_QUALITY = image_model_policy.DEFAULT_QUALITY

PNG = b'\x89PNG\r\n\x1a\n'
JPEG = b'\xff\xd8\xff'

class BackendError(RuntimeError):
    pass


def _configurable_bool(config_key: str, env_name: str) -> bool:
    """Product boolean from YAML, with an observable one-run env override."""
    raw = os.environ.get(env_name)
    if raw is not None and str(raw).strip():
        return str(raw).strip().lower() in {'1', 'true', 'on', 'yes'}
    value = storyos_config.get_path(storyos_config.load_config(), config_key)
    if not isinstance(value, bool):
        raise BackendError(f'CONFIG_INVALID: {config_key} must be bool')
    return value

def valid_image(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size < 16:
        return False
    header = path.read_bytes()[:16]
    return header.startswith(PNG) or header.startswith(JPEG)


def provider_raw_candidate_viable(path: Path) -> bool:
    """Whether a provider candidate is large enough to enter production RAW flow.

    ``valid_image`` deliberately stays a lightweight file/signature check because
    it is also used for references and recovery artifacts. Production provider
    output has a stronger minimum-dimension contract: tiny placeholder/thumbnail
    images (for example 100x100) must not hide a transport failure recorded by
    the same Codex invocation.
    """
    if not valid_image(path):
        return False
    try:
        with Image.open(path) as image:
            return min(int(image.width), int(image.height)) >= provider_capability.PROVIDER_RAW_MIN_DIMENSION
    except (OSError, ValueError):
        return False


def logged_backend_failure(raw_log_text: str, *, returncode: int,
                           candidate_valid: bool, candidate_viable: bool) -> str | None:
    """Prefer the invocation's technical root cause before a degenerate RAW error.

    A full-size valid candidate wins over incidental warning text. But when the
    only artifact is invalid or below the production minimum dimension, inspect
    the same invocation log first so NETWORK_ERROR / capacity / auth / transport
    failures are preserved instead of being overwritten later by a 100x100 RAW
    validation error.
    """
    if int(returncode) == 0 and candidate_valid and candidate_viable:
        return None
    relevant = runtime_log_policy.provider_relevant_codex_text(str(raw_log_text or ""))
    # The compact provider projection intentionally drops some generic transport
    # wording. Keep the original bounded tail as a fallback so a real network
    # failure is not lost merely because the projection found no provider token.
    tail = (relevant[-6000:] or str(raw_log_text or "")[-6000:])
    return image_model_policy.classify_backend_error(tail, source="image_backend")

def runner_generated_artifact_evidence(request_id: str | None) -> dict[str, object]:
    """Read only durable artifact metadata for one completed user-runner request."""
    value = str(request_id or "").strip()
    if not value:
        return {"result_found": False, "generated_artifact_count": None}
    try:
        result = codex_user_runner.read_task_result(value)
    except Exception:
        return {"result_found": False, "generated_artifact_count": None}
    if not isinstance(result, dict):
        return {"result_found": False, "generated_artifact_count": None}
    evidence = result.get("evidence") if isinstance(result.get("evidence"), dict) else {}
    artifacts = evidence.get("generated_artifacts")
    if not isinstance(artifacts, list):
        return {
            "result_found": True,
            "generated_artifact_count": None,
            "returncode": result.get("returncode"),
        }
    return {
        "result_found": True,
        "generated_artifact_count": len(artifacts),
        "returncode": result.get("returncode"),
    }


def resolve_codex(raw: str | None) -> Path:
    explicit = bool(raw or os.environ.get("CODEX_EXE"))
    if not runtime_router.local_codex_image_allowed(explicit=explicit):
        runtime, _ = runtime_router.detect()
        image_runtime, _ = runtime_router.image_execution_runtime()
        raise BackendError(
            f'LOCAL_CODEX_IMAGE_DISABLED_FOR_RUNTIME: runtime={runtime}; image_runtime={image_runtime}; '
            'select execution.image.executor=CODEX or pass an explicit Codex executable'
        )
    value = raw or os.environ.get("CODEX_EXE")
    # On Windows prefer the newest ChatGPT Desktop bundled Codex CLI over PATH.
    # The real V2.4 smoke found an older PATH codex that could not start while the
    # desktop-bundled CLI was healthy and had the user's ChatGPT/Codex login.
    if not value and os.name == "nt":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            root = Path(local) / "OpenAI" / "Codex" / "bin"
            candidates = []
            if root.is_dir():
                candidates.extend(root.glob("*/codex.exe"))
                candidates.extend(root.glob("codex.exe"))
            candidates = [p for p in candidates if p.is_file()]
            if candidates:
                value = str(max(candidates, key=lambda p: p.stat().st_mtime_ns))
    import codex_cli_contract
    try:
        return codex_cli_contract.resolve_path(value)
    except codex_cli_contract.CodexCliContractError as exc:
        raise BackendError(str(exc)) from exc

def command_prefix(codex: Path) -> list[str]:
    import codex_cli_contract
    return codex_cli_contract.command_prefix(codex)


def execution_command_prefix(codex: Path) -> list[str]:
    """Let the interactive runner resolve its own Codex executable.

    A SYSTEM-side absolute Codex path belongs to the service account install
    context and may point at a partially-updated Desktop bundle. Across the
    user-mode bridge, pass only the logical codex head so the runner selects
    the executable from the signed-in interactive user environment.
    """
    if codex_user_runner.bridge_required():
        return ["codex"]
    return command_prefix(codex)


def provider_size(width: int, height: int) -> str:
    return f'{width}x{height}'


def controller_args(episode: Path | str | None = None) -> list[str]:
    if str(os.environ.get("STORY_OS_IMAGE_PROVIDER_ROUTE") or "").strip().lower() == "api_http":
        raise BackendError("API_KEY_DIRECT_IMAGE_EXECUTOR_REQUIRED")
    if episode is None:
        controller = _IMAGE_CONTROLLER_POLICY
    else:
        # Production workers must bind the controller to the same frozen
        # Episode Policy used by the scheduler and payload resolver. The
        # module-level policy remains only for legacy CLI/self-test callers.
        errors = model_policy.validate_bound_policy(Path(episode).resolve())
        if errors:
            raise BackendError("MODEL_POLICY_NOT_FROZEN: " + "; ".join(errors))
        controller = model_policy.resolve("image.controller", episode=Path(episode).resolve())
    return [
        '-m', str(controller["model"]),
        '-c', f'model_reasoning_effort="{controller["reasoning_effort"]}"',
    ]




def _subscription_provider_args() -> list[str]:
    """Force the ChatGPT/Codex subscription endpoint for the login-auth lane."""
    return [
        '-c', 'model_provider="openai"',
        '-c', 'openai_base_url="https://chatgpt.com/backend-api/codex"',
    ]


def transport_args(model: str, effort: str) -> list[str]:
    model = str(model or "").strip()
    effort = str(effort or "").strip().lower() or "low"
    if not model:
        raise BackendError("LOGIN_AUTH_TRANSPORT_MODEL_REQUIRED")
    # Provider routing is a per-dispatch responsibility of codex_user_runner.
    # Pinning the native subscription URL here would turn this adapter into a
    # second transport authority and bypass OpenCodex -> native fallback.
    return [
        '-m', model,
        '-c', f'model_reasoning_effort="{effort}"',
    ]


_LOGIN_CATALOG_SOURCE = "LOGIN_ACCOUNT_MODEL_CATALOG"
_PHASE5A_CANARY_TYPE = "PHASE5A_COLLABORATIVE_REGRESSION"
_PHASE5A_PAYLOAD_DISPATCH_GRANT: ContextVar[dict | None] = ContextVar(
    "storyos_phase5a_payload_dispatch_grant", default=None
)
_PHASE5A_READINESS_SIGNING_KEY = secrets.token_bytes(32)


def _catalog_reasoning_levels(row: dict) -> list[str]:
    levels = row.get("supported_reasoning_levels") or []
    normalized = []
    for level in levels:
        if isinstance(level, str):
            normalized.append(level)
        elif isinstance(level, dict) and level.get("effort"):
            normalized.append(str(level["effort"]))
    return sorted(set(normalized))


def _catalog_image_tool_capability(row: dict) -> str:
    """Catalog rows are not the runtime/session tool authority in CLI 0.153.4.

    ``experimental_supported_tools`` and ``tool_mode`` are optional catalog
    metadata, not an exhaustive statement of what an enabled session exposes.
    They are fingerprinted for diagnosis but never grant or deny runtime tool
    capability by themselves.
    """
    return "UNKNOWN"


def _catalog_tool_names(row: dict, key: str) -> list[str] | None:
    value = row.get(key)
    if not isinstance(value, list):
        return None
    names = []
    for item in value:
        if isinstance(item, str):
            names.append(item.strip().lower())
        elif isinstance(item, dict):
            name = item.get("name") or item.get("tool") or item.get("type")
            if isinstance(name, str):
                names.append(name.strip().lower())
    return sorted(set(name for name in names if name))


def _catalog_candidates(payload: dict, *, target_model: str | None = None,
                        target_effort: str | None = None) -> list[dict]:
    rows = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    controller_model = str(_IMAGE_CONTROLLER_POLICY.get("model") or "")
    requested_model = str(target_model or "").strip()
    requested_effort = str(target_effort or "").strip().lower()
    candidates = []
    safe_catalog_entries = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        slug = str(row.get("slug") or "").strip()
        if not slug:
            continue
        visibility = str(row.get("visibility") or "")
        priority_value = row.get("priority")
        priority = int(priority_value) if priority_value is not None else 9999
        levels = _catalog_reasoning_levels(row)
        safe_catalog_entries.append({
            "slug": slug,
            "visibility": visibility,
            "priority": priority,
            "supported_reasoning_levels": levels,
            "supported_tools": _catalog_tool_names(row, "supported_tools"),
            "experimental_supported_tools": _catalog_tool_names(row, "experimental_supported_tools"),
            "tool_mode": str(row.get("tool_mode") or ""),
        })
        if visibility != "list":
            continue
        if requested_model:
            if slug != requested_model:
                continue
            effort = requested_effort or str(row.get("default_reasoning_level") or "medium")
            if levels and effort not in levels:
                continue
        else:
            # Legacy generic catalog discovery excludes the business controller.
            # Production Phase5 transport discovery below supplies an explicit
            # target and therefore never falls through to an unrelated Sol model.
            if slug == controller_model:
                continue
            effort = "low" if "low" in levels else str(row.get("default_reasoning_level") or "medium")
        candidates.append({
            "model": slug,
            "effort": effort,
            "priority": priority,
            "candidate_catalog_member": True,
            "catalog_source": _LOGIN_CATALOG_SOURCE,
            "tool_capability_state": _catalog_image_tool_capability(row),
            "tool_capability_source": "LOGIN_ACCOUNT_MODEL_CATALOG",
        })
    candidates.sort(key=lambda row: (row["priority"], row["model"]))
    safe_catalog_entries.sort(key=lambda row: row["slug"])
    catalog_sha256 = hashlib.sha256(json.dumps(
        safe_catalog_entries, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")).hexdigest()
    for candidate in candidates:
        candidate["catalog_sha256"] = catalog_sha256
        candidate["catalog_entry_count"] = len(safe_catalog_entries)
    return candidates


def _subscription_model_catalog_with_evidence(codex: Path) -> dict[str, object]:
    cmd = execution_command_prefix(codex) + ['debug', 'models', *_subscription_provider_args()]
    completed = codex_user_runner.run_codex(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=runtime_timeout_policy.seconds("codex_auth_probe"),
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
        task_type="smoke",
        codex_home_mode="inherit",
    )
    raw = str(completed.stdout or "").strip()
    if completed.returncode != 0:
        raise BackendError(f"LOGIN_AUTH_MODEL_CATALOG_FAILED: rc={completed.returncode}")
    start = raw.find("{")
    if start < 0:
        raise BackendError("LOGIN_AUTH_MODEL_CATALOG_INVALID")
    try:
        payload = json.loads(raw[start:])
    except json.JSONDecodeError as exc:
        raise BackendError("LOGIN_AUTH_MODEL_CATALOG_INVALID") from exc
    rows = _catalog_candidates(
        payload,
        target_model=CODEX_IMAGE_CONTROLLER_MODEL,
        target_effort=CODEX_IMAGE_REASONING_EFFORT,
    )
    if not rows:
        raise BackendError("LOGIN_AUTH_TRANSPORT_MODEL_UNAVAILABLE")
    return {
        "catalog_source": _LOGIN_CATALOG_SOURCE,
        "catalog_sha256": rows[0]["catalog_sha256"],
        "catalog_entry_count": rows[0]["catalog_entry_count"],
        "candidate_models": [str(row["model"]) for row in rows],
        "candidates": rows,
    }


def _subscription_model_catalog(codex: Path) -> list[dict]:
    """Compatibility wrapper for callers that only need candidates."""
    evidence = _subscription_model_catalog_with_evidence(codex)
    return list(evidence["candidates"])


def _validated_phase5a_canary_scope(ep: Path, canary_id: str,
                                   expected: dict | None = None, *,
                                   allow_running: bool = False,
                                   require_claim: bool = False) -> dict | None:
    """Re-read the dedicated Canary contract and its authorities fail-closed."""
    try:
        episode = Path(ep).resolve()
        value = str(canary_id or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", value) or ".." in value:
            return None
        expected_dir = (ROOT / ".codex_tmp" / "phase5a" / value).resolve()
        if episode != expected_dir:
            return None
        marker_path = episode / "meta" / "phase5a-canary.json"
        marker = json.loads(marker_path.read_text(encoding="utf-8-sig"))
        if marker != {
            "workspace_class": "TEST_ONLY",
            "promotion_class": "NON_PROMOTABLE",
            "canary_type": _PHASE5A_CANARY_TYPE,
            "canary_id": value,
        }:
            return None

        import generation_attempt_authority
        import logical_asset_identity
        import model_policy
        import scheduler_core

        if model_policy.validate_bound_policy(episode):
            return None
        controller = model_policy.resolve("image.controller", episode=episode)
        payload = model_policy.resolve("image.payload", episode=episode)
        if (controller.get("model_policy_sha256") != payload.get("model_policy_sha256")
                or not re.fullmatch(r"[0-9a-f]{64}", str(controller.get("model_policy_sha256") or ""))):
            return None
        queue = scheduler_core.load_queue(episode)
        # Superseded rows are immutable historical evidence, not active Canary
        # production items. Keep them in Queue history but exclude them from the
        # single-current-item Phase5A scope invariant.
        items = [
            row for row in queue.get("items") or []
            if isinstance(row, dict)
            and str(row.get("status") or "") != "superseded"
        ]
        if len(items) != 1:
            return None
        item = items[0]
        allowed_status = {"queued", "running"} if allow_running else {"queued"}
        if (int(item.get("frame") or 0) != 1 or item.get("kind") != "original"
                or item.get("scope") != "batch" or item.get("status") not in allowed_status):
            return None
        logical_key = logical_asset_identity.frame_asset_key(episode, 1)
        state = generation_attempt_authority.load_asset_state(episode, logical_key)
        consumed = int(state.get("attempts_consumed") or 0)
        remaining = int(state.get("remaining_attempts") or 0)
        active = state.get("active_attempt_index")
        attempt_reason = str(item.get("generation_attempt_reason") or "PRIMARY_GENERATION")
        technical_source = str(item.get("technical_retry_source_code") or "")
        primary_scope = (
            consumed == 0 and remaining == 2 and active is None
            and attempt_reason == "PRIMARY_GENERATION"
            and not technical_source
        )
        technical_retry_scope = (
            consumed == 1 and remaining == 1 and active is None
            and attempt_reason == "TECHNICAL_RETRY"
            and technical_source == "ASPECT_RATIO_MISMATCH"
        )
        if not (primary_scope or technical_retry_scope):
            return None
        if (str(payload.get("model") or "") != "gpt-image-2.5-flare"
                or str(payload.get("quality") or "").lower() != "high"):
            return None
        if require_claim:
            claims_root = ROOT / ".codex_tmp" / "phase5a"
            global_path = claims_root / ".phase5a-collaborative-canary-claim.json"
            replacement_path = claims_root / ".phase5a-collaborative-canary-replacement.json"
            global_claim = json.loads(global_path.read_text(encoding="utf-8-sig"))
            expected_workspace = str(episode)
            claim_valid = bool(
                global_claim.get("canary_type") == _PHASE5A_CANARY_TYPE
                and global_claim.get("canary_id") == value
                and global_claim.get("workspace") == expected_workspace
            )
            if not claim_valid and replacement_path.is_file():
                replacement = json.loads(replacement_path.read_text(encoding="utf-8-sig"))
                claim_valid = bool(
                    global_claim.get("canary_type") == _PHASE5A_CANARY_TYPE
                    and replacement.get("canary_type") == _PHASE5A_CANARY_TYPE
                    and replacement.get("canary_id") == value
                    and replacement.get("workspace") == expected_workspace
                    and replacement.get("previous_canary_id") == global_claim.get("canary_id")
                    and replacement.get("previous_workspace") == global_claim.get("workspace")
                )
            if not claim_valid:
                epoch_dir = claims_root / ".phase5a-validation-epochs"
                epoch_rows = []
                if epoch_dir.is_dir():
                    for path in sorted(epoch_dir.glob("epoch-*.json")):
                        if not re.fullmatch(r"epoch-\d{4}\.json", path.name):
                            return None
                        row = json.loads(path.read_text(encoding="utf-8-sig"))
                        epoch_rows.append(row)
                if epoch_rows:
                    latest = epoch_rows[-1]
                    claim_valid = bool(
                        latest.get("canary_type") == _PHASE5A_CANARY_TYPE
                        and latest.get("canary_id") == value
                        and latest.get("workspace") == expected_workspace
                        and int(latest.get("validation_epoch") or 0) >= 2
                    )
            if not claim_valid:
                return None
        identity = {
            "canary_type": _PHASE5A_CANARY_TYPE,
            "canary_id": value,
            "episode_path": str(episode),
            "queue_item_id": str(item.get("id") or ""),
            "queue_item_count": 1,
            "frame": 1,
            "kind": "original",
            "scope": "batch",
            "logical_asset_key": logical_key,
            "attempts_consumed": consumed,
            "remaining_attempts": remaining,
            "active_attempt_index": active,
            "generation_attempt_reason": attempt_reason,
            "technical_retry_source_code": technical_source,
            "model_policy_sha256": str(controller["model_policy_sha256"]),
            "payload_model": str(payload.get("model") or ""),
            "payload_quality": str(payload.get("quality") or "").lower(),
        }
        if expected is not None:
            for key in (
                "queue_item_id", "logical_asset_key", "model_policy_sha256",
                "payload_model", "payload_quality", "attempts_consumed",
                "remaining_attempts", "generation_attempt_reason",
                "technical_retry_source_code",
            ):
                if str(expected.get(key) or "") != str(identity[key] or ""):
                    return None
        return identity
    except Exception:
        return None


def _phase5a_readiness_signature(readiness: dict) -> str:
    """Sign a minimal in-process readiness identity; caller dictionaries alone authorize nothing."""
    scope = readiness.get("phase5a_scope") if isinstance(readiness.get("phase5a_scope"), dict) else {}
    bound = {
        "canary_type": scope.get("canary_type"),
        "canary_id": scope.get("canary_id"),
        "episode_path": scope.get("episode_path"),
        "queue_item_id": scope.get("queue_item_id"),
        "logical_asset_key": scope.get("logical_asset_key"),
        "attempts_consumed": scope.get("attempts_consumed"),
        "remaining_attempts": scope.get("remaining_attempts"),
        "generation_attempt_reason": scope.get("generation_attempt_reason"),
        "technical_retry_source_code": scope.get("technical_retry_source_code"),
        "model_policy_sha256": scope.get("model_policy_sha256"),
        "payload_model": readiness.get("payload_model"),
        "payload_quality": readiness.get("payload_quality"),
        "transport_model": readiness.get("transport_model"),
        "transport_effort": readiness.get("transport_effort"),
        "candidate_catalog_member": readiness.get("candidate_catalog_member"),
        "catalog_source": readiness.get("catalog_source"),
        "catalog_sha256": readiness.get("catalog_sha256"),
        "tool_capability_state": readiness.get("tool_capability_state"),
        "tool_capability_source": readiness.get("tool_capability_source"),
        "session_start": readiness.get("session_start"),
        "image_generation_visible_secondary": readiness.get("image_generation_visible_secondary"),
        "image_generation_called": readiness.get("image_generation_called"),
        "image_attempt_authority_called": readiness.get("image_attempt_authority_called"),
        "status": readiness.get("status"),
    }
    message = json.dumps(bound, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hmac.new(_PHASE5A_READINESS_SIGNING_KEY, message, hashlib.sha256).hexdigest()


@contextmanager
def phase5a_payload_dispatch_context(ep: Path, canary_id: str,
                                     canary_context: dict,
                                     payload_readiness: dict):
    """Authorize exactly one UNKNOWN-capability image item in the fixed Canary.

    This in-memory context is intentionally not a runtime option or a persisted
    bypass.  The worker consumes the grant once, and only after rechecking its
    queue item, policy, payload binding, and current Attempt state.
    """
    identity = _validated_phase5a_canary_scope(
        Path(ep), canary_id, canary_context, require_claim=True,
    )
    readiness_scope = (payload_readiness.get("phase5a_scope")
                       if isinstance(payload_readiness.get("phase5a_scope"), dict) else {})
    scope_matches = bool(identity) and all(
        str(readiness_scope.get(key) or "") == str(identity.get(key) or "")
        for key in (
            "canary_type", "canary_id", "episode_path", "queue_item_id",
            "logical_asset_key", "attempts_consumed", "remaining_attempts",
            "generation_attempt_reason", "technical_retry_source_code",
            "model_policy_sha256", "payload_model", "payload_quality",
        )
    )
    if (identity is None
            or not scope_matches
            or str(payload_readiness.get("status") or "") != "READY_FOR_REAL_CAPABILITY_PROOF"
            or payload_readiness.get("tool_capability_state") != "UNKNOWN"
            or payload_readiness.get("image_generation_called") is not False
            or payload_readiness.get("image_attempt_authority_called") is not False
            or payload_readiness.get("session_start") != "PASS"
            or payload_readiness.get("candidate_catalog_member") is not True
            or payload_readiness.get("catalog_source") != _LOGIN_CATALOG_SOURCE
            or not re.fullmatch(r"[0-9a-f]{64}", str(payload_readiness.get("catalog_sha256") or ""))
            or not str(payload_readiness.get("transport_model") or "")
            or not str(payload_readiness.get("transport_effort") or "")
            or not hmac.compare_digest(
                str(payload_readiness.get("_phase5a_readiness_signature") or ""),
                _phase5a_readiness_signature(payload_readiness),
            )):
        raise BackendError("PHASE5A_PAYLOAD_DISPATCH_GRANT_DENIED")
    grant = {
        **identity,
        "payload_readiness": dict(payload_readiness),
        "consumed": False,
    }
    token = _PHASE5A_PAYLOAD_DISPATCH_GRANT.set(grant)
    try:
        yield
    finally:
        _PHASE5A_PAYLOAD_DISPATCH_GRANT.reset(token)


def consume_phase5a_payload_dispatch_grant(ep: Path, item: dict, *,
                                           payload_model: str,
                                           payload_quality: str,
                                           policy_sha256: str) -> dict | None:
    """Consume the current task-local Phase5A grant once; ordinary work gets None."""
    grant = _PHASE5A_PAYLOAD_DISPATCH_GRANT.get()
    if not isinstance(grant, dict) or grant.get("consumed"):
        return None
    identity = _validated_phase5a_canary_scope(
        Path(ep), str(grant.get("canary_id") or ""), grant,
        allow_running=True, require_claim=True,
    )
    if identity is None:
        return None
    if (str(item.get("id") or "") != identity["queue_item_id"]
            or int(item.get("frame") or 0) != 1
            or item.get("kind") != "original"
            or item.get("scope") != "batch"
            or str(payload_model or "") != identity["payload_model"]
            or str(payload_quality or "").lower() != identity["payload_quality"]
            or str(policy_sha256 or "") != identity["model_policy_sha256"]):
        return None
    grant["consumed"] = True
    evidence = dict(grant["payload_readiness"])
    evidence["phase5a_dispatch_grant_consumed"] = True
    evidence["phase5a_canary_id"] = identity["canary_id"]
    evidence["phase5a_queue_item_id"] = identity["queue_item_id"]
    return evidence


def _probe_event_calls_image_generation(value: object) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if (str(key) in {"type", "tool", "tool_name", "name", "function"}
                    and str(child).strip() in {"image_generation", "image_generation_call"}):
                return True
            if _probe_event_calls_image_generation(child):
                return True
    elif isinstance(value, list):
        return any(_probe_event_calls_image_generation(child) for child in value)
    return False


def _transport_probe_completed(raw: str) -> bool:
    """Accept only a completed exact sentinel with no image tool invocation."""
    result = _inspect_transport_probe(raw)
    return bool(result["sentinel_completed"] and result["turn_completed"]
                and result["image_generation_call_count"] == 0
                and not result["malformed_jsonl"])


def _inspect_transport_probe(raw: str) -> dict[str, object]:
    """Return safe probe facts without retaining or returning model output."""
    sentinel = False
    turn_completed = False
    image_generation_call_count = 0
    malformed_jsonl = False
    diagnostic_noise_line_count = 0
    for line in str(raw or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            row = json.loads(stripped)
        except (TypeError, ValueError):
            # The runner merges stderr into the JSONL stream. Ordinary CLI
            # diagnostics are not protocol corruption. JSON-looking frames
            # that fail decoding still fail closed.
            if stripped.startswith(("{", "[")):
                malformed_jsonl = True
            else:
                diagnostic_noise_line_count += 1
            continue
        if not isinstance(row, dict):
            continue
        if _probe_event_calls_image_generation(row):
            image_generation_call_count += 1
        if row.get("type") == "turn.completed":
            turn_completed = True
        item = row.get("item") if isinstance(row.get("item"), dict) else {}
        if (row.get("type") == "item.completed"
                and item.get("type") == "agent_message"
                and str(item.get("text") or "").strip() == "STORYOS_TRANSPORT_OK"):
            sentinel = True
    return {
        "sentinel_completed": sentinel,
        "turn_completed": turn_completed,
        "image_generation_call_count": image_generation_call_count,
        "malformed_jsonl": malformed_jsonl,
        "diagnostic_noise_line_count": diagnostic_noise_line_count,
    }


def _inspect_tool_visibility_probe(raw: str) -> dict[str, object]:
    """Parse one exact secondary visibility answer and protocol completion facts."""
    turn_completed = False
    visibility: bool | None = None
    visibility_answer_count = 0
    image_generation_call_count = 0
    malformed_jsonl = False
    diagnostic_noise_line_count = 0
    for line in str(raw or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            row = json.loads(stripped)
        except (TypeError, ValueError):
            if stripped.startswith(("{", "[")):
                malformed_jsonl = True
            else:
                diagnostic_noise_line_count += 1
            continue
        if not isinstance(row, dict):
            continue
        if _probe_event_calls_image_generation(row):
            image_generation_call_count += 1
        if row.get("type") == "turn.completed":
            turn_completed = True
        item = row.get("item") if isinstance(row.get("item"), dict) else {}
        if row.get("type") == "item.completed" and item.get("type") == "agent_message":
            try:
                answer = json.loads(str(item.get("text") or "").strip())
            except (TypeError, ValueError):
                continue
            if (isinstance(answer, dict) and set(answer) == {"image_generation_visible"}
                    and isinstance(answer.get("image_generation_visible"), bool)):
                visibility = answer["image_generation_visible"]
                visibility_answer_count += 1
    valid = bool(turn_completed and visibility_answer_count == 1 and visibility is not None
                 and image_generation_call_count == 0 and not malformed_jsonl)
    return {
        "visibility_response_completed": visibility is not None,
        "visibility_response_count": visibility_answer_count,
        "image_generation_visible_secondary": visibility,
        "turn_completed": turn_completed,
        "image_generation_call_count": image_generation_call_count,
        "malformed_jsonl": malformed_jsonl,
        "diagnostic_noise_line_count": diagnostic_noise_line_count,
        "probe_result_valid": valid,
    }

def _timeout_probe_result(exc: Exception) -> str:
    return _timeout_probe_result_details(exc)[0]


def _timeout_probe_result_details(exc: Exception) -> tuple[str, bool]:
    remote = getattr(exc, "remote", None)
    if isinstance(remote, dict):
        request_id = str(remote.get("request_id") or "").strip()
    else:
        request_id = str(getattr(remote, "request_id", "") or "").strip()
    if not request_id:
        return "", False
    try:
        result = codex_user_runner.read_task_result(request_id)
    except Exception:
        return "", False
    if not isinstance(result, dict):
        return "", False
    encoded = str(result.get("output_base64") or "")
    if not encoded:
        return "", True
    try:
        output = base64.b64decode(encoded, validate=True)
        return output.decode("utf-8"), True
    except Exception:
        return "", True


def _probe_transport_model_diagnostic(codex: Path, model: str, effort: str,
                                      *, candidate_provenance: dict | None = None,
                                      tool_visibility_probe: bool = False) -> dict[str, object]:
    cmd = execution_command_prefix(codex) + [
        'exec', '--skip-git-repo-check', '--ephemeral', '--ignore-rules',
        '-c', 'skills.include_instructions=false',
        '-c', 'project_doc_max_bytes=0',
        '--enable', 'image_generation',
        *transport_args(model, effort),
        '-s', 'read-only', '--json', '-',
    ]
    resolution = "user_runner" if codex_user_runner.bridge_required() else "direct_cli"
    provenance = candidate_provenance if isinstance(candidate_provenance, dict) else {}
    candidate_member = (
        provenance.get("candidate_catalog_member") is True
        and provenance.get("catalog_source") == _LOGIN_CATALOG_SOURCE
        and str(provenance.get("model") or "") == str(model)
        and str(provenance.get("effort") or "") == str(effort)
        and bool(re.fullmatch(r"[0-9a-f]{64}", str(provenance.get("catalog_sha256") or "")))
    )
    if not candidate_member:
        return {
            "status": "BLOCKED",
            "failure_class": "LOGIN_AUTH_TRANSPORT_PROBE_INVALID_CANDIDATE",
            "failure_stage": "candidate_attestation",
            "candidate_model": str(model),
            "candidate_effort": str(effort),
            "candidate_priority": provenance.get("priority"),
            "candidate_catalog_member": False,
            "catalog_source": provenance.get("catalog_source"),
            "catalog_sha256": provenance.get("catalog_sha256"),
            "image_generation_call_count": 0,
            "image_attempt_authority_called": False,
            "image_generation_called": False,
        }
    candidate_identity = {
        "candidate_model": str(model),
        "candidate_effort": str(effort),
        "candidate_priority": provenance.get("priority"),
        "candidate_catalog_member": True,
        "catalog_source": _LOGIN_CATALOG_SOURCE,
        "catalog_sha256": str(provenance["catalog_sha256"]),
        "catalog_entry_count": provenance.get("catalog_entry_count"),
        "tool_capability_state": provenance.get("tool_capability_state", "UNKNOWN"),
        "tool_capability_source": provenance.get("tool_capability_source", _LOGIN_CATALOG_SOURCE),
        "image_attempt_authority_called": False,
        "image_generation_called": False,
    }
    prompt = (
        'Do not call any tool. Inspect only the tools made available to this session. '
        'Return exactly one JSON object: {"image_generation_visible":true} or '
        '{"image_generation_visible":false}. Do not infer from model knowledge. '
        'Answer only from the actual tool registry exposed to this session.'
        if tool_visibility_probe else
        "Return exactly STORYOS_TRANSPORT_OK and do not call any tool."
    )
    try:
        completed = codex_user_runner.run_model_codex(
            cmd,
            input=prompt,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=runtime_timeout_policy.seconds(
                "image_tool_visibility_probe" if tool_visibility_probe else "codex_auth_probe"),
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
            task_type="smoke",
            codex_home_mode="inherit",
        )
        raw = str(completed.stdout or "")
        facts = (_inspect_tool_visibility_probe(raw) if tool_visibility_probe
                 else _inspect_transport_probe(raw))
        failure_facts = _safe_transport_failure_facts(raw, int(completed.returncode))
        session_started = bool(
            tool_visibility_probe
            and int(completed.returncode) == 0
            and facts["turn_completed"]
            and facts["image_generation_call_count"] == 0
            and not facts["malformed_jsonl"]
        )
        passed = bool(int(completed.returncode) == 0 and facts["turn_completed"]
                      and facts["image_generation_call_count"] == 0
                      and not facts["malformed_jsonl"]
                      and (session_started if tool_visibility_probe
                           else facts["sentinel_completed"]))
        failure_class = None if passed else (
            failure_facts["failure_class"] if int(completed.returncode) != 0
            else "LOGIN_AUTH_TRANSPORT_PROBE_INVALID_RESULT"
        )
        return {
            **facts,
            **failure_facts,
            **candidate_identity,
            "image_generation_called": bool(facts["image_generation_call_count"]),
            "status": "PASS" if passed else "BLOCKED",
            "returncode": int(completed.returncode),
            "timed_out": False,
            "request_id": None,
            "durable_result_found": False,
            "exception_class": None,
            "codex_resolution": resolution,
            "transport_model_source": "LOGIN_CATALOG_PROBE",
            "failure_class": failure_class,
            "failure_stage": None if passed else "transport_probe",
            "session_start": "PASS" if session_started else None,
            "probe_kind": "TOOL_VISIBILITY_TEXT_PROBE" if tool_visibility_probe else "TRANSPORT_SENTINEL_PROBE",
            "tool_visibility_evidence_level": "SECONDARY_ATTESTATION" if tool_visibility_probe else None,
        }
    except codex_user_runner.CodexUserRunnerTimeout as exc:
        remote = getattr(exc, "remote", None)
        if isinstance(remote, dict):
            request_id = str(remote.get("request_id") or "").strip() or None
        else:
            request_id = str(getattr(remote, "request_id", "") or "").strip() or None
        raw, durable_result_found = _timeout_probe_result_details(exc)
        facts = (_inspect_tool_visibility_probe(raw) if tool_visibility_probe
                 else _inspect_transport_probe(raw))
        session_started = bool(
            tool_visibility_probe
            and facts["turn_completed"]
            and facts["image_generation_call_count"] == 0
            and not facts["malformed_jsonl"]
        )
        passed = bool(request_id and durable_result_found and raw and (
            session_started if tool_visibility_probe else
            facts["sentinel_completed"] and facts["turn_completed"]
            and facts["image_generation_call_count"] == 0
            and not facts["malformed_jsonl"]
        ))
        return {
            **facts,
            **candidate_identity,
            "image_generation_called": bool(facts["image_generation_call_count"]),
            "status": "PASS_WITH_CLEANUP_TIMEOUT" if passed else "BLOCKED",
            "returncode": _safe_remote_int(remote, "returncode"),
            "timed_out": True,
            "request_id": request_id,
            "durable_result_found": durable_result_found,
            "exception_class": type(exc).__name__,
            "codex_resolution": resolution,
            "transport_model_source": "LOGIN_CATALOG_PROBE",
            "failure_class": None if passed else "LOGIN_AUTH_TRANSPORT_PROBE_TIMEOUT",
            "failure_stage": None if passed else "transport_probe",
            "session_start": "PASS" if passed and tool_visibility_probe else None,
            "probe_kind": "TOOL_VISIBILITY_TEXT_PROBE" if tool_visibility_probe else "TRANSPORT_SENTINEL_PROBE",
            "tool_visibility_evidence_level": "SECONDARY_ATTESTATION" if tool_visibility_probe else None,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            **candidate_identity,
            "status": "BLOCKED",
            "failure_class": "LOGIN_AUTH_TRANSPORT_PROBE_TIMEOUT",
            "failure_stage": "transport_probe",
            "candidate_model": str(model),
            "returncode": None,
            "timed_out": True,
            "request_id": None,
            "durable_result_found": False,
            "sentinel_completed": False,
            "turn_completed": False,
            "image_generation_call_count": 0,
            "exception_class": type(exc).__name__,
            "codex_resolution": resolution,
            "transport_model_source": "LOGIN_CATALOG_PROBE",
        }
    except codex_user_runner.CodexUserRunnerUnavailable as exc:
        return {**candidate_identity,
                **_failed_transport_probe(model, resolution, "LOGIN_AUTH_RUNNER_UNAVAILABLE", exc)}
    except codex_user_runner.CodexUserRunnerAuthFailed as exc:
        return {**candidate_identity,
                **_failed_transport_probe(model, resolution, "LOGIN_AUTH_AUTH_FAILED", exc)}
    except Exception as exc:
        return {**candidate_identity,
                **_failed_transport_probe(model, resolution, "LOGIN_AUTH_TRANSPORT_EXEC_FAILED", exc)}


def _safe_remote_int(remote: object, key: str) -> int | None:
    value = remote.get(key) if isinstance(remote, dict) else getattr(remote, key, None)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _safe_request_id(remote: object) -> str | None:
    value = remote.get("request_id") if isinstance(remote, dict) else getattr(remote, "request_id", None)
    request_id = str(value or "").strip()
    if not request_id or len(request_id) > 128 or not re.fullmatch(r"[A-Za-z0-9._:-]+", request_id):
        return None
    return request_id


def _safe_transport_failure_facts(raw: str, returncode: int) -> dict[str, object]:
    """Classify common CLI failures using text transiently, storing no raw output."""
    text = str(raw or "").lower()
    status_match = re.search(r"\b(?:http(?:\s+error)?\s*)?(4\d\d|5\d\d)\b", text)
    http_status = int(status_match.group(1)) if status_match else None
    websocket_attempted = "responses_websocket" in text or "websocket" in text
    if returncode == 0:
        failure_class = None
    elif http_status in {401, 403} or any(term in text for term in ("unauthorized", "authentication failed", "not authenticated", "auth_failed")):
        failure_class = "LOGIN_AUTH_AUTH_FAILED"
    elif "runner unavailable" in text or "user runner unavailable" in text:
        failure_class = "LOGIN_AUTH_RUNNER_UNAVAILABLE"
    elif ("model" in text and any(term in text for term in ("unsupported", "not supported", "unavailable"))) or http_status == 400 and "model" in text:
        failure_class = "LOGIN_AUTH_TRANSPORT_MODEL_UNAVAILABLE"
    elif "image_generation" in text and any(term in text for term in ("unavailable", "not enabled", "not supported", "unknown tool")):
        failure_class = "LOGIN_AUTH_IMAGE_TOOL_CONFIG_UNAVAILABLE"
    else:
        failure_class = "LOGIN_AUTH_TRANSPORT_EXEC_FAILED"
    return {
        "http_status": http_status,
        "websocket_attempted": websocket_attempted,
        "protocol_failure_class": (
            "TRANSPORT_WEBSOCKET_UPGRADE_REJECTED" if http_status == 426 and websocket_attempted else None
        ),
        "failure_class": failure_class,
    }


def _failed_transport_probe(model: str, resolution: str, failure_class: str,
                            exc: Exception) -> dict[str, object]:
    return {
        "status": "BLOCKED",
        "failure_class": failure_class,
        "failure_stage": "transport_probe",
        "candidate_model": str(model),
        "returncode": _safe_remote_int(getattr(exc, "remote", None), "returncode"),
        "timed_out": False,
        "request_id": _safe_request_id(getattr(exc, "remote", None)),
        "durable_result_found": False,
        "sentinel_completed": False,
        "turn_completed": False,
        "image_generation_call_count": 0,
        "exception_class": type(exc).__name__,
        "codex_resolution": resolution,
        "transport_model_source": "LOGIN_CATALOG_PROBE",
    }


def _probe_transport_model(codex: Path, model: str, effort: str) -> tuple[bool, str]:
    """Compatibility wrapper with sanitized evidence only."""
    diagnostic = _probe_transport_model_diagnostic(codex, model, effort)
    status = str(diagnostic.get("status") or "BLOCKED")
    return status.startswith("PASS"), status


def _classify_preflight_exception(exc: Exception, *, stage: str) -> str:
    detail = str(exc).upper()
    if stage == "resolve_codex":
        return "LOGIN_AUTH_RUNNER_UNAVAILABLE"
    if stage == "runner_preflight":
        if "AUTHENTICATION" in detail or "AUTH_FAILED" in detail or "AUTHENTICATION CONTEXT" in detail:
            return "LOGIN_AUTH_AUTH_FAILED"
        return "LOGIN_AUTH_RUNNER_UNAVAILABLE"
    if stage == "model_catalog":
        if "UNAVAILABLE" in detail or "MODEL_UNAVAILABLE" in detail:
            return "LOGIN_AUTH_TRANSPORT_MODEL_UNAVAILABLE"
        return "LOGIN_AUTH_MODEL_CATALOG_FAILED"
    if stage == "transport_probe":
        return "LOGIN_AUTH_TRANSPORT_EXEC_FAILED"
    return "LOGIN_AUTH_IMAGE_TOOL_CONFIG_UNAVAILABLE"


def payload_capability_preflight(*, model: str, quality: str,
                                 codex_raw: str | None = None,
                                 phase5a_canary_id: str | None = None,
                                 phase5a_canary_context: dict | None = None,
                                 allow_unknown_capability_proof: bool = False) -> dict:
    """Prove login-auth transport before any image Attempt is reserved."""
    requested_model = str(model or "").strip()
    requested_quality = str(quality or "").strip().lower()
    if not requested_model or requested_quality != "high":
        return {
            "status": "BLOCKED",
            "failure_class": "PAYLOAD_MODEL_UNSUPPORTED_ON_LOGIN_TRANSPORT",
            "failure_stage": "request_validation",
            "provider": "codex_subscription",
            "image_attempt_authority_called": False,
            "image_generation_called": False,
        }
    stage = "resolve_codex"
    codex_resolution = "unknown"
    try:
        codex_resolution = "user_runner" if codex_user_runner.bridge_required() else "direct_cli"
        codex = resolve_codex(codex_raw)
        stage = "runner_preflight"
        image_runtime_preflight(bridged=codex_user_runner.bridge_required())
        stage = "model_catalog"
        catalog = _subscription_model_catalog_with_evidence(codex)
        candidates = catalog.get("candidates") if isinstance(catalog, dict) else None
        candidate_models = catalog.get("candidate_models") if isinstance(catalog, dict) else None
        catalog_sha256 = str(catalog.get("catalog_sha256") or "") if isinstance(catalog, dict) else ""
        catalog_source = str(catalog.get("catalog_source") or "") if isinstance(catalog, dict) else ""
        catalog_entry_count = catalog.get("catalog_entry_count") if isinstance(catalog, dict) else None
        if (not isinstance(candidates, list) or not isinstance(candidate_models, list)
                or catalog_source != _LOGIN_CATALOG_SOURCE
                or not re.fullmatch(r"[0-9a-f]{64}", catalog_sha256)):
            return {
                "status": "BLOCKED",
                "failure_class": "LOGIN_AUTH_MODEL_CATALOG_INVALID",
                "failure_stage": "model_catalog_attestation",
                "provider": "codex_subscription",
                "image_attempt_authority_called": False,
                "image_generation_called": False,
            }
        canary_scope = None
        if phase5a_canary_id is not None:
            episode_path = (
                str(phase5a_canary_context.get("episode_path") or "")
                if isinstance(phase5a_canary_context, dict) else ""
            )
            canary_scope = _validated_phase5a_canary_scope(
                Path(episode_path),
                phase5a_canary_id, phase5a_canary_context,
                require_claim=True,
            )
            # The fixed global/replacement claim is part of eligibility too;
            # a TEST_ONLY marker or copied runtime context is never sufficient.
            if canary_scope is None:
                return {
                    "status": "BLOCKED",
                    "failure_class": "PHASE5A_PAYLOAD_CAPABILITY_SCOPE_INVALID",
                    "failure_stage": "phase5a_scope_validation",
                    "image_attempt_authority_called": False,
                    "image_generation_called": False,
                }
        eligible = [
            row for row in candidates
            if isinstance(row, dict)
            and row.get("candidate_catalog_member") is True
            and row.get("catalog_source") == _LOGIN_CATALOG_SOURCE
            and row.get("catalog_sha256") == catalog_sha256
            and str(row.get("model") or "") in candidate_models
            and row.get("tool_capability_state") != "EXPLICIT_UNSUPPORTED"
        ]
        if not eligible:
            return {
                "status": "BLOCKED",
                "failure_class": "LOGIN_AUTH_IMAGE_TOOL_UNAVAILABLE_FOR_VISIBLE_MODELS",
                "failure_stage": "model_catalog_capability",
                "catalog_source": catalog_source,
                "catalog_sha256": catalog_sha256,
                "catalog_entry_count": catalog_entry_count,
                "live_candidates": [
                    {
                        "candidate_model": str(row.get("model") or ""),
                        "candidate_effort": str(row.get("effort") or ""),
                        "candidate_priority": row.get("priority"),
                        "candidate_catalog_member": row.get("candidate_catalog_member") is True,
                        "catalog_sha256": catalog_sha256,
                        "tool_capability_state": row.get("tool_capability_state", "UNKNOWN"),
                        "tool_capability_source": row.get("tool_capability_source"),
                    }
                    for row in candidates if isinstance(row, dict)
                ],
                "image_attempt_authority_called": False,
                "image_generation_called": False,
            }
        if (not canary_scope and not allow_unknown_capability_proof
                and not any(row.get("tool_capability_state") == "EXPLICIT_SUPPORTED" for row in eligible)):
            return {
                "status": "BLOCKED",
                "failure_class": "LOGIN_AUTH_IMAGE_TOOL_CAPABILITY_UNKNOWN",
                "failure_stage": "tool_capability_attestation",
                "tool_capability_state": "UNKNOWN",
                "tool_capability_source": "NO_SESSION_TOOL_REGISTRY_API",
                "catalog_source": catalog_source,
                "catalog_sha256": catalog_sha256,
                "catalog_entry_count": catalog_entry_count,
                "image_attempt_authority_called": False,
                "image_generation_called": False,
            }
        failures: list[dict[str, object]] = []
        for index, row in enumerate(eligible[:2]):
            candidate_provenance = {
                **row,
                "catalog_source": catalog_source,
                "catalog_sha256": catalog_sha256,
                "catalog_entry_count": catalog_entry_count,
            }
            stage = "transport_probe"
            capability_state = str(row.get("tool_capability_state") or "UNKNOWN")
            use_visibility_probe = capability_state == "UNKNOWN" and (
                canary_scope is not None or allow_unknown_capability_proof
            )
            diagnostic = _probe_transport_model_diagnostic(
                codex, row["model"], row["effort"],
                candidate_provenance=candidate_provenance,
                tool_visibility_probe=use_visibility_probe,
            )
            diagnostic = {
                **diagnostic,
                "candidate_model": str(row["model"]),
                "candidate_effort": str(row.get("effort") or ""),
                "candidate_priority": row.get("priority"),
                "candidate_catalog_member": True,
                "catalog_source": catalog_source,
                "catalog_sha256": catalog_sha256,
                "catalog_entry_count": catalog_entry_count,
                "tool_capability_state": row.get("tool_capability_state", "UNKNOWN"),
                "tool_capability_source": row.get("tool_capability_source", _LOGIN_CATALOG_SOURCE),
                "image_attempt_authority_called": False,
                "image_generation_called": bool(diagnostic.get("image_generation_call_count", 0)),
            }
            if str(diagnostic.get("status") or "") in {"PASS", "PASS_WITH_CLEANUP_TIMEOUT"}:
                if (capability_state == "UNKNOWN" and not canary_scope
                        and not allow_unknown_capability_proof):
                    failures.append({**diagnostic,
                                     "failure_class": "LOGIN_AUTH_IMAGE_TOOL_CAPABILITY_UNKNOWN"})
                    break
                readiness = {
                    "status": ("READY_FOR_REAL_CAPABILITY_PROOF"
                               if capability_state == "UNKNOWN" else "PASS"),
                    "provider": "codex_subscription",
                    "runner": "codex_user_runner" if codex_user_runner.bridge_required() else "codex_cli",
                    "transport_model": row["model"],
                    "transport_effort": row["effort"],
                    "transport_model_source": "LOGIN_CATALOG_PROBE",
                    "catalog_source": catalog_source,
                    "catalog_sha256": catalog_sha256,
                    "catalog_entry_count": catalog_entry_count,
                    "candidate_catalog_member": True,
                    "candidate_priority": row.get("priority"),
                    "tool_capability_state": capability_state,
                    "tool_capability_source": row.get("tool_capability_source"),
                    "tool_visibility_evidence_level": (
                        "SECONDARY_ATTESTATION" if use_visibility_probe else None
                    ),
                    "image_generation_visible_secondary": (
                        diagnostic.get("image_generation_visible_secondary")
                        if use_visibility_probe else None
                    ),
                    "image_generation_visible": (
                        diagnostic.get("image_generation_visible_secondary")
                        if use_visibility_probe else None
                    ),
                    "tool_registry_attestation": "UNAVAILABLE" if use_visibility_probe else None,
                    "visibility_response_completed": (
                        diagnostic.get("visibility_response_completed")
                        if use_visibility_probe else None
                    ),
                    "session_start": "PASS",
                    "explicit_negative_evidence": False,
                    "transport_probe_status": diagnostic["status"],
                    "transport_probe_diagnostic": diagnostic,
                    "payload_model": requested_model,
                    "payload_quality": requested_quality,
                    "api_key_required": False,
                    "image_attempt_authority_called": False,
                    "image_generation_called": False,
                    "phase5a_scope": canary_scope,
                }
                if readiness["status"] == "READY_FOR_REAL_CAPABILITY_PROOF":
                    readiness["_phase5a_readiness_signature"] = _phase5a_readiness_signature(readiness)
                return readiness
            failure_row = {
                **diagnostic,
                "candidate_model": str(row["model"]),
                "candidate_effort": str(row.get("effort") or ""),
                "tool_capability_state": row.get("tool_capability_state", "UNKNOWN"),
                "tool_capability_source": row.get("tool_capability_source", _LOGIN_CATALOG_SOURCE),
            }
            if (str(diagnostic.get("failure_class") or "") == "LOGIN_AUTH_IMAGE_TOOL_CONFIG_UNAVAILABLE"
                    and not use_visibility_probe):
                failure_row["tool_capability_state"] = "EXPLICIT_UNSUPPORTED"
                failure_row["tool_capability_source"] = "SESSION_TOOL_REJECTION"
            failures.append(failure_row)
            # Only an explicit account/model rejection justifies trying one
            # alternate catalog entry. Other failures are environmental or
            # ambiguous and must not fan out into more live model requests.
            next_candidate_allowed = str(diagnostic.get("failure_class") or "") in {
                "LOGIN_AUTH_TRANSPORT_MODEL_UNAVAILABLE",
                "LOGIN_AUTH_IMAGE_TOOL_CONFIG_UNAVAILABLE",
            }
            if not next_candidate_allowed:
                break
            if index == 1:
                break
        failure_classes = {str(row.get("failure_class") or "") for row in failures}
        failure_priority = (
            "LOGIN_AUTH_AUTH_FAILED",
            "LOGIN_AUTH_RUNNER_UNAVAILABLE",
            "LOGIN_AUTH_TRANSPORT_PROBE_TIMEOUT",
            "LOGIN_AUTH_TRANSPORT_EXEC_FAILED",
            "LOGIN_AUTH_IMAGE_TOOL_CONFIG_UNAVAILABLE",
            "LOGIN_AUTH_IMAGE_TOOL_CAPABILITY_UNKNOWN",
            "LOGIN_AUTH_TRANSPORT_PROBE_INVALID_RESULT",
            "LOGIN_AUTH_TRANSPORT_MODEL_UNAVAILABLE",
        )
        failure_class = next(
            (candidate for candidate in failure_priority if candidate in failure_classes),
            "LOGIN_AUTH_TRANSPORT_MODEL_UNAVAILABLE",
        )
        return {
            "status": "BLOCKED",
            "failure_class": failure_class,
            "failure_stage": "transport_probe",
            "safe_failure_stage": "transport_probe",
            "safe_failure_class": failure_class,
            "provider": "codex_subscription",
            "candidate_failures": failures,
            "catalog_source": catalog_source,
            "catalog_sha256": catalog_sha256,
            "catalog_entry_count": catalog_entry_count,
            "codex_resolution": codex_resolution,
            "transport_model_source": "LOGIN_CATALOG_PROBE",
            "image_attempt_authority_called": False,
            "image_generation_called": False,
        }
    except Exception as exc:
        failure_class = _classify_preflight_exception(exc, stage=stage)
        return {
            "status": "BLOCKED",
            "failure_class": failure_class,
            "safe_failure_stage": stage,
            "safe_failure_class": failure_class,
            "exception_class": type(exc).__name__,
            "provider": "codex_subscription",
            "codex_resolution": codex_resolution,
            "transport_model_source": "LOGIN_CATALOG_PROBE",
            "candidate_model": None,
            "returncode": _safe_remote_int(getattr(exc, "remote", None), "returncode"),
            "timed_out": isinstance(exc, codex_user_runner.CodexUserRunnerTimeout),
            "request_id": _safe_request_id(getattr(exc, "remote", None)),
            "durable_result_found": False,
            "sentinel_completed": False,
            "turn_completed": False,
            "image_generation_call_count": 0,
            "image_attempt_authority_called": False,
            "image_generation_called": False,
        }


def payload_transport_prompt(request: dict, size: str, reference_count: int) -> str:
    """Mechanical image-tool shim. Business semantics are frozen upstream."""
    canvas = request.get("canvas") if isinstance(request.get("canvas"), dict) else {}
    width = int(canvas.get("width") or 0)
    height = int(canvas.get("height") or 0)
    aspect_ratio = str(canvas.get("aspect_ratio") or "").strip()
    if (width <= 0 or height <= 0) and re.fullmatch(r"\d{2,5}x\d{2,5}", str(size or "")):
        width, height = [int(value) for value in str(size).lower().split("x", 1)]
    if not aspect_ratio and width > 0 and height > 0:
        import math
        divisor = math.gcd(width, height)
        aspect_ratio = f"{width // divisor}:{height // divisor}"
    orientation = (
        "PORTRAIT" if height > width else "LANDSCAPE" if width > height else "SQUARE"
    )
    refs = request.get("references") if isinstance(request.get("references"), list) else []
    semantics = []
    for index, row in enumerate(refs, 1):
        kind = str(row.get("kind") or "unspecified") if isinstance(row, dict) else "unspecified"
        if kind == "capture_style":
            rule = ("appearance and physical camera capture only; no copying people, faces, "
                    "actions, scenery, locations, props, wardrobe, screenshot UI, timestamps, or narrative events")
        elif kind == "identity":
            rule = "identity and visual continuity only; do not inherit unrelated scene actions or props"
        elif kind == "location":
            rule = "the story-authorized location only; do not copy reference people or actions"
        elif kind == "prop":
            rule = "the story-authorized prop only; do not copy reference people or actions"
        else:
            rule = "only the use permitted by the locked Frame Contract; never assume identity"
        semantics.append(f"REFERENCE_{index}_KIND: {kind}; ALLOWED_USE: {rule}")
    semantics_block = "\n".join(semantics)
    return (
        "You are an image tool transport only. Do not rewrite, summarize, reinterpret, "
        "improve, or alter the payload. FIRST ACTION: call image_generation exactly once. "
        "Do not call shell, exec, Python, node, web, or any other tool before or after it.\n"
        f"TRANSPORT_REQUEST_FINGERPRINT: {request.get('request_fingerprint')}\n"
        f"EXACT_IMAGE_MODEL: {request.get('payload_model')}\n"
        f"EXACT_IMAGE_QUALITY: {request.get('payload_quality')}\n"
        f"EXACT_CANVAS: {size}\n"
        f"EXACT_ASPECT_RATIO: {aspect_ratio or 'UNSPECIFIED'}\n"
        f"EXACT_ORIENTATION: {orientation}\n"
        f"EXACT_REFERENCE_COUNT: {int(reference_count)}\n"
        "Canvas geometry has higher priority than shot-scale wording. Terms such as "
        "'wide', 'wide shot', 'close-up', or lens language describe composition inside "
        "the locked canvas and MUST NOT change canvas orientation or aspect ratio. "
        "When image_generation exposes size/aspect controls, request the closest control "
        "that preserves EXACT_ASPECT_RATIO and EXACT_ORIENTATION. If exact geometry cannot "
        "be guaranteed by the tool, still call image_generation exactly once using the "
        "closest compatible portrait option; do not skip generation solely because exact "
        "canvas geometry is unavailable. StoryOS validates actual output geometry after "
        "artifact commit.\n"
        "Use each attached image only for its explicitly typed reference purpose; do not add others.\n"
        "The locked Story/Frame Contract exclusively controls scene content and motion; "
        "reference photos do not authorize importing any other story elements.\n"
        f"{semantics_block}\n"
        "<exact_scene_prompt>\n"
        f"{str(request.get('scene_prompt') or '')}\n"
        "</exact_scene_prompt>\n"
        "After image_generation succeeds, stop immediately."
    )


def provider_receipt_model_bindings(
    episode: Path | str, payload_model: str, payload_quality: str
) -> dict[str, object]:
    """Return honest, Episode-bound controller and explicit payload evidence."""
    ep = Path(episode).resolve()
    errors = model_policy.validate_bound_policy(ep)
    if errors:
        raise BackendError("MODEL_POLICY_NOT_FROZEN: " + "; ".join(errors))
    controller = model_policy.resolve("image.controller", episode=ep)
    return {
        "controller_model": controller.get("model"),
        "controller_effort": controller.get("reasoning_effort"),
        "controller_profile": controller.get("profile"),
        "controller_policy_sha256": controller.get("model_policy_sha256"),
        "controller_model_source": "EPISODE_BOUND_RUNTIME_POLICY",
        "payload_model": str(payload_model),
        "payload_quality": str(payload_quality),
        "payload_model_source": "EXPLICIT_RUNTIME_BINDING",
        "payload_provider_attestation": False,
    }

def worker_prompt(scene: str, refs: list[Path], size: str, visual_contract: str | None = None, frame_contract_text: str | None = None, image_model: str = DEFAULT_IMAGE_MODEL, image_quality: str = DEFAULT_IMAGE_QUALITY, strict_model: bool = False) -> str:
    reference_lines = '\n'.join(f'- reference {i}: {p.name}' for i, p in enumerate(refs, 1)) or '- no references'
    visual_block = (
        f'<visual_contract>\n{visual_contract.strip()}\n</visual_contract>\n\n'
        if visual_contract and visual_contract.strip() else ''
    )
    frame_block = (
        f'<frame_contract>\n{frame_contract_text.strip()}\n</frame_contract>\n\n'
        if frame_contract_text and frame_contract_text.strip() else ''
    )
    return (
        'You are an isolated Story OS image worker. FIRST ACTION: call image_generation exactly once. '
        'Do NOT read SKILL.md, AGENTS.md, repository files, or any other instructions; all required production context is already embedded below. '
        'Do NOT call shell/exec/Python/node before image_generation.\n'
        f'IMAGE MODEL CONTRACT: request model={image_model}, quality={image_quality}, canvas={size} exactly. strict={strict_model}. Never silently substitute a different image model or quality. If the image tool cannot honor an explicitly strict model, fail instead of pretending success.\n'
        f'{reference_lines}\n'
        'Use attached images only in the specific roles declared in the locked Frame Contract. '
        'Never treat a capture-style example as permission to copy its people, actions, props or environment. '
        f'Do not invent a different story. Generate in the locked Episode aspect ratio and request exact canvas {size}; do not request a different provider ratio for later cropping.\n\n'
        f'{visual_block}'
        f'{frame_block}'
        f'<scene>\n{scene}\n</scene>\n\n'
        'The visual contract is mandatory production context, not optional inspiration. '
        'After the image tool succeeds, stop immediately and do not call shell, exec, Python, node_repl, or any other tool to copy/move the image. '
        'Story OS will recover the generated artifact from this Codex thread by thread_id. '
        'Do not synthesize an image with Python or reuse a cached image.'
    )


def _reference_proxy(source: Path, workdir: Path, index: int) -> Path:
    """Create a lightweight disposable Codex attachment without changing authority.

    Queue/Ledger provenance continues to bind the original reference path + SHA.
    This proxy exists only inside the temporary worker directory to avoid Windows
    Codex reference-image stalls on multi-megabyte PNG attachments.
    """
    target = workdir / f'reference-{index:02d}.jpg'
    try:
        with Image.open(source) as image:
            image = image.convert('RGB')
            group_proxy = _configurable_bool('provider.group_reference_proxy', 'STORY_OS_GROUP_REFERENCE_PROXY')
            if group_proxy and image.width >= 600:
                # Same source authority, but reduce a two-person selfie to a compact
                # overlapping left/right identity strip. This is a disposable
                # attachment only; the original file + SHA stay in Queue/Ledger.
                overlap = max(48, image.width // 10)
                mid = image.width // 2
                left = image.crop((0, 0, min(image.width, mid + overlap), image.height))
                right = image.crop((max(0, mid - overlap), 0, image.width, image.height))
                for crop in (left, right):
                    crop.thumbnail((360, 520), Image.Resampling.LANCZOS)
                canvas = Image.new('RGB', (left.width + right.width, max(left.height, right.height)))
                canvas.paste(left, (0, 0))
                canvas.paste(right, (left.width, 0))
                image = canvas
            else:
                image.thumbnail((768, 768), Image.Resampling.LANCZOS)
            image.save(target, format='JPEG', quality=90, optimize=True)
        return target
    except Exception:
        ext = source.suffix.lower() if source.suffix.lower() in {'.png', '.jpg', '.jpeg'} else '.png'
        target = workdir / f'reference-{index:02d}{ext}'
        shutil.copy2(source, target)
        return target


def _legacy_bridge_auth_probe() -> bool:
    """Prove an older live user-runner still has a usable ChatGPT/Codex login.

    Runner processes can legitimately outlive a Story OS code deploy.  Protocol
    revision 2 runners started before ``codex_auth_present`` was added omit that
    health field even though they can still execute authenticated Codex work.
    Use the CLI's read-only login-status command through the same interactive-user
    bridge instead of treating an absent field as a logged-out user.
    """
    try:
        completed = codex_user_runner.run_codex(
            ["codex", "login", "status"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=runtime_timeout_policy.seconds("codex_auth_probe"),
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
            task_type="smoke",
            codex_home_mode="inherit",
        )
    except Exception:
        return False
    text = str(completed.stdout or "").strip().lower()
    return completed.returncode == 0 and ("logged in" in text or "authenticated" in text)


def image_runtime_preflight(*, bridged: bool, source_home: Path | None = None,
                            worker_home: Path | None = None) -> dict:
    """Fail before model execution when the selected Codex image lane is not ready.

    Credential *contents* are never read or returned. For direct execution we
    only prove that the sign-in marker exists and that the disposable worker's
    generated_images root is writable. For the user-mode bridge those checks are
    performed by the interactive runner and exposed as presence/accessibility
    booleans through its health endpoint.
    """
    if bridged:
        try:
            health = codex_user_runner.runner_health()
        except Exception as exc:
            raise BackendError(f'IMAGE_RUNTIME_PREFLIGHT_FAILED: user runner unavailable: {exc}') from exc
        if not health.get("codex_available"):
            raise BackendError('IMAGE_RUNTIME_PREFLIGHT_FAILED: bridged Codex executable unavailable')
        if not health.get("codex_home_accessible"):
            raise BackendError('IMAGE_RUNTIME_PREFLIGHT_FAILED: bridged CODEX_HOME is not accessible')
        if "codex_auth_present" in health:
            auth_present = bool(health.get("codex_auth_present"))
        else:
            # Backward compatibility for already-running user runners from before
            # the health presence bit existed.  Do not assume success: prove it
            # with a read-only `codex login status` call in that same user context.
            auth_present = _legacy_bridge_auth_probe()
        if not auth_present:
            raise BackendError('IMAGE_RUNTIME_PREFLIGHT_FAILED: bridged Codex authentication context unavailable')
        return {
            "transport": "user_runner",
            "codex_available": True,
            "codex_home_accessible": True,
            "auth_context_present": True,
            "generated_images_writable": True,
        }

    source = Path(source_home or os.environ.get("CODEX_HOME") or (Path.home() / ".codex")).expanduser()
    if not source.is_dir():
        raise BackendError(f'IMAGE_RUNTIME_PREFLIGHT_FAILED: CODEX_HOME missing: {source}')
    if not (source / "auth.json").is_file():
        raise BackendError('IMAGE_RUNTIME_PREFLIGHT_FAILED: CODEX_HOME has no auth.json')
    target = Path(worker_home or source).expanduser()
    try:
        generated = target / "generated_images"
        generated.mkdir(parents=True, exist_ok=True)
        probe = generated / f".storyos-write-probe-{uuid.uuid4().hex}"
        probe.write_bytes(b"ok")
        probe.unlink()
    except OSError as exc:
        raise BackendError(f'IMAGE_RUNTIME_PREFLIGHT_FAILED: generated_images is not writable: {target}') from exc
    return {
        "transport": "direct",
        "codex_available": True,
        "codex_home_accessible": True,
        "auth_context_present": True,
        "generated_images_writable": True,
    }


def image_worker_sandbox_mode(*, bridged: bool, has_references: bool) -> str:
    """Choose the Codex sandbox for the narrow disposable image worker.

    On Windows, a user-mode bridged worker must read the interactive user's real
    CODEX_HOME while its disposable working directory is owned by Story OS. The
    native workspace-write sandbox can reject that cross-root bootstrap with
    os error 5 before the model starts. Keep the no-OS-sandbox lane only for this
    narrow image subprocess; Story OS still owns queue/budget/output/gate policy.
    """
    if os.name == 'nt' and (bridged or has_references):
        return 'danger-full-access'
    return 'workspace-write'


def invoke_codex(prompt_path: Path, refs: list[Path], raw_output: Path, log: Path, size: str, timeout: int, codex_raw: str | None, visual_contract: str | None = None, frame_contract_text: str | None = None, image_model: str = DEFAULT_IMAGE_MODEL, image_quality: str = DEFAULT_IMAGE_QUALITY, strict_model: bool = False, *, scene_text: str | None = None, runner_request_id: str | None = None, episode_dir: Path | None = None, generation_attempt_lease: dict | None = None, transport_model: str | None = None, transport_effort: str | None = None, transport_request: dict | None = None) -> tuple[float, dict]:
    if episode_dir is None or not isinstance(generation_attempt_lease, dict):
        raise BackendError('GENERATION_ATTEMPT_LEASE_REQUIRED')
    scene = scene_text if scene_text is not None else prompt_path.read_text(encoding='utf-8-sig').strip()
    if not scene:
        raise BackendError('prompt is empty')
    codex = resolve_codex(codex_raw)
    started = time.monotonic()
    bridged = codex_user_runner.bridge_required()
    with codex_user_runner.workspace(prefix='story-os-image-') as raw_dir:
        workdir = Path(raw_dir)
        local_refs = []
        for index, source in enumerate(refs, 1):
            local_refs.append(_reference_proxy(source, workdir, index))
        # Windows reference-bound workers and bridged isolated-home workers cannot
        # reliably bootstrap the native workspace-write sandbox. Both remain narrow
        # image-only tasks in this disposable workdir; Story OS retains contract,
        # queue and ledger authority around the generated artifact.
        sandbox_mode = image_worker_sandbox_mode(bridged=bridged, has_references=bool(local_refs))
        # Image workers are intentionally narrow: Story OS already embeds the complete
        # visual/frame contracts in the prompt. Muting the Codex skills catalog prevents
        # the controller from spending a turn loading imagegen/SKILL.md before it can
        # reach image_generation; project docs are likewise unnecessary in this temp cwd.
        execution_args = (
            transport_args(str(transport_model or ""), str(transport_effort or "low"))
            if transport_request is not None else controller_args(episode_dir)
        )
        cmd = execution_command_prefix(codex) + [
            'exec', '--skip-git-repo-check', '--ephemeral', '--ignore-rules',
            '-c', 'skills.include_instructions=false', '-c', 'project_doc_max_bytes=0',
            '--enable', 'image_generation',
            *execution_args, '-s', sandbox_mode, '-C', str(workdir), '--json'
        ]
        for ref in local_refs:
            cmd.extend(['-i', str(ref)])
        cmd.append('-')
        log.parent.mkdir(parents=True, exist_ok=True)
        # 每个图片 worker 使用独立 CODEX_HOME，避免多个并发 worker 共享
        # ~/.codex/generated_images 导致 provider artifact save collision。
        # 该目录只影响 Codex CLI 临时产物，不改变 Story OS 资产权威路径。
        worker_env = os.environ.copy()
        worker_env.setdefault("STORY_OS_WORKER_ID", str(uuid.uuid4()))
        # STORY_OS_V2_7_CODEX_USER_MODE_BRIDGE: across the interactive-user
        # bridge the runner owns the real Codex home. The caller never reads or
        # copies credentials; runner-side thread-id scoped artifact export keeps
        # concurrent image results isolated without creating a fresh CODEX_HOME.
        if not bridged:
            worker_codex_home = workdir / "codex-home"
            worker_codex_home.mkdir(parents=True, exist_ok=True)
            # The isolated CODEX_HOME exists to stop concurrent workers sharing
            # ~/.codex/generated_images. An empty CODEX_HOME also drops the operator's
            # ChatGPT/Codex sign-in, which makes every worker unauthenticated
            # (HTTP 401) and produces zero images. Seed only the credentials the CLI
            # needs; the reference/generated_images isolation stays intact.
            source_home = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))
            for name in ("auth.json", "config.toml"):
                src = source_home / name
                if src.is_file() and not (worker_codex_home / name).exists():
                    shutil.copy2(src, worker_codex_home / name)
            image_runtime_preflight(
                bridged=False,
                source_home=source_home,
                worker_home=worker_codex_home,
            )
            worker_env["CODEX_HOME"] = str(worker_codex_home)
        else:
            image_runtime_preflight(bridged=True)
        request_prompt = (
            payload_transport_prompt(transport_request, size, len(local_refs))
            if transport_request is not None
            else worker_prompt(scene, local_refs, size, visual_contract, frame_contract_text,
                               image_model, image_quality, strict_model)
        )
        with log.open('w', encoding='utf-8', newline='\n') as log_handle:
            try:
                completed = image_generation_gateway.provider_generate(
                    episode_dir, generation_attempt_lease, generation_attempt_lease.get("fencing_token"),
                    'codex_subscription', lambda: codex_user_runner.run_model_codex(
                        cmd,
                        env=worker_env,
                        input=request_prompt,
                        text=True,
                        encoding="utf-8",
                        errors="strict",
                        stdout=log_handle,
                        stderr=subprocess.STDOUT,
                        cwd=workdir,
                        timeout=timeout,
                        check=False,
                        task_type="image",
                        codex_home_mode="inherit",
                        request_id=runner_request_id,
                    ),
                )
            except subprocess.TimeoutExpired as exc:
                raise BackendError(f'image worker timeout after {timeout}s; log={log}') from exc
        candidate = workdir / 'out.png'
        if not valid_image(candidate):
            alternatives = [p for p in workdir.glob('*.png') if not p.name.startswith('reference-')]
            if alternatives:
                candidate = max(alternatives, key=lambda p: p.stat().st_mtime)
        if not valid_image(candidate) and not bridged:
            # The recovery root lives inside the Codex home, which belongs to the
            # runner user once the task crossed the bridge.
            recovered = image_artifact_collector.recover_codex_generated(log, workdir)
            if recovered is not None:
                candidate = recovered
        if not valid_image(candidate) and bridged:
            # STORY_OS_V2_7_CODEX_USER_MODE_BRIDGE: the throwaway Codex home now
            # lives in the runner user's profile, so the runner mirrors provider
            # artifacts into this shared workdir instead.
            staged = codex_user_runner.exported_artifacts_dir(workdir)
            if staged.is_dir():
                exported = [p for p in sorted(staged.rglob('*'))
                            if p.is_file() and valid_image(p)]
                if exported:
                    candidate = max(exported, key=lambda p: p.stat().st_mtime)
        try:
            raw_log_text = log.read_text(encoding='utf-8', errors='replace') if log.is_file() else ''
            runtime_log_policy.write_codex_noise_summary(log, raw_log_text)
        except Exception:
            raw_log_text = ''
        candidate_valid = valid_image(candidate)
        candidate_viable = provider_raw_candidate_viable(candidate) if candidate_valid else False
        machine_code = logged_backend_failure(
            raw_log_text,
            returncode=completed.returncode,
            candidate_valid=candidate_valid,
            candidate_viable=candidate_viable,
        )
        if machine_code:
            raise BackendError(f'{machine_code}: requested={image_model}; log={log}')
        if completed.returncode == 0 and not candidate_valid:
            artifact_evidence = runner_generated_artifact_evidence(runner_request_id)
            if (artifact_evidence.get("result_found") is True
                    and artifact_evidence.get("generated_artifact_count") == 0):
                raise BackendError(
                    f'IMAGE_TOOL_NO_ARTIFACT: rc=0; generated_artifacts=0; log={log}'
                )
        if completed.returncode != 0 or not candidate_valid:
            raise BackendError(f'Codex image worker failed rc={completed.returncode}; no_valid_image=true; log={log}')
        # Structurally valid but undersized provider RAW with no technical error in
        # the same invocation continues to provider_capability.inspect(), which is
        # the canonical source of PROVIDER_RAW_CANVAS_DEGENERATE evidence.
        raw_output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidate, raw_output)
    return round(time.monotonic() - started, 2), codex_user_runner.provider_transport_evidence(getattr(completed, "remote", {}))

def _invoke_result(value) -> tuple[float, dict]:
    """Accept both the new transport-aware result and legacy/mocked float results."""
    if isinstance(value, tuple) and len(value) == 2:
        elapsed, evidence = value
        return float(elapsed), dict(evidence or {}) if isinstance(evidence, dict) else {}
    return float(value), {}


def common_validate(args: argparse.Namespace) -> tuple[Path, list[Path], Path, Path]:
    prompt_path = args.prompt_file.expanduser().resolve()
    if not prompt_path.is_file():
        raise BackendError(f'prompt missing: {prompt_path}')
    refs = [p.expanduser().resolve() for p in args.reference]
    if len(refs) > 2:
        raise BackendError('at most two references are supported')
    for ref in refs:
        if not valid_image(ref):
            raise BackendError(f'invalid reference image: {ref}')
    output = args.output.expanduser().resolve()
    log = args.log.expanduser().resolve()
    if output.exists() and not args.overwrite:
        raise BackendError(f'output exists: {output}')
    return prompt_path, refs, output, log

def generate_for_frame(args: argparse.Namespace) -> dict:
    prompt_path, refs, output, log = common_validate(args)
    ep = args.episode_dir.expanduser().resolve()
    width, height, aspect = read_canvas(ep)
    visual = compile_prompt_contract(ep)
    frame_contract = None
    scene_text = None
    if resolved_frame_contract.required(ep):
        import prompt_package
        package = prompt_package.compile_frame(ep, int(args.frame), prompt_path)
        scene_text = package['scene_prompt']
        frame_contract = {'contract_sha256': package['frame_contract_sha256'], 'prompt_contract': package['frame_prompt_contract']}
    size = provider_size(width, height)
    raw_dir = ep / 'media' / 'raw'
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_output = raw_dir / f'{int(args.frame):02d}-{int(time.time())}.png'
    frame_contract_text = frame_contract['prompt_contract'] if frame_contract else None
    internal_policy = getattr(args, '_image_model_policy', None)
    if isinstance(internal_policy, dict):
        payload_model_policy = dict(internal_policy)
    else:
        payload_model_policy = image_model_policy.for_episode(ep, explicit=getattr(args, 'image_model', None), explicit_quality=getattr(args, 'image_quality', None))
    recovered_codex_raw = getattr(args, '_recovered_codex_raw', None)
    canonical_payload_request = getattr(args, '_canonical_payload_request', None)
    recovered_src = Path(str(recovered_codex_raw)).expanduser().resolve() if recovered_codex_raw else None
    recovered_request_id = str(getattr(args, '_recovered_runner_request_id', '') or '').strip()
    if recovered_src is not None and not valid_image(recovered_src):
        raise BackendError(f'recovered Codex raw invalid: {recovered_src}')
    provider_evidence = None
    manual_dir = os.environ.get('STORY_OS_MANUAL_RAW_DIR')
    manual_src = None
    if manual_dir:
        matches = sorted(Path(manual_dir).glob(f'{int(args.frame):02d}.*'))
        if not matches:
            raise BackendError(f'manual raw missing for frame {int(args.frame):02d} in {manual_dir}')
        manual_src = matches[-1]
        if not valid_image(manual_src):
            raise BackendError(f'manual raw invalid: {manual_src}')
    transport_evidence = {}
    if recovered_src is not None:
        raw_output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(recovered_src, raw_output)
        elapsed = 0.0
        backend_name = 'codex_subscription'
    elif manual_src:
        raw_output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(manual_src, raw_output)
        elapsed = 0.0
        backend_name = 'codex_desktop_interface_imagegen'
    elif canonical_payload_request is not None:
        expected_policy = model_policy.resolve("image.payload", episode=ep)
        errors = image_payload_request.validate_request(
            canonical_payload_request,
            expected_policy_sha256=str(expected_policy.get("model_policy_sha256") or ""),
        )
        if errors:
            raise BackendError("IMAGE_PAYLOAD_REQUEST_INVALID: " + ",".join(errors))
        expected_key = __import__("logical_asset_identity").frame_asset_key(ep, int(args.frame))
        if canonical_payload_request.get("logical_asset_key") != expected_key:
            raise BackendError("IMAGE_PAYLOAD_REQUEST_LOGICAL_ASSET_MISMATCH")
        if canonical_payload_request.get("frame_contract_sha256") != (frame_contract or {}).get("contract_sha256"):
            raise BackendError("IMAGE_PAYLOAD_REQUEST_FRAME_CONTRACT_MISMATCH")
        if canonical_payload_request.get("payload_model") != payload_model_policy.get("model"):
            raise BackendError("IMAGE_PAYLOAD_REQUEST_MODEL_MISMATCH")
        if canonical_payload_request.get("payload_quality") != payload_model_policy.get("quality"):
            raise BackendError("IMAGE_PAYLOAD_REQUEST_QUALITY_MISMATCH")
        referenced = []
        for row in canonical_payload_request.get("references") or []:
            rel = str(row.get("path") or "").strip()
            if not rel:
                raise BackendError("IMAGE_PAYLOAD_REQUEST_REFERENCE_PATH_REQUIRED")
            path = (ROOT / rel).resolve()
            try:
                path.relative_to(ROOT.resolve())
            except ValueError as exc:
                raise BackendError("IMAGE_PAYLOAD_REQUEST_REFERENCE_PATH_UNSTABLE") from exc
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != row.get("sha256"):
                raise BackendError("IMAGE_PAYLOAD_REQUEST_REFERENCE_SHA_MISMATCH")
            referenced.append(path)
        selected_route = str(getattr(args, "_payload_provider_route", "") or "")
        started = time.monotonic()
        if selected_route == "openai_images_api":
            provider_evidence = openai_images_provider.generate_native_batch(
                prompt=str(canonical_payload_request["scene_prompt"]),
                references=referenced,
                count=1,
                model=str(canonical_payload_request["payload_model"]),
                quality=str(canonical_payload_request["payload_quality"]),
                release_width=int(width),
                release_height=int(height),
                timeout=int(args.timeout),
                raw_paths=[raw_output],
                generation_attempt_leases=[getattr(args, "_generation_attempt_lease", None)],
                episode_dir=ep,
            )
            backend_name = "openai_images_api"
        elif selected_route == "codex_subscription":
            transport_model = str(getattr(args, "_payload_transport_model", "") or "")
            transport_effort = str(getattr(args, "_payload_transport_effort", "") or "low")
            if not transport_model:
                raise BackendError("LOGIN_AUTH_TRANSPORT_MODEL_REQUIRED")
            elapsed = invoke_codex(
                prompt_path, referenced, raw_output, log, size, int(args.timeout), args.codex,
                None, None, payload_model_policy["model"], payload_model_policy["quality"], payload_model_policy["strict_model"],
                scene_text=str(canonical_payload_request["scene_prompt"]),
                runner_request_id=str(getattr(args, "_runner_request_id", "") or "") or None,
                episode_dir=ep,
                generation_attempt_lease=getattr(args, "_generation_attempt_lease", None),
                transport_model=transport_model,
                transport_effort=transport_effort,
                transport_request=canonical_payload_request,
            )
            provider_evidence = {
                "provider": "codex_subscription",
                "transport_route": "native_codex",
                "transport_model": transport_model,
                "transport_effort": transport_effort,
                "transport_role": "IMAGE_TOOL_TRANSPORT",
                "payload_request_fingerprint": canonical_payload_request.get("request_fingerprint"),
                "provider_model_reported": False,
            }
            backend_name = "codex_subscription"
        else:
            raise BackendError(f"PAYLOAD_PROVIDER_ROUTE_UNSUPPORTED:{selected_route}")
        elapsed = round(time.monotonic() - started, 3)
    else:
        if bool(getattr(args, "_raw_candidate_budget_preclaimed", False)):
            raise BackendError("INDEPENDENT_IMAGE_PAYLOAD_REQUEST_REQUIRED")
        elapsed, transport_evidence = _invoke_result(invoke_codex(prompt_path, refs, raw_output, log, size, args.timeout, args.codex, visual['text'], frame_contract_text, payload_model_policy['model'], payload_model_policy['quality'], payload_model_policy['strict_model'], scene_text=scene_text, runner_request_id=str(getattr(args, '_runner_request_id', '') or '') or None, episode_dir=ep, generation_attempt_lease=getattr(args, '_generation_attempt_lease', None)))
        backend_name = 'codex_subscription'
    receipt_data = provider_capability.inspect(raw_output, width, height, model=payload_model_policy["model"], route=backend_name, frame=int(args.frame))
    attempt_lease = getattr(args, "_generation_attempt_lease", None)
    if isinstance(attempt_lease, dict):
        attempt_context = attempt_lease.get("generation_context") or {}
        receipt_data.update({
            "generation_key": attempt_lease.get("generation_key"),
            "attempt_index": attempt_lease.get("attempt_index"),
            "fencing_token": attempt_lease.get("fencing_token"),
            "production_revision_id": attempt_context.get("production_revision_id"),
            "frame_contract_sha256": attempt_context.get("frame_contract_sha256"),
            "prompt_package_sha256": attempt_context.get("prompt_package_sha256"),
            "request_id": getattr(args, "_runner_request_id", None),
        })
    receipt_data.update(provider_receipt_model_bindings(
        ep, payload_model_policy["model"], payload_model_policy["quality"]))
    if canonical_payload_request is not None:
        receipt_data.update({
            "controller_receipt_id": canonical_payload_request.get("controller_receipt_id"),
            "controller_output_sha256": canonical_payload_request.get("controller_output_sha256"),
            "payload_request_fingerprint": canonical_payload_request.get("request_fingerprint"),
            "payload_model": canonical_payload_request.get("payload_model"),
            "payload_quality": canonical_payload_request.get("payload_quality"),
            "payload_effective_model_source": "EXPLICIT_RUNTIME_BINDING",
            "payload_provider_model_reported": False,
            "payload_provider_receipt": provider_evidence,
            "transport_model": getattr(args, "_payload_transport_model", None),
            "transport_effort": getattr(args, "_payload_transport_effort", None),
            "transport_role": "IMAGE_TOOL_TRANSPORT" if backend_name == "codex_subscription" else None,
        })
    # W-21: the receipt carries the reference files really sent to the provider, so
    # the production ledger can record execution evidence, not only a declaration.
    # A manual desktop import never attaches them to a provider call, so it must not
    # claim reference delivery it did not perform.
    if manual_src:
        receipt_data["reference_transport"] = "manual_desktop_import"
    elif backend_name == "openai_images_api":
        receipt_data["reference_transport"] = "openai_images_api_multipart" if refs else "openai_images_api_json"
    else:
        receipt_data["reference_transport"] = "codex_subscription_cli_attachment"
    receipt_data["references"] = [] if manual_src else provider_capability.reference_evidence(refs)
    receipt_data.update(transport_evidence)
    if recovered_src is not None:
        receipt_data["recovery"] = {
            "kind": "interrupted_user_runner_success",
            "runner_request_id": recovered_request_id or None,
            "source_artifact": str(recovered_src),
        }
    provider_receipt_info = provider_capability.write_receipt(ep, int(args.frame), receipt_data)
    if output.exists() and args.overwrite:
        output.unlink()
    try:
        norm = normalize(raw_output, output, width, height)
    except NormalizeError as exc:
        allow_provider_crop = _configurable_bool(
            'normalize.provider_ratio_crop_exception_enabled',
            'STORY_OS_PROVIDER_RATIO_CROP_EXCEPTION',
        )
        if exc.code == 'ASPECT_RATIO_MISMATCH' and allow_provider_crop:
            norm = normalize_provider_crop_exception(
                raw_output, output, width, height,
                reason=(
                    f'explicit provider-size compatibility exception; requested={width}x{height}; '
                    f'provider capability does not guarantee exact raw canvas; receipt={provider_receipt_info.get("path")}'
                ),
            )
        else:
            raise BackendError(f'{exc.code}: raw preserved at {raw_output}; provider_receipt={provider_receipt_info.get("path")}; {exc}') from exc
    receipt_path = Path(provider_receipt_info["path"])
    if not receipt_path.is_absolute():
        receipt_path = ROOT / receipt_path
    provider_receipt_info = provider_capability.finalize_receipt(receipt_path, norm, output)
    return {
        'ok': True,
        'backend': backend_name,
        'frame': f'{int(args.frame):02d}',
        'raw_output': str(raw_output),
        'output': str(output),
        'log': str(log),
        'provider_size': size,
        'target_size': [width, height],
        'aspect_ratio': aspect,
        'references': [str(p) for p in refs],
        'visual_profile': {
            'profile_id': visual['profile_id'],
            'profile_path': visual['profile_path'],
            'profile_sha256': visual['profile_sha256'],
            'capture_profile': visual['capture_profile'],
        },
        'frame_contract': {
            'path': (resolved_frame_contract.CACHE_ROOT / f"{int(args.frame):02d}.json").as_posix(),
            'contract_sha256': frame_contract['contract_sha256'],
        } if frame_contract else None,
        'normalization': norm,
        'provider_receipt': {k: v for k, v in provider_receipt_info.items() if k != 'receipt'},
        'provider_capability': provider_receipt_info.get('receipt'),
        'image_model': {
            **payload_model_policy,
            'enforcement': 'runtime_request_to_worker_contract',
            'provider_attestation': False,
            'generation_route': backend_name,
            'generation_route_note': f'generated via built-in image_gen tool in the Codex desktop interface when STORY_OS_MANUAL_RAW_DIR is set; model contract stays {payload_model_policy["model"]}',
        } if manual_src else {**payload_model_policy, 'enforcement': 'runtime_request_to_worker_contract', 'provider_attestation': False},
        'elapsed_seconds': elapsed,
        'transport': transport_evidence or None,
    }

def generate_legacy(args: argparse.Namespace) -> dict:
    prompt_path, refs, output, log = common_validate(args)
    size = args.size
    legacy_model_policy = image_model_policy.resolve_model(explicit=args.image_model, explicit_quality=getattr(args, 'image_quality', None))
    tmp_raw = output.with_name('.' + output.name + '.raw.png')
    elapsed, transport_evidence = _invoke_result(invoke_codex(prompt_path, refs, tmp_raw, log, size, args.timeout, args.codex, None, None, legacy_model_policy['model'], legacy_model_policy['quality'], legacy_model_policy['strict_model'], episode_dir=getattr(args, 'episode_dir', None), generation_attempt_lease=getattr(args, '_generation_attempt_lease', None)))
    if output.exists() and args.overwrite:
        output.unlink()
    os.replace(tmp_raw, output)
    return {'ok': True, 'backend':'codex_subscription', 'output':str(output), 'log':str(log), 'size':size, 'references':[str(p) for p in refs], 'elapsed_seconds':elapsed, 'transport': transport_evidence or None}

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('generate-for-frame')
    p.add_argument('episode_dir', type=Path)
    p.add_argument('--frame', required=True)
    p.add_argument('--prompt-file', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--log', required=True, type=Path)
    p.add_argument('--reference', action='append', default=[], type=Path)
    p.add_argument('--timeout', type=int, default=None)
    p.add_argument('--codex')
    p.add_argument('--image-model')
    p.add_argument('--image-quality', choices=['high'])
    p.add_argument('--overwrite', action='store_true')
    p.add_argument('--candidate-kind', choices=['original','repair','exception'], default='original')
    p = sub.add_parser('generate')
    p.add_argument('--prompt-file', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--log', required=True, type=Path)
    p.add_argument('--reference', action='append', default=[], type=Path)
    p.add_argument('--size', default='1024x1280')
    p.add_argument('--timeout', type=int, default=None)
    p.add_argument('--codex')
    p.add_argument('--image-model')
    p.add_argument('--image-quality', choices=['high'])
    p.add_argument('--overwrite', action='store_true')
    sub.add_parser('self-test')
    args = ap.parse_args()
    if args.cmd == 'self-test':
        smoke = worker_prompt('x', [], '1024x1280')
        assert 'FIRST ACTION: call image_generation exactly once' in smoke
        assert 'Do NOT read SKILL.md' in smoke
        assert image_model_policy.DEFAULT_MODEL in worker_prompt('x', [], '1024x1280')
        assert '<visual_contract>' in worker_prompt('x', [], '1024x1280', 'reality first')
        assert '<frame_contract>' in worker_prompt('x', [], '1080x1350', 'reality first', 'frame-contract-test')
        assert f'quality={image_model_policy.DEFAULT_QUALITY}' in worker_prompt('x', [], '1080x1350')
        smoke_prompt = worker_prompt('x', [], '1080x1350')
        assert 'stop immediately' in smoke_prompt
        assert 'thread_id' in smoke_prompt
        assert 'save or copy the actual generated candidate to ./out.png' not in smoke_prompt
        assert provider_size(1080, 1350) == '1080x1350'
        assert provider_size(1080, 1920) == '1080x1920'
        assert logged_backend_failure(
            'network error: error sending request', returncode=0,
            candidate_valid=True, candidate_viable=False,
        ) == image_model_policy.NETWORK_ERROR
        assert logged_backend_failure(
            'old warning: network error: error sending request', returncode=0,
            candidate_valid=True, candidate_viable=True,
        ) is None
        if os.name == 'nt':
            assert image_worker_sandbox_mode(bridged=True, has_references=False) == 'danger-full-access'
            assert image_worker_sandbox_mode(bridged=False, has_references=True) == 'danger-full-access'
        else:
            assert image_worker_sandbox_mode(bridged=True, has_references=False) == 'workspace-write'
        from unittest.mock import patch
        with patch.dict(os.environ, {'STORY_OS_IMAGE_PROVIDER_ROUTE': 'subscription'}):
            assert controller_args() == [
                '-m', CODEX_IMAGE_CONTROLLER_MODEL,
                '-c', f'model_reasoning_effort="{CODEX_IMAGE_REASONING_EFFORT}"',
            ]
        assert not valid_image(Path('__missing__'))
        print('CODEX SUBSCRIPTION IMAGE BACKEND SELF-TEST PASS')
        return 0
    args.timeout = runtime_timeout_policy.resolve("image_worker_request", args.timeout)
    low, high = runtime_timeout_policy.VALID_RANGE["image_worker_request"]
    if not low <= args.timeout <= high:
        raise SystemExit(f'timeout must be {low}..{high} seconds')
    # The direct CLI is also a formal image entrypoint. Hold a permit before
    # reserving ANY durable Generation Attempt, not just at Provider Gateway.
    # The nested Gateway call reuses this slot in the same process/thread.
    try:
        guard = (global_image_capacity.image_permits(1)
                 if args.cmd == 'generate-for-frame' else nullcontext())
        with guard:
            return _execute_cli_generation(args)
    except global_image_capacity.GlobalImageCapacityError as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=False))
        return 2


def _execute_cli_generation(args: argparse.Namespace) -> int:
    budget_token=None
    budget_reserved=False
    try:
        if args.cmd == 'generate-for-frame':
            budget_token="direct-"+uuid.uuid4().hex
            ok,budget_row=raw_candidate_budget.claim(args.episode_dir,int(args.frame),args.candidate_kind,reason="direct_generate_for_frame_cli",token=budget_token)
            if not ok:
                print(json.dumps({'ok':False,'error':'RAW_CANDIDATE_BUDGET_EXHAUSTED','budget':budget_row},ensure_ascii=False));return 3
            budget_reserved=True
            args._generation_attempt_lease = budget_row.get('lease')
        result = generate_for_frame(args) if args.cmd == 'generate-for-frame' else generate_legacy(args)
        if budget_reserved:
            commit_ok,commit_row=raw_candidate_budget.commit(args.episode_dir,budget_token,reason="direct_cli_normalized_candidate_exists")
            if not commit_ok:
                print(json.dumps({'ok':False,'error':'CANDIDATE_COMMIT_FAILED','budget':commit_row},ensure_ascii=False));return 4
    except (BackendError, OSError, UnicodeError, SystemExit, global_image_capacity.GlobalImageCapacityError) as exc:
        if budget_reserved:raw_candidate_budget.release(args.episode_dir,budget_token,reason="direct_generate_for_frame_exception")
        print(json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())

# STORY_OS_V2_5_1_1_FORCED_CANDIDATE_GATE

# STORY_OS_V2_6_0_PERFORMANCE_RUNTIME
