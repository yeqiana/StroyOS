"""Contract-aware F001 Visual Lock review and no phantom paid repair."""
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"episodes/_system"))
import visual_lock_baseline_gate as baseline
import auto_repair_enqueue as repairs


def contract_fixture(monkeypatch, tmp_path, required=False):
    ep=tmp_path/"episode";ep.mkdir()
    monkeypatch.setattr(baseline,"baseline_frame",lambda ep:1)
    monkeypatch.setattr(baseline,"repo_rel",lambda p:str(p))
    monkeypatch.setattr(baseline.frame_contract,"compile_frame",
                        lambda *_args,**_kwargs:{
                          "contract_sha256":"c"*64,
                          "hash_material":{
                             "capture_event":{"capture_device":"Sony A7S3",
                                "device_position":"windshield forward-facing POV",
                                "framing_constraint":"distant scene view"},
                             "frame_directive":{"required_visual_cues":[
                                "rain-streaked windshield","rockfall blocks the road"]}}})
    monkeypatch.setattr(baseline.character_visual_contract,"pixel_master_required",
                        lambda ep:required)
    monkeypatch.setattr(baseline.character_visual_contract,"load",
                        lambda ep:{"primary_cast_ids":["P01","P02"],"members":{}})
    monkeypatch.setattr(baseline,"prepare_review",
                        lambda ep,force=False:{"asset_path":"x","frame":1})
    monkeypatch.setattr(baseline.local_vision_shadow,"face_hint",lambda ep:"none")
    return ep


@pytest.mark.parametrize("creator",["critic_prompt","codex_critic_prompt"])
def test_no_pixel_master_does_not_invent_faces_or_phone(tmp_path,monkeypatch,creator):
    ep=contract_fixture(monkeypatch,tmp_path,required=False)
    prompt=getattr(baseline,creator)(ep)
    assert "Sony A7S3" in prompt
    assert "rain-streaked windshield" in prompt
    assert "rockfall blocks the road" in prompt
    assert "windshield forward-facing POV" in prompt
    assert "DOES NOT require a Pixel Master" in prompt
    assert "face_boxes=[]" in prompt
    assert '"face_boxes":[]' in prompt
    assert "NEVER invent faces" in prompt
    assert "actual lighting/style" in prompt or "independent photographic/style" in prompt
    assert "ordinary believable phone/photo baseline" not in prompt
    assert "this baseline is also Frame01 Character Identity Anchor evidence" not in prompt


@pytest.mark.parametrize("creator",["critic_prompt","codex_critic_prompt"])
def test_pixel_master_requires_real_primary_faces(tmp_path,monkeypatch,creator):
    ep=contract_fixture(monkeypatch,tmp_path,required=True)
    prompt=getattr(baseline,creator)(ep)
    assert "DOES require a Pixel Master" in prompt
    assert "Every primary cast member" in prompt
    assert "missing required person is a FAIL" in prompt
    assert "Sony A7S3" in prompt
    assert '"face_boxes":[{"character_id":"P01"' in prompt


def test_contract_bound_obligations_readonly_and_exact(tmp_path,monkeypatch):
    ep=contract_fixture(monkeypatch,tmp_path)
    result=baseline.baseline_review_obligations(ep)
    assert result["frame"]==1
    assert result["frame_contract_sha256"]=="c"*64
    assert result["pixel_master_required"] is False
    assert result["framing_constraint"]=="distant scene view"


def budget_fixture(monkeypatch,remaining,active=None):
    import production_ledger_persistence
    import runtime_router
    import generation_attempt_authority as authority
    import logical_asset_identity
    monkeypatch.setattr(runtime_router,"image_execution_runtime",lambda:("CODEX","test"))
    monkeypatch.setattr(production_ledger_persistence,"mode",lambda:"mysql")
    monkeypatch.setattr(logical_asset_identity,"frame_asset_key",lambda ep,frame:f"frame-{frame}")
    reader=Mock(return_value={"remaining_attempts":remaining,
             "attempts_consumed":2-remaining,
             "active_attempt_index":active})
    monkeypatch.setattr(authority,"load_asset_state",reader)
    return reader


def test_zero_real_attempts_exits_before_repair_authorization(tmp_path,monkeypatch):
    reader=budget_fixture(monkeypatch,0)
    monkeypatch.setattr(repairs,"repair_pending",lambda *_:False)
    led=Mock(side_effect=AssertionError("MUST_NOT_MUTATE_LEDGER"))
    monkeypatch.setattr(repairs,"_ledger_frame",led)
    result=repairs.enqueue(tmp_path,frame=1,findings=["style"],source="VISUAL_BASELINE",
                           review_note="missing style")
    assert result["status"]=="NEEDS_USER"
    assert result["reason_code"]=="REAL_IMAGE_ATTEMPT_BUDGET_EXHAUSTED"
    assert result["attempts_consumed"]==2
    assert result["attempts_reserved"]==0 and result["model_calls"]==0
    reader.assert_called_once()
    led.assert_not_called()


@pytest.mark.parametrize("remaining,active,expected",[
    (1,None,None),(0,1,"GENERATION_ATTEMPT_STILL_ACTIVE"),
    (1,1,"GENERATION_ATTEMPT_STILL_ACTIVE")])
def test_budget_gate_nonexhausted_and_active(tmp_path,monkeypatch,remaining,active,expected):
    budget_fixture(monkeypatch,remaining,active)
    result=repairs._native_real_attempt_budget_preflight(tmp_path,1)
    assert (result or {}).get("reason_code")==expected


def test_mysql_budget_unavailable_fails_closed(tmp_path,monkeypatch):
    reader=budget_fixture(monkeypatch,1)
    reader.side_effect=ConnectionError("lost MySQL")
    result=repairs._native_real_attempt_budget_preflight(tmp_path,1)
    assert result["status"]=="BLOCKED"
    assert result["reason_code"]=="GENERATION_ATTEMPT_AUTHORITY_UNVERIFIED"
    assert result["attempts_reserved"]==0


def test_non_native_or_non_mysql_does_not_invent_mysql_budget(tmp_path,monkeypatch):
    reader=budget_fixture(monkeypatch,0)
    import runtime_router,production_ledger_persistence
    monkeypatch.setattr(runtime_router,"image_execution_runtime",
                        lambda:("PRODUCT_RUNTIME","test"))
    assert repairs._native_real_attempt_budget_preflight(tmp_path,1) is None
    monkeypatch.setattr(runtime_router,"image_execution_runtime",lambda:("CODEX","test"))
    monkeypatch.setattr(production_ledger_persistence,"mode",lambda:"json")
    assert repairs._native_real_attempt_budget_preflight(tmp_path,1) is None
    reader.assert_not_called()
