#!/usr/bin/env python3
"""Exact latest Visual Lock rc4 postcondition recovery, read-only.

Proves that latest terminal rc4 is the old text-worker no-plan/no-pixel
postcondition, not a technical model/image failure or negative pixel review.
The authorized Driver must still run normal scheduler/Attempt/pixel gates.
"""
from __future__ import annotations

import argparse
from datetime import datetime,timedelta
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
SYSTEM=ROOT/"episodes/_system"
if str(SYSTEM) not in sys.path:sys.path.insert(0,str(SYSTEM))
STATUS="VISUAL_LOCK_RC4_MISSING_HOST_PLAN_RECOVERABLE"


def _at(raw):
    d=datetime.fromisoformat(str(raw or ""))
    if d.tzinfo is None or d.utcoffset() is None:
        raise ValueError("timestamp requires explicit zone")
    return d


def inspect(episode:Path)->dict:
    base={"status":"VISUAL_LOCK_RC4_UNVERIFIED","read_only":True,
          "model_calls":0,"sql_writes":0,"image_generation_called":False,
          "production_authorization":False,"image_entitlement_verified":False}
    def blocked(reason):return {**base,"status":reason}
    try:
        import runtime_driver
        import runtime_checkpoint
        import episode_state_persistence
        import storyos_driver_exit_remediation as exits
        import story_json

        ep=Path(episode).resolve()
        if (not ep.is_dir() or not ep.is_relative_to((ROOT/"episodes").resolve())
                or (episode_state_persistence.load(ep) or {}).get("current_state")!="STORYBOARD_LOCKED"):
            return blocked("VISUAL_STAGE_NOT_ELIGIBLE")
        driver=runtime_driver.status(ep)
        record=driver.get("record") or {}
        if (driver.get("driver_state")!="EXITED"
                or driver.get("exit_code")!="4" or driver.get("liveness")!="DEAD"
                or driver.get("pid")!=0 or record.get("pid")!=0
                or str(record.get("rc") or "").split(" ",1)[0]!="4"
                or Path(str(record.get("episode") or "")).resolve()!=ep
                or driver.get("log")!=record.get("log")):
            return blocked("DRIVER_LATEST_EXIT_NOT_TERMINAL_RC4")
        started,exited=_at(record.get("started_at")),_at(record.get("exited_at"))
        if started>=exited:
            return blocked("DRIVER_TIME_ORDER_INVALID")
        file=Path(str(record.get("log") or "")).resolve(strict=True)
        if (file.is_symlink() or not file.is_relative_to((ep/"meta/runtime/driver-logs").resolve())
                or file.stat().st_size>16384):
            return blocked("DRIVER_EXIT_LOG_UNVERIFIED")
        lines=file.read_bytes().splitlines()
        head=(re.fullmatch(rb"DRIVER TASK CARRIER pid=([1-9][0-9]*) task=([A-Za-z0-9-]+)",
                           lines[0]) if len(lines)==2 else None)
        if (not head or head.group(2).decode()!=record.get("carrier_task")
                or not re.fullmatch(rb"DRIVER EXIT rc=4[ \t]*",lines[1])):
            return blocked("DRIVER_EXIT_LOG_RC4_MISMATCH")
        rows=[x for x in runtime_checkpoint.load(ep,{}).get("step_runs",[])
              if isinstance(x,dict) and x.get("step")=="VISUAL_LOCK"]
        if not rows:
            return blocked("VISUAL_CHECKPOINT_MISSING")
        last=rows[-1]
        note=str(last.get("note") or "")
        required=("POSTCONDITION FAIL","visual_admission_frames",
                  "continuity_anchor_missing","visual_lock_v21_gate:",
                  "meta/visual-profile-review.json missing")
        if (last.get("returncode")!=4 or last.get("status")!="BLOCKED"
                or any(marker not in note for marker in required)
                or not started<=_at(last.get("finished_at"))<exited+timedelta(seconds=1)):
            return blocked("LATEST_RC4_NOT_MISSING_VISUAL_DELIVERABLES")
        # The old text worker must not have any formal plan or reviewed pixels
        # to preserve. Any existing Plan/Review requires normal reconciliation.
        if ((ep/"meta/visual-lock-plan.json").exists()
                or (ep/"meta/visual-profile-review.json").exists()):
            return blocked("VISUAL_PLAN_OR_REVIEW_ALREADY_EXISTS_RECONCILE")
        gates=story_json.read_json(ep/"meta/story-gates.json",default={}) or {}
        reviews=gates.get("reviews") or {}
        items=((gates.get("visual") or {}).get("calibration") or {}).get("items") or []
        if (items or reviews.get("visual_admission")!="pending"
                or reviews.get("authenticity")!="pending"):
            return blocked("VISUAL_GATE_NOT_STILL_PENDING")
        trace=ep/"meta/runtime/trace-events.jsonl"
        if not trace.is_file() or trace.stat().st_size>2500000:
            return blocked("VISUAL_TRACE_MISSING")
        latest=None
        for line in trace.read_text("utf-8-sig").splitlines():
            if '"STEP_FAILED"' not in line or '"VISUAL_LOCK"' not in line:
                continue
            row=json.loads(line)
            if row.get("event_type")=="STEP_FAILED" and row.get("step")=="VISUAL_LOCK":
                latest=row
        if (not isinstance(latest,dict)
                or str(latest.get("failure_class"))!="4"
                or not started<=_at(latest.get("timestamp"))<exited+timedelta(seconds=1)):
            return blocked("LATEST_VISUAL_TRACE_NOT_THIS_EXIT")
        reread=runtime_driver.status(ep)
        if (reread.get("record")!=record or reread.get("driver_state")!="EXITED"
                or reread.get("liveness")!="DEAD"):
            return blocked("DRIVER_EXIT_IDENTITY_CHANGED_DURING_CHECK")
        return {**base,"status":STATUS,
                "driver_record_sha256":exits.canonical_sha(record),
                "recovery_action":"HOST_FOUR_FRAME_PLAN_THEN_REAL_PIXELS",
                "actual_pixel_review_pass":False,"admission_plan_present":False}
    except (OSError,ValueError,TypeError,IndexError,KeyError,AttributeError):
        return blocked("VISUAL_RC4_READONLY_EVIDENCE_FAILURE")


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--episode",required=True)
    report=inspect(Path(ap.parse_args().episode))
    print(json.dumps(report,ensure_ascii=False,sort_keys=True))
    return 0 if report["status"]==STATUS else 2


if __name__=="__main__":
    raise SystemExit(main())
