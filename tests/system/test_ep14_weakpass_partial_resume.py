"""Partial Episode14 2/2 WEAK_PASS crash-recovery without paid image retries."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "episodes/_system"))
import visual_lock_candidate_pool as pool
import generation_attempt_authority as authority
import logical_asset_identity as identity


@pytest.fixture
def partial(tmp_path, monkeypatch):
    root = tmp_path / "storyOS"
    ep = root / "episodes" / "00_独立篇" / "14_深渊疗愈所_第一集_净土生命还原"
    ep.mkdir(parents=True)
    monkeypatch.setattr(pool, "__file__", str(root / "episodes/_system/visual_lock_candidate_pool.py"))
    expected = {1: "V-B", 5: "V-A", 45: "V-W", 47: "V-H"}
    rows = []
    registry = {"items": {}}
    ledgers = {}
    for frame, rid in expected.items():
        data = ("mock-current-pixels-%d" % frame).encode("utf-8")
        png = ep / ("%02d.png" % frame)
        png.write_bytes(data)
        sha = hashlib.sha256(data).hexdigest()
        contract = ("%064d" % frame)
        row = {"frame": frame, "id": rid, "sha256": sha, "frame_contract_sha256": contract}
        rows.append(row)
        prior = {"status": "FAIL", "sha256": sha, "frame_contract_sha256": contract,
                 "provenance": {"review_capability": "vision"}}
        entry = {"status": "WEAK_PASS", "frame": frame, "sha256": sha,
                 "frame_contract_sha256": contract, "profile_sha256": "p" * 64,
                 "story_os_version": "2.6.1",
                 "weak_pass": {"approved_by_policy": "episode14_paid_2of2_soft_visual_quality",
                               "prior_independent_fail": prior}}
        registry["items"][rid] = entry
        ledgers[frame] = {"status": "WEAK_PASS",
                          "current_candidate": {"sha256": sha, "path": str(png)},
                          "weak_pass": {"approved_by_policy": "episode14_paid_2of2_soft_visual_quality"}}
    monkeypatch.setattr(pool, "weak_pass_allowed", lambda *_: True)
    monkeypatch.setattr(pool.visual_profile_review_persistence, "load",
                        lambda *_: {"calibration": rows, "profile_sha256": "p" * 64, "story_os_version": "2.6.1"})
    monkeypatch.setattr(pool.visual_lock_admission_state, "load", lambda *_: registry)
    monkeypatch.setattr(pool, "_ledger_frame", lambda _ep, frame: ledgers[frame])
    monkeypatch.setattr(identity, "frame_asset_key", lambda _ep, frame: str(frame))
    monkeypatch.setattr(authority, "load_asset_state", lambda *_: {
        "attempts_consumed": 2, "remaining_attempts": 0, "active_attempt_index": None})
    monkeypatch.setattr(authority, "load_attempt", lambda _ep, _key, n: {
        "status": "SUCCEEDED"} if n == 2 else None)
    monkeypatch.setattr(pool, "weak_pass_eligibility", lambda *_: {
        "episode14_paid_exhaustion": True})
    monkeypatch.setattr(pool, "weak_pass_eligible_frames", lambda *_: [5, 45, 47])
    return ep, registry, ledgers


def test_partial_weak_pass_resumes_only_three_without_repeating_f001(partial):
    ep, _, _ = partial
    assert pool.ep14_remaining_exhausted_weak_passes(ep) == [5, 45, 47]


@pytest.mark.parametrize("corruption", ["old_fail", "ledger", "candidate_sha", "profile", "paid"])
def test_stale_partial_evidence_fails_closed(partial, monkeypatch, corruption):
    ep, registry, ledgers = partial
    if corruption == "old_fail":
        registry["items"]["V-B"]["weak_pass"]["prior_independent_fail"]["status"] = "PASS"
    elif corruption == "ledger":
        ledgers[1]["status"] = "PASSED"
    elif corruption == "candidate_sha":
        ledgers[1]["current_candidate"]["sha256"] = "0" * 64
    elif corruption == "profile":
        registry["items"]["V-B"]["profile_sha256"] = "0" * 64
    else:
        monkeypatch.setattr(authority, "load_attempt", lambda *_: None)
    assert pool.ep14_remaining_exhausted_weak_passes(ep) is None


def test_zero_remaining_admissions_can_resume_retirement(partial, monkeypatch):
    ep, _, _ = partial
    monkeypatch.setattr(pool, "weak_pass_eligible_frames", lambda *_: [])
    assert pool.ep14_remaining_exhausted_weak_passes(ep) == []
    called = []
    monkeypatch.setattr(pool.visual_lock_admission_state, "sync_gate_decisions",
                        lambda *_: {"all_passed": True})
    monkeypatch.setattr(pool, "_retire_ep14_exhausted_candidate_blocks",
                        lambda *_: called.append("retired") or {"status": "PASS"})
    monkeypatch.setattr(pool, "_lock_pixel_master_after_accepted_visual_gate",
                        lambda *_: {"status": "LOCKED"})
    result = pool.apply_weak_passes(ep, frames=[])
    assert result["status"] == "PASS"
    assert result["applied"] == []
    assert called == ["retired"]


def test_unrelated_episode_never_admitted(tmp_path):
    assert pool.ep14_remaining_exhausted_weak_passes(tmp_path) is None
