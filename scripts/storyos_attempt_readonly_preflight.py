#!/usr/bin/env python3
"""Read-only Episode Generation Attempt triage.

This command never reserves/releases an Attempt, changes a lease, or dispatches
images. Use the authenticated production-env wrapper; do not substitute a
JSON/fixture projection for MySQL Authority.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "episodes" / "_system"
if str(SYSTEM) not in sys.path:
    sys.path.insert(0, str(SYSTEM))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from platform.repository.mysql.schema_v2 import DATABASE_NAME


def canonical_episode(raw: str, *, root: Path = ROOT) -> tuple[Path, str]:
    root = Path(root).resolve()
    folder = Path(raw)
    episode = (folder if folder.is_absolute() else root / folder).resolve()
    allowed = root / "episodes"
    if not episode.is_dir() or not episode.is_relative_to(allowed):
        raise ValueError("ATTEMPT_READONLY_EPISODE_PATH_INVALID")
    return episode, episode.relative_to(allowed).as_posix()


def _history_integrity_issues(episode_id: str, attempts: list[dict],
                              asset_states: list[dict]) -> list[dict[str, str]]:
    """Check immutable Attempt/asset identities without modifying the Authority.

    Never echo out-of-scope keys: an unexpected MySQL row must not leak
    another Episode's asset identity into this Episode's operator receipt.
    This is diagnostic-only; even a clean result does NOT authorize dispatch.
    """
    findings: set[tuple[str, str]] = set()
    expected_prefix = episode_id + "/"
    seen_attempts: set[tuple[str, int]] = set()
    seen_states: set[str] = set()
    committed_indices: dict[str, int] = {}

    def key_of(row: dict) -> str:
        key = str(row.get("LOGICAL_ASSET_KEY") or "")
        if not key.startswith(expected_prefix) or len(key) <= len(expected_prefix):
            findings.add(("OUT_OF_SCOPE", "ASSET_EPISODE_IDENTITY_MISMATCH"))
            return ""
        return key

    def hard_cap(key: str) -> int:
        # MySQL CHECK and Generation Attempt Authority permit one provenance-
        # fenced compensatory frame; all other assets stay at two calls.
        if (episode_id == "00_独立篇/13_失物归还的那扇门"
                and key == episode_id + "/frame-01"):
            return 3
        return 2

    def index_of(raw, key: str, code: str) -> int | None:
        # MySQL BIGINT/INT columns arrive as ints; accept plain digit strings
        # from protocol adapters, but never floats, booleans or signed values.
        if isinstance(raw, bool) or (
            not isinstance(raw, int)
            and not (isinstance(raw, str) and raw.isdecimal())
        ):
            findings.add((key, code))
            return None
        value = int(raw)
        if not 1 <= value <= hard_cap(key):
            findings.add((key, code))
            return None
        return value

    for row in attempts:
        key = key_of(row)
        if not key:
            continue
        index = index_of(row.get("ATTEMPT_INDEX"), key, "ATTEMPT_INDEX_OUT_OF_RANGE")
        if index is not None:
            identity = (key, index)
            if identity in seen_attempts:
                findings.add((key, "DUPLICATE_ATTEMPT_INDEX"))
            seen_attempts.add(identity)
            if str(row.get("STATUS") or "") in {
                "DISPATCH_COMMITTED", "SUCCEEDED", "FAILED_AFTER_DISPATCH", "OUTCOME_UNKNOWN"
            }:
                committed_indices[key] = max(index, committed_indices.get(key, 0))

    for row in asset_states:
        key = key_of(row)
        if not key:
            continue
        if key in seen_states:
            findings.add((key, "DUPLICATE_ASSET_STATE"))
        seen_states.add(key)
        raw_consumed = row.get("ATTEMPTS_CONSUMED")
        if isinstance(raw_consumed, bool) or (
            not isinstance(raw_consumed, int)
            and not (isinstance(raw_consumed, str) and raw_consumed.isdecimal())
        ) or not 0 <= int(raw_consumed) <= hard_cap(key):
            findings.add((key, "ATTEMPT_BUDGET_OUT_OF_RANGE"))
        elif int(raw_consumed) < committed_indices.get(key, 0):
            # A paid/committed image dispatch must have consumed its shared
            # Attempt budget before the Provider was contacted. Never allow
            # a read-side triage to infer that a second dispatch is safe.
            findings.add((key, "COMMITTED_ATTEMPT_BUDGET_MISMATCH"))
        active = row.get("ACTIVE_ATTEMPT_INDEX")
        if active is not None:
            index_of(active, key, "ACTIVE_ATTEMPT_INDEX_OUT_OF_RANGE")
    return [{"logical_asset_key": key, "code": code}
            for key, code in sorted(findings)]


def inspect_attempt_history(connection, *, episode_id: str) -> dict:
    result = {"read_only": True, "sql_writes": 0, "model_calls": 0,
              "status": "BLOCKED", "episode_id": episode_id}
    try:
        identity = connection.query_one(
            "SELECT DATABASE() AS selected_database, @@lower_case_table_names AS case_mode"
        ) or {}
        if (identity.get("selected_database") != DATABASE_NAME
                or identity.get("case_mode") != 0):
            result["reason"] = "ATTEMPT_READONLY_DATABASE_IDENTITY_MISMATCH"
            return result
        result["database_identity_verified"] = True
        attempts = connection.query_all(
            "SELECT LOGICAL_ASSET_KEY, ATTEMPT_INDEX, STATUS FROM TB_GENERATION_ATTEMPT "
            "WHERE EPISODE_ID=%s ORDER BY LOGICAL_ASSET_KEY, ATTEMPT_INDEX",
            (episode_id,),
        ) or []
        asset_states = connection.query_all(
            "SELECT LOGICAL_ASSET_KEY, ATTEMPTS_CONSUMED, ACTIVE_ATTEMPT_INDEX "
            "FROM TB_GENERATION_ASSET_STATE WHERE EPISODE_ID=%s ORDER BY LOGICAL_ASSET_KEY",
            (episode_id,),
        ) or []
        integrity_issues = _history_integrity_issues(episode_id, attempts, asset_states)
        if integrity_issues:
            # The SELECTs remain read-only. Never interpret inconsistent rows
            # as a clean history or disclose foreign Episode asset keys.
            result.update({
                "status": "ATTEMPT_HISTORY_INTEGRITY_BLOCKED",
                "reason": "ATTEMPT_READONLY_AUTHORITY_INTEGRITY_MISMATCH",
                "attempt_rows": len(attempts),
                "asset_state_rows": len(asset_states),
                "integrity_issues": integrity_issues,
                "production_authorization": False,
            })
            return result
        counts = dict(sorted(Counter(str(row.get("STATUS") or "UNKNOWN") for row in attempts).items()))
        unknown = sorted({
            str(row.get("LOGICAL_ASSET_KEY") or "") for row in attempts
            if str(row.get("STATUS") or "") == "OUTCOME_UNKNOWN"
        })
        active_statuses = {"RESERVED", "DISPATCH_COMMITTED"}
        known_terminal = {"SUCCEEDED", "FAILED_AFTER_DISPATCH", "OUTCOME_UNKNOWN",
                          "RELEASED_PRE_DISPATCH"}
        active = sorted({
            str(row.get("LOGICAL_ASSET_KEY") or "") for row in attempts
            if str(row.get("STATUS") or "") in active_statuses
        } | {
            str(row.get("LOGICAL_ASSET_KEY") or "") for row in asset_states
            if row.get("ACTIVE_ATTEMPT_INDEX") is not None
        })
        unverified = sorted({
            str(row.get("LOGICAL_ASSET_KEY") or "") for row in attempts
            if str(row.get("STATUS") or "") not in active_statuses | known_terminal
        })
        blocked_assets = set(unknown) | set(active) | set(unverified)
        status = ("OUTCOME_UNKNOWN_BLOCKED" if unknown else
                  "ACTIVE_ATTEMPT_BLOCKED" if active else
                  "UNVERIFIED_ATTEMPT_STATUS_BLOCKED" if unverified else
                  "ATTEMPT_HISTORY_READ_ONLY")
        result.update({
            "status": status,
            "attempt_rows": len(attempts),
            "asset_state_rows": len(asset_states),
            "attempt_status_counts": counts,
            "outcome_unknown_assets": unknown,
            "active_attempt_assets": active,
            "unverified_status_assets": unverified,
            "attempt_budget": [{
                "logical_asset_key": str(row.get("LOGICAL_ASSET_KEY") or ""),
                "attempts_consumed": int(row.get("ATTEMPTS_CONSUMED") or 0),
                "active_attempt_index": row.get("ACTIVE_ATTEMPT_INDEX"),
            } for row in asset_states
              if str(row.get("LOGICAL_ASSET_KEY") or "") in blocked_assets],
            "production_authorization": False,
        })
    except Exception as exc:
        # Exceptions may contain driver credentials. Only expose the class.
        result["reason"] = "ATTEMPT_READONLY_MYSQL_QUERY_FAILED"
        result["error_type"] = type(exc).__name__
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episode", required=True)
    args = parser.parse_args(argv)
    try:
        _folder, episode_id = canonical_episode(args.episode)
        import storage_config
        from platform.repository.mysql.mysql_connection import MySqlConnection
        from platform.repository.mysql.schema_v2 import DATABASE_NAME
        settings = storage_config.mysql_connection_kwargs({"database": DATABASE_NAME})
        if not settings.get("password"):
            raise ValueError("ATTEMPT_READONLY_MYSQL_CREDENTIAL_MISSING")
        db = MySqlConnection(**settings)
        try:
            result = inspect_attempt_history(db, episode_id=episode_id)
        finally:
            db.close()
    except Exception as exc:
        result = {"status": "BLOCKED", "read_only": True, "sql_writes": 0,
                  "model_calls": 0, "reason": "ATTEMPT_READONLY_PREFLIGHT_FAILED",
                  "error_type": type(exc).__name__}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "ATTEMPT_HISTORY_READ_ONLY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
