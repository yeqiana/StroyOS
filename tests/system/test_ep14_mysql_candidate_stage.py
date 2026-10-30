"""Three reviewed EP14 render candidates persist atomically and cannot dispatch."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "episodes/_system"))
import production_ep14_mysql_candidate_stage as m


def sha(s):
    return hashlib.sha256(s.encode("utf8")).hexdigest()


@pytest.fixture
def env(monkeypatch, tmp_path):
    import production_ep14_render_queue_stage as qstage
    import scheduler_core
    ep = tmp_path / "episode"
    ep.mkdir()
    marker = {
        "state": "STAGED_BLOCKED", "bundle_sha256": sha("bundle"),
        "binding_sha256": sha("staged"),
        "production_dispatch_authorized": False,
        "canonical_prompt_packages_activated": False,
    }
    items = [{"frame": f, "scope": "batch", "id": f"item-{f}", "status": "external_blocked"}
             for f in (9, 29, 48)]
    queue = {qstage.QUEUE_KEY: marker, "items": items, "updated_at": "unchanged"}
    data = {"q": deepcopy(queue), "rows": {}, "artifacts": {}, "writes": 0, "queries": 0,
            "fail_insert": None}
    monkeypatch.setattr(qstage, "_queue_rows",
                        lambda q: {r["frame"]: r for r in q["items"] if r["frame"] in (9,29,48)})
    def preview(ep, item):
        f = item["frame"]
        package = {
            "frame": f"{f:02d}",
            "package_sha256": sha(f"package-{f}"),
            "frame_contract_sha256": sha(f"original-contract-{f}"),
            "scene_prompt": "SAFE IMAGE RENDER " + str(f) + " " * 200,
            "scene_prompt_sha256": sha(f"safe-scene-{f}"),
            "frame_prompt_contract": "SAFE RENDER TREATMENT",
            "render_variant_sha256": sha(f"variant-{f}"),
            "storyboard_source": {"sha256":sha(f"original-story-{f}"),
                "render_original_text_injected": False},
            "canonical_activation": False,
            "production_dispatch_authorized": False,
            "canonical_prompt_package_written": False,
        }
        return {"stage_binding_sha256": marker["binding_sha256"],
                "bundle_sha256": marker["bundle_sha256"],
                "production_dispatch_authorized": False,
                "source": package, "package_sha256": package["package_sha256"]}
    monkeypatch.setattr(qstage,"preview_worker_source",preview)
    monkeypatch.setattr(scheduler_core,"load_queue",lambda ep: deepcopy(data["q"]))
    @contextmanager
    def lock(ep):
        yield
    monkeypatch.setattr(scheduler_core,"queue_transaction",lock)
    monkeypatch.setattr(m.runtime_workspace,"read_json",
                        lambda ep,rel,default=None: deepcopy(data["artifacts"].get(str(rel),default)))
    def write(ep,rel,payload):
        data["artifacts"][str(rel)]=deepcopy(payload)
        data["writes"]+=1
        return tmp_path / str(rel)
    monkeypatch.setattr(m.runtime_workspace,"write_json",write)
    monkeypatch.setattr(m, "_episode_id", lambda ep: "00_独立篇/14_深渊疗愈所_第一集_净土生命还原")
    class Conn:
        def close(self): pass
        @contextmanager
        def transaction(self):
            before=deepcopy(data["rows"])
            try:
                yield self
            except Exception:
                data["rows"]=before
                raise
        def execute(self, sql,params):
            assert sql.startswith("INSERT IGNORE INTO TB_PROMPT_PACKAGE ")
            identity, episode, frame, kind, package_sha, payload = params
            assert kind == m.PACKAGE_TYPE
            if data["fail_insert"] == frame:
                raise RuntimeError("simulated mysql insert failure")
            import json
            if identity in data["rows"]: return 0
            data["rows"][identity]={"PROMPT_PACKAGE_ID":identity,"EPISODE_ID":episode,
                "FRAME_NO":frame,"PACKAGE_TYPE":kind,"SHA256":package_sha,
                "PAYLOAD":json.loads(payload)}
            return 1
    connection=Conn()
    class Repo:
        def __init__(self,conn): pass
        def get_by_id(self,id):
            import platform.repository.mysql.mysql_prompt_package_repository as repository
            return repository.MySqlPromptPackageRepository._decode(data["rows"].get(id))
    monkeypatch.setattr(m, "_open_db", lambda:connection)
    monkeypatch.setattr(m, "MySqlPromptPackageRepository", Repo)
    return ep,data,marker


def submit(ep):
    plan=m.plan(ep)
    return m.persist(ep,expected_queue_sha256=plan["expected_queue_sha256"],
                     expected_bundle_sha256=plan["bundle_sha256"])


def test_mysql_candidates_are_three_atomic_immutable_rows_without_queue_activation(env):
    ep,data,marker=env
    planned=m.plan(ep)
    assert planned["status"]=="READY_TO_PERSIST_NONCANONICAL_CANDIDATES"
    assert len(planned["candidate_ids"])==3
    assert not data["rows"] and not data["artifacts"]
    previous=deepcopy(data["q"])
    r=submit(ep)
    assert r["status"]==m.STATUS
    assert len(data["rows"])==3
    assert len(data["artifacts"])==3
    assert r["candidate_ids"]==planned["candidate_ids"]
    assert data["q"]==previous
    assert r["production_dispatch_authorized"] is False
    assert r["canonical_render_activated"] is False
    assert all(x["PACKAGE_TYPE"]==m.PACKAGE_TYPE for x in data["rows"].values())
    assert all(x["PAYLOAD"]["projection_type"]=="PROMPT_PACKAGE_REF" for x in data["rows"].values())
    assert all(x["PAYLOAD"]["document"]["sha256"] in [m.payload_sha256(a) for a in data["artifacts"].values()]
               for x in data["rows"].values())
    assert m.verify(ep)["status"]=="VERIFIED_THREE_MYSQL_CANDIDATES_NOT_ACTIVATED"


def test_replaying_same_candidate_bundle_does_not_rewrite_persisted_rows(env):
    ep,data,_=env
    one=submit(ep)
    rows=deepcopy(data["rows"])
    files=deepcopy(data["artifacts"])
    writes=data["writes"]
    two=submit(ep)
    assert two==one
    assert data["rows"]==rows
    assert data["artifacts"]==files
    assert data["writes"]==writes


@pytest.mark.parametrize("drift", [
    "queue", "bundle", "partial_db", "artifact", "collision",
    "missing_artifact", "transaction_fail", "unsupported_frame",
    "false_approval", "original_text_leak",
])
def test_stale_or_forged_candidates_fail_closed(env, monkeypatch, drift):
    ep,data,marker=env
    planned=m.plan(ep)
    if drift == "queue":
        data["q"]["updated_at"]="changed"
    elif drift == "bundle":
        planned["bundle_sha256"]="1"*64
    elif drift == "partial_db":
        original_open=m._open_db
        # One previously-staged row with a forged payload causes rollback.
        plan=m._candidate_plan(ep,data["q"])
        rec=plan["records"][0]
        data["rows"][rec["id"]]={"PROMPT_PACKAGE_ID":rec["id"],"EPISODE_ID":m._episode_id(ep),
            "FRAME_NO":9,"PACKAGE_TYPE":m.PACKAGE_TYPE,"SHA256":"0"*64,
            "PAYLOAD":{"forged":True}}
    elif drift == "artifact":
        plan=m._candidate_plan(ep,data["q"])
        rec=plan["records"][0]
        data["artifacts"][rec["reference"]["rel"]]={"forged":True}
    elif drift == "collision":
        plan=m._candidate_plan(ep,data["q"])
        rec=plan["records"][0]
        data["rows"][rec["id"]]={"PROMPT_PACKAGE_ID":rec["id"],"EPISODE_ID":m._episode_id(ep),
            "FRAME_NO":9,"PACKAGE_TYPE":"IMAGE","SHA256":rec["sha"],"PAYLOAD":rec["projection"]}
    elif drift == "missing_artifact":
        # Stage, then remove one artifact and check verifier rejects.
        submit(ep)
        data["artifacts"].pop(next(iter(data["artifacts"])))
        with pytest.raises(m.CandidateDenied):
            m.verify(ep)
        return
    elif drift == "transaction_fail":
        data["fail_insert"]=29
    elif drift == "unsupported_frame":
        data["q"]["items"][2]["frame"]=40
    elif drift == "false_approval":
        data["q"][m.queue_stage.QUEUE_KEY]["production_dispatch_authorized"]=True
    elif drift == "original_text_leak":
        old=m.queue_stage.preview_worker_source
        def leak(ep,item):
            v=old(ep,item)
            v["source"]["storyboard_source"]["text"]="OLD UNSAFE STORY"
            return v
        monkeypatch.setattr(m.queue_stage,"preview_worker_source",leak)
    before_rows=deepcopy(data["rows"])
    before_queue=deepcopy(data["q"])
    with pytest.raises((m.CandidateDenied,ValueError,KeyError,RuntimeError)):
        m.persist(ep,expected_queue_sha256=planned["expected_queue_sha256"],
                  expected_bundle_sha256=planned["bundle_sha256"])
    assert data["rows"]==before_rows
    assert data["q"] == before_queue  # a forged queue is never silently repaired by a failed write


def test_existing_image_type_records_are_not_touched(env):
    ep,data,_=env
    original={"PROMPT_PACKAGE_ID":"old-image","EPISODE_ID":m._episode_id(ep),
              "FRAME_NO":9,"PACKAGE_TYPE":"IMAGE","SHA256":"a"*64,
              "PAYLOAD":{"historical":True}}
    data["rows"]["old-image"]=deepcopy(original)
    submit(ep)
    assert data["rows"]["old-image"]==original
