"""Regression tests for the EP14 correction of pre-dispatch, never-generated repairs."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "recover_ep14_final_semantic_repair.py"
SPEC = importlib.util.spec_from_file_location("recover_ep14_semantic", SCRIPT)
recovery = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(recovery)


@pytest.fixture()
def incident(monkeypatch, tmp_path):
    ep = tmp_path / "00_独立篇" / "14_深渊疗愈所_第一集_净土生命还原"
    ep.mkdir(parents=True)
    pixels = tmp_path / "pixels"
    pixels.mkdir()
    (pixels / "existing.png").write_bytes(b"already generated")
    sha = hashlib.sha256(b"already generated").hexdigest()
    frames = {}
    items = []
    for key in recovery.TARGETS:
        previous = "REPAIR_AUTHORIZED" if key == "27" else "TECH_FAILED"
        row = {
            "status": previous,
            "repair_authorization": {"approval_basis": recovery.BASIS},
            "current_candidate": {"path": "pixels/existing.png", "sha256": sha},
            "content_repairs_used": 0 if previous == "REPAIR_AUTHORIZED" else 1,
            "attempts": [{"kind": "original", "result": "success"}],
        }
        if previous == "TECH_FAILED":
            row["attempts"].append({
                "kind": "repair",
                "result": "technical_failure",
                "provider_attempt": {"status": "NOT_INVOKED"},
                "error": {"code": recovery.FAILURE},
            })
            items.append({
                "scope": "repair", "frame": int(key), "status": "blocked",
                "prompt_file": f"prompts/repairs/{key}-final-semantic-a2.txt",
            })
        frames[key] = row
    db = {"frames": frames}
    q = {"items": items}
    monkeypatch.setattr(recovery.production_ledger, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(
        recovery.generation_attempt_authority, "load_asset_state",
        lambda episode, key: {
            "attempts_consumed": 2 if key.endswith("frame-27") else 1,
            "active_attempt_index": None,
        },
    )
    return ep, db, q


def test_preflight_accepts_only_uninvoked_failure_and_no_extra_generation(incident):
    ep, db, queue = incident
    result = recovery.preflight(ep, db, queue)
    assert len(result) == 17
    assert sum(status == "TECH_FAILED" for _, status, _, _ in result) == 16
    assert next(n for key, _, n, _ in result if key == "27") == 2


def test_preflight_rejects_provider_invocation(incident):
    ep, db, queue = incident
    db["frames"]["13"]["attempts"][-1]["provider_attempt"]["status"] = "INVOKED"
    with pytest.raises(RuntimeError, match="unverified uninvoked technical failure"):
        recovery.preflight(ep, db, queue)


def test_preflight_rejects_active_queue(incident):
    ep, db, queue = incident
    queue["items"][0]["status"] = "running"
    with pytest.raises(RuntimeError, match="active image queue"):
        recovery.preflight(ep, db, queue)


def test_correction_preserves_pixels_and_review_evidence(incident, monkeypatch):
    ep, db, queue = incident
    db["frames"]["13"]["reviews"] = [{"decision": "needs_user", "notes": "semantic mismatch"}]
    original_candidate = copy.deepcopy(db["frames"]["13"]["current_candidate"])
    storage = {"ledger": copy.deepcopy(db), "queue": copy.deepcopy(queue)}
    monkeypatch.setattr(
        recovery.production_ledger, "load_authority",
        lambda _ep, default=None: copy.deepcopy(storage["ledger"]),
    )
    monkeypatch.setattr(
        recovery.production_ledger, "save_json",
        lambda path, contents: storage.__setitem__("ledger", copy.deepcopy(contents)),
    )
    monkeypatch.setattr(
        recovery.scheduler_core, "load_queue",
        lambda _ep: copy.deepcopy(storage["queue"]),
    )
    monkeypatch.setattr(
        recovery.scheduler_core, "save_queue",
        lambda _ep, contents: storage.__setitem__("queue", copy.deepcopy(contents)),
    )
    preview = recovery.correct(ep, apply=False)
    assert preview["applied"] is False
    assert storage["ledger"]["frames"]["13"]["status"] == "TECH_FAILED"
    done = recovery.correct(ep, apply=True)
    assert done["applied"] is True
    for key in recovery.TARGETS:
        row = storage["ledger"]["frames"][key]
        assert row["status"] == "NEEDS_USER"
        assert row["content_repairs_used"] == 0
        assert row["repair_rollback_events"][-1]["reason"] == recovery.CORRECTION
    assert storage["ledger"]["frames"]["13"]["current_candidate"] == original_candidate
    assert storage["ledger"]["frames"]["13"]["reviews"] == [{"decision": "needs_user", "notes": "semantic mismatch"}]
    assert all(x["status"] == "superseded" for x in storage["queue"]["items"])
    with pytest.raises(RuntimeError, match="already revoked"):
        recovery.correct(ep, apply=True)
