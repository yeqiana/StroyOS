"""Transactional three-frame final render persistence keeps all paid gates closed."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"episodes/_system"))
import production_ep14_reviewed_final_mysql_stage as m


@pytest.fixture
def harness(monkeypatch,tmp_path):
    ep=tmp_path/"episode"
    ep.mkdir()
    actual={
        "schema_version":"ep14_render_bundle_queue_stage_v1",
        "state":"STAGED_BLOCKED",
        "production_dispatch_authorized":False,
    }
    q={m.queue_stage.QUEUE_KEY:actual,"items":[],"updated_at":"before"}
    data={"queue":deepcopy(q),"rows":{},"files":{},"writes":0,
          "fail_frame":None,"lock_count":0,"input_reviews":0}
    records=[]
    for f in (9,29,48):
        content={"frame":f"{f:02d}","scene_prompt":f"safe final treatment {f}",
                 "frame_prompt_contract":f"Reviewed camera pose {f}",
                 "postimage_pixel_review_required":True,
                 "production_dispatch_authorized":False}
        rel=f"meta/runtime/prompt-packages/reviewed-final/{f:02d}-test.json"
        ref=m.document_reference(content,rel)
        records.append({
            "frame":f,"id":f"reviewed-{f}",
            "sha":f"{f:064x}","payload":content,
            "reference":ref,
            "projection":m.prompt_package_projection(content,ref),
        })
    import hashlib
    expected=lambda: hashlib.sha256(
        json.dumps(data["queue"],ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    monkeypatch.setattr(m.queue_stage,"_sha",lambda q:hashlib.sha256(
        json.dumps(q,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest())
    def staged(ep):
        data["input_reviews"]+=1
        return {
            "status":"REVIEWED_FINAL_MYSQL_STAGE_ELIGIBLE_NOT_ACTIVATED",
            "expected_queue_sha256":expected(),
            "final_render_bundle_sha256":"a"*64,
            "candidate_bundle_sha256":"b"*64,
            "independent_runner_log_sha256":"c"*64,
            "records":deepcopy(records),
        }
    monkeypatch.setattr(m,"_safe_state",staged)
    monkeypatch.setattr(m.candidates,"_episode_id",lambda ep:"ep14")
    monkeypatch.setattr(m.scheduler_core,"load_queue",lambda ep:deepcopy(data["queue"]))
    @contextmanager
    def lock(ep):
        data["lock_count"]+=1
        try:yield
        finally:data["lock_count"]-=1
    monkeypatch.setattr(m.scheduler_core,"queue_transaction",lock)
    monkeypatch.setattr(m.runtime_workspace,"read_json",
        lambda ep,rel,default=None:deepcopy(data["files"].get(str(rel),default)))
    def write(ep,rel,payload):
        data["files"][str(rel)]=deepcopy(payload)
        data["writes"]+=1
    monkeypatch.setattr(m.runtime_workspace,"write_json",write)
    class DB:
        def close(self):pass
        @contextmanager
        def transaction(self):
            assert data["lock_count"]==1
            old=deepcopy(data["rows"])
            try:yield self
            except Exception:
                data["rows"]=old
                raise
        def execute(self,sql,params):
            assert sql.startswith("INSERT IGNORE INTO TB_PROMPT_PACKAGE ")
            id,epid,frame,kind,sha,content=params
            assert kind==m.PACKAGE_TYPE
            if data["fail_frame"]==frame:raise RuntimeError("mysql insert failure")
            if id in data["rows"]:return 0
            data["rows"][id]={
                "PROMPT_PACKAGE_ID":id,"EPISODE_ID":epid,"FRAME_NO":frame,
                "PACKAGE_TYPE":kind,"SHA256":sha,"PAYLOAD":json.loads(content)}
            return 1
    db=DB()
    class Repo:
        def __init__(self,db):pass
        def get_by_id(self,id):
            return m.MySqlPromptPackageRepository_real_decode(data["rows"].get(id))
    from platform.repository.mysql.mysql_prompt_package_repository import MySqlPromptPackageRepository
    monkeypatch.setattr(m,"MySqlPromptPackageRepository_real_decode",
                        MySqlPromptPackageRepository._decode,raising=False)
    monkeypatch.setattr(m,"MySqlPromptPackageRepository",Repo)
    monkeypatch.setattr(m.candidates,"_open_db",lambda:db)
    return ep,data,records


def submit(ep):
    a=m.plan(ep)
    return m.persist(ep,expected_queue_sha256=a["expected_queue_sha256"],
        expected_final_render_bundle_sha256=a["final_render_bundle_sha256"])


def test_three_reviewed_final_rows_persist_without_activating_queue_or_paid_attempt(harness):
    ep,data,_=harness
    snapshot=deepcopy(data["queue"])
    result=submit(ep)
    assert result["status"]==m.STATUS
    assert result["canonical_activation"] is False
    assert result["production_dispatch_authorized"] is False
    assert result["paid_attempts_reserved"]==0
    assert data["queue"]==snapshot
    assert len(data["rows"])==3 and len(data["files"])==3
    assert all(x["PACKAGE_TYPE"]==m.PACKAGE_TYPE for x in data["rows"].values())
    assert m.verify(ep)["status"]=="VERIFIED_THREE_REVIEWED_FINAL_MYSQL_PACKAGES_NOT_ACTIVATED"


def test_stage_replay_is_idempotent_and_never_rewrites_existing_artifacts(harness):
    ep,data,_=harness
    first=submit(ep)
    rows=deepcopy(data["rows"])
    files=deepcopy(data["files"])
    n=data["writes"]
    assert submit(ep)==first
    assert data["rows"]==rows and data["files"]==files
    assert data["writes"]==n


@pytest.mark.parametrize("case",[
    "queue_moved","incorrect_bundle","db_rollback","db_forged_id",
    "file_collision","postwrite_artifact_removed","stale_queue_after_review",
])
def test_final_review_stage_fails_closed_on_stale_queue_or_forged_rows(harness,monkeypatch,case):
    ep,data,records=harness
    initial=m.plan(ep)
    if case=="queue_moved":
        data["queue"]["updated_at"]="after"
    elif case=="incorrect_bundle":
        initial["final_render_bundle_sha256"]="f"*64
    elif case=="db_rollback":
        data["fail_frame"]=29
    elif case=="db_forged_id":
        x=records[0]
        data["rows"][x["id"]]={
            "PROMPT_PACKAGE_ID":x["id"],"EPISODE_ID":"ep14","FRAME_NO":9,
            "PACKAGE_TYPE":"IMAGE","SHA256":x["sha"],"PAYLOAD":x["projection"],
        }
    elif case=="file_collision":
        data["files"][records[0]["reference"]["rel"]]={"tampered":True}
    elif case=="postwrite_artifact_removed":
        submit(ep)
        data["files"].pop(records[0]["reference"]["rel"])
        with pytest.raises(m.ReviewedStageDenied):
            m.verify(ep)
        return
    elif case=="stale_queue_after_review":
        original=m._safe_state
        def racing(ep):
            x=original(ep)
            data["queue"]["updated_at"]="moved"
            return x
        monkeypatch.setattr(m,"_safe_state",racing)
    rows_before=deepcopy(data["rows"])
    with pytest.raises((m.ReviewedStageDenied,RuntimeError)):
        m.persist(ep,expected_queue_sha256=initial["expected_queue_sha256"],
           expected_final_render_bundle_sha256=initial["final_render_bundle_sha256"])
    assert data["rows"]==rows_before


def test_one_historical_image_row_never_touched(harness):
    ep,data,_=harness
    old={"PROMPT_PACKAGE_ID":"old","EPISODE_ID":"ep14",
         "FRAME_NO":9,"PACKAGE_TYPE":"IMAGE","SHA256":"d"*64,
         "PAYLOAD":{"original":True}}
    data["rows"]["old"]=deepcopy(old)
    submit(ep)
    assert data["rows"]["old"]==old


def test_missing_explicit_cas_denied_before_mysql(harness):
    ep,data,_=harness
    with pytest.raises(m.ReviewedStageDenied,match="EXPLICIT_CAS"):
        m.persist(ep,expected_queue_sha256="",
            expected_final_render_bundle_sha256="a"*64)
    assert data["rows"]=={}
