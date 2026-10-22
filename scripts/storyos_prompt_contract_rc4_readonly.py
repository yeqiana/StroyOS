#!/usr/bin/env python3
"""Read-only latest PROMPT_AUTHORING rc4 derived-index recovery proof.

Not a general quality-gate bypass. Requires immutable terminal Driver,
the exact checkpoint/trace failure and independent monotonic SHA migration
proof for all affected Frame Contracts, with no pixel dispatch.
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
STATUS="PROMPT_RC4_PREIMAGE_VISUAL_INDEX_REBIND_RECOVERABLE"


def _at(raw):
    d=datetime.fromisoformat(str(raw or ""))
    if not d.tzinfo or d.utcoffset() is None:
        raise ValueError("offset-aware timestamp required")
    return d


def inspect(episode:Path)->dict:
    base={"status":"PROMPT_RC4_PROOF_UNVERIFIED","read_only":True,
          "model_calls":0,"sql_writes":0,"image_generation_called":False,
          "production_authorization":False,"image_entitlement_verified":False}
    def denied(reason):return {**base,"status":reason}
    try:
        import runtime_driver,runtime_checkpoint,episode_state_persistence
        import storyos_driver_exit_remediation as exits
        import visual_lock_contract_bridge

        ep=Path(episode).resolve()
        if (not ep.is_dir() or not ep.is_relative_to((ROOT/"episodes").resolve())
                or (episode_state_persistence.load(ep) or {}).get("current_state")!="STORYBOARD_LOCKED"):
            return denied("PROMPT_RECOVERY_EPISODE_STAGE_INVALID")
        driver=runtime_driver.status(ep)
        record=driver.get("record") or {}
        if (driver.get("driver_state")!="EXITED"
                or str(driver.get("exit_code") or "")!="4"
                or driver.get("liveness")!="DEAD"
                or driver.get("pid")!=0 or record.get("pid")!=0
                or str(record.get("rc") or "").split(" ",1)[0]!="4"
                or Path(str(record.get("episode") or "")).resolve()!=ep
                or record.get("log")!=driver.get("log")):
            return denied("PROMPT_RECOVERY_DRIVER_NOT_EXACT_TERMINAL_RC4")
        started,exited=_at(record.get("started_at")),_at(record.get("exited_at"))
        if not started<exited:return denied("PROMPT_RECOVERY_TIME_INVALID")
        logfile=Path(str(record.get("log") or "")).resolve(strict=True)
        if (logfile.is_symlink()
                or not logfile.is_relative_to((ep/"meta/runtime/driver-logs").resolve())
                or logfile.stat().st_size>16384):
            return denied("PROMPT_RECOVERY_DRIVER_LOG_INVALID")
        lines=logfile.read_bytes().splitlines()
        match=(re.fullmatch(rb"DRIVER TASK CARRIER pid=([1-9][0-9]*) task=([A-Za-z0-9-]+)",
                            lines[0]) if len(lines)==2 else None)
        if (not match or match.group(2).decode()!=record.get("carrier_task")
                or not re.fullmatch(rb"DRIVER EXIT rc=4[ \t]*",lines[1])):
            return denied("PROMPT_RECOVERY_DRIVER_LOG_NOT_MATCHED")
        runlist=[r for r in (runtime_checkpoint.load(ep,{}) or {}).get("step_runs",[])
                 if isinstance(r,dict)]
        if not runlist:return denied("PROMPT_RECOVERY_CHECKPOINT_MISSING")
        last=runlist[-1]
        if (last.get("step")!="PROMPT_AUTHORING"
                or last.get("status")!="BLOCKED"
                or last.get("returncode")!=4
                or str(last.get("note") or "")!=
                   "LOCKED STORY PROMPT AUTHORING FAIL: frame contracts invalid: frame contract index stale"
                or not started<=_at(last.get("finished_at"))<exited+timedelta(seconds=1)):
            return denied("PROMPT_RECOVERY_CHECKPOINT_NOT_EXACT_INDEX_STALE")
        trace=ep/"meta/runtime/trace-events.jsonl"
        if not trace.is_file() or trace.stat().st_size>2500000:
            return denied("PROMPT_RECOVERY_TRACE_MISSING")
        matched=None
        for line in trace.read_text("utf-8-sig").splitlines():
            if '"STEP_FAILED"' not in line or '"PROMPT_AUTHORING"' not in line:
                continue
            row=json.loads(line)
            if row.get("event_type")=="STEP_FAILED" and row.get("step")=="PROMPT_AUTHORING":
                matched=row
        if (not isinstance(matched,dict) or str(matched.get("failure_class"))!="4"
                or not started<=_at(matched.get("timestamp"))<exited+timedelta(seconds=1)):
            return denied("PROMPT_RECOVERY_TRACE_NOT_THIS_RC4")
        probe=visual_lock_contract_bridge.reconcile(ep,dry_run=True)
        if probe.get("status")!="DERIVED_REBIND_READONLY_READY":
            return denied("PROMPT_RECOVERY_PROJECTION_NOT_PROVEN")
        reread=runtime_driver.status(ep)
        if (reread.get("record")!=record or reread.get("driver_state")!="EXITED"
                or reread.get("liveness")!="DEAD"):
            return denied("PROMPT_RECOVERY_DRIVER_CHANGED_DURING_READ")
        return {**base,"status":STATUS,
                "driver_record_sha256":exits.canonical_sha(record),
                "recovery_action":"REBUILD_EQUIVALENT_48_CONTRACTS_IN_EXPLICIT_DRIVER",
                "affected_frames":len(probe["frames_requiring_projection"]),
                "visual_frames":probe["visual_frames"],
                "attempts_reserved":0,"visual_review_pass":False}
    except (OSError,ValueError,RuntimeError,TypeError,IndexError,KeyError,
            AttributeError,ImportError):
        return denied("PROMPT_RECOVERY_READONLY_EVIDENCE_FAILED")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episode",required=True)
    report=inspect(Path(parser.parse_args().episode))
    print(json.dumps(report,ensure_ascii=False,sort_keys=True))
    return 0 if report["status"]==STATUS else 2


if __name__=="__main__":
    raise SystemExit(main())
