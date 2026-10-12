"""Hermetic SQL read-only adapter validation (no production database)."""
from __future__ import annotations

from unittest.mock import Mock
import pytest

from platform.operations.runtime_authority_evidence import RuntimeAuthorityEvidenceService
from platform.operations.runtime_authority_readers import (
    AdvisoryCapacityReadOnlyReader, MySqlAuthorityReadOnlyReaders,
)


class SelectOnlyConnection:
    def __init__(self, database="STORY_OS_RUNTIME", case_mode=0, tasks=4, attempts=2, unresolved=1, unknown=0):
        self.database, self.case_mode = database, case_mode
        self.tasks, self.attempts, self.unresolved, self.unknown = tasks, attempts, unresolved, unknown
        self.calls = []

    def query_one(self, sql, params=None):
        self.calls.append((sql, params))
        assert sql.startswith("SELECT "), "READ_ONLY_SQL_REQUIRED"
        if sql.startswith("SELECT DATABASE()"):
            return {"selected_database": self.database, "case_mode": self.case_mode}
        if "FROM TB_TASK " in sql:
            assert params == ("EPU_source",), "Task uses canonical storage UID"
            return {"task_count": self.tasks}
        if "FROM TB_GENERATION_ATTEMPT " in sql:
            assert params == ("series/episode",), "Generation Attempt uses stable namespace"
            return {"attempt_count": self.attempts, "unresolved_count": self.unresolved,
                    "unknown_count": self.unknown}
        raise AssertionError("UNEXPECTED_SQL")

    def execute(self, *_):
        raise AssertionError("SQL_MUTATION_FORBIDDEN")


class EpisodeRepository:
    def __init__(self, namespace="series/episode", state="ACTIVE"):
        self.namespace, self.state = namespace, state
        self.calls = []

    def unique_owner_by_namespace(self, namespace):
        self.calls.append(namespace)
        return {
            "episode_namespace": self.namespace, "episode_id": "EPU_source",
            "disposition": self.state,
        }


class Status:
    def get_episode_status(self, ref):
        return {"episode_ref": ref, "state_source": "MYSQL_REDIS_CUTOVER"}


def test_mysql_task_attempt_do_only_episode_bound_selects():
    connection=SelectOnlyConnection()
    repo=EpisodeRepository()
    adapters=MySqlAuthorityReadOnlyReaders(connection, repo)
    service=RuntimeAuthorityEvidenceService(
        Status(), permit_authority_reads=True,
        authorized_readers={"task": adapters.task, "attempt": adapters.attempt},
    )
    report=service.get_episode_authority("series/episode")
    assert report["scope"] == "AUTHORIZED_READ_ONLY"
    assert report["evidence"]["task"]["status"] == "READ_ONLY_VERIFIED"
    assert report["evidence"]["task"]["task_count"] == 4
    assert report["evidence"]["attempt"]["attempt_count"] == 2
    assert report["evidence"]["attempt"]["unresolved"] is True
    assert report["evidence"]["worker"]["status"] == "UNAVAILABLE"
    assert report["production_authorization"] is False
    assert repo.calls == ["series/episode","series/episode"]
    assert len(connection.calls) == 4
    assert all(sql.startswith("SELECT ") for sql, _ in connection.calls)
    assert [params for _, params in connection.calls if params is not None] == [
        ("EPU_source",), ("series/episode",),
    ]


@pytest.mark.parametrize("database,mode", [
    ("STORY_OS_RUNTIME", 1),
    ("story_os_runtime", 0),
    ("OTHER_SCHEMA", 0),
])
def test_bad_mysql_database_identity_never_reads_task_or_attempt(database,mode):
    db=SelectOnlyConnection(database=database,case_mode=mode)
    readers=MySqlAuthorityReadOnlyReaders(db, EpisodeRepository())
    report=RuntimeAuthorityEvidenceService(
        Status(), permit_authority_reads=True,
        authorized_readers={"task": readers.task, "attempt": readers.attempt},
    ).get_episode_authority("series/episode")
    assert report["evidence"]["task"]["status"] == "UNAVAILABLE"
    assert report["evidence"]["attempt"]["status"] == "UNAVAILABLE"
    assert all("FROM TB_TASK" not in sql and "FROM TB_GENERATION_ATTEMPT" not in sql
               for sql,_ in db.calls)


@pytest.mark.parametrize("namespace,state", [
    ("other/episode","ACTIVE"),
    ("series/episode","VOIDED"),
])
def test_wrong_episode_namespace_or_disposition_cannot_query_tasks(namespace,state):
    db=SelectOnlyConnection()
    repo=EpisodeRepository(namespace,state)
    adapter=MySqlAuthorityReadOnlyReaders(db,repo)
    report=RuntimeAuthorityEvidenceService(
        Status(),permit_authority_reads=True,authorized_readers={"task":adapter.task}
    ).get_episode_authority("series/episode")
    assert report["evidence"]["task"]["status"]=="UNAVAILABLE"
    assert not any("FROM TB_TASK" in sql for sql,_ in db.calls)


def test_counts_fail_closed_if_out_of_bounds_or_corrupt():
    db=SelectOnlyConnection(tasks=-1,attempts=2,unresolved=3)
    adapter=MySqlAuthorityReadOnlyReaders(db, EpisodeRepository())
    report=RuntimeAuthorityEvidenceService(
        Status(),permit_authority_reads=True,authorized_readers={
            "task":adapter.task,"attempt":adapter.attempt,
        }
    ).get_episode_authority("series/episode")
    assert report["evidence"]["task"]["status"]=="UNAVAILABLE"
    assert report["evidence"]["attempt"]["status"]=="UNAVAILABLE"


def test_unknown_generation_outcome_is_reported_without_authorizing_retry():
    db = SelectOnlyConnection(attempts=2, unresolved=1, unknown=1)
    reader = MySqlAuthorityReadOnlyReaders(db, EpisodeRepository())
    report = RuntimeAuthorityEvidenceService(
        Status(), permit_authority_reads=True,
        authorized_readers={"attempt": reader.attempt},
    ).get_episode_authority("series/episode")
    row = report["evidence"]["attempt"]
    assert row["status"] == "READ_ONLY_VERIFIED"
    assert row["unresolved"] is True
    assert row["unknown"] is True
    assert report["can_retry"] is False
    assert "STATUS='OUTCOME_UNKNOWN'" in db.calls[-1][0]
    assert db.calls[-1][1] == ("series/episode",)


def test_unknown_count_inconsistency_blocks_attempt_evidence():
    db = SelectOnlyConnection(attempts=2, unresolved=1, unknown=2)
    reader = MySqlAuthorityReadOnlyReaders(db, EpisodeRepository())
    report = RuntimeAuthorityEvidenceService(
        Status(), permit_authority_reads=True,
        authorized_readers={"attempt": reader.attempt},
    ).get_episode_authority("series/episode")
    assert report["evidence"]["attempt"]["status"] == "UNAVAILABLE"
    assert report["production_authorization"] is False


def test_advisory_capacity_snapshot_preserves_five_image_global_limit(tmp_path):
    from episodes._system import global_image_capacity as capacity
    read=AdvisoryCapacityReadOnlyReader(
        lambda:capacity.snapshot(shared_dir=tmp_path/"slots"))
    report=RuntimeAuthorityEvidenceService(
        Status(), permit_authority_reads=True,
        authorized_readers={"capacity":read},
    ).get_episode_authority("series/episode")
    row=report["evidence"]["capacity"]
    assert row["status"]=="ADVISORY_ONLY"
    assert row["observed_busy"]==0
    assert row["observed_available"]==5
    assert row["advisory_snapshot_only"] is True
    assert report["can_start"] is False
    assert report["can_retry"] is False


def test_capacity_corrupt_snapshot_fails_closed():
    read=AdvisoryCapacityReadOnlyReader(
        lambda:{"scope":"LOCAL_GIT_COMMON_DIRECTORY",
                "global_max_inflight_images":5,"observed_busy":4,
                "observed_available":4,"advisory_snapshot_only":True})
    report=RuntimeAuthorityEvidenceService(
        Status(),permit_authority_reads=True,authorized_readers={"capacity":read}
    ).get_episode_authority("series/episode")
    assert report["evidence"]["capacity"]["status"]=="UNAVAILABLE"
    assert report["production_authorization"] is False


def test_local_file_evidence_does_not_access_injected_mysql_or_os_locks():
    db=SelectOnlyConnection()
    adapter=MySqlAuthorityReadOnlyReaders(db,EpisodeRepository())
    locks=Mock(side_effect=RuntimeError("OS slot should not be read"))
    class LocalStatus:
        def get_episode_status(self,ref):
            return {"episode_ref":ref,"state_source":"local_workspace_episode_state_file"}
    report=RuntimeAuthorityEvidenceService(
        LocalStatus(),permit_authority_reads=True,authorized_readers={
            "task":adapter.task,"attempt":adapter.attempt,
            "capacity":AdvisoryCapacityReadOnlyReader(locks),
        }
    ).get_episode_authority("LOCAL_abc")
    assert db.calls==[]
    locks.assert_not_called()
    assert all(x["status"]=="UNAVAILABLE" for x in report["evidence"].values())
