"""R19 read-only handoff planning: never creates Episode or starts production."""
from copy import deepcopy
from uuid import uuid4

import pytest

from platform.operations.web_draft_handoff_plan import compile_handoff_plan


def fixture():
    wid = "WDW_" + str(uuid4())
    did = "WDE_" + str(uuid4())
    source = "ep-home-handoff"
    return {
        "workspace_id": wid,
        "version": 2,
        "backup": {
            "format": "storyos-local-draft-backup",
            "version": 1,
            "source": "browser_local_only",
            "drafts": [{"id": source, "title": "原创故事", "synopsis": "山村里发生了一件不可思议的事。"}],
            "projects": [],
        },
        "identity_map": {"drafts": {source: did}, "projects": {}},
    }


def test_handoff_uses_persisted_identity_and_canonical_dry_run():
    saved = fixture()
    before = deepcopy(saved)
    plan = compile_handoff_plan(saved)
    assert saved == before
    assert plan["authority"] == "READ_ONLY_HANDOFF_PLAN"
    assert plan["workspace_id"] == saved["workspace_id"]
    assert plan["workspace_version"] == 2
    assert len(plan["source_sha256"]) == 64
    assert plan["admission_granted"] is False
    assert plan["canonical_episode_created"] is False
    assert plan["production_started"] is False
    assert plan["model_calls"] == plan["runtime_writes"] == 0
    assert len(plan["items"]) == 1
    item = plan["items"][0]
    assert item["server_draft_id"] == saved["identity_map"]["drafts"][saved["backup"]["drafts"][0]["id"]]
    assert item["preflight_available"] is True
    assert item["preflight_argv"] == [
        "python", "episodes/_system/story_os.py", "create",
        "山村里发生了一件不可思议的事。", "--title", "原创故事", "--dry-run", "--json"
    ]


def test_empty_synopsis_refuses_handoff():
    saved = fixture()
    saved["backup"]["drafts"][0]["synopsis"] = "  "
    plan = compile_handoff_plan(saved)
    assert plan["items"][0]["preflight_available"] is False
    assert plan["items"][0]["reason"] == "SYNOPSIS_REQUIRED"
    assert "preflight_argv" not in plan["items"][0]


def test_missing_stable_id_fails_closed():
    saved = fixture()
    saved["identity_map"]["drafts"] = {}
    with pytest.raises(ValueError, match="DRAFT_IDENTITY_NOT_BOUND"):
        compile_handoff_plan(saved)


def test_invalid_workspace_and_version_rejected():
    saved = fixture()
    saved["version"] = True
    with pytest.raises(ValueError, match="WORKSPACE_RECEIPT_INVALID"):
        compile_handoff_plan(saved)
    saved = fixture()
    saved["workspace_id"] = "../story_os_runtime"
    with pytest.raises(ValueError, match="WORKSPACE_RECEIPT_INVALID"):
        compile_handoff_plan(saved)
