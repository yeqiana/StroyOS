#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Crash reconciliation for the Production Queue and Ledger.

``episode-state.json`` remains the only stage authority.  This module only
reconciles the two execution records around an image attempt.  It deliberately
does not call an image backend: a missing or still-running worker receipt is
unknown evidence, never permission to regenerate a frame.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import uuid
from pathlib import Path
from types import SimpleNamespace

import production_ledger
import production_recovery_persistence
import production_queue_store
import scheduler_core
import image_model_policy
import runtime_timeout_policy
import provider_receipt_persistence
from runtime_atomic_store import atomic_write_json, update_json

# Repository root, derived from this module's checked-in location like every
# other Story OS module.  Do not guess it from ``ep`` parent depth: the runner
# temp isolation layout differs per platform (e.g. /tmp on Ubuntu vs a deep
# user profile on Windows), so ``ep.parents[n]`` is not portable.
ROOT = Path(__file__).resolve().parents[2]

LEDGER_REL = Path("meta/production-ledger.json")
JOURNAL_REL = Path("meta/runtime/production-commit-journal.json")
LIFECYCLE_DIR = Path("meta/image-workers")

# Canonical vocabulary lives in production_ledger; keep these module-level
# names so existing consumers (including tests) keep working.
READY_LEDGER_STATES = production_ledger.READY_LEDGER_STATES
ACTIVE_LEDGER_STATES = production_ledger.ACTIVE_LEDGER_STATES


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def lifecycle_rel(item: dict) -> Path:
    frame = int(item.get("frame") or 0)
    attempt = max(1, int(item.get("attempts") or 1))
    return LIFECYCLE_DIR / f"{frame:02d}-{item.get('id')}-a{attempt}.lifecycle.json"


def lifecycle_path(ep: Path, item: dict) -> Path:
    return Path(ep) / lifecycle_rel(item)


def _read(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def _json_safe(value: object) -> object:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(row) for key, row in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(row) for row in value]
    return value


def _journal(ep: Path, transaction_id: str, phase: str, **details: object) -> None:
    """Persist recovery transaction evidence.

    MySQL is the authority in mysql/dual modes.  JSON is retained only for
    json mode and dual-write migration compatibility.
    """
    current_mode = production_recovery_persistence.mode()
    if current_mode in {"mysql", "dual"}:
        production_recovery_persistence.update_transaction(
            ep,
            transaction_id,
            phase,
            details={str(key): _json_safe(value) for key, value in details.items()},
        )
    if current_mode == "mysql":
        return

    path = Path(ep) / JOURNAL_REL

    def mutate(data: dict) -> None:
        data.setdefault("schema_version", 1)
        rows = data.setdefault("transactions", {})
        row = rows.setdefault(transaction_id, {"transaction_id": transaction_id, "created_at": now()})
        row.update({"phase": phase, "updated_at": now(), **details})
        # The journal is recovery evidence, not an unbounded second ledger.
        if len(rows) > 200:
            ordered = sorted(rows.items(), key=lambda pair: str(pair[1].get("updated_at") or ""))
            for key, _ in ordered[:-200]:
                rows.pop(key, None)

    update_json(path, dict, mutate)


def prepare_execution(ep: Path, item: dict) -> str:
    """Persist the pre-worker side of a queue/ledger transaction.

    Callers save the containing queue before invoking ``production_ledger
    begin``.  A crash at this point is provably pre-worker and can be retried.
    """
    existing = item.get("execution") or {}
    transaction_id = str(existing.get("transaction_id") or uuid.uuid4().hex)
    item["execution"] = {
        "transaction_id": transaction_id,
        "phase": "BEGIN_PREPARED",
        "prepared_at": now(),
        "expected_lifecycle": lifecycle_rel(item).as_posix(),
    }
    _journal(ep, transaction_id, "BEGIN_PREPARED", item_id=item.get("id"), frame=item.get("frame"),
             production_revision_id=item.get("production_revision_id"),
             frame_contract_sha256=(item.get("prompt_package") or {}).get("frame_contract_sha256"),
             prompt_package_sha256=(item.get("prompt_package") or {}).get("package_sha256"))
    return transaction_id


def mark_worker_pending(ep: Path, item: dict) -> None:
    execution = item.setdefault("execution", {})
    transaction_id = str(execution.get("transaction_id") or uuid.uuid4().hex)
    execution.update({
        "transaction_id": transaction_id,
        "phase": "WORKER_PENDING",
        "worker_pending_at": now(),
        "expected_lifecycle": lifecycle_rel(item).as_posix(),
    })
    _journal(ep, transaction_id, "WORKER_PENDING", item_id=item.get("id"), frame=item.get("frame"),
             production_revision_id=item.get("production_revision_id"),
             frame_contract_sha256=(item.get("prompt_package") or {}).get("frame_contract_sha256"),
             prompt_package_sha256=(item.get("prompt_package") or {}).get("package_sha256"))


def mark_terminal(ep: Path, item: dict, phase: str, **details: object) -> None:
    execution = item.setdefault("execution", {})
    transaction_id = str(execution.get("transaction_id") or "")
    if not transaction_id:
        return
    execution["phase"] = phase
    execution["updated_at"] = now()
    _journal(ep, transaction_id, phase, item_id=item.get("id"), frame=item.get("frame"),
             production_revision_id=item.get("production_revision_id"),
             frame_contract_sha256=(item.get("prompt_package") or {}).get("frame_contract_sha256"),
             prompt_package_sha256=(item.get("prompt_package") or {}).get("package_sha256"), **details)


def write_lifecycle(ep: Path, item: dict, state: str, **details: object) -> dict:
    """Durably record worker evidence before and after a backend invocation."""
    execution = item.get("execution") or {}
    data = {
        "schema_version": 1,
        "transaction_id": execution.get("transaction_id"),
        "item_id": item.get("id"),
        "frame": int(item.get("frame") or 0),
        "attempt": max(1, int(item.get("attempts") or 1)),
        "state": state,
        "updated_at": now(),
        **_json_safe(details),
    }
    path = lifecycle_path(ep, item)
    old = _read(path)
    # The native Runner's durable result is indexed by this exact request ID.
    # A terminal worker write (notably FAILED after NETWORK_ERROR) previously
    # replaced the whole JSON row and lost the BACKEND_INVOKED ID, making any
    # later non-generating receipt reconciliation impossible. Bind the original
    # ID to the SAME transaction, Queue item, frame and technical attempt only.
    same_dispatch = bool(
        data.get("transaction_id")
        and old.get("transaction_id") == data["transaction_id"]
        and old.get("item_id") == data["item_id"]
        and int(old.get("frame") or 0) == data["frame"]
        and int(old.get("attempt") or 0) == data["attempt"]
    )
    previous_runner_id = str(old.get("runner_request_id") or "").strip() if same_dispatch else ""
    new_runner_id = str(data.get("runner_request_id") or "").strip()
    for rid in (previous_runner_id, new_runner_id):
        if rid and not re.fullmatch(r"[a-fA-F0-9]{32}", rid):
            raise RuntimeError("RUNNER_REQUEST_ID_INVALID_LIFECYCLE_PROVENANCE")
    if previous_runner_id and new_runner_id and previous_runner_id.lower() != new_runner_id.lower():
        raise RuntimeError("RUNNER_REQUEST_ID_CONFLICT_WITH_SAME_GENERATION_ATTEMPT")
    if previous_runner_id and not new_runner_id:
        data["runner_request_id"] = previous_runner_id

    if old.get("started_at"):
        data["started_at"] = old["started_at"]
    elif state == "WORKER_STARTED":
        data["started_at"] = data["updated_at"]
    if same_dispatch and old.get("generation_key") and not data.get("generation_key"):
        data["generation_key"] = old["generation_key"]
    atomic_write_json(path, data)
    transaction_id = str(data.get("transaction_id") or "")
    if transaction_id:
        _journal(ep, transaction_id, state, item_id=item.get("id"), frame=item.get("frame"), lifecycle=lifecycle_rel(item).as_posix())
    return data


def generation_key_for_item(ep: Path, item: dict) -> str:
    key = str(item.get("generation_key") or "")
    if key:
        return key
    lifecycle = _read(lifecycle_path(ep, item))
    return str(lifecycle.get("generation_key") or "")


def _ledger_frame(ledger: dict, frame: int) -> dict:
    return ((ledger.get("frames") or {}).get(f"{frame:02d}") or {})


def _latest_ledger_attempt(frame_row: dict) -> dict:
    attempts = [x for x in (frame_row.get("attempts") or []) if isinstance(x, dict)]
    return attempts[-1] if attempts else {}


def _active_ledger_attempt(frame_row: dict) -> dict:
    """Return the currently open ledger attempt, if one is durably identifiable."""
    for attempt in reversed([x for x in (frame_row.get("attempts") or []) if isinstance(x, dict)]):
        if attempt.get("result") in {None, "pending"}:
            return attempt
    return {}


def _safe_output(ep: Path, raw: object) -> Path | None:
    if not raw:
        return None
    path = Path(str(raw))
    if not path.is_absolute():
        path = (ROOT / path).resolve()
    else:
        # Windows runner TEMP may use the 8.3 short spelling (RUNNER~1) while
        # tempfile/realpath resolve to the long name. Normalize before the
        # subpath check so the same file is never judged "outside the episode".
        path = path.resolve()
    try:
        path.relative_to(Path(ep).resolve())
    except ValueError:
        return None
    return path if path.is_file() else None


def _safe_episode_reference(ep: Path, raw: object) -> Path | None:
    """Resolve an episode-local reference without requiring a physical file."""
    if not raw:
        return None
    path = Path(str(raw))
    path = (ROOT / path).resolve() if not path.is_absolute() else path.resolve()
    try:
        path.relative_to(Path(ep).resolve())
    except ValueError:
        return None
    return path


def _current_contract_sha(ep: Path, frame: int) -> str | None:
    """Current resolved Frame Contract SHA without writing the derived cache.

    Legacy/test fixtures without version evidence return None so recovery
    keeps its pre-V2.1 behavior; V2.1+ episodes compare the queue-bound
    contract against the live authority before replaying worker success.
    """
    try:
        import frame_contract

        if not frame_contract.required(ep):
            return None
        row = frame_contract.compile_frame(ep, int(frame), write_cache=False)
        return str(row.get("contract_sha256") or "")
    except Exception:
        return None


def _commit_success(ep: Path, item: dict, lifecycle: dict) -> tuple[bool, str]:
    """Commit a worker's durable success through the normal ledger verifier."""
    item_tx = str((item.get("execution") or {}).get("transaction_id") or "")
    if lifecycle.get("transaction_id") != item_tx:
        return False, "lifecycle transaction does not match queue item"
    frame_row = _ledger_frame(production_ledger.load_authority(Path(ep).resolve(), default={}) or {}, int(item.get("frame") or 0))
    active = _active_ledger_attempt(frame_row)
    if active:
        active_tx = str(active.get("runtime_transaction_id") or "")
        if active_tx and item_tx and active_tx != item_tx:
            return False, "ledger active attempt transaction does not match queue item"
        if str(active.get("kind") or "") != str(item.get("kind") or ""):
            return False, "ledger active attempt kind does not match queue item"
    result = lifecycle.get("result") or {}
    if not isinstance(result, dict):
        return False, "lifecycle result is missing"
    policy = (result.get("payload") or {}).get("image_model") or {}
    if str(policy.get("model") or "") != str(item.get("model") or ""):
        return False, "lifecycle model does not match queue contract"
    if str(policy.get("quality") or "") != str(item.get("quality") or ""):
        return False, "lifecycle quality does not match queue contract"
    expected_sha = ((item.get("frame_contract") or {}).get("contract_sha256"))
    actual_sha = (((result.get("payload") or {}).get("frame_contract") or {}).get("contract_sha256"))
    if expected_sha and str(expected_sha).lower() != str(actual_sha or "").lower():
        return False, "lifecycle frame contract does not match queue contract"
    current_sha = _current_contract_sha(ep, int(item.get("frame") or 0))
    if current_sha and expected_sha and str(current_sha).lower() != str(expected_sha).lower():
        return False, (f"lifecycle frame contract stale vs current authority "
                       f"{current_sha}")
    output = _safe_output(ep, result.get("output"))
    if output is None:
        return False, "lifecycle output is absent or outside the episode"
    receipt = (((result.get("payload") or {}).get("provider_receipt") or {}).get("path"))
    receipt_path = _safe_episode_reference(ep, receipt) if receipt else None
    if receipt and receipt_path is None:
        return False, "lifecycle provider receipt is absent or outside the episode"
    if receipt_path is not None and not provider_receipt_persistence.load_by_path(ep, receipt_path):
        return False, "lifecycle provider receipt is missing from both MySQL and compatibility JSON"
    args = SimpleNamespace(
        episode_dir=str(ep), frame=f"{int(item['frame']):02d}", path=str(output),
        provider_receipt=str(receipt_path) if receipt_path else None,
    )
    try:
        production_ledger.cmd_success(args)
    except (SystemExit, OSError, ValueError) as exc:
        return False, str(exc)
    item["status"] = "generated"
    item["output_path"] = output.relative_to(ROOT.resolve()).as_posix()
    item["completed_at"] = now()
    item["last_error"] = None
    item.pop("technical_failure_code", None)
    item.pop("external_block", None)
    item.pop("retry_exhausted", None)
    item["prompt_package"] = result.get("prompt_package")
    if result.get("log"):
        log = Path(str(result["log"]))
        if log.is_file():
            item["log_path"] = log.resolve().relative_to(ROOT.resolve()).as_posix()
    mark_terminal(ep, item, "COMMITTED", recovery="worker_success_replayed")
    return True, "worker success committed"


def _mark_technical_failure(ep: Path, item: dict, code: str, message: str) -> None:
    args = SimpleNamespace(
        episode_dir=str(ep), frame=f"{int(item['frame']):02d}", code=code, message=message[:1000]
    )
    try:
        production_ledger.cmd_tech_fail(args)
    except (SystemExit, OSError, ValueError) as exc:
        item["status"] = "interrupted_unknown"
        item["last_error"] = f"RECOVERY_LEDGER_CLOSE_FAILED: {exc}"
        mark_terminal(ep, item, "RECONCILE_PENDING", reason=item["last_error"])
        return
    # A crash before candidate commit must release its provisional raw-candidate
    # claim; technical retry is the same content-repair round, not a new budget use.
    try:
        import raw_candidate_budget
        raw_candidate_budget.release(ep, str(item.get("id") or ""), reason=f"recovery_technical_failure:{code}")
    except Exception:
        pass
    item["status"] = "tech_failed"
    item["technical_failure_code"] = str(code or "IMAGE_BACKEND_ERROR")
    item.setdefault("technical_failures", []).append({"at": now(), "attempt": int(item.get("attempts") or 0), "code": str(code or "IMAGE_BACKEND_ERROR"), "recovery": True})
    item["completed_at"] = now()
    item["last_error"] = message[:1000]
    mark_terminal(ep, item, "TECH_FAILED", code=code)


def reconcile_locked(ep: Path, queue: dict) -> dict:
    """Reconcile interrupted queue rows while the scheduler lock is held.

    The result is execution evidence only.  Unknown rows remain non-runnable;
    no path here calls a provider or changes an Episode stage.
    """
    ep = Path(ep).resolve()
    ledger = production_ledger.load_authority(ep, default={}) or {}
    report = {"schema_version": 1, "reconciled_at": now(), "rows": []}
    for item in queue.get("items") or []:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "")
        # A candidate-commit failure means the provider already returned usable
        # pixels but the final Ledger commit did not close.  It is intentionally
        # non-regenerating, so once the Ledger is repaired/replayed this blocked
        # queue row must be eligible for the same READY replay as a running row.
        commit_blocked = (
            status == "blocked"
            and str(item.get("last_error") or "").startswith("CANDIDATE_COMMIT_FAILED:")
        )
        if status not in {"running", "generated", "interrupted_unknown"} and not commit_blocked:
            continue
        frame = int(item.get("frame") or 0)
        frame_row = _ledger_frame(ledger, frame)
        ledger_status = str(frame_row.get("status") or "PENDING")
        lifecycle = _read(lifecycle_path(ep, item))
        lifecycle_state = str(lifecycle.get("state") or "MISSING")
        outcome = "UNCHANGED"

        # A historical queue row can coexist with a newer repair attempt in any
        # terminal or active ledger state. Never project the newest ledger state
        # backwards onto that older row. Ownership is transaction-bound, not just
        # frame-bound.
        latest = _latest_ledger_attempt(frame_row)
        latest_tx = str(latest.get("runtime_transaction_id") or "")
        item_tx = str((item.get("execution") or {}).get("transaction_id") or "")
        if latest_tx and item_tx and latest_tx != item_tx:
            if item.get("status") == "running":
                item["status"] = "superseded"
                item["last_error"] = None
                mark_terminal(ep, item, "SUPERSEDED", recovery="newer_ledger_attempt_owns_frame")
            outcome = "OLDER_QUEUE_ITEM_IGNORED_FOR_NEWER_LEDGER_ATTEMPT"
            report["rows"].append({"item_id": item.get("id"), "frame": frame, "outcome": outcome,
                                   "ledger_status": ledger_status, "lifecycle_state": lifecycle_state})
            ledger = production_ledger.load_authority(ep, default={}) or {}
            continue

        # A committed candidate remains a valid historical queue row after its
        # pixels are reviewed. Review/authorization states belong to the Ledger,
        # not to Queue execution. Keep the generated row intact when it is still
        # the ledger's SHA/path-bound current candidate; otherwise a subsequent
        # scheduler run would misclassify a reviewed candidate as an interruption.
        if ledger_status in {"CONTENT_FAILED", "REPAIR_AUTHORIZED", "AUTHORITY_REFRESH_AUTHORIZED", "EXCEPTION_REPAIR_AUTHORIZED", "NEEDS_USER"}:
            candidate = frame_row.get("current_candidate") or {}
            candidate_path = _safe_output(ep, candidate.get("path"))
            item_output = _safe_output(ep, item.get("output_path"))
            if candidate_path is not None and item_output is not None and candidate_path == item_output:
                item["status"] = "generated"
                item["last_error"] = None
                item.pop("technical_failure_code", None)
                item.pop("external_block", None)
                item.pop("retry_exhausted", None)
                outcome = "REVIEWED_CANDIDATE_RETAINED"
                report["rows"].append({"item_id": item.get("id"), "frame": frame, "outcome": outcome,
                                       "ledger_status": ledger_status, "lifecycle_state": lifecycle_state})
                ledger = production_ledger.load_authority(ep, default={}) or {}
                continue

        if ledger_status in READY_LEDGER_STATES:
            candidate = frame_row.get("current_candidate") or {}
            candidate_path = _safe_output(ep, candidate.get("path"))
            if candidate_path:
                item["status"] = "generated"
                item["output_path"] = candidate_path.relative_to(ROOT.resolve()).as_posix()
                item["completed_at"] = item.get("completed_at") or now()
                item["last_error"] = None
                item.pop("technical_failure_code", None)
                item.pop("external_block", None)
                item.pop("retry_exhausted", None)
                mark_terminal(ep, item, "COMMITTED", recovery="ledger_ready_replayed")
                outcome = "LEDGER_READY_REPLAYED"
            else:
                item["status"] = "interrupted_unknown"
                item["last_error"] = "RECOVERY_LEDGER_READY_CANDIDATE_MISSING"
                mark_terminal(ep, item, "RECONCILE_PENDING", reason=item["last_error"])
                outcome = "LEDGER_READY_CANDIDATE_MISSING"
        elif ledger_status == "TECH_FAILED":
            item["status"] = "tech_failed"
            item["last_error"] = item.get("last_error") or "RECOVERY_LEDGER_TECH_FAILED"
            mark_terminal(ep, item, "TECH_FAILED", recovery="ledger_tech_failed_replayed")
            outcome = "LEDGER_TECH_FAILED_REPLAYED"
        elif ledger_status in ACTIVE_LEDGER_STATES:
            if lifecycle_state == "SUCCEEDED":
                ok, note = _commit_success(ep, item, lifecycle)
                if ok:
                    outcome = "WORKER_SUCCESS_REPLAYED"
                else:
                    item["status"] = "interrupted_unknown"
                    item["last_error"] = f"RECOVERY_SUCCESS_EVIDENCE_INVALID: {note}"
                    mark_terminal(ep, item, "RECONCILE_PENDING", reason=item["last_error"])
                    outcome = "SUCCESS_EVIDENCE_INVALID"
            elif lifecycle_state == "FAILED":
                failure = str(lifecycle.get("error") or "worker failed before scheduler commit")
                failure_code = (
                    image_model_policy.classify_backend_error(failure, source="image_backend")
                    or "WORKER_INTERRUPTED_FAILURE"
                )
                _mark_technical_failure(ep, item, failure_code, failure)
                outcome = "WORKER_FAILURE_REPLAYED"
            elif lifecycle_state in {"WORKER_STARTED", "BACKEND_INVOKED"}:
                # Resume is allowed to classify an abandoned worker as a
                # technical failure only after inspecting durable evidence:
                # the recorded worker PID is dead and no candidate output was
                # written. If an output exists, keep fail-closed because provider
                # success may have happened without a terminal receipt.
                worker_pid = lifecycle.get("worker_pid")
                worker_alive = False
                if worker_pid:
                    try:
                        import codex_user_runner
                        worker_alive = codex_user_runner._pid_alive(worker_pid)
                    except Exception:
                        worker_alive = True
                output = _safe_output(ep, lifecycle.get("expected_output"))
                runner_request_id = str(
                    lifecycle.get("runner_request_id")
                    or ((item.get("execution") or {}).get("runner_request_id"))
                    or ""
                ).strip()
                if worker_pid and not worker_alive and output is None and runner_request_id:
                    try:
                        recovered = recover_user_runner_success(
                            ep, frame, runner_request_id,
                            queue_override=queue,
                            write_queue=False,
                        )
                        outcome = "USER_RUNNER_SUCCESS_RECOVERED"
                        item["recovery"] = {
                            "runner_request_id": runner_request_id,
                            "recovered_at": now(),
                            "output": recovered.get("output"),
                        }
                    except Exception as exc:
                        persisted = None
                        try:
                            import codex_user_runner
                            persisted = codex_user_runner.read_task_result(runner_request_id)
                        except Exception:
                            persisted = None
                        if persisted:
                            _mark_technical_failure(
                                ep, item, "RUNNER_RESULT_RECOVERY_FAILED",
                                f"runner request {runner_request_id} had durable result but recovery failed: {exc}"
                            )
                            outcome = "RUNNER_RESULT_RECOVERY_FAILED"
                        else:
                            _mark_technical_failure(
                                ep, item, "WORKER_PROCESS_LOST",
                                f"worker pid={worker_pid} disappeared before terminal receipt; runner request={runner_request_id} has no durable result"
                            )
                            outcome = "DEAD_WORKER_NO_RUNNER_RESULT_RETRYABLE"
                elif worker_pid and not worker_alive and output is None:
                    _mark_technical_failure(
                        ep, item, "WORKER_PROCESS_LOST",
                        f"worker pid={worker_pid} disappeared before terminal receipt and produced no candidate"
                    )
                    outcome = "DEAD_WORKER_NO_OUTPUT_RETRYABLE"
                else:
                    item["status"] = "interrupted_unknown"
                    item["last_error"] = "RECOVERY_UNKNOWN_RUNNING_WORKER: lifecycle has no terminal receipt"
                    mark_terminal(ep, item, "RECONCILE_PENDING", reason=item["last_error"])
                    outcome = "UNKNOWN_RUNNING_WORKER"
            elif lifecycle_state == "MISSING" and str((item.get("execution") or {}).get("phase") or "") in {"BEGIN_PREPARED", "WORKER_PENDING"}:
                _mark_technical_failure(ep, item, "SCHEDULER_INTERRUPTED_BEFORE_WORKER", "scheduler stopped before worker lifecycle began")
                outcome = "PRE_WORKER_INTERRUPTION_RETRYABLE"
            else:
                item["status"] = "interrupted_unknown"
                item["last_error"] = "RECOVERY_UNKNOWN_RUNNING_WORKER: lifecycle has no terminal receipt"
                mark_terminal(ep, item, "RECONCILE_PENDING", reason=item["last_error"])
                outcome = "UNKNOWN_RUNNING_WORKER"
        elif ledger_status == "PENDING" and str((item.get("execution") or {}).get("phase") or "") == "BEGIN_PREPARED" and lifecycle_state == "MISSING":
            item["status"] = "queued"
            item.pop("execution", None)
            item["last_error"] = None
            outcome = "PRE_BEGIN_PREPARATION_REPLAYED"
        else:
            item["status"] = "interrupted_unknown"
            item["last_error"] = f"RECOVERY_QUEUE_LEDGER_MISMATCH: queue={item.get('status')} ledger={ledger_status} lifecycle={lifecycle_state}"
            mark_terminal(ep, item, "RECONCILE_PENDING", reason=item["last_error"])
            outcome = "QUEUE_LEDGER_MISMATCH"
        report["rows"].append({"item_id": item.get("id"), "frame": frame, "outcome": outcome,
                               "ledger_status": ledger_status, "lifecycle_state": lifecycle_state})
        ledger = production_ledger.load_authority(ep, default={}) or {}
    atomic_write_json(ep / "meta/runtime/production-reconciliation.json", report)
    return report


def _recover_user_runner_success_locked(ep: Path, frame: int, request_id: str, *, queue_override: dict | None = None, write_queue: bool = True) -> dict:
    """Recover a real Codex image when the scheduler died after provider success.

    This is deliberately fail-closed.  It accepts only an ``interrupted_unknown``
    queue row, a successful image task from the authenticated user runner, an exact
    request hash match, and a real provider artifact.  It does not call the image
    provider again and it preserves ``codex_subscription`` provenance.

    Current recovery supports reference-free image tasks because temporary proxy
    reference paths are intentionally destroyed with the interrupted worker.  A
    reference-bound interrupted task remains unknown rather than guessing.
    """
    import codex_subscription_image as backend
    import codex_user_runner
    import image_model_policy
    import prompt_package
    import raw_candidate_budget

    ep = Path(ep).resolve()
    queue = queue_override if isinstance(queue_override, dict) else scheduler_core.load_queue(ep)
    rows = [x for x in queue.get("items") or []
            if isinstance(x, dict) and int(x.get("frame") or 0) == int(frame)
            and x.get("status") in {"interrupted_unknown", "running", "tech_failed", "external_blocked"}]
    if not rows:
        raise RuntimeError(f"RECOVERY_ITEM_MISSING: frame={int(frame):02d}")

    runner_row = None
    persisted = codex_user_runner.read_task_result(str(request_id))
    if isinstance(persisted, dict):
        evidence = persisted.get("evidence") or {}
        if isinstance(evidence, dict) and str(evidence.get("request_id") or "") == str(request_id):
            runner_row = evidence
    if runner_row is None:
        runner_log = codex_user_runner.runtime_dir() / codex_user_runner.LOG_NAME
        if runner_log.is_file():
            for raw in runner_log.read_text(encoding="utf-8-sig").splitlines():
                try:
                    row = json.loads(raw)
                except Exception:
                    continue
                if isinstance(row, dict) and str(row.get("request_id") or "") == str(request_id):
                    runner_row = row
                    break
    if not runner_row:
        raise RuntimeError(f"RECOVERY_RUNNER_REQUEST_MISSING: {request_id}")
    runner_rc = runner_row.get("returncode")
    if runner_row.get("task_type") != "image" or runner_rc is None or int(runner_rc) != 0:
        raise RuntimeError("RECOVERY_RUNNER_REQUEST_NOT_SUCCESSFUL_IMAGE")
    artifacts = runner_row.get("generated_artifacts") or []
    if not isinstance(artifacts, list) or len(artifacts) != 1:
        raise RuntimeError(f"RECOVERY_ARTIFACT_COUNT_INVALID: {len(artifacts) if isinstance(artifacts, list) else 'non-list'}")

    visual = backend.compile_prompt_contract(ep)
    width, height, _ = backend.read_canvas(ep)
    size = backend.provider_size(width, height)
    episode_policy = image_model_policy.for_episode(ep)
    runner_sha = str(runner_row.get("stdin_sha256") or "").lower()
    runner_inputs = [x for x in (runner_row.get("input_images") or []) if isinstance(x, dict)]
    matches = []
    for candidate in rows:
        lifecycle = _read(lifecycle_path(ep, candidate))
        bound_request_id = str(
            lifecycle.get("runner_request_id")
            or ((candidate.get("execution") or {}).get("runner_request_id"))
            or ""
        ).strip()
        if bound_request_id and bound_request_id != str(request_id):
            continue
        refs = candidate.get("references") or []
        if len(refs) != len(runner_inputs):
            continue
        candidate_prompt = (ROOT / str(candidate.get("prompt_file") or "")).resolve()
        if not candidate_prompt.is_file():
            continue
        candidate_package = prompt_package.compile_frame(ep, int(frame), candidate_prompt, write=False)
        candidate_model = str(candidate.get("model") or episode_policy["model"])
        candidate_quality = str(candidate.get("quality") or episode_policy["quality"])
        candidate_strict = bool(candidate.get("strict_model", episode_policy.get("strict_model")))
        # The image worker prompt names only the disposable proxy basename, not
        # its absolute path. Recreate those names from runner evidence so legacy
        # reference-bound tasks can still be matched exactly by stdin SHA.
        proxy_refs = []
        for index, row in enumerate(runner_inputs, 1):
            raw = str(row.get("source") or row.get("staged") or "").strip()
            name = Path(raw).name if raw else f"reference-{index:02d}.jpg"
            proxy_refs.append(Path(name))
        candidate_stdin = backend.worker_prompt(
            candidate_package["scene_prompt"], proxy_refs, size, visual["text"], candidate_package["frame_prompt_contract"],
            candidate_model, candidate_quality, candidate_strict,
        ).encode("utf-8")
        candidate_sha = hashlib.sha256(candidate_stdin).hexdigest()
        # New workers bind request_id before provider invocation. Legacy workers
        # without that binding must still match the exact stdin contract.
        if bound_request_id or candidate_sha.lower() == runner_sha:
            worker_pid = lifecycle.get("worker_pid") if isinstance(lifecycle, dict) else None
            if candidate.get("status") == "running" and worker_pid and codex_user_runner._pid_alive(worker_pid):
                raise RuntimeError(f"RECOVERY_WORKER_STILL_ALIVE: pid={worker_pid}")
            matches.append((candidate, candidate_prompt, candidate_package, candidate_model,
                            candidate_quality, candidate_strict, candidate_sha))
    if len(matches) != 1:
        raise RuntimeError(
            f"RECOVERY_REQUEST_MATCH_NOT_UNIQUE: frame={int(frame):02d} matches={len(matches)} runner_sha={runner_sha}"
        )
    item, prompt_path, package, model, quality, strict_model, expected_sha = matches[0]
    original_refs = [
        (ROOT / str(ref.get("path") or "")).resolve()
        for ref in (item.get("references") or [])
        if isinstance(ref, dict) and ref.get("path")
    ]
    if len(original_refs) != len(runner_inputs):
        raise RuntimeError("RECOVERY_REFERENCE_COUNT_MISMATCH")
    if any(not ref.is_file() for ref in original_refs):
        raise RuntimeError("RECOVERY_REFERENCE_SOURCE_MISSING")

    home, _ = codex_user_runner.codex_home()
    artifact = (home / "generated_images" / str(artifacts[0])).resolve()
    try:
        artifact.relative_to((home / "generated_images").resolve())
    except ValueError as exc:
        raise RuntimeError("RECOVERY_ARTIFACT_OUTSIDE_CODEX_GENERATED_IMAGES") from exc
    if not backend.valid_image(artifact):
        raise RuntimeError(f"RECOVERY_ARTIFACT_INVALID: {artifact}")

    attempt = max(1, int(item.get("attempts") or 1))
    output = ep / "media/candidates/scheduled" / f"{int(frame):02d}-{item['id']}-a{attempt}.png"
    log = ep / "meta/image-workers" / f"{int(frame):02d}-{item['id']}-a{attempt}.jsonl"
    policy = {**episode_policy, "model": model, "quality": quality, "strict_model": strict_model}
    ns = SimpleNamespace(
        episode_dir=ep, frame=f"{int(frame):02d}", prompt_file=prompt_path, output=output, log=log,
        # The namespace mirrors a real worker CLI parse, so its timeout carries the
        # same policy-resolved default. Recovery itself never invokes the provider
        # (see _recovered_codex_raw below), so this value is never read here; it
        # exists so this namespace stays equivalent to the CLI one.
        reference=original_refs,
        timeout=runtime_timeout_policy.seconds("image_worker_request"),
        codex=None, image_model=model, image_quality=quality,
        # Recovery never calls the provider again. If the interrupted worker had
        # already written the normalized candidate before dying, rebuild the same
        # file from the hash-matched recovered provider artifact and overwrite it
        # deterministically so queue/ledger commit can finish.
        overwrite=True, _image_model_policy=policy,
        _recovered_codex_raw=artifact, _recovered_runner_request_id=str(request_id),
    )
    payload = backend.generate_for_frame(ns)

    generation_key = generation_key_for_item(ep, item)
    if not generation_key:
        raise RuntimeError("RECOVERY_GENERATION_ATTEMPT_EVIDENCE_MISSING")
    import generation_attempt_authority
    budget_row = generation_attempt_authority.complete_external_generation(
        ep, generation_attempt_authority.frame_key(ep, frame), generation_key,
        result_ref=str(output),
    )
    result = {
        "returncode": 0,
        "stdout": "",
        "payload": payload,
        "output": output,
        "log": log,
        "attempt": attempt,
        "scout": None,
        "candidate_budget": budget_row,
        "prompt_package": {
            "package_sha256": package["package_sha256"],
            "scene_prompt_sha256": package["scene_prompt_sha256"],
            "frame_contract_sha256": package["frame_contract_sha256"],
        },
        "worker_pool": {"mode": "user_runner_success_recovery", "codex_session_reuse": False},
        "recovery": {"runner_request_id": str(request_id), "stdin_sha256": expected_sha},
    }
    write_lifecycle(ep, item, "SUCCEEDED", worker_pid=None, result=result,
                    recovery="interrupted_user_runner_success", runner_request_id=str(request_id))
    frame_row = _ledger_frame(production_ledger.load_authority(ep, default={}) or {}, int(frame))
    latest = _latest_ledger_attempt(frame_row)
    if latest.get("result") == "technical_failure":
        correction_args = SimpleNamespace(
            episode_dir=str(ep), frame=f"{int(frame):02d}", path=str(output),
            provider_receipt=str((payload.get("provider_receipt") or {}).get("path") or ""),
            transaction_id=str((item.get("execution") or {}).get("transaction_id") or ""),
            runner_request_id=str(request_id),
        )
        try:
            production_ledger.cmd_recover_success(correction_args)
        except (SystemExit, OSError, ValueError) as exc:
            raise RuntimeError(f"RECOVERY_LEDGER_CORRECTION_FAILED: {exc}") from exc
        item["status"] = "generated"
        item["output_path"] = output.relative_to(ROOT.resolve()).as_posix()
        item["completed_at"] = now()
        item["last_error"] = None
        item["prompt_package"] = result.get("prompt_package")
        item.pop("technical_failure_code", None)
        item.pop("retry_exhausted", None)
        item.pop("external_block_reason", None)
        if log.is_file():
            item["log_path"] = log.resolve().relative_to(ROOT.resolve()).as_posix()
        mark_terminal(ep, item, "COMMITTED", recovery="late_user_runner_success_corrected")
    else:
        ok, note = _commit_success(ep, item, _read(lifecycle_path(ep, item)))
        if not ok:
            raise RuntimeError(f"RECOVERY_LEDGER_COMMIT_FAILED: {note}")
    if write_queue:
        scheduler_core.save_queue(ep, queue)
    return {
        "ok": True,
        "frame": f"{int(frame):02d}",
        "item_id": item.get("id"),
        "runner_request_id": str(request_id),
        "stdin_sha256": expected_sha,
        "artifact": str(artifact),
        "output": str(output),
        "provider_receipt": (payload.get("provider_receipt") or {}).get("path"),
    }


def recover_user_runner_success(ep: Path, frame: int, request_id: str, *, queue_override: dict | None = None, write_queue: bool = True) -> dict:
    ep = Path(ep).resolve()
    with scheduler_core.queue_transaction(ep):
        return _recover_user_runner_success_locked(
            ep, frame, request_id, queue_override=queue_override, write_queue=write_queue
        )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("recover-user-runner-success")
    p.add_argument("episode_dir", type=Path)
    p.add_argument("--frame", type=int, required=True)
    p.add_argument("--request-id", required=True)
    args = ap.parse_args()
    if args.cmd == "recover-user-runner-success":
        try:
            result = recover_user_runner_success(args.episode_dir, args.frame, args.request_id)
        except Exception as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())