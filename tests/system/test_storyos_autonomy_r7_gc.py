"""R7 slot1: delete only the exact verified Git ref, atomically."""
from pathlib import Path
import sys
import pytest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
import storyos_retired_worktree_gc as gc

def test_ref_delete_uses_expected_object_cas(monkeypatch):
    ref="fix/storyos-merged"
    sha="a"*40
    monkeypatch.setattr(gc,"branch_plan",lambda:{"status":"DRY_RUN","eligible":[ref]})
    monkeypatch.setattr(gc,"_worktrees",lambda:[])
    calls=[]
    def fake_git(*args,**kw):
        calls.append(args)
        if args[0]=="rev-parse":return 0,sha
        if args[0]=="update-ref":
            assert args==("update-ref","-d","refs/heads/"+ref,sha)
            return 0,""
        if args[0]=="branch":pytest.fail("nonatomic branch -d")
        raise AssertionError(args)
    monkeypatch.setattr(gc,"_git",fake_git)
    assert gc.apply_branches(acknowledged=True,max_count=1)["deleted_count"]==1
    assert any(x[0]=="update-ref" for x in calls)

def test_git_update_ref_concurrent_move_fails_safely(monkeypatch):
    ref="fix/storyos-merged"
    sha="a"*40
    monkeypatch.setattr(gc,"branch_plan",lambda:{"status":"DRY_RUN","eligible":[ref]})
    monkeypatch.setattr(gc,"_worktrees",lambda:[])
    calls=[]
    def fake_git(*args,**kw):
        calls.append(args)
        if args[0]=="rev-parse":return 0,sha
        if args[0]=="update-ref":return 1,""
        raise AssertionError(args)
    monkeypatch.setattr(gc,"_git",fake_git)
    assert gc.apply_branches(acknowledged=True,max_count=1)["deleted_count"]==0
    assert len([x for x in calls if x[0]=="update-ref"])==1

def test_ref_becoming_checked_out_during_cleanup_must_not_be_deleted(monkeypatch):
    target="fix/storyos-merged"
    monkeypatch.setattr(gc,"branch_plan",lambda:{"status":"DRY_RUN","eligible":[target]})
    monkeypatch.setattr(gc,"_worktrees",lambda:[{"branch":target}])
    calls=[]
    def fake_git(*args,**kwargs):
        calls.append(args)
        if args[0]=="rev-parse":return 0,"a"*40
        if args[0]=="update-ref":pytest.fail("worktree now owns this branch")
        raise AssertionError(args)
    monkeypatch.setattr(gc,"_git",fake_git)
    assert gc.apply_branches(acknowledged=True,max_count=1)["deleted_count"]==0
    assert not any(x[0]=="update-ref" for x in calls)
