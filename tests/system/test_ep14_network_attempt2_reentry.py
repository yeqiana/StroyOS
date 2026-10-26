"""Episode14 attempt-2 gates: no provider calls, no implicit risk authorization."""
from __future__ import annotations
import copy
import hashlib
import json
import sys
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/"episodes/_system"),str(ROOT/"scripts")]
import native_network_failure_rearm as net
import production_ep14_network_attempt2_reentry as retry
import runtime_driver


@pytest.fixture
def ep(tmp_path,monkeypatch):
    path=tmp_path/"episodes"/"00_独立篇"/"14_深渊疗愈所_第一集_净土生命还原"
    path.mkdir(parents=True)
    monkeypatch.setattr(net,"ROOT",tmp_path)
    monkeypatch.setattr(retry,"EP",path)
    return path


def _row(frame=20):
    return {
        "id":"original-network", "frame":frame, "scope":"batch",
        "kind":"original", "model":"gpt-image-2.5-flare",
        "status":"external_blocked","technical_failure_code":"IMAGE_BACKEND_ERROR",
        "last_error":"NETWORK_ERROR: native image transport",
        "attempts":2,"native_batch_verified_followon":True,
        "native_network_terminal_only_receipt_sha256":"a"*64,
        "native_network_terminal_only_log_sha256":"b"*64,
        "upstream_billing_outcome_unverified":True,
        "frame_contract":{"contract_sha256":"c"*64},
        "prompt_package":{"package_sha256":"d"*64},
        "execution":{"transaction_id":"old-transaction"},
    }


def test_explicit_risk_ack_requeues_at_most_once_without_paid_reservation(ep,monkeypatch):
    row=_row()
    queue={"items":[row]}
    raw_log=ep/"meta/image-workers/20-original.jsonl"
    raw_log.parent.mkdir(parents=True)
    raw_log.write_bytes(b"original")
    proof={"already_terminal":True,"receipt_sha256":"a"*64,
           "log_sha256":"b"*64,"request_id":"r"*32,"log":raw_log}
    monkeypatch.setattr(runtime_driver,"status",lambda *_:{
        "driver_state":"EXITED","liveness":"DEAD","exit_code":"24","pid":0})
    monkeypatch.setattr(net.scheduler_core,"queue_transaction",lambda *_:nullcontext())
    monkeypatch.setattr(net.scheduler_core,"load_queue",lambda *_:queue)
    monkeypatch.setattr(net,"inspect",lambda *_:proof)
    commit=Mock();save=Mock()
    monkeypatch.setattr(net,"_commit_terminal",commit)
    monkeypatch.setattr(net.scheduler_core,"save_queue",save)
    assert net.rearm_one(ep,20)["reason"]=="DUPLICATE_UPSTREAM_COST_RISK_ACK_REQUIRED"
    assert row["status"]=="external_blocked"
    result=net.rearm_one(ep,20,acknowledged=True)
    assert result["status"]=="PASS"
    assert result["queued_for_attempt_index"]==2
    assert result["provider_calls"]==result["new_attempts_reserved"]==0
    assert row["status"]=="queued"
    assert row["attempts"]==0
    assert row["native_network_duplicate_billing_risk_ack"] is True
    assert row[net.RECOVERY_KEY]==1
    assert row["native_network_terminal_receipt_sha256"]=="a"*64
    assert row["native_network_original_log_path"]=="meta/image-workers/20-original.jsonl"
    assert "execution" not in row and "technical_failure_code" not in row
    commit.assert_called_once()
    save.assert_called_once()
    assert net.rearm_one(ep,20,acknowledged=True)["status"]=="BLOCKED"
    save.assert_called_once()


def test_only_frames_20_27_may_enter_ep14_billing_risk_rearm(ep):
    assert net._ep14_tls_scope(ep,20)
    assert net._ep14_tls_scope(ep,27)
    assert not net._ep14_tls_scope(ep,9)
    assert not net._ep14_tls_scope(ep,29)
    assert not net._ep14_tls_scope(ep,48)
    assert not net._ep14_tls_scope(ep.parent/"13_失物归还的那扇门",20)


def test_second_attempt_worker_requires_ack_with_sha_and_mysql(ep,monkeypatch):
    row=_row()
    row.update({
        "status":"queued",
        net.RECOVERY_KEY:1,
        "native_network_terminal_receipt_sha256":"a"*64,
        "native_network_terminal_original_log_sha256":"b"*64,
        "native_network_duplicate_billing_risk_ack":True,
        "native_network_original_log_path":"meta/image-workers/20-original.jsonl",
    })
    raw=ep/"meta/image-workers/20-original.jsonl"
    raw.parent.mkdir(parents=True)
    raw.write_bytes(b"original native TLS terminal byte evidence")
    proof_sha=hashlib.sha256(raw.read_bytes()).hexdigest()
    metadata=net.EP14_TLS_TERMINAL[20].copy()
    monkeypatch.setitem(net.EP14_TLS_TERMINAL,20,{
        **metadata,"log_sha256":proof_sha,"receipt_sha256":"a"*64,
        "request_id":"r"*32})
    row["native_network_terminal_only_log_sha256"]=proof_sha
    row["native_network_terminal_original_log_sha256"]=proof_sha
    monkeypatch.setattr(net,"_ep14_tls_terminal_log",lambda b,f:b==raw.read_bytes() and f==20)
    monkeypatch.setattr(net,"_matched_receipt",lambda b:{
        "request_id":"r"*32,"receipt_sha256":"a"*64,"log_sha256":proof_sha})
    monkeypatch.setattr(net.authority,"load_asset_state",lambda *_:{
        "attempts_consumed":1,"active_attempt_index":None,"fencing_counter":1})
    monkeypatch.setattr(net.authority,"load_attempt",lambda _ep,_key,index:{
        "status":"FAILED_AFTER_DISPATCH","failure_class":net.FAILURE_CLASS,
        "provider":"codex_subscription","runner_request_id":"r"*32,
        "generation_key":"stable-key","result_ref":None,
    } if index==1 else None)
    monkeypatch.setattr(net.authority,"stable_generation_key",lambda *_:"stable-key")
    class Conn:
        def query_one(self,*_):
            return {"STATUS":"FAILED_AFTER_DISPATCH","FENCING_TOKEN":1,
                    "GENERATION_KEY":"stable-key",
                    "CONTEXT":json.dumps({
                        "scope":"batch","queue_item_id":"original-network",
                        "runner_request_id":"r"*32,
                        "network_failure_runner_receipt_sha256":"a"*64,
                        "network_failure_original_log_sha256":proof_sha,
                        "network_failure_original_transaction_id":"old-transaction",
                        "frame_contract_sha256":"c"*64,
                        "prompt_package_sha256":"d"*64,
                        "upstream_billing_outcome_unverified":True,
                    })}
        def close(self):pass
    monkeypatch.setattr(net.authority,"_connect",lambda:Conn())
    assert net.remaining_second_attempt(ep,row)
    # A new Attempt #2 worker log coexists; never invalidate immutable #1.
    (raw.parent/"20-second-worker.jsonl").write_bytes(b"new thread")
    assert net.remaining_second_attempt(ep,row)
    tampered=dict(row,native_network_duplicate_billing_risk_ack=False)
    assert not net.remaining_second_attempt(ep,tampered)
    tampered=dict(row,native_network_terminal_original_log_sha256="0"*64)
    assert not net.remaining_second_attempt(ep,tampered)
    tampered=dict(row,frame=29)
    assert not net.remaining_second_attempt(ep,tampered)
    monkeypatch.setattr(net.authority,"load_attempt",lambda _ep,_key,index:{"status":"SUCCEEDED"} if index==2 else {})
    assert not net.remaining_second_attempt(ep,row)


def test_rc24_probe_denies_unmodified_production_and_foreign_episodes(ep):
    assert retry.verify_rearmed(ep)["status"]=="BLOCKED"
    assert retry.verify_rearmed(ep.parent/"other")["status"]=="BLOCKED"



def test_rc24_proof_only_after_exact_two_acks_and_safety_frames_preserved(ep,monkeypatch):
    import image_scheduler
    logs=ep/"meta/runtime/driver-logs";logs.mkdir(parents=True)
    old_log=logs/"original-driver.log";old_log.write_bytes(b"original rc24\n")
    d={"driver_state":"EXITED","liveness":"DEAD","pid":0,"exit_code":"24",
       "record":{"log":str(old_log)}}
    monkeypatch.setattr(retry.runtime_driver,"status",lambda *_:d)
    monkeypatch.setattr(retry.exit_remediation,"canonical_sha",lambda *_:"driver-sha")
    monkeypatch.setattr(retry,"OLD_DRIVER_SHA","driver-sha")
    monkeypatch.setattr(retry,"OLD_LOG_SHA",hashlib.sha256(old_log.read_bytes()).hexdigest())
    batch=[{"id":f"frame-{f}","frame":f,"scope":"batch",
            "status":("queued" if f in (20,27) else
                      "external_blocked" if f in (9,29,48) else "generated")}
           for f in range(1,49) if f not in (1,5,45,47)]
    for x in batch:
        if x["frame"] in (9,29,48):
            x.update({"no_automatic_original_prompt_retry":True,
                      "requires_content_revision":True,
                      "provider_safety_refusal_receipt_sha256":"f"*64})
    queue={"items":batch}
    monkeypatch.setattr(retry.scheduler_core,"load_queue",lambda *_:queue)
    monkeypatch.setattr(retry.attempts,"load_asset_state",
                        lambda *_:{"attempts_consumed":1,"active_attempt_index":None})
    monkeypatch.setattr(retry.attempts,"load_attempt",lambda _ep,_key,i:
                        {"status":"FAILED_AFTER_DISPATCH",
                         "failure_class":"IMAGE_PROVIDER_SAFETY_REJECTED"} if i==1 else None)
    good=Mock(return_value=True)
    monkeypatch.setattr(retry.network,"remaining_second_attempt",good)
    monkeypatch.setattr(image_scheduler,"ready_items",
                        lambda ep,q:([x for x in q["items"] if x["status"]=="queued"],[]))
    result=retry.verify_rearmed(ep)
    assert result["status"]=="EP14_RC24_F020_F027_ATTEMPT2_AUTHORIZED_REENTRY"
    assert result["frames"]==[20,27]
    assert result["safety_refusals_still_blocked"]==[9,29,48]
    assert result["model_calls"]==result["sql_writes"]==0
    assert good.call_count==2
    batch[0]["status"]="queued"
    assert retry.verify_rearmed(ep)["status"]=="BLOCKED"
    batch[0]["status"]="generated"
    good.return_value=False
    assert retry.verify_rearmed(ep)["status"]=="BLOCKED"
    good.return_value=True
    d["record"]["log"]=str(ep/"different-driver.log")
    assert retry.verify_rearmed(ep)["status"]=="BLOCKED"
