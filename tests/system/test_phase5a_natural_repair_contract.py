from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from contextlib import nullcontext
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SYSTEM = ROOT / "episodes" / "_system"
if str(SYSTEM) not in sys.path:
    sys.path.insert(0, str(SYSTEM))

import frame_scout_persistence
import generation_attempt_authority
import image_generation_gateway
import image_scheduler
import logical_asset_identity
import model_policy
import production_ledger
import repair_aggregator
import review_queue
import scheduler_core


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _policy(role: str) -> dict:
    return {
        "role": role,
        "profile": "vision_final" if role == "vision.final" else "image_controller",
        "model": "gpt-6-luna",
        "reasoning_effort": "high",
        "model_policy_sha256": "a" * 64,
        "policy_version": "phase5a-stub-policy",
    }


def test_natural_final_review_repair_flows_through_one_wave_scheduler_and_review(
    tmp_path, monkeypatch,
):
    """Stub every external boundary while retaining queue/aggregator/scheduler control flow."""
    ep = tmp_path / "canary-episode"
    (ep / "meta").mkdir(parents=True)
    original_prompt = ep / "frame-01.prompt.md"
    original_prompt.write_text("preserve passed dimensions; test input", encoding="utf-8")
    first_artifact = ep / "frame-01-attempt-1.png"
    first_artifact.write_bytes(b"first-pass-pixels")
    repair_artifact = ep / "frame-01-attempt-2.png"

    queue = {"schema_version": 1, "items": [], "waves": [], review_queue.QUEUE_KEY: []}
    ledger = {"frames": {"01": {"status": "REPAIR_AUTHORIZED", "current_candidate": {
        "path": str(first_artifact), "sha256": _sha(first_artifact),
    }}}}
    monkeypatch.setattr(scheduler_core, "queue_transaction", lambda *_a, **_k: nullcontext())
    monkeypatch.setattr(scheduler_core, "load_queue", lambda *_a, **_k: queue)
    monkeypatch.setattr(scheduler_core, "save_queue", lambda *_a, **_k: None)
    monkeypatch.setattr(image_scheduler, "load_queue", lambda *_a, **_k: queue)
    monkeypatch.setattr(image_scheduler, "save_queue", lambda *_a, **_k: None)
    monkeypatch.setattr(production_ledger, "load_authority", lambda *_a, **_k: ledger)
    monkeypatch.setattr(review_queue, "telemetry", lambda *_a, **_k: None)
    monkeypatch.setattr(image_scheduler, "_telemetry_image", lambda *_a, **_k: None)
    monkeypatch.setattr(frame_scout_persistence, "save", lambda *_a, **_k: None)
    monkeypatch.setattr(model_policy, "resolve", lambda role, **_k: _policy(role))
    monkeypatch.setattr(review_queue, "_current_final_candidate_matches", lambda *_a, **_k: True)

    original = {
        "id": "first-pass-01", "frame": 1, "kind": "original", "scope": "production",
        "status": "generated", "generation_key": "canary/frame-01/attempt-1",
        "attempt_index": 1, "output_path": str(first_artifact),
        "prompt_file": str(original_prompt),
    }
    queue["items"].append(original)

    # First Review is a normal claimed FINAL_SEMANTIC queue item. The stub returns
    # a model-backed content finding, which the queue finalizes as REPAIR_NEEDED.
    first_review = review_queue.enqueue(
        queue, episode=ep, source_item=original, artifact_path=str(first_artifact),
        artifact_sha256=_sha(first_artifact), policy=_policy("vision.final"),
        review_kind=review_queue.FINAL_SEMANTIC,
    )
    assert first_review["status"] == "ENQUEUED"
    first_receipt = {
        "schema_version": 1, "review_kind": review_queue.FINAL_SEMANTIC,
        "status": "COMPLETED_WITH_FINDINGS", "review_outcome": "REPAIR_NEEDED",
        "episode_id": first_review["item"]["episode_id"],
        "logical_asset_key": first_review["item"]["logical_asset_key"],
        "generation_key": original["generation_key"], "attempt_index": 1,
        "artifact_sha256": _sha(first_artifact), "model_role": "vision.final",
        "model": "gpt-6-luna", "profile": "vision_final", "reasoning_effort": "high",
        "model_policy_sha256": "a" * 64,
        "issue_codes": ["KEY_PROP_DRIFT"], "notes": "key prop differs",
        "critic_receipt": {"status": "SUCCESS", "call_id": "stub-first-review"},
    }
    monkeypatch.setattr(review_queue, "_final_semantic_receipt", lambda *_a, **_k: dict(first_receipt))
    stop = asyncio.Event()
    stop.set()
    asyncio.run(review_queue.run_lane(
        ep, changed=asyncio.Event(), progress=asyncio.Event(), stop=stop,
        codex="stub", timeout=1, max_inflight=1,
    ))
    persisted_first = queue[review_queue.QUEUE_KEY][0]
    assert persisted_first["status"] == "finalized"
    assert persisted_first["receipt"]["review_outcome"] == "REPAIR_NEEDED"
    assert persisted_first["receipt"]["generation_key"] == original["generation_key"]
    assert persisted_first["receipt"]["artifact_sha256"] == _sha(first_artifact)

    # The canonical first-pass evidence consumed by the aggregator is bound to
    # that completed queue receipt and the still-current Attempt 1 candidate.
    first_pass_evidence = {
        "schema_version": 3, "attempt": 1, "review_scope": "CANDIDATE_FULL_FRAME_SET",
        "recorded_at": "2026-10-01T00:00:00Z", "failed_frames": ["01"],
        "reviewed_assets": [{"frame": "01", "sha256": _sha(first_artifact),
                              "generation_key": original["generation_key"]}],
        "critic_result": {"frames": [{"frame": "01", "issue_codes": ["KEY_PROP_DRIFT"],
                                         "notes": persisted_first["receipt"]["notes"]}]},
        "review_queue_receipt": persisted_first["receipt"],
    }
    evidence_path = ep / "meta" / "frame-semantic-candidate-attempt-1.json"
    evidence_path.write_text(json.dumps(first_pass_evidence), encoding="utf-8")
    monkeypatch.setattr(repair_aggregator, "_queue_source", lambda *_a, **_k: original)
    monkeypatch.setattr(generation_attempt_authority, "remaining", lambda *_a, **_k: 1)
    prompt_calls = []

    def prompt_runner(_ep, *, task_input):
        prompt_calls.append(task_input)
        prompt_path = ep / "meta" / "repair-prompt-01.txt"
        prompt_path.write_text("change only failed key prop", encoding="utf-8")
        return {"status": "SUCCESS", "fingerprint": "repair-prompt-fingerprint",
                "prompt_path": str(prompt_path), "receipt_path": "stub-repair-prompt-receipt.json"}

    # Keep the production Scheduler.add_item implementation; persistence and
    # contract references are isolated to this in-memory contract fixture.
    monkeypatch.setattr(image_scheduler, "contract_references", lambda *_a, **_k: [])
    monkeypatch.setattr(image_scheduler, "risk_priority", lambda *_a, **_k: 0)
    monkeypatch.setattr(image_scheduler, "repo_rel", lambda path: str(Path(path).resolve()))
    monkeypatch.setattr(image_scheduler, "frame_contract", type("FrameContract", (), {
        "provenance": staticmethod(lambda *_a, **_k: {"source": "TEST_ONLY"}),
        "required": staticmethod(lambda *_a, **_k: False),
        "compile_frame": staticmethod(lambda *_a, **_k: {"hash_material": {"frame_directive": {}}}),
    }))
    monkeypatch.setattr(image_scheduler, "_CONFIG", {})
    monkeypatch.setattr(image_scheduler, "storyos_config", type("Config", (), {
        "get_path": staticmethod(lambda *_a, **_k: {}),
    }))
    # Stub only the model lookup; keep real image policy error classifications and constants.
    monkeypatch.setattr(image_scheduler.image_model_policy, "for_episode",
                        lambda *_a, **_k: {"model": "gpt-image-2.5-flare", "quality": "high"})
    monkeypatch.setattr(repair_aggregator, "_event", lambda *_a, **_k: None)

    materialized = repair_aggregator.materialize_wave(
        ep, attempt=1, prompt_runner=prompt_runner, policy=_policy("prompt.repair"),
    )
    assert materialized["status"] == "STARTED"
    assert len(prompt_calls) == 1
    plan = repair_aggregator.load_wave(ep)
    repair_rows = [row for row in queue["items"] if row.get("repair_wave_id")]
    assert len(repair_rows) == 1
    repair_item = repair_rows[0]
    assert repair_item["scope"] == "repair"
    assert repair_item["repair_wave_id"] == plan["repair_wave_id"]
    assert plan["frames"][0]["source_generation_key"] == original["generation_key"]
    assert plan["frames"][0]["source_artifact_sha256"] == _sha(first_artifact)

    # Run the real image_scheduler refill/consume loop. Only its Attempt Authority
    # and Provider callback are stubbed; the real Gateway commits before the call.
    dispatches = []
    fake_state = {"attempts_consumed": 1, "active_attempt_index": None, "fencing_counter": 4}

    def reserve_stub(_ep, asset_key, generation_context=None, **_kwargs):
        assert asset_key == repair_item.get("logical_asset_key") or asset_key == logical_asset_identity.frame_asset_key(ep, 1)
        return {"episode_id": "canary", "logical_asset_key": asset_key, "attempt_index": 2,
                "generation_key": "canary/frame-01/attempt-2", "lease_token": "opaque",
                "fencing_token": 5, "generation_context": generation_context or {}}

    def commit(_ep, lease, fence, *, provider=None):
        assert fence == 5 and lease["attempt_index"] == 2
        assert fake_state["attempts_consumed"] == 1
        fake_state["attempts_consumed"] += 1
        dispatches.append((lease["generation_key"], provider))
        return {**lease, "attempt_consumed": True, "status": "DISPATCH_COMMITTED"}

    monkeypatch.setattr(generation_attempt_authority, "reserve", reserve_stub)
    monkeypatch.setattr(generation_attempt_authority, "commit_dispatch", commit)
    # The test uses a synthetic committed lease; the production MySQL validator
    # must not reach a real database from this hermetic provider stub.
    monkeypatch.setattr(generation_attempt_authority, "validate_committed_dispatch",
                        lambda *_a, **_k: True)
    monkeypatch.setattr(generation_attempt_authority, "mark_observed", lambda *_a, **_k: None)
    monkeypatch.setattr(
        generation_attempt_authority, "load_attempt",
        lambda *_a, **_k: {
            "attempt_index": 2,
            "generation_key": "canary/frame-01/attempt-2",
            "status": "SUCCEEDED",
        },
    )
    monkeypatch.setattr(image_scheduler.resource_library, "ensure_fresh", lambda *_a, **_k: None)
    monkeypatch.setattr(image_scheduler.production_recovery, "reconcile_locked", lambda *_a, **_k: None)
    monkeypatch.setattr(scheduler_core, "terminalize_superseded_history", lambda *_a, **_k: None)
    monkeypatch.setattr(image_scheduler.frame_scout, "required", lambda *_a, **_k: False)
    monkeypatch.setattr(image_scheduler.runtime_router, "detect", lambda: ("CODEX", "stub"))
    monkeypatch.setattr(image_scheduler.runtime_router, "image_execution_runtime", lambda: ("CODEX", "stub"))
    monkeypatch.setattr(image_scheduler.raw_candidate_budget, "summary", lambda *_a, **_k: {"available": 1})
    monkeypatch.setattr(image_scheduler.production_recovery, "prepare_execution", lambda *_a, **_k: None)
    monkeypatch.setattr(image_scheduler, "ledger_begin", lambda *_a, **_k: (True, ""))
    monkeypatch.setattr(image_scheduler.production_recovery, "mark_worker_pending", lambda *_a, **_k: None)
    monkeypatch.setattr(image_scheduler.production_recovery, "mark_terminal", lambda *_a, **_k: None)
    monkeypatch.setattr(image_scheduler.local_visual_triage, "inspect_candidate", lambda *_a, **_k: {"block_commit": False})
    monkeypatch.setattr(image_scheduler.local_visual_triage, "queue_summary", lambda *_a, **_k: {})
    monkeypatch.setattr(image_scheduler, "ledger_success", lambda *_a, **_k: (True, ""))
    monkeypatch.setattr(image_scheduler.episode_performance, "safe_record_queue_image_attempt", lambda *_a, **_k: None)
    monkeypatch.setattr(image_scheduler, "repo_rel", lambda path: str(Path(path).resolve()))
    monkeypatch.setattr(image_scheduler, "_scheduler_terminal_rc", lambda *_a, **_k: 0)
    monkeypatch.setattr(image_scheduler.runtime_observability, "safe_record_runtime_event", lambda *_a, **_k: None)

    async def fake_backend_worker(_ep, item, _timeout, _codex):
        lease = generation_attempt_authority.reserve(_ep, logical_asset_identity.frame_asset_key(ep, 1), {
            "model_role": "image.controller", "model_policy_sha256": "a" * 64,
        })

        def fake_provider():
            repair_artifact.write_bytes(b"attempt-two-repair-pixels")
            return {"provider_stub": "TEST_ONLY"}

        image_generation_gateway.provider_generate(
            _ep, lease, lease["fencing_token"], "TEST_ONLY", fake_provider,
        )
        item["generation_key"] = lease["generation_key"]
        item["attempt_index"] = 2
        return {"returncode": 0, "output": str(repair_artifact)}

    monkeypatch.setattr(image_scheduler, "async_backend_worker", fake_backend_worker)
    scheduler_rc = image_scheduler.run_scheduler_async(ep, 1, 1, "stub")
    assert scheduler_rc == 0
    assert fake_state["attempts_consumed"] == 2
    assert dispatches == [("canary/frame-01/attempt-2", "TEST_ONLY")]
    assert repair_item["status"] == "generated", (repair_item.get("technical_failure_code"), repair_item.get("last_error"))
    assert repair_item["generation_key"] == "canary/frame-01/attempt-2"
    assert repair_artifact.is_file()

    # Attempt 2's terminal FINAL_SEMANTIC review is a second Queue item, bound
    # to the new generation/artifact. No review path calls the Provider Gateway.
    ledger["frames"]["01"]["current_candidate"] = {
        "path": str(repair_artifact), "sha256": _sha(repair_artifact),
    }
    repair_source = {**repair_item, "frame": 1, "generation_key": "canary/frame-01/attempt-2",
                     "attempt_index": 2, "output_path": str(repair_artifact), "scope": "repair"}
    second_review = review_queue.enqueue(
        queue, episode=ep, source_item=repair_source, artifact_path=str(repair_artifact),
        artifact_sha256=_sha(repair_artifact), policy=_policy("vision.final"),
        review_kind=review_queue.FINAL_SEMANTIC,
    )
    assert second_review["status"] == "ENQUEUED"
    review_queue_calls = []

    def attempt2_final_review(*_a, **_k):
        review_queue_calls.append("called")
        return {**second_review["item"], "status": "COMPLETED_WITH_FINDINGS",
                "review_outcome": "REPAIR_NEEDED", "issue_codes": ["KEY_PROP_DRIFT"],
                "critic_receipt": {"status": "SUCCESS", "call_id": "stub-attempt2-review"}}

    monkeypatch.setattr(review_queue, "_final_semantic_receipt", attempt2_final_review)
    stop = asyncio.Event()
    stop.set()
    asyncio.run(review_queue.run_lane(
        ep, changed=asyncio.Event(), progress=asyncio.Event(), stop=stop,
        codex="stub", timeout=1, max_inflight=1,
    ))
    terminal_attempt2 = next(
        row for row in queue[review_queue.QUEUE_KEY]
        if row["generation_key"] == "canary/frame-01/attempt-2"
    )
    assert terminal_attempt2["status"] == "finalized"
    assert terminal_attempt2["receipt"]["review_outcome"] == "REPAIR_NEEDED"
    assert terminal_attempt2["receipt"]["attempt_index"] == 2
    assert terminal_attempt2["receipt"]["artifact_sha256"] == _sha(repair_artifact)
    assert len(review_queue_calls) == 1
    assert len(dispatches) == 1  # Review did not call Provider or Gateway.

    # Wave 1 consumes the queue's terminal review outcome. Resume cannot create
    # a second wave, even though Attempt 2 naturally remains REPAIR_NEEDED.
    monkeypatch.setattr(repair_aggregator.incremental_closure, "plan", lambda *_a, **_k: {
        "action": "PATCH", "dirty_frames": ["01"], "context_frames": [], "reused_frames": [],
    })
    monkeypatch.setattr(repair_aggregator, "_event", lambda *_a, **_k: None)
    final = repair_aggregator.finalize_wave(
        ep, repair_reviews={"01": terminal_attempt2["receipt"]["review_outcome"]},
    )
    assert final["status"] == "COMPLETED"
    assert final["plan"]["status"] == "COMPLETED"
    assert final["plan"]["frames"][0]["repair_status"] == "NEEDS_USER"
    assert len([row for row in queue["items"] if row.get("repair_wave_id")]) == 1
    assert len(dispatches) == 1
    assert fake_state["attempts_consumed"] == 2
