"""R5 slot4: four independent quick tests plus integrated failure injection."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
import storyos_autonomy_fast_test as quick

def test_all_r5_slot_names_and_final_suite():
    for slot in ("retirement","provider-receipt","native-login","r5-integrated"):
        assert slot in quick.SLOTS
        assert quick.test_commands(slot=slot)
    stress=quick.test_commands(slot="all",stress=True)
    assert "test_multi_episode_global_image_capacity.py" in " ".join(stress[-1])

def test_all_four_slots_fail_closed_on_unsafe_control_paths(monkeypatch,tmp_path):
    from contextlib import nullcontext
    import storyos_retired_worktree_gc as gc
    import storyos_autonomy_native_ready as native
    SYSTEM=ROOT/"episodes"/"_system"
    sys.path.insert(0,str(SYSTEM))
    import image_generation_gateway as gateway
    from generation_attempt_authority import AttemptDenied

    # Merely merged is not permission to remove a dirty checkout.
    candidate={"path":ROOT/".worktrees"/"old","branch":"feature/storyos-old",
               "merged_local":True,"merged_remote":True,"registered":True,
               "clean":False,"is_primary":False,"age_hours":500,
               "process_verification":"CLEAR","branch_checked_out_elsewhere":False}
    assert gc.classify(candidate)["eligible"] is False
    assert gc.execute_plan([candidate],apply=False,acknowledged=False)["status"]=="DRY_RUN"

    # The native authenticated bridge never grants paid image entitlement.
    ready=native.summarize({"status":"CLI_FLAGS_SUPPORTED"},{"status":"BRIDGE_AUTH_PRESENT"})
    assert ready["status"]=="NATIVE_AUTH_CONTEXT_READY"
    assert ready["may_start_paid_production"] is False

    # Provider completed, but the receipt is missing: mark UNKNOWN not FAILED.
    evidence=[]
    lease={"episode_id":"ep","logical_asset_key":"ep/01","fencing_token":5}
    monkeypatch.setattr(gateway.global_image_capacity,"image_permits",lambda *_:nullcontext())
    monkeypatch.setattr(gateway.authority,"commit_dispatch",lambda *a,**k:dict(lease))
    monkeypatch.setattr(gateway.authority,"validate_committed_dispatch",lambda *a,**k:True)
    monkeypatch.setattr(gateway.authority,"mark_observed",
                        lambda *a:(_ for _ in ()).throw(OSError("receipt missing")))
    monkeypatch.setattr(gateway.authority,"mark_outcome_unknown",
                        lambda *a,**kw:evidence.append("UNKNOWN"))
    monkeypatch.setattr(gateway.authority,"fail_after_dispatch",
                        lambda *a,**kw:evidence.append("FAILED"))
    import pytest
    with pytest.raises(OSError):
        gateway.provider_generate(tmp_path,lease,5,"fake",
                                  lambda:evidence.append("PROVIDER_RETURNED") or "ok")
    assert evidence==["PROVIDER_RETURNED","UNKNOWN"]
    assert lease["_phase"]=="TERMINAL"
