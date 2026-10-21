"""Bounded, receipt-backed reuse of already-authored PREIMAGE payloads.

Read-only inspect checks an immutable task identity, authoritative snapshot,
the *original* successful native turn, and a real file_change in that turn.
Only the explicit canonical PREIMAGE Driver may call seal_verified. No model
dispatch, review/gate projection, or production authorization is provided.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import preimage_task_contract as tasks

ROOT = Path(__file__).resolve().parents[2]
MAX_LOG_BYTES = 4 * 1024 * 1024
MAX_CANDIDATE_BYTES = 256 * 1024


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _time(value: str) -> datetime:
    t = datetime.fromisoformat(str(value or ""))
    if t.tzinfo is None or t.utcoffset() is None:
        raise ValueError("timestamp must have timezone")
    return t.astimezone(timezone.utc)


def inspect(ep: Path, task: dict) -> dict:
    """Prove an old, FAILED metadata-only Candidate was authored by this model."""
    def refused(reason):
        return {"status": "REFUSED", "reason": reason,
                "read_only": True, "model_calls": 0, "production_authorization": False}
    try:
        ep = Path(ep).resolve()
        episode_rel = ep.relative_to((ROOT / "episodes").resolve()).as_posix()
        if task.get("task_type") not in tasks.TASK_TYPES:
            return refused("task type outside four PREIMAGE protocols")
        state = tasks.story_json.read_json(ep / tasks.STATE_REL, default={}) or {}
        row = (state.get("tasks") or {}).get(task["task_type"]) or {}
        if (state.get("snapshot_id") != task.get("snapshot_id")
                or row.get("task_id") != task.get("task_id")
                or row.get("status") != "FAILED"):
            return refused("failed task / snapshot authority not matching")
        path = ep / task["candidate_output"]
        if (not path.is_file() or path.is_symlink()
                or path.stat().st_size > MAX_CANDIDATE_BYTES):
            return refused("candidate file missing or oversized")
        original = path.read_bytes()
        candidate = json.loads(original.decode("utf-8-sig"))
        if (not isinstance(candidate, dict)
                or candidate.get("task_id") != task.get("task_id")
                or candidate.get("task_type") != task.get("task_type")
                or candidate.get("snapshot_id") != task.get("snapshot_id")
                or not isinstance(candidate.get("payload"), dict)):
            return refused("model Candidate task/snapshot identity mismatched")
        # Only incomplete Host envelope qualifies; semantic or authority errors
        # are still independently checked by the canonical Host sealing.
        if not any(k not in candidate for k in (
                "source_authority_sha256", "authority_scope", "generated_at", "status")):
            return refused("not a Host metadata omission")
        mtime = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        log = ep / "meta/scoped-workers" / (
            tasks.canonical_step(task["task_type"]).lower() + ".jsonl")
        if not log.is_file() or log.is_symlink() or log.stat().st_size > MAX_LOG_BYTES:
            return refused("native scoped model JSONL unavailable")
        data = log.read_bytes()
        starts = []
        for offset, raw in _lines(data):
            try:
                event = json.loads(raw)
            except ValueError:
                continue
            if isinstance(event, dict) and event.get("type") == "thread.started":
                starts.append(offset)
        if not starts:
            return refused("native model thread proof missing")
        ranges = list(zip(starts, starts[1:] + [len(data)]))
        receipts = []
        folder = ep / "meta/provider-receipts/model-executions"
        for path_receipt in folder.glob("*.json"):
            if (path_receipt.is_symlink() or path_receipt.stat().st_size > 16384):
                continue
            try:
                receipt = json.loads(path_receipt.read_text("utf-8-sig"))
            except (OSError, ValueError):
                continue
            if (receipt.get("step") == tasks.canonical_step(task["task_type"])
                    and receipt.get("episode_id") == episode_rel
                    and receipt.get("status") == "SUCCESS"
                    and receipt.get("call_id") == path_receipt.stem
                    and receipt.get("model_binding_source") == "EPISODE_BOUND_MODEL_POLICY"
                    and receipt.get("runner") == "codex exec"):
                receipts.append((receipt, path_receipt))
        receipts.sort(key=lambda e: _time(e[0].get("started_at")))
        # One completed scoped native turn per SUCCESS receipt, no ambiguous
        # interleaving. Do not tie a new receipt to an earlier model-written file.
        if not receipts or len(receipts) != len(ranges):
            return refused("native completed turns and successful receipts not one-to-one")
        path_name = path.resolve().as_posix().casefold()
        for (receipt, rp), (start, end) in zip(receipts, ranges):
            from_time = _time(receipt["started_at"])
            to_time = _time(receipt["finished_at"])
            if not from_time <= mtime <= to_time or from_time >= to_time:
                continue
            chunk = data[start:end]
            events = []
            for _, raw in _lines(chunk):
                try:
                    e = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(e, dict):
                    events.append(e)
            if (sum(e.get("type") == "thread.started" for e in events) != 1
                or sum(e.get("type") == "turn.completed" for e in events) != 1
                or any(e.get("type") == "turn.failed" for e in events)):
                return refused("matching model turn not completed")
            authored = False
            for e in events:
                item = e.get("item") or {}
                if (e.get("type") == "item.completed"
                        and item.get("type") == "file_change"
                        and item.get("status") == "completed"):
                    authored = any(
                        str(change.get("path") or "").replace("\\", "/").casefold()
                        == path_name and change.get("kind") in {"add", "update"}
                        for change in item.get("changes") or []
                    )
                    if authored:
                        break
            if not authored:
                return refused("matching native turn has no completed Candidate file_change")
            return {
                "status": "ELIGIBLE", "read_only": True, "model_calls": 0,
                "production_authorization": False, "task_id": task["task_id"],
                "snapshot_id": task["snapshot_id"],
                "candidate_sha256": _sha(original), "native_log_sha256": _sha(data),
                "receipt_sha256": _sha(rp.read_bytes()),
                "receipt_path": rp.relative_to(ep).as_posix(),
                "receipt_call_id": rp.stem, "log_start_offset": start,
                "log_end_offset": end, "original_model_success": True,
                "not_a_new_model_execution": True,
            }
        return refused("candidate mtime not inside an authentic successful model turn")
    except (OSError, KeyError, TypeError, ValueError, AttributeError):
        return refused("source evidence malformed or unavailable")


def _lines(data: bytes):
    """Yield exact byte offsets; never derive offsets from Unicode text."""
    offset = 0
    for raw in data.splitlines(keepends=True):
        yield offset, raw
        offset += len(raw)


def seal_verified(ep: Path, task: dict, proof: dict) -> dict:
    """A canonical Driver-only mutation; re-prove before overwriting."""
    if proof.get("status") != "ELIGIBLE":
        return {"status": "REFUSED", "reason": "not eligible"}
    latest = inspect(ep, task)
    fields = ("task_id", "snapshot_id", "candidate_sha256", "native_log_sha256",
              "receipt_sha256", "receipt_call_id", "log_start_offset", "log_end_offset")
    if latest.get("status") != "ELIGIBLE" or any(
            latest.get(k) != proof.get(k) for k in fields):
        return {"status": "REFUSED", "reason": "receipt/log/Candidate changed before Host sealing"}
    result = tasks.seal_scoped_native_candidate(
        ep, task,
        Path(ep) / "meta/scoped-workers" / (
            tasks.canonical_step(task["task_type"]).lower() + ".jsonl"),
        log_start_offset=proof["log_start_offset"],
        log_end_offset=proof["log_end_offset"],
        expected_candidate_sha256=proof["candidate_sha256"],
    )
    if result.get("status") != "PASS":
        return result
    return {"status": "PASS", "sealed": result,
            "previous_model_call_id": proof["receipt_call_id"],
            "reused_verified_model_result": True}
