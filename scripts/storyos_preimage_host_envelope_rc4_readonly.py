#!/usr/bin/env python3
"""Read-only, event-bound proof that latest rc4 was PREIMAGE Host envelope only.

This does not clear historical failures, reserve starts, dispatch models,
mutate SQL, authorize images or infer any paid tool entitlement.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
SYSTEM=ROOT/"episodes/_system"
if str(SYSTEM) not in sys.path:
    sys.path.insert(0,str(SYSTEM))

STATUS="PREIMAGE_RC4_HOST_ENVELOPE_RECOVERABLE"


def _time(value):
    t=datetime.fromisoformat(str(value or ""))
    if t.tzinfo is None or t.utcoffset() is None:
        raise ValueError("offset aware timestamp required")
    return t


def inspect(episode: Path) -> dict:
    base={"status":"PREIMAGE_RC4_NOT_PROVEN","read_only":True,
          "model_calls":0,"sql_writes":0,"production_authorization":False,
          "image_entitlement_verified":False}
    def refuse(why):return {**base,"status":why}
    try:
        import runtime_driver
        import runtime_checkpoint
        import episode_state_persistence
        import preimage_authority_snapshot as authority
        import preimage_task_contract as tasks
        import preimage_host_receipt_recovery as candidate_recovery
        import storyos_driver_exit_remediation as exits

        ep=Path(episode).resolve()
        if (not ep.is_dir()
                or not ep.is_relative_to((ROOT/"episodes").resolve())
                or (episode_state_persistence.load(ep) or {}).get("current_state")!="STORYBOARD_LOCKED"):
            return refuse("STAGE_OR_EPISODE_NOT_ELIGIBLE")
        driver=runtime_driver.status(ep)
        record=driver.get("record")
        if (driver.get("driver_state")!="EXITED"
                or driver.get("exit_code")!="4"
                or driver.get("pid")!=0 or driver.get("liveness")!="DEAD"
                or not isinstance(record,dict) or record.get("pid")!=0
                or str(record.get("rc") or "").split(" ",1)[0]!="4"
                or Path(str(record.get("episode") or "")).resolve()!=ep
                or driver.get("log")!=record.get("log")):
            return refuse("LATEST_DRIVER_NOT_EXACT_TERMINAL_RC4")
        start,end=_time(record.get("started_at")),_time(record.get("exited_at"))
        if start>=end:
            return refuse("DRIVER_TIME_ORDER_INVALID")
        log=Path(str(record.get("log") or "")).resolve(strict=True)
        if (not log.is_relative_to((ep/"meta/runtime/driver-logs").resolve())
                or log.is_symlink() or log.stat().st_size>16384):
            return refuse("DRIVER_LOG_OUTSIDE_AUTHORITY")
        lines=log.read_bytes().splitlines()
        header=(re.fullmatch(rb"DRIVER TASK CARRIER pid=([1-9][0-9]*) task=([A-Za-z0-9-]+)",
                              lines[0]) if len(lines)==2 else None)
        if (not header or header.group(2).decode()!=record.get("carrier_task")
                or not re.fullmatch(rb"DRIVER EXIT rc=4[ \t]*",lines[1])):
            return refuse("DRIVER_LOG_RC4_IDENTITY_MISMATCH")
        cp=runtime_checkpoint.load(ep,{})
        rows=[r for r in cp.get("step_runs",[]) if
              isinstance(r,dict) and r.get("step")=="PREIMAGE_COMPILE"]
        if not rows:
            return refuse("LATEST_PREIMAGE_RUN_MISSING")
        last=rows[-1]
        if (last.get("status")!="BLOCKED" or last.get("returncode")!=4
                or not start<=_time(last.get("finished_at"))<end+timedelta(seconds=1)):
            return refuse("PREIMAGE_RC4_NOT_LATEST_FAILED_RUN")
        note=json.loads(str(last.get("note") or "").strip())
        if (note.get("status")!="FAILED"
                or any(row.get("status")=="FAILED"
                       and row.get("task_type")!="CHARACTER_FINALIZE"
                       for row in note.get("tasks") or [])
                or not any(row.get("task_type")=="CHARACTER_FINALIZE"
                           and row.get("status")=="FAILED"
                           for row in note.get("tasks") or [])):
            return refuse("OTHER_PREIMAGE_FAILURE_NOT_RESEALABLE")
        trace=ep/"meta/runtime/trace-events.jsonl"
        if not trace.is_file() or trace.stat().st_size>2000000:
            return refuse("CURRENT_PREIMAGE_TRACE_MISSING")
        latest=None
        for line in trace.read_text("utf-8-sig").splitlines():
            if '"STEP_FAILED"' not in line or '"PREIMAGE_COMPILE"' not in line:
                continue
            row=json.loads(line)
            if row.get("event_type")=="STEP_FAILED" and row.get("step")=="PREIMAGE_COMPILE":
                latest=row
        if (not isinstance(latest,dict) or str(latest.get("failure_class"))!="4"
                or not start<=_time(latest.get("timestamp"))<end+timedelta(seconds=1)):
            return refuse("LATEST_PREIMAGE_TRACE_NOT_THIS_EXIT")
        snapshot=authority.build(ep,write=False)
        state=tasks.story_json.read_json(ep/tasks.STATE_REL,default={}) or {}
        if (not snapshot.get("snapshot_id")
                or state.get("snapshot_id")!=snapshot["snapshot_id"]
                or authority.stale_owned(ep,snapshot)):
            return refuse("PREIMAGE_FROZEN_SOURCE_CHANGED")
        taskset=tasks.plan_tasks(ep,snapshot,resume=True)
        for task in taskset:
            if task["task_type"]=="CHARACTER_FINALIZE":
                continue
            row=(state.get("tasks") or {}).get(task["task_type"]) or {}
            if (row.get("status") not in {"COMPLETED","REUSED"}
                    or tasks.verify_candidate(tasks.read_candidate(ep,task) or {},task)):
                return refuse("OTHER_PREIMAGE_TASK_NOT_VERIFIED_COMPLETE")
        task=next(t for t in taskset if t["task_type"]=="CHARACTER_FINALIZE")
        proof=candidate_recovery.inspect(ep,task)
        if proof.get("status")!="ELIGIBLE":
            return refuse("HOST_CANDIDATE_OLD_MODEL_PROOF_INVALID:"+str(proof.get("reason")))
        latest_driver=runtime_driver.status(ep)
        if (latest_driver.get("record")!=record
                or latest_driver.get("liveness")!="DEAD"
                or latest_driver.get("driver_state")!="EXITED"):
            return refuse("DRIVER_CHANGED_DURING_PROOF")
        return {**base,"status":STATUS,
                "driver_record_sha256":exits.canonical_sha(record),
                "candidate_sha256":proof["candidate_sha256"],
                "original_success_call_id":proof["receipt_call_id"],
                "input_snapshot_id":snapshot["snapshot_id"],
                "recovery_action":"HOST_SEAL_WITHOUT_NEW_MODEL"}
    except (ValueError,KeyError,OSError,TypeError,IndexError,StopIteration,AttributeError):
        return refuse("PREIMAGE_RC4_EVIDENCE_READ_ERROR")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episode",required=True)
    out=inspect(Path(parser.parse_args().episode))
    print(json.dumps(out,ensure_ascii=False,sort_keys=True))
    return 0 if out["status"]==STATUS else 2


if __name__=="__main__":
    raise SystemExit(main())
