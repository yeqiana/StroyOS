#!/usr/bin/env python3
"""Read-only, event-bound recovery proof for a verified post-PASS Character SHA rc4.

Never launches a Driver, changes MySQL/Redis, reserves attempts or grants images.
The ordinary native preflight must still check Stage, live owner, Codex route,
and all active/unknown image Generation Attempts.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
SYSTEM=ROOT/"episodes"/"_system"
if str(SYSTEM) not in sys.path:
    sys.path.insert(0,str(SYSTEM))

STATUS="STORY_RC4_APPROVED_CHARACTER_BINDING_RECOVERABLE"


def _time(value):
    parsed=datetime.fromisoformat(str(value or ""))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("offset-aware time required")
    return parsed


def inspect(episode: Path) -> dict:
    base={"status":"POST_PASS_CHARACTER_RC4_NOT_PROVEN",
          "read_only":True,"model_calls":0,"sql_writes":0,
          "production_authorization":False,"image_entitlement_verified":False}
    def blocked(reason):
        return {**base,"status":reason}
    try:
        import runtime_driver
        import runtime_checkpoint
        import storyos_driver_exit_remediation as exits
        import character_contract
        import episode_state_persistence

        ep=Path(episode).resolve()
        if (not ep.is_dir() or not ep.is_relative_to((ROOT/"episodes").resolve())
                or (episode_state_persistence.load(ep) or {}).get("current_state")!="IDEA_LOCKED"):
            return blocked("EPISODE_OR_STAGE_NOT_ELIGIBLE")
        driver=runtime_driver.status(ep)
        record=driver.get("record")
        if (driver.get("driver_state")!="EXITED"
                or driver.get("exit_code")!="4"
                or driver.get("pid")!=0 or driver.get("liveness")!="DEAD"
                or not isinstance(record,dict)
                or record.get("pid")!=0
                or str(record.get("rc") or "").split(" ",1)[0]!="4"
                or Path(str(record.get("episode") or "")).resolve()!=ep
                or record.get("log")!=driver.get("log")):
            return blocked("DRIVER_NOT_EXACT_TERMINAL_RC4")
        start=_time(record.get("started_at"))
        end=_time(record.get("exited_at"))
        if not start<end:
            return blocked("DRIVER_TEMPORAL_IDENTITY_INVALID")
        logfile=Path(str(record.get("log") or "")).resolve(strict=True)
        if (not logfile.is_relative_to((ep/"meta/runtime/driver-logs").resolve())
                or logfile.is_symlink() or logfile.stat().st_size>16384):
            return blocked("DRIVER_LOG_OUTSIDE_AUTHORITY")
        lines=logfile.read_bytes().splitlines()
        header=(re.fullmatch(
            rb"DRIVER TASK CARRIER pid=([1-9][0-9]*) task=([A-Za-z0-9-]+)",
            lines[0]) if len(lines)==2 else None)
        if (header is None
                or header.group(2).decode("ascii")!=record.get("carrier_task")
                or re.fullmatch(rb"DRIVER EXIT rc=4[ \t]*",lines[1]) is None):
            return blocked("DRIVER_RC4_LOG_MISMATCH")

        # The exact post-PASS rc4 event must be a contract SOURCE SHA failure,
        # not an unrelated story quality, transport, or character identity veto.
        checkpoint=runtime_checkpoint.load(ep,{})
        rows=[r for r in checkpoint.get("step_runs",[]) if
              isinstance(r,dict) and r.get("step")=="CREATIVE_STORY"]
        if not rows:
            return blocked("STORY_RC4_CHECKPOINT_MISSING")
        last=rows[-1]
        note=str(last.get("note") or "")
        if (last.get("status")!="BLOCKED"
                or last.get("returncode")!=4
                or re.search(r"(?m)^CHARACTER CONTRACT FAIL\s*$",note) is None
                or re.search(r"(?m)^final Story review source SHA drift\s*$",note) is None
                or "WORLD IDENTITY FAIL" in note
                or "POSTCONDITION FAIL" in note
                or not(start<=_time(last.get("finished_at"))<end+timedelta(seconds=1))):
            return blocked("CURRENT_RC4_NOT_CHARACTER_SOURCE_SHA_ONLY")
        trace=ep/"meta/runtime/trace-events.jsonl"
        if not trace.is_file() or trace.stat().st_size>2000000:
            return blocked("CURRENT_RC4_TRACE_UNVERIFIED")
        latest_failure=None
        for line in trace.read_text(encoding="utf-8-sig").splitlines():
            if '"STEP_FAILED"' not in line or '"CREATIVE_STORY"' not in line:
                continue
            row=json.loads(line)
            if row.get("event_type")=="STEP_FAILED" and row.get("step")=="CREATIVE_STORY":
                latest_failure=row
        if (not isinstance(latest_failure,dict)
                or latest_failure.get("failure_class")!="4"
                or not (start<=_time(latest_failure.get("timestamp"))<end+timedelta(seconds=1))):
            return blocked("CURRENT_RC4_TRACE_IDENTITY_UNVERIFIED")
        approval=character_contract.approved_story_rebind(ep,write=False)
        if approval.get("status")!="VERIFIED_REBIND_READY":
            return blocked("OFFICIAL_STORY_CHARACTER_BIND_NOT_REBIND_READY:"
                           +str(approval.get("status") or "UNKNOWN"))
        record_sha=exits.canonical_sha(record)
        latest=runtime_driver.status(ep)
        if (latest.get("record")!=record or latest.get("driver_state")!="EXITED"
                or latest.get("liveness")!="DEAD"):
            return blocked("DRIVER_IDENTITY_CHANGED_DURING_CHECK")
        return {**base,"status":STATUS,"driver_record_sha256":record_sha,
                "official_story_sha256":approval["bind"]["story_sha256"],
                "previous_character_story_sha256":approval["bind"]["previous_story_sha256"],
                "review_attempt":approval["bind"]["review_attempt"],
                "binding_action":"CAS_APPEND_ONLY_WITHIN_EXPLICIT_DRIVER",
                "story_gate_verified":True}
    except Exception:
        return blocked("POST_PASS_CHARACTER_REBIND_EVIDENCE_READ_ERROR")


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episode",required=True)
    result=inspect(Path(parser.parse_args().episode))
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))
    return 0 if result["status"]==STATUS else 2


if __name__=="__main__":
    raise SystemExit(main())
