"""No-provider regression for exact Episode14 safety-rejected originals."""
from pathlib import Path
from unittest.mock import Mock
from contextlib import nullcontext
import sys
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/"episodes/_system")]
import production_ep14_safety_refusal_audit as safety
import production_native_batch_followon as followon


def test_exact_scope_only_and_no_larger_claim(tmp_path,monkeypatch):
    monkeypatch.setattr(safety,"ROOT",tmp_path)
    monkeypatch.setattr(safety,"EP",tmp_path/"episodes"/"00_独立篇"/"14_深渊疗愈所_第一集_净土生命还原")
    ep=safety.EP
    assert [n for n in range(1,49) if safety._scope(ep,n)]==[9,29,48]
    assert not safety._scope(ep.parent/"13_失物归还的那扇门",9)
    assert not safety._scope(ep,20)


def test_reconcile_safety_keeps_queue_blocked_and_no_paid_attempt(tmp_path,monkeypatch):
    ep=tmp_path/"episodes"/"00_独立篇"/"14_深渊疗愈所_第一集_净土生命还原"
    monkeypatch.setattr(safety,"EP",ep)
    ep.mkdir(parents=True)
    row={"frame":9,"scope":"batch","kind":"original",
         "status":"external_blocked","attempts":2,
         "technical_failure_code":"IMAGE_BACKEND_ERROR"}
    q={"items":[row]}
    proof={"receipt_sha256":"a"*64,"log_sha256":"b"*64}
    monkeypatch.setattr(safety.runtime_driver,"status",
                        lambda *_:{"driver_state":"EXITED","liveness":"DEAD","pid":0})
    monkeypatch.setattr(safety.scheduler_core,"queue_transaction",lambda *_:nullcontext())
    monkeypatch.setattr(safety.scheduler_core,"load_queue",lambda *_:q)
    monkeypatch.setattr(safety,"inspect",lambda *_:proof)
    cas=Mock();saved=Mock()
    monkeypatch.setattr(safety,"_cas",cas)
    monkeypatch.setattr(safety.scheduler_core,"save_queue",saved)
    result=safety.reconcile(ep,9)
    assert result["status"]=="PASS"
    assert result["provider_calls"]==result["attempts_reserved"]==0
    assert result["requires_content_revision"] is True
    assert result["upstream_billing_outcome_unverified"] is True
    assert row["status"]=="external_blocked" and row["attempts"]==2
    assert row["no_automatic_original_prompt_retry"] is True
    assert row["requires_content_revision"] is True
    cas.assert_called_once();saved.assert_called_once()
    assert safety.reconcile(ep,20)["status"]=="BLOCKED"


def test_safety_cas_failed_driver_blocks_prior_to_commit(tmp_path,monkeypatch):
    ep=tmp_path/"episodes"/"00_独立篇"/"14_深渊疗愈所_第一集_净土生命还原"
    monkeypatch.setattr(safety,"EP",ep)
    ep.mkdir(parents=True)
    monkeypatch.setattr(safety.runtime_driver,"status",
                        lambda *_:{"driver_state":"RUNNING","liveness":"ALIVE","pid":224})
    claimed=Mock()
    monkeypatch.setattr(safety,"_cas",claimed)
    assert safety.reconcile(ep,9)["reason"]=="DRIVER_NOT_STOPPED"
    claimed.assert_not_called()


def test_rejected_original_cannot_be_readmitted_by_native_batch_worker(tmp_path,monkeypatch):
    ep=tmp_path/"episodes"/"00_独立篇"/"14_深渊疗愈所_第一集_净土生命还原"
    marked={"frame":9,"id":"frame9","scope":"batch","kind":"original",
            "status":"queued","model":"gpt-image-2.5-flare",
            "native_batch_verified_followon":True,
            "no_automatic_original_prompt_retry":True}
    assert followon.worker_eligible(ep,marked,{"model":"gpt-image-2.5-flare"},{},
                                   queue={"items":[marked]}) is False
    eligible_old=marked.copy();eligible_old.pop("no_automatic_original_prompt_retry")
    # Canonical sibling row can still block a stale in-flight worker copy.
    monkeypatch.setattr(followon,"_batch",lambda *_:[marked])
    monkeypatch.setattr(followon,"_episode_authorized",lambda *_:True)
    eligible_old["native_batch_success_anchor_sha256"]="a"*64
    eligible_old["native_batch_followon_evidence_sha256"]="b"*64
    marked["native_batch_success_anchor_sha256"]="a"*64
    marked["native_batch_followon_evidence_sha256"]="b"*64
    assert followon.worker_eligible(ep,eligible_old,{"model":"gpt-image-2.5-flare"},{},
                                   queue={"items":[marked]}) is False
