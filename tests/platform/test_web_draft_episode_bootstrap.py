"""R21 bootstrap safety contract: no formal Episode, Driver, or paid model calls."""
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from platform.operations.web_draft_episode_bootstrap import BootstrapBlocked, bootstrap_saved_episode
from platform.operations.web_draft_handoff_plan import compile_handoff_plan


def saved():
    uid=str(uuid4())
    return {
        "workspace_id":"WDW_"+str(uuid4()),"version":3,
        "backup":{"format":"storyos-local-draft-backup","version":1,"source":"browser_local_only",
                  "drafts":[{"id":"ep-home-"+uid,"title":"全新测试故事","synopsis":"山村里发生了一件重要的事。"}],
                  "projects":[]},
        "identity_map":{"drafts":{"ep-home-"+uid:"WDE_"+str(uuid4())},"projects":{}}
    }


def request(record):
    plan=compile_handoff_plan(record)
    return {"server_draft_id":plan["items"][0]["server_draft_id"],
            "workspace_version":plan["workspace_version"],
            "source_sha256":plan["source_sha256"],
            "ack":"CREATE_EPISODE_WITHOUT_START"}


def valid_preflight(record, request, **kwargs):
    return {"authority":"CANONICAL_DRY_RUN","real_preflight_executed":True,
            "status":"PLANNED","admission_granted":False,
            "canonical_episode_created":False,"production_started":False,
            "workspace_id":record["workspace_id"],"workspace_version":record["version"],
            "source_sha256":request["source_sha256"],
            "server_draft_id":request["server_draft_id"]}


def test_default_disabled_and_missing_ack_never_call_creator(tmp_path):
    obj=saved()
    with pytest.raises(BootstrapBlocked,match="EPISODE_BOOTSTRAP_DISABLED"):
        bootstrap_saved_episode(obj,request(obj),root=tmp_path)
    bad=request(obj);bad.pop("ack")
    with pytest.raises(BootstrapBlocked,match="EPISODE_CREATE_ACK_REQUIRED"):
        bootstrap_saved_episode(obj,bad,root=tmp_path,admitted=True)


@pytest.mark.parametrize("key,value",[
    ("workspace_version",2),("source_sha256","0"*64),
    ("server_draft_id","WDE_"+str(uuid4())),("ack","START_PRODUCTION")
])
def test_stale_or_invalid_identity_blocks_before_preflight(tmp_path,key,value):
    obj=saved();req=request(obj);req[key]=value
    with pytest.raises(BootstrapBlocked):
        bootstrap_saved_episode(obj,req,root=tmp_path,admitted=True,
                                dry_run=lambda *args,**kw: pytest.fail("No preflight on stale version"))


@pytest.mark.parametrize("bad",[
    {"status":"HUMAN_GATE_REQUIRED"},
    {"admission_granted":True},
    {"production_started":True},
    {"canonical_episode_created":True},
    {"real_preflight_executed":False},
])
def test_refuse_unapproved_preflight(tmp_path,bad):
    obj=saved()
    def preflight(record,req,**kwargs):
        return {**valid_preflight(record,req),**bad}
    with pytest.raises(BootstrapBlocked,match="EPISODE_PREFLIGHT_NOT_APPROVED"):
        bootstrap_saved_episode(obj,request(obj),root=tmp_path,admitted=True,dry_run=preflight)


def test_bootstrap_calls_only_canonical_creator_once(tmp_path,monkeypatch):
    root=tmp_path
    (root/"episodes"/"_system").mkdir(parents=True)
    (root/"episodes"/"00_独立篇").mkdir()
    monkeypatch.setitem(sys.modules,"story_creator",SimpleNamespace(
        slugify=lambda title:title,
        DEFAULT_STANDALONE_SERIES="00_独立篇"
    ))
    monkeypatch.setitem(sys.modules,"episode_state_persistence",SimpleNamespace(
        authority_mode=lambda:"mysql",list_episode_namespaces=lambda:[]
    ))
    called=[]
    def creator(base,title,source):
        called.append((base,title,source))
        path=root/"episodes"/"00_独立篇"/("12_"+title)
        path.mkdir()
        return path
    obj=saved()
    res=bootstrap_saved_episode(obj,request(obj),root=root,admitted=True,
                                dry_run=valid_preflight,creator=creator)
    assert called==[(root,"全新测试故事","山村里发生了一件重要的事。")]
    assert res["authority"]=="CANONICAL_EPISODE_BOOTSTRAP"
    assert res["canonical_episode_created"] is True
    assert res["production_started"] is False
    assert res["driver_started"] is False
    assert res["requires_production_gate"] is True
    with pytest.raises(BootstrapBlocked,match="EPISODE_TITLE_ALREADY_EXISTS"):
        bootstrap_saved_episode(obj,request(obj),root=root,admitted=True,
                                dry_run=valid_preflight,creator=creator)
    assert len(called)==1


def test_never_create_on_json_mode(tmp_path,monkeypatch):
    (tmp_path/"episodes"/"_system").mkdir(parents=True)
    monkeypatch.setitem(sys.modules,"story_creator",SimpleNamespace(
        slugify=lambda title:title,
        DEFAULT_STANDALONE_SERIES="00_独立篇"
    ))
    monkeypatch.setitem(sys.modules,"episode_state_persistence",SimpleNamespace(
        authority_mode=lambda:"json",list_episode_namespaces=lambda:[]
    ))
    obj=saved()
    with pytest.raises(BootstrapBlocked,match="EPISODE_MYSQL_AUTHORITY_REQUIRED"):
        bootstrap_saved_episode(obj,request(obj),root=tmp_path,admitted=True,
                                dry_run=valid_preflight,creator=lambda *args:pytest.fail("No JSON fallback"))



def test_handoff_displays_already_submitted_source():
    obj=saved()
    did=next(iter(obj["identity_map"]["drafts"].values()))
    obj["identity_map"]["episode_bootstraps"]={did:{"status":"CREATED","namespace":"00_独立篇/13_Test"}}
    plan=compile_handoff_plan(obj)
    item=plan["items"][0]
    assert item["bootstrap_status"]=="CREATED"
    assert item["episode_namespace"]=="00_独立篇/13_Test"
    assert item["preflight_available"] is False
    assert "preflight_argv" not in item
