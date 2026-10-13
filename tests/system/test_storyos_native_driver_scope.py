"""Detached native-Codex Driver mode regression. No real Driver or provider calls."""
from __future__ import annotations

import os
from pathlib import Path
import sys

import pytest

SYSTEM = Path(__file__).resolve().parents[2] / "episodes" / "_system"
if str(SYSTEM) not in sys.path:
    sys.path.insert(0, str(SYSTEM))
import runtime_driver as driver


def test_native_scope_is_serialized_only_when_both_authorities_match(monkeypatch):
    monkeypatch.setenv("STORY_OS_PRODUCTION_MODE", "CODEX_MANAGED")
    monkeypatch.setenv("STORY_OS_IMAGE_EXECUTOR", "CODEX")
    assert driver._native_child_scope_args() == [
        "--production-mode", "CODEX_MANAGED", "--image-executor", "CODEX"
    ]
    monkeypatch.setenv("STORY_OS_IMAGE_EXECUTOR", "PRODUCT_RUNTIME")
    with pytest.raises(ValueError, match="NATIVE_DRIVER_SCOPE_MISMATCH"):
        driver._native_child_scope_args()
    monkeypatch.setenv("STORY_OS_PRODUCTION_MODE", "COLLABORATIVE")
    assert driver._native_child_scope_args() == []


def test_task_carrier_child_reloads_native_mode_without_proxy(monkeypatch, tmp_path):
    envfile = tmp_path / "runtime.env"
    envfile.write_text("STORYOS_MYSQL_HOST=127.0.0.1\n", encoding="utf-8")
    monkeypatch.setattr(driver, "RUNTIME_ENV_PATH", envfile)
    monkeypatch.setenv("STORY_OS_PRODUCTION_MODE", "COLLABORATIVE")
    monkeypatch.setenv("STORY_OS_IMAGE_EXECUTOR", "PRODUCT_RUNTIME")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:10100")
    monkeypatch.setenv("OPENAI_API_KEY", "forbidden-key")
    driver._load_child_runtime_environment(
        runtime_store_mode="mysql", episode_meta_store_mode="mysql",
        hot_state_mode="file", production_mode="CODEX_MANAGED", image_executor="CODEX"
    )
    assert os.environ["STORY_OS_PRODUCTION_MODE"] == "CODEX_MANAGED"
    assert os.environ["STORY_OS_IMAGE_EXECUTOR"] == "CODEX"
    assert os.environ["STORYOS_RUNTIME_STORE_MODE"] == "mysql"
    assert "OPENAI_BASE_URL" not in os.environ
    assert "OPENAI_API_KEY" not in os.environ

@pytest.mark.parametrize("exit_code", ["20 2026-10-13", "21 2026-10-13",
                                      "22 2026-10-13", "23 2026-10-13",
                                      "24 2026-10-13", "900 2026-10-13"])
def test_recover_reports_remediation_for_exhausted_or_blocked_driver(monkeypatch, exit_code):
    monkeypatch.setattr(driver, "status", lambda _ep: {
        "driver_state": "EXITED", "exit_code": exit_code, "pid": 0
    })
    report = driver.recover(Path("fake-episode"))
    assert report["recovery"] == "REMEDIATION_REQUIRED"
    assert report["driver_state"] == "EXITED"


def test_recover_clean_exit_allows_readonly_restart_advice(monkeypatch):
    monkeypatch.setattr(driver, "status", lambda _ep: {
        "driver_state": "EXITED", "exit_code": "0 2026-10-13", "pid": 0
    })
    assert driver.recover(Path("fake-episode"))["recovery"] == "START_IF_WORK_REMAINS"
