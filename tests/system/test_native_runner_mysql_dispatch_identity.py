"""Exact native Runner request identity must persist in MySQL at dispatch commit."""
from __future__ import annotations
import json
import sys
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
import pytest
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/"episodes/_system")]
import generation_attempt_authority as a

class FakeConnection:
    def __init__(self,prior=None):
        self.row={"CONTEXT":json.dumps({"scope":"batch","frame_contract_sha256":"a"*64,
                                         **({"runner_request_id":prior} if prior else {})}),
                  "STATUS":"RESERVED","LEASE_EXPIRES_AT":a._utcnow()+timedelta(minutes=3)}
        self.state={"ATTEMPTS_CONSUMED":0}
        self.updates=[]
    @contextmanager
    def transaction(self):
        yield
    def execute(self,sql,args):
        self.updates.append((sql,args))
        return 1
    def close(self):pass

def execute_request(rid,prior=None):
    db=FakeConnection(prior)
    lease={"episode_id":"episode","logical_asset_key":"episode/frame-05",
           "attempt_index":1,"fencing_token":1,
           "generation_key":"ga1-"+"1"*48+"-a1",
           "generation_context":{"scope":"batch"},
           "runner_request_id":rid}
    def invoke():
        with patch.object(a,"_connect",return_value=db),patch.object(a,"_locked_lease",return_value=(db.state,db.row)),patch.object(a,"_telemetry"):
            return a.commit_dispatch(Path("."),lease,1,provider="codex_subscription")
    return db,invoke

def test_dispatch_commits_runner_identity_in_exact_mysql_attempt():
    db,invoke=execute_request("a"*32)
    result=invoke()
    assert result["status"]=="DISPATCH_COMMITTED"
    sql,args=db.updates[0]
    assert "CONTEXT=%s" in sql and "STATUS='DISPATCH_COMMITTED'" in sql
    recorded=json.loads(args[2])
    assert recorded["runner_request_id"]=="a"*32
    assert recorded["frame_contract_sha256"]=="a"*64

def test_wrong_or_conflicting_runner_identity_rejected_before_provider_dispatch():
    for value in ("../wrong","a"*31,"not-a-real-request"):
        db,invoke=execute_request(value)
        with pytest.raises(a.AttemptDenied,match="RUNNER_REQUEST_ID"):
            invoke()
        assert not db.updates
    db,invoke=execute_request("b"*32,prior="a"*32)
    with pytest.raises(a.AttemptDenied,match="RUNNER_REQUEST_ID"):
        invoke()
    assert not db.updates

def test_unbound_non_image_dispatch_stays_backward_compatible():
    db,invoke=execute_request(None)
    result=invoke()
    assert result["attempt_consumed"] is True
    assert "CONTEXT=%s" not in db.updates[0][0]

def test_load_attempt_exposes_bound_runner_id_from_mysql_context():
    class LoadDB:
        def query_one(self,*args):
            return {"EPISODE_ID":"episode","LOGICAL_ASSET_KEY":"episode/frame-05",
                    "ATTEMPT_INDEX":1,"STATUS":"OUTCOME_UNKNOWN",
                    "CONTEXT":json.dumps({"scope":"batch","runner_request_id":"a"*32})}
        def close(self):pass
    with patch.object(a,"_connect",return_value=LoadDB()),patch.object(a,"_episode_id",return_value="episode"):
        row=a.load_attempt(Path("."),"episode/frame-05",1)
    assert row["runner_request_id"]=="a"*32
    assert row["status"]=="OUTCOME_UNKNOWN"