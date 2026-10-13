#!/usr/bin/env python3
"""Repair ONLY byte-identical source-document paths after a recorded Git rename.

Never change a Review, MySQL, image Attempt or production authority. Changes
only release-manifest.artifacts under a single acknowledged, stopped Episode.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

import storyos_codex_managed as native
import storyos_relocated_review_recovery as evidence


def plan(episode: str) -> dict:
    base={"status":"REFUSED","read_only":True,"model_calls":0,
          "mysql_writes":0,"review_writes":0,"can_dispatch_image":False}
    try:
        ep=native.canonical_episode(episode)
        root=native.ROOT
        manifest_path=ep/"meta/release-manifest.json"
        manifest=json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        req=ep/"meta/runtime/reviews/story-semantic-attempt-2-request.json"
        source=json.loads(req.read_text(encoding="utf-8-sig"))
        if source.get("status")!="FINALIZED" or source.get("attempt")!=2:
            return {**base,"status":"REVIEW_REQUEST_UNVERIFIED"}
        relocated=evidence.verify_relocated_artifacts(
            root,ep,manifest,source.get("source_files") or [],check_all_frozen_sources=False)
        if relocated["status"]!="GIT_RENAME_AND_REVIEW_SHA_VERIFIED":
            return {**base,"status":relocated["status"]}
        full=evidence.verify_relocated_artifacts(
            root,ep,manifest,source.get("source_files") or [])
        return {**base,"status":"PATH_RELOCATION_PROVEN",
                "episode":ep.relative_to(root).as_posix(),
                "manifest_sha256":evidence.sha256_file(manifest_path),
                "request_sha256":evidence.sha256_file(req),
                "paths":relocated["paths"],
                "legacy_review_replay_allowed":full["status"]=="GIT_RENAME_AND_REVIEW_SHA_VERIFIED",
                "review_replay_blocker":None if full["status"]=="GIT_RENAME_AND_REVIEW_SHA_VERIFIED" else full["status"]}
    except Exception as exc:
        return {**base,"status":"RELOCATION_EVIDENCE_UNAVAILABLE",
                "failure_kind":type(exc).__name__}


def apply(episode: str, expected: dict) -> dict:
    base={"status":"REFUSED","manifest_writes":0,"model_calls":0,
          "mysql_writes":0,"review_writes":0,"can_dispatch_image":False}
    ep=native.canonical_episode(episode)
    root=native.ROOT
    # An active feature Worktree has a .git file; never apply a production
    # Episode migration against its copied fixtures/artifacts.
    if (root/".git").is_file():
        return {**base,"status":"NOT_PRIMARY_CHECKOUT"}
    git=subprocess.run(["git","rev-parse","--show-toplevel"],cwd=root,
                       capture_output=True,text=True,timeout=15)
    if git.returncode!=0 or Path(git.stdout.strip()).resolve()!=root.resolve():
        return {**base,"status":"NONPRIMARY_CHECKOUT"}
    fresh=plan(episode)
    fences=("status","manifest_sha256","request_sha256","paths")
    if expected.get("status")!="PATH_RELOCATION_PROVEN" or any(
        expected.get(x)!=fresh.get(x) for x in fences):
        return {**base,"status":"EVIDENCE_CHANGED"}
    rc,driver=native._probe(native.native_environment(),
                "episodes/_system/runtime_driver.py",
                ["status",fresh["episode"],"--json"])
    if rc!=0 or not isinstance(driver,dict):
        return {**base,"status":"DRIVER_AUTHORITY_UNKNOWN"}
    if driver.get("driver_state")=="RUNNING" or driver.get("liveness")=="ALIVE":
        return {**base,"status":"DRIVER_ACTIVE"}
    path=ep/"meta/release-manifest.json"
    original=path.read_bytes()
    if hashlib.sha256(original).hexdigest()!=fresh["manifest_sha256"]:
        return {**base,"status":"MANIFEST_CHANGED"}
    data=json.loads(original.decode("utf-8-sig"))
    for field,files in fresh["paths"].items():
        if data.get("artifacts",{}).get(field)!=files["old"]:
            return {**base,"status":"SOURCE_PATH_CHANGED"}
        data["artifacts"][field]=files["new"]
    # Single small atomic file replacement: other Evidence files remain intact.
    import os
    import tempfile
    fd,temp=tempfile.mkstemp(prefix=".release-manifest-r11-",suffix=".json",dir=path.parent)
    try:
        with os.fdopen(fd,"w",encoding="utf-8",newline="\n") as stream:
            json.dump(data,stream,ensure_ascii=False,indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp,path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    after=json.loads(path.read_text(encoding="utf-8-sig"))
    if any(after["artifacts"][k]!=v["new"] for k,v in fresh["paths"].items()):
        return {**base,"status":"MANIFEST_READBACK_MISMATCH","manifest_writes":1}
    return {**base,"status":"SOURCE_PATHS_RELOCATED",
            "manifest_writes":1,
            "review_replay_blocker":fresh["review_replay_blocker"],
            "next_step":"INDEPENDENT_CRITIC_AUTHORITY_RECONCILIATION"}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("episode")
    parser.add_argument("--apply",action="store_true")
    parser.add_argument("--ack-real-production",action="store_true")
    args=parser.parse_args(argv)
    outcome=plan(args.episode)
    if args.apply:
        outcome=apply(args.episode,outcome) if args.ack_real_production else {
            "status":"PRODUCTION_ACK_REQUIRED","can_dispatch_image":False}
    print(json.dumps(outcome,ensure_ascii=False,sort_keys=True))
    return 0 if outcome.get("status") in ("PATH_RELOCATION_PROVEN","SOURCE_PATHS_RELOCATED") else 2

if __name__=="__main__":
    raise SystemExit(main())
