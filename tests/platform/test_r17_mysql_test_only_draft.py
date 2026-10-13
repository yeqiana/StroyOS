"""R17 P0: isolated MySQL 8, no production credentials or canonical tables."""
import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from platform.repository.mysql.r17_isolated_draft_repo import (
    R17IsolatedMysqlStore, R17VaultError, DB_NAME,
)

ROOT = Path(__file__).resolve().parents[2]
DDL = ROOT / "platform/repository/mysql/r17_test_only_draft_schema.sql"


@pytest.fixture(scope="module")
def credentials():
    raw = os.environ.get("STORYOS_R17_MYSQL_TEST_AUTH")
    if not raw:
        pytest.skip("Dedicated R17 TEST_ONLY MySQL credential file not set")
    cfg = json.loads(Path(raw).read_text(encoding="utf-8"))
    assert cfg["test_only"] is True
    assert cfg["database"] == DB_NAME
    return cfg


@pytest.fixture(scope="module")
def repo(credentials):
    store = R17IsolatedMysqlStore(credentials, test_only=True)
    store.install_schema(DDL)
    yield store
    store.close()


def _backup(tag, title="Original"):
    return {
        "format": "storyos-local-draft-backup",
        "version": 1,
        "source": "browser_local_only",
        "exportedAt": "2026-10-13T00:00:00Z",
        "projects": [{
            "id": f"proj-{tag}", "name": "TEST Project",
            "createdAt": "2026-10-13", "episodeIds": [],
        }],
        "drafts": [{
            "id": f"ep-home-{tag}", "title": title,
            "code": tag, "synopsis": "TEST ONLY",
            "projectId": f"proj-{tag}", "frameReviews": [],
            "preflightChecks": [], "storyboardBeats": [],
            "characters": [], "runtimeRequest": {"mode": "auto_create"},
            "currentStage": "IDEA_LOCK",
        }],
    }


def _tag():
    return uuid.uuid4().hex[:12]


def test_must_be_dedicated_mysql_and_low_privilege(credentials, repo):
    with pytest.raises(R17VaultError, match="TEST_ONLY_REQUIRED"):
        R17IsolatedMysqlStore(credentials, test_only=False)
    with pytest.raises(R17VaultError, match="UNSAFE_MYSQL_TARGET"):
        R17IsolatedMysqlStore({**credentials, "database": "STORY_OS_RUNTIME"}, test_only=True)
    with repo.conn.cursor() as cur:
        cur.execute("SELECT DATABASE() AS db_name")
        assert cur.fetchone()["db_name"] == DB_NAME
        cur.execute("SHOW GRANTS")
        grant_text = " ".join(str(x) for row in cur.fetchall() for x in row.values()).upper()
        assert DB_NAME in grant_text
        assert "STORY_OS_RUNTIME" not in grant_text
        assert "ALL PRIVILEGES" not in grant_text
        assert " ON *.*" not in grant_text or "GRANT USAGE ON *.*" in grant_text


def test_import_idempotency_conflict_rollback_and_cross_connection(repo, credentials):
    tag = _tag()
    backup = _backup(tag)
    rid = "r17_import_" + tag
    first = repo.import_backup(rid, backup)
    assert first["production_created"] is False
    assert first["test_only"] is True
    assert first["drafts"] == 1 and first["projects"] == 1
    assert repo.import_backup(rid, backup) == first
    with pytest.raises(R17VaultError, match="IDEMPOTENCY_CONFLICT"):
        repo.import_backup(rid, _backup(tag, "changed"))
    with pytest.raises(R17VaultError, match="SOURCE_ID_CONFLICT"):
        repo.import_backup("r17_reimport_" + tag, backup)
    assert repo.read_bundle(first["bundle_id"])["backup"]["drafts"][0]["title"] == "Original"
    reopened = R17IsolatedMysqlStore(credentials, test_only=True)
    try:
        assert reopened.read_bundle(first["bundle_id"])["backup"]["projects"][0]["name"] == "TEST Project"
    finally:
        reopened.close()
    with repo.conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM r17_draft_requests WHERE request_id=%s",
                    ("r17_reimport_" + tag,))
        assert cur.fetchone()["n"] == 0


def test_optimistic_version_and_evidence_projection(repo):
    tag = _tag()
    result = repo.import_backup("r17_ver_" + tag, _backup(tag))
    with repo.conn.cursor() as cur:
        cur.execute("SELECT draft_id FROM r17_draft_episodes WHERE bundle_id=%s", (result["bundle_id"],))
        draft_id = cur.fetchone()["draft_id"]
    name = "Updated " + tag
    first = repo.rename_draft(draft_id, "r17_rename_" + tag, 1, name)
    assert first["revision"] == 2
    assert repo.rename_draft(draft_id, "r17_rename_" + tag, 1, name) == first
    with pytest.raises(R17VaultError, match="VERSION_CONFLICT"):
        repo.rename_draft(draft_id, "r17_stale_" + tag, 1, "stale")
    assert repo.read_bundle(result["bundle_id"])["backup"]["drafts"][0]["title"] == name
    with repo.conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM r17_draft_audit WHERE subject_id IN (%s,%s)",
                    (result["bundle_id"], draft_id))
        assert cur.fetchone()["n"] == 2


def test_concurrent_same_request_returns_one_result(credentials):
    tag = _tag()
    request_id = "r17_parallel_" + tag
    backup = _backup(tag)
    def worker(_):
        conn = R17IsolatedMysqlStore(credentials, test_only=True)
        try:
            return conn.import_backup(request_id, backup)
        finally:
            conn.close()
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(worker, range(2)))
    assert results[0] == results[1]
    conn = R17IsolatedMysqlStore(credentials, test_only=True)
    try:
        with conn.conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM r17_draft_bundles WHERE bundle_id=%s",
                        (results[0]["bundle_id"],))
            assert cur.fetchone()["n"] == 1
            cur.execute("SELECT COUNT(*) AS n FROM r17_draft_requests WHERE request_id=%s",
                        (request_id,))
            assert cur.fetchone()["n"] == 1
    finally:
        conn.close()
