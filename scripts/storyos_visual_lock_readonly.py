#!/usr/bin/env python3
"""Read-only Visual Lock triage. Never reserves an Attempt or authorizes image tools."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SYSTEM=ROOT/"episodes"/"_system"
for x in (ROOT,SYSTEM):
    if str(x) not in sys.path:sys.path.insert(0,str(x))

EXPECTED_PLAN=((1,"ordinary_baseline"),(16,"worst_capture_condition"),
               (8,"first_major_anomaly"),(17,"high_impact_admission"))
# EXPECTED_PLAN is the original regression sample, NOT the universal frame
# numbering contract: each storyboard selects its own four admission frames.
EXPECTED_ROLES=tuple(role for _,role in EXPECTED_PLAN)


def valid_four_frame_plan(plan:dict|None, *, frame_count:int|None=None)->tuple[int,...]:
    if not isinstance(plan,dict) or plan.get("schema_version",1)!=1:
        return ()
    items=plan.get("items")
    if not isinstance(items,list) or len(items)!=4:
        return ()
    if any(not isinstance(x,dict) for x in items):
        return ()
    if tuple(x.get("role") for x in items)!=EXPECTED_ROLES:
        return ()
    frames=tuple(x.get("frame") for x in items)
    # Episodes may contain 25, 48, or more frames; never hardcode 20 or
    # force baseline frame 01 when the canonical selector legitimately chose
    # an opening selfie in frame 02. Bound by the authoritative episode count
    # when it is supplied by the read-only caller.
    if (frame_count is not None and (type(frame_count) is not int or frame_count<4)
            or any(type(f) is not int or f<1
                   or (frame_count is not None and f>frame_count)
                   for f in frames)
            or len(set(frames))!=4):
        return ()
    return frames


def classify(*,stage:str,attempt_status:str,reviews:dict,plan:dict|None,calibration:dict|None,
             frame_count:int|None=None)->dict:
    """Never infer tool entitlement from a text-only probe or a filename."""
    result={"status":"BLOCKED","read_only":True,"model_calls":0,"sql_writes":0,
            "image_generation_called":False,"image_attempt_reserved":False,
            "tool_generation_proven":False,"model_entitlement_verified":False,
            "attempt_status":attempt_status,"episode_stage":stage}
    if attempt_status!="ATTEMPT_HISTORY_READ_ONLY":
        result["reason"]="GENERATION_ATTEMPT_RECONCILIATION_REQUIRED"
        return result
    if stage not in {"STORYBOARD_LOCKED","IMAGE_LOCKED"}:
        result.update(status="NOT_APPLICABLE",reason="EPISODE_NOT_AT_VISUAL_ADMISSION_STAGE")
        return result
    frames=valid_four_frame_plan(plan,frame_count=frame_count)
    if not frames:
        result["reason"]="OFFICIAL_VISUAL_LOCK_FOUR_FRAME_PLAN_MISSING_OR_DRIFTED"
        return result
    decisions=(calibration or {}).get("items")
    result["admission_frames"]=list(frames)
    result["pending_admission_items"]=sum(
        isinstance(x,dict) and x.get("decision")=="pending" for x in decisions
    ) if isinstance(decisions,list) else None
    result["review_states"]={key:reviews.get(key) for key in
                              ("authenticity","visual_admission","continuity")}
    if reviews.get("visual_admission")=="passed":
        result.update(status="REVIEW_PASS_REQUIRES_INDEPENDENT_PROVENANCE",
                      reason="REVIEW_PASS_DOES_NOT_PROVE_NATIVE_IMAGE_TOOL_ENTITLEMENT")
    else:
        result["reason"]="REAL_NATIVE_IMAGE_PIXEL_PROOF_NOT_YET_ESTABLISHED"
    return result

def main(argv:list[str]|None=None)->int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episode",required=True)
    args=parser.parse_args(argv)
    try:
        import episode_state_persistence
        import story_json,storyos_attempt_readonly_preflight as attempts
        import storage_config
        from platform.repository.mysql.mysql_connection import MySqlConnection
        from platform.repository.mysql.schema_v2 import DATABASE_NAME
        episode,episode_id=attempts.canonical_episode(args.episode)
        settings=storage_config.mysql_connection_kwargs({"database":DATABASE_NAME})
        if not settings.get("password"):raise ValueError("MYSQL_CREDENTIAL_MISSING")
        db=MySqlConnection(**settings)
        try:history=attempts.inspect_attempt_history(db,episode_id=episode_id)
        finally:db.close()
        state,source=episode_state_persistence.load_with_source(episode)
        if source!="mysql" or not isinstance(state,dict):
            raise ValueError("MYSQL_STAGE_NOT_AUTHORITATIVE")
        gates=story_json.read_json(episode/"meta/story-gates.json")
        plan_path=episode/"meta/visual-lock-plan.json"
        plan=story_json.read_json(plan_path) if plan_path.is_file() else None
        import frame_contract
        result=classify(
            stage=str(state.get("current_state") or state.get("state") or ""),
            attempt_status=str(history.get("status") or ""),
            reviews=gates.get("reviews") or {},plan=plan,
            frame_count=frame_contract.frame_count(episode),
            calibration=(gates.get("visual") or {}).get("calibration") or {})
        result.update(episode=episode.relative_to(ROOT).as_posix(),
                      stage_source=source,visual_lock_plan_present=plan_path.is_file(),
                      active_attempt_assets=history.get("active_attempt_assets",[]),
                      outcome_unknown_assets=history.get("outcome_unknown_assets",[]))
    except Exception as exc:
        result={"status":"BLOCKED","reason":"VISUAL_LOCK_READONLY_AUTHORITY_CHECK_FAILED",
                "error_type":type(exc).__name__,"read_only":True,"model_calls":0,
                "sql_writes":0,"image_generation_called":False,
                "image_attempt_reserved":False}
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))
    return 2 if result.get("reason")=="VISUAL_LOCK_READONLY_AUTHORITY_CHECK_FAILED" else 0

if __name__=="__main__":
    raise SystemExit(main())
