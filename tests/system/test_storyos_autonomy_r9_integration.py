"""R9 Slot 4: real-production safety and GC regressed after each change."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
import storyos_autonomy_fast_test as fast
import storyos_retired_worktree_gc as gc
import storyos_autonomy_production_probe as p

def test_four_slots_have_fast_tests_and_complete_stress():
    for s in ("real-canary","watchdog-user","mysql-receipt","r9-integrated"):
        assert s in fast.SLOTS and fast.test_commands(slot=s)
    commands=fast.test_commands(slot="all",stress=True)
    assert "test_multi_episode_global_image_capacity.py" in " ".join(commands[-1])
    assert "test_storyos_autonomy_r9_probe.py" in " ".join(" ".join(c) for c in commands)

def test_running_driver_does_not_make_dirty_worktree_gc_eligible():
    candidate={"path":ROOT/".worktrees"/"active","branch":"fix/storyos-old",
               "registered":True,"is_primary":False,"merged_local":True,
               "merged_remote":True,"clean":False,"age_hours":100,
               "process_verification":"ACTIVE","branch_checked_out_elsewhere":False}
    assert not gc.classify(candidate)["eligible"]
    x=p.assess({"driver_state":"RUNNING","liveness":"ALIVE","heartbeat_status":"RETRY_WAIT"},
               {"status":"ATTEMPT_HISTORY_READ_ONLY","active_attempt_assets":[],"outcome_unknown_assets":[]},
               {"status":"STAGE_ELIGIBLE","stage":"STORYBOARD_LOCKED","source":"mysql"})
    assert x["may_retry_paid_attempt"] is False
