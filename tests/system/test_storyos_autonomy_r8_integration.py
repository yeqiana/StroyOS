"""R8 cleanup and integration fast tests are wired into the complete suite."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
import storyos_autonomy_fast_test as quick
import storyos_retired_worktree_gc as gc

def test_r8_slot_commands_and_stress_includes_old_suites():
    for slot in ("frame01-real","native-image-readiness","stage-drift","r8-integration"):
        assert slot in quick.SLOTS
        assert len(quick.test_commands(slot=slot))==1
    assert "test_multi_episode_global_image_capacity.py" in " ".join(
        quick.test_commands(slot="all",stress=True)[-1])

def test_retired_gc_requires_no_untracked_and_no_live_processes():
    info={"path":ROOT/".worktrees"/"retired","branch":"fix/storyos-retired",
          "registered":True,"is_primary":False,"merged_local":True,"merged_remote":True,
          "clean":True,"age_hours":90,"process_verification":"ACTIVE",
          "branch_checked_out_elsewhere":False}
    assert gc.classify(info)["eligible"] is False
    info["process_verification"]="CLEAR"
    info["clean"]=False
    assert gc.classify(info)["eligible"] is False
