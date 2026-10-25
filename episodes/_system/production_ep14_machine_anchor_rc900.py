"""Strict read-only reentry of one Episode14 rc900 machine-anchor overwrite crash."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for item in (ROOT, ROOT / "scripts"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

import machine_action_executor as machine
import runtime_driver
import storyos_driver_exit_remediation as exits

EPISODE = (ROOT / "episodes" / "00_独立篇" /
           "14_深渊疗愈所_第一集_净土生命还原")
CRASH_MARKER = (
    b'DRIVER CRASH ValueError("machine contract refresh requires '
    b"['LOCKED', 'NEEDS_USER', 'ORIGINAL_READY', 'PASSED', 'REPAIR_READY'], "
    b'got WEAK_PASS")'
)


class SourceUnverified(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise SourceUnverified(reason)


def inspect(ep: Path) -> dict:
    ep = Path(ep).resolve()
    require(ep == EPISODE.resolve(), "WRONG_EPISODE")
    driver = runtime_driver.status(ep)
    record = driver.get("record") or {}
    require(driver.get("driver_state") == "EXITED"
            and driver.get("liveness") == "DEAD"
            and driver.get("pid") == 0
            and str(driver.get("exit_code")) == "900"
            and str(record.get("rc") or "").split(" ", 1)[0] == "900"
            and Path(str(record.get("episode") or "")).resolve() == ep,
            "DRIVER_RC900_NOT_PROVEN")
    path = Path(str(driver.get("log") or "")).resolve()
    require(path.is_relative_to((ep / "meta/runtime/driver-logs").resolve())
            and path.is_file() and str(record.get("log") or "") == str(driver.get("log") or ""),
            "DRIVER_CRASH_LOG_NOT_BOUND")
    raw_log = path.read_bytes()
    require(CRASH_MARKER in raw_log, "UNRELATED_RC900_CRASH")
    plan = machine.ep14_visual_anchor_restore_plan(ep)
    require(plan.get("status") == "READY"
            and plan.get("fields") == ["location", "weather_time"],
            "MACHINE_ANCHOR_RESTORE_NOT_VERIFIED")
    # The Plan independently binds historical 2/2 Attempts, original Vision
    # FAIL and exact four PNG SHA through ep14_remaining_exhausted_weak_passes.
    return {
        "status": "VISUAL_LOCK_RC900_EP14_MACHINE_ANCHOR_RESTORE_RECOVERABLE",
        "driver_record_sha256": exits.canonical_sha(record),
        "driver_log_sha256": hashlib.sha256(raw_log).hexdigest(),
        "gate_sha256": plan["source_gate_sha256"],
        "restored": plan["restored"],
        "machine_action": plan["action"],
        "new_paid_attempts": 0,
        "new_model_calls": 0,
        "read_only": True,
        "production_authorization": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--episode", required=True)
    parser.add_argument("--verify-rearmed", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = inspect(Path(args.episode))
    except Exception as error:
        report = {"status": "BLOCKED", "reason": str(error),
                  "error_class": type(error).__name__}
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return (0 if report["status"] ==
            "VISUAL_LOCK_RC900_EP14_MACHINE_ANCHOR_RESTORE_RECOVERABLE" else 2)


if __name__ == "__main__":
    raise SystemExit(main())
