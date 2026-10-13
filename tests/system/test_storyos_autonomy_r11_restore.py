"""R11 slot2: never mutate when authorization and current evidence differ."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
import storyos_relocation_apply as apply
import storyos_autonomy_production_probe as prod
import storyos_relocated_review_recovery as inspect

def test_no_run_without_explicit_ack(monkeypatch):
    import pytest
    assert inspect.main(["episodes/15_天界生活日常/01_天界普通女生的一天","--apply"])==2

def test_restore_rejects_feature_worktree_without_any_mutation(tmp_path,monkeypatch):
    (tmp_path/".git").write_text("gitdir: elsewhere")
    ep=tmp_path/"episodes"/"fixture"
    ep.mkdir(parents=True)
    monkeypatch.setattr(apply.native,"ROOT",tmp_path)
    monkeypatch.setattr(apply.native,"canonical_episode",lambda _:ep)
    result=apply.restore("synthetic",{"can_recover_review":True,"review_sha256":"old"},
        lambda _: (_ for _ in ()).throw(AssertionError("worktree must not inspect")))
    assert result["status"]=="NOT_PRIMARY_CHECKOUT"
    assert not result["mysql_writes_verified"]


def test_missing_or_drifted_plan_refuses_before_driver(tmp_path,monkeypatch):
    import subprocess
    (tmp_path/".git").mkdir()
    ep=tmp_path/"episodes"/"fixture"
    ep.mkdir(parents=True)
    monkeypatch.setattr(apply.native,"ROOT",tmp_path)
    monkeypatch.setattr(apply.native,"canonical_episode",lambda _:ep)
    monkeypatch.setattr(apply.subprocess,"run",lambda *a,**kw:
        subprocess.CompletedProcess(a,0,stdout=str(tmp_path)))
    result=apply.restore("synthetic",{"can_recover_review":True,"review_sha256":"old"},
                         lambda _:{"can_recover_review":True,"review_sha256":"new"})
    assert result["status"]=="EVIDENCE_CHANGED_BEFORE_APPLY"
    assert not result["mysql_writes_verified"]

def test_paid_attempt_unknown_remains_nonretryable():
    result=prod.assess({"driver_state":"RUNNING","liveness":"ALIVE"},
        {"status":"ATTEMPT_HISTORY_READ_ONLY","active_attempt_assets":[],
         "outcome_unknown_assets":["frame01"],"attempt_rows":1},
        {"status":"STAGE_ELIGIBLE","source":"mysql","stage":"STORYBOARD_LOCKED"})
    assert result["status"]=="PAID_ATTEMPT_RECONCILIATION_REQUIRED"
    assert result["may_retry_paid_attempt"] is False
