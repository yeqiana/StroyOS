from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
source = ROOT / "scripts/storyos_allow_verified_episode13_compensation.py"
spec = importlib.util.spec_from_file_location("migration", source)
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


def test_scoped_check_does_not_expand_global_two_attempt_cap():
    sql = migration.DDL.lower()
    assert "attempt_index between 1 and 2" in sql
    assert "attempt_index = 3 and" in sql
    assert migration.EPISODE in migration.DDL
    assert migration.KEY in migration.DDL
    assert sql.count("drop check") == 1
    assert sql.count("add constraint") == 1


def test_schema_drift_fails_closed_and_migration_is_idempotent():
    old = ("CONSTRAINT CHECK_TB_GENERATION_ATTEMPT_INDEX "
           "CHECK ((ATTEMPT_INDEX between 1 and 2))")
    modern = ("CONSTRAINT CHECK_TB_GENERATION_ATTEMPT_INDEX CHECK "
              "((ATTEMPT_INDEX between 1 and 2) or "
              "((ATTEMPT_INDEX = 3) and "
              "(EPISODE_ID = '00_独立篇/13_失物归还的那扇门') and "
              "(LOGICAL_ASSET_KEY = '00_独立篇/13_失物归还的那扇门/frame-01')))")
    assert migration.classify(old) == "LEGACY_TWO_ATTEMPT_CHECK"
    assert migration.classify(modern) == "VERIFIED_SCOPED_THIRD_ATTEMPT"
    with pytest.raises(RuntimeError):
        migration.classify("CONSTRAINT CHECK_TB_GENERATION_ATTEMPT_INDEX CHECK (1=1)")
    with pytest.raises(RuntimeError):
        migration.classify("CONSTRAINT CHECK_TB_GENERATION_ATTEMPT_INDEX CHECK "
                           "((ATTEMPT_INDEX between 1 and 3))")
