"""Strict read-only rc24 driver reentry after TWO user-risk-acknowledged network retries.

ONLY Episode14 F020/F027. Does not generate, restart, grant extra
Attempt or release the three unrelated safety-refused frames.
"""
from __future__ import annotations
import sys
from pathlib import Path

# This script is spawned as a standalone CLI by storyos_production_env.py.
# The script directory is episodes/_system, not the repository root. Install
# canonical package paths BEFORE imports can resolve Python's stdlib
# `platform` in place of StoryOS's platform.repository package.
ROOT=Path(__file__).resolve().parents[2]
for package_dir in (ROOT/"scripts", ROOT):
    if str(package_dir) not in sys.path:
        sys.path.insert(0,str(package_dir))

import hashlib
import json

import generation_attempt_authority as attempts
import logical_asset_identity
import native_network_failure_rearm as network
import runtime_driver
import scheduler_core
import storyos_driver_exit_remediation as exit_remediation

EP=ROOT/"episodes"/"00_独立篇"/"14_深渊疗愈所_第一集_净土生命还原"
OLD_DRIVER_SHA="1ff8f3103600802d7dfb40041142f3937bc1f9973cf3fb08dae4fe9d809c7620"
OLD_LOG_SHA="3e92fd6f78bfb4d4ede6733fcbcfa839f185e0469e383cff611cb8fc80e9cf33"
NETWORK_FRAMES=frozenset({20,27})
SAFETY_FRAMES=frozenset({9,29,48})


def verify_rearmed(ep:Path)->dict:
    ep=Path(ep).resolve()
    deny=lambda reason: {"status":"BLOCKED","reason":reason,"read_only":True,
                         "model_calls":0,"sql_writes":0}
    if ep!=EP.resolve():
        return deny("EPISODE_NOT_IN_EXACT_SCOPE")
    d=runtime_driver.status(ep)
    record=d.get("record") or {}
    if (d.get("driver_state")!="EXITED" or d.get("liveness")!="DEAD"
        or int(d.get("pid") or 0)!=0 or str(d.get("exit_code"))!="24"
        or exit_remediation.canonical_sha(record)!=OLD_DRIVER_SHA):
        return deny("HISTORICAL_RC24_DRIVER_NOT_EXACT")
    driver_log=Path(str(record.get("log") or "")).resolve()
    if (not driver_log.is_relative_to(ep/"meta/runtime/driver-logs")
        or not driver_log.is_file()
        or hashlib.sha256(driver_log.read_bytes()).hexdigest()!=OLD_LOG_SHA):
        return deny("HISTORICAL_RC24_LOG_CHANGED")
    q=scheduler_core.load_queue(ep)
    rows=[x for x in q.get("items") or [] if x.get("scope")=="batch"]
    if (len(rows)!=44
        or len({int(x.get("frame") or 0) for x in rows})!=44
        or sum(x.get("status")=="generated" for x in rows)!=39):
        return deny("HISTORICAL_NATIVE_BATCH_COUNT_DRIFT")
    blocked=[x for x in rows if x.get("status")=="external_blocked"]
    queued=[x for x in rows if x.get("status")=="queued"]
    if ({int(x["frame"]) for x in blocked}!=SAFETY_FRAMES
        or {int(x["frame"]) for x in queued}!=NETWORK_FRAMES
        or any(x.get("status") not in ("generated","external_blocked","queued") for x in rows)):
        return deny("ONLY_BOUNDED_NETWORK_ATTEMPT_2_MAY_RUN")
    for x in blocked:
        if (x.get("no_automatic_original_prompt_retry") is not True
                or x.get("requires_content_revision") is not True
                or not x.get("provider_safety_refusal_receipt_sha256")):
            return deny("SAFETY_REFUSAL_QUEUE_PROTECTION_MISSING")
        frame=int(x["frame"])
        key=logical_asset_identity.frame_asset_key(ep,frame)
        state=attempts.load_asset_state(ep,key) or {}
        first=attempts.load_attempt(ep,key,1) or {}
        if (int(state.get("attempts_consumed") or 0)!=1
            or state.get("active_attempt_index") is not None
            or first.get("status")!="FAILED_AFTER_DISPATCH"
            or first.get("failure_class")!="IMAGE_PROVIDER_SAFETY_REJECTED"
            or bool(attempts.load_attempt(ep,key,2))):
            return deny("SAFETY_REFUSAL_ATTEMPT_DRIFT")
    for x in queued:
        if (not network.remaining_second_attempt(ep,x)
                or int(x.get("frame") or 0) not in NETWORK_FRAMES):
            return deny("NETWORK_ATTEMPT_2_WORKER_PROOF_DENIED")
    import image_scheduler
    ready,blocked_by_dependency=image_scheduler.ready_items(ep,q)
    if {int(x["frame"]) for x in ready}!=NETWORK_FRAMES:
        return deny("NETWORK_FRAMES_NOT_EXACTLY_RUNNABLE")
    return {
        "status":"EP14_RC24_F020_F027_ATTEMPT2_AUTHORIZED_REENTRY",
        "driver_record_sha256":OLD_DRIVER_SHA,
        "driver_log_sha256":OLD_LOG_SHA,
        "frames":sorted(NETWORK_FRAMES),
        "safety_refusals_still_blocked":sorted(SAFETY_FRAMES),
        "remaining_real_attempt_budget_per_frame":1,
        "upstream_first_attempt_billing_unverified":True,
        "read_only":True,"model_calls":0,"sql_writes":0,
        "production_authorization":False,
    }


if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument("--episode",type=Path,required=True)
    parser.add_argument("--verify-rearmed",action="store_true",required=True)
    args=parser.parse_args()
    report=verify_rearmed(args.episode)
    print(json.dumps(report,ensure_ascii=False))
    raise SystemExit(0 if report["status"].startswith("EP14_RC24_") else 2)
