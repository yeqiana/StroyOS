#!/usr/bin/env python3
"""Read-only pre-dispatch Story Critic authority, under canonical runtime.env.

Distinguishes DAG reuses from two real bounded Critic attempts. Nothing written.
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from pathlib import Path
import storyos_codex_managed as native


def inspect(episode: str) -> dict:
    blocked={"status":"AUTHORITIES_UNVERIFIED","read_only":True,
             "model_calls":0,"sql_writes":0,"can_dispatch_model":False}
    try:
        ep=native.canonical_episode(episode)
        env=native.native_environment()
        ref=ep.relative_to(native.ROOT).as_posix()
        rc,stage=native._probe(env,"scripts/storyos_episode_stage_readonly.py",
                               ["--episode",ref])
        if (rc!=0 or not isinstance(stage,dict)
                or stage.get("status")!="STAGE_ELIGIBLE"
                or stage.get("source")!="mysql"
                or stage.get("stage")!="STORYBOARD_LOCKED"):
            return {**blocked,"status":"MYSQL_STORYBOARD_STAGE_UNVERIFIED"}
        os.environ.update(env)
        system=str(native.SYSTEM)
        if system not in sys.path:
            sys.path.insert(0,system)
        import product_review_adapter as requests
        import story_review
        import workflow_step_protocol as protocol
        import story_review_attempt_admission as authority
        rows={}
        candidate_presence={}
        for i in (1,2):
            path=requests.request_path(ep,"story-semantic",attempt=i)
            if requests._request_exists(path):
                rows[i]=requests._read_json(path)
                source=str(rows[i].get("candidate_path") or "")
                target=(native.ROOT/source).resolve() if source else native.ROOT
                candidate_presence[i]=bool(source and
                    target.is_relative_to(native.ROOT) and target.is_file())
        official=story_review.load_review(ep)
        checkpoint=protocol.load_state(ep)
        prev=((checkpoint.get("steps") or {}).get("CREATIVE_STORY") or {})
        dag_attempt=int(prev.get("attempt") or 0)+1
        verdict=authority.decide(
            dag_attempt=dag_attempt,
            official_review=official if isinstance(official,dict) else None,
            request_rows=rows,candidate_exists=candidate_presence)
        # Reconfirm mysql identity after all lifecycle observations.
        latest_rc,latest=native._probe(env,"scripts/storyos_episode_stage_readonly.py",
                                       ["--episode",ref])
        if latest_rc!=rc or latest!=stage:
            return {**blocked,"status":"MYSQL_STAGE_CHANGED_DURING_READ"}
        return {**blocked,"episode":ref,"status":verdict["status"],
                "dag_counter_not_review_attempt":dag_attempt,
                "official_review_present":isinstance(official,dict),
                "scoped_review_requests":{str(k):str(v.get("status") or "UNKNOWN")
                                          for k,v in rows.items()},
                "bounded_review_attempt":verdict.get("attempt"),
                "can_dispatch_model":False,
                "next_step":"RECONCILE_OFFICIAL_STORY_REVIEW_LIFECYCLE"
                    if verdict["return_code"]==22 else
                    "CANONICAL_STORY_REVIEW_EXECUTOR_WITH_FRESH_AUTHORITY"}
    except Exception:
        return blocked


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("episode")
    result=inspect(parser.parse_args(argv).episode)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))
    return 0 if result["status"]=="DISPATCH_BOUNDED_STORY_CRITIC" else 2


if __name__=="__main__":
    raise SystemExit(main())
