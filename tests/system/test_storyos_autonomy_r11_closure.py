"""R11 fourth-slot GC and all-fast stress registration."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
import storyos_autonomy_fast_test as fast
import storyos_retired_worktree_gc as gc

def test_r11_slots_are_registered():
    for slot in ("review-relocation","review-restore-guard","frame01-after-review","r11-closure"):
        assert slot in fast.SLOTS and fast.test_commands(slot=slot)
    stress=fast.test_commands(slot="all",stress=True)
    assert "test_multi_episode_global_image_capacity.py" in " ".join(stress[-1])

def test_gc_does_not_remove_live_unmerged_worktree():
    row=dict(path=ROOT/".worktrees"/"active",branch="fix/storyos-old",
             registered=True,is_primary=False,merged_local=False,
             merged_remote=True,clean=True,age_hours=100,
             process_verification="ACTIVE",branch_checked_out_elsewhere=False)
    assert gc.classify(row)["eligible"] is False
