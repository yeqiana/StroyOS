"""Bounded read-only last-node observation, never a live execution authorization."""
from __future__ import annotations
from pathlib import Path
import json
import re

EVENTS = frozenset(("STEP_STARTED", "STEP_FINISHED", "STEP_FAILED",
                    "WORKER_DISPATCH_COMMITTED", "WORKER_RESULT_RECEIVED",
                    "EPISODE_RUN_FINISHED"))
CODE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,63}$")


def latest_node(episode_dir: Path) -> dict:
    result = {"execution_status": "UNKNOWN", "current_action": None,
              "blocking_reason": None, "last_event_at": None}
    root = episode_dir.resolve()
    path = root / "meta" / "runtime" / "trace-events.jsonl"
    try:
        if (path.is_symlink() or not path.is_file() or
                not path.resolve(strict=True).is_relative_to(root)):
            return result
        with path.open("rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 131072))
            # The first truncated line is ignored if this is a tail window.
            tail = f.read(131072).decode("utf-8", errors="replace").splitlines()
        # A final envelope has no node identity: reuse its preceding step.
        finished = None
        for line in reversed(tail):
            if len(line) > 8192:
                continue
            try:
                row = json.loads(line)
            except (ValueError, TypeError):
                continue
            if not isinstance(row, dict) or row.get("event_type") not in EVENTS:
                continue
            kind, step = row["event_type"], row.get("step")
            if not isinstance(step, str) or not CODE.fullmatch(step):
                if kind == "EPISODE_RUN_FINISHED" and finished is None:
                    finished = row
                continue
            status = ("DISPATCH_RECORDED" if kind in ("STEP_STARTED", "WORKER_DISPATCH_COMMITTED")
                      else "RESULT_RECORDED" if kind in ("STEP_FINISHED", "WORKER_RESULT_RECEIVED")
                      else "BLOCKED_RECORDED" if kind == "STEP_FAILED" else "UNKNOWN")
            result.update(execution_status=status, current_action=step)
            reason = row.get("failure_class") if status == "BLOCKED_RECORDED" else None
            result["blocking_reason"] = (reason if isinstance(reason, str) and CODE.fullmatch(reason)
                                         else "STEP_BLOCKED" if status == "BLOCKED_RECORDED" else None)
            ts = row.get("timestamp")
            result["last_event_at"] = ts if isinstance(ts, str) and len(ts) <= 45 else None
            return result
        if finished is not None:
            result["execution_status"] = "FINISHED_RECORDED"
            ts = finished.get("timestamp")
            result["last_event_at"] = ts if isinstance(ts, str) and len(ts) <= 45 else None
    except OSError:
        pass
    return result
