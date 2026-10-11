"""No-write CLI admission gate for native Frame01 evidence preflight."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import storyos_native_frame01_preflight as entry


@pytest.fixture()
def launched(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(
        entry.storyos_codex_managed, "canonical_episode",
        lambda raw: Path("C:/synthetic-episode"),
    )
    monkeypatch.setattr(
        entry.storyos_codex_managed, "native_environment",
        lambda: {"STORYOS_MYSQL_HOST": "127.0.0.1",
                 "STORYOS_MYSQL_PORT": "3307",
                 "STORYOS_TEST_ONLY_FAKE": "unit"},
    )
    def run(cmd, **kwargs):
        assert cmd[0] == sys.executable
        assert cmd[1].endswith("native_baseline_readonly_preflight.py")
        assert kwargs["env"]["STORYOS_TEST_ONLY_FAKE"] == "unit"
        assert kwargs["capture_output"] is True
        assert kwargs["check"] is False
        calls.append((cmd, kwargs))
        return SimpleNamespace(
            returncode=run.returncode,
            stdout=json.dumps(run.payload, ensure_ascii=False),
            stderr="DO_NOT_DISCLOSE",
        )
    run.returncode = 0
    run.payload = {
        "status": "READ_ONLY_EVIDENCE_READY_TEST_DB_STILL_REQUIRED",
        "authorized_to_mutate_production": False,
        "sql_writes": 0,
        "model_calls": 0,
    }
    monkeypatch.setattr(entry.subprocess, "run", run)
    return run, calls, capsys


def test_wrapper_uses_canonical_runtime_and_retains_non_authorization(launched):
    run, calls, capsys = launched
    assert entry.main(["episodes/synthetic"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "READ_ONLY_EVIDENCE_READY_TEST_DB_STILL_REQUIRED"
    assert output["authorized_to_mutate_production"] is False
    assert len(calls) == 1


@pytest.mark.parametrize("drift", [
    "attempts_to_authorize", "claims_sql_write", "claims_model_call",
    "unknown_status", "wrong_exit", "broken_json",
])
def test_wrapper_rejects_untrusted_child_outcome(launched, drift):
    run, calls, capsys = launched
    if drift == "attempts_to_authorize":
        run.payload["authorized_to_mutate_production"] = True
    elif drift == "claims_sql_write":
        run.payload["sql_writes"] = 1
    elif drift == "claims_model_call":
        run.payload["model_calls"] = 1
    elif drift == "unknown_status":
        run.payload["status"] = "PUBLISH_READY"
    elif drift == "wrong_exit":
        run.returncode = 7
    elif drift == "broken_json":
        run.payload = "malformed"
        # JSON string is not an object, and should fail closed.
    assert entry.main(["episodes/synthetic"]) == 2
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "BLOCKED"
    assert output["authorized_to_mutate_production"] is False
    assert output["sql_writes"] == 0
    assert output["model_calls"] == 0
    assert "DO_NOT_DISCLOSE" not in json.dumps(output)
    assert len(calls) == 1
