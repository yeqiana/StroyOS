"""F001 independent pass projection preserves old FAILED audit and paid budget."""
from __future__ import annotations
import copy
import sys
from pathlib import Path
import pytest

SYSTEM=Path(__file__).resolve().parents[2]/"episodes"/"_system"
sys.path.insert(0,str(SYSTEM))
import f001_independent_baseline_pass_cas as cas

SHA="a"*64

def documented_source():
    original={"attempt_id":cas.EXPECTED_ORIGINAL_ATTEMPT_ID,
        "result":"success","kind":"original"}
    repair={"attempt_id":cas.EXPECTED_REPAIR_ATTEMPT_ID,
        "result":"technical_failure","kind":"repair",
        "provider_attempt":{"status":"NOT_INVOKED"},
        "error":{"code":"LOGIN_AUTH_IMAGE_TOOL_CAPABILITY_UNKNOWN"}}
    candidate={"kind":"original","sha256":cas.EXPECTED_CANDIDATE_SHA,
               "path":"media/candidates/scheduled/a.png"}
    frame={"status":"TECH_FAILED","current_candidate":candidate,
       "content_repairs_used":1,"approved_asset":None,
       "repair_authorization":{"approval_basis":"delegated_auto_review"},
       "attempts":[{"attempt_id":"a0"},{"attempt_id":"a1"},original,repair],
       "technical_failures":[{"attempt_id":cas.EXPECTED_REPAIR_ATTEMPT_ID}]}
    ledger={"frames":{"01":frame},"canvas":{"width":1080,"height":1350}}
    source={"candidate":candidate,"witness_sha":"b"*64}
    return ledger,source

def test_ledger_recovery_keeps_original_technical_failure(monkeypatch):
    ledger,src=documented_source()
    old=copy.deepcopy(ledger)
    amended=cas.corrected_ledger(ledger,src)
    frame=amended["frames"]["01"]
    assert frame["status"]=="ORIGINAL_READY"
    assert frame["current_candidate"]==old["frames"]["01"]["current_candidate"]
    assert frame["attempts"]==old["frames"]["01"]["attempts"]
    assert frame["technical_failures"]==old["frames"]["01"]["technical_failures"]
    assert frame["content_repairs_used"]==1
    assert frame["approved_asset"] is None
    assert frame["independent_review_reconciliation"]["repair_provider_invoked"] is False
    assert frame["independent_review_reconciliation"]["report_sha256"]=="b"*64
    assert frame["independent_review_reconciliation"]["image_attempts_consumed"]==2
    assert old==ledger

@pytest.mark.parametrize("drift",["not_failed","wrong_candidate","unspent_content","wrong_approval","approved_artifact"])
def test_pure_recovery_drift_denied(drift):
    ledger,source=documented_source()
    f=ledger["frames"]["01"]
    if drift=="not_failed":f["status"]="ORIGINAL_READY"
    if drift=="wrong_candidate":f["current_candidate"]["sha256"]="c"*64
    if drift=="unspent_content":f["content_repairs_used"]=0
    if drift=="wrong_approval":f["repair_authorization"]["approval_basis"]="direct_user_review"
    if drift=="approved_artifact":f["approved_asset"]={"sha256":"d"*64}
    if drift=="wrong_candidate":source["candidate"]={**source["candidate"],"sha256":cas.EXPECTED_CANDIDATE_SHA}
    with pytest.raises(cas.ReviewPassDenied):
        cas.corrected_ledger(ledger,source)

def test_no_user_ack_never_calls_mysql(monkeypatch,tmp_path):
    monkeypatch.setattr(cas,"inspect",lambda *_args,**_kwargs:pytest.fail("inspect without consent"))
    with pytest.raises(cas.ReviewPassDenied,match="ACK_REQUIRED"):
        cas.commit(tmp_path,expected_review_sha=SHA,ack=False)

def test_review_proof_does_not_authorize_more_images():
    ledger,source=documented_source()
    frame=cas.corrected_ledger(ledger,source)["frames"]["01"]
    assert frame["independent_review_reconciliation"]["image_attempts_consumed"]==2
    assert frame["independent_review_reconciliation"]["repair_result_remains"]=="technical_failure"
    assert frame["current_candidate"]["kind"]=="original"
    assert frame["attempts"][-1]["provider_attempt"]["status"]=="NOT_INVOKED"


def test_rc22_rearm_requires_canonical_pass_and_three_dependents(tmp_path,monkeypatch):
    q={"items":[
        {"scope":"visual_lock","kind":"original","frame":i,
         "status":"queued","depends_on":[1]} for i in (5,45,47)]}
    source={"current_status":"PASSED","ep":tmp_path,"queue":q,
        "repair":{"status":"superseded","superseded_review_sha256":"b"*64},
        "witness_sha":"b"*64}
    monkeypatch.setattr(cas,"inspect",lambda *_args,**_kwargs:source)
    monkeypatch.setattr(cas.baseline,"approved",lambda *_:True)
    monkeypatch.setattr(cas.runtime_driver,"status",
                        lambda *_:{"record":{"exit_code":"22"}})
    admitted=cas.verify_rearmed(tmp_path)
    assert admitted["status"]=="VISUAL_LOCK_RC22_F001_INDEPENDENT_PASS_RECOVERABLE"
    assert admitted["paid_attempts_consumed"]==2
    assert admitted["new_paid_attempts"]==0
    assert len(admitted["driver_record_sha256"])==64
    q["items"][0]["depends_on"]=[2]
    with pytest.raises(cas.ReviewPassDenied,match="DEPENDENT_QUEUE_CHANGED"):
        cas.verify_rearmed(tmp_path)


def test_rc22_rearm_never_bypasses_failed_review(tmp_path,monkeypatch):
    source={"current_status":"PASSED","ep":tmp_path,"queue":{"items":[]},
        "repair":{"status":"superseded","superseded_review_sha256":"b"*64},
        "witness_sha":"b"*64}
    monkeypatch.setattr(cas,"inspect",lambda *_args,**_kwargs:source)
    monkeypatch.setattr(cas.baseline,"approved",lambda *_:False)
    with pytest.raises(cas.ReviewPassDenied,match="NOT_PASSED"):
        cas.verify_rearmed(tmp_path)
