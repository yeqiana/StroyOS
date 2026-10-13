#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Single-host native-Codex Driver watchdog, never an image/Review scheduler.

The read-only plan never writes. An explicitly acknowledged tick can only
re-admit an already-started, safely terminated Driver through canonical
storyos_codex_managed preflight and runtime_driver start --resume.

No OpenCodex fallback, MySQL mutation, standalone Provider retry or stage write.
Distributed multi-host Writer fencing remains OUT OF SCOPE.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

import storyos_codex_managed as native

ROOT = Path(__file__).resolve().parents[1]
WINDOW_SECONDS = 24 * 3600
MAX_RECOVERIES = 2
COOLDOWN_SECONDS = 300
SCHEMA_VERSION = 1


class LockBusy(RuntimeError):
    """A second watchdog for the same Episode must never dispatch."""


class InvalidJournal(RuntimeError):
    """A damaged or foreign journal cannot be repaired by guessing."""


def episode_id(episode_ref: str) -> str:
    return hashlib.sha256(episode_ref.encode("utf-8")).hexdigest()[:24]


def _paths(root: Path, episode_ref: str) -> tuple[Path, Path]:
    key = episode_id(episode_ref)
    return root / ("watch-" + key + ".lock"), root / ("watch-" + key + ".json")


def _canonical_data_root() -> Path:
    """All Git worktrees share one lock/journal in the common Git directory."""
    result = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "--git-common-dir"],
        text=True, capture_output=True, timeout=15, check=False,
    )
    if result.returncode or not result.stdout.strip():
        raise InvalidJournal("GIT_COMMON_DIRECTORY_UNVERIFIED")
    raw = Path(result.stdout.strip())
    git_dir = (raw if raw.is_absolute() else ROOT / raw).resolve()
    if not git_dir.is_dir():
        raise InvalidJournal("GIT_COMMON_DIRECTORY_UNVERIFIED")
    return git_dir / "storyos-autonomy-watchdog"


@contextmanager
def episode_lock(data_root: Path, episode_ref: str):
    """Real OS advisory exclusive lock across processes/worktrees, nonblocking."""
    data_root.mkdir(parents=True, exist_ok=True)
    path, _ = _paths(data_root, episode_ref)
    with path.open("a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise LockBusy("SAME_EPISODE_WATCHDOG_BUSY") from exc
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise LockBusy("SAME_EPISODE_WATCHDOG_BUSY") from exc
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def policy_decision(report: dict, *, expected_episode: str) -> dict:
    """Pure conservative policy: all truth comes from canonical read-only preflight."""
    def result(action: str, reason: str) -> dict:
        return {"action": action, "reason": reason}
    if not isinstance(report, dict) or report.get("episode") != expected_episode:
        return result("BLOCK", "EPISODE_IDENTITY_UNVERIFIED")
    if (report.get("scope") != "NATIVE_CODEX_FULL_AUTO"
            or report.get("production_mode") != "CODEX_MANAGED"
            or report.get("image_executor") != "CODEX"
            or report.get("read_only") is not True
            or report.get("production_authorization") is not False
            or report.get("model_calls") != 0 or report.get("sql_writes") != 0):
        return result("BLOCK", "PREFLIGHT_PROVENANCE_INVALID")
    if (report.get("mysql") or {}).get("schema_status") != "READY_FOR_FURTHER_ADMISSION":
        return result("BLOCK", "MYSQL_SCHEMA_UNVERIFIED")
    stage = report.get("episode_stage") or {}
    if stage.get("status") != "STAGE_ELIGIBLE" or stage.get("source") != "mysql":
        return result("BLOCK", "MYSQL_EPISODE_STAGE_UNVERIFIED")
    attempt = report.get("attempt") or {}
    if (attempt.get("status") != "ATTEMPT_HISTORY_READ_ONLY"
            or attempt.get("outcome_unknown_assets")
            or attempt.get("active_attempt_assets")):
        return result("BLOCK", "GENERATION_ATTEMPT_UNVERIFIED")
    state = str(report.get("driver_state") or "")
    driver = report.get("driver_evidence") or {}
    if state != driver.get("driver_state"):
        return result("BLOCK", "DRIVER_EVIDENCE_MISSING_OR_DRIFTED")
    blockers = set(report.get("blockers") or [])
    if state == "RUNNING" and blockers.issubset({
            "EPISODE_DRIVER_OWNER_NOT_IDLE_OR_UNVERIFIED"}):
        return result("WAIT", "CANONICAL_DRIVER_ALREADY_RUNNING")
    if state == "NEVER_STARTED" and blockers.issubset(set()):
        return result("WAIT", "FIRST_START_MUST_BE_EXPLICIT")
    if report.get("status") != "READY_TO_START" or blockers:
        return result("BLOCK", "CANONICAL_PREFLIGHT_BLOCKED")
    if not native.resident_restart_permitted(driver):
        return result("BLOCK", "DRIVER_NOT_SAFELY_RECOVERABLE")
    if state == "ABNORMAL_DISAPPEARANCE":
        if driver.get("liveness") != "DEAD" or not isinstance(driver.get("pid"), int) or driver["pid"] <= 0:
            return result("BLOCK", "DEAD_DRIVER_NOT_PROVEN")
    elif state == "EXITED":
        if driver.get("pid") != 0 or str(driver.get("exit_code") or "").split(" ", 1)[0] != "0":
            return result("BLOCK", "EXIT_RECORD_NOT_CLEAN")
    else:
        return result("BLOCK", "UNSUPPORTED_DRIVER_STATE")
    return result("RECOVER", "RECHECK_CANONICAL_AUTHORITIES")


def _load_journal(path: Path, episode_ref: str) -> dict:
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "episode": episode_ref,
                "last_observed_at": 0, "attempts": []}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(doc, dict) or doc.get("schema_version") != SCHEMA_VERSION
                or doc.get("episode") != episode_ref
                or type(doc.get("last_observed_at")) not in (int, float)
                or not math.isfinite(doc["last_observed_at"])
                or doc["last_observed_at"] < 0
                or not isinstance(doc.get("attempts"), list)):
            raise InvalidJournal("JOURNAL_INVALID")
        ids = set()
        for item in doc["attempts"]:
            if (not isinstance(item, dict) or not isinstance(item.get("id"), str)
                    or not item["id"] or item["id"] in ids
                    or type(item.get("at")) not in (int, float)
                    or not math.isfinite(item["at"])
                    or item["at"] < 0 or item["at"] > doc["last_observed_at"]
                    or item.get("status") not in {
                        "RESERVED", "DISPATCHED", "HANDOFF_UNKNOWN"}):
                raise InvalidJournal("JOURNAL_INVALID")
            ids.add(item["id"])
        if len(doc["attempts"]) > 10000:
            raise InvalidJournal("JOURNAL_TOO_LARGE")
        return doc
    except (OSError, ValueError, TypeError, UnicodeError) as exc:
        raise InvalidJournal("JOURNAL_INVALID") from exc


def _save_journal(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def reserve_recovery(path: Path, episode_ref: str, *, now_ts: float,
                     max_attempts: int = MAX_RECOVERIES,
                     cooldown: int = COOLDOWN_SECONDS) -> dict:
    """Reserve *before* dispatch. Caller must hold the episode OS lock."""
    if (not isinstance(now_ts, (int, float)) or not math.isfinite(now_ts)
            or now_ts < 0 or not 1 <= max_attempts <= 5
            or not 0 <= cooldown <= 86400):
        return {"ok": False, "reason": "BUDGET_POLICY_INVALID"}
    try:
        doc = _load_journal(path, episode_ref)
    except InvalidJournal:
        return {"ok": False, "reason": "JOURNAL_INVALID"}
    if now_ts < doc["last_observed_at"]:
        return {"ok": False, "reason": "CLOCK_ROLLBACK"}
    if any(attempt["at"] > now_ts for attempt in doc["attempts"]):
        return {"ok": False, "reason": "CLOCK_ROLLBACK"}
    recent = [item for item in doc["attempts"]
              if now_ts - item["at"] < WINDOW_SECONDS]
    if len(recent) >= max_attempts:
        return {"ok": False, "reason": "BUDGET_EXHAUSTED"}
    if recent and now_ts - recent[-1]["at"] < cooldown:
        return {"ok": False, "reason": "COOLDOWN"}
    item = {"id": uuid.uuid4().hex, "at": now_ts, "status": "RESERVED"}
    doc["attempts"].append(item)
    doc["last_observed_at"] = now_ts
    _save_journal(path, doc)
    return {"ok": True, "reason": "RESERVED", "attempt_id": item["id"]}


def _mark_handoff(path: Path, episode_ref: str, attempt_id: str, status: str) -> bool:
    try:
        journal = _load_journal(path, episode_ref)
        for row in journal["attempts"]:
            if row["id"] == attempt_id and row["status"] == "RESERVED":
                row["status"] = status
                _save_journal(path, journal)
                return True
    except (OSError, InvalidJournal):
        pass
    # Caller must return HANDOFF_UNKNOWN, never a fabricated success.
    return False


def launch_driver(episode: Path, env: dict[str, str]) -> dict:
    """Use ONLY the existing canonical resident Driver, not a shadow runner."""
    command = native.full_auto_command(argparse.Namespace(command="start"), episode)
    result = subprocess.run(command, cwd=native.ROOT, env=env,
                            text=True, encoding="utf-8", errors="replace",
                            capture_output=True, timeout=120, check=False)
    if result.returncode:
        return {"started": False, "driver_state": "UNKNOWN"}
    try:
        output = json.loads(result.stdout)
        if isinstance(output, dict):
            return {"started": output.get("started") is True,
                    "driver_state": output.get("driver_state")}
    except (ValueError, TypeError):
        pass
    return {"started": False, "driver_state": "UNKNOWN"}


def tick(episode: str, *, acknowledged: bool, data_root: Path | None = None,
         now_ts: float | None = None, max_attempts: int = MAX_RECOVERIES,
         cooldown: int = COOLDOWN_SECONDS, dispatch=None) -> dict:
    """One bounded iteration. No unacknowledged filesystem effects."""
    if not acknowledged:
        return {"status": "ACK_REQUIRED", "dispatched": False}
    try:
        ep = native.canonical_episode(episode)
        ref = ep.relative_to(native.ROOT).as_posix()
        env = native.native_environment()
    except (ValueError, OSError):
        return {"status": "ENVIRONMENT_UNVERIFIED", "dispatched": False}
    now = time.time() if now_ts is None else float(now_ts)
    if not math.isfinite(now) or now < 0:
        return {"status": "CLOCK_INVALID", "dispatched": False}
    try:
        home = data_root if data_root is not None else _canonical_data_root()
        _, journal = _paths(home, ref)
        with episode_lock(home, ref):
            try:
                before = native.preflight(env, episode=ep)
            except Exception:
                return {"status": "PREFLIGHT_UNAVAILABLE", "dispatched": False}
            first = policy_decision(before, expected_episode=ref)
            if first["action"] != "RECOVER":
                return {"status": first["action"], "reason": first["reason"],
                        "dispatched": False}
            # A second fresh preflight under same-Episode watchdog lock catches
            # changes at the MySQL/Driver/Attempt edge. Owner lock still wins.
            try:
                after = native.preflight(env, episode=ep)
            except Exception:
                return {"status": "PREFLIGHT_UNAVAILABLE", "dispatched": False}
            second = policy_decision(after, expected_episode=ref)
            if (second["action"] != "RECOVER" or
                    before.get("driver_evidence") != after.get("driver_evidence") or
                    before.get("attempt") != after.get("attempt") or
                    before.get("episode_stage") != after.get("episode_stage") or
                    before.get("blockers") != after.get("blockers") or
                    before.get("codex") != after.get("codex") or
                    before.get("mysql") != after.get("mysql") or
                    before.get("visual_lock_admission") != after.get("visual_lock_admission") or
                    before.get("creative_story_recovery") != after.get("creative_story_recovery")):
                return {"status": "AUTHORITY_CHANGED", "dispatched": False}
            reservation = reserve_recovery(
                journal, ref, now_ts=now, max_attempts=max_attempts, cooldown=cooldown)
            if not reservation["ok"]:
                return {"status": reservation["reason"], "dispatched": False}
            try:
                result = (dispatch or launch_driver)(ep, env)
                confirmed = (isinstance(result, dict)
                             and result.get("started") is True
                             and result.get("driver_state") == "RUNNING")
            except Exception:
                confirmed = False
            code = "DISPATCHED" if confirmed else "HANDOFF_UNKNOWN"
            recorded = _mark_handoff(journal, ref, reservation["attempt_id"], code)
            if not recorded:
                return {"status": "HANDOFF_UNKNOWN", "dispatched": False,
                        "recovery_attempt_reserved": True}
            return {"status": code, "dispatched": confirmed,
                    "recovery_attempt_reserved": True}
    except LockBusy:
        return {"status": "SAME_EPISODE_WATCHDOG_BUSY", "dispatched": False}
    except (OSError, InvalidJournal):
        return {"status": "WATCHDOG_LOCAL_AUTHORITY_UNAVAILABLE",
                "dispatched": False}


def plan(episode: str) -> dict:
    """All probes read-only, including no lock/journal creation."""
    try:
        ep = native.canonical_episode(episode)
        env = native.native_environment()
        report = native.preflight(env, episode=ep)
        return {"status": "READ_ONLY", **policy_decision(
            report, expected_episode=ep.relative_to(native.ROOT).as_posix()),
            "production_authorization": False}
    except (ValueError, OSError):
        return {"status": "BLOCKED", "reason": "ENVIRONMENT_UNVERIFIED",
                "production_authorization": False}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    view = sub.add_parser("plan")
    view.add_argument("episode")
    once = sub.add_parser("once")
    once.add_argument("episode")
    once.add_argument("--ack-real-production", action="store_true")
    watch = sub.add_parser("watch")
    watch.add_argument("episode")
    watch.add_argument("--ack-real-production", action="store_true")
    watch.add_argument("--interval-seconds", type=int, default=300)
    watch.add_argument("--max-cycles", type=int, default=0)
    args = parser.parse_args(argv)
    if args.cmd == "plan":
        print(json.dumps(plan(args.episode), ensure_ascii=False))
        return 0
    if not args.ack_real_production:
        print(json.dumps({"status": "ACK_REQUIRED", "dispatched": False}))
        return 2
    if args.cmd == "watch" and args.interval_seconds < 60:
        print(json.dumps({"status": "INTERVAL_TOO_SHORT"}))
        return 2
    cycles = 0
    while True:
        result = tick(args.episode, acknowledged=True)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        if result["status"] in {"HANDOFF_UNKNOWN", "WATCHDOG_LOCAL_AUTHORITY_UNAVAILABLE",
                                "AUTHORITY_CHANGED", "SAME_EPISODE_WATCHDOG_BUSY",
                                "CLOCK_INVALID", "ENVIRONMENT_UNVERIFIED"}:
            return 3
        cycles += 1
        if args.cmd == "once" or (args.max_cycles and cycles >= args.max_cycles):
            return 0
        time.sleep(args.interval_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
