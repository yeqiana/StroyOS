"""Hermetic safety checks for one-shot non-generating baseline capability recovery."""
from __future__ import annotations

from contextlib import nullcontext
import copy
import sys
from pathlib import Path

import pytest

SYSTEM = Path(__file__).resolve().parents[2] / "episodes" / "_system"
if str(SYSTEM) not in sys.path:
    sys.path.insert(0, str(SYSTEM))

import production_native_baseline_predispatch_rearm as rearm


@pytest.fixture
def ctx(monkeypatch, tmp_path):
    episode = tmp_path / "episodes" / "00_独立篇" / "14_深渊疗愈所_第一集_净土生命还原"
    rows = [
        {"id": "q1", "frame": 1, "scope": "visual_lock",
         "status": "blocked", "kind": "original", "attempts": 1,
         "technical_failure_code": rearm.FAILURE, "last_error": rearm.PREFIX},
    ] + [
        {"id": f"q{f}", "frame": f, "scope": "visual_lock", "kind": "original",
         "status": "queued", "attempts": 0, "depends_on": [1]}
        for f in (45, 5, 47)
    ]
    q = {"items": rows}
    payload = {"model": "gpt-image-2.5-flare", "quality": "high"}
    controller = {"model": "gpt-6-luna", "reasoning_effort": "high"}
    writes = []
    checks = []
    monkeypatch.setattr(rearm.model_policy, "resolve",
                        lambda name, **kwargs: payload if name == "image.payload" else controller)
    monkeypatch.setattr(rearm.image_scheduler, "queue_transaction", lambda _: nullcontext())
    monkeypatch.setattr(rearm.image_scheduler, "load_queue", lambda _: q)
    monkeypatch.setattr(rearm.image_scheduler, "save_queue",
                        lambda _, data: writes.append(copy.deepcopy(data)))
    monkeypatch.setattr(rearm.runtime_driver, "status",
                        lambda _: {"driver_state": "EXITED", "exit_code": "4"})
    monkeypatch.setattr(rearm.logical_asset_identity, "frame_asset_key", lambda *_: "asset1")
    monkeypatch.setattr(rearm.attempts, "load_attempt", lambda *_: None)
    monkeypatch.setattr(rearm.baseline, "eligible", lambda *_a, **_kw: True)
    monkeypatch.setattr(rearm.image_payload_transport, "payload_capability_preflight",
                        lambda **_kw: checks.append("fresh") or {"status": "BLOCKED"})
    monkeypatch.setattr(rearm.baseline, "attest_secondary",
                        lambda *_a: {"catalog_sha256": "a"*64, "transport_model": "gpt-6-luna"})
    monkeypatch.setattr(rearm.baseline, "evidence_sha", lambda _: "b"*64)
    return locals()


def test_rearm_once_without_paid_attempt_or_followon_dispatch(ctx):
    result = rearm.rearm_one(ctx["episode"], acknowledged=True)
    assert result["status"] == "PASS"
    assert result["provider_calls"] == 0 and result["paid_attempts_reserved"] == 0
    assert ctx["checks"] == ["fresh"] and len(ctx["writes"]) == 1
    assert ctx["rows"][0]["status"] == "queued"
    assert ctx["rows"][0][rearm.REARM_FLAG] == 1
    assert [r["status"] for r in ctx["rows"][1:]] == ["queued"] * 3
    assert rearm.rearm_one(ctx["episode"], acknowledged=True)["status"] == "BLOCKED"
    assert len(ctx["writes"]) == 1


def test_no_ack_no_mutation(ctx):
    assert rearm.rearm_one(ctx["episode"])["reason"] == "EXPLICIT_ACK_REQUIRED"
    assert ctx["checks"] == [] and ctx["writes"] == []


def test_missing_session_proof_no_mutation(ctx, monkeypatch):
    monkeypatch.setattr(rearm.baseline, "attest_secondary", lambda *_a: None)
    assert rearm.rearm_one(ctx["episode"], acknowledged=True)["reason"] == "CURRENT_SESSION_IMAGE_TOOL_UNVERIFIED"
    assert len(ctx["checks"]) == 1 and not ctx["writes"]


@pytest.mark.parametrize("failure", ["active_driver", "non_capability_error", "wrong_attempt_count",
                                      "rearmed_already", "pixel_exists", "paid_attempt_exists",
                                      "ineligible_authorities"])
def test_wrong_provenance_rejects_before_probe(ctx, monkeypatch, failure):
    row = ctx["rows"][0]
    if failure == "active_driver":
        monkeypatch.setattr(rearm.runtime_driver, "status",
                            lambda _: {"driver_state": "RUNNING", "exit_code": ""})
    elif failure == "non_capability_error":
        row["technical_failure_code"] = "IMAGE_BACKEND_ERROR"
    elif failure == "wrong_attempt_count":
        row["attempts"] = 2
    elif failure == "rearmed_already":
        row[rearm.REARM_FLAG] = 1
    elif failure == "pixel_exists":
        row["output_path"] = "media/raw/01.png"
    elif failure == "paid_attempt_exists":
        monkeypatch.setattr(rearm.attempts, "load_attempt",
                            lambda *_args: {"status": "UNKNOWN"})
    elif failure == "ineligible_authorities":
        monkeypatch.setattr(rearm.baseline, "eligible", lambda *_a, **_kw: False)
    assert rearm.rearm_one(ctx["episode"], acknowledged=True)["status"] == "BLOCKED"
    assert not ctx["checks"] and not ctx["writes"]


def test_drift_during_session_probe_denied(ctx, monkeypatch):
    def drift(**_):
        ctx["rows"][0]["id"] = "new-id"
        return {"status": "BLOCKED"}
    monkeypatch.setattr(rearm.image_payload_transport, "payload_capability_preflight", drift)
    result = rearm.rearm_one(ctx["episode"], acknowledged=True)
    assert result["reason"] == "AUTHORITIES_DRIFTED"
    assert not ctx["writes"]


def test_standalone_cli_import_bootstrap():
    """Fail if a fresh CLI process imports stdlib platform before StoryOS."""
    import subprocess
    proc = subprocess.run(
        [sys.executable, str(SYSTEM / "production_native_baseline_predispatch_rearm.py"),
         "--help"],
        cwd=SYSTEM.parents[1], capture_output=True, text=True, timeout=30,
        encoding="utf-8", errors="replace")
    assert proc.returncode == 0, proc.stderr
    assert "--ack-real-production" in proc.stdout
