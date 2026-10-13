"""Fast real-MySQL contract test: dedicated DB only, zero canonical Episode mutations."""
import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from platform.repository.mysql.web_draft_repository import (
    WebDraftRepository, DraftWriteError, DATABASE,
)

AUTH = Path(os.environ.get("STORYOS_WEB_DRAFTS_AUTH", ""))


@pytest.fixture
def credentials():
    if not AUTH.is_file():
        pytest.skip("No dedicated test Web draft credential file")
    data=json.loads(AUTH.read_text(encoding="utf8"))
    assert data["test_only"] is True
    assert data["database"] == DATABASE
    return data


def backup():
    code=uuid.uuid4().hex[:12]
    return {"format":"storyos-local-draft-backup","version":1,
            "source":"browser_local_only","exportedAt":"2026-10-13T00:00:00Z",
            "projects":[{"id":"proj-"+code,"name":"Saved project","createdAt":"2026-10-13","episodeIds":[]}],
            "drafts":[{"id":"ep-home-"+code,"projectId":"proj-"+code,"title":"One","code":code,
                       "synopsis":"draft only","frameReviews":[],"preflightChecks":[],
                       "runtimeRequest":{"mode":"dry"},"storyboardBeats":[],"characters":[],
                       "currentStage":"IDEA_LOCK"}]}


def test_reject_production_connection_and_elevated_scope(credentials):
    with pytest.raises(DraftWriteError, match="DRAFT_DATABASE_IDENTITY_FORBIDDEN"):
        WebDraftRepository({**credentials, "database":"STORY_OS_RUNTIME"}, test_only=True)
    with pytest.raises(DraftWriteError, match="DRAFT_DATABASE_IDENTITY_FORBIDDEN"):
        WebDraftRepository(credentials, test_only=False)
    repo=WebDraftRepository(credentials,test_only=True)
    try:
        with repo.db.cursor() as cur:
            cur.execute("SHOW GRANTS")
            grants=" ".join(str(x) for row in cur.fetchall() for x in row.values()).upper()
            assert DATABASE in grants
            assert "STORY_OS_RUNTIME" not in grants
            assert "ALL PRIVILEGES" not in grants
            assert " ON *.*" not in grants or "GRANT USAGE ON *.*" in grants
    finally:repo.close()


def test_create_update_identity_stable_cas_read_again(credentials):
    repo=WebDraftRepository(credentials,test_only=True)
    try:
        content=backup()
        create_id="web_create_"+uuid.uuid4().hex
        first=repo.save(create_id,content)
        assert first["version"]==1
        assert first["canonical_episode_created"] is False
        assert first["production_started"] is False
        assert first["draft_saved"] is True
        assert len(first["identity_map"]["projects"])==1
        assert len(first["identity_map"]["drafts"])==1
        assert all(v.startswith("WDP_") for v in first["identity_map"]["projects"].values())
        assert all(v.startswith("WDE_") for v in first["identity_map"]["drafts"].values())
        assert repo.save(create_id,content)==first
        edited={**content,"drafts":[{**content["drafts"][0],"title":"Second"}]}
        update_id="web_update_"+uuid.uuid4().hex
        latest=repo.save(update_id,edited,first["workspace_id"],1)
        assert latest["version"]==2
        assert latest["identity_map"]==first["identity_map"]
        assert repo.save(update_id,edited,first["workspace_id"],1)==latest
        with pytest.raises(DraftWriteError, match="VERSION_CONFLICT"):
            repo.save("web_stale_"+uuid.uuid4().hex,content,first["workspace_id"],1)
        with pytest.raises(DraftWriteError, match="IDEMPOTENCY_CONFLICT"):
            repo.save(update_id,content,first["workspace_id"],1)
        reread=repo.read(first["workspace_id"])
        assert reread["backup"]["drafts"][0]["title"]=="Second"
        assert reread["identity_map"]==first["identity_map"]
        assert any(row["workspace_id"]==first["workspace_id"] for row in repo.list()["items"])
        new=WebDraftRepository(credentials,test_only=True)
        try:
            assert new.read(first["workspace_id"])["version"]==2
        finally:new.close()
    finally:repo.close()


def test_parallel_same_request_creates_one_workspace(credentials):
    content=backup()
    req="web_parallel_"+uuid.uuid4().hex
    def worker(_):
        repo=WebDraftRepository(credentials,test_only=True)
        try:return repo.save(req,content)
        finally:repo.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(worker,range(2)))
    assert results[0]==results[1]
    repo=WebDraftRepository(credentials,test_only=True)
    try:
        with repo.db.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM WEB_DRAFT_WORKSPACE WHERE WORKSPACE_ID=%s",
                        (results[0]["workspace_id"],))
            assert cur.fetchone()["n"]==1
            cur.execute("SELECT COUNT(*) AS n FROM WEB_DRAFT_REQUEST WHERE REQUEST_ID=%s",(req,))
            assert cur.fetchone()["n"]==1
    finally:repo.close()


def test_durable_identity_claim_records_pending_and_completion(credentials):
    record=WebDraftRepository(credentials,test_only=True)
    try:
        item=backup()
        saved=record.save("r21_source_"+uuid.uuid4().hex,item)
        workspace=saved["workspace_id"]
        did=next(iter(saved["identity_map"]["drafts"].values()))
        record.reserve_episode_bootstrap(workspace,1,did,"Claimed title")
        pending=record.read(workspace)["identity_map"]["episode_bootstraps"][did]
        assert pending["status"]=="PENDING"
        with pytest.raises(DraftWriteError,match="EPISODE_DRAFT_ALREADY_SUBMITTED"):
            record.reserve_episode_bootstrap(workspace,1,did,"Changed title")
        record.complete_episode_bootstrap(workspace,did,"00_独立篇/45_Claimed_title")
        done=record.read(workspace)["identity_map"]["episode_bootstraps"][did]
        assert done["status"]=="CREATED"
        assert done["namespace"]=="00_独立篇/45_Claimed_title"
        # A browser version update must retain the irreversible WDE mapping.
        edited={**item,"drafts":[{**item["drafts"][0],"title":"Edited"}]}
        record.save("r21_edit_"+uuid.uuid4().hex,edited,workspace,1)
        assert record.read(workspace)["identity_map"]["episode_bootstraps"][did]==done
    finally:
        record.close()
