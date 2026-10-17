"""Bounded reconciliation of preserved native image NETWORK_ERROR receipts.

Never calls a model, never claims upstream billing was zero. A verified native
Runner terminal failure + byte-identical original CLI output proves no local
usable image, allowing *only* Attempt #2 under the existing two-attempt cap.

The one-time operator risk acknowledgement is separate from source evidence.
"""
from __future__ import annotations
import base64
import hashlib
import json
import os
import re
from contextlib import contextmanager
from pathlib import Path

import codex_user_runner
import generation_attempt_authority as authority
import image_blocked_recovery
import logical_asset_identity
import production_ledger
import scheduler_core

ROOT = Path(__file__).resolve().parents[2]

FAILURE_CLASS = "IMAGE_TOOL_NETWORK_ERROR_DURABLE_RECEIPT"
RECOVERY_KEY = "native_network_terminal_rearm_count"
NETWORK_WORDING = frozenset({
    "Image generation failed due to a network error.",
    "Image generation failed because of a network error.",
    "Image generation failed because of a network error. I made one attempt.",
})
HEX32 = re.compile(r"[a-fA-F0-9]{32}\Z")
HEX64 = re.compile(r"[a-fA-F0-9]{64}\Z")


class EvidenceDenied(RuntimeError):
    pass


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _matched_receipt(log: bytes) -> dict:
    """Only immutable Runner receipts whose full output exactly matches the log."""
    wanted = _hash(log)
    if not log or len(log) > 2_000_000:
        raise EvidenceDenied("INVALID_OR_OVERSIZED_ORIGINAL_LOG")
    path = (codex_user_runner.endpoint_path().parent
            if codex_user_runner.bridge_required()
            else codex_user_runner.ROOT / codex_user_runner.RUNTIME_REL)
    root = path / codex_user_runner.RESULT_DIR_NAME
    if not root.is_dir():
        raise EvidenceDenied("RUNNER_RESULTS_UNAVAILABLE")
    candidates = []
    count = 0
    for entry in root.glob("*.json"):
        count += 1
        if count > 10000:
            raise EvidenceDenied("RUNNER_RESULT_INDEX_UNBOUNDED")
        try:
            record = _json(entry)
        except (OSError, ValueError, UnicodeError):
            continue
        if record.get("output_sha256") == wanted:
            candidates.append((entry, record))
            if len(candidates) > 1:
                raise EvidenceDenied("AMBIGUOUS_ORIGINAL_RUNNER_RESULT")
    if len(candidates) != 1:
        raise EvidenceDenied("ORIGINAL_RUNNER_RESULT_NOT_UNIQUELY_FOUND")
    entry, record = candidates[0]
    rid = record.get("request_id")
    evidence = record.get("evidence") or {}
    try:
        echoed = base64.b64decode(record.get("output_base64") or "", validate=True)
    except Exception as exc:
        raise EvidenceDenied("CORRUPT_ORIGINAL_RUNNER_RESULT_BYTES") from exc
    if (not isinstance(rid, str) or not HEX32.fullmatch(rid)
            or entry.stem != rid
            or not isinstance(evidence, dict)
            or evidence.get("request_id") != rid
            or evidence.get("task_type") != "image"
            or evidence.get("transport_route") != "native_codex"
            or record.get("returncode") != 0
            or evidence.get("returncode") != 0
            or evidence.get("timed_out") is True
            or evidence.get("generated_artifacts") not in (None, [])
            or len(echoed) != record.get("output_bytes")
            or echoed != log):
        raise EvidenceDenied("RUNNER_RECEIPT_NOT_VERIFIED_TERMINAL_IMAGE_TASK")
    return {"request_id": rid, "receipt": entry, "receipt_sha256": _hash(entry.read_bytes()),
            "log_sha256": wanted}


def _network_failed_log(log: bytes) -> bool:
    """Require the Codex image router error, not just a model-written claim.

    Native --json stdout may contain stderr startup diagnostics; allow only
    known CLI noise. The entire byte stream must separately match the stored
    original native Runner result SHA-256.
    """
    try:
        lines = log.decode("utf-8-sig").splitlines()
    except UnicodeError:
        return False
    if len(lines) > 64:
        return False
    events = []
    router_failures = 0
    timestamp = r"\d{4}-\d{2}-\d{2}T[^\s]{8,40}Z"
    for line in lines:
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except ValueError:
            if len(line) > 380:
                return False
            if line.startswith("WARNING: proceeding, even though we could not create PATH aliases:"):
                continue
            if line == "Reading prompt from stdin...":
                continue
            if re.fullmatch(timestamp + r" ERROR codex_models_manager::manager: failed to refresh available models.*", line):
                continue
            if re.fullmatch(timestamp + r" ERROR codex_core::tools::router: error=image generation failed: network error: error sending request", line):
                router_failures += 1
                continue
            return False
        if not isinstance(event, dict):
            return False
        events.append(event)
    if router_failures != 1:
        return False
    if sum(e.get("type") == "turn.completed" for e in events) != 1:
        return False
    if any(e.get("type") not in {"thread.started", "turn.started",
                                "item.completed", "turn.completed"} for e in events):
        return False
    messages = []
    for e in events:
        if e.get("type") != "item.completed":
            continue
        item = e.get("item") or {}
        if not isinstance(item, dict) or item.get("type") != "agent_message":
            return False
        messages.append(str(item.get("text") or ""))
    return bool(messages and messages[-1] in NETWORK_WORDING)


def _log_and_queue(ep: Path, row: dict) -> tuple[Path, bytes]:
    n = int(row["frame"])
    logs = list((ep / "meta" / "image-workers").glob(f"{n:02d}-*.jsonl"))
    if len(logs) != 1 or not logs[0].is_file():
        raise EvidenceDenied("ORIGINAL_FRAME_LOG_NOT_UNIQUE")
    path = logs[0].resolve()
    if not path.is_relative_to(ep.resolve()):
        raise EvidenceDenied("ORIGINAL_LOG_OUTSIDE_EPISODE")
    content = path.read_bytes()
    if not _network_failed_log(content):
        raise EvidenceDenied("NATIVE_RUNNER_TERMINAL_NETWORK_FAILURE_NOT_PROVEN")
    return path, content


def inspect(ep: Path, row: dict) -> dict:
    """Read-only hard gate. A native Runner receipt is not proof of zero charge."""
    ep = Path(ep).resolve()
    frame = int(row.get("frame") or 0)
    if (row.get("scope") != "batch" or row.get("kind") != "original"
            or frame not in (5, 10, 15)  # narrow historical campaign only
            or row.get("status") != "external_blocked"
            or row.get("technical_failure_code") != "IMAGE_BACKEND_ERROR"
            or not str(row.get("last_error") or "").startswith("NETWORK_ERROR:")
            or int(row.get(RECOVERY_KEY) or 0) != 0
            or row.get("output_path") or row.get("candidate_output_path")):
        raise EvidenceDenied("NOT_A_BOUNDED_HISTORICAL_NETWORK_ERROR")
    if list((ep / "media" / "raw").glob(f"{frame:02d}-*.png")):
        raise EvidenceDenied("RAW_IMAGE_MUST_BE_RECONCILED_INSTEAD")
    logpath, output = _log_and_queue(ep, row)
    proof = _matched_receipt(output)
    key = logical_asset_identity.frame_asset_key(ep, frame)
    state = authority.load_asset_state(ep, key)
    attempt = authority.load_attempt(ep, key, 1) or {}
    generation_key = authority.stable_generation_key(logical_asset_identity.episode_id(ep), key, 1)
    contract_sha = str((row.get("frame_contract") or {}).get("contract_sha256") or "")
    package_sha = str((row.get("prompt_package") or {}).get("package_sha256") or "")
    if not HEX64.fullmatch(contract_sha) or not HEX64.fullmatch(package_sha):
        raise EvidenceDenied("FRAME_AND_PROMPT_CONTRACT_SHA_REQUIRED")

    if (int(state.get("attempts_consumed") or 0) != 1
            or state.get("active_attempt_index") is not None
            or int(state.get("fencing_counter") or 0) != 1
            or attempt.get("status") not in ("OUTCOME_UNKNOWN", "FAILED_AFTER_DISPATCH")
            or attempt.get("provider") != "codex_subscription"
            or attempt.get("payload_model") != row.get("model")
            or attempt.get("payload_quality") != row.get("quality")

            or attempt.get("generation_key") != generation_key
            or attempt.get("attempt_index") != 1
            or attempt.get("result_ref")
            or not attempt.get("dispatch_committed_at")
            or not attempt.get("generation_observed_at")):
        raise EvidenceDenied("PAID_GENERATION_ATTEMPT_NOT_ELIGIBLE")
    already = attempt["status"] == "FAILED_AFTER_DISPATCH"
    if already and attempt.get("failure_class") != FAILURE_CLASS:
        raise EvidenceDenied("CONFLICTING_EXISTING_TERMINAL_CLASSIFICATION")
    if not already and attempt.get("failure_class") != "generation_failed_before_candidate_commit":
        raise EvidenceDenied("UNKNOWN_ATTEMPT_NOT_RECORDED_NETWORK_FAILURE")
    # Cross-check this is the exact failed Ledger transaction, not an unrelated log.
    ledger = production_ledger.load_authority(ep, default={}) or {}
    latest = image_blocked_recovery._latest_attempt(ledger, frame)
    if (latest.get("result") != "technical_failure"
            or str(latest.get("runtime_transaction_id") or "") !=
               str((row.get("execution") or {}).get("transaction_id") or "")
            or not latest.get("runtime_transaction_id")):
        raise EvidenceDenied("LEDGER_TRANSACTION_MISMATCH")
    if str((latest.get("request") or {}).get("frame_contract_sha256") or "") != contract_sha:
        raise EvidenceDenied("LEDGER_FRAME_CONTRACT_SHA_MISMATCH")
    return {**proof, "frame": frame, "asset_key": key, "generation_key": generation_key,
            "log": logpath, "already_terminal": already, "item_id": row["id"],
            "transaction_id": latest["runtime_transaction_id"],
            "frame_contract_sha256": contract_sha, "prompt_package_sha256": package_sha}


@contextmanager
def _freeze_sources(proof: dict):
    # Exclusive against write/replace on the local Windows production host.
    handles = []
    if os.name == "nt":
        import native_baseline_source_freeze as freeze
        try:
            for source in sorted((proof["log"], proof["receipt"]), key=str):
                handles.append(freeze._windows_open_shared_read(source))
            yield
        finally:
            for handle in reversed(handles):
                freeze._windows_close(handle)
    else:
        yield


def _commit_terminal(ep: Path, proof: dict) -> None:
    with _freeze_sources(proof):
        conn = authority._connect()
        try:
            with conn.transaction():
                if (_hash(proof["log"].read_bytes()) != proof["log_sha256"]
                        or _hash(proof["receipt"].read_bytes()) != proof["receipt_sha256"]):
                    raise EvidenceDenied("NATIVE_RUNNER_SOURCE_CHANGED")
                eid = authority._episode_id(ep)
                state = authority._row(conn, eid, proof["asset_key"])
                row = conn.query_one(
                    "SELECT * FROM TB_GENERATION_ATTEMPT WHERE EPISODE_ID=%s "
                    "AND LOGICAL_ASSET_KEY=%s AND ATTEMPT_INDEX=1 FOR UPDATE",
                    (eid, proof["asset_key"]))
                if (not state or not row
                    or int(state.get("ATTEMPTS_CONSUMED") or 0) != 1
                    or state.get("ACTIVE_ATTEMPT_INDEX") is not None
                    or int(state.get("FENCING_COUNTER") or 0) != 1
                    or int(row.get("FENCING_TOKEN") or 0) != 1
                    or row.get("GENERATION_KEY") != proof["generation_key"]
                    or row.get("PROVIDER") != "codex_subscription"
                    or row.get("RESULT_REF")
                    or row.get("DISPATCH_COMMITTED_AT") is None
                    or row.get("GENERATION_OBSERVED_AT") is None):
                    raise EvidenceDenied("MYSQL_ORIGINAL_ATTEMPT_FENCE_CHANGED")
                if row["STATUS"] == "FAILED_AFTER_DISPATCH":
                    if row.get("FAILURE_CLASS") != FAILURE_CLASS:
                        raise EvidenceDenied("MYSQL_TERMINAL_CLASS_CONFLICT")
                    return
                if (row["STATUS"] != "OUTCOME_UNKNOWN"
                        or row.get("FAILURE_CLASS") != "generation_failed_before_candidate_commit"):
                    raise EvidenceDenied("MYSQL_UNKNOWN_ATTEMPT_NO_LONGER_ELIGIBLE")
                context = authority._context(row)
                if (context.get("scope") != "batch"
                    or context.get("queue_item_id") != proof["item_id"]
                    or context.get("frame_contract_sha256") != proof["frame_contract_sha256"]
                    or context.get("prompt_package_sha256") != proof["prompt_package_sha256"]
                    or context.get("runner_request_id") not in (None, "", proof["request_id"])):
                    raise EvidenceDenied("MYSQL_GENERATION_CONTEXT_MISMATCH")
                context["runner_request_id"] = proof["request_id"]
                context["network_failure_runner_receipt_sha256"] = proof["receipt_sha256"]
                context["network_failure_original_log_sha256"] = proof["log_sha256"]
                context["upstream_billing_outcome_unverified"] = True
                context["network_failure_original_transaction_id"] = proof["transaction_id"]
                updated = conn.execute(
                    "UPDATE TB_GENERATION_ATTEMPT SET STATUS='FAILED_AFTER_DISPATCH', "
                    "FAILURE_CLASS=%s, CONTEXT=%s WHERE EPISODE_ID=%s "
                    "AND LOGICAL_ASSET_KEY=%s AND ATTEMPT_INDEX=1 "
                    "AND STATUS='OUTCOME_UNKNOWN' AND GENERATION_KEY=%s AND FENCING_TOKEN=1 "
                    "AND RESULT_REF IS NULL AND FAILURE_CLASS='generation_failed_before_candidate_commit'",
                    (FAILURE_CLASS, json.dumps(context, ensure_ascii=False, sort_keys=True),
                     eid, proof["asset_key"], proof["generation_key"]))
                if updated != 1:
                    raise EvidenceDenied("MYSQL_NETWORK_RECONCILIATION_CAS_LOST")
                if (_hash(proof["log"].read_bytes()) != proof["log_sha256"]
                        or _hash(proof["receipt"].read_bytes()) != proof["receipt_sha256"]):
                    raise EvidenceDenied("NATIVE_RUNNER_SOURCE_CHANGED_BEFORE_COMMIT")
        finally:
            conn.close()


def rearm_one(ep: Path, frame: int, *, acknowledged: bool = False) -> dict:
    """Terminalize original local network failure, then queue only Attempt 2."""
    if not acknowledged:
        return {"status": "BLOCKED", "reason": "DUPLICATE_UPSTREAM_COST_RISK_ACK_REQUIRED"}
    ep = Path(ep).resolve()
    try:
        with scheduler_core.queue_transaction(ep):
            q = scheduler_core.load_queue(ep)
            row = next((x for x in q.get("items",[]) if x.get("scope") == "batch"
                        and int(x.get("frame") or 0) == int(frame)), None)
            if row is None:
                return {"status": "BLOCKED", "reason": "MISSING_FRAME"}
            proof = inspect(ep, row)
            _commit_terminal(ep, proof)
            row[RECOVERY_KEY] = 1
            row["native_network_source_technical_attempts"] = int(row.get("attempts") or 0)
            row["native_network_terminal_receipt_sha256"] = proof["receipt_sha256"]
            row["native_network_terminal_original_log_sha256"] = proof["log_sha256"]
            row["attempts"] = 0
            row["status"] = "queued"
            row["last_error"] = None
            row.pop("external_block", None)
            row.pop("technical_failure_code", None)
            row.pop("completed_at", None)
            row.pop("execution", None)
            scheduler_core.save_queue(ep, q)
            return {"status":"PASS","frame":int(frame),"provider_calls":0,
                    "additional_attempts_consumed":0,
                    "remaining_real_attempt_budget":1,
                    "upstream_billing_outcome_unverified":True}
    except scheduler_core.QueueMutationBusy:
        return {"status": "BLOCKED", "reason": "QUEUE_MUTATION_BUSY"}
    except EvidenceDenied as e:
        return {"status": "BLOCKED", "reason": str(e)}



def remaining_second_attempt(ep: Path, row: dict) -> bool:
    """Read-only: authorize a fresh NON-generating visibility probe for Attempt #2.

    Only an original paid first Attempt with verified network-terminal receipt
    can take this path. It never changes the original result or quota.
    """
    try:
        ep = Path(ep).resolve()
        frame = int(row.get("frame") or 0)
        if (ep.name != "13_失物归还的那扇门"
                or ep.parent.name != "00_独立篇"
                or not ep.is_relative_to(ROOT / "episodes")
                or frame not in (5, 10, 15)
                or row.get("scope") != "batch" or row.get("kind") != "original"
                or row.get("status") not in {"blocked","queued","running","generating"}
                or row.get("native_batch_verified_followon") is not True
                or int(row.get(RECOVERY_KEY) or 0) != 1
                or int(row.get("native_network_capability_requeue_count") or 0) > 1
                or row.get("output_path") or row.get("candidate_output_path")):
            return False
        receipt_sha = str(row.get("native_network_terminal_receipt_sha256") or "")
        log_sha = str(row.get("native_network_terminal_original_log_sha256") or "")
        if not HEX64.fullmatch(receipt_sha) or not HEX64.fullmatch(log_sha):
            return False
        if list((ep / "media/raw").glob(f"{frame:02d}-*.png")):
            return False
        _, original_output = _log_and_queue(ep, row)
        if _hash(original_output) != log_sha:
            return False
        original_runner = _matched_receipt(original_output)
        if original_runner["receipt_sha256"] != receipt_sha:
            return False
        key = logical_asset_identity.frame_asset_key(ep, frame)
        state = authority.load_asset_state(ep, key) or {}
        first = authority.load_attempt(ep, key, 1) or {}
        second = authority.load_attempt(ep, key, 2) or {}
        if (int(state.get("attempts_consumed") or 0) != 1
                or state.get("active_attempt_index") is not None
                or int(state.get("fencing_counter") or 0) != 1
                or first.get("status") != "FAILED_AFTER_DISPATCH"
                or first.get("failure_class") != FAILURE_CLASS
                or first.get("provider") != "codex_subscription"
                or first.get("runner_request_id") != original_runner["request_id"]
                or first.get("generation_key") != authority.stable_generation_key(
                    authority._episode_id(ep), key, 1)
                or first.get("result_ref") or bool(second)):
            return False
        connection = authority._connect()
        try:
            dbrow = connection.query_one(
                "SELECT CONTEXT, STATUS, GENERATION_KEY, FENCING_TOKEN "
                "FROM TB_GENERATION_ATTEMPT WHERE EPISODE_ID=%s "
                "AND LOGICAL_ASSET_KEY=%s AND ATTEMPT_INDEX=1",
                (authority._episode_id(ep), key))
        finally:
            connection.close()
        if (not isinstance(dbrow, dict) or dbrow.get("STATUS") != "FAILED_AFTER_DISPATCH"
                or int(dbrow.get("FENCING_TOKEN") or 0) != 1
                or dbrow.get("GENERATION_KEY") != first.get("generation_key")):
            return False
        context = authority._context(dbrow)
        return bool(
            context.get("scope") == "batch"
            and context.get("queue_item_id") == row.get("id")
            and context.get("runner_request_id") == original_runner["request_id"]
            and context.get("network_failure_runner_receipt_sha256") == receipt_sha
            and context.get("network_failure_original_log_sha256") == log_sha
            and context.get("upstream_billing_outcome_unverified") is True
        )
    except Exception:
        return False


def requeue_capability_preflight(ep: Path, frame: int, *, acknowledged: bool = False) -> dict:
    """One-shot requeue after pre-dispatch UNKNOWN capability gate rejected Attempt #2.

    The non-generating secondary visibility probe is still checked freshly by
    the canonical worker. No MySQL Attempt is reserved or reset here.
    """
    if not acknowledged:
        return {"status": "BLOCKED", "reason": "ACK_REQUIRED"}
    ep = Path(ep).resolve()
    try:
        with scheduler_core.queue_transaction(ep):
            queue = scheduler_core.load_queue(ep)
            row = next((x for x in queue.get("items", [])
                        if x.get("scope") == "batch" and int(x.get("frame") or 0) == frame), None)
            if (row is None or row.get("status") != "blocked"
                    or row.get("technical_failure_code") != "LOGIN_AUTH_IMAGE_TOOL_CAPABILITY_UNKNOWN"
                    or not str(row.get("last_error") or "").startswith(
                        "LOGIN_AUTH_IMAGE_TOOL_CAPABILITY_UNKNOWN:")
                    or int(row.get("attempts") or 0) != 1
                    or int(row.get("native_network_capability_requeue_count") or 0) != 0
                    or not remaining_second_attempt(ep, row)):
                return {"status": "BLOCKED", "reason": "PROVENANCE_OR_ONE_SHOT_REARM_DENIED"}
            row["native_network_capability_requeue_count"] = 1
            row["native_network_preflight_error_before_requeue"] = row["last_error"]
            row["status"] = "queued"
            row["last_error"] = None
            row.pop("technical_failure_code", None)
            row.pop("external_block", None)
            row.pop("completed_at", None)
            row.pop("execution", None)
            scheduler_core.save_queue(ep, queue)
            return {"status": "PASS", "frame": frame, "provider_calls": 0,
                    "additional_attempts_consumed": 0, "remaining_real_attempt_budget": 1}
    except scheduler_core.QueueMutationBusy:
        return {"status": "BLOCKED", "reason": "QUEUE_MUTATION_BUSY"}


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("episode_dir", type=Path)
    ap.add_argument("--frame", type=int, choices=(5,10,15), required=True)
    ap.add_argument("--ack-duplicate-upstream-cost-risk", action="store_true")
    a=ap.parse_args()
    result=rearm_one(a.episode_dir,a.frame,acknowledged=a.ack_duplicate_upstream_cost_risk)
    print(json.dumps(result,ensure_ascii=False))
    return 0 if result["status"]=="PASS" else 2

if __name__=="__main__":
    raise SystemExit(main())