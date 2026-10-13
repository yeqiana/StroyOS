"""Deterministic autonomous-production fault-injection tests; no real models/DB/Provider."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch
import pytest

ROOT = Path(__file__).resolve().parents[2]
for directory in (ROOT / "scripts", ROOT / "episodes/_system"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
import storyos_codex_managed as native
import workflow_runner


def _probe_for(driver_state, attempt="ATTEMPT_HISTORY_READ_ONLY", schema=True):
    def fake(_env, script, args, **_kw):
        if script.endswith("runtime_router.py"):
            return 0, dict(effective_production_mode="CODEX_MANAGED",
                           effective_runtime="CODEX", image_execution_runtime="CODEX",
                           local_codex_spawn_allowed=True,
                           local_codex_image_spawn_allowed=True,
                           text_review_runtime="CODEX", vision_review_runtime="CODEX",
                           governance_review_runtime="CODEX")
        if script.endswith("codex_user_runner.py"):
            return 0, dict(status="ok", codex_available=True, codex_auth_present=True)
        if script.endswith("storyos_native_model_readiness.py"):
            return 0, {"status": "CLIENT_VERSION_COMPATIBLE"}
        if script.endswith("storyos_revision_schema_readonly.py"):
            return (0 if schema else 2), {"status": (
                "READY_FOR_FURTHER_ADMISSION" if schema else "SCHEMA_UNVERIFIED")}
        if script.endswith("storyos_episode_stage_readonly.py"):
            return 0, {"status": "STAGE_ELIGIBLE", "stage": "IDEA_LOCKED", "source": "mysql"}
        if script.endswith("storyos_creative_recovery_readonly.py"):
            return 0, {}
        if script.endswith("storyos_attempt_readonly_preflight.py"):
            return (0 if attempt == "ATTEMPT_HISTORY_READ_ONLY" else 2), {
                "status": attempt, "outcome_unknown_assets": (
                    ["frame-06"] if attempt != "ATTEMPT_HISTORY_READ_ONLY" else [])
            }
        if script.endswith("runtime_driver.py"):
            return 0, driver_state
        raise AssertionError("Unexpected external probe: " + script)
    return fake


@pytest.mark.parametrize("state", [
    {"driver_state": "NEVER_STARTED"},
    {"driver_state": "RUNNING", "pid": 1234},
    {"driver_state": "ALIVE_NOT_BEATING", "pid": 1234},
    {"driver_state": "UNKNOWN"},
    {"driver_state": "ABNORMAL_DISAPPEARANCE", "liveness": "DEAD"},
    {"driver_state": "ABNORMAL_DISAPPEARANCE", "liveness": "UNKNOWN"},
    {"driver_state": "EXITED", "exit_code": ""},
    {"driver_state": "EXITED", "exit_code": "0 2026-10-13"},
    {"driver_state": "EXITED", "exit_code": "21 2026-10-13"},
    {"driver_state": "EXITED", "exit_code": "23 2026-10-13"},
])
@pytest.mark.parametrize("attempt", ["ATTEMPT_HISTORY_READ_ONLY", "OUTCOME_UNKNOWN_BLOCKED"])
@pytest.mark.parametrize("schema", [True, False])
def test_40_way_driver_attempt_schema_gate_is_fail_closed(monkeypatch, state, attempt, schema):
    monkeypatch.setattr(native, "_probe", _probe_for(state, attempt, schema))
    result = native.preflight(
        {"STORYOS_MYSQL_HOST": "127.0.0.1", "STORYOS_MYSQL_PORT": "3307"},
        episode=native.ROOT / "episodes")
    expected = native.resident_restart_permitted(state) and schema and (
        attempt == "ATTEMPT_HISTORY_READ_ONLY")
    assert (result["status"] == "READY_TO_START") is expected
    assert result["production_authorization"] is False
    assert result["model_calls"] == 0
    assert result["sql_writes"] == 0


def test_cross_stage_host_loop_completes_three_local_actions_without_host_prompt():
    steps = ["REVIEW_ORDINARY_BASELINE", "GENERATE_IMAGES",
             "FINALIZE_PRODUCTION_IMAGES", "WAIT_HOST"]
    cursor = [0]
    invokes = []
    def next_action(_):
        return {"action": steps[cursor[0]]}
    def allowlist(action):
        return action["action"] if action["action"] in steps[:3] else None
    def run_local(_ep, action):
        invokes.append(action["action"])
        cursor[0] += 1
        return 0
    def dag_execute(*a, **kw):
        return 0 if cursor[0] >= 3 else 20
    with patch("episode_runner.local_host_action", side_effect=allowlist), \
         patch("episode_runner.run_local_host_action", side_effect=run_local), \
         patch.object(workflow_runner.next_action, "write", side_effect=next_action), \
         patch.object(workflow_runner.runtime_dag, "execute", side_effect=dag_execute):
        rc, note = workflow_runner.advance_host_loop(
            ROOT / "episodes", codex=None, timeout=3, run_id="test", trace_id="test",
            max_cycles=5)
    assert rc == 0
    assert invokes == steps[:3]


def test_true_external_wait_never_fakes_progress_or_spins():
    with patch("episode_runner.local_host_action", return_value=None), \
         patch.object(workflow_runner.next_action, "write",
                      return_value={"action": "REAL_HUMAN_REVIEW"}), \
         patch.object(workflow_runner.runtime_dag, "execute") as dag:
        rc, note = workflow_runner.advance_host_loop(
            ROOT / "episodes", codex=None, timeout=3, run_id="test", trace_id="test",
            max_cycles=10000)
    assert rc == 20
    assert "host_owns=REAL_HUMAN_REVIEW" in note
    dag.assert_not_called()
