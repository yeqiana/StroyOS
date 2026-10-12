"""Bounded, read-only StoryOS Git Worktree audit.

Produces candidates for *human review*, never deletion permission.
Never runs git clean/reset/worktree remove, never touches Episode or Runtime data.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def parse_worktrees(raw: str) -> list[dict]:
    """Parse git worktree list --porcelain without losing detached/locked flags."""
    result: list[dict] = []
    current: dict = {}
    for line in (raw + "\n\n").splitlines():
        if not line:
            if current.get("path"):
                result.append(current)
            current = {}
            continue
        if line.startswith("worktree "):
            current["path"] = line[9:]
        elif line.startswith("HEAD "):
            current["head"] = line[5:]
        elif line.startswith("branch refs/heads/"):
            current["branch"] = line[len("branch refs/heads/"):]
        elif line == "detached":
            current["detached"] = True
        elif line.startswith("locked"):
            current["locked"] = True
        elif line.startswith("prunable"):
            current["prunable"] = True
    return result


def classify(
    entry: dict,
    *,
    primary_path: str,
    tracked_or_untracked: list[str] | None,
    ignored: list[str] | None,
    merged: bool | None,
    patch_equivalent: bool | None = None,
    junctions: list[str] | None = None,
) -> dict:
    """No outcome here authorizes deletion: process ownership is not knowable from Git."""
    reasons: list[str] = []
    candidate = True
    path = str(entry.get("path") or "")
    if not path or Path(path).resolve(strict=False) == Path(primary_path).resolve(strict=False):
        reasons.append("primary_or_invalid_worktree")
        candidate = False
    if entry.get("locked") or entry.get("prunable"):
        reasons.append("locked_or_prunable_metadata")
        candidate = False
    if entry.get("detached") or not entry.get("branch"):
        reasons.append("detached_or_unnamed_branch")
        candidate = False
    if merged is not True:
        reasons.append("unmerged_or_unverified_head")
        candidate = False
        if patch_equivalent is True:
            reasons.append("patch_equivalent_not_a_merge_or_retirement_authority")
    if tracked_or_untracked is None or ignored is None:
        reasons.append("git_status_probe_unavailable")
        candidate = False
    else:
        if tracked_or_untracked:
            reasons.append("tracked_or_untracked_changes")
            candidate = False
        if ignored:
            reasons.append("ignored_files_may_contain_production_data")
            candidate = False
    if junctions:
        reasons.append("junction_or_symlink_requires_target_protection")
        candidate = False
    if candidate:
        reasons.append("manual_process_ownership_check_required")
    return {
        "path": path,
        "branch": entry.get("branch"),
        "head": entry.get("head"),
        "classification": "MANUAL_REVIEW_CANDIDATE" if candidate else "PROTECTED",
        "safe_to_delete": False,
        "reasons": reasons,
        "dirty_entry_count": len(tracked_or_untracked) if tracked_or_untracked is not None else None,
        "ignored_entry_count": len(ignored) if ignored is not None else None,
        "patch_equivalent": patch_equivalent,
        "junctions": junctions,
    }


def git(cwd: Path, *args: str, timeout: float = 12) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError("git " + " ".join(args[:2]) + " failed")
    return completed.stdout

def git_patch_equivalent(repo: Path, main_ref: str, branch: str) -> bool | None:
    """Read-only Patch-ID evidence; never permission to delete a worktree."""
    try:
        lines = git(repo, "cherry", main_ref, branch).splitlines()
    except (OSError, RuntimeError, subprocess.TimeoutExpired):
        return None
    if not lines or any(line[:2] not in ("+ ", "- ") for line in lines):
        return None
    return all(line.startswith("- ") for line in lines)


def ignored_junctions(worktree: Path, ignored: list[str]) -> list[str]:
    """Probe named ignored paths only, never follow or scan shared targets."""
    matches: list[str] = []
    for entry in ignored:
        normalized = entry.replace("\\", "/").rstrip("/")
        if not normalized or any(part in ("", ".", "..") for part in normalized.split("/")):
            continue
        path = worktree.joinpath(*normalized.split("/"))
        try:
            is_junction = getattr(path, "is_junction", lambda: False)
            if path.is_symlink() or is_junction():
                matches.append(entry)
        except OSError:
            matches.append(entry + " (probe unavailable)")
    return matches


def audit(repo: Path, *, main_ref: str, offset: int, limit: int) -> dict:
    root = Path(git(repo, "rev-parse", "--show-toplevel").strip()).resolve()
    worktrees = parse_worktrees(git(root, "worktree", "list", "--porcelain"))
    records = []
    for item in worktrees[offset:offset + limit]:
        path = Path(item["path"])
        status = None
        ignored = None
        merged = None
        patch_equivalent = None
        junctions = None
        if path.is_dir():
            try:
                status = git(path, "status", "--porcelain=v1", "--untracked-files=all").splitlines()
                ignored = git(path, "ls-files", "--others", "--ignored", "--exclude-standard", "--directory").splitlines()
                if item.get("branch") and item.get("head"):
                    process = subprocess.run(
                        ["git", "merge-base", "--is-ancestor", item["head"], main_ref],
                        cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        timeout=12, check=False,
                    )
                    merged = process.returncode == 0
                    if not merged:
                        patch_equivalent = git_patch_equivalent(root, main_ref, item["branch"])
                junctions = ignored_junctions(path, ignored)
            except (OSError, RuntimeError, subprocess.TimeoutExpired):
                pass  # fail closed if *any* probe fails
        records.append(classify(
            item, primary_path=str(root),
            tracked_or_untracked=status, ignored=ignored, merged=merged,
            patch_equivalent=patch_equivalent, junctions=junctions,
        ))
    return {
        "mode": "READ_ONLY",
        "deletes_performed": 0,
        "safe_to_delete": False,
        "main_ref": main_ref,
        "total_worktrees": len(worktrees),
        "offset": offset,
        "limit": limit,
        "records": records,
        "patch_equivalent_non_ancestor": sum(
            record["patch_equivalent"] is True and record["classification"] == "PROTECTED"
            for record in records
        ),
        "junctions_detected": sum(len(record["junctions"] or []) for record in records),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only, bounded Worktree governance audit")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--main-ref", default="story-platform-v3-rever")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=8)
    args = parser.parse_args()
    if args.offset < 0 or not 1 <= args.limit <= 30:
        parser.error("offset must be >= 0 and limit must be 1..30")
    print(json.dumps(
        audit(args.repo, main_ref=args.main_ref, offset=args.offset, limit=args.limit),
        ensure_ascii=False, indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
