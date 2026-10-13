"""R13 slot4: integration is part of all/stress, no mutation in GC plan."""
from pathlib import Path
import inspect
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
sys.path.insert(0,str(ROOT/"episodes"/"_system"))
import storyos_autonomy_fast_test as fast
import story_review
import storyos_retired_worktree_gc as gc

def test_each_r13_slot_has_a_fast_entry():
    for slot in ("r13-critic-merge","r13-attempt-history","r13-frame01","r13-integrated"):
        assert slot in fast.SLOTS and fast.test_commands(slot=slot)
    cmds=fast.test_commands(slot="all",stress=True)
    assert any("test_storyos_autonomy_r13_critic_merge.py" in x for row in cmds for x in row)
    assert any("test_multi_episode_global_image_capacity.py" in x for x in cmds[-1])

def test_integrated_review_has_both_verified_authority_validation_scopes():
    source=inspect.getsource(story_review.verify)
    assert "CONCEPT_SELECTION_SOURCE_REVISION" in source
    assert "CONCEPT_SELECTION_SOURCE_REPAIR_AFTER_FAIL_A5" in source
    assert "MIGRATED_EPISODE_RUBRIC_REVALIDATION" in source or "story_review_rubric_migration.REVIEW_SCOPE" in source

def test_gc_is_a_plan_not_force_delete():
    import inspect
    assert "merged" in inspect.getsource(gc.classify).lower()
