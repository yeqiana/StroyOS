"""R6 slot4: each slot has a quick test, full stress preserves five permits."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
import storyos_autonomy_fast_test as quick

def test_every_r6_slot_has_dedicated_fast_suite():
    for slot in ("gc-fence","provider-timeout","codex-frame01","r6-e2e"):
        assert slot in quick.SLOTS
        assert quick.test_commands(slot=slot)

def test_r6_integrated_suite_keeps_prior_capacity_recovery():
    cmds=quick.test_commands(slot="all",stress=True)
    text=" ".join(" ".join(c) for c in cmds)
    for essential in ("test_storyos_autonomy_r6_gc.py",
                      "test_storyos_autonomy_r6_receipt.py",
                      "test_storyos_autonomy_r6_canary.py",
                      "test_runtime_recovery.py",
                      "test_multi_episode_global_image_capacity.py"):
        assert essential in text

def test_combined_gc_cli_and_paid_timeout_are_fail_closed(monkeypatch,tmp_path):
    from contextlib import nullcontext
    from types import SimpleNamespace
    import storyos_retired_worktree_gc as gc
    import storyos_autonomy_native_ready as ready
    SYSTEM=ROOT/"episodes"/"_system"
    if str(SYSTEM) not in sys.path:
        sys.path.insert(0,str(SYSTEM))
    import image_generation_gateway as gateway

    bad={"path":ROOT/".worktrees"/"old","branch":"feature/storyos-old",
         "registered":True,"is_primary":False,"merged_local":True,"merged_remote":True,
         "clean":False,"age_hours":200,"process_verification":"CLEAR",
         "branch_checked_out_elsewhere":False}
    assert gc.classify(bad)["eligible"] is False
    auth=ready.summarize({"status":"CLI_FLAGS_SUPPORTED"},{"status":"BRIDGE_AUTH_PRESENT"})
    assert auth["may_start_paid_production"] is False

    events=[]
    lease={"episode_id":"ep","logical_asset_key":"ep/frame-01","fencing_token":3}
    monkeypatch.setattr(gateway.global_image_capacity,"image_permits",lambda *_:nullcontext())
    monkeypatch.setattr(gateway.authority,"commit_dispatch",lambda *a,**kw:dict(lease))
    monkeypatch.setattr(gateway.authority,"validate_committed_dispatch",lambda *a,**kw:True)
    monkeypatch.setattr(gateway.authority,"mark_outcome_unknown",
                        lambda *a,**kw:events.append("OUTCOME_UNKNOWN"))
    monkeypatch.setattr(gateway.authority,"fail_after_dispatch",
                        lambda *a,**kw:events.append("FAILED"))
    import pytest
    with pytest.raises(TimeoutError):
        gateway.provider_generate(tmp_path,lease,3,"native",
            lambda:(_ for _ in ()).throw(TimeoutError("no provider receipt")))
    assert events==["OUTCOME_UNKNOWN"]
    assert lease["_phase"]=="TERMINAL"
