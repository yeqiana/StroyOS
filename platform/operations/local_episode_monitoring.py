"""Conservative read-only projection of actual on-disk StoryOS production evidence.

A recorded RUNNING/heartbeat file is *not* proof of a live Worker. Never
read prompt payloads, host request details, model credentials or raw logs.
No databases, Redis, image providers, or writes are used here.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any

MAX_SOURCE_BYTES = 8 * 1024 * 1024
FRAME_RE = re.compile(r"^(0?[1-9]|1[0-9]|20)$")
CODE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,63}$")
SOURCES = {
    "queue": "production-queue.json",
    "ledger": "production-ledger.json",
    "checkpoint": "runtime-checkpoint.json",
    "runner": "runtime-runner-state.json",
    "story_review": "story-semantic-review.json",
    "frame_review": "frame-semantic-review.json",
    "release_review": "release-semantic-review.json",
    "visual_lock": "visual-lock-baseline-review.json",
}


def _safe_code(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return value if CODE_RE.fullmatch(value) else None


def _date(value: object) -> str | None:
    if not isinstance(value, str) or len(value) > 48:
        return None
    try:
        if datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo:
            return value
    except ValueError:
        pass
    return None


def _load(meta: Path, filename: str, errors: list[str]) -> dict | None:
    path = meta / filename
    if not path.exists():
        return None
    try:
        if path.is_symlink() or not path.is_file() or not path.resolve(strict=True).is_relative_to(meta.resolve(strict=True)):
            raise ValueError("not an ordinary local evidence file")
        if path.stat().st_size > MAX_SOURCE_BYTES:
            raise ValueError("evidence file exceeds read limit")
        with path.open("rb") as stream:
            data = stream.read(MAX_SOURCE_BYTES + 1)
        if len(data) > MAX_SOURCE_BYTES:
            raise ValueError("evidence file exceeds read limit")
        payload = json.loads(data.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("evidence file is not an object")
        return payload
    except (OSError, ValueError, UnicodeError, json.JSONDecodeError):
        # Never expose filenames from arbitrary user input or raw JSON.
        errors.append(filename + ":UNREADABLE")
        return None


def _frame_number(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 1 <= value <= 20 else None
    if isinstance(value, str) and FRAME_RE.fullmatch(value):
        return int(value)
    return None


def _attempt_count(value: object) -> int | None:
    if isinstance(value, list):
        return min(len(value), 10000)
    if type(value) is int and 0 <= value <= 10000:
        return value
    return None


def _error_code(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    for key in ("error_code", "code", "category", "type"):
        result = _safe_code(value.get(key))
        if result:
            return result
    return None


def read_recorded_production(meta: Path) -> dict[str, Any]:
    """Return provenance-labelled recorded facts, with no live authorization."""
    errors: list[str] = []
    sources: dict[str, dict[str, str | None]] = {}
    documents: dict[str, dict | None] = {}
    for kind, filename in SOURCES.items():
        data = _load(meta, filename, errors)
        documents[kind] = data
        if data is not None:
            sources[kind] = {
                "source": "local_workspace_recorded_file",
                "recorded_at": _date(data.get("updated_at") or data.get("approved_at") or data.get("generated_at") or data.get("created_at")),
            }

    ledger, queue = documents["ledger"], documents["queue"]
    ledger_rows: dict[int, dict] = {}
    if isinstance(ledger, dict) and isinstance(ledger.get("frames"), dict):
        for key, value in ledger["frames"].items():
            number = _frame_number(key)
            if number is not None and isinstance(value, dict):
                ledger_rows[number] = value

    queue_rows: dict[int, list[dict]] = {}
    statuses: Counter[str] = Counter()
    if isinstance(queue, dict) and isinstance(queue.get("items"), list):
        for item in queue["items"][:5000]:
            if not isinstance(item, dict):
                continue
            code = _safe_code(item.get("status"))
            if code:
                statuses[code] += 1
            number = _frame_number(item.get("frame"))
            if number is not None:
                queue_rows.setdefault(number, []).append(item)

    frames: list[dict] = []
    for number in sorted(set(ledger_rows) | set(queue_rows)):
        ledger_item = ledger_rows.get(number, {})
        candidates = queue_rows.get(number, [])
        # Superseded queue items remain in the history, never an active task.
        latest = next((x for x in reversed(candidates) if str(x.get("status") or "").lower() != "superseded"), None)
        if latest is None and candidates:
            latest = candidates[-1]
        latest = latest or {}
        frames.append({
            "frame": number,
            "ledger_status": _safe_code(ledger_item.get("status")),
            "queue_status": _safe_code(latest.get("status")),
            "recorded_attempt_entries": _attempt_count(ledger_item.get("attempts")),
            "queue_attempts": _attempt_count(latest.get("attempts")),
            "approved_in_ledger": bool(ledger_item.get("approved_asset")),
            "last_error_code": _error_code(latest.get("last_error")),
            "queue_history_count": len(candidates),
        })

    checkpoint = documents["checkpoint"]
    last_steps: list[dict] = []
    if isinstance(checkpoint, dict) and isinstance(checkpoint.get("step_runs"), list):
        for step in checkpoint["step_runs"][-16:]:
            if not isinstance(step, dict):
                continue
            name, status = _safe_code(step.get("step")), _safe_code(step.get("status"))
            if name and status:
                last_steps.append({
                    "step": name,
                    "status": status,
                    "attempt": _attempt_count(step.get("attempt")),
                    "finished_at": _date(step.get("finished_at")),
                })

    runner = documents["runner"]
    runner_record: dict | None = None
    if isinstance(runner, dict):
        runner_record = {
            "recorded_status": _safe_code(runner.get("status")),
            "last_heartbeat_recorded_at": _date(runner.get("heartbeat")),
            "verified_live": False,
        }

    reviews: dict[str, dict] = {}
    for kind in ("story_review", "frame_review", "release_review", "visual_lock"):
        record = documents[kind]
        if not isinstance(record, dict):
            continue
        summary = record.get("summary") if isinstance(record.get("summary"), dict) else {}
        value = summary.get("passed")
        reviews[kind] = {
            "recorded_status": _safe_code(record.get("status")),
            "decision": _safe_code(record.get("decision")),
            "passed": value if type(value) is bool else None,
            "source": "local_workspace_recorded_file",
        }

    accepted = sum(bool(row.get("approved_in_ledger")) for row in frames)
    progress = ({
        "accepted_frames": accepted,
        "expected_frames": len(ledger_rows),
    } if ledger_rows else None)
    return {
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "monitoring_scope": "RECORDED_FILES_ONLY",
        "read_only": True,
        "can_start": False,
        "can_retry": False,
        "can_publish": False,
        "image_progress": progress,
        "queue_summary": {
            "recorded_items": sum(statuses.values()),
            "status_counts": dict(sorted(statuses.items())),
            "recorded_at": sources.get("queue", {}).get("recorded_at"),
        } if queue is not None else None,
        "frame_records": frames,
        "checkpoint_steps": last_steps,
        "review_records": reviews,
        "runner_record": runner_record,
        "recorded_sources": sources,
        "source_errors": errors,
    }
