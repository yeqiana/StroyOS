"""Strict read-only preflight for the one official native Frame01 recovery.

No SELECT FOR UPDATE, transaction, queue write, native Codex model call,
new image Attempt or mutation of any Production Ledger authority.
The result is evidence readiness, NEVER production execution authorization.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import generation_attempt_authority as attempt_authority
import native_baseline_atomic_ledger as ledger_correction
import native_baseline_unknown_cas as cas
import production_ledger_persistence as ledger_store
from episode_identity import storage_episode_id
from platform.repository.mysql.mysql_production_attempt_repository import (
    MySqlProductionAttemptRepository,
)
from platform.repository.mysql.mysql_production_frame_repository import (
    MySqlProductionFrameRepository,
)


class NativeFrame01PreflightDenied(RuntimeError):
    pass


def _require(ok: bool, code: str) -> None:
    if not ok:
        raise NativeFrame01PreflightDenied(code)


def inspect(ep: Path) -> dict:
    """Compare all three original authorities without modifying any of them."""
    ep = Path(ep).resolve()
    proof = cas.verify_frame01_sources(ep)
    ledger = ledger_store.load_authority(ep)
    _require(isinstance(ledger, dict), "NATIVE_PREFLIGHT_LEDGER_MISSING")
    ledger_correction.corrected_ledger_document(ledger, proof)

    key = attempt_authority.frame_key(ep, 1)
    state = attempt_authority.load_asset_state(ep, key)
    attempt = attempt_authority.load_attempt(ep, key, 1)
    _require(bool(attempt), "NATIVE_PREFLIGHT_GENERATION_ATTEMPT_MISSING")
    _require(
        state["attempts_consumed"] == 1
        and state["active_attempt_index"] is None
        and state["fencing_counter"] >= 1
        and attempt.get("status") == "OUTCOME_UNKNOWN"
        and attempt.get("generation_key") == proof["generation_key"]
        and attempt.get("failure_class") == cas.EXPECTED_REASON
        and attempt.get("result_ref") in (None, "")
        and attempt.get("dispatch_committed_at") is not None,
        "NATIVE_PREFLIGHT_GENERATION_AUTHORITY_DRIFT",
    )

    storage_id = storage_episode_id(ep)
    frame = ledger["frames"]["01"]
    original = frame["attempts"][0]
    connection = attempt_authority._connect()
    try:
        # Inspect the original Generation Attempt context too: the normalized
        # load_attempt summary alone does not expose its fencing/model binding.
        original_row = connection.query_one(
            "SELECT * FROM TB_GENERATION_ATTEMPT "
            "WHERE EPISODE_ID=%s AND LOGICAL_ASSET_KEY=%s AND ATTEMPT_INDEX=1",
            (state["episode_id"], key),
        )
        _require(isinstance(original_row, dict),
                 "NATIVE_PREFLIGHT_GENERATION_ATTEMPT_ROW_MISSING")
        context = attempt_authority._context(original_row)
        _require(
            int(original_row.get("FENCING_TOKEN") or 0) == state["fencing_counter"]
            and original_row.get("GENERATION_KEY") == proof["generation_key"]
            and original_row.get("STATUS") == "OUTCOME_UNKNOWN"
            and original_row.get("FAILURE_CLASS") == cas.EXPECTED_REASON
            and original_row.get("RESULT_REF") in (None, "")
            and original_row.get("DISPATCH_COMMITTED_AT") is not None
            and original_row.get("CONTROLLER_MODEL") == "gpt-6-luna"
            and original_row.get("PAYLOAD_MODEL") == "gpt-image-2.5-flare"
            and original_row.get("PAYLOAD_QUALITY") == "high"
            and original_row.get("PROVIDER") == "codex_subscription"
            and context.get("scope") == "visual_lock"
            and context.get("visual_lock_frame") == 1
            and context.get("queue_item_id") == proof["queue_item_id"]
            and context.get("tool_capability_claim") == "UNKNOWN_NOT_YET_PROVEN"
            and context.get("frame_contract_sha256") == proof["frame_contract_sha256"]
            and context.get("prompt_package_sha256") == proof["prompt_package_sha256"]
            and context.get("controller_effort") == "high"
            and context.get("model_policy_sha256")
            == original_row.get("MODEL_POLICY_SHA256"),
            "NATIVE_PREFLIGHT_GENERATION_FENCE_OR_CONTEXT_DRIFT",
        )
        # Typed repository getters are ordinary non-locking SELECT statements.
        typed_frame = MySqlProductionFrameRepository(connection).get(storage_id, 1)
        typed_attempts = MySqlProductionAttemptRepository(connection).list_frame(storage_id, 1)
    finally:
        connection.close()
    _require(
        isinstance(typed_frame, dict)
        and len(typed_attempts) == 1
        and typed_frame["status"] == frame["status"]
        and typed_frame["current_attempt_id"] == original["attempt_id"]
        and typed_frame["contract_sha256"] == ledger_store._contract_sha(frame)
        and typed_frame["approved_artifact_id"] is None,
        "NATIVE_PREFLIGHT_TYPED_FRAME_DRIFT",
    )
    typed_attempt = typed_attempts[0]
    _require(
        typed_attempt["attempt_id"] == original["attempt_id"]
        and typed_attempt["episode_id"] == storage_id
        and typed_attempt["frame_no"] == 1
        and typed_attempt["attempt_no"] == 1
        and typed_attempt["attempt_kind"] == original["kind"]
        and typed_attempt["status"] == original["result"]
        and typed_attempt["payload"] == original,
        "NATIVE_PREFLIGHT_TYPED_ATTEMPT_DRIFT",
    )

    return {
        "status": "READ_ONLY_EVIDENCE_READY_TEST_DB_STILL_REQUIRED",
        "episode": ep.as_posix(),
        "frame": 1,
        "generation_attempt_status": attempt["status"],
        "generation_attempts_consumed": state["attempts_consumed"],
        "fencing_token": state["fencing_counter"],
        "ledger_frame_status": frame["status"],
        "typed_frame_status": typed_frame["status"],
        "source_evidence_sha256": proof["evidence_sha256"],
        "candidate_sha256": proof["candidate_sha256"],
        "source_model_attested": False,
        "pixel_review_pass": False,
        "real_mysql_integration_tests_passed": False,
        "authorized_to_mutate_production": False,
        "model_calls": 0,
        "sql_writes": 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("episode_dir")
    args = parser.parse_args(argv)
    try:
        result = inspect(Path(args.episode_dir))
    except Exception as exc:
        # Do not render connection errors / DSNs or Python tracebacks to an
        # operator-facing command; known typed denials contain safe codes.
        known = (NativeFrame01PreflightDenied,
                 cas.NativeReconciliationDenied,
                 ledger_correction.LedgerRecoveryDenied)
        reason = (str(exc) if isinstance(exc, known)
                  else "NATIVE_PREFLIGHT_READ_ONLY_EVIDENCE_UNAVAILABLE")
        print(json.dumps({
            "status": "BLOCKED",
            "reason": reason,
            "authorized_to_mutate_production": False,
            "sql_writes": 0,
            "model_calls": 0,
        }, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
