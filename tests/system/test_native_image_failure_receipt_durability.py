"""Permanent regression for native image request provenance after worker failure.

No provider calls, no production MySQL/Redis, no Codex user credentials.
"""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/"episodes/_system")]
import production_recovery as rec


def item(tx="a"*32, attempt=1):
    return {"id":"ep13-frame05","frame":5,"attempts":attempt,"scope":"batch",
            "execution":{"transaction_id":tx,"phase":"WORKER_PENDING"}}


def lifecycle(tmp_path,item):
    ep=tmp_path/"ep"
    ep.mkdir(exist_ok=True)
    return ep,rec.lifecycle_path(ep,item)


def test_failure_keeps_trusted_user_runner_request_id(tmp_path):
    i=item()
    ep,path=lifecycle(tmp_path,i)
    with patch.object(rec,"_journal"):
        rec.write_lifecycle(ep,i,"BACKEND_INVOKED",runner_request_id="b"*32,worker_pid=123)
        failed=rec.write_lifecycle(ep,i,"FAILED",worker_pid=123,error="NETWORK_ERROR")
    assert failed["state"]=="FAILED"
    assert failed["runner_request_id"]=="b"*32
    assert rec._read(path)["runner_request_id"]=="b"*32


@pytest.mark.parametrize("state",["FAILED","BLOCKED","SUCCEEDED","UNKNOWN"])
def test_terminal_idempotent_and_no_retained_id_cross_transaction(tmp_path,state):
    i=item()
    ep,path=lifecycle(tmp_path,i)
    with patch.object(rec,"_journal"):
        rec.write_lifecycle(ep,i,"BACKEND_INVOKED",runner_request_id="c"*32)
        later=rec.write_lifecycle(ep,i,state)
        assert later["runner_request_id"]=="c"*32
        again=rec.write_lifecycle(ep,i,state)
        assert again["runner_request_id"]=="c"*32
        other=item("d"*32)
        new=rec.write_lifecycle(ep,other,"FAILED")
    assert new.get("runner_request_id") is None
    assert rec._read(path).get("runner_request_id") is None


def test_conflicting_request_id_same_transaction_is_not_silently_reassigned(tmp_path):
    i=item()
    ep,path=lifecycle(tmp_path,i)
    with patch.object(rec,"_journal"):
        original=rec.write_lifecycle(ep,i,"BACKEND_INVOKED",runner_request_id="b"*32)
        with pytest.raises(RuntimeError,match="RUNNER_REQUEST_ID"):
            rec.write_lifecycle(ep,i,"FAILED",runner_request_id="c"*32)
    assert rec._read(path)==original


def test_attempt_mismatch_must_not_reuse_old_request_id(tmp_path):
    i=item()
    ep,path=lifecycle(tmp_path,i)
    with patch.object(rec,"_journal"):
        rec.write_lifecycle(ep,i,"BACKEND_INVOKED",runner_request_id="b"*32)
        changed=item(attempt=2)
        updated=rec.write_lifecycle(ep,changed,"FAILED")
    assert updated.get("runner_request_id") is None


def test_old_generation_key_never_leaks_into_new_queue_transaction(tmp_path):
    i=item()
    ep,path=lifecycle(tmp_path,i)
    with patch.object(rec,"_journal"):
        rec.write_lifecycle(ep,i,"ATTEMPT_RESERVED",generation_key="ga1-old-a1")
        assert rec.write_lifecycle(ep,i,"BACKEND_INVOKED")["generation_key"]=="ga1-old-a1"
        fresh=rec.write_lifecycle(ep,item("f"*32),"WORKER_STARTED")
    assert fresh.get("generation_key") is None
    assert rec._read(path).get("generation_key") is None


def test_pre_backend_has_no_phantom_runner_receipt(tmp_path):
    i=item()
    ep,path=lifecycle(tmp_path,i)
    with patch.object(rec,"_journal"):
        v=rec.write_lifecycle(ep,i,"WORKER_STARTED",worker_pid=234)
    assert v.get("runner_request_id") is None
    assert rec._read(path).get("runner_request_id") is None


def test_invalid_explicit_runner_id_rejected(tmp_path):
    i=item()
    ep,path=lifecycle(tmp_path,i)
    with patch.object(rec,"_journal"):
        with pytest.raises(RuntimeError,match="RUNNER_REQUEST_ID"):
            rec.write_lifecycle(ep,i,"BACKEND_INVOKED",runner_request_id="../malicious")
    assert not path.exists()