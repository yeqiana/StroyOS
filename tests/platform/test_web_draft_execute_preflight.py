"""R20 executable but side-effect-free canonical dry-run contract."""
import subprocess
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from platform.operations.web_draft_execute_preflight import (
    execute_saved_dry_run, PreflightBlocked,
)
from platform.operations.web_draft_handoff_plan import compile_handoff_plan

ROOT=Path(__file__).resolve().parents[2]


def saved():
    uid=uuid4()
    return {
        "workspace_id": "WDW_" + str(uuid4()),
        "version": 4,
        "backup":{
            "format":"storyos-local-draft-backup","version":1,"source":"browser_local_only",
            "drafts":[{"id":"ep-home-"+str(uid),"title":"午后的山村","synopsis":"一个普通村子的午后出现了异常现象。"}],
            "projects":[]
        },
        "identity_map":{"projects":{},"drafts":{"ep-home-"+str(uid):"WDE_"+str(uuid4())}}
    }


def params(record):
    plan=compile_handoff_plan(record)
    return {"server_draft_id":plan["items"][0]["server_draft_id"],
            "workspace_version":plan["workspace_version"],
            "source_sha256":plan["source_sha256"]}


def runner_ok(commands, **kwargs):
    assert commands[2] == "create"
    assert commands[-2:] == ["--dry-run","--json"]
    assert not any(option in commands for option in ("--full-auto","driver","start","run"))
    assert kwargs["env"]["STORYOS_MYSQL_PORT"] == "3307"
    return SimpleNamespace(returncode=2,stdout='{"status":"PLANNED","dry_run":true,"written":false,"created":false,"workflow":{"invoked":false},"production":"not_started","visual_profile_selection":{"profile_id":"test"}}')


def test_versioned_canonical_dryrun_command_only():
    record=saved()
    out=execute_saved_dry_run(record,params(record),root=ROOT,runner=runner_ok)
    assert out["authority"]=="CANONICAL_DRY_RUN"
    assert out["real_preflight_executed"] is True
    assert out["profile_id"]=="test"
    assert out["canonical_episode_created"] is False
    assert out["production_started"] is False
    assert out["admission_granted"] is False


@pytest.mark.parametrize("tamper",[
    lambda req: req.update(workspace_version=1),
    lambda req: req.update(source_sha256="0"*64),
    lambda req: req.update(server_draft_id="WDE_"+str(uuid4())),
    lambda req: req.update(unknown="argument"),
])
def test_stale_or_invalid_request_fails_without_spawning(tamper):
    record=saved()
    req=params(record)
    tamper(req)
    def never(*args, **kwargs):
        pytest.fail("Rejected request must not spawn subprocess")
    with pytest.raises(PreflightBlocked):
        execute_saved_dry_run(record,req,root=ROOT,runner=never)


def test_invalid_canonical_receipt_does_not_claim_pass():
    record=saved()
    def invalid(*args,**kwargs):
        return SimpleNamespace(returncode=0,stdout='{"status":"PUBLISH_READY","dry_run":false,"written":true,"created":true,"workflow":{"invoked":true},"production":"done"}')
    with pytest.raises(PreflightBlocked,match="PREFLIGHT_UNSAFE_RECEIPT"):
        execute_saved_dry_run(record,params(record),root=ROOT,runner=invalid)


def test_timeout_and_process_fail_closed():
    record=saved()
    def timeout(*args,**kwargs):
        raise subprocess.TimeoutExpired("create",timeout=24)
    with pytest.raises(PreflightBlocked,match="PREFLIGHT_TIMEOUT"):
        execute_saved_dry_run(record,params(record),root=ROOT,runner=timeout)


def test_config_not_provisioned_blocks(monkeypatch):
    record=saved()
    monkeypatch.delenv("STORYOS_WEB_DRAFTS_PREFLIGHT_AUTH",raising=False)
    with pytest.raises(PreflightBlocked,match="PREFLIGHT_READONLY_DB_NOT_CONFIGURED"):
        execute_saved_dry_run(record,params(record),root=ROOT)
