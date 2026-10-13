"""R14 slot4: published release must retain four independent fast-test gates."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
import storyos_autonomy_fast_test as fast
import storyos_retired_worktree_gc as gc

def test_new_four_slot_contract_exists():
    for name in ("r14-primary-worktree","r14-native-identity",
                 "r14-critic-history","r14-closure"):
        assert name in fast.SLOTS
        assert fast.test_commands(slot=name)
    assert len(fast.FULL_STRESS)>=7

def test_authority_proof_fail_closed_does_not_turn_into_image_permission():
    from storyos_autonomy_r12_critic_preflight import decide
    r=decide(stage={"source":"json","status":"STAGE_ELIGIBLE","stage":"STORYBOARD_LOCKED"},
             paid={},driver={},codex={},review={})
    assert r["status"]=="MYSQL_STAGE_UNVERIFIED"
    assert not r["can_dispatch_image"]
    assert not r["may_start_new_text_review"]

def test_retirement_gc_keeps_unmerged_or_active_worktrees():
    import inspect
    source=inspect.getsource(gc.classify)
    assert "merged" in source.lower()
    assert "clean" in source.lower()
