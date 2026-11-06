#!/usr/bin/env python3
"""One-time audited correction of EP14 final-semantic repair dispatch (2026-11-06).

Only supersedes the failed, provider-NOT_INVOKED 2026-11-05 queue items.
Never changes generated assets, generation attempts, or semantic review verdicts.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "episodes" / "_system"))

import generation_attempt_authority
import logical_asset_identity
import production_ledger
import runtime_driver
import scheduler_core

TARGETS = ("13", "15", "16", "21", "25", "26", "27", "28", "30",
           "31", "32", "34", "39", "41", "42", "43", "44")
BASIS = "direct_user_final_semantic_ordinary_repair"
FAILURE = "LOGIN_AUTH_IMAGE_TOOL_CAPABILITY_UNKNOWN"
CORRECTION = "USER_CORRECTION_FINAL_SEMANTIC_NOT_GENERATION_REPAIR"


def preflight(ep: Path, data: dict, queue: dict) -> list[tuple[str, str, int, list[dict]]]:
    if not (ep.parent.name == "00_独立篇" and ep.name.startswith("14_深渊疗愈所_第一集_")):
        raise RuntimeError("wrong episode: correction is exclusively for EP14")
    frames = data.get("frames") or {}
    items = queue.get("items") or []
    if any(str(item.get("status") or "") in {"queued", "running", "interrupted_unknown"}
           and int(item.get("frame") or 0) in {int(k) for k in TARGETS}
           for item in items):
        raise RuntimeError("active image queue: cannot correct while dispatch may proceed")
    plans = []
    for key in TARGETS:
        frame = frames[key]
        auth = frame.get("repair_authorization") or {}
        if auth.get("approval_basis") != BASIS or auth.get("revocations"):
            raise RuntimeError(f"{key}: authorization changed or already revoked")
        status = frame.get("status")
        if status not in {"TECH_FAILED", "REPAIR_AUTHORIZED"}:
            raise RuntimeError(f"{key}: unexpected status {status}")
        candidate = frame.get("current_candidate") or {}
        raw = Path(candidate.get("path") or "")
        actual = raw if raw.is_absolute() else production_ledger.repo_root() / raw
        sha = str(candidate.get("sha256") or "").lower()
        if not sha or not actual.is_file() or production_ledger.sha256_file(actual) != sha:
            raise RuntimeError(f"{key}: existing candidate missing or hash drift")
        state = generation_attempt_authority.load_asset_state(
            ep, logical_asset_identity.frame_asset_key(ep, int(key)))
        if state.get("active_attempt_index") is not None:
            raise RuntimeError(f"{key}: unresolved generation lease")
        consumed = int(state.get("attempts_consumed") or 0)
        if consumed > 2:
            raise RuntimeError(f"{key}: unexpected real generation count {consumed}")
        rows = [item for item in items
                if int(item.get("frame") or 0) == int(key)
                and str(item.get("prompt_file") or "").endswith("final-semantic-a2.txt")]
        if status == "TECH_FAILED":
            last = (frame.get("attempts") or [{}])[-1]
            if not (frame.get("content_repairs_used") == 1
                    and last.get("kind") == "repair"
                    and last.get("result") == "technical_failure"
                    and (last.get("provider_attempt") or {}).get("status") == "NOT_INVOKED"
                    and (last.get("error") or {}).get("code") == FAILURE
                    and len(rows) == 1 and rows[0].get("status") == "blocked"):
                raise RuntimeError(f"{key}: unverified uninvoked technical failure")
        elif frame.get("content_repairs_used") != 0 or rows:
            raise RuntimeError(f"{key}: unexpected authorized-only state")
        plans.append((key, status, consumed, rows))
    return plans


def correct(ep: Path, *, apply: bool = False) -> dict:
    ep = ep.resolve()
    data = production_ledger.load_authority(ep, default=None)
    if not isinstance(data, dict):
        raise RuntimeError("MySQL production ledger authority missing")
    queue = scheduler_core.load_queue(ep)
    plans = preflight(ep, data, queue)
    summary = {"frames": len(plans),
               "uninvoked_technical_failures": sum(s == "TECH_FAILED" for _, s, _, _ in plans),
               "authorized_only": sum(s == "REPAIR_AUTHORIZED" for _, s, _, _ in plans),
               "real_generation_counts": {key: count for key, _, count, _ in plans},
               "applied": False}
    if not apply:
        return summary
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    for key, previous, consumed, queue_rows in plans:
        frame = data["frames"][key]
        frame.setdefault("repair_rollback_events", []).append({
            "at": now, "from_status": previous, "to_status": "NEEDS_USER",
            "reason": CORRECTION, "real_attempts_consumed": consumed,
            "previous_content_repairs_used": frame.get("content_repairs_used"),
            "candidate_sha256": frame["current_candidate"]["sha256"],
            "provider_invoked": False,
        })
        frame["repair_authorization"].setdefault("revocations", []).append({
            "at": now, "reason": CORRECTION,
        })
        if previous == "TECH_FAILED":
            frame["attempts"][-1]["postflight_correction"] = {
                "at": now, "reason": "provider_not_invoked",
                "original_result_retained": "technical_failure",
            }
            frame["content_repairs_used"] = 0
        frame["status"] = "NEEDS_USER"
        for item in queue_rows:
            item["prior_status_before_correction"] = "blocked"
            item["status"] = "superseded"
            item["superseded_at"] = now
            item["superseded_reason"] = CORRECTION
    # No active worker is permitted by preflight. First terminalize the Redis
    # queue; then commit the MySQL ledger. A failure preserves retryable evidence.
    scheduler_core.save_queue(ep, queue)
    data["updated_at"] = now
    production_ledger.save_json(ep / "meta" / "production-ledger.json", data)
    updated = production_ledger.load_authority(ep, default={})
    if not all(updated["frames"][key]["status"] == "NEEDS_USER"
               and updated["frames"][key].get("content_repairs_used") == 0
               for key in TARGETS):
        raise RuntimeError("post-commit authority verification failed")
    summary["applied"] = True
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("episode_dir", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    runtime_driver._load_child_runtime_environment(
        runtime_store_mode="mysql", episode_meta_store_mode="mysql",
        hot_state_mode="redis", production_mode="CODEX_MANAGED", image_executor="CODEX")
    import json
    print(json.dumps(correct(args.episode_dir, apply=args.apply), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
