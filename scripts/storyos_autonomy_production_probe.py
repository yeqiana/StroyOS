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
            "outcome_unknown_count":0,"driver_running":False,
            "previous_driver_start_verified":False,
            "historical_attempt_rows":None}
    if not all(isinstance(x,dict) for x in (driver,attempt,stage)):
        return report
    active=attempt.get("active_attempt_assets")
    unknown=attempt.get("outcome_unknown_assets")
    unverifiable=attempt.get("unverified_status_assets",[])
    historical=attempt.get("attempt_rows",0)
    attempt_status=str(attempt.get("status") or "")
    permitted_statuses={"ATTEMPT_HISTORY_READ_ONLY","OUTCOME_UNKNOWN_BLOCKED",
                        "ACTIVE_ATTEMPT_BLOCKED","UNVERIFIED_ATTEMPT_STATUS_BLOCKED"}
    if (attempt_status not in permitted_statuses
            or not isinstance(active,list) or not isinstance(unknown,list)
            or not isinstance(unverifiable,list)
            or type(historical) is not int or historical < 0
            or stage.get("source")!="mysql"
            or stage.get("status") not in ("STAGE_ELIGIBLE","ALREADY_PUBLISH_READY")):
        return report
    # The MySQL readonly preflight exits 2 on a trusted UNKNOWN/ACTIVE
    # diagnosis. Do not erase it into generic AUTHORITIES_UNVERIFIED; nor
    # accept a claimed blocked status without its matching asset evidence.
    if (attempt_status == "OUTCOME_UNKNOWN_BLOCKED" and not unknown
            or attempt_status == "ACTIVE_ATTEMPT_BLOCKED" and not active
            or attempt_status == "UNVERIFIED_ATTEMPT_STATUS_BLOCKED" and not unverifiable):
        return report
    report["historical_attempt_rows"]=historical
    report["active_attempt_count"]=len(active)
    report["outcome_unknown_count"]=len(unknown)
    running=(driver.get("driver_state")=="RUNNING"
             and driver.get("liveness")=="ALIVE")
    report["driver_running"]=running
    report["driver_heartbeat_status"]=str(driver.get("heartbeat_status") or "UNVERIFIED")
    report["canonical_mysql_stage"]=stage.get("stage")
    if unknown or unverifiable or attempt_status != "ATTEMPT_HISTORY_READ_ONLY":
        report["status"]="PAID_ATTEMPT_RECONCILIATION_REQUIRED"
    elif stage.get("stage") in ("PUBLISH_READY","PUBLISHED","DATA_REVIEWED"):
        report["status"]="MYSQL_PUBLISH_READY"
        report["publish_ready_verified"]=True
    elif running and report["driver_heartbeat_status"]=="RETRY_WAIT":
        report["status"]="RUNNING_RETRY_WAIT"
    elif running and not active and historical:
        report["status"]="RUNNING_WITH_HISTORICAL_ATTEMPTS"
    elif running and not active:
        report["status"]="RUNNING_NO_PAID_ATTEMPT"
    elif running:
        report["status"]="RUNNING_ATTEMPT_UNVERIFIED"
    elif driver.get("driver_state")=="NEVER_STARTED":
        # An absent volatile Driver record is not evidence that the episode
        # never ran; the Windows carrier may have an earlier completed task.
        report["status"]="DRIVER_HISTORY_UNVERIFIED"
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
        if rc1!=0 or rc2 not in (0,2) or rc3 not in (0,2):
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
