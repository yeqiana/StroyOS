#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Frame01 real-image Canary evidence-only admission, without Provider dispatch.

No independent image launch: official model/image execution must remain inside
the canonical StoryOS five-capacity permit, MySQL Attempt and pixel-review gates.
The existing native Frame01 preflight also explicitly requires independent test
DB/production authority before a paid attempt can ever be approved.
"""
from __future__ import annotations

import argparse
import json

import storyos_codex_managed as native
import storyos_autonomy_native_ready as native_cli


def decide(native_report: dict, baseline: dict, *, episode: str) -> dict:
    """Conservative two-authority evaluation: EVIDENCE_ONLY is NOT approval."""
    result={"status":"BLOCKED","episode":episode,"frame":1,"frame_key":"01",
            "can_dispatch_image":False,"production_authorization":False,
            "model_entitlement_verified":False,"model_calls":0,"sql_writes":0}
    if not isinstance(native_report,dict) or not isinstance(baseline,dict):
        return {**result,"reason":"EVIDENCE_INVALID"}
    ep=native_report.get("episode")
    if ep is not None and ep!=episode:
        return {**result,"reason":"EPISODE_IDENTITY_MISMATCH"}
    source_episode=baseline.get("episode")
    if source_episode is not None and source_episode!=episode:
        return {**result,"reason":"FRAME01_EPISODE_IDENTITY_MISMATCH"}
    if (native_report.get("status")!="READY_TO_START"
            or native_report.get("read_only") is not True
            or native_report.get("production_authorization") is not False
            or native_report.get("model_calls")!=0
            or native_report.get("sql_writes")!=0
            or native_report.get("image_executor")!="CODEX"
            or native_report.get("production_mode")!="CODEX_MANAGED"
            or native_report.get("blockers")):
        return {**result,"reason":"NATIVE_AUTHORITY_UNVERIFIED"}
    stage=native_report.get("episode_stage") or {}
    if stage.get("source")!="mysql" or stage.get("current_state")!="STORYBOARD_LOCKED":
        return {**result,"reason":"STORYBOARD_STAGE_UNVERIFIED"}
    attempt=native_report.get("attempt") or {}
    if (attempt.get("status")!="ATTEMPT_HISTORY_READ_ONLY"
            or attempt.get("active_attempt_assets")
            or attempt.get("outcome_unknown_assets")):
        return {**result,"reason":"GENERATION_ATTEMPT_UNVERIFIED"}
    codex=native_report.get("codex") or {}
    if not all(codex.get(key) is True
               for key in ("mode_ok","bridge_ok","model_client_version_ok")):
        return {**result,"reason":"NATIVE_CODEX_ROUTE_UNVERIFIED"}
    if (baseline.get("status")!="READ_ONLY_EVIDENCE_READY_TEST_DB_STILL_REQUIRED"
            or baseline.get("authorized_to_mutate_production") is not False
            or baseline.get("model_calls")!=0 or baseline.get("sql_writes")!=0):
        return {**result,"reason":"FRAME01_EVIDENCE_UNVERIFIED"}
    return {**result,"status":"EVIDENCE_ONLY",
            "reason":"REAL_IMAGE_TOOL_AND_TEST_DB_STILL_UNVERIFIED",
            "next_step":"INDEPENDENT_AUTHORIZED_CANARY_NOT_THIS_COMMAND"}


def plan(episode: str) -> dict:
    try:
        ep=native.canonical_episode(episode)
        env=native.native_environment()
        ref=ep.relative_to(native.ROOT).as_posix()
        primary=native.preflight(env,episode=ep)
        first_cli=native_cli.report()
        # Existing Frame01 gate is read-only and is the single evidence source.
        rc,baseline=native._probe(env,"scripts/storyos_native_frame01_preflight.py",[ref])
        if rc not in (0,2):
            baseline={}
        # Frame01 MySQL/Attempt/Driver can change while its read-only baseline
        # assessment runs. Recheck the entire canonical scope, not just Stage.
        fresh=native.preflight(env,episode=ep)
        if primary != fresh:
            return {"status":"BLOCKED","reason":"CANARY_AUTHORITY_CHANGED",
                    "can_dispatch_image":False,"production_authorization":False,
                    "model_calls":0,"sql_writes":0,"frame":1}
        final_cli=native_cli.report()
        unavailable={"status":"BLOCKED","reason":"NATIVE_CLI_OR_LOGIN_UNVERIFIED",
                     "can_dispatch_image":False,"production_authorization":False,
                     "model_calls":0,"sql_writes":0,"frame":1}
        if (not isinstance(first_cli,dict)
                or first_cli.get("status")!="NATIVE_AUTH_CONTEXT_READY"
                or first_cli.get("model_calls")!=0 or first_cli.get("sql_writes")!=0
                or first_cli.get("may_start_paid_production") is not False
                or first_cli.get("cli_runner_same_binary_verified") is not True
                or first_cli.get("opencodex_used") is not False):
            return unavailable
        if first_cli != final_cli:
            return {**unavailable,"reason":"NATIVE_CLI_OR_LOGIN_CHANGED"}
        return decide(fresh,baseline,episode=ref)
    except (ValueError,OSError):
        return {"status":"BLOCKED","reason":"ENVIRONMENT_UNVERIFIED",
                "can_dispatch_image":False,"model_calls":0,"sql_writes":0}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command",choices=("plan",))
    parser.add_argument("episode")
    args=parser.parse_args(argv)
    result=plan(args.episode)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))
    return 0 if result["status"]=="EVIDENCE_ONLY" else 2


if __name__=="__main__":
    raise SystemExit(main())
