"""F048 independently authorized, never inherited from F029 early PASS."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import hashlib
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "episodes/_system"))
import production_ep14_f048_followon as r
import production_ep14_followon_release as f029


@pytest.fixture
def env(monkeypatch, tmp_path):
    ep = tmp_path / "00_独立篇" / "14_深渊疗愈所_第一集_净土生命还原"
    ep.mkdir(parents=True)
    path = ep / "media/candidates/scheduled/29-6f4a6433f2b9-a5.png"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"genuine-bound-image-test-fixture")
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(r, "F029_PIXEL_SHA", sha)
    monkeypatch.setattr(r.review, "ROOT", tmp_path)
    monkeypatch.setattr(r.f029, "_previous_provider_and_review",
                        lambda ep, rows: {"f009_requires_user": True})
    marker = {
        "state": "ACTIVE_THREE_REVIEWED_CONTENT_REVISIONS",
        "final_render_bundle_sha256": r.activation.BUNDLE,
        "production_dispatch_authorized": True,
        "historical_safety_refusals_preserved": True,
        "postimage_pixel_review_required": True,
        "followon_active_frame": 29,
        "followon_authority": f029.AUTHORITY,
        "followon_pending_final_review": True,
    }
    source = {
        "id": f029.NEXT_FRAME_ID, "frame": 29, "scope": "batch", "kind": "repair",
        "status": "generated", "batch_id": r.F029_BATCH,
        "output_path": str(path.relative_to(tmp_path)),
        "vision_batch_review": {"decision": "PASS_PREVIEW"},
    }
    held = {
        "id": r.ITEM_ID, "frame": 48, "scope": "batch", "kind": "repair",
        "status": "pilot_hold", "attempts": 1, "output_path": None,
        "ep14_active_package_id": "PP48", "ep14_active_bundle_sha256": r.activation.BUNDLE,
        "prompt_package": {"package_sha256": "a" * 64},
    }
    original = {
        "id": "original48", "frame": 48, "kind": "original", "scope": "batch",
        "status": "external_blocked", "requires_content_revision": True,
        "no_automatic_original_prompt_retry": True,
    }
    q = {"items": [
        {"id": f029.PREVIOUS_ITEM_ID, "frame": 9, "scope": "batch",
         "kind": "repair", "status": "scout_repair"},
        source, held, original,
    ], r.activation.QUEUE_KEY: marker}
    doc = {"frames": {
        "29": {"status": "REPAIR_READY", "current_candidate": {"sha256": sha}},
        "48": {"status": "TECH_FAILED", "content_repairs_used": 0,
               "attempts": [{"kind": "original", "result": "technical_failure"},
                            {"kind": "original", "result": "technical_failure"}]},
    }}
    unit = {"frame": "29", "decision": "PASS_PREVIEW", "candidate_sha256": sha,
            "frame_contract_sha256": "b" * 64,
            "checks": {"whole_image": "pass", "key_regions": "pass"},
            "unresolved": [], "issue_codes": [], "reason": "pixels"}
    review = {
        "batch_id": r.F029_BATCH, "review_scope": "EARLY_BATCH_ACTUAL_PIXELS",
        "final_pass_authority": False, "frames": [unit],
        "critic_provenance": {"runtime": "CODEX_ISOLATED",
                              "session_reused_from_generation": False},
    }
    state = {"q": q, "doc": doc, "review": review, "writes": [],
             "f48_second": None, "f29_status": "SUCCEEDED"}
    monkeypatch.setattr(r.scheduler_core, "load_queue", lambda ep: deepcopy(state["q"]))
    monkeypatch.setattr(r.scheduler_core, "save_queue",
                        lambda ep, value: (state["writes"].append("queue"),
                                           state.__setitem__("q", deepcopy(value))))
    @contextmanager
    def lock(ep):
        yield
    monkeypatch.setattr(r.scheduler_core, "queue_transaction", lock)
    monkeypatch.setattr(r.review, "read_json", lambda path: deepcopy(state["review"]))
    monkeypatch.setattr(r.review, "unit_binding",
                        lambda ep, item: {"frame_contract_sha256": "b" * 64})
    monkeypatch.setattr(r.identity, "frame_asset_key",
                        lambda ep, frame: f"frame-{frame}")
    monkeypatch.setattr(r.attempts, "load_asset_state", lambda ep, key:
        {"attempts_consumed": 2, "remaining_attempts": 0, "active_attempt_index": None}
        if key == "frame-29" else
        {"attempts_consumed": 1, "remaining_attempts": 1, "active_attempt_index": None})
    monkeypatch.setattr(r.attempts, "load_attempt", lambda ep, key, index:
        {"status": state["f29_status"], "provider": "codex_subscription"}
        if key == "frame-29" and index == 2 else
        {"status": "FAILED_AFTER_DISPATCH", "failure_class": "IMAGE_PROVIDER_SAFETY_REJECTED"}
        if key == "frame-48" and index == 1 else state["f48_second"])
    monkeypatch.setattr(r.ledger, "frame_obj",
                        lambda doc, number: (str(number).zfill(2),
                                             doc["frames"][str(number).zfill(2)]))
    monkeypatch.setattr(r.ledger, "get_ledger", lambda ep:
                        (ep / "ledger.json", deepcopy(state["doc"])))
    monkeypatch.setattr(r.ledger, "save_json",
                        lambda path, doc: (state["writes"].append("ledger"),
                                           state.__setitem__("doc", deepcopy(doc))))
    monkeypatch.setattr(r.ledger, "content_repair_limit", lambda doc: 1)
    monkeypatch.setattr(r.ledger, "now_iso", lambda: "2026-11-04T14:00:00+08:00")
    monkeypatch.setattr(r.activation, "load_for_dispatch",
                        lambda ep, item, for_followon=False, **kwargs: {
                            "independent_preimage_text_approved": True,
                            "postimage_pixel_review_required": True,
                            "package_sha256": "a" * 64,
                            "render_content_sha256": "a" * 64,
                            "scene_prompt_sha256": "c" * 64,
                        } if for_followon else None)
    return ep, state, path


def _release(ep):
    plan = r.plan(ep)
    return r.release(ep, expected_queue_sha256=plan["expected_queue_sha256"],
                     expected_ledger_sha256=plan["expected_ledger_sha256"])


def test_release_binds_f048_and_preserves_failed_f009(env):
    ep, state, _ = env
    before_f009 = deepcopy(state["q"]["items"][0])
    before_f029 = deepcopy(state["q"]["items"][1])
    original = deepcopy(state["q"]["items"][3])
    history = deepcopy(state["doc"]["frames"]["48"]["attempts"])
    result = _release(ep)
    assert result["queued_frame"] == 48 and result["paid_attempts_reserved"] == 0
    assert state["writes"] == ["ledger", "queue"]
    assert state["q"]["items"][0] == before_f009
    assert state["q"]["items"][1] == before_f029
    assert state["q"]["items"][3] == original
    assert state["doc"]["frames"]["48"]["attempts"] == history
    row = state["q"]["items"][2]
    assert row["status"] == "queued" and row["batch_id"] == r.F048_BATCH
    assert r.dispatch_authorized(ep, row, state["q"][r.activation.QUEUE_KEY])
    assert f029.dispatch_authorized(ep, 48, row,
                                   state["q"][r.activation.QUEUE_KEY])
    with pytest.raises(r.ReleaseDenied):
        r.plan(ep)


def test_dispatch_requires_current_ledger_transaction(env):
    ep, state, _ = env
    _release(ep)
    row = state["q"]["items"][2]
    frame = state["doc"]["frames"]["48"]
    row["status"] = "running"
    row["attempts"] = 2
    row["execution"] = {"transaction_id": "new-tx"}
    frame["status"] = "REPAIRING"
    frame["content_repairs_used"] = 1
    frame["attempts"].append({
        "kind": "repair", "result": "pending", "runtime_transaction_id": "new-tx",
        "provider_attempt": {"status": "NOT_INVOKED"},
    })
    assert r.dispatch_authorized(ep, row, state["q"][r.activation.QUEUE_KEY])
    frame["attempts"][-1]["runtime_transaction_id"] = "old-tx"
    assert not r.dispatch_authorized(ep, row, state["q"][r.activation.QUEUE_KEY])


@pytest.mark.parametrize("kind", [
    "wrong_pixels", "wrong_review", "uncertain_review", "f029_not_succeeded",
    "f029_not_generated", "f029_not_ready", "f048_already_dispatched",
    "f048_no_hold", "f048_old_unblocked", "stale_queue", "stale_ledger",
])
def test_f048_never_released_with_unverified_source(env, kind):
    ep, state, path = env
    plan = r.plan(ep)
    if kind == "wrong_pixels":
        path.write_bytes(b"source pixel tampered")
    elif kind == "wrong_review":
        state["review"]["frames"][0]["candidate_sha256"] = "0" * 64
    elif kind == "uncertain_review":
        state["review"]["frames"][0]["decision"] = "UNCERTAIN"
    elif kind == "f029_not_succeeded":
        state["f29_status"] = "OUTCOME_UNKNOWN"
    elif kind == "f029_not_generated":
        state["q"]["items"][1]["status"] = "blocked"
    elif kind == "f029_not_ready":
        state["doc"]["frames"]["29"]["status"] = "TECH_FAILED"
    elif kind == "f048_already_dispatched":
        state["f48_second"] = {"status": "DISPATCH_COMMITTED"}
    elif kind == "f048_no_hold":
        state["q"]["items"][2]["status"] = "queued"
    elif kind == "f048_old_unblocked":
        state["q"]["items"][3]["status"] = "queued"
    elif kind == "stale_queue":
        plan["expected_queue_sha256"] = "0" * 64
    elif kind == "stale_ledger":
        plan["expected_ledger_sha256"] = "0" * 64
    with pytest.raises(r.ReleaseDenied):
        r.release(ep, expected_queue_sha256=plan["expected_queue_sha256"],
                  expected_ledger_sha256=plan["expected_ledger_sha256"])
    assert state["writes"] == []

def _preledger_failure(env):
    ep, state, _ = env
    _release(ep)
    row = state["q"]["items"][2]
    row.update(status="blocked", attempts=1,
               last_error="EP14_REVIEWED_LEDGER_BINDING_DENIED: ActivationDenied")
    state["writes"].clear()
    return ep, state


def test_preledger_rearm_only_changes_queue_without_rebilling(env, monkeypatch):
    ep, state = _preledger_failure(env)
    monkeypatch.setattr(r.activation, "load_for_dispatch",
                        lambda ep, item, **kwargs: {"package_sha256": "a" * 64})
    p = r.ledger_binding_rearm_plan(ep)
    original_history = deepcopy(state["doc"]["frames"]["48"]["attempts"])
    original29 = deepcopy(state["q"]["items"][1])
    result = r.ledger_binding_rearm(
        ep, expected_queue_sha256=p["expected_queue_sha256"],
        expected_ledger_sha256=p["expected_ledger_sha256"])
    assert result["paid_attempts_reserved"] == 0
    assert state["writes"] == ["queue"]
    assert state["q"]["items"][1] == original29
    assert state["doc"]["frames"]["48"]["attempts"] == original_history
    row = state["q"]["items"][2]
    assert row["status"] == "queued"
    assert row["f048_ledger_binding_rearm_count"] == 1
    assert r.dispatch_authorized(ep, row, state["q"][r.activation.QUEUE_KEY])
    with pytest.raises(r.ReleaseDenied):
        r.ledger_binding_rearm_plan(ep)


@pytest.mark.parametrize("kind", [
    "different_error", "payment_committed", "new_ledger_attempt",
    "changed_status", "wrong_attempt_count", "stale_queue", "stale_ledger",
    "pixel_drift",
])
def test_preledger_rearm_requires_exact_noninvoked_proof(env, monkeypatch, kind):
    ep, state = _preledger_failure(env)
    monkeypatch.setattr(r.activation, "load_for_dispatch",
                        lambda ep, item, **kwargs: {"package_sha256": "a" * 64})
    p = r.ledger_binding_rearm_plan(ep)
    row = state["q"]["items"][2]
    if kind == "different_error":
        row["last_error"] = "IMAGE_PROVIDER_TIMEOUT"
    elif kind == "payment_committed":
        state["f48_second"] = {"status": "DISPATCH_COMMITTED"}
    elif kind == "new_ledger_attempt":
        state["doc"]["frames"]["48"]["attempts"].append({"kind": "repair", "result": "pending"})
    elif kind == "changed_status":
        row["status"] = "running"
    elif kind == "wrong_attempt_count":
        row["attempts"] = 2
    elif kind == "stale_queue":
        p["expected_queue_sha256"] = "0" * 64
    elif kind == "stale_ledger":
        p["expected_ledger_sha256"] = "0" * 64
    elif kind == "pixel_drift":
        state["review"]["frames"][0]["decision"] = "UNCERTAIN"
    with pytest.raises(r.ReleaseDenied):
        r.ledger_binding_rearm(
            ep, expected_queue_sha256=p["expected_queue_sha256"],
            expected_ledger_sha256=p["expected_ledger_sha256"])
    assert state["writes"] == []
