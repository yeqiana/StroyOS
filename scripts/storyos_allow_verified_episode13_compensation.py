#!/usr/bin/env python3
"""One-time, fail-closed MySQL CHECK migration for a single proven image repair.

The normal Generation Attempt limit remains 2 everywhere else. This DDL does
not authorize Provider dispatch; generation_attempt_authority independently
verifies both predecessor receipts and the exact repair context.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "episodes/_system"))

CHECK_NAME = "CHECK_TB_GENERATION_ATTEMPT_INDEX"
EPISODE = "00_独立篇/13_失物归还的那扇门"
KEY = EPISODE + "/frame-01"
# Static, fully controlled SQL; no untrusted strings are interpolated.
DDL = (
    "ALTER TABLE TB_GENERATION_ATTEMPT "
    "DROP CHECK CHECK_TB_GENERATION_ATTEMPT_INDEX, "
    "ADD CONSTRAINT CHECK_TB_GENERATION_ATTEMPT_INDEX CHECK ("
    "(ATTEMPT_INDEX BETWEEN 1 AND 2) OR "
    "(ATTEMPT_INDEX = 3 AND "
    "EPISODE_ID = '00_独立篇/13_失物归还的那扇门' AND "
    "LOGICAL_ASSET_KEY = '00_独立篇/13_失物归还的那扇门/frame-01'))"
)


def classify(ddl: str) -> str:
    line = next((line for line in ddl.splitlines() if CHECK_NAME in line), "")
    normalized = line.lower().replace(chr(96), "").replace(" ", "")
    if not line:
        raise RuntimeError("ATTEMPT_INDEX_CHECK_ABSENT_REFUSE_MIGRATION")
    if "between1and2" not in normalized:
        raise RuntimeError("ATTEMPT_INDEX_CHECK_DRIFT_REFUSE_MIGRATION")
    if "attempt_index=3" in normalized:
        if EPISODE.lower() not in normalized or KEY.lower() not in normalized:
            raise RuntimeError("ATTEMPT_INDEX_CHECK_ALREADY_CHANGED_OTHER_SCOPE")
        return "VERIFIED_SCOPED_THIRD_ATTEMPT"
    if "episode_id" in normalized or "logical_asset_key" in normalized:
        raise RuntimeError("ATTEMPT_INDEX_CHECK_UNRECOGNIZED_REFUSE_MIGRATION")
    return "LEGACY_TWO_ATTEMPT_CHECK"


def main() -> int:
    import generation_attempt_authority as authority

    cn = authority._connect()
    try:
        before = cn.query_one("SHOW CREATE TABLE TB_GENERATION_ATTEMPT", ())
        status = classify(before["Create Table"])
        if status == "LEGACY_TWO_ATTEMPT_CHECK":
            # Atomic MySQL DDL: no interval with the CHECK absent.
            cn.execute(DDL)
        after = cn.query_one("SHOW CREATE TABLE TB_GENERATION_ATTEMPT", ())
        assert classify(after["Create Table"]) == "VERIFIED_SCOPED_THIRD_ATTEMPT"
        print(json.dumps({
            "status": "SCOPED_CHECK_VERIFIED",
            "alter_applied": status == "LEGACY_TWO_ATTEMPT_CHECK",
            "ordinary_attempt_limit_unchanged": 2,
            "allowed_extra_attempt": 3,
            "allowed_asset": KEY,
        }, ensure_ascii=False))
        return 0
    finally:
        cn.close()


if __name__ == "__main__":
    raise SystemExit(main())
