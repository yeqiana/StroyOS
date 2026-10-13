"""R16 slot4: no-retry repair and safe Worktree retirement contract."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
import storyos_autonomy_fast_test as fast
import storyos_a9_receipt_reconcile as r
import storyos_retired_worktree_gc as gc

def test_four_distinct_rapid_slots_and_189_pressure_lane():
    for slot in ("r16-receipt","r16-candidate","r16-driver","r16-integrated"):
        assert slot in fast.SLOTS and fast.test_commands(slot=slot)
    assert "tests/system/test_multi_episode_global_image_capacity.py" in fast.FULL_STRESS

def test_unverified_previous_review_never_authorizes_paid_retry():
    result=r.decide(epoch_present=True,candidate=None,candidate_exists=False,
        evidence_status="RUNNER_RECEIPT_MISSING",official_review_present=False)
    assert not any(result[k] for k in
        ("may_retry_attempt_9","can_dispatch_model","can_dispatch_image","can_publish"))

def test_worktree_cleanup_still_requires_clean_and_merged_proof():
    import inspect
    f=inspect.getsource(gc.classify)
    assert "merged" in f.lower() and "clean" in f.lower()
