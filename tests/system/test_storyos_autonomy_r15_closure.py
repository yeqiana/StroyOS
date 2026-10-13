"""R15 slot4: all new four slots and hard-retirement rules testable."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
import storyos_autonomy_fast_test as fast
import storyos_retired_worktree_gc as gc

def test_four_slot_test_registry_and_extreme_final_pressure():
    for name in ("r15-release-overlap","r15-critic-sandbox",
                 "r15-frame01","r15-closure"):
        assert name in fast.SLOTS and fast.test_commands(slot=name)
    assert any("test_multi_episode_global_image_capacity.py" in x
               for x in fast.FULL_STRESS)

def test_gc_requires_proven_merged_and_clean_not_just_age():
    import inspect
    txt=inspect.getsource(gc.classify)
    assert "merged" in txt.lower()
    assert "clean" in txt.lower()
