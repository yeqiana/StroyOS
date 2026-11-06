"""Trace gaps are WARN only under full direct-user SHA acceptance, never fabricated PASS."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "episodes" / "_system"))

import machine_gate
import verified_review_authority


def _case(monkeypatch, *, full_accepted: bool, scope_accepted: bool = True):
    frames = {"02": {
        "status": "LOCKED",
        "current_candidate": {"sha256": "a" * 64},
        "approved_asset": {"sha256": "a" * 64},
        "attempts": [{"result": "success", "started_at": "2026-01-01T00:00:00"}],
    }}
    monkeypatch.setattr(machine_gate.story_semantic_trace, "required", lambda ep: True)
    monkeypatch.setattr(machine_gate, "load_production_ledger_authority",
                        lambda *a, **k: {
                            "story_semantic_trace_evidence": {"schema_version": 1},
                            "frames": frames,
                        })
    monkeypatch.setattr(machine_gate, "accepted_frame_attempt",
                        lambda row: row["attempts"][0])
    monkeypatch.setattr(machine_gate.story_semantic_trace, "frame_requirements",
                        lambda *a: {"required": True})
    monkeypatch.setattr(machine_gate.frame_review_persistence, "load",
                        lambda *a: None)
    monkeypatch.setattr(machine_gate.story_semantic_trace, "trace_from_review",
                        lambda *a: None)
    monkeypatch.setattr(machine_gate.story_semantic_trace, "attempt_contract_sha",
                        lambda *a: "b" * 64)
    monkeypatch.setattr(machine_gate.story_semantic_trace, "validate_frame",
                        lambda *a: [("story_semantic_trace_missing",
                                    "historical final review lacks trace")])
    monkeypatch.setattr(machine_gate, "acceptance_allows",
                        lambda ep, scope, frame=None:
                        scope_accepted if frame is None else False)
    monkeypatch.setattr(verified_review_authority, "verify_episode_review_authority",
                        lambda *a, **k: {
                            "status": "USER_ACCEPTED" if full_accepted else "BLOCKED",
                            "frames": ["02"] if full_accepted else [],
                        })
    findings = []
    machine_gate.check_story_semantic_trace(
        Path("synthetic"), Path("synthetic"), {}, findings, metadata_only=False)
    return findings


def test_sha_bound_full_acceptance_keeps_missing_trace_visible_as_warn(monkeypatch):
    findings = _case(monkeypatch, full_accepted=True)
    assert len(findings) == 1
    assert findings[0].level == "WARN"
    assert findings[0].code == "story_semantic_trace_user_final_asset"


def test_missing_direct_user_evidence_keeps_trace_as_fail(monkeypatch):
    findings = _case(monkeypatch, full_accepted=False)
    assert len(findings) == 1
    assert findings[0].level == "FAIL"
    assert findings[0].code == "story_semantic_trace_missing"


def test_missing_direct_user_scope_keeps_trace_as_fail(monkeypatch):
    findings = _case(monkeypatch, full_accepted=True, scope_accepted=False)
    assert len(findings) == 1
    assert findings[0].level == "FAIL"
