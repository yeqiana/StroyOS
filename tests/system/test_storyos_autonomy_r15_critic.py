"""R15 slot2: paid migrated Critic is read-only even on Windows."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"episodes"/"_system"))
import story_review
import codex_critic_runner

def test_new_native_text_critic_will_not_degrade_into_windows_danger_full_access():
    assert story_review.critic_sandbox(migrated_rubric=True)=="read-only"
    assert codex_critic_runner.resolve_sandbox("read-only")=="read-only"

def test_historical_other_scope_does_not_change_legacy_contract():
    assert story_review.critic_sandbox(migrated_rubric=False)=="workspace-write"

def test_invalid_existing_candidate_blocks_before_one_shot_reservation(monkeypatch):
    from types import SimpleNamespace
    ep=ROOT/"episodes/15_天界生活日常/01_天界普通女生的一天"
    monkeypatch.setitem(sys.modules,"storyos_autonomy_r12_critic_preflight",
        SimpleNamespace(inspect=lambda ref:{"may_start_new_text_review":True}))
    monkeypatch.setattr(story_review,"resolve_codex",lambda raw:"codex.cmd")
    monkeypatch.setattr(story_review.story_review_rubric_migration,"authorize",
        lambda *a,**kw: (_ for _ in ()).throw(AssertionError("paid token burned")))
    # A candidate file from an unfinished independent review MUST be
    # reconciled; it must never be deleted to start a new paid call.
    monkeypatch.setattr(story_review.Path,"exists",lambda self:(
        True if self.name==Path(story_review.CANDIDATE_REL).name
        else self.is_file()))
    import pytest
    with pytest.raises(RuntimeError,match="candidate already exists"):
        story_review.run_critic(ep,attempt=9,codex_raw="codex",
                                direct_user_migrated_rubric=True,timeout=10)


def test_prepaid_attempt9_resolves_native_executable_before_reservation(monkeypatch):
    from types import SimpleNamespace
    ep=ROOT/"episodes/15_天界生活日常/01_天界普通女生的一天"
    monkeypatch.setitem(sys.modules,"storyos_autonomy_r12_critic_preflight",
        SimpleNamespace(inspect=lambda ref:{"may_start_new_text_review":True}))
    monkeypatch.setattr(story_review,"resolve_codex",
        lambda raw: (_ for _ in ()).throw(ValueError("NATIVE_CLI_UNAVAILABLE")))
    monkeypatch.setattr(story_review.story_review_rubric_migration,"authorize",
        lambda *a,**kw: (_ for _ in ()).throw(AssertionError("paid one-shot burned")))
    import pytest
    with pytest.raises(ValueError,match="NATIVE_CLI_UNAVAILABLE"):
        story_review.run_critic(ep,attempt=9,codex_raw="missing",
                                direct_user_migrated_rubric=True,timeout=10)
