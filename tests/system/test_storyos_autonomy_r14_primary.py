"""R14 slot 1: a feature worktree may not start even one paid text Critic."""
from pathlib import Path
import sys
import pytest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
sys.path.insert(0,str(ROOT/"episodes"/"_system"))
import story_review
import story_review_rubric_migration as migration
import storyos_autonomy_r12_critic_preflight as check

def test_current_isolated_worktree_cannot_issue_live_model_admission(tmp_path,monkeypatch):
    # Hermetic: the same test must pass in a feature Worktree and primary CI.
    (tmp_path/".git").write_text("gitdir: elsewhere")
    monkeypatch.setattr(check.native,"ROOT",tmp_path)
    monkeypatch.setattr(check.native,"native_environment",
        lambda: (_ for _ in ()).throw(AssertionError("credential read")))
    result=check.inspect("episodes/demo")
    assert result["status"]=="PRIMARY_CHECKOUT_REQUIRED"
    assert result["may_start_new_text_review"] is False
    assert result["can_dispatch_image"] is False
    assert result["sql_writes"]==result["model_calls"]==0

def test_paid_epoch_reservation_requires_primary_git_directory(tmp_path,monkeypatch):
    ep=tmp_path/"episodes"/"safe"
    ep.mkdir(parents=True)
    (tmp_path/".git").write_text("gitdir: elsewhere")
    monkeypatch.setattr(story_review,"ROOT",tmp_path)
    monkeypatch.setattr(migration,"plan",
        lambda ep: (_ for _ in ()).throw(AssertionError("paid evidence accessed")))
    with pytest.raises(RuntimeError,match="canonical primary checkout"):
        migration.authorize(ep,attempt=9,current_rubric_sha256="a"*64)
    assert not (ep/migration.EPOCH_REL).exists()

def test_outside_episode_primary_root_is_rejected(tmp_path,monkeypatch):
    (tmp_path/".git").mkdir()
    monkeypatch.setattr(story_review,"ROOT",tmp_path)
    with pytest.raises(RuntimeError,match="canonical primary checkout"):
        migration.authorize(ROOT,attempt=9,current_rubric_sha256="a"*64)
