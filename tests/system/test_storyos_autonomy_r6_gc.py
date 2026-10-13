"""R6 slot1: refuse invalid retirement ages and stale, mutated branch heads."""
from pathlib import Path
import math
import sys
import pytest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
import storyos_retired_worktree_gc as gc


def candidate(**overrides):
    row=dict(path=ROOT/".worktrees"/"retired",branch="feature/storyos-retired",
             registered=True,is_primary=False,merged_local=True,
             merged_remote=True,clean=True,age_hours=101,
             process_verification="CLEAR",branch_checked_out_elsewhere=False)
    row.update(overrides)
    return row


@pytest.mark.parametrize("value",[float("inf"), float("-inf"), float("nan"), True])
def test_age_must_be_finite_number_not_unbounded(value):
    assert gc.classify(candidate(age_hours=value))["eligible"] is False


def test_branch_plan_snapshot_ignores_checked_out_old_branch(monkeypatch):
    import time
    old=int(time.time())-5*24*3600
    def fake_git(*args,**kwargs):
        if args[0]=="for-each-ref":
            return 0,f"feature/storyos-merged\t{old}"
        raise AssertionError(args)
    monkeypatch.setattr(gc,"_git",fake_git)
    monkeypatch.setattr(gc,"_worktrees",lambda:[{"branch":"feature/storyos-merged"}])
    assert gc.branch_plan()["eligible"]==[]


def test_gc_apply_refuses_branch_moved_between_pins(monkeypatch):
    """A branch that changed SHA since the first plan must not be deleted."""
    monkeypatch.setattr(gc,"branch_plan",lambda:{"status":"DRY_RUN","eligible":["fix/storyos-retired"]})
    responses=iter([(0,"a"*40),(0,"b"*40)])
    events=[]
    def git(*args,**kw):
        events.append(args)
        if args[0]=="rev-parse":return next(responses)
        if args[0]=="branch":pytest.fail("deleted updated branch")
        raise AssertionError(args)
    monkeypatch.setattr(gc,"_git",git)
    result=gc.apply_branches(acknowledged=True,max_count=1)
    assert result["deleted_count"]==0
    assert not any(x[0]=="branch" for x in events)
