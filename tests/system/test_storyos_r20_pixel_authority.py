"""R20 independent four-slot checks, no model and no production image."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import sys
import pytest
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/"scripts"),str(ROOT/"episodes/_system")]
import storyos_a9_receipt_reconcile as a9
import storyos_codex_managed as native
import storyos_m00_native_evidence_readonly as image_evidence
import story_review_a11_source_repair as a11

def test_a11_verified_mysql_pass_supersedes_a9_timeout_but_not_history(tmp_path,monkeypatch):
    ep=tmp_path/"episodes"/"fixture"
    ticket=ep/"meta/runtime/story-review-migrated-rubric-a9.json"
    ticket.parent.mkdir(parents=True)
    ticket.write_text(json.dumps({
        "schema":"storyos.story_review_migrated_rubric_epoch.v1",
        "global_review_attempt":9,
        "review_scope":a9.migration.REVIEW_SCOPE
    }))
    p={"attempt":11,"review_scope":a11.REVIEW_SCOPE}
    monkeypatch.setattr(a9.review,"load_review",lambda _:{"critic_provenance":p,"summary":{"passed":True}})
    monkeypatch.setattr(a9.review,"verify",lambda _:[])
    monkeypatch.setattr(a11,"validate_epoch",lambda ep,prov:True)
    result=a9.inspect(ep,root=tmp_path)
    assert result["status"]=="CANONICAL_A11_PASS_VERIFIED"
    assert result["may_start_driver"] is True
    assert result["can_dispatch_image"] is False
    assert result["may_retry_attempt_9"] is False
    monkeypatch.setattr(a11,"validate_epoch",lambda ep,prov:False)
    denied=a9.inspect(ep,root=tmp_path)
    assert not denied["may_start_driver"]
    assert denied["status"]!="CANONICAL_A11_PASS_VERIFIED"

def test_a11_validated_driver_preflight_does_not_claim_image_ready(tmp_path,monkeypatch):
    ep=tmp_path/"episodes"/"fixture"
    ticket=ep/"meta/runtime/story-review-migrated-rubric-a9.json"
    ticket.parent.mkdir(parents=True)
    ticket.write_text("{}")
    monkeypatch.setattr(native,"ROOT",tmp_path)
    def probe(env,script,args,**kwargs):
        if script.endswith("runtime_router.py"):
            return 0,{"effective_production_mode":"CODEX_MANAGED","effective_runtime":"CODEX",
                "image_execution_runtime":"CODEX","local_codex_spawn_allowed":True,
                "local_codex_image_spawn_allowed":True,"text_review_runtime":"CODEX",
                "vision_review_runtime":"CODEX","governance_review_runtime":"CODEX"}
        if script.endswith("codex_user_runner.py"):return 0,{"status":"ok","codex_available":True,"codex_auth_present":True}
        if script.endswith("storyos_native_model_readiness.py"):return 0,{"status":"CLIENT_VERSION_COMPATIBLE"}
        if script.endswith("storyos_revision_schema_readonly.py"):return 0,{"status":"READY_FOR_FURTHER_ADMISSION"}
        if script.endswith("storyos_episode_stage_readonly.py"):return 0,{"status":"STAGE_ELIGIBLE","stage":"STORYBOARD_LOCKED","source":"mysql"}
        if script.endswith("storyos_attempt_readonly_preflight.py"):return 0,{"status":"ATTEMPT_HISTORY_READ_ONLY"}
        if script.endswith("runtime_driver.py"):return 0,{"driver_state":"NEVER_STARTED","liveness":"DEAD"}
        if script.endswith("storyos_visual_lock_readonly.py"):return 0,{"status":"BLOCKED","reason":"REAL_NATIVE_IMAGE_PIXEL_PROOF_NOT_YET_ESTABLISHED"}
        if script.endswith("storyos_a9_receipt_reconcile.py"):return 0,{"status":"CANONICAL_A11_PASS_VERIFIED"}
        if script.endswith("storyos_m00_native_evidence_readonly.py"):return 0,{
          "status":"NATIVE_TEST_ONLY_PIXELS_VERIFIED","production_authorization":False}
        return 2,{}
    monkeypatch.setattr(native,"_probe",probe)
    r=native.preflight({"STORYOS_MYSQL_HOST":"127.0.0.1",
         "STORYOS_MYSQL_PORT":"3306"},episode=ep)
    assert r["status"]=="READY_TO_START"
    assert r["blockers"]==[]
    assert r["production_admission"]["dag_startable"] is True
    assert r["production_admission"]["image_ready"] is False
    assert r["production_admission"]["production_authorization"] is False

def test_pixel_test_receipt_sha_native_but_never_grants_production(tmp_path):
    from PIL import Image
    import m00_calibration_receipts
    base=tmp_path/".storyos/user-visual-references/test-only-calibration"
    for case in ("C02-R2","C04-R2"):
        out=base/case
        out.mkdir(parents=True)
        img=out/"generated.png"
        Image.new("RGB",(600,750)).save(img)
        identity={"test_only":True,"case":case}
        fp=hashlib.sha256(json.dumps(identity,sort_keys=True,ensure_ascii=False,
            separators=(",",":")).encode()).hexdigest()
        row={"frame":case,"status":"IMAGE_CREATED",
            "output":(out/"generated.png").as_posix(),
            "output_sha256":hashlib.sha256(img.read_bytes()).hexdigest(),
            "dimensions":[600,750],"codex_returncode":0,
            "request_identity":identity,"request_fingerprint":fp,
            "mock":{"authority":"TEST_ONLY_LOCAL","production_authority":False,
                    "mysql_attempt":False,"episode_authority":False},
            "runner_transport":{"transport_route":"native_codex"},
            "model_requested":"gpt-image-2.5-flare"}
        (out/"test-only-record.json").write_text(json.dumps(row))
    r=image_evidence.inspect(root=tmp_path)
    assert r["status"]=="NATIVE_TEST_ONLY_PIXELS_VERIFIED"
    assert r["verified_image_count"]==2
    assert r["model_entitlement_verified"] is False
    assert r["production_authorization"] is False
    assert r["can_dispatch_image"] is False
    (base/"C02-R2"/"generated.png").write_bytes(b"bad")
    assert image_evidence.inspect(root=tmp_path)["status"]=="IMAGE_TEST_PROOF_INCOMPLETE"

def test_frame01_cannot_borrow_m00_test_pixels_as_attempt():
    from storyos_autonomy_canary import decide_new_frame01
    baseline={"episode":"episodes/fixture","status":"READY_TO_START",
        "read_only":True,"production_authorization":False,
        "model_calls":0,"sql_writes":0,"image_executor":"CODEX",
        "production_mode":"CODEX_MANAGED","blockers":[],
        "episode_stage":{"source":"mysql","current_state":"STORYBOARD_LOCKED"},
        "attempt":{"status":"ATTEMPT_HISTORY_READ_ONLY",
                   "active_attempt_assets":[],"outcome_unknown_assets":[]},
        "codex":{"mode_ok":True,"bridge_ok":True,"model_client_version_ok":True},
        "visual_lock_admission":{"read_only":True,"status":"BLOCKED",
              "reason":"REAL_NATIVE_IMAGE_PIXEL_PROOF_NOT_YET_ESTABLISHED"},
        "test_only_native_pixel_evidence":{"status":"NATIVE_TEST_ONLY_PIXELS_VERIFIED",
                       "production_authorization":False}}
    canary=decide_new_frame01(baseline,episode="episodes/fixture")
    assert canary["status"]=="BLOCKED"
    assert canary["can_dispatch_image"] is False
    assert canary["production_authorization"] is False
