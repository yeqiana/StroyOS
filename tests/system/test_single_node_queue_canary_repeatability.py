"""Single-node non-paid queue cutover/rollback repeatability.

Exercise the existing canary in separate disposable roots; it must never
touch a real Episode, pay Provider, or leave Runtime Workspace override.
"""
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
SYSTEM=ROOT/"episodes"/"_system"
if str(SYSTEM) not in sys.path:sys.path.insert(0,str(SYSTEM))
import production_queue_canary
import runtime_workspace


def test_repeated_queue_cutover_canary_preserves_all_queue_items_and_no_residue(tmp_path):
    initial=(runtime_workspace.ROOT,
             runtime_workspace.EPISODES_ROOT,
             runtime_workspace.DEFAULT_ROOT)
    for iteration in range(3):
        result=production_queue_canary.run_isolated_canary(base_dir=tmp_path)
        assert result["status"]=="PASS",iteration
        assert result["real_episode_touched"] is False
        assert result["initial_authority"]=="legacy_episode"
        assert result["active_authority"]=="runtime_workspace"
        assert result["final_authority"]=="legacy_episode"
        assert result["workspace_write_verified"] is True
        assert result["rollback_latest_queue_preserved"] is True
        assert list(tmp_path.iterdir())==[]
        assert (runtime_workspace.ROOT,
                runtime_workspace.EPISODES_ROOT,
                runtime_workspace.DEFAULT_ROOT)==initial
