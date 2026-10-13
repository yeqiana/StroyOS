#!/usr/bin/env python3
"""StoryOS retired worktree/branch GC: safe dry-run by default.

Only a locally AND remote-main merged, clean, registered, aged worktree under
the repository-owned retirement roots can be removed. Cannot force-remove.
Unexpected process inventory failures, detached/untracked modifications,
unmerged and archive branches all fail closed. No effect on production data.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from functools import lru_cache
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
BRANCH_PREFIXES = ("feature/storyos-", "fix/storyos-", "feat/storyos-",
                   "fix/r", "feature/r", "feat/r")
MIN_AGE_HOURS = 72


def safe_branch(branch: str, *, merged: bool, checked_out: bool) -> bool:
    return (isinstance(branch, str) and branch.startswith(BRANCH_PREFIXES)
            and not checked_out and merged and not any(
                branch.startswith(part) for part in
                ("archive/", "release/", "story-platform-v3-rever", "main", "master")))


def retirement_root_allowed(path: Path) -> bool:
    """Never walk outside known internal worktree areas, including '..' aliases."""
    candidate = Path(path).resolve()
    # The script may itself live in an isolated worktree for tests.
    for checkout in (ROOT, primary_checkout()):
        for rel in (".worktrees", ".storyos/worktrees"):
            parent = (checkout / rel).resolve()
            # A registered worktree must be an immediate child of the
            # retirement root, never arbitrary content nested inside it.
            if candidate.parent == parent:
                return True
    return False


def classify(info: dict) -> dict:
    path = Path(info["path"])
    checks = {
        "registered": info.get("registered") is True,
        "inside_retirement_root": retirement_root_allowed(path),
        "not_primary": info.get("is_primary") is False,
        "merged_in_local_main": info.get("merged_local") is True,
        "merged_in_origin_main": info.get("merged_remote") is True,
        "clean_including_untracked": info.get("clean") is True,
        "older_than_72h": type(info.get("age_hours")) in (int, float)
            and math.isfinite(info["age_hours"])
            and info["age_hours"] >= MIN_AGE_HOURS,
        "no_running_process_references": info.get("process_verification") == "CLEAR",
        "no_other_checkout": info.get("branch_checked_out_elsewhere") is False,
        "allowed_temporary_branch": safe_branch(
            info.get("branch"), merged=info.get("merged_local") is True,
            checked_out=False),
    }
    return {"eligible": all(checks.values()), "checks": checks}


def _git(*args: str, cwd: Path | None = None, timeout: int = 20) -> tuple[int, str]:
    try:
        proc = subprocess.run(["git", "-C", str(cwd or ROOT), *args],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout, check=False)
        return proc.returncode, proc.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return 2, ""


def _worktrees() -> list[dict]:
    rc, output = _git("worktree", "list", "--porcelain")
    if rc:
        return []
    items: list[dict] = []
    for part in output.split("\n\n"):
        raw = {}
        for line in part.splitlines():
            key, _, value = line.partition(" ")
            if key == "worktree":
                raw["path"] = Path(value)
            elif key == "branch":
                raw["branch"] = value.removeprefix("refs/heads/")
            elif key in {"detached", "bare", "locked", "prunable"}:
                raw[key] = True
        if "path" in raw:
            items.append(raw)
    return items


@lru_cache(maxsize=1)
def primary_checkout() -> Path:
    records = _worktrees()
    return records[0]["path"].resolve() if records else ROOT.resolve()


def _process_verification(path: Path) -> str:
    """Inspect OS process cmdlines and cwd; if unable to prove, do not delete."""
    try:
        import psutil
    except ImportError:
        return "UNKNOWN"
    try:
        target = str(path.resolve()).casefold().replace("/", "\\")
        for proc in psutil.process_iter(["pid", "cwd", "cmdline"]):
            try:
                if proc.pid == os.getpid():
                    continue
                details = proc.info
                cwd = str(details.get("cwd") or "").casefold().replace("/", "\\")
                argv = " ".join(details.get("cmdline") or []).casefold().replace("/", "\\")
                if (cwd == target or cwd.startswith(target + "\\")
                        or target in argv):
                    return "ACTIVE"
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                # Cannot prove every process absent when details are denied.
                return "UNKNOWN"
        return "CLEAR"
    except Exception:
        return "UNKNOWN"


def _age_hours(path: Path, branch: str) -> float:
    rc, output = _git("log", "-1", "--format=%ct", branch)
    if rc or not output.isdigit():
        return -1
    try:
        newest = max(int(output), path.stat().st_mtime)
        return max(-1, (time.time() - newest) / 3600)
    except OSError:
        return -1


def plan() -> dict:
    entries = _worktrees()
    primary = primary_checkout()
    info: list[dict] = []
    for record in entries:
        path = record["path"].resolve()
        branch = record.get("branch", "")
        safe_location = retirement_root_allowed(path)
        is_primary = path == primary
        # Avoid walking or executing commands in untrusted external paths.
        clean, local, remote, age, process = False, False, False, -1, "UNKNOWN"
        # Cheap filters first. Older history is evaluated fully; unmerged or
        # recently used worktrees are never probed or unlinked.
        eligible_name = (safe_location and not record.get("locked")
                         and not record.get("prunable")
                         and safe_branch(branch, merged=True, checked_out=False))
        if eligible_name:
            local = _git("merge-base", "--is-ancestor", branch,
                         "story-platform-v3-rever")[0] == 0
            if local:
                remote = _git("merge-base", "--is-ancestor", branch,
                              "origin/story-platform-v3-rever")[0] == 0
            if local and remote:
                age = _age_hours(path, branch)
                if age >= MIN_AGE_HOURS:
                    rclean, status = _git("status", "--porcelain",
                                          "--untracked-files=all", cwd=path)
                    clean = rclean == 0 and not status
                    if clean:
                        process = _process_verification(path)
        item = {"path": str(path), "branch": branch,
                "registered": not record.get("prunable", False),
                "is_primary": is_primary, "merged_local": local,
                "merged_remote": remote, "clean": clean,
                "age_hours": round(age, 1), "process_verification": process,
                "branch_checked_out_elsewhere": False}
        decision = classify(item)
        info.append({**item, **decision})
    return {"status": "DRY_RUN", "worktrees": info,
            "eligible_count": sum(x["eligible"] for x in info)}


def remove_retired(info: dict) -> bool:
    path = Path(info["path"])
    # Revalidate ALL dynamic evidence at the last possible point.
    new = plan()
    row = next((r for r in new["worktrees"]
                if r["path"] == str(path.resolve()) and r["branch"] == info["branch"]), None)
    if not row or not row["eligible"]:
        return False
    rc, _ = _git("worktree", "remove", str(path), timeout=90)
    if rc:
        return False
    # Worktree is already gone. Branch deletion allowed ONLY after merged checks.
    rc, _ = _git("branch", "-d", row["branch"])
    return rc == 0


def execute_plan(items: list[dict], *, apply: bool, acknowledged: bool,
                 max_count: int = 5) -> dict:
    if not apply:
        return {"status": "DRY_RUN", "eligible_count": sum(classify(x)["eligible"] for x in items)}
    if not acknowledged:
        return {"status": "ACK_REQUIRED", "deleted_count": 0}
    if not 1 <= max_count <= 20:
        return {"status": "INVALID_LIMIT", "deleted_count": 0}
    removed = []
    for item in items:
        if len(removed) >= max_count:
            break
        if classify(item)["eligible"] and remove_retired(item):
            removed.append(item["branch"])
    return {"status": "APPLIED", "deleted_count": len(removed), "deleted_branches": removed}




def branch_plan() -> dict:
    """Eligible local branch refs only; never prune remote refs or archive."""
    format_spec = "%(refname:short)%09%(committerdate:unix)"
    local_rc, local_text = _git(
        "for-each-ref", "--merged=story-platform-v3-rever",
        "--format=" + format_spec, "refs/heads")
    remote_rc, remote_text = _git(
        "for-each-ref", "--merged=origin/story-platform-v3-rever",
        "--format=" + format_spec, "refs/heads")
    if local_rc or remote_rc:
        return {"status": "GIT_AUTHORITY_UNAVAILABLE", "eligible": []}
    remote = {x.split("\t", 1)[0] for x in remote_text.splitlines()}
    checked = {w.get("branch") for w in _worktrees()}
    candidates = []
    for item in local_text.splitlines():
        parts = item.split("\t", 1)
        if len(parts) != 2 or not parts[1].isdigit():
            continue
        branch, commit_time = parts[0], int(parts[1])
        age_hours = (time.time() - commit_time) / 3600
        if (branch in remote and age_hours >= MIN_AGE_HOURS
                and safe_branch(branch, merged=True, checked_out=branch in checked)):
            candidates.append(branch)
    return {"status": "DRY_RUN", "eligible": sorted(candidates)}


def apply_branches(*, acknowledged: bool, max_count: int = 15) -> dict:
    """Delete only obsolete LOCAL branch refs using Git safe -d."""
    if not acknowledged:
        return {"status": "ACK_REQUIRED", "deleted": []}
    if not 1 <= max_count <= 30:
        return {"status": "INVALID_LIMIT", "deleted": []}
    before = branch_plan()
    if before["status"] != "DRY_RUN":
        return {"status": "GIT_AUTHORITY_UNAVAILABLE", "deleted": []}
    removed = []
    for branch in before["eligible"][:max_count]:
        # A branch can be force-moved between initial and final scans.
        # Pin the exact tip around the final eligibility recheck.
        rc, initial_tip = _git("rev-parse", "--verify", "refs/heads/" + branch)
        if rc or not re.fullmatch(r"[0-9a-fA-F]{40,64}", initial_tip):
            continue
        second = branch_plan()
        if second["status"] != "DRY_RUN" or branch not in second["eligible"]:
            continue
        rc, final_tip = _git("rev-parse", "--verify", "refs/heads/" + branch)
        if rc or final_tip != initial_tip:
            continue
        rc, _ = _git("branch", "-d", branch)
        if rc == 0:
            removed.append(branch)
    return {"status": "APPLIED", "deleted": removed, "deleted_count": len(removed)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "apply", "branches-plan", "branches-apply"))
    parser.add_argument("--ack-retired-cleanup", action="store_true")
    parser.add_argument("--max-count", type=int, default=5)
    args = parser.parse_args(argv)
    if args.command in {"branches-plan", "branches-apply"}:
        if args.command == "branches-apply" and not args.ack_retired_cleanup:
            print(json.dumps({"status": "ACK_REQUIRED", "deleted": []}))
            return 2
        result = (branch_plan() if args.command == "branches-plan" else
                  apply_branches(acknowledged=True, max_count=args.max_count))
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["status"] in {"DRY_RUN", "APPLIED"} else 2
    if args.command == "apply" and not args.ack_retired_cleanup:
        print(json.dumps({"status": "ACK_REQUIRED", "deleted_count": 0}))
        return 2
    report = plan()
    result = (report if args.command == "plan" else execute_plan(
        report["worktrees"], apply=True, acknowledged=True, max_count=args.max_count))
    print(json.dumps(result, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
