#!/usr/bin/env python3
"""R9 native production state probe: read-only, never a Driver/Provider dispatcher.

A live Driver heartbeat does NOT attest an image-tool call or its paid receipt.
The only Stage authority is canonical MySQL; unknown Attempts never get retried.
"""
from __future__ import annotations

import argparse
import json
import storyos_codex_managed as native


def assess(driver: dict, attempt: dict, stage: dict) -> dict:
    report={"status":"AUTHORITIES_UNVERIFIED",
            "read_only":True,"model_calls":0,"sql_writes":0,
            "publish_ready_verified":False,"image_generation_verified":False,
            "may_retry_paid_attempt":False,"active_attempt_count":0,
            "outcome_unknown_count":0,"driver_running":False}
    if not all(isinstance(x,dict) for x in (driver,attempt,stage)):
        return report
    active=attempt.get("active_attempt_assets")
    unknown=attempt.get("outcome_unknown_assets")
    if (attempt.get("status")!="ATTEMPT_HISTORY_READ_ONLY"
            or not isinstance(active,list) or not isinstance(unknown,list)
            or stage.get("source")!="mysql"
            or stage.get("status") not in ("STAGE_ELIGIBLE","ALREADY_PUBLISH_READY")):
        return report
    report["active_attempt_count"]=len(active)
    report["outcome_unknown_count"]=len(unknown)
    running=(driver.get("driver_state")=="RUNNING"
             and driver.get("liveness")=="ALIVE")
    report["driver_running"]=running
    report["driver_heartbeat_status"]=str(driver.get("heartbeat_status") or "UNVERIFIED")
    report["canonical_mysql_stage"]=stage.get("stage")
    if unknown:
        report["status"]="PAID_ATTEMPT_RECONCILIATION_REQUIRED"
    elif stage.get("stage") in ("PUBLISH_READY","PUBLISHED","DATA_REVIEWED"):
        report["status"]="MYSQL_PUBLISH_READY"
        report["publish_ready_verified"]=True
    elif running and report["driver_heartbeat_status"]=="RETRY_WAIT":
        report["status"]="RUNNING_RETRY_WAIT"
    elif running and not active:
        report["status"]="RUNNING_NO_PAID_ATTEMPT"
    elif running:
        report["status"]="RUNNING_ATTEMPT_UNVERIFIED"
    elif driver.get("driver_state")=="NEVER_STARTED":
        report["status"]="FIRST_START_NOT_REQUESTED"
    else:
        report["status"]="DRIVER_NOT_RUNNING"
    return report


def inspect(episode: str) -> dict:
    """Canonical runtime.env must be applied BEFORE any direct Driver status."""
    try:
        ep=native.canonical_episode(episode)
        env=native.native_environment()
        ref=ep.relative_to(native.ROOT).as_posix()
        rc1,driver=native._probe(env,"episodes/_system/runtime_driver.py",
                                  ["status",ref,"--json"])
        rc2,attempt=native._probe(env,"scripts/storyos_attempt_readonly_preflight.py",
                                   ["--episode",ref])
        rc3,stage=native._probe(env,"scripts/storyos_episode_stage_readonly.py",
                                 ["--episode",ref])
        if rc1!=0 or rc2!=0 or rc3 not in (0,2):
            return assess({}, {}, {})
        return {"episode":ref,**assess(driver,attempt,stage)}
    except (ValueError,OSError):
        return assess({}, {}, {})


def main(argv=None)->int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("episode")
    args=parser.parse_args(argv)
    result=inspect(args.episode)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))
    return 0 if result["status"] not in ("AUTHORITIES_UNVERIFIED",
        "PAID_ATTEMPT_RECONCILIATION_REQUIRED") else 2


if __name__=="__main__":
    raise SystemExit(main())
