"""R5 slot 1: retirement must fail closed and never delete active/unmerged content."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
import storyos_retired_worktree_gc as gc

def case(**kw):
    data={"path":ROOT/".worktrees"/"old", "branch":"feature/storyos-old",
          "is_primary":False,"merged_local":True,"merged_remote":True,
          "clean":True,"age_hours":100,"process_verification":"CLEAR",
          "branch_checked_out_elsewhere":False,"registered":True}
    data.update(kw)
    return data

def test_clean_merged_old_registered_worktree_eligible():
    assert gc.classify(case())["eligible"] is True

def test_unknown_process_unmerged_dirty_and_recent_fail_closed():
    for change in ({"process_verification":"UNKNOWN"},{"process_verification":"ACTIVE"},
                   {"merged_local":False},{"merged_remote":False},
                   {"clean":False},{"age_hours":1},{"branch_checked_out_elsewhere":True},
                   {"registered":False},{"is_primary":True},
                   {"branch":"story-platform-v3-rever"},
                   {"branch":"archive/important"}):
        assert not gc.classify(case(**change))["eligible"]

def test_paths_must_remain_inside_approved_retirement_roots():
    for p in (ROOT/"episodes"/"00_独立篇"/"p",
              ROOT.parent.parent/"not-ours",
              ROOT/".worktrees"/".."/"episodes"):
        assert not gc.classify(case(path=p))["eligible"]

def test_only_explicit_apply_may_remove(monkeypatch):
    history=[]
    monkeypatch.setattr(gc,"remove_retired",lambda *a:history.append(1))
    report=gc.execute_plan([case()],apply=False,acknowledged=False)
    assert report["status"]=="DRY_RUN" and not history
    report=gc.execute_plan([case()],apply=True,acknowledged=False)
    assert report["status"]=="ACK_REQUIRED" and not history

def test_prunable_branches_must_be_merged_not_archives_and_not_checked_out():
    assert gc.safe_branch("feature/storyos-clean",merged=True,checked_out=False)
    for branch,merged,checked in (
        ("archive/storyos-important",True,False),
        ("story-platform-v3-rever",True,False),
        ("feature/storyos-other",False,False),
        ("feature/storyos-active",True,True),
        ("release/hotfix",True,False)):
        assert not gc.safe_branch(branch,merged=merged,checked_out=checked)

def test_branch_delete_requires_ack_and_proof(monkeypatch):
    removed=[]
    monkeypatch.setattr(gc,"_git",lambda *a,**k:removed.append(a) or (0,""))
    assert gc.apply_branches(acknowledged=False)["status"]=="ACK_REQUIRED"
    assert not removed

def test_branch_plan_skips_checked_out_and_recent_refs(monkeypatch):
    old=int(__import__("time").time())-100*3600
    young=int(__import__("time").time())-3600
    def fake_git(*args,**kwargs):
        if args[0]=="for-each-ref":
            return 0, f"feature/storyos-unused\t{old}\nfix/storyos-new\t{young}\narchive/storyos-safe\t{old}"
        raise AssertionError(args)
    monkeypatch.setattr(gc,"_git",fake_git)
    monkeypatch.setattr(gc,"_worktrees",lambda:[{"branch":"fix/storyos-new"}])
    assert gc.branch_plan()["eligible"]==["feature/storyos-unused"]
