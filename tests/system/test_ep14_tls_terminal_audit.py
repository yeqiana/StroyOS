"""Episode14 native TLS terminal audit; zero paid generation and strict immutable evidence."""
from __future__ import annotations
import hashlib
import json
import sys
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'episodes/_system'))
import native_network_failure_rearm as recovery


@pytest.fixture
def ep(tmp_path, monkeypatch):
    path=tmp_path/'episodes'/'00_独立篇'/'14_深渊疗愈所_第一集_净土生命还原'
    path.mkdir(parents=True)
    monkeypatch.setattr(recovery,'ROOT',tmp_path)
    return path


def test_ep14_scoped_only_to_original_network_frames(ep):
    assert [f for f in range(1,49) if recovery._ep14_tls_scope(ep,f)]==[20,27]
    assert not recovery._ep14_tls_scope(ep.parent/'13_失物归还的那扇门',20)


def _native_tls_fixture():
    events=[
        'WARNING: proceeding, even though we could not create PATH aliases: mock',
        '{"type":"thread.started"}',
        '{"type":"turn.started"}',
        '2026-10-26T05:23:34Z ERROR codex_core::tools::router: error=image generation failed: connection failed: error sending request',
    ]
    events += [
        '2026-10-26T05:23:35Z ERROR codex_api::endpoint::responses_websocket: failed to connect to websocket: IO error: tls handshake eof, url: wss://chatgpt.com/backend-api/codex/responses'
        for _ in range(6)
    ]
    events.extend([
        '{"type":"error","message":"Reconnecting... waiting for network (Connection failed: error sending request)"}',
        '{"type":"item.completed","item":{"type":"agent_message","text":"Image generation failed because the connection could not be established."}}',
        '{"type":"turn.completed"}',
    ])
    return ('\n'.join(events)+'\n').encode()


def test_tls_terminal_exact_log_sha_and_negative_cases(monkeypatch):
    original=recovery.EP14_TLS_TERMINAL[20]
    good=_native_tls_fixture()
    monkeypatch.setitem(recovery.EP14_TLS_TERMINAL,20,{**original,'log_sha256':hashlib.sha256(good).hexdigest()})
    assert recovery._ep14_tls_terminal_log(good,20)
    assert not recovery._ep14_tls_terminal_log(good,27)
    assert not recovery._ep14_tls_terminal_log(good+b'forged extra event\n',20)
    forged=good.replace(b'connection could not be established',b'image saved')
    monkeypatch.setitem(recovery.EP14_TLS_TERMINAL,20,{**original,'log_sha256':hashlib.sha256(forged).hexdigest()})
    assert not recovery._ep14_tls_terminal_log(forged,20)


def test_terminal_only_requires_dead_driver_and_no_queue_release(ep,monkeypatch):
    row={'frame':20,'scope':'batch','status':'external_blocked',
         'technical_failure_code':'IMAGE_BACKEND_ERROR',
         'attempts':2}
    original=dict(row)
    q={'items':[row]}
    proof={'request_id':'a'*32,'receipt_sha256':'b'*64,'log_sha256':'c'*64}
    driver={'driver_state':'EXITED','liveness':'DEAD','pid':0}
    import runtime_driver
    monkeypatch.setattr(runtime_driver,'status',lambda *_:driver)
    monkeypatch.setattr(recovery.scheduler_core,'queue_transaction',lambda *_:nullcontext())
    monkeypatch.setattr(recovery.scheduler_core,'load_queue',lambda *_:q)
    monkeypatch.setattr(recovery,'inspect',lambda *_:proof)
    terminal=Mock()
    saved=Mock()
    monkeypatch.setattr(recovery,'_commit_terminal',terminal)
    monkeypatch.setattr(recovery.scheduler_core,'save_queue',saved)
    result=recovery.reconcile_ep14_terminal_only(ep,20)
    assert result['status']=='PASS'
    assert result['provider_calls']==result['attempts_reserved']==0
    assert result['upstream_billing_outcome_unverified'] is True
    assert row['status']==original['status']=='external_blocked'
    assert row['attempts']==original['attempts']==2
    assert 'native_network_terminal_rearm_count' not in row
    assert row['native_network_terminal_only_receipt_sha256']=='b'*64
    terminal.assert_called_once()
    saved.assert_called_once()
    assert recovery.reconcile_ep14_terminal_only(ep,20)['status']=='PASS'
    assert recovery.reconcile_ep14_terminal_only(ep,21)['status']=='BLOCKED'
    driver['liveness']='ALIVE'
    assert recovery.reconcile_ep14_terminal_only(ep,27)['reason']=='DRIVER_NOT_STOPPED'


def test_ep14_rearm_cannot_spend_second_attempt(ep):
    assert recovery.rearm_one(ep,20,acknowledged=True)=={
        'status':'BLOCKED','reason':'EP14_TERMINAL_AUDIT_ONLY_NO_PAID_REARM'}
