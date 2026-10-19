#!/usr/bin/env python3
"""One-shot audited remediation of a *specific* fixed nonzero Driver crash.

Ordinary start/watchdog keep rejecting nonzero exits. This explicit exceptional
flow is allowed only with exact prior exit, log and CI-reviewed fix bytes.
It never changes the old Driver record or the image Generation Attempt ledger.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re


class RemediationDenied(Exception):
    pass


APPROVED_FIXED_BLOB = "a9e66908c5fb92e43908a42a0c4d60e74535fe90"
KNOWN_CRASH = "DRIVER CRASH RuntimeError('final semantic source bindings changed before commit')"
REQUIRED_FIXED_MARKERS = (
    'if review_scope == "FULL_FRAME_SET" and review_item is None:',
    'provenance["review_source_bindings"] = review_source_bindings(ep, current)',
)
# A second, separately reviewed cause is permitted only when its own fixed
# source file blob matches exactly. There is no generic "rc 900" override.
APPROVED_REPAIR_WAVE_BLOB = "afbb49c80cf512312c9a0dd3043ee87e29bdea5a"
KNOWN_REPAIR_WAVE_CRASH = """DRIVER CRASH TypeError("materialize_wave() got an unexpected keyword argument 'evidence'")"""
REQUIRED_REPAIR_WAVE_MARKERS = (
    'repair_aggregator.materialize_wave(ep,attempt=attempt,findings=evidence)',
)
REMEDIATION_KINDS = frozenset({"source_binding", "repair_wave_signature"})

HISTORICAL_EXIT_BLOCKERS = frozenset({
    "EPISODE_DRIVER_OWNER_NOT_IDLE_OR_UNVERIFIED",
    "EPISODE_DRIVER_EXIT_REQUIRES_REMEDIATION",
})


def canonical_sha(data: dict) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


def git_blob_sha(content: bytes) -> str:
    return hashlib.sha1(f"blob {len(content)}\0".encode("ascii") + content).hexdigest()


def only_historical_exit_blockers(blockers: list[str]) -> bool:
    return set(blockers) == HISTORICAL_EXIT_BLOCKERS and len(blockers) == 2


def verify_exit(ep: Path, driver: dict, *, source: Path, expected: dict[str, str], kind: str = "source_binding") -> dict:
    """Check immutable exact pointers; returning proof itself writes nothing."""
    if kind not in REMEDIATION_KINDS:
        raise RemediationDenied("UNKNOWN_REMEDIATION_KIND")
    ep = ep.resolve()
    if (not isinstance(driver, dict) or driver.get("driver_state") != "EXITED"
            or driver.get("pid") != 0 or driver.get("liveness") != "DEAD"
            or str(driver.get("exit_code") or "").split(" ", 1)[0] != "900"):
        raise RemediationDenied("DRIVER_EXIT_NOT_PROVEN_DEAD_900")
    record = driver.get("record")
    if (not isinstance(record, dict) or record.get("pid") != 0
            or str(record.get("rc") or "").split(" ", 1)[0] != "900"
            or Path(str(record.get("episode") or "")).resolve() != ep):
        raise RemediationDenied("DRIVER_EXIT_RECORD_MISMATCH")
    if not all(isinstance(expected.get(k), str) and
               re.fullmatch(r"[0-9a-f]{64}", expected[k])
               for k in ("driver_sha256", "log_sha256", "fix_sha256")):
        raise RemediationDenied("REMEDIATION_SHA_ARGUMENT_INVALID")
    digest = canonical_sha(record)
    if digest != expected["driver_sha256"]:
        raise RemediationDenied("DRIVER_EXIT_IDENTITY_CHANGED")
    try:
        log = Path(str(driver.get("log") or "")).resolve(strict=True)
        base = (ep / "meta/runtime/driver-logs").resolve()
        if (not log.is_relative_to(base) or not log.name.startswith("driver_")
                or record.get("log") != driver.get("log")):
            raise RemediationDenied("DRIVER_CRASH_LOG_SCOPE_INVALID")
        raw_log = log.read_bytes()
        raw_fix = source.resolve(strict=True).read_bytes()
    except (OSError, ValueError):
        raise RemediationDenied("REMEDIATION_EVIDENCE_MISSING") from None
    if hashlib.sha256(raw_log).hexdigest() != expected["log_sha256"]:
        raise RemediationDenied("DRIVER_CRASH_LOG_CHANGED")
    known_crash = (KNOWN_REPAIR_WAVE_CRASH if kind == "repair_wave_signature"
                   else KNOWN_CRASH)
    approved_blob = (APPROVED_REPAIR_WAVE_BLOB if kind == "repair_wave_signature"
                     else APPROVED_FIXED_BLOB)
    required_markers = (REQUIRED_REPAIR_WAVE_MARKERS if kind == "repair_wave_signature"
                        else REQUIRED_FIXED_MARKERS)
    if known_crash.encode("utf-8") not in raw_log:
        raise RemediationDenied("UNRELATED_DRIVER_CRASH_NOT_REMEDIATED")
    if hashlib.sha256(raw_fix).hexdigest() != expected["fix_sha256"]:
        raise RemediationDenied("DEPLOYED_FIX_SHA_CHANGED")
    if git_blob_sha(raw_fix) != approved_blob:
        raise RemediationDenied("DEPLOYED_FIX_NOT_CI_REVIEWED")
    fixed_text = raw_fix.decode("utf-8")
    if not all(marker in fixed_text for marker in required_markers):
        raise RemediationDenied("DEPLOYED_FIX_INCOMPLETE")
    return {
        "schema_version": 1, "episode": str(ep), "exit_code": "900",
        "driver_sha256": digest, "log_sha256": expected["log_sha256"],
        "fix_sha256": expected["fix_sha256"],
        "approved_git_blob": approved_blob, "remediation_kind": kind,
    }


def reserve_once(ep: Path, proof: dict) -> Path:
    """O_EXCL file is the atomic per-exit single-use audit reservation.

    This is not a privileged approval token; it merely prevents repeating the
    explicitly authorized remediation for the same prior exit event.
    """
    if (proof.get("schema_version") != 1 or proof.get("episode") != str(ep.resolve())
            or proof.get("exit_code") != "900"
            or not re.fullmatch(r"[0-9a-f]{64}", str(proof.get("driver_sha256") or ""))):
        raise RemediationDenied("INVALID_REMEDIATION_PROOF")
    path = ep / "meta/runtime" / f"driver-remediation-{proof['driver_sha256']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    receipt = {**proof, "status": "REMEDIATION_DISPATCH_RESERVED",
               "actor": "EXPLICIT_REAL_PRODUCTION_ACK",
               "relaunch_policy": "SINGLE_USE_CURRENT_EXIT_ONLY"}
    try:
        with path.open("x", encoding="utf-8") as f:
            json.dump(receipt, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
    except FileExistsError:
        raise RemediationDenied("NONZERO_EXIT_ALREADY_REMEDIATION_RESERVED") from None
    return path