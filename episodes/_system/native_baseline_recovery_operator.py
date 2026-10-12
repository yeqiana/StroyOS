"""One-off native Frame01 recovery: plan, durable backup, gated commit.

Only execute touches production authority. The documented TEST_ONLY MySQL
approval NEVER authorizes execute. This module does not generate/review images.
"""
from __future__ import annotations

import base64
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import uuid

import episode_identity
import generation_attempt_authority as generation
import logical_asset_identity
import native_baseline_atomic_ledger as atomic_ledger
import native_baseline_readonly_preflight as preflight
import native_baseline_source_freeze as freeze
import native_baseline_unknown_cas as recovery
import scheduler_core

ROOT = Path(__file__).resolve().parents[2]
ARCHIVES = ROOT / ".storyos" / "native-frame01-recovery-archives"
PRODUCTION_APPROVAL_ENV = "STORYOS_NATIVE_FRAME01_PRODUCTION_APPROVAL"
PRODUCTION_APPROVAL_VALUE = "I_AUTHORIZE_OFFICIAL_FRAME01_ATTEMPT1_RECOVERY"

# Only these five tables, and only the exact Episode/Frame01 rows, may be read.
TABLES = (
    ("generation_asset", "TB_GENERATION_ASSET_STATE", "EPISODE_ID=%s AND LOGICAL_ASSET_KEY=%s"),
    ("generation_attempt", "TB_GENERATION_ATTEMPT", "EPISODE_ID=%s AND LOGICAL_ASSET_KEY=%s AND ATTEMPT_INDEX=1"),
    ("ledger", "TB_PRODUCTION_LEDGER_AUTHORITY", "EPISODE_ID=%s"),
    ("typed_frame", "TB_PRODUCTION_FRAME", "EPISODE_ID=%s AND FRAME_NO=1"),
    ("typed_attempt", "TB_PRODUCTION_ATTEMPT", "EPISODE_ID=%s AND FRAME_NO=1 AND ATTEMPT_NO=1"),
)


class NativeFrame01OperationDenied(RuntimeError):
    """Safety gate rejected the one-off recovery operation."""


def _deny(code: str) -> None:
    raise NativeFrame01OperationDenied(code)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _normalized(value):
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"binary_base64": base64.b64encode(bytes(value)).decode("ascii")}
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _normalized(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalized(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    _deny("NATIVE_FRAME01_SNAPSHOT_UNSUPPORTED_VALUE")


def _json_bytes(data) -> bytes:
    return (json.dumps(_normalized(data), ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def _episode(ep: Path) -> Path:
    ep = Path(ep).resolve()
    if ep != (ROOT / "episodes/00_独立篇/06_五十亩山地之后_全新重制").resolve():
        _deny("NATIVE_FRAME01_OFFICIAL_EPISODE_REQUIRED")
    return ep


def _authority(ep: Path) -> dict:
    """Read raw MySQL rows without locking or mutating the DB."""
    logical = logical_asset_identity.episode_id(ep)
    key = generation.frame_key(ep, 1)
    storage = episode_identity.storage_episode_id(ep)
    params = ((logical, key), (logical, key), (storage,), (storage,), (storage,))
    connection = generation._connect()
    try:
        rows = {}
        for (label, table, where), args in zip(TABLES, params):
            row = connection.query_one("SELECT * FROM " + table + " WHERE " + where, args)
            if not isinstance(row, dict):
                _deny("NATIVE_FRAME01_SNAPSHOT_MISSING_" + label.upper())
            rows[label] = _normalized(row)
        return rows
    finally:
        connection.close()


def capture(ep: Path) -> tuple[dict, dict[str, bytes]]:
    """Double-check all read-only authorities and capture six original files."""
    ep = _episode(ep)
    before = preflight.inspect(ep)
    _require_ready(before)
    proof = recovery.verify_frame01_sources(ep)
    paths = freeze.source_paths(proof)
    identities = {key: proof[key].resolve() for key in freeze.SOURCE_KEYS}
    if set(paths) != set(identities.values()):
        _deny("NATIVE_FRAME01_SOURCE_IDENTITY_DRIFT")
    rows = _authority(ep)
    queue = _normalized(scheduler_core.load_queue(ep))
    files = {}
    for key, path in identities.items():
        payload = path.read_bytes()
        if not payload:
            _deny("NATIVE_FRAME01_SOURCE_EMPTY")
        files["sources/" + key + ".bin"] = payload
    after = preflight.inspect(ep)
    if before != after or rows != _authority(ep) or queue != _normalized(scheduler_core.load_queue(ep)):
        _deny("NATIVE_FRAME01_SNAPSHOT_AUTHORITY_MOVED")
    if {key: _digest(value) for key, value in files.items()} != {
        "sources/" + key + ".bin": _digest(path.read_bytes())
        for key, path in identities.items()
    }:
        _deny("NATIVE_FRAME01_SNAPSHOT_SOURCE_MOVED")
    record = {
        "schema_version": 1,
        "purpose": "OFFICIAL_FRAME01_EXISTING_ATTEMPT_BACKUP_ONLY",
        "episode": ep.relative_to(ROOT).as_posix(),
        "fencing_token": before["fencing_token"],
        "evidence_sha256": before["source_evidence_sha256"],
        "candidate_sha256": before["candidate_sha256"],
        "authority_rows": rows,
        "queue": queue,
        "source_paths": {key: str(path) for key, path in identities.items()},
    }
    files["state.json"] = _json_bytes(record)
    return before, files


def _require_ready(result: dict) -> None:
    if (result.get("status") != "READ_ONLY_EVIDENCE_READY_TEST_DB_STILL_REQUIRED"
            or result.get("authorized_to_mutate_production") is not False
            or result.get("sql_writes") != 0
            or result.get("model_calls") != 0
            or result.get("generation_attempt_status") != "OUTCOME_UNKNOWN"
            or result.get("generation_attempts_consumed") != 1
            or not isinstance(result.get("fencing_token"), int)):
        _deny("NATIVE_FRAME01_PREFLIGHT_NOT_READY")


def plan(ep: Path) -> dict:
    result = preflight.inspect(_episode(ep))
    _require_ready(result)
    return {
        "status": "PLAN_ONLY_PRODUCTION_WRITE_NOT_AUTHORIZED",
        "evidence_sha256": result["source_evidence_sha256"],
        "fencing_token": result["fencing_token"],
        "backup_required": True,
        "authorized_to_mutate_production": False,
        "sql_writes": 0,
        "model_calls": 0,
    }


def backup(ep: Path) -> dict:
    result, files = capture(ep)
    if (ARCHIVES.is_symlink() or ARCHIVES.parent.is_symlink()
            or not ARCHIVES.resolve().is_relative_to(ROOT.resolve())):
        _deny("NATIVE_FRAME01_BACKUP_ROOT_OUTSIDE_REPOSITORY")
    ARCHIVES.mkdir(parents=True, exist_ok=True)
    name = "frame01-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex
    staging = Path(tempfile.mkdtemp(prefix=".partial-", dir=ARCHIVES))
    finished = ARCHIVES / name
    try:
        for relative, data in files.items():
            output = staging / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        manifest = {
            "schema_version": 1,
            "status": "SEALED_READ_ONLY_BACKUP_NOT_PRODUCTION_AUTHORIZATION",
            "evidence_sha256": result["source_evidence_sha256"],
            "fencing_token": result["fencing_token"],
            "files": {k: _digest(v) for k, v in sorted(files.items())},
        }
        manifest_bytes = _json_bytes(manifest)
        with (staging / "manifest.json").open("xb") as handle:
            handle.write(manifest_bytes)
            handle.flush()
            os.fsync(handle.fileno())
        staging.rename(finished)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return {
        "status": manifest["status"],
        "archive": str(finished),
        "manifest_sha256": _digest(manifest_bytes),
        "evidence_sha256": result["source_evidence_sha256"],
        "fencing_token": result["fencing_token"],
        "authorized_to_mutate_production": False,
        "sql_writes": 0,
        "model_calls": 0,
    }


def _committed_sql_pending_queue_resume(
        ep: Path, manifest: dict, fence: int, evidence: str) -> None:
    """Proof-bound reentry after SQL COMMIT but before Queue persistence.

    Original authority backup necessarily differs after an atomic SQL commit.
    Do not allow arbitrary drift: require the same six source bytes, original
    Generation Key and Fencing, plus a completed SHA-bound Ledger. The canonical
    MySQL transaction rechecks its typed projections before fixing the Queue.
    """
    import production_ledger_persistence as ledger_store

    proof = recovery.verify_frame01_sources(ep, allow_generated=True)
    if proof["evidence_sha256"] != evidence:
        _deny("NATIVE_FRAME01_RESUME_EVIDENCE_CHANGED")
    for key in freeze.SOURCE_KEYS:
        path = proof.get(key)
        if (not isinstance(path, Path) or not path.is_file()
                or _digest(path.read_bytes())
                != manifest["files"]["sources/" + key + ".bin"]):
            _deny("NATIVE_FRAME01_RESUME_SOURCE_CHANGED")
    key = generation.frame_key(ep, 1)
    state = generation.load_asset_state(ep, key)
    row = generation.load_attempt(ep, key, 1)
    if (not isinstance(row, dict)
            or row.get("status") != "SUCCEEDED"
            or row.get("generation_key") != proof["generation_key"]
            or row.get("result_ref") != str(proof["candidate"])
            or state.get("attempts_consumed") != 1
            or state.get("active_attempt_index") is not None
            or state.get("fencing_counter") != fence):
        _deny("NATIVE_FRAME01_RESUME_GENERATION_AUTHORITY_DRIFT")
    ledger = ledger_store.load_authority(ep)
    if not isinstance(ledger, dict):
        _deny("NATIVE_FRAME01_RESUME_LEDGER_MISSING")
    atomic_ledger._check_existing(ledger, proof, completed=True)


def _verified_archive(ep: Path, manifest_file: Path, digest: str, fence: int, evidence: str) -> None:
    original_manifest = Path(manifest_file)
    if (original_manifest.is_symlink() or original_manifest.parent.is_symlink()):
        _deny("NATIVE_FRAME01_BACKUP_SYMLINK")
    manifest_file = original_manifest.resolve()
    if (manifest_file.name != "manifest.json"
            or not manifest_file.is_relative_to(ARCHIVES.resolve())
            or manifest_file.parent.is_symlink()):
        _deny("NATIVE_FRAME01_BACKUP_OUTSIDE_LOCAL_ARCHIVE")
    if _digest(manifest_file.read_bytes()) != digest:
        _deny("NATIVE_FRAME01_BACKUP_MANIFEST_CHANGED")
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    if (manifest.get("schema_version") != 1
            or manifest.get("status") != "SEALED_READ_ONLY_BACKUP_NOT_PRODUCTION_AUTHORIZATION"
            or manifest.get("fencing_token") != fence
            or manifest.get("evidence_sha256") != evidence
            or set(manifest.get("files") or {}) != {"state.json"} | {
                "sources/" + key + ".bin" for key in freeze.SOURCE_KEYS
            }):
        _deny("NATIVE_FRAME01_BACKUP_CONTRACT_CHANGED")
    for name, sha in manifest["files"].items():
        source = manifest_file.parent / name
        if not source.is_file() or source.is_symlink() or _digest(source.read_bytes()) != sha:
            _deny("NATIVE_FRAME01_BACKUP_CONTENT_CHANGED")
    # Before SQL COMMIT, every row must exactly match the original snapshot.
    # After an interrupted COMMIT, the BLOB/typed/Generation Attempt has
    # legitimately changed; recover ONLY that one proven transition, never
    # accept arbitrary mismatches or make another image Attempt.
    try:
        current, files = capture(ep)
    except (preflight.NativeFrame01PreflightDenied,
            recovery.NativeReconciliationDenied,
            atomic_ledger.LedgerRecoveryDenied,
            NativeFrame01OperationDenied):
        _committed_sql_pending_queue_resume(ep, manifest, fence, evidence)
        return
    if current["fencing_token"] != fence or current["source_evidence_sha256"] != evidence:
        _deny("NATIVE_FRAME01_LIVE_AUTHORITY_MOVED")
    if {name: _digest(data) for name, data in files.items()} != manifest["files"]:
        _deny("NATIVE_FRAME01_LIVE_AUTHORITY_MOVED")


def execute(ep: Path, *, fencing_token: int, evidence_sha256: str,
            manifest: Path, manifest_sha256: str, approval_ticket: str,
            production_approval: str | None = None) -> dict:
    """Never called without distinct explicit production mutation consent."""
    # The user's TEST_ONLY MySQL approval cannot authorize production writes.
    if (production_approval != PRODUCTION_APPROVAL_VALUE
            or not approval_ticket.startswith("FRAME01-")
            or len(approval_ticket) < 16):
        _deny("NATIVE_FRAME01_SEPARATE_PRODUCTION_APPROVAL_REQUIRED")
    if not (isinstance(fencing_token, int) and fencing_token >= 1
            and len(evidence_sha256) == 64
            and len(manifest_sha256) == 64):
        _deny("NATIVE_FRAME01_OPERATOR_FENCE_OR_SHA_MISSING")
    ep = _episode(ep)
    _verified_archive(ep, manifest, manifest_sha256, fencing_token, evidence_sha256)
    # This canonical function holds the OS queue Owner lock, locks Generation
    # Attempt + Ledger/typed projections in one SQL transaction and ensures
    # all six provenance files stay frozen across COMMIT/ROLLBACK on Windows.
    outcome = recovery.reconcile_frame01_and_queue(
        ep, expected_fencing_token=fencing_token,
        expected_evidence_sha256=evidence_sha256,
    )
    return {
        "status": "FRAME01_RECONCILED_PENDING_INDEPENDENT_VISUAL_REVIEW",
        "queue_reconciled": outcome.get("queue_reconciled") is True,
        "visual_review_pass": False,
        "new_generation_attempts": 0,
        "model_calls": 0,
    }
