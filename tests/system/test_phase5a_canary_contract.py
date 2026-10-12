from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SYSTEM = ROOT / "episodes" / "_system"
if str(SYSTEM) not in sys.path:
    sys.path.insert(0, str(SYSTEM))

import phase5a_collaborative_canary as canary


def test_contract_is_fixed_and_non_promotable():
    value = canary.contract()
    assert value == {
        "canary_type": "PHASE5A_COLLABORATIVE_REGRESSION",
        "production_mode": "COLLABORATIVE",
        "scope": "PRODUCTION_SUBPATH",
        "promotable": False,
        "release_eligible": False,
        "stage_authority": False,
        "provider_generation_target": 1,
        "provider_generation_hard_max": 2,
        "requires_visual_lock_stage": False,
    }
    value["provider_generation_hard_max"] = 5
    assert canary.contract()["provider_generation_hard_max"] == 2


def test_dedicated_entry_accepts_normal_request_but_runtime_cannot_opt_in():
    request = {"schema_version": 1, "topic": {"title": "Canary"}}
    assert canary.authorize_entry(
        entrypoint=canary.CANARY_ENTRYPOINT,
        runtime_request=request,
    )["scope"] == "PRODUCTION_SUBPATH"

    for entrypoint in ("runtime_dag", "episode_runner", "story_os"):
        try:
            canary.authorize_entry(entrypoint=entrypoint, runtime_request=request)
        except canary.CanaryContractError as exc:
            assert str(exc) == "CANARY_ENTRYPOINT_REQUIRED"
        else:
            raise AssertionError(f"ordinary entrypoint unexpectedly authorized: {entrypoint}")

    for request_with_bypass in (
        {"skip_visual_lock": True},
        {"runtime": {"canary_scope": "PRODUCTION_SUBPATH"}},
        {"execution": {"requires_visual_lock_stage": False}},
    ):
        try:
            canary.authorize_entry(
                entrypoint=canary.CANARY_ENTRYPOINT,
                runtime_request=request_with_bypass,
            )
        except canary.CanaryContractError as exc:
            assert str(exc) == "RUNTIME_REQUEST_CANNOT_ENABLE_CANARY_BYPASS"
        else:
            raise AssertionError("Runtime Request must not grant canary bypass")


def test_relaxed_or_user_supplied_contract_is_rejected():
    for candidate in ({}, {**canary.contract(), "release_eligible": True}):
        try:
            canary.authorize_entry(
                entrypoint=canary.CANARY_ENTRYPOINT,
                runtime_request={},
                candidate_contract=candidate,
            )
        except canary.CanaryContractError as exc:
            assert str(exc) == "CANARY_CONTRACT_MISMATCH"
        else:
            raise AssertionError("relaxed contract must fail closed")


def test_stage_visual_lock_and_release_mutations_are_denied():
    for action in (
        "STAGE_PROMOTION",
        "WRITE_CANONICAL_STAGE",
        "WRITE_VISUAL_LOCK_PASS",
        "RELEASE_AUTHORITY_COMMIT",
        "PUBLISH_READY_TRANSITION",
        "PUBLISH",
    ):
        try:
            canary.authorize_action(action)
        except canary.CanaryContractError as exc:
            assert str(exc) == "CANARY_STAGE_OR_RELEASE_MUTATION_FORBIDDEN"
        else:
            raise AssertionError(f"mutation must be denied: {action}")

    assert canary.authorize_action("RUN_PRODUCTION_SUBPATH") == "RUN_PRODUCTION_SUBPATH"
    try:
        canary.authorize_action("UNKNOWN_ACTION")
    except canary.CanaryContractError as exc:
        assert str(exc) == "CANARY_ACTION_NOT_ALLOWLISTED"
    else:
        raise AssertionError("unknown actions must fail closed")


def test_workspace_marker_and_hard_generation_ceiling():
    marker = canary.workspace_marker("phase5a-20261001-a")
    assert marker["workspace_class"] == "TEST_ONLY"
    assert marker["promotion_class"] == "NON_PROMOTABLE"
    assert marker["canary_type"] == canary.CANARY_TYPE

    assert canary.validate_generation_count(0) == 0
    assert canary.validate_generation_count(1) == 1
    assert canary.validate_generation_count(2) == 2
    for invalid in (-1, 3, True, 1.0):
        try:
            canary.validate_generation_count(invalid)
        except canary.CanaryContractError:
            pass
        else:
            raise AssertionError(f"invalid generation count accepted: {invalid!r}")


def test_workspace_marker_must_be_exact_and_canary_id_is_path_safe(tmp_path, monkeypatch):
    import json
    import pytest

    monkeypatch.setattr(canary, "ROOT", tmp_path)
    canary_id = "phase5a-contract-test"
    ep = canary.initialize_workspace(canary_id)
    assert ep.is_relative_to((tmp_path / canary.WORKSPACE_REL).resolve())
    assert canary.validate_workspace(ep, canary_id)[1] == canary.workspace_marker(canary_id)

    marker_path = ep / canary.MARKER_REL
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    marker["stage_authority"] = True
    marker_path.write_text(json.dumps(marker), encoding="utf-8")
    with pytest.raises(canary.CanaryContractError, match="CANARY_WORKSPACE_MARKER_INVALID"):
        canary.validate_workspace(ep, canary_id)

    with pytest.raises(canary.CanaryContractError, match="INVALID_CANARY_ID"):
        canary.workspace_marker("..\\outside")


def test_bind_and_freeze_returns_episode_bound_policy_identity(tmp_path, monkeypatch):
    import model_policy
    import runtime_request

    monkeypatch.setattr(canary, "ROOT", tmp_path)
    request = {"schema_version": 1, "request_id": "request-1"}
    frozen_payload = {
        "policy_version": "test-policy-v1",
        "policy_sha256": "f" * 64,
    }
    monkeypatch.setattr(runtime_request, "bind_data", lambda *_a, **_k: None)
    monkeypatch.setattr(runtime_request, "effective_for_episode", lambda *_a: request)
    monkeypatch.setattr(canary, "model_policy_persistence_load", lambda _ep: None)
    monkeypatch.setattr(model_policy, "freeze_for_episode", lambda _ep: {
        "policy": frozen_payload, "policy_sha256": frozen_payload["policy_sha256"], "created": True
    })
    monkeypatch.setattr(model_policy, "validate_bound_policy", lambda _ep: [])
    events = []
    monkeypatch.setattr(canary, "_telemetry", lambda _ep, event, **attrs: events.append((event, attrs)))

    episode = tmp_path / canary.WORKSPACE_REL / "episode"
    result = canary.bind_and_freeze(episode, request)
    assert result == {
        "runtime_request_id": "request-1",
        "policy_version": "test-policy-v1",
        "policy_sha256": "f" * 64,
    }
    assert [event for event, _ in events] == [
        "STEP_FINISHED", "STEP_FINISHED"
    ]
    assert [attrs["step"] for _, attrs in events] == [
        "RUNTIME_REQUEST_BIND", "MODEL_POLICY_FREEZE"
    ]


def test_active_canary_queue_items_ignore_superseded_history():
    queue = {
        "items": [
            {"id": "old", "status": "superseded"},
            {"id": "current", "status": "queued"},
        ]
    }
    assert canary._active_canary_queue_items(queue) == [
        {"id": "current", "status": "queued"}
    ]


def test_failed_provisional_final_receipt_is_terminalized_and_kept_visible(tmp_path):
    import json

    directory = tmp_path / "meta/provider-receipts/model-executions"
    directory.mkdir(parents=True)
    receipt = {
        "receipt_schema_version": 1,
        "episode_id": "_external/test",
        "run_id": "run-1",
        "trace_id": "trace-1",
        "step": "vision.final",
        "call_id": "failed-call",
        "model_role": "vision.final",
        "profile": "vision_final",
        "requested_model": "gpt-6-luna",
        "effective_model": "gpt-6-luna",
        "reasoning_effort": "high",
        "model_policy_version": "v1",
        "model_policy_sha256": "p" * 64,
        "provider": "codex",
        "runner": "codex_user_runner",
        "started_at": "2026-10-02T22:00:00+08:00",
        "finished_at": "2026-10-02T22:01:00+08:00",
        "duration_ms": 60000,
        "status": "PENDING_VALIDATION",
        "returncode": 1,
        "runner_request_id": "request-failed",
        "thread_id": "",
        "model_binding_source": "EPISODE_BOUND_POLICY",
        "effective_model_source": "EXPLICIT_RUNTIME_BINDING",
        "durable_result_status": "TURN_NOT_COMPLETED",
        "logical_asset_key": "asset-01",
        "generation_key": "generation-01-a1",
        "attempt_index": 1,
        "artifact_sha256": "a" * 64,
    }
    path = directory / "failed-call.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")

    changed = canary._reconcile_failed_final_semantic_receipts(
        tmp_path, generation_key="generation-01-a1", artifact_sha256="a" * 64)

    assert len(changed) == 1
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["status"] == "FAILED"
    assert stored["call_id"] == "failed-call"
    assert stored["runner_request_id"] == "request-failed"
    assert stored["status_reconciled_from"] == "PENDING_VALIDATION"
    assert stored["status_reconciliation_reason"] == "NONZERO_RETURN_CODE_BEFORE_FINAL_VALIDATION"


def test_final_receipt_partition_requires_one_validated_success_and_no_unresolved():
    success = {
        "call_id": "success-call", "status": "SUCCESS", "returncode": 0,
        "durable_result_status": "VALIDATED",
    }
    failed = {
        "call_id": "failed-call", "status": "FAILED", "returncode": 1,
        "durable_result_status": "TURN_NOT_COMPLETED",
    }
    parts = canary._partition_final_semantic_receipts(
        [success, failed], embedded_call_id="success-call")
    assert parts["embedded"] == [success]
    assert parts["successful"] == [success]
    assert parts["failed"] == [failed]
    assert parts["unresolved"] == []

    pending = {
        "call_id": "pending-call", "status": "PENDING_VALIDATION", "returncode": 0,
        "durable_result_status": "VALIDATED",
    }
    parts = canary._partition_final_semantic_receipts(
        [success, pending], embedded_call_id="success-call")
    assert parts["unresolved"] == [pending]
