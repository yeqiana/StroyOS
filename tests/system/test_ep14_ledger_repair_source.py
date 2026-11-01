"""EP14 Ledger consumes only the canonical reviewed scene, never old prompt."""
from __future__ import annotations
import hashlib
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"episodes/_system"))
import scheduler_core as core
import ledger_call
import frame_contract
import prompt_package
import production_ep14_canonical_activation as active


def item(scene: str):
    return {
        "id":"f009-new-repair","frame":9,"kind":"repair","scope":"batch",
        "status":"queued","ep14_active_package_id":"PP_approved",
        "prompt_file":"prompts/old-provider-denied.txt",
        "capture_id":"reviewed-09","model":"gpt-image-2.5-flare",
        "quality":"high","references":[],
        "prompt_package":{"scene_prompt_sha256":
            hashlib.sha256(scene.encode("utf-8")).hexdigest()},
    }


def test_ledger_uses_reviewed_scene_instead_of_old_denied_prompt(monkeypatch):
    scene="Safe, independently approved photographic treatment for frame nine."
    row=item(scene)
    capture={}
    monkeypatch.setattr(active,"load_for_dispatch",lambda ep,r:{"scene_prompt":scene})
    monkeypatch.setattr(frame_contract,"required",lambda ep:True)
    def reject_old(*args,**kwargs):
        raise AssertionError("old rejected prompt must never be recompiled")
    monkeypatch.setattr(prompt_package,"compile_frame",reject_old)
    def ledger_mock(ep,**kwargs):
        capture.update(kwargs)
        return True,"LEDGER_BEGIN_OK"
    monkeypatch.setattr(ledger_call,"begin",ledger_mock)
    ok,message=core.ledger_begin(Path("ep14"),row)
    assert ok is True
    assert message=="LEDGER_BEGIN_OK"
    assert capture["reviewed_scene_prompt"]==scene
    assert capture["kind"]=="repair"
    assert capture["prompt_file"].name=="old-provider-denied.txt"


@pytest.mark.parametrize("scene",["tampered","",123,None])
def test_wrong_sha_or_missing_review_is_rejected_before_ledger(monkeypatch,scene):
    row=item("approved")
    monkeypatch.setattr(active,"load_for_dispatch",lambda ep,r:{"scene_prompt":scene})
    def ledger_must_not_run(*args,**kwargs):
        raise AssertionError("ledger called without exact reviewed scene SHA")
    monkeypatch.setattr(ledger_call,"begin",ledger_must_not_run)
    ok,message=core.ledger_begin(Path("ep14"),row)
    assert ok is False
    assert message=="EP14_REVIEWED_LEDGER_SCENE_SHA_NOT_AUTHORIZED"


def test_review_authority_missing_cannot_fall_back_to_old_file(monkeypatch):
    row=item("approved")
    def reject(ep,row):
        raise active.ActivationDenied("MYSQL_ACTIVE_SHA_MISMATCH")
    monkeypatch.setattr(active,"load_for_dispatch",reject)
    monkeypatch.setattr(ledger_call,"begin",lambda *a,**kw:
                        (_ for _ in ()).throw(AssertionError("ledger bypass")))
    ok,message=core.ledger_begin(Path("ep14"),row)
    assert ok is False
    assert "EP14_REVIEWED_LEDGER_BINDING_DENIED" in message


def test_ledger_bridge_selects_reviewed_text_without_file(monkeypatch):
    seen={}
    def mock(fn,ns):
        seen["prompt"]=ns.prompt
        seen["prompt_file"]=ns.prompt_file
        seen["long"]=ns.allow_long_prompt
        return True,"LEDGER_STARTED"
    monkeypatch.setattr(ledger_call,"_invoke",mock)
    from pathlib import Path
    args=dict(ep=Path("episode"),frame=9,kind="repair",
              prompt_file=Path("old-refused.txt"),capture_id="approved09",
              model="gpt-image-2.5-flare",quality="high")
    assert ledger_call.begin(**args,reviewed_scene_prompt="reviewed final scene")==(True,"LEDGER_STARTED")
    assert seen=={"prompt":"reviewed final scene","prompt_file":None,"long":True}
    ledger_call.begin(**args)
    assert seen["prompt"] is None and seen["prompt_file"] is not None
    assert seen["long"] is False


def test_non_ep14_original_source_binding_stays_strict(monkeypatch):
    row=item("new approved")
    row.pop("ep14_active_package_id")
    row["kind"]="original"
    row["frame_contract"]={"contract_sha256":"original"}
    monkeypatch.setattr(frame_contract,"required",lambda ep:True)
    monkeypatch.setattr(prompt_package,"compile_frame",lambda *a,**kw:{
        "frame_contract_sha256":"original",
        "scene_prompt_sha256":"different"})
    monkeypatch.setattr(ledger_call,"begin",lambda *a,**kw:
                        (_ for _ in ()).throw(AssertionError("ledger bypass")))
    ok,reason=core.ledger_begin(Path("episode"),row)
    assert not ok and "PROMPT_SOURCE_DRIFT" in reason
