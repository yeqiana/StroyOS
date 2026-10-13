"""R4 slot4: four-slot test runner and hard no-paid-transactions invariant."""
from __future__ import annotations
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
import storyos_autonomy_fast_test as runner

def test_r4_every_slot_has_executable_fast_suite():
    for slot in ("dispatch-fence","carrier-integrity","frame01-fence","r4-integration"):
        assert slot in runner.SLOTS
        assert runner.test_commands(slot=slot)[0][2]=="pytest"


def test_r4_total_suite_also_runs_cross_episode_cap():
    all_commands=runner.test_commands(slot="all",stress=True)
    content=" ".join(" ".join(cmd) for cmd in all_commands)
    assert "test_storyos_autonomy_r4_dispatch_fence.py" in content
    assert "test_storyos_autonomy_r4_carrier.py" in content
    assert "test_storyos_autonomy_r4_canary.py" in content
    assert "test_multi_episode_global_image_capacity.py" in content

def test_three_layer_failure_injection_never_spends_or_dispatches(monkeypatch,tmp_path):
    from contextlib import nullcontext
    import storyos_autonomy_carrier as carrier
    import storyos_autonomy_canary as canary
    from test_storyos_autonomy_r3_canary import healthy,baseline
    sys.path.insert(0,str(ROOT/"episodes/_system"))
    import image_generation_gateway as gateway
    from generation_attempt_authority import AttemptDenied

    # A forged scheduled task is not a verified Writer/Watchdog owner.
    planned=carrier.build_plan(tmp_path,identity="local\\real-user")
    forged={"principal":planned["principal"],"executable":planned["executable"],
            "arguments":planned["arguments"],"working_directory":planned["working_directory"],
            "trigger":"AT_BOOT","trigger_user":planned["principal"],
            "multiple_instances":"Parallel","enabled":True}
    assert carrier._task_matches(planned,forged) is False

    # A mismatched frame-01 evidence identity cannot authorize paid images.
    invalid=baseline()
    invalid["episode"]="different-episode"
    report=canary.decide(healthy(),invalid,episode="episodes/00_独立篇/test")
    assert report["status"]=="BLOCKED" and report["can_dispatch_image"] is False

    # If the Writer fence changes after irrevocable commit, Provider remains untouched.
    calls=[]
    lease={"episode_id":"ep","logical_asset_key":"ep/01","fencing_token":3}
    monkeypatch.setattr(gateway.global_image_capacity,"image_permits",lambda *_a:nullcontext())
    monkeypatch.setattr(gateway.authority,"commit_dispatch",lambda *_a,**_k:dict(lease))
    def no_longer_owner(*_a,**_k):
        raise AttemptDenied("STALE_GENERATION_ATTEMPT_FENCE")
    monkeypatch.setattr(gateway.authority,"validate_committed_dispatch",no_longer_owner)
    monkeypatch.setattr(gateway.authority,"fail_after_dispatch",lambda *_a,**_k:None)
    import pytest
    with pytest.raises(AttemptDenied):
        gateway.provider_generate(tmp_path,lease,3,"test",lambda:calls.append("paid"))
    assert calls==[] and lease["_phase"]=="TERMINAL"
