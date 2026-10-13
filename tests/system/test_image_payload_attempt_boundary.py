from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SYSTEM = ROOT / "episodes" / "_system"
if str(SYSTEM) not in sys.path:
    sys.path.insert(0, str(SYSTEM))

import generation_attempt_authority
import image_generation_gateway
import image_payload_controller
import model_policy
import raw_candidate_budget
import batch_image_worker
import batch_scheduler
import batch_runtime_config


POLICY_SHA = "a" * 64


def _bound_policy(role: str) -> dict:
    common = {
        "policy_version": "phase5a-test-frozen-v1",
        "model_policy_sha256": POLICY_SHA,
    }
    if role == "image.controller":
        return {
            **common,
            "role": role,
            "profile": "image_controller",
            "model": "gpt-6-luna",
            "reasoning_effort": "high",
        }
    return {
        **common,
        "role": role,
        "profile": "image_payload",
        "model": "gpt-image-2.5-flare",
        "quality": "high",
    }


@pytest.mark.parametrize(
    ("role", "field", "bad_value"),
    [
        ("image.controller", "model", "unsupported-model"),
        ("image.payload", "model", "unsupported-payload"),
        ("image.payload", "quality", "medium"),
    ],
)
def test_frozen_controller_or_payload_binding_blocked_before_attempt_claim(
    monkeypatch, tmp_path, role, field, bad_value
):
    """Binding/preflight rejection must happen before any budget claim."""
    episode = tmp_path / "canary"
    episode.mkdir()
    resolved = {name: _bound_policy(name) for name in ("image.controller", "image.payload")}
    resolved[role][field] = bad_value
    claims = []

    monkeypatch.setattr(model_policy, "validate_bound_policy", lambda _ep: [])
    monkeypatch.setattr(model_policy, "resolve", lambda name, **_kwargs: dict(resolved[name]))
    monkeypatch.setattr(
        raw_candidate_budget,
        "claim",
        lambda *args, **kwargs: claims.append((args, kwargs)),
    )

    with pytest.raises(image_payload_controller.ImagePayloadControllerError):
        image_payload_controller._binding_for_episode(episode)

    assert claims == []


def test_gateway_dispatch_commit_is_the_payload_handoff_boundary(monkeypatch, tmp_path):
    events = []
    lease = {"generation_key": "ga-test-a1", "fencing_token": 7}
    committed = {**lease, "status": "DISPATCH_COMMITTED"}

    def commit(_ep, actual_lease, fence, *, provider):
        assert actual_lease is lease
        assert fence == 7
        assert provider == "test-provider"
        events.append("dispatch_commit")
        return committed

    monkeypatch.setattr(generation_attempt_authority, "commit_dispatch", commit)
    # Simulated commit must also simulate the *read-only* post-commit Fence.
    monkeypatch.setattr(generation_attempt_authority, "validate_committed_dispatch",
                        lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        generation_attempt_authority,
        "mark_observed",
        lambda *_args, **_kwargs: events.append("observed"),
    )
    payload_handoff = lambda: events.append("payload_handoff") or {"stub": True}

    result = image_generation_gateway.provider_generate(
        tmp_path, lease, 7, "test-provider", payload_handoff
    )

    assert result == {"stub": True}
    assert events == ["dispatch_commit", "payload_handoff", "observed"]
    assert lease["_phase"] == "DISPATCH_COMMITTED"


def test_gateway_commit_denial_prevents_payload_handoff(monkeypatch, tmp_path):
    events = []

    def deny(*_args, **_kwargs):
        events.append("dispatch_denied")
        raise generation_attempt_authority.AttemptDenied("STALE_GENERATION_ATTEMPT_FENCE")

    monkeypatch.setattr(generation_attempt_authority, "commit_dispatch", deny)
    lease = {"generation_key": "ga-test-a1", "fencing_token": 3}

    with pytest.raises(generation_attempt_authority.AttemptDenied):
        image_generation_gateway.provider_generate(
            tmp_path,
            lease,
            3,
            "test-provider",
            lambda: events.append("payload_handoff"),
        )

    assert events == ["dispatch_denied"]
    assert "_phase" not in lease


def test_legacy_batch_worker_denies_controller_payload_split_before_attempt_claim(monkeypatch, tmp_path):
    claims = []
    monkeypatch.setattr(image_payload_controller, "separate_execution_required", lambda _ep: True)
    monkeypatch.setattr(raw_candidate_budget, "claim", lambda *a, **k: claims.append((a, k)))
    with pytest.raises(batch_image_worker.BatchBackendError, match="CANONICAL_CONTROLLER_PAYLOAD_SPLIT_REQUIRED"):
        batch_image_worker.execute_batch(
            tmp_path, {"planned_count": 1}, [{"id": "q1", "frame": 1}],
            timeout=1, codex=None,
        )
    assert claims == []


def test_batch_scheduler_routes_split_policy_to_single_frame_lane(monkeypatch, tmp_path):
    monkeypatch.setattr(batch_runtime_config, "enabled", lambda: True)
    monkeypatch.setattr(image_payload_controller, "separate_execution_required", lambda _ep: True)
    monkeypatch.setattr(batch_scheduler, "load_queue", lambda _ep: {
        "items": [{"status": "queued", "scope": "batch", "kind": "original"}]
    })
    assert batch_scheduler.should_use(tmp_path) is False
