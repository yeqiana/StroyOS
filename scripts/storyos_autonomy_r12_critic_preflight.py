#!/usr/bin/env python3
"""Never grants image production; admits exactly one new native text Critic.

Checks true MySQL Stage, Attempt UNKNOWN, Driver singleton, native login and
all historical source SHA evidence. No outgoing model call, no DB/FS writes.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import storyos_codex_managed as native


def decide(*, stage:dict, paid:dict, driver:dict, codex:dict, review:dict)->dict:
    base={"status":"BLOCKED","read_only":True,"model_calls":0,
          "sql_writes":0,"can_dispatch_image":False,
          "may_start_new_text_review":False}
    if any(not isinstance(x,dict) for x in (stage,paid,driver,codex,review)):
        return {**base,"status":"SOURCE_UNVERIFIED"}
    if (stage.get("source")!="mysql" or stage.get("status")!="STAGE_ELIGIBLE"
        or stage.get("stage")!="STORYBOARD_LOCKED"):
        return {**base,"status":"MYSQL_STAGE_UNVERIFIED"}
    if (paid.get("status")!="ATTEMPT_HISTORY_READ_ONLY"
        or paid.get("active_attempt_assets") or paid.get("outcome_unknown_assets")
        or paid.get("unverified_status_assets")):
        return {**base,"status":"IMAGE_ATTEMPT_AUTHORITY_UNVERIFIED"}
    if (driver.get("driver_state")=="RUNNING"
        or driver.get("liveness")=="ALIVE"
        or driver.get("driver_state") not in ("NEVER_STARTED","STOPPED","EXITED","DRIVER_NOT_RUNNING")):
        return {**base,"status":"DRIVER_SINGLETON_UNVERIFIED"}
    if (codex.get("status")!="NATIVE_AUTH_CONTEXT_READY"
        or codex.get("opencodex_used") is not False
        or codex.get("interactive_codex_auth_context_present") is not True):
        return {**base,"status":"NATIVE_CODEX_AUTH_UNVERIFIED"}
    if review.get("status")!="ONE_SHOT_NEW_CRITIC_EPOCH_READY" or review.get("attempt")!=9:
        return {**base,"status":"RUBRIC_REVIEW_AUTHORITY_UNVERIFIED"}
    return {**base,"status":"READY_FOR_ONE_SHOT_NATIVE_TEXT_REVIEW",
            "may_start_new_text_review":True,
            "review_attempt":9,"review_scope":"MIGRATED_EPISODE_RUBRIC_REVALIDATION"}


def inspect(episode:str)->dict:
    try:
        ep=native.canonical_episode(episode)
        env=native.native_environment()
        ref=ep.relative_to(native.ROOT).as_posix()
        a,stage=native._probe(env,"scripts/storyos_episode_stage_readonly.py",["--episode",ref])
        b,attempts=native._probe(env,"scripts/storyos_attempt_readonly_preflight.py",["--episode",ref])
        c,driver=native._probe(env,"episodes/_system/runtime_driver.py",["status",ref,"--json"])
        # Native report is used from scripts and stays strictly read-only.
        import storyos_autonomy_native_ready as ready
        codex=ready.report()
        os.environ.update(env)
        if str(native.SYSTEM) not in sys.path: sys.path.insert(0,str(native.SYSTEM))
        import story_review_rubric_migration as review
        evidence=review.plan(ep)
        if any(x!=0 for x in (a,b,c)):
            return decide(stage={},paid={},driver={},codex={},review={})
        return {"episode":ref,**decide(stage=stage,paid=attempts,
                driver=driver,codex=codex,review=evidence)}
    except Exception:
        return decide(stage={},paid={},driver={},codex={},review={})


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("episode")
    r=inspect(ap.parse_args(argv).episode)
    print(json.dumps(r,ensure_ascii=False,sort_keys=True))
    return 0 if r["may_start_new_text_review"] else 2


if __name__=="__main__":
    raise SystemExit(main())
