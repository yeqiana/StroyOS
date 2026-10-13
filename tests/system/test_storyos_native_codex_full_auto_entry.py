"""Hermetic entrypoint tests: no MySQL connections, provider calls, or child runs."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "storyos_codex_managed", SCRIPTS / "storyos_codex_managed.py"
)
assert SPEC is not None and SPEC.loader is not None
native = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(native)


def _env_file(path: Path):
    path.write_text(
        "STORYOS_MYSQL_HOST=127.0.0.1\n"
        "STORYOS_MYSQL_PORT=3307\n"
        "STORYOS_MYSQL_USER=local_runner\n"
        "STORYOS_MYSQL_PWD=secret-do-not-print\n"
        "STORYOS_MYSQL_DB=STORY_OS_RUNTIME\n",
        encoding="utf-8",
    )


def test_native_env_discards_stale_mysql_and_proxy_and_sets_scope(tmp_path):
    path = tmp_path / "runtime.env"
    _env_file(path)
    env = native.native_environment(
        source={
            "STORYOS_MYSQL_HOST": "192.0.2.9", "STORYOS_MYSQL_PORT": "3306",
            "STORYOS_MYSQL_DB": "WRONG",
            "STORYOS_MYSQL_PWD": "wrong",
            "STORY_OS_PRODUCTION_MODE": "COLLABORATIVE",
            "STORY_OS_IMAGE_EXECUTOR": "PRODUCT_RUNTIME",
            "STORY_OS_RUNTIME": "WORK",
            "OPENAI_BASE_URL": "http://localhost:10100",
            "OPENAI_API_KEY": "unsafe-key",
            "PATH": "native-tools",
        },
        runtime_env=path,
    )
    assert env["STORYOS_MYSQL_HOST"] == "127.0.0.1"
    assert env["STORYOS_MYSQL_PORT"] == "3307"
    assert env["STORYOS_MYSQL_DB"] == "STORY_OS_RUNTIME"
    assert env["STORYOS_MYSQL_PWD"] == "secret-do-not-print"
    assert env["STORY_OS_PRODUCTION_MODE"] == "CODEX_MANAGED"
    assert env["STORY_OS_IMAGE_EXECUTOR"] == "CODEX"
    assert env["PATH"] == "native-tools"
    assert "OPENAI_BASE_URL" not in env
    assert "OPENAI_API_KEY" not in env
    assert "STORY_OS_RUNTIME" not in env
    assert "secret-do-not-print" not in json.dumps({"port": env["STORYOS_MYSQL_PORT"]})
    assert "STORYOS_MYSQL_PWD" in native.DB_KEYS


def test_native_env_fails_closed_when_missing(tmp_path):
    with pytest.raises(ValueError, match="NATIVE_CODEX_RUNTIME_ENV_MISSING"):
        native.native_environment(source={}, runtime_env=tmp_path / "missing.env")


def test_canonical_episode_rejects_outside_and_missing(tmp_path):
    with pytest.raises(ValueError, match="NATIVE_CODEX_EPISODE_PATH_INVALID"):
        native.canonical_episode(str(tmp_path))


def _proofs(status="ATTEMPT_HISTORY_READ_ONLY", driver="NEVER_STARTED",
            schema="READY_FOR_FURTHER_ADMISSION", executor="CODEX",
            model_client_ok=True):
    def probe(_env, script, args, **_kw):
        if script.endswith("runtime_router.py"):
            return 0, {
                "effective_production_mode": "CODEX_MANAGED",
                "effective_runtime": "CODEX",
                "image_execution_runtime": executor,
                "local_codex_spawn_allowed": True,
                "local_codex_image_spawn_allowed": True,
                "text_review_runtime": "CODEX",
                "vision_review_runtime": "CODEX",
                "governance_review_runtime": "CODEX",
            }
        if script.endswith("codex_user_runner.py"):
            return 0, {"status": "ok", "codex_available": True, "codex_auth_present": True}
        if script.endswith("storyos_native_model_readiness.py"):
            return (0 if model_client_ok else 2), {
                "status": ("CLIENT_VERSION_COMPATIBLE" if model_client_ok
                           else "CLIENT_VERSION_BLOCKED"),
                "minimum_cli_version": "0.155.0",
                "policy_source": "MYSQL_EPISODE_MODEL_POLICY" if args else "CONFIG_UNBOUND",
                "model_entitlement_verified": False,
            }
        if script.endswith("storyos_revision_schema_readonly.py"):
            return (0 if schema == "READY_FOR_FURTHER_ADMISSION" else 2), {
                "status": schema, "reason": "SCHEMA_PRESENT_REQUIRES_VISUAL_LOCK_AND_AUTHORITY"
            }
        if script.endswith("storyos_episode_stage_readonly.py"):
            return 0, {"status": "STAGE_ELIGIBLE", "stage": "STORYBOARD_LOCKED",
                       "source": "mysql"}
        if script.endswith("storyos_creative_recovery_readonly.py"):
            return 0, {"status": "REVIEW_EVIDENCE_NOT_YET_CREATED",
                       "contract_status": "DRAFT",
                       "review_path_present": False,
                       "model_success_receipt_count": 0,
                       "model_success_receipt_reuse_verified": False,
                       "model_generation_required": None}
        if script.endswith("storyos_attempt_readonly_preflight.py"):
            return (0 if status == "ATTEMPT_HISTORY_READ_ONLY" else 2), {
                "status": status,
                "outcome_unknown_assets": (["episode/frame-06"] if "UNKNOWN" in status else []),
                "active_attempt_assets": [],
            }
        if script.endswith("runtime_driver.py"):
            return 0, {"driver_state": driver}
        if script.endswith("storyos_visual_lock_readonly.py"):
            # Readiness diagnostics are independent of Driver admission.
            # A synthetic Storyboard episode is NOT proof of image tools.
            return 0, {"status": "BLOCKED",
                       "reason": "REAL_NATIVE_IMAGE_PIXEL_PROOF_NOT_YET_ESTABLISHED",
                       "tool_generation_proven": False, "read_only": True,
                       "model_calls": 0, "sql_writes": 0}
        raise AssertionError(f"Unexpected probe {script}: {args}")
    return probe


def _test_env():
    return {"STORYOS_MYSQL_HOST": "127.0.0.1", "STORYOS_MYSQL_PORT": "3307",
            "STORYOS_MYSQL_DB": "STORY_OS_RUNTIME"}


def test_preflight_new_idea_can_start_without_existing_episode(monkeypatch):
    monkeypatch.setattr(native, "_probe", _proofs())
    result = native.preflight(_test_env())
    assert result["status"] == "READY_TO_START"
    assert result["scope"] == "NATIVE_CODEX_FULL_AUTO"
    assert result["codex"]["tool_generation_proven"] is False
    assert result["codex"]["model_client_version_ok"] is True
    assert result["codex"]["model_entitlement_verified"] is False
    assert result["model_calls"] == result["sql_writes"] == 0


def test_native_preflight_exposes_unlocked_story_without_reuse_authority(monkeypatch):
    monkeypatch.setattr(native, "_probe", _proofs())
    result = native.preflight(_test_env(), episode=native.ROOT / "episodes")
    recovery = result["creative_story_recovery"]
    assert recovery["contract_status"] == "DRAFT"
    assert recovery["review_path_present"] is False
    assert recovery["model_success_receipt_reuse_verified"] is False
    assert recovery["model_success_is_story_lock"] is False
    assert recovery["model_generation_required"] is None
    assert result["production_authorization"] is False
    assert result["visual_lock_admission"]["status"] == "BLOCKED"
    assert result["visual_lock_admission"]["tool_generation_proven"] is False


def test_preflight_blocks_incompatible_cli_before_paid_production(monkeypatch):
    monkeypatch.setattr(native, "_probe", _proofs(model_client_ok=False))
    result = native.preflight(_test_env(), episode=native.ROOT / "episodes")
    assert result["status"] == "BLOCKED"
    assert result["codex"]["model_client_version_ok"] is False
    assert result["codex"]["model_entitlement_verified"] is False
    assert "NATIVE_CODEX_MODEL_CLI_VERSION_OR_POLICY_UNVERIFIED" in result["blockers"]
    assert result["production_authorization"] is False
    assert result["model_calls"] == result["sql_writes"] == 0


def test_preflight_blocks_unknown_and_never_authorizes_retry(monkeypatch):
    monkeypatch.setattr(native, "_probe", _proofs(status="OUTCOME_UNKNOWN_BLOCKED"))
    episode = native.ROOT / "episodes"
    result = native.preflight(_test_env(), episode=episode)
    assert result["status"] == "BLOCKED"
    assert result["attempt"]["outcome_unknown_assets"] == ["episode/frame-06"]
    assert "GENERATION_ATTEMPT_AUTHORITY_RECONCILIATION_REQUIRED" in result["blockers"]
    assert result["production_authorization"] is False


@pytest.mark.parametrize(
    "driver,schema,executor",
    [("RUNNING", "READY_FOR_FURTHER_ADMISSION", "CODEX"),
     ("UNKNOWN", "READY_FOR_FURTHER_ADMISSION", "CODEX"),
     ("NEVER_STARTED", "BLOCKED", "CODEX"),
     ("NEVER_STARTED", "READY_FOR_FURTHER_ADMISSION", "PRODUCT_RUNTIME")],
)
def test_preflight_fail_closed_on_ambiguous_owner_schema_or_executor(
    monkeypatch, driver, schema, executor
):
    monkeypatch.setattr(native, "_probe", _proofs(
        driver=driver, schema=schema, executor=executor
    ))
    result = native.preflight(_test_env(), episode=native.ROOT / "episodes")
    assert result["status"] == "BLOCKED"




def test_finished_episode_is_blocked_before_paid_model_calls(monkeypatch):
    base_probe = _proofs()
    def probe(env, script, args, **kwargs):
        if script.endswith("storyos_episode_stage_readonly.py"):
            return 2, {"status": "ALREADY_PUBLISH_READY", "stage": "PUBLISH_READY",
                       "source": "mysql"}
        return base_probe(env, script, args, **kwargs)
    monkeypatch.setattr(native, "_probe", probe)
    result = native.preflight(_test_env(), episode=native.ROOT / "episodes")
    assert result["status"] == "BLOCKED"
    assert "EPISODE_STAGE_NOT_ELIGIBLE_FOR_PRODUCTION" in result["blockers"]
    assert result["episode_stage"]["current_state"] == "PUBLISH_READY"
    assert result["production_authorization"] is False


def test_full_auto_command_uses_canonical_storyos_only():
    episode = native.ROOT / "episodes" / "example"
    args = argparse.Namespace(command="run")
    command = native.full_auto_command(args, episode)
    assert command[1].endswith("episodes\\_system\\story_os.py") or command[1].endswith(
        "episodes/_system/story_os.py"
    )
    assert command[2:] == ["run", str(episode), "--full-auto", "--resume"]
    args = argparse.Namespace(command="create", request_text="A mystery",
                              title="The Orchard", visual_profile=None)
    assert native.full_auto_command(args, None)[2:] == [
        "create", "A mystery", "--full-auto", "--title", "The Orchard"
    ]


def test_main_blocked_does_not_spawn_model_or_production(monkeypatch, capsys):
    monkeypatch.setattr(native, "canonical_episode", lambda _name: native.ROOT / "episodes")
    monkeypatch.setattr(native, "native_environment", lambda: _test_env())
    monkeypatch.setattr(native, "_probe", _proofs(status="OUTCOME_UNKNOWN_BLOCKED"))
    monkeypatch.setattr(native.subprocess, "call",
                        lambda *_a, **_kw: pytest.fail("unexpected production subprocess"))
    rc = native.main(["run", "placeholder", "--ack-real-production"])
    assert rc == 3
    assert "NATIVE_CODEX_FULL_AUTO_BLOCKED_BY_AUTHORITY" in capsys.readouterr().err


def test_main_requires_real_production_ack(monkeypatch, capsys):
    monkeypatch.setattr(native, "canonical_episode", lambda _name: native.ROOT / "episodes")
    monkeypatch.setattr(native, "native_environment", lambda: _test_env())
    monkeypatch.setattr(native, "_probe", _proofs())
    monkeypatch.setattr(native.subprocess, "call",
                        lambda *_a, **_kw: pytest.fail("unexpected production subprocess"))
    assert native.main(["run", "placeholder"]) == 2
    assert "ACK_REQUIRED" in capsys.readouterr().err


def test_main_authorized_delegates_once_without_background_or_provider_calls(monkeypatch):
    monkeypatch.setattr(native, "canonical_episode", lambda _name: native.ROOT / "episodes")
    monkeypatch.setattr(native, "native_environment", lambda: _test_env())
    monkeypatch.setattr(native, "_probe", _proofs())
    calls = []
    def fake_call(command, *, cwd, env):
        calls.append((command, cwd, dict(env)))
        return 0
    monkeypatch.setattr(native.subprocess, "call", fake_call)
    assert native.main(["run", "placeholder", "--ack-real-production"]) == 0
    assert len(calls) == 1
    assert calls[0][0][-2:] == ["--full-auto", "--resume"]
    assert calls[0][1] == native.ROOT

# Autonomy fast tests: hermetic; never connect to MySQL or paid providers.
def test_resident_start_routes_to_existing_runtime_driver(monkeypatch):
    monkeypatch.setattr(native, "canonical_episode", lambda _name: native.ROOT / "episodes")
    monkeypatch.setattr(native, "native_environment", lambda: _test_env())
    monkeypatch.setattr(native, "_probe", _proofs())
    calls = []
    monkeypatch.setattr(native.subprocess, "call",
                        lambda cmd, *, cwd, env: (calls.append((cmd, cwd, env)) or 0))
    assert native.main(["start", "placeholder", "--ack-real-production"]) == 0
    assert len(calls) == 1
    cmd, cwd, env = calls[0]
    assert cmd[1].endswith("runtime_driver.py")
    assert cmd[2:] == ["start", str(native.ROOT / "episodes"), "--resume", "--json"]
    assert cwd == native.ROOT


def test_resident_start_requires_ack_and_blocks_unknown(monkeypatch):
    monkeypatch.setattr(native, "canonical_episode", lambda _name: native.ROOT / "episodes")
    monkeypatch.setattr(native, "native_environment", lambda: _test_env())
    monkeypatch.setattr(native.subprocess, "call",
                        lambda *_a, **_kw: pytest.fail("no production subprocess allowed"))
    monkeypatch.setattr(native, "_probe", _proofs())
    assert native.main(["start", "placeholder"]) == 2
    monkeypatch.setattr(native, "_probe", _proofs(status="OUTCOME_UNKNOWN_BLOCKED"))
    assert native.main(["start", "placeholder", "--ack-real-production"]) == 3


@pytest.mark.parametrize("rc", ["20 2026-10-13T01:00:00Z", "21 2026-10-13T01:00:00Z",
                               "22 2026-10-13T01:00:00Z", "23 2026-10-13T01:00:00Z",
                               "24 2026-10-13T01:00:00Z", "25 2026-10-13T01:00:00Z"])
def test_resident_start_refuses_terminal_or_exhausted_driver(monkeypatch, rc):
    base = _proofs(driver="EXITED")
    def probe(env, script, args, **kw):
        if script.endswith("runtime_driver.py"):
            return 0, {"driver_state": "EXITED", "exit_code": rc}
        return base(env, script, args, **kw)
    monkeypatch.setattr(native, "_probe", probe)
    result = native.preflight(_test_env(), episode=native.ROOT / "episodes")
    assert result["status"] == "BLOCKED"
    assert "EPISODE_DRIVER_EXIT_REQUIRES_REMEDIATION" in result["blockers"]
    assert result["production_authorization"] is False


@pytest.mark.parametrize("exit_code,allowed", [
    ("", True), ("0 2026-10-13T01:00:00Z", True),
    ("901 2026-10-13T01:00:00Z", False),
    ("20 2026-10-13T01:00:00Z", False),
])
def test_resident_exit_decision_is_bounded_and_explicit(exit_code, allowed):
    assert native.resident_restart_permitted(
        {"driver_state": "EXITED", "exit_code": exit_code}
    ) is allowed

def test_crashed_driver_is_recoverable_only_when_pid_proven_dead(monkeypatch):
    base = _proofs(driver="EXITED")
    def probe(env, script, args, **kw):
        if script.endswith("runtime_driver.py"):
            return 0, {"driver_state": "ABNORMAL_DISAPPEARANCE",
                       "liveness": "DEAD", "exit_code": ""}
        return base(env, script, args, **kw)
    monkeypatch.setattr(native, "_probe", probe)
    report = native.preflight(_test_env(), episode=native.ROOT / "episodes")
    assert report["status"] == "READY_TO_START"
    assert report["driver_state"] == "ABNORMAL_DISAPPEARANCE"
    assert report["attempt"]["active_attempt_assets"] == []


@pytest.mark.parametrize("liveness", ["UNKNOWN", "ALIVE", None])
def test_crashed_driver_cannot_restart_without_pid_proof(liveness):
    assert native.resident_restart_permitted(
        {"driver_state": "ABNORMAL_DISAPPEARANCE",
         "exit_code": "", "liveness": liveness}
    ) is False


def test_repeated_preflight_is_pure_and_never_spawns(monkeypatch):
    calls = []
    monkeypatch.setattr(native, "_probe", lambda *a, **kw: (calls.append((a,kw)) or _proofs()(*a,**kw)))
    for _ in range(50):
        report = native.preflight(_test_env(), episode=native.ROOT / "episodes")
        assert report["status"] == "READY_TO_START"
        assert report["model_calls"] == report["sql_writes"] == 0
    assert len(calls) == 50 * 9  # all nine probes are read-only
