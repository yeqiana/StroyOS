#!/usr/bin/env python3
"""Read-only proof for an old VISUAL_LOCK rc=4 after F001 predispatch rearm.

This only licenses another canonical Driver start. It cannot grant image tool
entitlement, approve visual reviews, or reserve/retry a paid Generation Attempt.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "episodes/_system"
if str(SYSTEM) not in sys.path:
    sys.path.insert(0, str(SYSTEM))

STATUS = "VISUAL_LOCK_RC4_VERIFIED_F001_PREDISPATCH_REARM_RECOVERABLE"
HOST_NOTE = ("VISUAL_LOCK_HOST_LANE_BLOCKED:VisualLockHostBlocked:"
             "VISUAL_LOCK_SCHEDULER_BASELINE_BLOCKED:rc=22")


def _time(s: str) -> datetime:
    d = datetime.fromisoformat(str(s or ""))
    if d.tzinfo is None or d.utcoffset() is None:
        raise ValueError("offset-aware timestamp required")
    return d


def inspect(episode: Path) -> dict:
    base = {"status": "VISUAL_LOCK_F001_REARM_RECOVERY_UNVERIFIED",
            "read_only": True, "production_authorization": False,
            "image_generation_called": False, "model_calls": 0,
            "sql_writes": 0, "image_entitlement_verified": False}
    def deny(reason: str) -> dict:
        return {**base, "status": reason}

    try:
        import episode_state_persistence
        import generation_attempt_authority as attempts
        import image_scheduler
        import model_policy
        import production_native_baseline_predispatch_rearm as rearm
        import production_native_baseline_proof as native_proof
        import runtime_checkpoint
        import runtime_driver
        import storyos_driver_exit_remediation as exit_authority

        ep = Path(episode).resolve()
        if (not ep.is_dir() or not ep.is_relative_to((ROOT/"episodes").resolve())):
            return deny("EPISODE_SCOPE_INVALID")
        if (episode_state_persistence.load(ep) or {}).get("current_state") != "STORYBOARD_LOCKED":
            return deny("STAGE_NO_LONGER_STORYBOARD_LOCKED")
        driver = runtime_driver.status(ep)
        record = driver.get("record") or {}
        if (driver.get("driver_state") != "EXITED"
                or driver.get("liveness") != "DEAD"
                or driver.get("exit_code") != "4"
                or driver.get("pid") != 0 or record.get("pid") != 0
                or str(record.get("rc") or "").split(" ", 1)[0] != "4"
                or Path(str(record.get("episode") or "")).resolve() != ep
                or driver.get("log") != record.get("log")):
            return deny("LATEST_DRIVER_EXIT_NOT_EXACT_RC4")
        started, ended = _time(record.get("started_at")), _time(record.get("exited_at"))
        if started >= ended:
            return deny("DRIVER_TIME_ORDER_INVALID")
        log = Path(str(record.get("log") or "")).resolve(strict=True)
        if (log.is_symlink()
                or not log.is_relative_to((ep/"meta/runtime/driver-logs").resolve())
                or log.stat().st_size > 16384):
            return deny("DRIVER_LOG_OUT_OF_SCOPE")
        lines = log.read_bytes().splitlines()
        m = (re.fullmatch(rb"DRIVER TASK CARRIER pid=([1-9][0-9]*) task=([A-Za-z0-9-]+)",
                          lines[0]) if len(lines) == 2 else None)
        if (m is None or m.group(2).decode() != record.get("carrier_task")
                or not re.fullmatch(rb"DRIVER EXIT rc=4[ \t]*", lines[1])):
            return deny("DRIVER_LOG_NOT_EXACT_TERMINAL_RC4")

        runs = [r for r in (runtime_checkpoint.load(ep, {}) or {}).get("step_runs", [])
                if isinstance(r, dict)]
        if not runs:
            return deny("CHECKPOINT_MISSING")
        last = runs[-1]
        if (last.get("step") != "VISUAL_LOCK"
                or last.get("status") != "BLOCKED"
                or last.get("returncode") != 4
                or str(last.get("note") or "") != HOST_NOTE
                or not started <= _time(last.get("finished_at")) < ended + timedelta(seconds=1)):
            return deny("LATEST_RC4_NOT_EXACT_BASELINE_BLOCK")

        trace_path = ep/"meta/runtime/trace-events.jsonl"
        if not trace_path.is_file() or trace_path.stat().st_size > 2500000:
            return deny("TRACE_MISSING_OR_OVERSIZED")
        last_fail = None
        for line in trace_path.read_text("utf-8-sig").splitlines():
            if '"STEP_FAILED"' not in line or '"VISUAL_LOCK"' not in line:
                continue
            item = json.loads(line)
            if item.get("event_type") == "STEP_FAILED" and item.get("step") == "VISUAL_LOCK":
                last_fail = item
        if (not isinstance(last_fail, dict) or str(last_fail.get("failure_class")) != "4"
                or not started <= _time(last_fail.get("timestamp")) < ended + timedelta(seconds=1)):
            return deny("TRACE_NOT_THIS_RC4")

        queue = image_scheduler.load_queue(ep)
        items = queue.get("items") or []
        first = next((x for x in items if int(x.get("frame") or 0) == 1), None)
        if (len(items) != 4 or not isinstance(first, dict)
                or first.get("status") != "queued"
                or first.get("scope") != "visual_lock"
                or int(first.get("attempts") or 0) != 1
                or int(first.get(rearm.REARM_FLAG) or 0) != 1
                or str(first.get("native_baseline_original_error") or "") != rearm.PREFIX
                or not re.fullmatch(r"[0-9a-f]{64}",
                                    str(first.get("native_baseline_visibility_sha256") or ""))
                or first.get("technical_failure_code") or first.get("last_error")):
            return deny("F001_NOT_EXACTLY_ONCE_REARMED")
        payload = model_policy.resolve("image.payload", episode=ep)
        controller = model_policy.resolve("image.controller", episode=ep)
        if not native_proof.eligible(ep, first, payload, controller, queue_override=queue):
            return deny("F001_NATIVE_BASELINE_AUTHORITIES_UNVERIFIED")
        key = rearm.logical_asset_identity.frame_asset_key(ep, 1)
        if (attempts.load_attempt(ep, key, 1) is not None
                or attempts.load_attempt(ep, key, 2) is not None):
            return deny("PAID_ATTEMPT_ALREADY_EXISTS")
        queue_identity = json.dumps(queue, ensure_ascii=False, sort_keys=True)
        if (runtime_driver.status(ep).get("record") != record
                or json.dumps(image_scheduler.load_queue(ep), ensure_ascii=False,
                              sort_keys=True) != queue_identity):
            return deny("DRIVER_OR_QUEUE_CHANGED_DURING_PROOF")
        return {**base, "status": STATUS,
                "driver_record_sha256": exit_authority.canonical_sha(record),
                "recovery_action": "CANONICAL_VISUAL_LOCK_F001_ONLY",
                "f001_queue_item_id": first["id"],
                "f001_reattest_proof_sha256": first["native_baseline_visibility_sha256"],
                "other_three_still_queued": True,
                "paid_attempts_reserved": 0}
    except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError,
            ImportError, RuntimeError):
        return deny("VISUAL_RC4_F001_RECOVERY_EVIDENCE_FAILURE")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--episode", required=True)
    report = inspect(Path(ap.parse_args().episode))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == STATUS else 2


if __name__ == "__main__":
    raise SystemExit(main())
