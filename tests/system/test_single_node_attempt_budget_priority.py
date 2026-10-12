"""Single-node Attempt budget denial stays stronger than absent legacy history.

No external MySQL: fake transaction confirms rejection occurs after transaction
cleanup and never treats over-cap legacy state as missing history.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sys
import pytest

ROOT=Path(__file__).resolve().parents[2]
SYSTEM=ROOT/"episodes"/"_system"
if str(SYSTEM) not in sys.path:sys.path.insert(0,str(SYSTEM))
import generation_attempt_authority as attempt
import production_revision_authority


class FakeSql:
    def __init__(self):self.sql=[];self.closed=False;self.committed=False
    def execute(self,statement,arguments):
        self.sql.append(statement)
        return 1
    @contextmanager
    def transaction(self):
        yield
        self.committed=True
    def query_one(self,sql,*args):
        raise AssertionError("over-budget must not inspect historical attempt")
    def close(self):self.closed=True


def test_over_limit_legacy_budget_does_not_query_missing_attempt(monkeypatch,tmp_path):
    fake=FakeSql()
    ep=tmp_path/"ep"
    ep.mkdir()
    namespace="test-only/episode"
    key=namespace+"/frame-01"
    cap=attempt.MAX_REAL_IMAGE_GENERATION_ATTEMPTS_PER_ASSET
    monkeypatch.setattr(attempt,"_episode_id",lambda _:namespace)
    monkeypatch.setattr(attempt,"_connect",lambda:fake)
    monkeypatch.setattr(attempt,"_telemetry",lambda *a,**kw:None)
    monkeypatch.setattr(attempt,"_row",lambda *a,**kw:{"ATTEMPTS_CONSUMED":cap,
                                                        "FENCING_COUNTER":cap,
                                                        "ACTIVE_ATTEMPT_INDEX":None})
    monkeypatch.setattr(attempt,"_expire_active",lambda con,ns,key,state,path:state)
    monkeypatch.setattr(
        attempt,"_previous_attempt_denial",
        lambda *a: (_ for _ in ()).throw(AssertionError("do not inspect absent legacy history")),
    )
    monkeypatch.setattr(production_revision_authority,"validate_dispatch_binding",
                        lambda *a,**kw:None)
    with pytest.raises(attempt.AttemptDenied,match="GENERATION_ATTEMPT_BUDGET_EXHAUSTED"):
        attempt._reserve_impl(ep,key,legacy_consumed=cap)
    assert fake.committed and fake.closed
    assert not any("INSERT INTO TB_GENERATION_ATTEMPT" in sql for sql in fake.sql)


def test_previous_unknown_still_denied_when_budget_available(monkeypatch,tmp_path):
    fake=FakeSql()
    ep=tmp_path/"ep"
    ep.mkdir()
    namespace="test-only/episode"
    key=namespace+"/frame-01"
    monkeypatch.setattr(attempt,"_episode_id",lambda _:namespace)
    monkeypatch.setattr(attempt,"_connect",lambda:fake)
    monkeypatch.setattr(attempt,"_telemetry",lambda *a,**kw:None)
    monkeypatch.setattr(attempt,"_row",lambda *a,**kw:{"ATTEMPTS_CONSUMED":1,
                                                        "FENCING_COUNTER":1,
                                                        "ACTIVE_ATTEMPT_INDEX":None})
    monkeypatch.setattr(attempt,"_expire_active",lambda con,ns,key,state,path:state)
    inspected=[]
    monkeypatch.setattr(attempt,"_previous_attempt_denial",
                        lambda *args:inspected.append(True) or
                        "GENERATION_ATTEMPT_OUTCOME_UNKNOWN_RECONCILIATION_REQUIRED")
    monkeypatch.setattr(production_revision_authority,"validate_dispatch_binding",
                        lambda *a,**kw:None)
    with pytest.raises(attempt.AttemptDenied,match="OUTCOME_UNKNOWN_RECONCILIATION_REQUIRED"):
        attempt._reserve_impl(ep,key)
    assert inspected==[True] and fake.committed and fake.closed
