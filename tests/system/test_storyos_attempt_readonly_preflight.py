"""Hermetic contract checks for read-only MySQL Attempt recovery triage."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import storyos_attempt_readonly_preflight as audit


class FakeConnection:
    def __init__(self, attempts=None, states=None, error=None,
                 database="STORY_OS_RUNTIME", case_mode=0):
        self.database = database
        self.case_mode = case_mode
        self.attempts = attempts or []
        self.states = states or []
        self.error = error
        self.queries = []

    def query_one(self, sql):
        self.queries.append((sql, None))
        if self.error:
            raise self.error
        assert sql.startswith("SELECT DATABASE()")
        return {"selected_database": self.database, "case_mode": self.case_mode}

    def query_all(self, sql, params):
        self.queries.append((sql, params))
        if self.error:
            raise self.error
        if "FROM TB_GENERATION_ATTEMPT " in sql:
            return self.attempts
        if "FROM TB_GENERATION_ASSET_STATE " in sql:
            return self.states
        raise AssertionError("UNEXPECTED_SQL")

    def execute(self, *_):
        raise AssertionError("READONLY_MUST_NOT_WRITE")


def test_unknown_attempts_keep_identity_and_shared_budget():
    episode = "00_demo/05_story"
    key6 = episode + "/frame-06"
    key24 = episode + "/frame-24"
    db = FakeConnection(
        attempts=[{"LOGICAL_ASSET_KEY": key6, "ATTEMPT_INDEX": 1,
                   "STATUS": "OUTCOME_UNKNOWN"},
                  {"LOGICAL_ASSET_KEY": key24, "ATTEMPT_INDEX": 1,
                   "STATUS": "OUTCOME_UNKNOWN"},
                  {"LOGICAL_ASSET_KEY": episode + "/frame-03", "ATTEMPT_INDEX": 1,
                   "STATUS": "SUCCEEDED"}],
        states=[{"LOGICAL_ASSET_KEY": key6, "ATTEMPTS_CONSUMED": 1},
                {"LOGICAL_ASSET_KEY": key24, "ATTEMPTS_CONSUMED": 1}])
    result = audit.inspect_attempt_history(db, episode_id=episode)
    assert result["status"] == "OUTCOME_UNKNOWN_BLOCKED"
    assert result["attempt_status_counts"] == {"OUTCOME_UNKNOWN": 2, "SUCCEEDED": 1}
    assert result["outcome_unknown_assets"] == [key6, key24]
    assert all(x["attempts_consumed"] == 1 for x in result["attempt_budget"])
    assert result["production_authorization"] is False
    assert len(db.queries) == 3
    assert all(sql.startswith("SELECT ") for sql, _ in db.queries)
    assert all(params == (episode,) for _, params in db.queries[1:])


def test_empty_history_does_not_claim_production_ready():
    result = audit.inspect_attempt_history(FakeConnection(), episode_id="ep")
    assert result["status"] == "ATTEMPT_HISTORY_READ_ONLY"
    assert result["production_authorization"] is False
    assert result["attempt_rows"] == 0


def test_active_dispatch_or_lease_blocks_even_without_outcome_unknown():
    episode = "00_demo/05_story"
    key = episode + "/frame-02"
    db = FakeConnection(
        attempts=[{"LOGICAL_ASSET_KEY": key, "ATTEMPT_INDEX": 1,
                   "STATUS": "DISPATCH_COMMITTED"}],
        states=[{"LOGICAL_ASSET_KEY": key, "ATTEMPTS_CONSUMED": 1,
                 "ACTIVE_ATTEMPT_INDEX": 1}],
    )
    result = audit.inspect_attempt_history(db, episode_id=episode)
    assert result["status"] == "ACTIVE_ATTEMPT_BLOCKED"
    assert result["active_attempt_assets"] == [key]
    assert result["attempt_budget"][0]["attempts_consumed"] == 1
    assert result["production_authorization"] is False


def test_stale_active_pointer_without_inflight_row_still_blocks():
    key = "ep/frame-01"
    result = audit.inspect_attempt_history(
        FakeConnection(states=[{"LOGICAL_ASSET_KEY": key, "ATTEMPTS_CONSUMED": 1,
                                "ACTIVE_ATTEMPT_INDEX": 1}]), episode_id="ep")
    assert result["status"] == "ACTIVE_ATTEMPT_BLOCKED"
    assert result["active_attempt_assets"] == [key]


def test_wrong_database_or_case_mode_blocks_before_attempt_reads():
    for database, mode in (("story_os_runtime", 0), ("STORY_OS_RUNTIME", 1)):
        db = FakeConnection(database=database, case_mode=mode)
        result = audit.inspect_attempt_history(db, episode_id="ep")
        assert result["status"] == "BLOCKED"
        assert result["reason"] == "ATTEMPT_READONLY_DATABASE_IDENTITY_MISMATCH"
        assert len(db.queries) == 1


def test_unrecognised_status_cannot_be_mistaken_for_clean_history():
    row = {"LOGICAL_ASSET_KEY": "ep/frame-01", "ATTEMPT_INDEX": 1,
           "STATUS": "UNEXPECTED_STATE"}
    result = audit.inspect_attempt_history(FakeConnection(attempts=[row]), episode_id="ep")
    assert result["status"] == "UNVERIFIED_ATTEMPT_STATUS_BLOCKED"
    assert result["unverified_status_assets"] == ["ep/frame-01"]


def test_mysql_error_fails_closed_and_never_leaks_driver_secret():
    db = FakeConnection(error=ConnectionError("private-driver-secret"))
    result = audit.inspect_attempt_history(db, episode_id="ep")
    assert result["status"] == "BLOCKED"
    assert "private-driver-secret" not in str(result)



def test_integrity_rejects_foreign_episode_attempt_without_exposing_other_story():
    episode = "00_demo/05_story"
    foreign = "other_story/private_frame_key"
    db = FakeConnection(attempts=[{
        "LOGICAL_ASSET_KEY": foreign, "ATTEMPT_INDEX": 1, "STATUS": "SUCCEEDED",
    }])
    result = audit.inspect_attempt_history(db, episode_id=episode)
    assert result["status"] == "ATTEMPT_HISTORY_INTEGRITY_BLOCKED"
    assert result["integrity_issues"] == [{
        "logical_asset_key": "OUT_OF_SCOPE",
        "code": "ASSET_EPISODE_IDENTITY_MISMATCH",
    }]
    assert foreign not in str(result)
    assert result["production_authorization"] is False
    assert all(sql.startswith("SELECT ") for sql, _ in db.queries)


def test_integrity_rejects_foreign_episode_asset_state_and_invalid_budget():
    episode = "ep"
    foreign = "other/secret"
    key = "ep/frame-01"
    db = FakeConnection(states=[
        {"LOGICAL_ASSET_KEY": foreign, "ATTEMPTS_CONSUMED": 0},
        {"LOGICAL_ASSET_KEY": key, "ATTEMPTS_CONSUMED": 3},
    ])
    result = audit.inspect_attempt_history(db, episode_id=episode)
    assert result["status"] == "ATTEMPT_HISTORY_INTEGRITY_BLOCKED"
    assert {i["code"] for i in result["integrity_issues"]} == {
        "ASSET_EPISODE_IDENTITY_MISMATCH", "ATTEMPT_BUDGET_OUT_OF_RANGE"}
    assert foreign not in str(result)
    assert result["production_authorization"] is False


def test_integrity_rejects_duplicate_attempt_identity_and_state_rows():
    key = "ep/frame-01"
    attempts = [{"LOGICAL_ASSET_KEY": key, "ATTEMPT_INDEX": 1,
                 "STATUS": "SUCCEEDED"}] * 2
    states = [{"LOGICAL_ASSET_KEY": key, "ATTEMPTS_CONSUMED": 1}] * 2
    result = audit.inspect_attempt_history(
        FakeConnection(attempts=attempts, states=states), episode_id="ep")
    assert result["status"] == "ATTEMPT_HISTORY_INTEGRITY_BLOCKED"
    assert {x["code"] for x in result["integrity_issues"]} == {
        "DUPLICATE_ATTEMPT_INDEX", "DUPLICATE_ASSET_STATE"}


def test_integrity_rejects_out_of_range_attempt_and_active_indices():
    key = "ep/frame-01"
    db = FakeConnection(
        attempts=[{"LOGICAL_ASSET_KEY": key, "ATTEMPT_INDEX": 3, "STATUS": "SUCCEEDED"}],
        states=[{"LOGICAL_ASSET_KEY": key, "ATTEMPTS_CONSUMED": 1,
                 "ACTIVE_ATTEMPT_INDEX": 0}],
    )
    result = audit.inspect_attempt_history(db, episode_id="ep")
    assert result["status"] == "ATTEMPT_HISTORY_INTEGRITY_BLOCKED"
    assert {i["code"] for i in result["integrity_issues"]} == {
        "ATTEMPT_INDEX_OUT_OF_RANGE", "ACTIVE_ATTEMPT_INDEX_OUT_OF_RANGE"}


def test_integrity_rejects_boolean_and_non_numeric_mysql_projection():
    key = "ep/frame-01"
    db = FakeConnection(
        attempts=[{"LOGICAL_ASSET_KEY": key, "ATTEMPT_INDEX": True,
                   "STATUS": "FAILED_AFTER_DISPATCH"}],
        states=[{"LOGICAL_ASSET_KEY": key, "ATTEMPTS_CONSUMED": "garbled"}],
    )
    result = audit.inspect_attempt_history(db, episode_id="ep")
    assert result["status"] == "ATTEMPT_HISTORY_INTEGRITY_BLOCKED"
    assert {i["code"] for i in result["integrity_issues"]} == {
        "ATTEMPT_INDEX_OUT_OF_RANGE", "ATTEMPT_BUDGET_OUT_OF_RANGE"}
    assert "garbled" not in str(result)



def test_committed_attempt_must_not_outpace_consumed_budget():
    key = "ep/frame-03"
    result = audit.inspect_attempt_history(
        FakeConnection(
            attempts=[{"LOGICAL_ASSET_KEY": key, "ATTEMPT_INDEX": 2,
                       "STATUS": "SUCCEEDED"}],
            states=[{"LOGICAL_ASSET_KEY": key, "ATTEMPTS_CONSUMED": 1}],
        ),
        episode_id="ep",
    )
    assert result["status"] == "ATTEMPT_HISTORY_INTEGRITY_BLOCKED"
    assert result["integrity_issues"] == [{
        "logical_asset_key": key,
        "code": "COMMITTED_ATTEMPT_BUDGET_MISMATCH",
    }]
    assert result["production_authorization"] is False


def test_reserved_attempt_does_not_consume_budget_before_dispatch():
    key = "ep/frame-02"
    result = audit.inspect_attempt_history(
        FakeConnection(
            attempts=[{"LOGICAL_ASSET_KEY": key, "ATTEMPT_INDEX": 2,
                       "STATUS": "RESERVED"}],
            states=[{"LOGICAL_ASSET_KEY": key, "ATTEMPTS_CONSUMED": 1,
                     "ACTIVE_ATTEMPT_INDEX": 2}],
        ),
        episode_id="ep",
    )
    assert result["status"] == "ACTIVE_ATTEMPT_BLOCKED"
    assert "integrity_issues" not in result
    assert result["production_authorization"] is False


def test_two_terminal_attempts_can_be_described_without_authorizing_another():
    key = "ep/frame-01"
    db = FakeConnection(
        attempts=[{"LOGICAL_ASSET_KEY": key, "ATTEMPT_INDEX": 1,
                   "STATUS": "FAILED_AFTER_DISPATCH"},
                  {"LOGICAL_ASSET_KEY": key, "ATTEMPT_INDEX": 2,
                   "STATUS": "SUCCEEDED"}],
        states=[{"LOGICAL_ASSET_KEY": key, "ATTEMPTS_CONSUMED": 2}],
    )
    result = audit.inspect_attempt_history(db, episode_id="ep")
    assert result["status"] == "ATTEMPT_HISTORY_READ_ONLY"
    assert result["attempt_status_counts"] == {
        "FAILED_AFTER_DISPATCH": 1, "SUCCEEDED": 1}
    assert result["production_authorization"] is False


def test_canonical_episode_rejects_path_escape_and_duplicate_root(tmp_path):
    (tmp_path / "episodes" / "demo").mkdir(parents=True)
    folder, identifier = audit.canonical_episode("episodes/demo", root=tmp_path)
    assert folder.is_dir() and identifier == "demo"
    outside = tmp_path / "outside"
    outside.mkdir()
    import pytest
    with pytest.raises(ValueError, match="ATTEMPT_READONLY_EPISODE_PATH_INVALID"):
        audit.canonical_episode(str(outside), root=tmp_path)
