#!/usr/bin/env python3
"""Compare a local Episode stage projection with canonical MySQL read-only stage.

No writes, reconciliation attempts, network model calls, or local file repair.
Canonical Stage must be from the official read-only stage script, not a file.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import storyos_codex_managed as native

ROOT=Path(__file__).resolve().parents[1]

def inspect(episode:Path,*,root:Path=ROOT,stage_probe=None)->dict:
    base={"status":"BLOCKED","canonical_stage_authoritative":False,
          "read_only":True,"sql_writes":0,"model_calls":0,
          "local_stage":None,"canonical_mysql_stage":None}
    root=Path(root).resolve()
    ep=Path(episode).resolve()
    if not ep.is_dir() or not ep.is_relative_to(root/"episodes"):
        return {**base,"status":"EPISODE_PATH_INVALID"}
    local=ep/"meta"/"episode-state.json"
    try:
        obj=json.loads(local.read_text(encoding="utf-8"))
        if not isinstance(obj,dict):
            raise ValueError("invalid file")
        local_stage=obj.get("current_state")
        if not isinstance(local_stage,str) or not local_stage.strip():
            raise ValueError("missing current_state")
    except (OSError,ValueError,UnicodeError):
        return {**base,"status":"LOCAL_PROJECTION_UNAVAILABLE"}
    result={**base,"local_stage":local_stage,
            "episode":ep.relative_to(root).as_posix()}
    if stage_probe is None:
        try:
            env=native.native_environment()
            stage_probe=lambda ref:native._probe(env,"scripts/storyos_episode_stage_readonly.py",["--episode",ref])
        except (OSError,ValueError):
            return {**result,"status":"MYSQL_AUTHORITY_UNVERIFIED"}
    try:
        rc,stage=stage_probe(result["episode"])
    except Exception:
        return {**result,"status":"MYSQL_AUTHORITY_UNVERIFIED"}
    if (not isinstance(stage,dict) or stage.get("source")!="mysql"
            or stage.get("status") not in ("STAGE_ELIGIBLE","ALREADY_PUBLISH_READY")
            or not isinstance(stage.get("stage"),str)):
        return {**result,"status":"MYSQL_AUTHORITY_UNVERIFIED"}
    if rc not in (0,2) or (rc==2 and stage["status"]!="ALREADY_PUBLISH_READY"):
        return {**result,"status":"MYSQL_AUTHORITY_UNVERIFIED"}
    return {**result,"status":"IN_SYNC" if local_stage==stage["stage"] else "STAGE_DRIFT",
            "canonical_mysql_stage":stage["stage"],
            "canonical_stage_authoritative":True,
            "reason":None if local_stage==stage["stage"] else "LOCAL_FILE_NOT_CANONICAL",
            "requires_write_to_repair":local_stage!=stage["stage"]}

def main(argv=None)->int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("episode")
    args=parser.parse_args(argv)
    result=inspect(native.ROOT/args.episode)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))
    return 0 if result["status"]=="IN_SYNC" else 2

if __name__=="__main__":
    raise SystemExit(main())
