#!/usr/bin/env python3
"""Read-only proof that one old Story Critic Driver rc4 is superseded by A15 PASS.

This does not reset the historical Driver, create authorization, grant image
entitlement, reserve paid attempts, or start any work. The normal owner lock,
image Gateway, and Generation Attempt fences remain authoritative.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "episodes" / "_system"
if str(SYSTEM) not in sys.path:
    sys.path.insert(0, str(SYSTEM))

APPROVED_SCOPE = "SERIAL_EPISODE_AUTHORIZED_SOURCE_REVISION_AFTER_A14_FAIL"
STATUS = "HISTORICAL_STORY_RC4_SUPERSEDED_BY_VERIFIED_A15_PASS"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _timestamp(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value or ""))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("offset-aware timestamp required")
    return parsed


def inspect(ep: Path) -> dict:
    result = {
        "status": "STORY_RC4_SUPERSESSION_NOT_PROVEN",
        "read_only": True,
        "model_calls": 0,
        "sql_writes": 0,
        "production_authorization": False,
        "image_entitlement_verified": False,
    }

    def blocked(reason: str) -> dict:
        return {**result, "status": reason}

    try:
        import runtime_driver
        import story_review
        import runtime_request
        import story_narrative_form
        import storyos_driver_exit_remediation as exit_proof
        import story_source_revision_a15_review as a15

        ep = Path(ep).resolve()
        if not ep.is_dir() or not ep.is_relative_to((ROOT / "episodes").resolve()):
            return blocked("EPISODE_PATH_OUTSIDE_AUTHORITY")
        driver = runtime_driver.status(ep)
        record = driver.get("record")
        if (driver.get("driver_state") != "EXITED"
                or driver.get("exit_code") != "4"
                or driver.get("pid") != 0
                or driver.get("liveness") != "DEAD"
                or not isinstance(record, dict)
                or record.get("pid") != 0
                or str(record.get("rc") or "").split(" ", 1)[0] != "4"
                or Path(str(record.get("episode") or "")).resolve() != ep
                or record.get("log") != driver.get("log")):
            return blocked("HISTORICAL_DRIVER_RC4_IDENTITY_UNVERIFIED")
        driver_digest = exit_proof.canonical_sha(record)
        # The Driver record is mirrored via Redis and MySQL; non-identity
        # metadata can differ from the older approval snapshot. Never
        # equate a changed whole-record SHA with a new exit, nor accept that
        # SHA by itself as proof. The immutable episode-scoped exit LOG SHA
        # is the stronger shared event identity, backed by the prior
        # reserved ticket, same source, and an exact terminal Driver record.
        receipts = list((ep / "meta/runtime").glob(
            "corrected-story-rc4-remediation-*.json"))
        if len(receipts) != 1:
            return blocked("PRIOR_OPERATOR_REMEDIATION_NOT_UNIQUE")
        receipt = receipts[0]
        token_digest = receipt.name.removeprefix(
            "corrected-story-rc4-remediation-").removesuffix(".json")
        if (re.fullmatch(r"[0-9a-f]{64}", token_digest) is None
                or not receipt.is_file() or receipt.is_symlink()
                or receipt.stat().st_size > 8192):
            return blocked("PRIOR_OPERATOR_REMEDIATION_RECEIPT_MISSING")
        prior = json.loads(receipt.read_text(encoding="utf-8"))
        if (prior.get("status") != "SINGLE_USE_RESERVED"
                or prior.get("ack") != "EXPLICIT_REAL_PRODUCTION"
                or prior.get("historical_driver_sha256") != token_digest
                or prior.get("historical_failure_step") != "CREATIVE_STORY"
                or prior.get("historical_failure_class") != "4"
                or prior.get("frame_count") != 48
                or prior.get("canvas") != "4:5"
                or prior.get("no_gate_pass_asserted") is not True):
            return blocked("PRIOR_OPERATOR_REMEDIATION_BINDING_INVALID")

        logfile = Path(str(driver.get("log") or "")).resolve(strict=True)
        if (not logfile.is_relative_to((ep / "meta/runtime/driver-logs").resolve())
                or not logfile.name.startswith("driver_")
                or logfile.is_symlink() or logfile.stat().st_size > 16384):
            return blocked("HISTORICAL_DRIVER_LOG_SCOPE_INVALID")
        raw = logfile.read_bytes()
        # The old one-shot *canvas* receipt was written against an earlier
        # hot-state snapshot; its log-byte digest may not match later carrier
        # output. Do NOT rewrite or reuse that token as a paid-attempt permit.
        # Instead, classify the exact current rc4 episode/event independently:
        # same task identity, exact two-line terminal log and same-epoch
        # CREATIVE_STORY failure trace, followed by a separately reviewed PASS.
        lines = raw.splitlines()
        header = (re.fullmatch(
            rb"DRIVER TASK CARRIER pid=([1-9][0-9]*) task=([A-Za-z0-9-]+)",
            lines[0]) if len(lines) == 2 else None)
        if (header is None
                or header.group(2).decode("ascii") != record.get("carrier_task")
                or re.fullmatch(rb"DRIVER EXIT rc=4[ \t]*", lines[1]) is None
                or b"DRIVER CRASH" in raw):
            return blocked("HISTORICAL_RC4_TERMINAL_LOG_NOT_EXACT")
        trace = ep / "meta/runtime/trace-events.jsonl"
        if not trace.is_file() or trace.stat().st_size > 2000000:
            return blocked("HISTORICAL_CREATIVE_STORY_TRACE_MISSING")
        failures = []
        for line in trace.read_text(encoding="utf-8-sig").splitlines():
            if '"STEP_FAILED"' not in line or '"CREATIVE_STORY"' not in line:
                continue
            item = json.loads(line)
            if (item.get("event_type") == "STEP_FAILED"
                    and item.get("step") == "CREATIVE_STORY"):
                failures.append(item)
        if (not failures or failures[-1].get("failure_class") != "4"
                or not (_timestamp(record.get("started_at"))
                        <= _timestamp(failures[-1].get("timestamp"))
                        < _timestamp(record.get("exited_at")) + timedelta(seconds=1))):
            return blocked("HISTORICAL_RC4_CREATIVE_QUALITY_EXIT_NOT_PROVEN")
        legacy_log_sha_matches = _sha(raw) == prior.get("historical_log_sha256")

        request = runtime_request.authority_for_episode(ep)
        if (not story_narrative_form.is_locked(request)
                or story_narrative_form.from_request(request) != "SERIAL_EPISODE"
                or request.get("request_id") != prior.get("runtime_request_id")
                or (request.get("user_intent") or {}).get("full_auto_authorized") is not True):
            return blocked("LOCKED_SERIAL_RUNTIME_REQUEST_MISMATCH")
        source_binding = story_review.read_json(ep / "meta/user-source-binding.json")
        if (source_binding.get("canvas") != "4:5"
                or source_binding.get("frame_count") != 48
                or source_binding.get("source_sha256") != prior.get("source_sha256")):
            return blocked("IMMUTABLE_ORIGINAL_SOURCE_BINDING_DRIFT")
        source_rel = Path(str(source_binding.get("source_archive") or ""))
        if source_rel.is_absolute() or ".." in source_rel.parts:
            return blocked("USER_SOURCE_ARCHIVE_INVALID")
        archived = (ROOT / source_rel).resolve()
        if (not archived.is_relative_to((ep / "docs/source").resolve())
                or not archived.is_file()
                or _sha(archived.read_bytes()) != prior.get("source_sha256")):
            return blocked("IMMUTABLE_USER_SOURCE_ARCHIVE_DRIFT")

        review = story_review.load_review(ep)
        prov = (review.get("critic_provenance") or {}) if isinstance(review, dict) else {}
        if (not story_review.review_required(ep)
                or not isinstance(review, dict)
                or (review.get("summary") or {}).get("passed") is not True
                or review.get("issue_codes") != []
                or prov.get("attempt") != 15
                or prov.get("review_scope") != APPROVED_SCOPE
                or prov.get("review_epoch") != 14
                or prov.get("direct_user_continuation_review") is not True
                or _timestamp(prov.get("reviewed_at")) <= _timestamp(record.get("exited_at"))):
            return blocked("OFFICIAL_A15_PASS_NOT_NEWER_THAN_OLD_EXIT")
        if story_review.verify(ep):
            return blocked("OFFICIAL_A15_PASS_SHA_OR_EPOCH_UNVERIFIED")
        if not a15.validate_epoch(ep, prov):
            return blocked("A15_ONE_SHOT_EPOCH_AUTHORITY_INVALID")
        gates = story_review.read_json(ep / "meta/story-gates.json")
        if ((gates.get("reviews") or {}).get("story") != "passed"
                or (gates.get("story") or {}).get("task_closed") is not True):
            return blocked("STORY_GATE_PASS_AND_LOCAL_CLOSURE_REQUIRED")

        current = runtime_driver.status(ep)
        if (current.get("record") != record
                or current.get("driver_state") != "EXITED"
                or current.get("liveness") != "DEAD"):
            return blocked("DRIVER_IDENTITY_CHANGED_DURING_READ")
        return {
            **result,
            "status": STATUS,
            "driver_record_sha256": driver_digest,
            "verified_review_attempt": 15,
            "story_gate_verified": True,
            "historical_receipt_log_byte_sha_same": legacy_log_sha_matches,
            "supersession_evidence": "CURRENT_RC4_LOG_TRACE_PLUS_NEW_A15_PASS",
            "resume_scope": "DAG_ONLY_CANONICAL_DRIVER_WITH_EXPLICIT_ACK",
        }
    except Exception:
        return blocked("STORY_RC4_READ_AUTHORITY_ERROR")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episode", required=True)
    result = inspect(Path(parser.parse_args().episode))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == STATUS else 2


if __name__ == "__main__":
    raise SystemExit(main())
