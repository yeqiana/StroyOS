"""R3 slot4: offline delivery-contract integration, no background OS services."""
from __future__ import annotations
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
import storyos_autonomy_fast_test as runner

def test_all_four_r3_slots_present_in_fast_suite():
    for name in ("carrier","writer","canary","autonomy-integration"):
        cmds=runner.test_commands(slot=name)
        assert cmds and "-m" in cmds[0] and "pytest" in cmds[0]

def test_stress_preserves_legacy_resident_and_multiepisode_capacity():
    cmds=runner.test_commands(slot="all",stress=True)
    joined=" ".join(" ".join(c) for c in cmds)
    assert "test_multi_episode_global_image_capacity.py" in joined
    assert "test_runtime_recovery.py" in joined
    assert "test_runtime_state_store.py" in joined
    assert "test_storyos_autonomy_r3_integration.py" in joined
