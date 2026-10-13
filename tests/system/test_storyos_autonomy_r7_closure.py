"""R7 slot4: complete four-slot fast gates and provider paid-edge closure."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
import storyos_autonomy_fast_test as f

def test_r7_slot_list_and_complete_suite():
    for name in ("gc-atomic","gateway-proof","native-route","r7-closure"):
        assert name in f.SLOTS
        assert len(f.test_commands(slot=name))==1
    stress=f.test_commands(slot="all",stress=True)
    assert "test_multi_episode_global_image_capacity.py" in " ".join(stress[-1])
    assert "test_storyos_autonomy_r7_gateway.py" in " ".join(" ".join(c) for c in stress)

def test_three_security_boundaries_fail_closed_together(monkeypatch,tmp_path):
    """Synthetic race/route/fence faults; none may delete refs or invoke Provider."""
    from contextlib import nullcontext
    import storyos_retired_worktree_gc as gc
    import storyos_autonomy_native_ready as native
    import storyos_codex_cli_readiness as low
    import pytest
    SYSTEM=ROOT/"episodes"/"_system"
    sys.path.insert(0,str(SYSTEM))
    import image_generation_gateway as gateway
    from generation_attempt_authority import AttemptDenied

    # Auth present under one CLI does not authorize a different Runner executable.
    cli={"status":"CLI_FLAGS_SUPPORTED","version":"codex-cli 0.162.1",
         "executable_fingerprint":low.executable_fingerprint("C:/client/codex.cmd")}
    runner={"status":"BRIDGE_AUTH_PRESENT","codex_version":"codex-cli 0.162.1",
            "executable_fingerprint":low.executable_fingerprint("C:/runner/codex.cmd")}
    assert native.summarize(cli,runner)["status"]=="BLOCKED"

    # Branch moved after planning: Git's atomic compare-and-delete refuses it.
    monkeypatch.setattr(gc,"branch_plan",lambda:{"status":"DRY_RUN","eligible":["fix/storyos-retired"]})
    monkeypatch.setattr(gc,"_worktrees",lambda:[])
    git_ops=[]
    def git(*args,**kwargs):
        git_ops.append(args)
        if args[0]=="rev-parse":return 0,"a"*40
        if args[0]=="update-ref":return 1,""  # another process changed the branch
        raise AssertionError(args)
    monkeypatch.setattr(gc,"_git",git)
    assert gc.apply_branches(acknowledged=True,max_count=1)["deleted_count"]==0

    # A post-commit Fence returning False must not dispatch a paid frame.
    lease={"episode_id":"ep","logical_asset_key":"ep/01","fencing_token":11}
    emitted=[]
    monkeypatch.setattr(gateway.global_image_capacity,"image_permits",lambda *_:nullcontext())
    monkeypatch.setattr(gateway.authority,"commit_dispatch",lambda *a,**k:dict(lease))
    monkeypatch.setattr(gateway.authority,"validate_committed_dispatch",lambda *a,**k:False)
    monkeypatch.setattr(gateway.authority,"fail_after_dispatch",lambda *a,**k:None)
    with pytest.raises(AttemptDenied):
        gateway.provider_generate(tmp_path,lease,11,"native",
                                  lambda:emitted.append("PAID"))
    assert not emitted
