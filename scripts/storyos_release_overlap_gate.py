#!/usr/bin/env python3
"""Fail-closed read-only preview for merging the reviewed StoryOS PR to main.

Never modifies refs, index, worktree or remote. Does not turn a diagnostic
into permission to overwrite live production/uncommitted files.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def decide(*, main_commit: str, feature_commit: str, remote_main: str,
           ancestry_ok: bool, dirty: list[str], incoming: list[str]) -> dict:
    result = {
        "status":"BLOCKED","read_only":True,"git_writes":0,
        "may_merge_primary":False,"may_dispatch_paid_model":False,
        "main_commit":main_commit,"feature_commit":feature_commit,
        "dirty_count":len(dirty),"incoming_count":len(incoming),
        "overlap":sorted(set(dirty) & set(incoming)),
    }
    if (not main_commit or not feature_commit or not remote_main
            or remote_main!=main_commit):
        return {**result,"status":"REMOTE_MAIN_CHANGED"}
    if not ancestry_ok:
        return {**result,"status":"FEATURE_NOT_DESCENDANT_OF_MAIN"}
    if result["overlap"]:
        return {**result,"status":"DIRTY_FILE_OVERLAP_REFUSE_MAIN_MERGE"}
    return {**result,"status":"REVIEWABLE_FF_CANDIDATE"}


def _run(root: Path, *args: str) -> bytes:
    p=subprocess.run(["git","-C",str(root),*args],capture_output=True,
                     timeout=35,check=False)
    if p.returncode:
        raise RuntimeError("GIT_READ_ONLY_EVIDENCE_UNAVAILABLE")
    return p.stdout


def _paths(root: Path, *args: str) -> list[str]:
    result=_run(root,*args)
    return [b.decode("utf-8","strict") for b in result.split(b"\0") if b]


def inspect(root: Path, feature: str) -> dict:
    base={"status":"GIT_EVIDENCE_UNAVAILABLE","may_merge_primary":False,
          "read_only":True,"git_writes":0,"may_dispatch_paid_model":False}
    try:
        root=Path(root).resolve()
        if not (root/".git").is_dir():
            return {**base,"status":"PRIMARY_CHECKOUT_REQUIRED"}
        # Remote may advance while we read; a later merge must re-check.
        main=_run(root,"rev-parse","--verify","HEAD").decode().strip()
        candidate=_run(root,"rev-parse","--verify",feature).decode().strip()
        remote=_run(root,"ls-remote","--heads","origin",
                    "story-platform-v3-rever").split()
        if len(remote)!=2 or remote[1]!=b"refs/heads/story-platform-v3-rever":
            return base
        latest=remote[0].decode("ascii")
        # First-class decoded -z paths, avoids Windows quoted UTF-8 misparse.
        tracked=set(_paths(root,"diff","--name-only","-z"))
        tracked.update(_paths(root,"diff","--cached","--name-only","-z"))
        untracked=set(_paths(root,"ls-files","--others","--exclude-standard","-z"))
        changed=_paths(root,"diff","--name-only","-z",
                       main,candidate)
        ancestor=subprocess.run(["git","-C",str(root),
            "merge-base","--is-ancestor",main,candidate],
            capture_output=True,timeout=30,check=False).returncode==0
        result=decide(main_commit=main,feature_commit=candidate,
                      remote_main=latest,ancestry_ok=ancestor,
                      dirty=sorted(tracked | untracked),incoming=changed)
        result["tracked_dirty_count"]=len(tracked)
        result["untracked_count"]=len(untracked)
        if _run(root,"rev-parse","--verify","HEAD").decode().strip()!=main:
            return {**base,"status":"MAIN_CHANGED_DURING_AUDIT"}
        return result
    except Exception:
        return base


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--feature",
        default="fix/storyos-r13-review-integration-20261013")
    args=parser.parse_args(argv)
    data=inspect(Path(args.root),args.feature)
    print(json.dumps(data,ensure_ascii=False,sort_keys=True))
    # Informational only: never return an executable merge permit.
    return 0 if data["status"]=="REVIEWABLE_FF_CANDIDATE" else 2


if __name__=="__main__":
    raise SystemExit(main())
