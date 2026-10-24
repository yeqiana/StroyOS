"""F045 preserved RAW 5.208% ratio deviation is recovered, never regenerated."""
from __future__ import annotations
import json
import sys
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/"episodes/_system"))
import f045_visual_lock_raw_scope as scope
import f045_raw_verified_rc24_rearm as recovery
import image_unknown_raw_reconcile as rawcas
from test_image_unknown_raw_reconcile import evidence,FakeConnection

def test_foreign_episode_or_wrong_frame_never_qualified(tmp_path):
    ep=tmp_path/"episodes"/"00_独立篇"/scope.EPISODE
    item={"frame":45,"id":scope.ITEM_ID,"kind":"original",
          "scope":"visual_lock","status":"external_blocked",
          "technical_failure_code":"ASPECT_RATIO_MISMATCH",
          "frame_contract":{"contract_sha256":scope.CONTRACT_SHA}}
    assert scope.allowed(ep,item) is False
    assert scope.allowed(ep,{**item,"frame":47}) is False
    assert scope.allowed(ep,{**item,"id":"another"}) is False

def test_visual_scope_never_bypasses_only_mysql_receiver_and_original_raw(tmp_path):
    ep,raw,receipt_path,key,gen,receipt,row,plan,old,state,loaded=evidence(tmp_path)
    row.update(scope="visual_lock",frame=45,id=scope.ITEM_ID)
    receipt.update(frame="45")
    with (patch.object(scope,"allowed",return_value=True),
          patch.object(rawcas.legacy,"inspect_item",return_value=plan),
          patch.object(rawcas.provider_receipt_persistence,"load_by_path",return_value=loaded),
          patch.object(rawcas.logical_asset_identity,"frame_asset_key",return_value=key),
          patch.object(rawcas.logical_asset_identity,"episode_id",return_value="episode"),
          patch.object(rawcas.authority,"stable_generation_key",return_value=gen),
          patch.object(rawcas.authority,"load_asset_state",return_value=state),
          patch.object(rawcas.authority,"load_attempt",return_value=old)):
        proof=rawcas.eligible(ep,row)
        assert proof and proof["scope"]=="visual_lock"
        assert proof["attempt_index"]==1
        assert proof["raw_sha256"]==rawcas.sha(raw)
        row["technical_failure_code"]="IMAGE_BACKEND_ERROR"
        assert rawcas.eligible(ep,row) is None
        row["technical_failure_code"]="ASPECT_RATIO_MISMATCH"
        old["status"]="FAILED_AFTER_DISPATCH"
        assert rawcas.eligible(ep,row) is None
        old["status"]="OUTCOME_UNKNOWN"
        raw.write_bytes(b"tampered")
        assert rawcas.eligible(ep,row) is None

def test_mysql_CAS_uses_the_actual_visual_lock_scope(tmp_path):
    ep,raw,receipt_path,key,gen,receipt,row,source,old,state,loaded=evidence(tmp_path)
    output=ep/"media/candidates/scheduled/45-final.png"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"normalized-raw")
    source["generation_key"]=gen
    proof={**source,"scope":"visual_lock","raw_path":raw,
        "asset_key":key,"raw_sha256":rawcas.sha(raw),
        "receipt_legacy_path":loaded["legacy_path"],
        "receipt_id":loaded["receipt_id"],
        "item_id":scope.ITEM_ID,
        "frame_contract_sha256":"c"*64,
        "prompt_package_sha256":"p"*64}
    sha=rawcas.sha(output)
    db=FakeConnection(proof,sha)
    db.attempt["CONTEXT"]=json.dumps({
        "scope":"visual_lock","queue_item_id":scope.ITEM_ID,
        "frame_contract_sha256":"c"*64,"prompt_package_sha256":"p"*64
    })
    proof["receipt_sha256"]=rawcas._receipt_digest(db.receipt)
    with (patch.object(rawcas,"_freeze_three",return_value=nullcontext()),
          patch.object(rawcas.authority,"_connect",return_value=db),
          patch.object(rawcas.authority,"_row",return_value={
              "ATTEMPTS_CONSUMED":1,"ACTIVE_ATTEMPT_INDEX":None,"FENCING_COUNTER":1}),
          patch.object(rawcas.authority,"_episode_id",return_value="episode"),
          patch.object(rawcas.provider_receipt_persistence,"_episode_id",return_value="episode")):
        rawcas._mysql_reconcile(ep,proof,output,sha)
        assert db.writes==1
        db.writes=0
        db.attempt["CONTEXT"]=json.dumps({
            "scope":"batch","queue_item_id":scope.ITEM_ID,
            "frame_contract_sha256":"c"*64,"prompt_package_sha256":"p"*64})
        with pytest.raises(rawcas.PreservedRawDenied,match="UNKNOWN_GENERATION_FENCE_CHANGED"):
            rawcas._mysql_reconcile(ep,proof,output,sha)
        assert db.writes==0

def test_post_restore_exit_requires_canonical_review(tmp_path,monkeypatch):
    ep=recovery.EP
    monkeypatch.setattr(recovery.runtime_driver,"status",lambda *_:{
        "driver_state":"EXITED","liveness":"DEAD","pid":0,"exit_code":"24"})
    monkeypatch.setattr(recovery.baseline,"approved",lambda *_:False)
    with pytest.raises(recovery.RecoveryDenied,match="BASELINE_REVIEW_NOT_APPROVED"):
        recovery.inspect(ep)

def test_retry_never_borrows_f001_image_budget():
    source=(ROOT/"episodes/_system/f045_raw_verified_rc24_rearm.py")
    assert "f001_attempts_consumed" in source.read_text("utf-8")
    code=(ROOT/"episodes/_system/image_unknown_raw_reconcile.py").read_text("utf-8")
    assert "generation_failed_before_candidate_commit" in code
    assert "f045_visual_lock_raw_scope.allowed" in code
