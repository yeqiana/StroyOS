"""Hermetic ledger+Generation Attempt atomic recovery tests.

All connections/repositories below are memory fakes; the real Episode MySQL
and native image tool are never touched.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime, timezone
import sys

import pytest

SYSTEM = Path(__file__).resolve().parents[2] / "episodes" / "_system"
if str(SYSTEM) not in sys.path:
    sys.path.insert(0, str(SYSTEM))

import native_baseline_atomic_ledger as atomic
import native_baseline_unknown_cas as reconcile


@pytest.fixture
def sample(tmp_path, monkeypatch):
    ep = tmp_path / "ep"
    ep.mkdir()
    monkeypatch.setattr(atomic, "_core", lambda: SimpleNamespace(
        verify_attempt_visual_provenance=lambda *_: None,
        verify_attempt_frame_contract_provenance=lambda *_: None,
        now_iso=lambda: "2026-10-11T21:00:00+08:00",
    ))
    source = {
        "episode": ep,
        "runtime_transaction_id": "9" * 32,
        "generation_key": "ga1-" + "d" * 48 + "-a1",
        "frame_contract_sha256": "a" * 64,
        "scene_prompt_sha256": "c" * 64,
        "candidate_sha256": "b" * 64,
        "candidate_repo_rel": "episodes/00_独立篇/06_五十亩山地之后_全新重制/media/candidates/scheduled/01-65db61f1e871-a1.png",
        "canvas_width": 1080,
        "canvas_height": 1350,
        "evidence_sha256": "e" * 64,
        "runner_request_id": "f" * 32,
        "raw_sha256": "1" * 64,
    }
    attempt = {
        "attempt_id": "ca8ec994fbf7", "kind": "original",
        "result": "technical_failure",
        "runtime_transaction_id": source["runtime_transaction_id"],
        "request": {"frame": "01", "frame_contract_sha256": source["frame_contract_sha256"],
                    "prompt_sha256": source["scene_prompt_sha256"],
                    "model": "gpt-image-2.5-flare", "quality": "high"},
        "error": {"code": "IMAGE_BACKEND_ERROR",
                  "message": "NATIVE_BASELINE_PIXEL_TOOL_PROOF_UNVERIFIED: RuntimeError"},
        "provider_attempt": {"status": "NOT_INVOKED", "failure_code": "IMAGE_BACKEND_ERROR"},
    }
    ledger = {
        "schema_version": 1, "engine_version": "test",
        "canvas": {"width": 1080, "height": 1350},
        "frames": {"01": {
            "number": 1, "status": "TECH_FAILED", "current_candidate": None,
            "attempts": [attempt], "content_repairs_used": 0,
            "technical_failures": [{"attempt_id": attempt["attempt_id"],
                                    "code": "IMAGE_BACKEND_ERROR"}]},
            "02": {"number": 2, "status": "PENDING", "attempts": [],
                   "content_repairs_used": 0}},
    }
    return source, ledger


def test_correction_retains_failure_and_does_not_pass_visual(sample):
    source, ledger = sample
    baseline = deepcopy(ledger)
    fixed = atomic.corrected_ledger_document(ledger, source)
    assert ledger == baseline
    frame = fixed["frames"]["01"]
    attempt = frame["attempts"][0]
    assert frame["status"] == "ORIGINAL_READY"
    assert attempt["result"] == "success"
    assert attempt["generation_key"] == source["generation_key"]
    assert attempt["generation_attempt_index"] == 1
    assert frame["current_candidate"]["sha256"] == source["candidate_sha256"]
    assert attempt["recovery_correction"]["previous_result"] == "technical_failure"
    assert attempt["recovery_correction"]["previous_error"] == baseline["frames"]["01"]["attempts"][0]["error"]
    assert attempt["recovery_correction"]["previous_provider_attempt"]["status"] == "NOT_INVOKED"
    assert attempt["recovery_correction"]["review_pass"] is False
    assert attempt["recovery_correction"]["provider_model_attested"] is False
    assert attempt["provider_attempt"]["native_image_generation_jsonl_events"] == 0
    assert "error" not in attempt
    assert frame["technical_failures"][0]["code"] == "IMAGE_BACKEND_ERROR"
    assert frame["technical_failures"][0]["recovered_at"]
    assert fixed["frames"]["02"] == baseline["frames"]["02"]
    assert frame["content_repairs_used"] == 0
    atomic._check_existing(fixed, source, completed=True)


@pytest.mark.parametrize("mutate", [
    "attempt_count", "status", "transaction", "frame_contract", "prompt",
    "model", "quality", "canvas", "failure_code", "failure_message",
    "provider_status", "technical_failure_id", "already_recovered",
    "current_candidate", "attempt_kind",
])
def test_ledger_drift_never_generates_candidate(sample, mutate):
    source, ledger = sample
    item = ledger["frames"]["01"]
    att = item["attempts"][0]
    if mutate == "attempt_count":
        item["attempts"].append(deepcopy(att))
    elif mutate == "status":
        item["status"] = "PASSED"
    elif mutate == "transaction":
        att["runtime_transaction_id"] = "wrong"
    elif mutate == "frame_contract":
        att["request"]["frame_contract_sha256"] = "0" * 64
    elif mutate == "prompt":
        att["request"]["prompt_sha256"] = "0" * 64
    elif mutate == "model":
        att["request"]["model"] = "other"
    elif mutate == "quality":
        att["request"]["quality"] = "low"
    elif mutate == "canvas":
        ledger["canvas"]["width"] = 1081
    elif mutate == "failure_code":
        att["error"]["code"] = "OTHER"
    elif mutate == "failure_message":
        att["error"]["message"] = "other"
    elif mutate == "provider_status":
        att["provider_attempt"]["status"] = "COMPLETED"
    elif mutate == "technical_failure_id":
        item["technical_failures"][0]["attempt_id"] = "other"
    elif mutate == "already_recovered":
        item["technical_failures"][0]["recovered_at"] = "yesterday"
    elif mutate == "current_candidate":
        item["current_candidate"] = {"path": "other.png"}
    elif mutate == "attempt_kind":
        att["kind"] = "repair"
    before = deepcopy(ledger)
    with pytest.raises(atomic.LedgerRecoveryDenied):
        atomic.corrected_ledger_document(ledger, source)
    assert ledger == before


def test_idempotent_correction_checks_proof_identity(sample):
    source, ledger = sample
    fixed = atomic.corrected_ledger_document(ledger, source)
    for key, value in (
        ("evidence_sha256", "0" * 64),
        ("generation_key", "wrong"),
        ("candidate_sha256", "wrong"),
        ("runner_request_id", "wrong"),
        ("runtime_transaction_id", "wrong"),
    ):
        changed = dict(source, **{key: value})
        with pytest.raises(atomic.LedgerRecoveryDenied):
            atomic._check_existing(fixed, changed, completed=True)


def test_typed_authority_and_projection_share_given_connection(sample, monkeypatch):
    source, document = sample
    class MemoryConn:
        def __init__(self):
            self.current = deepcopy(document)
            self.writes = []
            self.sha = "8" * 64
        def query_one(self, sql, args):
            assert "FOR UPDATE" in sql and "TB_PRODUCTION_LEDGER_AUTHORITY" in sql
            return {"SHA256": self.sha}
    db = MemoryConn()
    class Repo:
        def __init__(self, conn):
            assert conn is db
        def get(self, sid):
            return {"sha256": db.sha, "document": deepcopy(db.current)}
        def upsert(self, sid, data):
            db.writes.append(("authority", sid, deepcopy(data)))
            db.current = deepcopy(data)
    class Frames:
        def __init__(self, conn): assert conn is db
        def upsert(self, data): db.writes.append(("frame", data["frame_no"]))
    class Attempts:
        def __init__(self, conn): assert conn is db
        def upsert(self, data): db.writes.append(("attempt", data["attempt_no"]))
    monkeypatch.setattr(atomic, "MySqlProductionLedgerAuthorityRepository", Repo)
    monkeypatch.setattr(atomic, "MySqlProductionFrameRepository", Frames)
    monkeypatch.setattr(atomic, "MySqlProductionAttemptRepository", Attempts)
    monkeypatch.setattr(atomic.episode_identity, "storage_episode_id", lambda _: "00-06")
    monkeypatch.setattr(atomic.ledger_store, "mode", lambda: "mysql")
    assert atomic.locked_ledger_update(db, source["episode"], source, already_succeeded=False) is True
    assert [row[0] for row in db.writes] == ["authority", "attempt", "frame"]
    assert db.current["frames"]["01"]["status"] == "ORIGINAL_READY"
    assert atomic.locked_ledger_update(db, source["episode"], source, already_succeeded=True) is False
    assert len(db.writes) == 3


def test_atomic_ledger_refuses_non_mysql_mode(sample, monkeypatch):
    source, document = sample
    monkeypatch.setattr(atomic.ledger_store, "mode", lambda: "json")
    with pytest.raises(atomic.LedgerRecoveryDenied, match="MYSQL_LEDGER_REQUIRED"):
        atomic.locked_ledger_update(object(), source["episode"], source,
                                    already_succeeded=False)
