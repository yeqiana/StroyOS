from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
SYSTEM = ROOT / "episodes/_system"
if str(SYSTEM) not in sys.path:
    sys.path.insert(0, str(SYSTEM))

import runtime_driver as driver


@pytest.mark.parametrize("failure,code", [
    (subprocess.TimeoutExpired(["powershell"], 60), "TASK_SCHEDULER_CARRIER_TIMEOUT"),
    (PermissionError("access denied"), "TASK_SCHEDULER_CARRIER_UNAVAILABLE"),
])
def test_task_scheduler_control_failure_has_bounded_driver_terminal_reason(failure, code):
    """No false success or unhandled OS error after job breakaway is denied."""
    with (
        patch.object(driver, "os", SimpleNamespace(name="nt")),
        patch.object(driver, "resolve_task_carrier_user", return_value=("INTERACTIVE\\user", "verified")),
        patch.object(driver, "task_carrier_script", return_value=("StoryOSDriver-test", "$script")),
        patch.object(driver.subprocess, "run", side_effect=failure) as runner,
    ):
        with pytest.raises(driver.DetachedLaunchError, match=code):
            driver._start_task_carrier(Path("."), ["python.exe", "runtime_driver.py"])
        runner.assert_called_once()
