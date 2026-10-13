#!/usr/bin/env python3
"""Single read-only production go/no-go for native Codex Episode recovery."""
from __future__ import annotations
import argparse
import json
import storyos_autonomy_production_probe as production
import storyos_story_review_readonly as review
import storyos_manifest_relocation as paths


def classify(production_state: dict, review_state: dict, source_plan: dict) -> dict:
    base={"can_auto_dispatch":False,"can_dispatch_image":False,
          "may_retry_paid_attempt":False,"model_calls":0,"sql_writes":0,
          "read_only":True,"status":"UNVERIFIED"}
    if not all(isinstance(x,dict) for x in (production_state,review_state,source_plan)):
        return base
    if (production_state.get("status") in (
        "PAID_ATTEMPT_RECONCILIATION_REQUIRED","AUTHORITIES_UNVERIFIED")
        or production_state.get("outcome_unknown_count",0)
        or production_state.get("active_attempt_count",0)):
        return {**base,"status":"STOP_PAID_ATTEMPT_AUTHORITY"}
    if production_state.get("canonical_mysql_stage") != "STORYBOARD_LOCKED":
        return {**base,"status":"STOP_NON_STORYBOARD_MYSQL_STAGE"}
    review_status=review_state.get("status")
    if review_status=="FINALIZED_REVIEW_WITHOUT_CANONICAL_PROOF":
        return {**base,"status":"STOP_REVIEW_AUTHORITY_MISSING",
                "next_step":"VERIFY_HISTORICAL_SOURCE_AND_NEW_CRITIC_EPOCH"}
    if review_status!="EXISTING_REVIEW_MUST_BE_REVALIDATED":
        return {**base,"status":"STOP_STORY_REVIEW_UNVERIFIED"}
    if source_plan.get("status")=="PATH_RELOCATION_PROVEN":
        return {**base,"status":"STOP_MANIFEST_PATHS_STALE"}
    # A valid Review and migrated Manifest would only allow the canonical DAG
    # preflight, never an independent paid image Provider call.
    return {**base,"status":"CANONICAL_DAG_PREFLIGHT_ONLY"}


def inspect(ep: str) -> dict:
    try:
        result=production.inspect(ep)
        reviewed=review.inspect(ep)
        mapped=paths.plan(ep)
        return {"episode":ep,**classify(result,reviewed,mapped)}
    except Exception:
        return classify({}, {}, {})


def main(argv=None)->int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("episode")
    answer=inspect(parser.parse_args(argv).episode)
    print(json.dumps(answer,ensure_ascii=False,sort_keys=True))
    return 0 if answer["status"]=="CANONICAL_DAG_PREFLIGHT_ONLY" else 2

if __name__=="__main__":
    raise SystemExit(main())
