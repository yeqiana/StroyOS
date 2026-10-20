"""Authoritative native image evidence inspection must never dispatch/retry models."""
from __future__ import annotations
import base64
import hashlib
import json
import sys
from pathlib import Path
from unittest.mock import patch
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import storyos_native_image_outcome_evidence as evidence

RID = "a" * 32
KEY = "generation-key-abc"
TID = "12345678-1234-1234-1234-123456789abc"
ITEM_ID = "test-task-02"


def fixture(tmp_path, monkeypatch, *, with_image=False, mismatch=None):
    ep = tmp_path / "episodes" / "00_独立篇" / "13_失物归还的那扇门"
    ep.mkdir(parents=True)
    attempt = {"status": "OUTCOME_UNKNOWN", "attempt_index": 2,
               "generation_key": KEY, "runner_request_id": RID}
    lifecycle = {"item_id": ITEM_ID, "attempt": 2, "generation_key": KEY,
                 "runner_request_id": RID}
    item = {"id": ITEM_ID, "frame": 2, "scope": "repair", "kind": "repair"}
    home = tmp_path / ".codex"
    home.mkdir()
    raw = b'{"type":"thread.started","thread_id":"' + TID.encode() + b'"}\n'
    raw += b'{"type":"item.completed","item":{"type":"agent_message","text":"HTTP 429"}}\n'
    receipt = {"request_id": RID, "returncode": 0, "output_base64": base64.b64encode(raw).decode(),
               "output_bytes": len(raw), "output_sha256": hashlib.sha256(raw).hexdigest(),
               "evidence": {"request_id": RID, "task_type": "image", "returncode": 0,
                            "thread_ids": [TID], "codex_home": {"path": str(home),
                            "accessible": True}, "generated_artifacts": [],
                            "artifact_settle": {"used": True, "polls": 21}}}
    dest = tmp_path / "runtime" / "codex-user-runner" / "task-results"
    dest.mkdir(parents=True)
    (dest / (RID + ".json")).write_text(json.dumps(receipt), encoding="utf-8")
    if with_image:
        folder = home / "generated_images" / TID
        folder.mkdir(parents=True)
        (folder / "candidate.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"img" * 100)
    if mismatch == "attempt_generation": attempt["generation_key"] = "wrong"
    if mismatch == "lifecycle_item": lifecycle["item_id"] = "foreign-task"
    if mismatch == "lifecycle_request": lifecycle["runner_request_id"] = "b" * 32
    if mismatch == "corrupt_receipt": receipt["output_sha256"] = "b" * 64
    if mismatch == "foreign_thread": receipt["evidence"]["thread_ids"] = ["../foreign"]
    if mismatch == "wrong_task": receipt["evidence"]["task_type"] = "review"
    if mismatch in {"corrupt_receipt", "foreign_thread", "wrong_task"}:
        (dest / (RID + ".json")).write_text(json.dumps(receipt), encoding="utf-8")
    monkeypatch.setattr(evidence.logical_asset_identity, "frame_asset_key", lambda *_a: "frame-02")
    monkeypatch.setattr(evidence.generation_attempt_authority, "load_attempt", lambda *_a: attempt)
    monkeypatch.setattr(evidence.scheduler_core, "load_queue", lambda *_a: {"items": [item]})
    monkeypatch.setattr(evidence.production_recovery, "lifecycle_path", lambda *_a: ep / "lifecycle.json")
    monkeypatch.setattr(evidence.production_recovery, "_read", lambda *_a: lifecycle)
    return ep, tmp_path


def test_real_native_429_no_artifact_is_unknown_not_failed(tmp_path, monkeypatch):
    ep, root = fixture(tmp_path, monkeypatch)
    result = evidence.inspect(ep, frame=2, attempt_index=2, root=root)
    assert result["status"] == "PAID_ATTEMPT_UNRESOLVED_NO_PIXEL"
    assert result["canonical_attempt_status"] == "OUTCOME_UNKNOWN"
    assert result["runner_output_digest_verified"] is True
    assert result["native_agent_message_mentions_429"] is True
    assert result["native_image_tool_event_count"] == 0
    assert result["thread_scoped_pixel_count"] == 0
    assert result["may_retry_paid_attempt"] is False
    assert result["model_calls"] == 0 and result["sql_writes"] == 0


def test_late_exact_thread_pixel_is_candidate_only(tmp_path, monkeypatch):
    ep, root = fixture(tmp_path, monkeypatch, with_image=True)
    result = evidence.inspect(ep, frame=2, attempt_index=2, root=root)
    assert result["status"] == "RECOVERY_CANDIDATE_NEEDS_SHA_ADMISSION"
    assert len(result["pixel_candidates"]) == 1
    assert len(result["pixel_candidates"][0]["sha256"]) == 64
    assert result["image_generation_verified"] is False
    assert result["may_retry_paid_attempt"] is False


@pytest.mark.parametrize("tamper", ["attempt_generation", "lifecycle_item",
                                    "lifecycle_request", "corrupt_receipt",
                                    "foreign_thread", "wrong_task"])
def test_foreign_or_invalid_native_evidence_is_quarantined(tmp_path, monkeypatch, tamper):
    ep, root = fixture(tmp_path, monkeypatch, mismatch=tamper)
    result = evidence.inspect(ep, frame=2, attempt_index=2, root=root)
    assert result["status"] == "NATIVE_EVIDENCE_UNVERIFIED"
    assert not result["may_retry_paid_attempt"]


def test_missing_mysql_authority_fails_closed(tmp_path, monkeypatch):
    ep, root = fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(evidence.generation_attempt_authority, "load_attempt",
                        lambda *_a: None)
    result = evidence.inspect(ep, frame=2, attempt_index=2, root=root)
    assert result["status"] == "NATIVE_EVIDENCE_UNVERIFIED"
    assert result["provider_outcome_verified"] is False


def test_missing_receipt_fails_closed(tmp_path, monkeypatch):
    ep, root = fixture(tmp_path, monkeypatch)
    (root / "runtime/codex-user-runner/task-results" / (RID + ".json")).unlink()
    result = evidence.inspect(ep, frame=2, attempt_index=2, root=root)
    assert result["status"] == "NATIVE_EVIDENCE_UNVERIFIED"
    assert result["image_generation_verified"] is False


def test_no_mutation_no_provider_dispatch_from_readonly_code():
    src=(ROOT/"scripts/storyos_native_image_outcome_evidence.py").read_text(encoding="utf-8")
    assert "def inspect(" in src
    assert "mark_outcome_unknown(" not in src
    assert "complete_external_generation(" not in src
    assert "run_model_codex(" not in src
    assert "requests.post(" not in src

def test_home_unavailable_does_not_claim_no_pixel(tmp_path, monkeypatch):
    ep, root = fixture(tmp_path, monkeypatch)
    receipt_file = root / "runtime" / "codex-user-runner" / "task-results" / (RID + ".json")
    data=json.loads(receipt_file.read_text(encoding="utf-8"))
    data["evidence"]["codex_home"]["accessible"]=False
    receipt_file.write_text(json.dumps(data),encoding="utf-8")
    result=evidence.inspect(ep,frame=2,attempt_index=2,root=root)
    assert result["status"]=="PROVIDER_OUTCOME_UNVERIFIED"
    assert result["thread_scoped_pixel_count"]==0
    assert result["may_retry_paid_attempt"] is False
