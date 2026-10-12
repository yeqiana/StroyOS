#!/usr/bin/env python3
"""Multi-Episode launcher over canonical per-Episode StoryOS Drivers.

The per-Episode Driver and Authority gates remain the only production owners.
This utility starts *different* Episodes and never dispatches pixels itself.
The shared image Provider Gateway enforces one machine-wide five-image cap.

Use the authenticated local production environment wrapper to launch this tool.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "episodes" / "_system"
if str(SYSTEM) not in sys.path:
    sys.path.insert(0, str(SYSTEM))

import global_image_capacity
import runtime_driver
import runtime_router


def validate_episodes(raw_episodes: list[str], *, root: Path | None = None) -> list[Path]:
    if len(raw_episodes) < 2:
        raise ValueError("MULTI_EPISODE_AT_LEAST_TWO_REQUIRED")
    root = Path(ROOT if root is None else root).resolve()
    allowed = root / "episodes"
    resolved: list[Path] = []
    for raw in raw_episodes:
        ep = Path(raw)
        ep = (ep if ep.is_absolute() else root / ep).resolve()
        if not ep.is_dir() or not ep.is_relative_to(allowed):
            raise ValueError("MULTI_EPISODE_PATH_INVALID")
        if ep in resolved:
            raise ValueError("MULTI_EPISODE_DUPLICATE")
        resolved.append(ep)
    return resolved


def multi_status(episodes: list[Path], *, status_fn=None, snapshot_fn=None) -> dict:
    status = status_fn if status_fn is not None else runtime_driver.status
    snapshot = snapshot_fn if snapshot_fn is not None else global_image_capacity.snapshot
    rows = []
    diagnostic_incomplete = False
    for ep in episodes:
        try:
            state = status(ep)
            if not isinstance(state, dict):
                raise TypeError("DRIVER_STATUS_INVALID")
            driver_state = str(state.get("driver_state") or "UNKNOWN")
            row = {
                "episode": ep.relative_to(ROOT).as_posix(),
                "driver_state": driver_state,
                "liveness": state.get("liveness"),
                "status_only": True,
            }
            if driver_state not in {"RUNNING", "NEVER_STARTED", "EXITED"}:
                diagnostic_incomplete = True
                row["diagnostic_error"] = "DRIVER_OWNER_UNVERIFIED"
        except Exception as exc:
            # Runtime may require an unavailable canonical MySQL connection.
            # Never silently fall back to stale episode JSON, or leak a driver
            # DSN/credential through an uncaught stack trace.
            diagnostic_incomplete = True
            row = {
                "episode": ep.relative_to(ROOT).as_posix(),
                "driver_state": "UNKNOWN",
                "liveness": None,
                "status_only": True,
                "diagnostic_error": "DRIVER_STATUS_READ_FAILED",
                "error_type": type(exc).__name__,
            }
        rows.append(row)
    try:
        capacity = snapshot()
    except Exception as exc:
        diagnostic_incomplete = True
        capacity = {
            "scope": "LOCAL_GIT_COMMON_DIRECTORY",
            "advisory_snapshot_only": True,
            "observation_status": "UNAVAILABLE",
            "diagnostic_error": "GLOBAL_IMAGE_CAPACITY_SNAPSHOT_FAILED",
            "error_type": type(exc).__name__,
        }
    return {
        "scope": "LOCAL_GIT_COMMON_DIRECTORY",
        "episode_count": len(rows),
        "episodes": rows,
        "global_image_capacity": capacity,
        "diagnostic_incomplete": diagnostic_incomplete,
        "production_authorization": False,
        "authority": "DIAGNOSTIC_ONLY",
        "model_calls": 0,
    }


def start_episodes(episodes: list[Path], *, status_fn=None, start_fn=None) -> dict:
    """Fail closed on any ambiguous owner; never start the same Episode twice."""
    # OS locks cover synchronous native Provider calls, not asynchronous
    # PRODUCT_RUNTIME host requests. Never advertise a hard five-image cap for
    # a multi-Episode launch unless the effective image executor is CODEX.
    image_executor, _ = runtime_router.image_execution_runtime()
    if image_executor != "CODEX":
        raise ValueError("MULTI_EPISODE_NATIVE_CODEX_IMAGE_EXECUTOR_REQUIRED")
    status = status_fn if status_fn is not None else runtime_driver.status
    start = start_fn if start_fn is not None else runtime_driver.launch
    found = []
    for ep in episodes:
        try:
            current = status(ep)
            if not isinstance(current, dict):
                raise TypeError("DRIVER_STATUS_INVALID")
            found.append((ep, str(current.get("driver_state") or "UNKNOWN")))
        except Exception as exc:
            # Every owner must be known before the FIRST Driver is started.
            # A database or heartbeat error cannot silently start peers, and
            # connection details must never appear in the CLI JSON receipt.
            return {
                "ok": False,
                "reason": "MULTI_EPISODE_DRIVER_OWNER_UNVERIFIED",
                "blocked_episodes": [ep.relative_to(ROOT).as_posix()],
                "error_type": type(exc).__name__,
                "starts_attempted": 0,
                "results": [],
            }
    ambiguous = [(ep, state) for ep, state in found
                 if state not in {"RUNNING", "NEVER_STARTED", "EXITED"}]
    if ambiguous:
        return {"ok": False, "reason": "MULTI_EPISODE_DRIVER_OWNER_UNVERIFIED",
                "blocked_episodes": [ep.relative_to(ROOT).as_posix() for ep, _ in ambiguous],
                "starts_attempted": 0, "results": []}
    results = []
    for ep, previous in found:
        if previous == "RUNNING":
            results.append({"episode": ep.relative_to(ROOT).as_posix(),
                            "status": "ALREADY_RUNNING", "started": False})
            continue
        try:
            launched = start(ep, resume=True)
            results.append({
                "episode": ep.relative_to(ROOT).as_posix(),
                "status": "STARTED" if launched.get("started") else "BLOCKED",
                "started": bool(launched.get("started")),
                "reason": launched.get("reason"),
            })
        except Exception as exc:
            # Do not undo the already-running other Episode or erase its evidence.
            results.append({"episode": ep.relative_to(ROOT).as_posix(),
                            "status": "BLOCKED", "started": False,
                            "reason": type(exc).__name__})
    return {"ok": all(x["status"] in {"STARTED", "ALREADY_RUNNING"} for x in results),
            "results": results, "starts_attempted": sum(x["status"] != "ALREADY_RUNNING" for x in results),
            "no_rollback_of_other_episode": True}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["plan", "status", "start"])
    parser.add_argument("--episode", action="append", required=True,
                        help="One distinct canonical Episode directory; repeat >=2 times")
    parser.add_argument("--ack-real-production", action="store_true",
                        help="Required for start; this may call paid models")
    args = parser.parse_args(argv)
    try:
        eps = validate_episodes(args.episode)
        if args.command == "start":
            if not args.ack_real_production:
                raise ValueError("MULTI_EPISODE_REAL_PRODUCTION_ACK_REQUIRED")
            # Verify the machine-wide shared store is available before starting
            # either Episode. This never claims an image Attempt.
            global_image_capacity.snapshot()
            output = start_episodes(eps)
            print(json.dumps(output, ensure_ascii=False, indent=2))
            return 0 if output["ok"] else 3
        output = multi_status(eps)
        if args.command == "plan":
            output["note"] = "No production gate is granted; each Driver still validates its own Episode"
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 3 if output.get("diagnostic_incomplete") else 0
    except (ValueError, OSError, global_image_capacity.GlobalImageCapacityError) as exc:
        print(json.dumps({"ok": False, "reason": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
