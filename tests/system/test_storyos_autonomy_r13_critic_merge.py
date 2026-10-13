"""R13 slot1: bounded Concept A3/A4/A5 and migrated rubric A9 are exclusive."""
from pathlib import Path
import inspect
import sys
import types
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"episodes"/"_system"))
import story_review
import story_review_rubric_migration as migration

EP=ROOT/"episodes/15_天界生活日常/01_天界普通女生的一天"

def test_independent_bounded_review_scopes_coexist_in_signature():
    params=inspect.signature(story_review.run_critic).parameters
    for option in (
        "direct_user_concept_selection_source_revision",
        "direct_user_concept_selection_source_repair_after_fail",
        "direct_user_concept_selection_source_repair_after_fail_a5",
        "direct_user_migrated_rubric"):
        assert option in params
    assert migration.REVIEW_SCOPE=="MIGRATED_EPISODE_RUBRIC_REVALIDATION"

@pytest.mark.parametrize("flag",[
    "direct_user_concept_selection_source_revision",
    "direct_user_concept_selection_source_repair_after_fail",
    "direct_user_concept_selection_source_repair_after_fail_a5",
])
def test_concept_continuation_cannot_alias_a9_migrated_review(monkeypatch,flag):
    monkeypatch.setitem(sys.modules,"storyos_autonomy_r12_critic_preflight",
        types.SimpleNamespace(inspect=lambda _:{"may_start_new_text_review":True}))
    monkeypatch.setattr(migration,"authorize",
        lambda *a,**k: (_ for _ in ()).throw(AssertionError("review token allocated")))
    kwargs={"attempt":9,"codex_raw":"codex","timeout":5,
            "direct_user_migrated_rubric":True,flag:True}
    with pytest.raises(RuntimeError):
        story_review.run_critic(EP,**kwargs)

def test_rubric_only_a9_has_no_legacy_codex_provenance_alias():
    old=migration.read_legacy_review(EP)
    assert (old.get("critic_provenance") or {}).get("attempt")==2
    assert migration.validate_epoch(EP,old.get("critic_provenance") or {}) is False
