#!/usr/bin/env python3
"""Fixed safety contract for the Phase 5A COLLABORATIVE subpath canary.

This module is not an Episode runner or an alternate stage authority. It only
defines the narrow authorization boundary that a dedicated canary harness may
use. Ordinary Runtime Requests and the normal Runtime DAG cannot opt into this
contract or use it to skip the canonical Visual Lock gate.
"""
from __future__ import annotations

from copy import deepcopy
import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any, Mapping
from platform.repository.mysql.schema_v2 import DATABASE_NAME
import runtime_timeout_policy
import subprocess
import time
import uuid


CANARY_ENTRYPOINT = "phase5a_collaborative_canary"
CANARY_TYPE = "PHASE5A_COLLABORATIVE_REGRESSION"

_CONTRACT = MappingProxyType({
    "canary_type": CANARY_TYPE,
    "production_mode": "COLLABORATIVE",
    "scope": "PRODUCTION_SUBPATH",
    "promotable": False,
    "release_eligible": False,
    "stage_authority": False,
    "provider_generation_target": 1,
    "provider_generation_hard_max": 2,
    # This is a harness-only declaration. It is not a production option.
    "requires_visual_lock_stage": False,
})

_FORBIDDEN_REQUEST_KEYS = frozenset({
    "canary_type",
    "canary_scope",
    "skip_visual_lock",
    "requires_visual_lock_stage",
    "promotable",
    "release_eligible",
    "stage_authority",
})

_ALLOWED_ACTIONS = frozenset({
    "RUN_PRODUCTION_SUBPATH",
    "WRITE_CANARY_EVIDENCE",
    "RESUME_PRODUCTION_SUBPATH",
    "RUN_INCREMENTAL_REUSE",
})

_FORBIDDEN_ACTIONS = frozenset({
    "STAGE_PROMOTION",
    "WRITE_CANONICAL_STAGE",
    "WRITE_VISUAL_LOCK_PASS",
    "RELEASE_AUTHORITY_COMMIT",
    "PUBLISH_READY_TRANSITION",
    "PUBLISH",
})

WORKSPACE_REL = Path(".codex_tmp/phase5a")
MARKER_REL = Path("meta/phase5a-canary.json")
GLOBAL_CLAIM_REL = WORKSPACE_REL / ".phase5a-collaborative-canary-claim.json"
REPLACEMENT_CLAIM_REL = WORKSPACE_REL / ".phase5a-collaborative-canary-replacement.json"
VALIDATION_EPOCH_DIR_REL = WORKSPACE_REL / ".phase5a-validation-epochs"
VALIDATION_EPOCH_RETIREMENT_DIR_REL = VALIDATION_EPOCH_DIR_REL / "retirements"
ROOT = Path(__file__).resolve().parents[2]

_RETIREMENT_REASONS = frozenset({
    "REVIEW_EXECUTION_RECEIPT_UNRECOVERABLE",
    "GENERATION_IDENTITY_MISMATCH",
    "UNVERIFIED_REVIEW_PROJECTION",
})


class CanaryContractError(ValueError):
    """Raised when the dedicated non-promotable canary contract is violated."""


def _telemetry(ep: Path, event: str, **attrs: Any) -> None:
    """Best-effort timing evidence; never grants authority or changes outcome."""
    try:
        import runtime_observability

        runtime_observability.safe_record_runtime_event(
            Path(ep), event, source=CANARY_ENTRYPOINT, **attrs
        )
    except Exception:
        return


def contract() -> dict[str, Any]:
    """Return a detached copy of the immutable harness contract."""
    return deepcopy(dict(_CONTRACT))


def workspace_marker(canary_id: str) -> dict[str, str]:
    """Return required non-authoritative workspace labels for a canary run."""
    value = str(canary_id or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", value) or ".." in value:
        raise CanaryContractError("INVALID_CANARY_ID")
    return {
        "workspace_class": "TEST_ONLY",
        "promotion_class": "NON_PROMOTABLE",
        "canary_type": CANARY_TYPE,
        "canary_id": value,
    }


def initialize_workspace(canary_id: str) -> Path:
    """Create one empty, isolated harness directory and its TEST_ONLY marker."""
    marker = workspace_marker(canary_id)
    repo_root = ROOT.resolve()
    base_requested = ROOT / WORKSPACE_REL
    base = base_requested.resolve()
    try:
        base.relative_to(repo_root)
    except ValueError as exc:
        raise CanaryContractError("CANARY_WORKSPACE_PATH_ESCAPE") from exc
    episode_requested = base_requested / str(canary_id)
    episode = episode_requested.resolve()
    try:
        episode.relative_to(base)
    except ValueError as exc:
        raise CanaryContractError("CANARY_WORKSPACE_PATH_ESCAPE") from exc
    if episode_requested.exists() or episode_requested.is_symlink():
        raise CanaryContractError("CANARY_WORKSPACE_ALREADY_EXISTS")
    episode_requested.mkdir(parents=True)
    marker_path = episode / MARKER_REL
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.write_text(json.dumps(marker, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8", newline="\n")
    return episode


def bind_and_freeze(ep: str | Path, request: Mapping[str, Any]) -> dict[str, Any]:
    """Bind an ordinary immutable Runtime Request then freeze its Model Policy."""
    from runtime_request import bind_data, effective_for_episode
    import model_policy

    episode = Path(ep).resolve()
    if not episode.is_relative_to((ROOT / WORKSPACE_REL).resolve()):
        raise CanaryContractError("CANARY_WORKSPACE_PATH_REQUIRED")
    reject_runtime_request_canary_fields(request)
    existing = effective_for_episode(episode)
    if existing is not None and dict(existing) != dict(request):
        raise CanaryContractError("CANARY_RUNTIME_REQUEST_IMMUTABLE")
    bind_data(dict(request), episode)
    bound = effective_for_episode(episode)
    _telemetry(episode, "STEP_FINISHED", step="RUNTIME_REQUEST_BIND", status="SUCCESS",
               evidence_ref=(bound or {}).get("request_id"))
    policy = model_policy_persistence_load(episode)
    if policy is None:
        frozen = model_policy.freeze_for_episode(episode)
        policy = frozen.get("policy") if isinstance(frozen, dict) else None
    if not isinstance(policy, dict):
        raise CanaryContractError("CANARY_MODEL_POLICY_FREEZE_FAILED: missing frozen payload")
    errors = model_policy.validate_bound_policy(episode)
    if errors:
        raise CanaryContractError("CANARY_MODEL_POLICY_FREEZE_FAILED: " + "; ".join(errors))
    _telemetry(episode, "STEP_FINISHED", step="MODEL_POLICY_FREEZE", status="SUCCESS",
               policy_version=policy.get("policy_version"),
               model_policy_sha256=policy.get("policy_sha256"))
    return {"runtime_request_id": bound.get("request_id"),
            "policy_version": policy.get("policy_version"),
            "policy_sha256": policy.get("policy_sha256")}


def model_policy_persistence_load(ep: Path) -> dict | None:
    import model_policy_persistence
    return model_policy_persistence.load(Path(ep).resolve())


def validate_contract(candidate: Mapping[str, Any] | None) -> dict[str, Any]:
    """Require an exact contract; caller-supplied relaxations fail closed."""
    if not isinstance(candidate, Mapping):
        raise CanaryContractError("CANARY_CONTRACT_REQUIRED")
    expected = dict(_CONTRACT)
    if dict(candidate) != expected:
        raise CanaryContractError("CANARY_CONTRACT_MISMATCH")
    return expected


def _contains_forbidden_request_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        return bool(_FORBIDDEN_REQUEST_KEYS.intersection(value)) or any(
            _contains_forbidden_request_key(child) for child in value.values()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_forbidden_request_key(child) for child in value)
    return False


def reject_runtime_request_canary_fields(runtime_request: Mapping[str, Any]) -> None:
    """Shared fail-closed guard for Runtime Request bind/validation paths."""
    if not isinstance(runtime_request, Mapping):
        raise CanaryContractError("INVALID_RUNTIME_REQUEST")
    if _contains_forbidden_request_key(runtime_request):
        raise CanaryContractError("RUNTIME_REQUEST_CANNOT_ENABLE_CANARY_BYPASS")


def authorize_entry(
    *,
    entrypoint: str,
    runtime_request: Mapping[str, Any] | None,
    candidate_contract: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Authorize only the dedicated harness; ordinary runtime entrypoints deny.

    The canary marker is intentionally not accepted from a Runtime Request. A
    valid user request may still be bound as input, but it cannot grant bypass
    authority or request a relaxed stage gate.
    """
    if entrypoint != CANARY_ENTRYPOINT:
        raise CanaryContractError("CANARY_ENTRYPOINT_REQUIRED")
    if runtime_request is not None:
        reject_runtime_request_canary_fields(runtime_request)
    return validate_contract(_CONTRACT if candidate_contract is None else candidate_contract)


def authorize_action(action: str) -> str:
    """Allow only subpath actions; stage, Visual Lock, and release writes deny."""
    normalized = str(action or "").strip().upper()
    if normalized in _FORBIDDEN_ACTIONS:
        raise CanaryContractError("CANARY_STAGE_OR_RELEASE_MUTATION_FORBIDDEN")
    if normalized not in _ALLOWED_ACTIONS:
        raise CanaryContractError("CANARY_ACTION_NOT_ALLOWLISTED")
    return normalized


def validate_generation_count(count: int) -> int:
    """Enforce the fixed 2-call ceiling without making it configurable."""
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise CanaryContractError("INVALID_CANARY_GENERATION_COUNT")
    if count > int(_CONTRACT["provider_generation_hard_max"]):
        raise CanaryContractError("CANARY_GENERATION_HARD_MAX_EXCEEDED")
    return count


def validate_replacement_attempt_state(asset_state: Mapping[str, Any],
                                       attempt: Mapping[str, Any] | None) -> None:
    """Allow exactly one new canary identity after a terminal unknown first run."""
    if int((asset_state or {}).get("attempts_consumed") or 0) != 1:
        raise CanaryContractError("CANARY_REPLACEMENT_SOURCE_ATTEMPT_COUNT_INVALID")
    if (asset_state or {}).get("active_attempt_index") is not None:
        raise CanaryContractError("CANARY_REPLACEMENT_SOURCE_ATTEMPT_ACTIVE")
    if not isinstance(attempt, Mapping) or int(attempt.get("attempt_index") or 0) != 1:
        raise CanaryContractError("CANARY_REPLACEMENT_SOURCE_ATTEMPT_MISSING")
    if str(attempt.get("status") or "") != "OUTCOME_UNKNOWN":
        raise CanaryContractError("CANARY_REPLACEMENT_SOURCE_NOT_OUTCOME_UNKNOWN")
    if str(attempt.get("result_ref") or "").strip():
        raise CanaryContractError("CANARY_REPLACEMENT_SOURCE_HAS_RESULT")


def _replacement_source_evidence(previous_episode: Path) -> dict[str, Any]:
    import generation_attempt_authority
    import logical_asset_identity

    key = logical_asset_identity.frame_asset_key(previous_episode, 1)
    state = generation_attempt_authority.load_asset_state(previous_episode, key)
    attempt = generation_attempt_authority.load_attempt(previous_episode, key, 1)
    validate_replacement_attempt_state(state, attempt)
    return {
        "logical_asset_key": key,
        "generation_key": (attempt or {}).get("generation_key"),
        "status": (attempt or {}).get("status"),
        "failure_class": (attempt or {}).get("failure_class"),
    }


def _validation_epoch_claims() -> list[dict[str, Any]]:
    """Read append-only validation epoch claims in strict contiguous order."""
    directory = (ROOT / VALIDATION_EPOCH_DIR_REL).resolve()
    if not directory.exists():
        return []
    try:
        directory.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise CanaryContractError("CANARY_VALIDATION_EPOCH_PATH_ESCAPE") from exc
    rows = []
    for path in sorted(directory.glob("epoch-*.json")):
        match = re.fullmatch(r"epoch-(\d{4})\.json", path.name)
        if not match:
            raise CanaryContractError("CANARY_VALIDATION_EPOCH_CLAIM_INVALID_FAIL_CLOSED")
        try:
            row = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as exc:
            raise CanaryContractError("CANARY_VALIDATION_EPOCH_CLAIM_INVALID_FAIL_CLOSED") from exc
        row = dict(row)
        row["_path"] = str(path)
        row["_epoch_index"] = int(match.group(1))
        rows.append(row)
    expected = list(range(2, 2 + len(rows)))
    actual = [int(row["_epoch_index"]) for row in rows]
    if actual != expected:
        raise CanaryContractError("CANARY_VALIDATION_EPOCH_SEQUENCE_INVALID_FAIL_CLOSED")
    return rows


def validation_epoch_lock_target(ep: str | Path) -> Path:
    """Return the shared OS-lock target used by reservation and retirement."""
    episode = Path(ep).resolve()
    try:
        episode.relative_to((ROOT / WORKSPACE_REL).resolve())
    except ValueError as exc:
        raise CanaryContractError("CANARY_WORKSPACE_PATH_REQUIRED") from exc
    return episode / "meta" / "runtime" / "phase5a-validation-epoch-authority"


def _retirement_path(canary_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", str(canary_id)) or ".." in str(canary_id):
        raise CanaryContractError("INVALID_CANARY_ID")
    path = (ROOT / VALIDATION_EPOCH_RETIREMENT_DIR_REL / f"{canary_id}.json").resolve()
    try:
        path.relative_to((ROOT / VALIDATION_EPOCH_DIR_REL).resolve())
    except ValueError as exc:
        raise CanaryContractError("CANARY_VALIDATION_EPOCH_PATH_ESCAPE") from exc
    return path


def _read_retirement(canary_id: str) -> dict[str, Any] | None:
    path = _retirement_path(canary_id)
    if not path.exists():
        return None
    try:
        row = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise CanaryContractError("CANARY_VALIDATION_RETIREMENT_INVALID_FAIL_CLOSED") from exc
    if (not isinstance(row, dict) or row.get("schema_version") != 1
            or row.get("canary_type") != CANARY_TYPE
            or row.get("canary_id") != canary_id
            or row.get("retired") is not True
            or row.get("generation_dispatch_eligible") is not False
            or row.get("review_dispatch_eligible") is not False
            or row.get("promotable") is not False
            or row.get("release_eligible") is not False
            or row.get("stage_authority") is not False
            or row.get("retirement_reason") not in _RETIREMENT_REASONS
            or not re.fullmatch(r"phase5a-validation-e[0-9]+-[0-9a-f]{12}",
                                str(row.get("successor_epoch_id") or ""))
            or int(row.get("attempts_consumed", -1)) < 0
            or int(row.get("remaining_attempts", -1)) != 2 - int(row.get("attempts_consumed", -1))
            or row.get("active_attempt_index") is not None):
        raise CanaryContractError("CANARY_VALIDATION_RETIREMENT_INVALID_FAIL_CLOSED")
    return row


def assert_validation_epoch_dispatch_eligible(ep: str | Path) -> None:
    """Fail closed at generation reservation for a retired Phase5A workspace."""
    episode = Path(ep).resolve()
    marker_path = episode / MARKER_REL
    if not marker_path.is_file():
        return
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise CanaryContractError("CANARY_MARKER_INVALID_FAIL_CLOSED") from exc
    canary_id = str(marker.get("canary_id") or "")
    if marker.get("canary_type") != CANARY_TYPE or not canary_id:
        raise CanaryContractError("CANARY_MARKER_INVALID_FAIL_CLOSED")
    retirement = _read_retirement(canary_id)
    if retirement is not None:
        raise CanaryContractError("CANARY_VALIDATION_EPOCH_RETIRED_DISPATCH_DENIED")


def assert_validation_epoch_review_dispatch_eligible(ep: str | Path) -> None:
    """Fail closed before Phase5A Review Queue can recover/claim retired work."""
    try:
        assert_validation_epoch_dispatch_eligible(ep)
    except CanaryContractError as exc:
        if "RETIRED_DISPATCH_DENIED" in str(exc):
            raise CanaryContractError("CANARY_VALIDATION_EPOCH_RETIRED_REVIEW_DENIED") from exc
        raise


def _validation_epoch_source_evidence(previous_episode: Path) -> dict[str, Any]:
    """Require the previous validation canary to be fully exhausted and terminal."""
    import generation_attempt_authority
    import logical_asset_identity
    import scheduler_core

    key = logical_asset_identity.frame_asset_key(previous_episode, 1)
    state = generation_attempt_authority.load_asset_state(previous_episode, key)
    if int(state.get("attempts_consumed") or 0) != 2:
        raise CanaryContractError("CANARY_VALIDATION_SOURCE_NOT_EXHAUSTED")
    if int(state.get("remaining_attempts") or 0) != 0:
        raise CanaryContractError("CANARY_VALIDATION_SOURCE_BUDGET_REMAINS")
    if state.get("active_attempt_index") is not None:
        raise CanaryContractError("CANARY_VALIDATION_SOURCE_ATTEMPT_ACTIVE")

    queue = scheduler_core.load_queue(previous_episode)
    items = [row for row in queue.get("items") or [] if isinstance(row, dict)]
    reviews = [row for row in queue.get("review_work_items") or [] if isinstance(row, dict)]
    if len(items) != 1:
        raise CanaryContractError("CANARY_VALIDATION_SOURCE_QUEUE_INVALID")
    item = items[0]
    if (int(item.get("frame") or 0) != 1
            or item.get("kind") != "original"
            or item.get("scope") != "batch"
            or item.get("status") not in {"external_blocked", "blocked"}):
        raise CanaryContractError("CANARY_VALIDATION_SOURCE_NOT_TERMINAL")
    if reviews:
        raise CanaryContractError("CANARY_VALIDATION_SOURCE_HAS_REVIEW_CANDIDATE")

    attempt2 = generation_attempt_authority.load_attempt(previous_episode, key, 2)
    if not isinstance(attempt2, Mapping) or int(attempt2.get("attempt_index") or 0) != 2:
        raise CanaryContractError("CANARY_VALIDATION_SOURCE_ATTEMPT2_MISSING")
    if str(attempt2.get("result_ref") or "").strip():
        raise CanaryContractError("CANARY_VALIDATION_SOURCE_ATTEMPT2_HAS_RESULT")
    return {
        "logical_asset_key": key,
        "attempts_consumed": 2,
        "remaining_attempts": 0,
        "attempt2_generation_key": attempt2.get("generation_key"),
        "attempt2_status": attempt2.get("status"),
        "attempt2_failure_class": attempt2.get("failure_class"),
        "queue_status": item.get("status"),
        "external_block_reason": (
            (item.get("external_block") or {}).get("reason")
            if isinstance(item.get("external_block"), Mapping) else None
        ),
    }


def _retirement_source_claim(episode: Path, canary_id: str) -> dict[str, Any]:
    """Permit the original TEST_ONLY global claim to retire as epoch one.

    Never reuse the original claim if a replacement or newer validation
    epoch exists. The old image Attempt and all receipts remain immutable.
    """
    claims = _validation_epoch_claims()
    if claims:
        latest = claims[-1]
        if (latest.get("canary_id") != canary_id
                or Path(str(latest.get("workspace") or "")).resolve() != episode):
            raise CanaryContractError("CANARY_VALIDATION_RETIREMENT_NOT_LATEST_EPOCH")
        return dict(latest)

    claim_path = (ROOT / GLOBAL_CLAIM_REL).resolve()
    if (ROOT / REPLACEMENT_CLAIM_REL).exists():
        raise CanaryContractError("CANARY_VALIDATION_RETIREMENT_NOT_LATEST_EPOCH")
    try:
        original = json.loads(claim_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise CanaryContractError("CANARY_VALIDATION_RETIREMENT_EPOCH_CLAIM_REQUIRED") from exc
    if (not isinstance(original, Mapping)
            or original.get("canary_type") != CANARY_TYPE
            or original.get("canary_id") != canary_id
            or Path(str(original.get("workspace") or "")).resolve() != episode):
        raise CanaryContractError("CANARY_VALIDATION_RETIREMENT_EPOCH_CLAIM_REQUIRED")
    return {**original, "validation_epoch": 1, "_epoch_index": 1}


def _assert_review_queue_not_recoverable(queue: Mapping[str, Any], *, at: str | None = None) -> list[dict[str, Any]]:
    """Retirement is forbidden while Review can still be resumed or completed.

    An expired running lease is retireable only when it has no bound Runner
    request, no persisted result receipt, and no durable completed turn (the
    latter is checked against the Critic logs by the caller).
    """
    from datetime import datetime, timezone

    now = datetime.fromisoformat(at) if at else datetime.now(timezone.utc)
    items = [row for row in queue.get("items") or [] if isinstance(row, dict)]
    if len(items) != 1 or int(items[0].get("frame") or 0) != 1:
        raise CanaryContractError("CANARY_VALIDATION_RETIREMENT_QUEUE_INVALID")
    # `review_pending` is not a failed, unrecoverable outcome: Resume can still
    # enqueue/dispatch Review. Only generated or explicitly blocked frame work
    # may proceed to the narrower unrecoverable-evidence checks below.
    if str(items[0].get("status") or "").lower() not in {"generated", "blocked", "external_blocked"}:
        raise CanaryContractError("CANARY_VALIDATION_RETIREMENT_REVIEW_RECOVERABLE")

    review_items = [row for row in queue.get("review_work_items") or [] if isinstance(row, dict)]
    stale_claims: list[dict[str, Any]] = []
    pending = {"queued", "pending", "ready", "claimed", "inflight", "dispatching", "started"}
    for row in review_items:
        status = str(row.get("status") or "").lower()
        if status in pending:
            raise CanaryContractError("CANARY_VALIDATION_RETIREMENT_REVIEW_RECOVERABLE")
        if status == "running":
            expiry_raw = str(row.get("lease_expires_at") or "")
            try:
                expiry = datetime.fromisoformat(expiry_raw)
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                raise CanaryContractError("CANARY_VALIDATION_RETIREMENT_REVIEW_RECOVERABLE")
            if expiry > now:
                raise CanaryContractError("CANARY_VALIDATION_RETIREMENT_REVIEW_RECOVERABLE")
            request_ids = ("runner_request_id", "request_id", "user_runner_request_id", "codex_request_id")
            if any(str(row.get(key) or "").strip() for key in request_ids) or row.get("receipt") is not None:
                raise CanaryContractError("CANARY_VALIDATION_RETIREMENT_REVIEW_RECOVERABLE")
            stale_claims.append({
                "review_key": row.get("review_key"),
                "review_kind": row.get("review_kind"),
                "status": status,
                "lease_expires_at": expiry.isoformat(),
                "runner_request_bound": False,
                "result_receipt_present": False,
            })
        elif status == "blocked":
            # Only an already quarantined, unreceipted, unbound legacy Final
            # Semantic can be reviewed for retirement. Caller independently
            # verifies the official receipt, local diagnostic, and critic log.
            request_ids = ("runner_request_id", "request_id", "user_runner_request_id", "codex_request_id")
            if (row.get("review_kind") != "FINAL_SEMANTIC"
                    or row.get("technical_failure_code") != "FINAL_SEMANTIC_UNVERIFIED_INTERRUPTED_CALL"
                    or row.get("recovery_action") != "VERIFY_FINAL_SEMANTIC_EXECUTION_BEFORE_RETRY"
                    or any(str(row.get(key) or "").strip() for key in request_ids)
                    or row.get("receipt") is not None):
                raise CanaryContractError("CANARY_VALIDATION_RETIREMENT_REVIEW_RECOVERABLE")
            stale_claims.append({
                "review_key": row.get("review_key"), "review_kind": "FINAL_SEMANTIC",
                "status": "blocked", "lease_expires_at": None,
                "runner_request_bound": False, "result_receipt_present": False,
            })
        elif status not in {"finalized", "failed", "stale"}:
            raise CanaryContractError("CANARY_VALIDATION_RETIREMENT_REVIEW_STATUS_UNKNOWN")
    if any(str(row.get("review_kind") or row.get("kind") or "").upper() == "FINAL_SEMANTIC"
           and str(row.get("status") or "").lower() in {
               "success", "passed", "pass", "finalized", "complete", "completed",
           }
           for row in review_items):
        raise CanaryContractError("CANARY_VALIDATION_RETIREMENT_REVIEW_SUCCESS_PRESENT")
    return stale_claims


def _retirement_evidence(ep: Path, canary_id: str, reason: str,
                         evidence_ref: str | Path) -> dict[str, Any]:
    """Read and validate the narrow evidence needed to retire a broken epoch.

    The reference must be the local diagnostic reconciliation report. It is
    evidence of a failed review authority check, never a success authority.
    Generation rows remain read-only and retain their factual budget values.
    """
    import generation_attempt_authority
    import logical_asset_identity
    import scheduler_core
    import frame_semantic_review

    episode, marker = validate_workspace(ep, canary_id)
    if marker.get("promotable") is True:
        raise CanaryContractError("CANARY_VALIDATION_RETIREMENT_PROMOTABLE_SOURCE_DENIED")
    if marker.get("release_eligible") is True:
        raise CanaryContractError("CANARY_VALIDATION_RETIREMENT_RELEASE_AUTHORITY_PRESENT")
    if marker.get("stage_authority") is True:
        raise CanaryContractError("CANARY_VALIDATION_RETIREMENT_STAGE_AUTHORITY_PRESENT")
    if marker.get("workspace_class") != "TEST_ONLY" or marker.get("promotion_class") != "NON_PROMOTABLE":
        raise CanaryContractError("CANARY_VALIDATION_RETIREMENT_PROMOTABLE_SOURCE_DENIED")
    if (episode / "meta" / "episode-state.json").exists():
        raise CanaryContractError("CANARY_VALIDATION_RETIREMENT_STAGE_AUTHORITY_PRESENT")
    release_manifest = episode / "meta" / "release-manifest.json"
    if release_manifest.is_file():
        try:
            release = json.loads(release_manifest.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as exc:
            raise CanaryContractError("CANARY_VALIDATION_RETIREMENT_RELEASE_STATE_INVALID") from exc
        if str(release.get("status") or "").upper() in {"PUBLISH_READY", "PUBLISHED"}:
            raise CanaryContractError("CANARY_VALIDATION_RETIREMENT_RELEASE_AUTHORITY_PRESENT")

    _retirement_source_claim(episode, canary_id)

    key = logical_asset_identity.frame_asset_key(episode, 1)
    state = generation_attempt_authority.load_asset_state(episode, key)
    if state.get("active_attempt_index") is not None:
        raise CanaryContractError("CANARY_VALIDATION_RETIREMENT_ATTEMPT_ACTIVE")
    consumed = int(state.get("attempts_consumed") or 0)
    remaining = int(state.get("remaining_attempts") if state.get("remaining_attempts") is not None
                    else max(0, 2 - consumed))
    if consumed < 1 or consumed >= 2 or remaining != 2 - consumed:
        raise CanaryContractError("CANARY_VALIDATION_RETIREMENT_ATTEMPT_STATE_INVALID")

    # Any persisted Final Semantic receipt is conservatively treated as a
    # potentially recoverable authority; never retire around it.
    if frame_semantic_review.review_receipt_for_frame(episode, 1) is not None:
        raise CanaryContractError("CANARY_VALIDATION_RETIREMENT_REVIEW_RECEIPT_PRESENT")
    # A model execution receipt may survive independently of a final review
    # projection or empty local critic log. Do not retire a potentially
    # recoverable Final Semantic call merely because its queue receipt is absent.
    if any(str(row.get("model_role") or "") == "vision.final"
           for row in _model_execution_receipts(episode)):
        raise CanaryContractError("CANARY_VALIDATION_RETIREMENT_MODEL_RECEIPT_PRESENT")
    queue = scheduler_core.load_queue(episode)
    stale_review_claims = _assert_review_queue_not_recoverable(queue)

    report_path = Path(evidence_ref)
    if not report_path.is_absolute():
        report_path = episode / report_path
    report_path = report_path.resolve()
    try:
        report_path.relative_to(episode)
    except ValueError as exc:
        raise CanaryContractError("CANARY_VALIDATION_RETIREMENT_EVIDENCE_PATH_INVALID") from exc
    try:
        report = json.loads(report_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise CanaryContractError("CANARY_VALIDATION_RETIREMENT_EVIDENCE_MISSING") from exc
    if (report.get("authority") != "DIAGNOSTIC_ONLY"
            or int(report.get("model_dispatch_count") or 0) != 0
            or int(report.get("provider_dispatch_count") or 0) != 0
            or report.get("status") != "UNVERIFIED_REVIEW_PROJECTION"):
        raise CanaryContractError("CANARY_VALIDATION_RETIREMENT_EVIDENCE_NOT_UNVERIFIED")
    projections = [row for row in report.get("projections") or [] if isinstance(row, dict)]
    matching = [row for row in projections if str(row.get("frame")) in {"1", "01"}]
    errors = [str(error) for row in matching for error in row.get("errors") or []]
    reason_present = (
        reason == "UNVERIFIED_REVIEW_PROJECTION"
        or (reason == "REVIEW_EXECUTION_RECEIPT_UNRECOVERABLE"
            and any("receipt missing" in error.lower() for error in errors))
        or (reason == "GENERATION_IDENTITY_MISMATCH"
            and any("generation_key" in error.lower() for error in errors))
    )
    if not matching or not reason_present:
        raise CanaryContractError("CANARY_VALIDATION_RETIREMENT_REASON_UNSUPPORTED_BY_EVIDENCE")

    # Critic logs without a completed turn are not recoverable execution
    # receipts. A completed turn is conservatively rejected for manual review.
    critic_logs = sorted((episode / "meta").glob("frame-semantic-critic-attempt-*.jsonl"))
    for log_path in critic_logs:
        try:
            if "turn.completed" in log_path.read_text(encoding="utf-8-sig"):
                raise CanaryContractError("CANARY_VALIDATION_RETIREMENT_RECOVERABLE_CRITIC_TURN")
        except OSError as exc:
            raise CanaryContractError("CANARY_VALIDATION_RETIREMENT_CRITIC_EVIDENCE_UNREADABLE") from exc
    attempt = generation_attempt_authority.load_attempt(episode, key, 1)
    if (not isinstance(attempt, Mapping)
            or str(attempt.get("status") or "") != "SUCCEEDED"
            or not str(attempt.get("result_ref") or "").strip()):
        raise CanaryContractError("CANARY_VALIDATION_RETIREMENT_GENERATION_ATTEMPT_MISSING")
    return {
        "logical_asset_key": key,
        "attempts_consumed": consumed,
        "remaining_attempts": remaining,
        "active_attempt_index": None,
        "attempt1_generation_key": attempt.get("generation_key"),
        "queue_status": (queue.get("items") or [])[0].get("status"),
        "stale_review_claims": stale_review_claims,
        "review_receipt_present": False,
        "recoverable_critic_turn_present": False,
        "diagnostic_report_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
        "diagnostic_report_ref": report_path.relative_to(episode).as_posix(),
    }


def retire_validation_epoch(ep: str | Path, canary_id: str, *,
                            retirement_reason: str,
                            evidence_ref: str | Path) -> dict[str, Any]:
    """Retire an unrecoverable validation epoch without changing Attempt facts.

    Retirement and generation reservation share the same OS file lock. The
    immutable record reserves exactly one successor ID, so retries cannot
    branch the epoch chain or consume the source's remaining budget.
    """
    from runtime_atomic_store import FileLock

    if retirement_reason not in _RETIREMENT_REASONS:
        raise CanaryContractError("CANARY_VALIDATION_RETIREMENT_REASON_INVALID")
    episode, _marker = validate_workspace(ep, canary_id)
    with FileLock(
        validation_epoch_lock_target(episode),
        timeout=runtime_timeout_policy.seconds("authority_lock"),
        stale_seconds=3600,
    ):
        existing = _read_retirement(canary_id)
        if existing is not None:
            if existing.get("retirement_reason") != retirement_reason:
                raise CanaryContractError("CANARY_VALIDATION_RETIREMENT_CONFLICT")
            return dict(existing)
        evidence = _retirement_evidence(episode, canary_id, retirement_reason, evidence_ref)
        source = _retirement_source_claim(episode, canary_id)
        successor_id = f"phase5a-validation-e{int(source['_epoch_index']) + 1}-{uuid.uuid4().hex[:12]}"
        record = {
            "schema_version": 1,
            "canary_type": CANARY_TYPE,
            "canary_id": canary_id,
            "workspace": str(episode),
            "validation_epoch": int(source["_epoch_index"]),
            "retired": True,
            "retirement_reason": retirement_reason,
            "retirement_evidence": evidence,
            "retired_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "attempts_consumed": evidence["attempts_consumed"],
            "remaining_attempts": evidence["remaining_attempts"],
            "active_attempt_index": None,
            "generation_dispatch_eligible": False,
            "review_dispatch_eligible": False,
            "promotable": False,
            "release_eligible": False,
            "stage_authority": False,
            "parent_epoch_id": canary_id,
            "successor_epoch_id": successor_id,
        }
        path = _retirement_path(canary_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            raced = _read_retirement(canary_id)
            if raced is not None and raced.get("retirement_reason") == retirement_reason:
                return dict(raced)
            raise CanaryContractError("CANARY_VALIDATION_RETIREMENT_CONFLICT")
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(record, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
        except Exception as exc:
            raise CanaryContractError("CANARY_VALIDATION_RETIREMENT_WRITE_FAILED_FAIL_CLOSED") from exc
        return record


def _claim_validation_epoch(ep: Path, canary_id: str, *, previous_claim: Mapping[str, Any]) -> dict[str, Any]:
    episode, _marker = validate_workspace(ep, canary_id)
    previous_workspace = Path(str(previous_claim.get("workspace") or "")).resolve()
    previous_id = str(previous_claim.get("canary_id") or "")
    validate_workspace(previous_workspace, previous_id)
    existing = _validation_epoch_claims()
    epoch_index = 2 + len(existing)
    retirement = _read_retirement(previous_id)
    if retirement is not None:
        if retirement.get("successor_epoch_id") != canary_id:
            raise CanaryContractError("CANARY_VALIDATION_EPOCH_SUCCESSOR_RESERVED")
        if int(retirement.get("validation_epoch") or 0) != epoch_index - 1:
            raise CanaryContractError("CANARY_VALIDATION_EPOCH_SEQUENCE_INVALID_FAIL_CLOSED")
        evidence = dict(retirement.get("retirement_evidence") or {})
        source_reason = "SOURCE_RETIRED_UNRECOVERABLE"
    else:
        evidence = _validation_epoch_source_evidence(previous_workspace)
        source_reason = "SOURCE_EXHAUSTED_NO_REVIEW_CANDIDATE"
    directory = (ROOT / VALIDATION_EPOCH_DIR_REL).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"epoch-{epoch_index:04d}.json"
    claim = {
        "canary_type": CANARY_TYPE,
        "canary_id": str(canary_id),
        "workspace": str(episode),
        "validation_epoch": epoch_index,
        "previous_canary_id": previous_id,
        "previous_workspace": str(previous_workspace),
        "reason": source_reason,
        "previous_retired": retirement is not None,
        "previous_retirement_reason": retirement.get("retirement_reason") if retirement else None,
        "previous_successor_reservation": retirement.get("successor_epoch_id") if retirement else None,
        "previous_logical_asset_key": evidence.get("logical_asset_key"),
        "previous_attempts_consumed": evidence.get("attempts_consumed"),
        "previous_attempt2_generation_key": evidence.get("attempt2_generation_key"),
        "previous_attempt2_status": evidence.get("attempt2_status"),
        "previous_attempt2_failure_class": evidence.get("attempt2_failure_class"),
        "previous_queue_status": evidence.get("queue_status"),
        "previous_external_block_reason": evidence.get("external_block_reason"),
    }
    try:
        descriptor = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        try:
            raced = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as exc:
            raise CanaryContractError("CANARY_VALIDATION_EPOCH_CLAIM_INVALID_FAIL_CLOSED") from exc
        if raced.get("canary_id") == canary_id and raced.get("workspace") == str(episode):
            return {
                "canary_type": CANARY_TYPE,
                "canary_id": str(canary_id),
                "workspace": str(episode),
                "resumed": True,
                "replacement": False,
                "validation_epoch": epoch_index,
                "previous_canary_id": previous_id,
                "previous_retired": retirement is not None,
            }
        raise CanaryContractError("CANARY_VALIDATION_EPOCH_ALREADY_CLAIMED")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(claim, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        raise CanaryContractError("CANARY_VALIDATION_EPOCH_WRITE_FAILED_FAIL_CLOSED")
    return {
        "canary_type": CANARY_TYPE,
        "canary_id": str(canary_id),
        "workspace": str(episode),
        "resumed": False,
        "replacement": False,
        "validation_epoch": epoch_index,
        "previous_canary_id": previous_id,
        "previous_retired": retirement is not None,
    }


def _matching_validation_epoch_claim(expected: Mapping[str, Any]) -> dict[str, Any] | None:
    rows = _validation_epoch_claims()
    if not rows:
        return None
    latest = rows[-1]
    if (latest.get("canary_type") == CANARY_TYPE
            and latest.get("canary_id") == expected.get("canary_id")
            and latest.get("workspace") == expected.get("workspace")):
        return latest
    return None


def claim_global_canary(
    ep: str | Path,
    canary_id: str,
    *,
    allow_validation_epoch: bool = False,
) -> dict[str, Any]:
    """Reserve or resume the fixed Canary chain.

    Base + replacement behavior is unchanged. Additional validation epochs are
    append-only, require explicit allow_validation_epoch=True, and are admitted
    only after the immediately previous Canary exhausted its full 2-attempt
    budget with no Review candidate and no active Attempt.
    """
    episode, _marker = validate_workspace(ep, canary_id)
    claim_path = (ROOT / GLOBAL_CLAIM_REL).resolve()
    replacement_path = (ROOT / REPLACEMENT_CLAIM_REL).resolve()
    for path in (claim_path, replacement_path):
        try:
            path.relative_to(ROOT.resolve())
        except ValueError as exc:
            raise CanaryContractError("CANARY_GLOBAL_CLAIM_PATH_ESCAPE") from exc
    claim_path.parent.mkdir(parents=True, exist_ok=True)
    expected = {
        "canary_type": CANARY_TYPE,
        "canary_id": str(canary_id),
        "workspace": str(episode),
    }
    try:
        descriptor = os.open(str(claim_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        try:
            current = json.loads(claim_path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as exc:
            raise CanaryContractError("CANARY_GLOBAL_CLAIM_INVALID_FAIL_CLOSED") from exc
        if current == expected:
            return {**expected, "resumed": True, "replacement": False}

        if replacement_path.exists():
            try:
                replacement = json.loads(replacement_path.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError) as exc:
                raise CanaryContractError("CANARY_REPLACEMENT_CLAIM_INVALID_FAIL_CLOSED") from exc
            if (replacement.get("canary_type") == CANARY_TYPE
                    and replacement.get("canary_id") == expected["canary_id"]
                    and replacement.get("workspace") == expected["workspace"]
                    and replacement.get("previous_canary_id") == current.get("canary_id")
                    and replacement.get("previous_workspace") == current.get("workspace")):
                return {**expected, "resumed": True, "replacement": True,
                        "previous_canary_id": current.get("canary_id")}

            matching_epoch = _matching_validation_epoch_claim(expected)
            if matching_epoch is not None:
                return {
                    **expected,
                    "resumed": True,
                    "replacement": False,
                    "validation_epoch": int(matching_epoch.get("validation_epoch") or 0),
                    "previous_canary_id": matching_epoch.get("previous_canary_id"),
                }
            if not allow_validation_epoch:
                raise CanaryContractError("CANARY_GLOBAL_REPLACEMENT_ALREADY_CLAIMED")

            existing_epochs = _validation_epoch_claims()
            previous_claim = existing_epochs[-1] if existing_epochs else replacement
            return _claim_validation_epoch(
                episode, str(canary_id), previous_claim=previous_claim)

        previous_workspace = Path(str(current.get("workspace") or "")).resolve()
        previous_id = str(current.get("canary_id") or "")
        validate_workspace(previous_workspace, previous_id)
        # A root epoch can be followed by the append-only epoch ledger
        # without ever replacing or mutating the original global claim.
        existing_epochs = _validation_epoch_claims()
        if existing_epochs:
            matching_epoch = _matching_validation_epoch_claim(expected)
            if matching_epoch is not None:
                return {**expected, "resumed": True, "replacement": False,
                        "validation_epoch": int(matching_epoch.get("validation_epoch") or 0),
                        "previous_canary_id": matching_epoch.get("previous_canary_id")}
            if not allow_validation_epoch:
                raise CanaryContractError("CANARY_VALIDATION_EPOCH_EXPLICIT_AUTHORIZATION_REQUIRED")
            return _claim_validation_epoch(
                episode, str(canary_id), previous_claim=existing_epochs[-1])

        # Explicitly authorized epoch-2 successor for a retired initial
        # Canary; this does not reuse or clear the original Attempt budget.
        original_retirement = _read_retirement(previous_id)
        if original_retirement is not None:
            if not allow_validation_epoch:
                raise CanaryContractError("CANARY_VALIDATION_EPOCH_EXPLICIT_AUTHORIZATION_REQUIRED")
            return _claim_validation_epoch(
                episode, str(canary_id),
                previous_claim={**current, "validation_epoch": 1, "_epoch_index": 1})
        evidence = _replacement_source_evidence(previous_workspace)
        replacement = {
            "canary_type": CANARY_TYPE,
            "canary_id": expected["canary_id"],
            "workspace": expected["workspace"],
            "previous_canary_id": previous_id,
            "previous_workspace": str(previous_workspace),
            "reason": "PRIOR_CANARY_OUTCOME_UNKNOWN_NO_ARTIFACT",
            "previous_generation_key": evidence.get("generation_key"),
            "previous_failure_class": evidence.get("failure_class"),
        }
        try:
            replacement_descriptor = os.open(
                str(replacement_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            raise CanaryContractError("CANARY_GLOBAL_REPLACEMENT_ALREADY_CLAIMED")
        try:
            with os.fdopen(replacement_descriptor, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(replacement, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
        except Exception:
            raise CanaryContractError("CANARY_REPLACEMENT_CLAIM_WRITE_FAILED_FAIL_CLOSED")
        return {**expected, "resumed": False, "replacement": True,
                "previous_canary_id": previous_id}
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(expected, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        # Keep a partial claim as a fail-closed marker; never silently free a slot.
        raise CanaryContractError("CANARY_GLOBAL_CLAIM_WRITE_FAILED_FAIL_CLOSED")
    return {**expected, "resumed": False, "replacement": False}


def validate_queued_attempt(item: Mapping[str, Any], asset_state: Mapping[str, Any]) -> None:
    """Share one max-2 image budget across primary, technical retry and repair."""
    if item.get("status") != "queued":
        return
    if asset_state.get("active_attempt_index") is not None:
        raise CanaryContractError("CANARY_GENERATION_ATTEMPT_ALREADY_ACTIVE")
    consumed = int(asset_state.get("attempts_consumed") or 0)
    remaining = int(asset_state.get("remaining_attempts") or 0)
    if remaining <= 0:
        raise CanaryContractError("CANARY_GENERATION_ATTEMPT_BUDGET_EXHAUSTED")
    if item.get("kind") == "original" and consumed > 0:
        technical_retry = (
            str(item.get("generation_attempt_reason") or "") == "TECHNICAL_RETRY"
            and str(item.get("technical_retry_source_code") or "") == "ASPECT_RATIO_MISMATCH"
            and consumed == 1
            and remaining == 1
        )
        if not technical_retry:
            raise CanaryContractError("CANARY_ORIGINAL_ITEM_CANNOT_USE_ATTEMPT2")


def _model_execution_receipts(ep: Path) -> list[dict[str, Any]]:
    directory = ep / "meta/provider-receipts/model-executions"
    rows: list[dict[str, Any]] = []
    if not directory.is_dir():
        return rows
    for path in sorted(directory.glob("*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _reconcile_failed_final_semantic_receipts(
    ep: Path, *, generation_key: str, artifact_sha256: str,
) -> list[dict[str, Any]]:
    """Terminalize impossible provisional receipts without deleting evidence.

    A Final Semantic call is provisional only when its process returned 0 and
    awaits durable/schema validation. Older code incorrectly left rc!=0 calls
    as PENDING_VALIDATION. Convert only the provably terminal form to FAILED;
    keep call/request identity and the original durable evidence intact.
    """
    import runtime_observability

    reconciled: list[dict[str, Any]] = []
    for row in _model_execution_receipts(ep):
        if (row.get("model_role") != "vision.final"
                or row.get("generation_key") != generation_key
                or row.get("artifact_sha256") != artifact_sha256
                or row.get("status") != "PENDING_VALIDATION"):
            continue
        try:
            returncode = int(row.get("returncode"))
        except (TypeError, ValueError):
            continue
        if returncode == 0 or row.get("durable_result_status") != "TURN_NOT_COMPLETED":
            continue
        terminal = dict(row)
        terminal["status"] = "FAILED"
        terminal["status_reconciled_from"] = "PENDING_VALIDATION"
        terminal["status_reconciliation_reason"] = "NONZERO_RETURN_CODE_BEFORE_FINAL_VALIDATION"
        terminal["status_reconciled_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        runtime_observability.write_model_execution_receipt(ep, receipt=terminal)
        reconciled.append(terminal)
    return reconciled


def _partition_final_semantic_receipts(
    rows: list[dict[str, Any]], *, embedded_call_id: str,
) -> dict[str, list[dict[str, Any]]]:
    """Separate canonical success from visible terminal failures/unresolved calls."""
    successful = [
        row for row in rows
        if row.get("status") == "SUCCESS" and row.get("durable_result_status") == "VALIDATED"
    ]
    failed: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for row in rows:
        if row in successful:
            continue
        try:
            returncode = int(row.get("returncode"))
        except (TypeError, ValueError):
            returncode = 0
        if (row.get("status") == "FAILED" and returncode != 0
                and row.get("durable_result_status") != "VALIDATED"):
            failed.append(row)
        else:
            unresolved.append(row)
    embedded = [row for row in successful
                if embedded_call_id and row.get("call_id") == embedded_call_id]
    return {
        "successful": successful,
        "failed": failed,
        "unresolved": unresolved,
        "embedded": embedded,
    }


def _model_execution_receipt_snapshot(ep: Path) -> dict[str, str]:
    """Return a stable id-to-content digest snapshot for resume call counting."""
    directory = ep / "meta/provider-receipts/model-executions"
    snapshot: dict[str, str] = {}
    if not directory.is_dir():
        return snapshot
    for path in sorted(directory.glob("*.json")):
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        snapshot[path.stem] = hashlib.sha256(raw).hexdigest()
    return snapshot


def _trace_event_count(ep: Path, event_type: str, *, logical_asset_key: str,
                       generation_key: str) -> int:
    import runtime_observability

    path = ep / runtime_observability.TRACE_EVENTS_REL
    if not path.is_file():
        return 0
    count = 0
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        try:
            row = json.loads(raw)
        except ValueError:
            continue
        if (isinstance(row, dict) and row.get("event_type") == event_type
                and row.get("logical_asset_key") == logical_asset_key
                and row.get("generation_key") == generation_key):
            count += 1
    return count


def validate_workspace(ep: str | Path, canary_id: str) -> tuple[Path, dict[str, Any]]:
    """Accept only a marked disposable workspace below the reserved temp root."""
    episode = Path(ep).resolve()
    try:
        relative = episode.relative_to(ROOT)
    except ValueError as exc:
        raise CanaryContractError("CANARY_WORKSPACE_OUTSIDE_REPOSITORY") from exc
    if relative.parts[:len(WORKSPACE_REL.parts)] != WORKSPACE_REL.parts:
        raise CanaryContractError("CANARY_WORKSPACE_PATH_REQUIRED")
    if relative.parts[len(WORKSPACE_REL.parts):] != (str(canary_id),):
        raise CanaryContractError("CANARY_WORKSPACE_ID_MISMATCH")
    marker_path = episode / MARKER_REL
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise CanaryContractError("CANARY_WORKSPACE_MARKER_REQUIRED") from exc
    expected = workspace_marker(canary_id)
    if not isinstance(marker, dict) or marker != expected:
        raise CanaryContractError("CANARY_WORKSPACE_MARKER_INVALID")
    return episode, marker


def _active_canary_queue_items(queue: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return current production rows while preserving superseded history."""
    return [
        row for row in queue.get("items") or []
        if isinstance(row, dict) and str(row.get("status") or "") != "superseded"
    ]


def _assert_final_semantic_recovery_safe(queue: Mapping[str, Any], item: Mapping[str, Any]) -> None:
    """Do not advertise READY for an interrupted, unreceipted final critic.

    Generation success is independent of Final Semantic completion. A blocked
    model call cannot be replayed merely because the image output exists.
    Only the official Review Authority may reconcile or requeue its evidence.
    """
    generation_key = str(item.get("generation_key") or "")
    if not generation_key:
        return
    for review in queue.get("review_work_items") or []:
        if (not isinstance(review, Mapping)
                or review.get("review_kind") != "FINAL_SEMANTIC"
                or str(review.get("generation_key") or "") != generation_key):
            continue
        if review.get("status") == "blocked":
            if (review.get("technical_failure_code")
                    == "FINAL_SEMANTIC_UNVERIFIED_INTERRUPTED_CALL"
                    and not isinstance(review.get("receipt"), dict)):
                raise CanaryContractError("CANARY_FINAL_SEMANTIC_EXECUTION_UNVERIFIED")
            raise CanaryContractError("CANARY_FINAL_SEMANTIC_BLOCKED_REQUIRES_RECOVERY")


def _preflight(ep: Path, canary_id: str) -> dict[str, Any]:
    """Check all durable bindings before asking the canonical scheduler to run."""
    import fast_frame_scout
    import frame_contract
    import generation_attempt_authority
    import image_model_policy
    import logical_asset_identity
    import model_policy
    import prompt_package
    import production_queue_store
    import runtime_request
    import scheduler_core
    import storyos_config
    import storage_config

    authorize_entry(entrypoint=CANARY_ENTRYPOINT, runtime_request=None)
    ep, marker = validate_workspace(ep, canary_id)
    authorize_action("RUN_PRODUCTION_SUBPATH")
    cfg = storyos_config.load_config()
    errors = storyos_config.validate(cfg)
    if errors:
        raise CanaryContractError("CONFIG_INVALID: " + "; ".join(str(x) for x in errors))
    mode = storyos_config.get_path(cfg, "production.mode")
    if mode != "COLLABORATIVE":
        raise CanaryContractError("CANARY_REQUIRES_COLLABORATIVE_MODE")
    mysql = storage_config.mysql_connection_kwargs()
    if (str(mysql.get("host")) not in {"127.0.0.1", "localhost"}
            or int(mysql.get("port") or 0) != 3306
            or str(mysql.get("database")) != DATABASE_NAME):
        raise CanaryContractError("CANARY_TEST_ONLY_MYSQL_REQUIRED")
    if (ep / "meta/episode-state.json").exists():
        raise CanaryContractError("CANARY_CANONICAL_STAGE_AUTHORITY_FORBIDDEN")
    if not (ep / "meta/release-manifest.json").is_file():
        raise CanaryContractError("CANARY_FRAME_CONTRACT_INPUTS_MISSING")
    bound_request = runtime_request.effective_for_episode(ep)
    if not bound_request:
        raise CanaryContractError("CANARY_RUNTIME_REQUEST_NOT_BOUND")
    errors = model_policy.validate_bound_policy(ep)
    if errors:
        raise CanaryContractError("CANARY_MODEL_POLICY_NOT_FROZEN: " + "; ".join(errors))
    controller = model_policy.resolve("image.controller", episode=ep)
    reviewer = model_policy.resolve("vision.final", episode=ep)
    payload = image_model_policy.for_episode(ep)
    if (controller.get("model"), controller.get("reasoning_effort")) != ("gpt-6-luna", "high"):
        raise CanaryContractError("CANARY_CONTROLLER_BINDING_MISMATCH")
    if (payload.get("model"), payload.get("quality")) != ("gpt-image-2.5-flare", "high"):
        raise CanaryContractError("CANARY_PAYLOAD_BINDING_MISMATCH")
    if (reviewer.get("model"), reviewer.get("reasoning_effort")) != ("gpt-6-luna", "high"):
        raise CanaryContractError("CANARY_REVIEW_BINDING_MISMATCH")
    queue = scheduler_core.load_queue(ep)
    items = _active_canary_queue_items(queue)
    if len(items) != 1:
        raise CanaryContractError("CANARY_REQUIRES_EXACTLY_ONE_QUEUE_ITEM")
    item = items[0]
    if int(item.get("frame") or 0) != 1 or str(item.get("scope") or "") != "batch":
        raise CanaryContractError("CANARY_QUEUE_ITEM_MUST_BE_SINGLE_PRODUCTION_FRAME")
    if str(item.get("kind") or "") != "original":
        raise CanaryContractError("CANARY_QUEUE_ITEM_KIND_INVALID")
    if item.get("status") not in {"queued", "generated"}:
        raise CanaryContractError("CANARY_QUEUE_ITEM_NOT_RUNNABLE_OR_COMPLETE")
    if not item.get("prompt_package"):
        raise CanaryContractError("CANARY_PRODUCTION_PROMPT_NOT_COMPILED_FROM_CONTRACT")
    prompt_raw = str(item.get("prompt_file") or "").strip()
    if not prompt_raw:
        raise CanaryContractError("CANARY_PRODUCTION_PROMPT_SOURCE_MISSING")
    prompt_path = Path(prompt_raw)
    prompt_path = prompt_path if prompt_path.is_absolute() else (ROOT / prompt_path).resolve()
    if not prompt_path.is_file():
        raise CanaryContractError("CANARY_PRODUCTION_PROMPT_SOURCE_MISSING")
    try:
        compiled_contract = frame_contract.compile_frame(ep, 1, write_cache=False)
        compiled_prompt = prompt_package.compile_frame(ep, 1, prompt_path, write=False)
    except Exception as exc:
        raise CanaryContractError(f"CANARY_PRODUCTION_INPUT_COMPILE_FAILED: {exc}") from exc
    frame_contract_sha = str(compiled_contract.get("contract_sha256") or "").lower()
    queued_contract_sha = str(((item.get("frame_contract") or {}).get("contract_sha256")) or "").lower()
    prompt_package_sha = str(compiled_prompt.get("package_sha256") or "").lower()
    queued_package_sha = str(((item.get("prompt_package") or {}).get("package_sha256")) or "").lower()
    if not frame_contract_sha or frame_contract_sha != queued_contract_sha:
        raise CanaryContractError("CANARY_FRAME_CONTRACT_SOURCE_BINDING_MISMATCH")
    if (not prompt_package_sha or prompt_package_sha != queued_package_sha
            or compiled_prompt.get("frame_contract_sha256") != frame_contract_sha):
        raise CanaryContractError("CANARY_PROMPT_PACKAGE_SOURCE_BINDING_MISMATCH")
    if not fast_frame_scout.required(ep):
        raise CanaryContractError("CANARY_REVIEW_LANE_NOT_REQUIRED")
    key = logical_asset_identity.frame_asset_key(ep, 1)
    asset_state = generation_attempt_authority.load_asset_state(ep, key)
    validate_generation_count(asset_state["attempts_consumed"])
    # A completed queue item is safe to resume only when its persisted
    # Generation identity is backed by the immutable Attempt Authority.
    if item.get("status") == "generated":
        generation_key = str(item.get("generation_key") or "")
        attempt_index = int(item.get("attempt_index") or 0)
        if not generation_key or attempt_index <= 0:
            raise CanaryContractError("CANARY_GENERATED_ITEM_IDENTITY_MISSING")
        attempt = generation_attempt_authority.load_attempt(ep, key, attempt_index)
        if (not isinstance(attempt, Mapping)
                or str(attempt.get("generation_key") or "") != generation_key
                or str(attempt.get("status") or "").upper() != "SUCCEEDED"):
            raise CanaryContractError("CANARY_GENERATED_ITEM_IDENTITY_AUTHORITY_MISMATCH")
    # A queued item may be run only when no lease is active and the hard ceiling
    # still has capacity.
    validate_queued_attempt(item, asset_state)
    _assert_final_semantic_recovery_safe(queue, item)
    return {
        "episode": ep,
        "episode_path": str(ep.resolve()),
        "canary_id": canary_id,
        "marker": marker,
        "runtime_request_id": bound_request.get("request_id"),
        "policy_version": controller.get("policy_version"),
        "policy_sha256": controller.get("model_policy_sha256"),
        "model_policy_sha256": controller.get("model_policy_sha256"),
        "controller": {"model": controller.get("model"), "effort": controller.get("reasoning_effort")},
        "reviewer": {"model": reviewer.get("model"), "effort": reviewer.get("reasoning_effort"),
                     "profile": reviewer.get("profile")},
        "payload": {"model": payload.get("model"), "quality": payload.get("quality")},
        "payload_model": str(payload.get("model") or ""),
        "payload_quality": str(payload.get("quality") or "").lower(),
        "logical_asset_key": key,
        "frame_contract_sha256": frame_contract_sha,
        "prompt_package_sha256": prompt_package_sha,
        "attempt_state": asset_state,
        "attempts_consumed": int(asset_state.get("attempts_consumed") or 0),
        "remaining_attempts": int(asset_state.get("remaining_attempts") or 0),
        "active_attempt_index": asset_state.get("active_attempt_index"),
        "generation_attempt_reason": str(item.get("generation_attempt_reason") or "PRIMARY_GENERATION"),
        "technical_retry_source_code": str(item.get("technical_retry_source_code") or ""),
        "queue_item_id": item.get("id"),
        "queue_item_count": len(items),
        "frame": int(item.get("frame") or 0),
        "kind": str(item.get("kind") or ""),
        "scope": str(item.get("scope") or ""),
        "queue_item_status": item.get("status"),
        "generation_key": item.get("generation_key"),
        "attempt_index": int(item.get("attempt_index") or 0) or None,
        "queue_authority": production_queue_store.authority(ep),
    }



def _controller_probe_event_calls_image_generation(value: object) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if (str(key) in {"type", "tool", "tool_name", "name", "function"}
                    and str(child).strip() in {"image_generation", "image_generation_call"}):
                return True
            if _controller_probe_event_calls_image_generation(child):
                return True
    elif isinstance(value, list):
        return any(_controller_probe_event_calls_image_generation(child) for child in value)
    return False


def _controller_probe_facts(raw: str) -> dict[str, Any]:
    """Parse only protocol facts needed to adopt a completed cleanup timeout."""
    import json as _json
    turn_completed = False
    image_generation_call_count = 0
    malformed_jsonl = False
    diagnostic_noise_line_count = 0
    for line in str(raw or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            row = _json.loads(stripped)
        except (TypeError, ValueError):
            if stripped.startswith(("{", "[")):
                malformed_jsonl = True
            else:
                diagnostic_noise_line_count += 1
            continue
        if not isinstance(row, dict):
            continue
        if _controller_probe_event_calls_image_generation(row):
            image_generation_call_count += 1
        if row.get("type") == "turn.completed":
            turn_completed = True
    return {
        "turn_completed": turn_completed,
        "image_generation_call_count": image_generation_call_count,
        "malformed_jsonl": malformed_jsonl,
        "diagnostic_noise_line_count": diagnostic_noise_line_count,
    }


def _recover_controller_cleanup_timeout(runner_diagnostics: dict[str, Any],
                                        codex_critic_runner: Any,
                                        codex_user_runner: Any) -> dict[str, Any]:
    request_id = str((runner_diagnostics or {}).get("request_id") or "").strip()
    if not request_id or not (runner_diagnostics or {}).get("durable_result_present"):
        return {"adopted": False, "reason": "DURABLE_RESULT_UNAVAILABLE"}
    try:
        result = codex_user_runner.read_task_result(request_id)
    except Exception:
        return {"adopted": False, "reason": "DURABLE_RESULT_READ_FAILED"}
    if not isinstance(result, dict):
        return {"adopted": False, "reason": "DURABLE_RESULT_INVALID"}
    encoded = str(result.get("output_base64") or "")
    if not encoded:
        return {"adopted": False, "reason": "DURABLE_OUTPUT_MISSING"}
    try:
        raw = base64.b64decode(encoded, validate=True).decode("utf-8", "replace")
    except Exception:
        return {"adopted": False, "reason": "DURABLE_OUTPUT_INVALID"}
    facts = _controller_probe_facts(raw)
    recovered = codex_critic_runner.recover_completed_agent_json(raw)
    adopted = bool(
        recovered == {"capability_probe": "PASS"}
        and facts["turn_completed"]
        and facts["image_generation_call_count"] == 0
        and not facts["malformed_jsonl"]
    )
    return {
        "adopted": adopted,
        "reason": "PASS_WITH_CLEANUP_TIMEOUT" if adopted else "DURABLE_PROBE_INVALID",
        "turn_completed": facts["turn_completed"],
        "image_generation_call_count": facts["image_generation_call_count"],
        "malformed_jsonl": facts["malformed_jsonl"],
        "diagnostic_noise_line_count": facts["diagnostic_noise_line_count"],
        "request_id": request_id,
    }


def exact_controller_capability_preflight(ep: str | Path, *, codex: str | None = None,
                                          timeout: int | None = None) -> dict[str, Any]:
    """Execute a tiny exact-model text task before the image Scheduler can run.

    The call uses the frozen Episode controller binding and the regular scoped
    text runner. It deliberately does not inherit the legacy image worker's
    ChatGPT image-tool endpoint override. It does not call image_generation,
    the Attempt Authority, or the Production Ledger.
    """
    import codex_user_runner
    import codex_critic_runner
    import logical_asset_identity
    import model_policy
    import runtime_observability
    import runtime_timeout_policy
    import scoped_codex_worker

    episode = Path(ep).resolve()
    call_id = uuid.uuid4().hex
    run_id = f"phase5a-controller-probe-{call_id[:12]}"
    trace_id = f"ST_{call_id[:16]}"
    started_at = runtime_observability.now()
    started = time.monotonic()
    binding: dict[str, Any] = {}
    argv: list[str] = []
    auth_context = "unverified"
    status = "FAILED"
    failure_class = "CONTROLLER_PROBE_FAILED"
    returncode: int | None = None
    error_detail = ""
    failure_diagnostics: dict[str, Any] = {
        "protocol_failure_type": None,
        "http_status": None,
        "websocket_attempted": False,
        "endpoint_class": "UNKNOWN",
        "runner_request_id": None,
        "durable_result_present": False,
    }

    try:
        errors = model_policy.validate_bound_policy(episode)
        if errors:
            raise RuntimeError("MODEL_POLICY_NOT_FROZEN: " + "; ".join(errors))
        binding = model_policy.resolve("image.controller", episode=episode)
        requested_model = str(binding.get("model") or "")
        effort = str(binding.get("reasoning_effort") or "").lower()
        if (requested_model, effort) != ("gpt-6-luna", "high"):
            raise RuntimeError("CANARY_CONTROLLER_BINDING_MISMATCH")
        if not binding.get("model_policy_sha256"):
            raise RuntimeError("CANARY_CONTROLLER_POLICY_SHA_MISSING")

        # Controller execution uses the regular scoped text runner. Do not
        # inherit the legacy image worker's ChatGPT image-tool endpoint override:
        # that transport is precisely where Luna was rejected, and the Controller
        # has no image_generation capability requirement.
        probe_prompt = (
            'Return only this exact JSON object and do not call tools: '
            '{"capability_probe":"PASS"}'
        )
        probe_stream = io.StringIO()
        auth_context = "user_runner" if codex_user_runner.bridge_required() else "direct_codex_user_runner"
        rc, receipt = scoped_codex_worker.execute_model_call(
            episode, "EXACT_CONTROLLER_CAPABILITY_PREFLIGHT", binding, probe_prompt,
            codex_raw=codex, timeout=(int(timeout) if timeout is not None
                                      else runtime_timeout_policy.seconds("codex_auth_probe")),
            run_id=run_id, trace_id=trace_id, call_id=call_id,
            output_handle=probe_stream, sandbox="read-only",
            receipt_fields={
                "provider": "codex_cli_configured_transport",
                "provider_source": "CODEX_CLI_CONFIG",
                "runner": "codex_user_runner",
                "auth_context": auth_context,
                "effective_model_source": "EXPLICIT_RUNTIME_BINDING",
                "image_generation_enabled": False,
            },
        )
        returncode = int(rc)
        argv = list(receipt.get("codex_argv") or [])
        runner_diagnostics = receipt.get("runner_diagnostics")
        if isinstance(runner_diagnostics, dict):
            failure_diagnostics["runner_request_id"] = runner_diagnostics.get("request_id")
            failure_diagnostics["durable_result_present"] = bool(
                runner_diagnostics.get("durable_result_present")
            )
        if not ("-m" in argv and "gpt-6-luna" in argv and "-c" in argv
                and 'model_reasoning_effort="high"' in argv):
            status = "FAILED"
            failure_class = "EXACT_CONTROLLER_BINDING_NOT_PRESENT_IN_ARGV"
            error_detail = "EXPLICIT_MODEL_OR_EFFORT_ARGV_MISSING"
            returncode = returncode or 1
            raise RuntimeError(failure_class)
        # A zero process exit is insufficient: require Codex's completed
        # assistant result and the exact structured sentinel. A runner cleanup
        # timeout may be adopted only from its durable result when the turn
        # already completed, the sentinel is exact, and no image tool ran.
        result_object = (codex_critic_runner.recover_completed_agent_json(
            probe_stream.getvalue()) if returncode == 0 else None)
        cleanup_recovery = None
        if returncode == 124:
            cleanup_recovery = _recover_controller_cleanup_timeout(
                runner_diagnostics, codex_critic_runner, codex_user_runner
            )
        if returncode == 0 and result_object == {"capability_probe": "PASS"}:
            status = "SUCCESS"
            failure_class = ""
        elif returncode == 124 and cleanup_recovery and cleanup_recovery.get("adopted"):
            status = "SUCCESS"
            failure_class = ""
            error_detail = ""
            failure_diagnostics = {
                **failure_diagnostics,
                "runner_request_id": cleanup_recovery.get("request_id"),
                "durable_result_present": True,
                "cleanup_timeout_recovered": True,
                "cleanup_timeout_recovery": "PASS_WITH_CLEANUP_TIMEOUT",
                "turn_completed": cleanup_recovery.get("turn_completed"),
                "image_generation_call_count": cleanup_recovery.get("image_generation_call_count"),
                "diagnostic_noise_line_count": cleanup_recovery.get("diagnostic_noise_line_count"),
            }
        elif returncode != 0:
            failure_class, failure_diagnostics = _controller_failure_diagnostics(
                probe_stream.getvalue(), returncode, runner_diagnostics
            )
            error_detail = "CODEX_EXEC_NONZERO_EXIT"
        else:
            failure_class = "PROBE_RESULT_INVALID"
            error_detail = "COMPLETED_ASSISTANT_RESULT_DID_NOT_MATCH_SENTINEL"
    except subprocess.TimeoutExpired as exc:
        failure_class = "RUNNER_TIMEOUT"
        error_detail = type(exc).__name__
    except Exception as exc:
        # Exception text may contain endpoints or credentials. Use stable type
        # and a narrow known contract code; never persist the message itself.
        lowered = type(exc).__name__.lower()
        if "exact_controller_binding_not_present_in_argv" in str(exc).lower():
            failure_class = "EXACT_CONTROLLER_BINDING_NOT_PRESENT_IN_ARGV"
            error_detail = "EXPLICIT_MODEL_OR_EFFORT_ARGV_MISSING"
        elif "auth" in lowered or "401" in str(exc):
            failure_class = "AUTH_FAILED"
        elif "runner" in lowered or "connectionerror" in lowered or "timeout" in lowered:
            failure_class = "RUNNER_UNAVAILABLE"
        else:
            failure_class = "CONTROLLER_PROBE_FAILED"
        # Do not copy exception messages or captured process output into the
        # durable receipt. Those strings can contain transport/auth details.
        error_detail = type(exc).__name__

    finished_at = runtime_observability.now()
    receipt = {
        "receipt_schema_version": 1,
        "episode_id": logical_asset_identity.episode_id(episode),
        "run_id": run_id,
        "trace_id": trace_id,
        "step": "EXACT_CONTROLLER_CAPABILITY_PREFLIGHT",
        "call_id": call_id,
        "model_role": binding.get("role") or "image.controller",
        "profile": binding.get("profile") or "image_controller",
        "requested_model": binding.get("model") or "gpt-6-luna",
        "effective_model": binding.get("model") or "gpt-6-luna",
        "reasoning_effort": binding.get("reasoning_effort") or "high",
        "model_policy_version": binding.get("policy_version") or "unknown",
        "model_policy_sha256": binding.get("model_policy_sha256") or "unknown",
        "provider": "codex_cli_configured_transport",
        "runner": "codex_user_runner",
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_ms": round((time.monotonic() - started) * 1000, 3),
        "status": status,
        "model_binding_source": "EPISODE_BOUND_MODEL_POLICY",
        "effective_model_source": "EXPLICIT_RUNTIME_BINDING",
        "codex_argv": argv,
        "auth_context": auth_context,
        "returncode": returncode,
        "failure_class": failure_class or None,
        "error_detail": error_detail or None,
        **failure_diagnostics,
        "probe_result_valid": status == "SUCCESS",
        "image_generation_called": False,
        "image_attempt_authority_called": False,
    }
    try:
        receipt_path = runtime_observability.write_model_execution_receipt(episode, receipt=receipt)
        receipt["receipt_path"] = str(receipt_path)
        _telemetry(episode, "MODEL_EXECUTION", step=receipt["step"], call_id=call_id,
                   model_role=receipt["model_role"], profile=receipt["profile"],
                   requested_model=receipt["requested_model"],
                   effective_model_source=receipt["effective_model_source"],
                   reasoning_effort=receipt["reasoning_effort"],
                   model_policy_sha256=receipt["model_policy_sha256"],
                   provider=receipt["provider"], runner=receipt["runner"],
                   status=status, duration_ms=receipt["duration_ms"])
    except Exception as exc:
        # Missing durable probe evidence must fail closed before any image work.
        return {"status": "BLOCKED", "failure_class": "PROBE_RECEIPT_WRITE_FAILED",
                "reason": str(exc)[:600], "receipt": receipt}
    return {"status": "PASS" if status == "SUCCESS" else "BLOCKED",
            "failure_class": failure_class or None,
            "reason": error_detail or None, "receipt": receipt}


def _controller_failure_diagnostics(output: str, returncode: int | None,
                                    runner: object = None) -> tuple[str, dict[str, Any]]:
    """Classify controller transport failures without persisting raw output."""
    text = str(output or "").lower()
    status_match = re.search(r"\b(?:http(?:\s+error)?\s*[: ]\s*)?(4\d\d|5\d\d)\b", text)
    http_status = int(status_match.group(1)) if status_match else None
    websocket_attempted = any(token in text for token in (
        "websocket", "web_socket", "responses_websocket", "responses websocket"
    ))
    if "127.0.0.1:10100" in text or "localhost:10100" in text:
        endpoint_class = "LOCAL_PROXY"
    elif "chatgpt.com/backend-api/codex" in text:
        endpoint_class = "CHATGPT_SUBSCRIPTION"
    elif "api.openai.com" in text:
        endpoint_class = "DIRECT_API"
    else:
        endpoint_class = "UNKNOWN"
    diagnostics: dict[str, Any] = {
        "protocol_failure_type": None,
        "http_status": http_status,
        "websocket_attempted": websocket_attempted,
        "endpoint_class": endpoint_class,
        "runner_request_id": None,
        "durable_result_present": False,
    }
    if isinstance(runner, dict):
        diagnostics["runner_request_id"] = runner.get("request_id")
        diagnostics["durable_result_present"] = bool(runner.get("durable_result_present"))
    if http_status == 426 and websocket_attempted:
        diagnostics["protocol_failure_type"] = "TRANSPORT_WEBSOCKET_UPGRADE_REJECTED"
        return "CONTROLLER_PROTOCOL_FAILURE", diagnostics
    if http_status == 401 or any(token in text for token in (
        "unauthorized", "authentication failed", "login required"
    )):
        return "AUTH_FAILED", diagnostics
    if http_status == 400 and any(token in text for token in (
        "model unsupported", "model is not supported", "unknown model", "model unavailable"
    )):
        return "MODEL_UNAVAILABLE", diagnostics
    return ("CONTROLLER_EXECUTION_FAILED" if returncode else "PROBE_RESULT_INVALID"), diagnostics


def requires_generation_capability_preflight(preflight: Mapping[str, Any]) -> bool:
    """Return whether this invocation can still dispatch a real image.

    Resume from a successfully generated artifact skips Payload/Controller
    generation-capability probes because those probes cannot affect the already
    committed artifact and only add latency/failure surface.
    """
    status = str(preflight.get("queue_item_status") or "")
    if status == "queued":
        return True
    if status == "generated":
        generation_key = str(preflight.get("generation_key") or "")
        attempt_index = int(preflight.get("attempt_index") or 0)
        consumed = int(preflight.get("attempts_consumed") or 0)
        active = preflight.get("active_attempt_index")
        if generation_key and attempt_index > 0 and consumed >= attempt_index and active is None:
            return False
        raise CanaryContractError("CANARY_GENERATED_RESUME_IDENTITY_INVALID")
    raise CanaryContractError("CANARY_GENERATION_CAPABILITY_SCOPE_INVALID")


def run_production_subpath(ep: str | Path, *, canary_id: str, timeout: int | None = None,
                           codex: str | None = None, dry_run: bool = False,
                           allow_validation_epoch: bool = False) -> dict[str, Any]:
    """Run/resume exactly one item through the existing Production Scheduler.

    The harness owns no Stage, Release, Attempt, Provider, or Review authority.
    """
    timeout = runtime_timeout_policy.resolve("phase5a_canary_run", timeout)
    preflight = _preflight(Path(ep), canary_id)
    if dry_run:
        return {"status": "READY", **{k: v for k, v in preflight.items() if k != "episode"}}
    import model_policy
    import image_payload_transport
    import codex_subscription_image
    generation_preflight_required = requires_generation_capability_preflight(preflight)
    if not generation_preflight_required:
        global_claim = claim_global_canary(
            preflight["episode"], canary_id,
            allow_validation_epoch=allow_validation_epoch)
        payload_route = {
            "provider": "NOT_REQUIRED_EXISTING_GENERATION",
            "reason": "existing successful Generation Attempt is already committed",
        }
        payload_probe = {
            "status": "NOT_REQUIRED_EXISTING_GENERATION",
            "image_generation_called": False,
            "image_attempt_authority_called": False,
            "generation_key": preflight.get("generation_key"),
            "attempt_index": preflight.get("attempt_index"),
        }
        payload_status = "NOT_REQUIRED_EXISTING_GENERATION"
        controller_probe = {
            "status": "NOT_REQUIRED_EXISTING_GENERATION",
            "generation_key": preflight.get("generation_key"),
            "attempt_index": preflight.get("attempt_index"),
        }
    else:
        payload_binding = model_policy.resolve("image.payload", episode=preflight["episode"])
        payload_route = image_payload_transport.selected_route(1)
        if str(payload_route.get("provider") or "") == "codex_subscription":
            # The UNKNOWN-capability readiness path is scoped to the already
            # claimed Phase 5A replacement. Persist that single bounded claim
            # before its live text-only preflight; this writes no image Attempt and
            # does not authorize any dispatch by itself.
            global_claim = claim_global_canary(
                preflight["episode"], canary_id,
                allow_validation_epoch=allow_validation_epoch)
            payload_probe = codex_subscription_image.payload_capability_preflight(
                model=str(payload_binding.get("model") or ""),
                quality=str(payload_binding.get("quality") or ""),
                codex_raw=codex,
                phase5a_canary_id=canary_id,
                phase5a_canary_context={k: v for k, v in preflight.items() if k != "episode"},
            )
            payload_probe = {**payload_route, **payload_probe,
                             "provider": payload_probe.get("provider") or payload_route.get("provider")}
        else:
            payload_probe = image_payload_transport.payload_capability_preflight(
                model=str(payload_binding.get("model") or ""),
                quality=str(payload_binding.get("quality") or ""),
                codex_raw=codex,
            )
        payload_status = str(payload_probe.get("status") or "")
        if (payload_status == "READY_FOR_REAL_CAPABILITY_PROOF"
                and str(payload_probe.get("provider") or "") != "codex_subscription"):
            payload_status = "BLOCKED"
            payload_probe = {**payload_probe, "status": "BLOCKED",
                             "failure_class": "PHASE5A_UNKNOWN_CAPABILITY_REQUIRES_CODEX_SUBSCRIPTION"}
        if (payload_status != "PASS"
                and not (payload_status == "READY_FOR_REAL_CAPABILITY_PROOF"
                         and payload_probe.get("tool_capability_state") == "UNKNOWN"
                         and payload_probe.get("session_start") == "PASS"
                         and payload_probe.get("image_generation_called") is False
                         and payload_probe.get("image_attempt_authority_called") is False
                         and payload_probe.get("phase5a_scope", {}).get("canary_id") == canary_id)):
            _telemetry(preflight["episode"], "CANARY_PAYLOAD_PREFLIGHT_BLOCKED",
                       logical_asset_key=preflight["logical_asset_key"],
                       model_policy_sha256=preflight["policy_sha256"],
                       failure_class=payload_probe.get("failure_class"),
                       provider=payload_probe.get("provider"), status="BLOCKED",
                       step="EXACT_PAYLOAD_CAPABILITY_PREFLIGHT")
            return {"status": "CANARY_PAYLOAD_PREFLIGHT_BLOCKED",
                    "failure_class": payload_probe.get("failure_class"),
                    "payload_preflight": payload_probe,
                    "image_attempt_reserve_called": False,
                    "image_scheduler_called": False,
                    "controller_preflight_called": False,
                    "preflight": {k: v for k, v in preflight.items() if k != "episode"}}
        controller_probe = exact_controller_capability_preflight(
            preflight["episode"], codex=codex)
        if controller_probe.get("status") != "PASS":
            _telemetry(preflight["episode"], "CANARY_CONTROLLER_PREFLIGHT_BLOCKED",
                       logical_asset_key=preflight["logical_asset_key"],
                       model_policy_sha256=preflight["policy_sha256"],
                       failure_class=controller_probe.get("failure_class"),
                       status="BLOCKED", step="EXACT_CONTROLLER_CAPABILITY_PREFLIGHT")
            return {"status": "CANARY_CONTROLLER_PREFLIGHT_BLOCKED",
                    "controller_preflight": controller_probe,
                    "payload_preflight": payload_probe,
                    "image_attempt_reserve_called": False,
                    "image_scheduler_called": False,
                    "preflight": {k: v for k, v in preflight.items() if k != "episode"}}
        if str(payload_route.get("provider") or "") != "codex_subscription":
            global_claim = claim_global_canary(
                preflight["episode"], canary_id,
                allow_validation_epoch=allow_validation_epoch)
    import runtime_trace
    run_id = f"phase5a-{canary_id}"
    trace_id = runtime_trace.start_run(
        preflight["episode"], run_id, {"request_id": preflight["runtime_request_id"]},
        runtime="COLLABORATIVE", route_decision={"entry_step": "PRODUCTION_SUBPATH_CANARY"})
    _telemetry(preflight["episode"], "CANARY_RUN_STARTED",
               logical_asset_key=preflight["logical_asset_key"],
               model_policy_sha256=preflight["policy_sha256"],
               run_id=run_id, trace_id=trace_id, step="PHASE5A_CANARY",
               status="RUNNING")
    stage_path = preflight["episode"] / "meta/episode-state.json"
    before_stage = stage_path.read_bytes() if stage_path.is_file() else None
    release_path = preflight["episode"] / "meta/release-manifest.json"
    before_release = release_path.read_bytes() if release_path.is_file() else None
    import image_scheduler
    try:
        if payload_status == "READY_FOR_REAL_CAPABILITY_PROOF":
            with codex_subscription_image.phase5a_payload_dispatch_context(
                preflight["episode"], canary_id,
                {k: v for k, v in preflight.items() if k != "episode"},
                payload_probe,
            ):
                rc = image_scheduler.run_scheduler_async(
                    preflight["episode"], max_workers=1, timeout=int(timeout), codex=codex)
        else:
            rc = image_scheduler.run_scheduler_async(preflight["episode"], max_workers=1,
                                                     timeout=int(timeout), codex=codex)
    except Exception as exc:
        original_exc = exc
        after_stage = stage_path.read_bytes() if stage_path.is_file() else None
        after_release = release_path.read_bytes() if release_path.is_file() else None
        if before_stage != after_stage:
            observed_exc = CanaryContractError("CANARY_STAGE_STATE_FILE_CHANGED_DURING_FAILED_RUN")
        elif before_release != after_release:
            observed_exc = CanaryContractError("CANARY_RELEASE_MANIFEST_CHANGED_DURING_FAILED_RUN")
        else:
            observed_exc = original_exc
        _telemetry(preflight["episode"], "CANARY_RUN_FINISHED",
                   logical_asset_key=preflight["logical_asset_key"], status="FAILED",
                   failure_class=type(observed_exc).__name__, run_id=run_id, trace_id=trace_id,
                   step="PHASE5A_CANARY", reason="scheduler_exception")
        runtime_trace.finish_run(preflight["episode"], trace_id, run_id, "FAILED",
                                 note=type(observed_exc).__name__)
        if observed_exc is not original_exc:
            raise observed_exc from original_exc
        raise
    after_state = __import__("generation_attempt_authority").load_asset_state(
        preflight["episode"], preflight["logical_asset_key"])
    validate_generation_count(after_state["attempts_consumed"])
    after_stage = stage_path.read_bytes() if stage_path.is_file() else None
    after_release = release_path.read_bytes() if release_path.is_file() else None
    stage_state_file_changed = before_stage != after_stage
    release_manifest_changed = before_release != after_release
    if after_stage is not None or stage_state_file_changed:
        raise CanaryContractError("CANARY_STAGE_AUTHORITY_MUTATED")
    if release_manifest_changed:
        raise CanaryContractError("CANARY_RELEASE_AUTHORITY_MUTATED")
    queue = image_scheduler.load_queue(preflight["episode"])
    item = next((row for row in queue.get("items") or []
                 if row.get("id") == preflight["queue_item_id"]), {})
    review = next((row for row in queue.get("review_work_items") or []
                   if row.get("generation_key") == item.get("generation_key")
                   and row.get("logical_asset_key") == preflight["logical_asset_key"]), {})
    result = {
        "status": "BLOCKED",
        "scheduler_rc": int(rc),
        "queue_item_status": item.get("status"),
        "generation_key": item.get("generation_key"),
        "attempt_index": item.get("attempt_index"),
        "review_status": review.get("status"),
        "review_receipt": review.get("receipt"),
        "attempt_state": after_state,
        "stage_state_file_present_after_run": after_stage is not None,
        "stage_state_file_changed_during_run": stage_state_file_changed,
        "release_manifest_changed_during_run": release_manifest_changed,
        "global_canary_claim": global_claim,
        "preflight": {k: v for k, v in preflight.items() if k != "episode"},
    }
    # Fast Scout is early triage only. Enqueue final semantic work into the
    # existing durable Review Lane and let the canonical Scheduler consume it.
    # The harness never invokes the Critic directly.
    if rc == 0 and item.get("status") == "generated" and review.get("status") == "finalized":
        import incremental_frame_review
        import production_ledger
        import review_queue
        import scheduler_core

        artifact_rel = str(item.get("output_path") or "").strip()
        artifact = (Path(artifact_rel) if Path(artifact_rel).is_absolute()
                    else (ROOT / artifact_rel).resolve())
        if not artifact_rel or not artifact.is_file():
            raise CanaryContractError("CANARY_COMMITTED_ARTIFACT_MISSING")
        with scheduler_core.queue_transaction(preflight["episode"]):
            q = scheduler_core.load_queue(preflight["episode"])
            current_item = next((row for row in q.get("items") or []
                                 if row.get("id") == preflight["queue_item_id"]), {})
            enqueued_final = review_queue.enqueue_final_semantic(
                q, episode=preflight["episode"], source_item=current_item,
                artifact=artifact, artifact_path=artifact_rel,
                review_scope=review_queue.PHASE5A_SINGLE_FRAME)
            if enqueued_final.get("status") not in {
                    "ENQUEUED", "ALREADY_ENQUEUED", "REENQUEUED_STALE",
                    "REENQUEUED_RECOVERED_EVIDENCE"}:
                raise CanaryContractError("CANARY_FINAL_REVIEW_ENQUEUE_FAILED: "
                                          + str(enqueued_final.get("reason") or enqueued_final.get("status")))
            scheduler_core.save_queue(preflight["episode"], q)

        receipts_before_final = {row.get("call_id") for row in _model_execution_receipts(preflight["episode"])}
        final_scheduler_rc = image_scheduler.run_scheduler_async(
            preflight["episode"], max_workers=1, timeout=int(timeout), codex=codex)
        queue = image_scheduler.load_queue(preflight["episode"])
        review = next((row for row in queue.get("review_work_items") or []
                       if row.get("review_kind") == review_queue.FINAL_SEMANTIC
                       and row.get("generation_key") == item.get("generation_key")
                       and row.get("logical_asset_key") == preflight["logical_asset_key"]), {})
        semantic_receipt = review.get("receipt") or {}
        final_receipt = semantic_receipt.get("critic_receipt") or {}
        semantic_errors = ([] if review.get("status") == "finalized"
                           and semantic_receipt.get("review_outcome") in {"PASS", "REPAIR_NEEDED", "NEEDS_USER"}
                           else [str(semantic_receipt.get("notes") or "FINAL_SEMANTIC_REVIEW_NOT_TERMINAL")])
        incremental_rc = (incremental_frame_review.run_review(
            preflight["episode"], attempt=int(item.get("attempt_index") or 1),
            codex_raw=codex, timeout=int(timeout))
            if not semantic_errors and semantic_receipt.get("review_outcome") == "PASS" else None)
        incremental_plan = (incremental_frame_review.build_plan(preflight["episode"])
                            if incremental_rc == 0 else {})
        final_ledger = production_ledger.load_authority(preflight["episode"], default={}) or {}
        final_frame = ((final_ledger.get("frames") or {}).get("01") or {})
        bound_review = __import__("model_policy").resolve("vision.final", episode=preflight["episode"])
        # On first execution this is the newly written call; after a safe
        # resume it is the same persisted call embedded in the adopted Queue
        # Receipt. In either case validate the exact model execution evidence.
        reconciled_failed_receipts = _reconcile_failed_final_semantic_receipts(
            preflight["episode"],
            generation_key=str(item.get("generation_key") or ""),
            artifact_sha256=str(semantic_receipt.get("artifact_sha256") or ""),
        )
        all_final_receipts = [row for row in _model_execution_receipts(preflight["episode"])
                              if row.get("model_role") == "vision.final"
                              and row.get("generation_key") == item.get("generation_key")
                              and row.get("artifact_sha256") == semantic_receipt.get("artifact_sha256")]
        embedded_call_id = str(final_receipt.get("call_id") or "")
        receipt_partition = _partition_final_semantic_receipts(
            all_final_receipts, embedded_call_id=embedded_call_id)
        successful_final_receipts = receipt_partition["successful"]
        failed_final_receipts = receipt_partition["failed"]
        unresolved_final_receipts = receipt_partition["unresolved"]
        final_receipts = receipt_partition["embedded"]
        receipt_contract_pass = (
            int(final_scheduler_rc) == 0
            and review.get("status") == "finalized"
            and semantic_receipt.get("review_outcome") == "PASS"
            and semantic_receipt.get("generation_key") == item.get("generation_key")
            and semantic_receipt.get("artifact_sha256") == final_receipt.get("artifact_sha256")
            and final_receipt.get("status") == "SUCCESS"
            and final_receipt.get("model_role") == "vision.final"
            and final_receipt.get("profile") == bound_review.get("profile")
            and final_receipt.get("effective_model") == bound_review.get("model")
            and final_receipt.get("reasoning_effort") == bound_review.get("reasoning_effort")
            and final_receipt.get("model_policy_sha256") == preflight["policy_sha256"]
            and final_receipt.get("logical_asset_key") == preflight["logical_asset_key"]
            and final_receipt.get("generation_key") == item.get("generation_key")
            and int(final_receipt.get("attempt_index") or 0) == int(item.get("attempt_index") or 0)
            and final_receipt.get("artifact_sha256") == semantic_receipt.get("artifact_sha256")
            and final_receipt.get("effective_model_source") == "EXPLICIT_RUNTIME_BINDING"
            and len(final_receipts) == 1
            and len(successful_final_receipts) == 1
            and len(unresolved_final_receipts) == 0
        )
        receipt_is_adopted = bool(semantic_receipt.get("reused_official_evidence"))
        review_receipt_pass = (receipt_contract_pass and (
            receipt_is_adopted
            or final_receipts[0].get("call_id") not in receipts_before_final
        ))
        semantic_pass = (not semantic_errors
                         and final_frame.get("status") in production_ledger.ACCEPTED_LEDGER_STATES
                         and review_receipt_pass
                         and incremental_rc == 0
                         and incremental_plan.get("action") == "NOOP"
                         and "01" in (incremental_plan.get("reused_frames") or []))
        result.update({
            "final_semantic_enqueue_status": enqueued_final.get("status"),
            "final_semantic_scheduler_rc": int(final_scheduler_rc),
            "final_semantic_queue_status": review.get("status"),
            "final_semantic_queue_receipt": semantic_receipt,
            "final_semantic_errors": semantic_errors,
            "final_semantic_status": final_frame.get("status"),
            "final_semantic_model_receipts": final_receipts,
            "final_semantic_failed_model_receipts": failed_final_receipts,
            "final_semantic_unresolved_model_receipts": unresolved_final_receipts,
            "final_semantic_reconciled_failed_receipts": reconciled_failed_receipts,
            "final_semantic_receipt_pass": review_receipt_pass,
            "incremental_review_rc": incremental_rc,
            "incremental_plan": incremental_plan,
            "real_evidence_reused": semantic_pass,
            "additional_critic_calls_after_reuse": 0 if semantic_pass else None,
        })
        if semantic_pass:
            # Safe scheduler resume after final evidence is persisted must leave
            # the Authority row and finalized Review item unchanged.
            before_consumed = int(after_state.get("attempts_consumed") or 0)
            before_generation_key = str(item.get("generation_key") or "")
            import runtime_observability
            trace_path = preflight["episode"] / runtime_observability.TRACE_EVENTS_REL
            before_review_starts = _trace_event_count(
                preflight["episode"], "REVIEW_STARTED",
                logical_asset_key=preflight["logical_asset_key"], generation_key=before_generation_key)
            before_worker_dispatches = _trace_event_count(
                preflight["episode"], "WORKER_DISPATCH_COMMITTED",
                logical_asset_key=preflight["logical_asset_key"], generation_key=before_generation_key)
            before_model_receipts = _model_execution_receipt_snapshot(preflight["episode"])
            before_review_model_receipt_count = sum(
                1 for row in _model_execution_receipts(preflight["episode"])
                if row.get("model_role") in {"vision.final", "final_semantic"}
            )
            before_review_key = (str(review.get("generation_key") or ""),
                                 str((review.get("receipt") or {}).get("artifact_sha256") or ""),
                                 str(review.get("review_kind") or ""))
            resume_rc = image_scheduler.run_scheduler_async(
                preflight["episode"], max_workers=1, timeout=int(timeout), codex=codex)
            resumed_state = __import__("generation_attempt_authority").load_asset_state(
                preflight["episode"], preflight["logical_asset_key"])
            resumed_queue = image_scheduler.load_queue(preflight["episode"])
            resumed_item = next((row for row in resumed_queue.get("items") or []
                                 if row.get("id") == preflight["queue_item_id"]), {})
            resumed_review = next((row for row in resumed_queue.get("review_work_items") or []
                                   if row.get("generation_key") == before_generation_key
                                   and row.get("logical_asset_key") == preflight["logical_asset_key"]
                                   and row.get("review_kind") == review_queue.FINAL_SEMANTIC), {})
            after_review_starts = _trace_event_count(
                preflight["episode"], "REVIEW_STARTED",
                logical_asset_key=preflight["logical_asset_key"], generation_key=before_generation_key)
            after_worker_dispatches = _trace_event_count(
                preflight["episode"], "WORKER_DISPATCH_COMMITTED",
                logical_asset_key=preflight["logical_asset_key"], generation_key=before_generation_key)
            after_model_receipts = _model_execution_receipt_snapshot(preflight["episode"])
            after_review_model_receipt_count = sum(
                1 for row in _model_execution_receipts(preflight["episode"])
                if row.get("model_role") in {"vision.final", "final_semantic"}
            )
            provider_redispatch_count = after_worker_dispatches - before_worker_dispatches
            review_redispatch_count = after_review_model_receipt_count - before_review_model_receipt_count
            resume_pass = (
                resume_rc == 0
                and int(resumed_state.get("attempts_consumed") or 0) == before_consumed
                and resumed_item.get("generation_key") == before_generation_key
                and resumed_review.get("status") == "finalized"
                and (str(resumed_review.get("generation_key") or ""),
                     str((resumed_review.get("receipt") or {}).get("artifact_sha256") or ""),
                     str(resumed_review.get("review_kind") or "")) == before_review_key
                and after_review_starts == before_review_starts
                and before_worker_dispatches >= 1
                and provider_redispatch_count == 0
                and review_redispatch_count == 0
                and after_model_receipts == before_model_receipts
            )
            result["resume"] = {
                "scheduler_rc": int(resume_rc),
                "provider_redispatch_count_observed": provider_redispatch_count,
                "review_redispatch_count_observed": review_redispatch_count,
                "worker_dispatch_commits_before": before_worker_dispatches,
                "worker_dispatch_commits_after": after_worker_dispatches,
                "model_execution_receipt_count_before": len(before_model_receipts),
                "model_execution_receipt_count_after": len(after_model_receipts),
                "model_execution_receipts_unchanged": after_model_receipts == before_model_receipts,
                "review_model_receipt_count_before": before_review_model_receipt_count,
                "review_model_receipt_count_after": after_review_model_receipt_count,
                "generation_key_unchanged": resumed_item.get("generation_key") == before_generation_key,
                "attempts_consumed_unchanged": int(resumed_state.get("attempts_consumed") or 0) == before_consumed,
            }
            result["review_queue_start_events_before_resume"] = before_review_starts
            result["review_queue_start_events_after_resume"] = after_review_starts
            if resume_pass:
                result["status"] = "PASS"
    _telemetry(preflight["episode"], "CANARY_RUN_FINISHED",
               status=result["status"], logical_asset_key=preflight["logical_asset_key"],
               generation_key=item.get("generation_key"), attempt_index=item.get("attempt_index"),
               evidence_ref=str((review.get("receipt") or {}).get("critic_log") or ""),
               reason=str(result.get("final_semantic_status") or review.get("status") or ""),
               step="PHASE5A_CANARY", run_id=run_id, trace_id=trace_id)
    runtime_trace.finish_run(preflight["episode"], trace_id, run_id, result["status"],
                             note="Phase 5A non-promotable production subpath canary")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Run or safely resume one prepared Phase 5A canary asset")
    run.add_argument("episode_dir", type=Path)
    run.add_argument("--canary-id", required=True)
    run.add_argument("--timeout", type=int, default=None)
    run.add_argument("--codex")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--allow-validation-epoch", action="store_true")
    args = parser.parse_args()
    try:
        result = run_production_subpath(args.episode_dir, canary_id=args.canary_id,
                                        timeout=args.timeout, codex=args.codex,
                                        dry_run=args.dry_run,
                                        allow_validation_epoch=args.allow_validation_epoch)
    except Exception as exc:
        result = {"status": "BLOCKED", "error": f"{type(exc).__name__}: {exc}"}
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result.get("status") in {"READY", "PASS"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
