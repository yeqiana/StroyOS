"""EP14 final F009 second-Attempt RAW salvage is exact-SHA and no-crop only."""
from __future__ import annotations

from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
import hashlib
import sys

from PIL import Image
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/"episodes/_system"))
import production_ep14_f009_preserved_raw as rescue


def _raw(tmp_path,monkeypatch):
    ep=tmp_path/"episodes"/"00_独立篇"/rescue.EPISODE_NAME
    src=ep/"media/raw/09-real.png"
    src.parent.mkdir(parents=True)
    # Distinguishable left/right/top/bottom pixels reveal cropping.
    im=Image.new("RGB",rescue.RAW_SIZE,(60,110,150))
    for y in range(40):
        for x in range(rescue.RAW_SIZE[0]):
            im.putpixel((x,y),(220,20,20))
            im.putpixel((x,rescue.RAW_SIZE[1]-1-y),(20,220,20))
    im.save(src,"PNG")
    sha=hashlib.sha256(src.read_bytes()).hexdigest()
    monkeypatch.setattr(rescue,"RAW_SHA",sha)
    return ep,src,sha


def _proof(monkeypatch,ep,src,sha):
    row={"id":rescue.PILOT_ITEM_ID,"frame":9,"kind":"repair",
         "scope":"batch","status":"external_blocked",
         "technical_failure_code":"ASPECT_RATIO_MISMATCH",
         "last_error":"ASPECT_RATIO_MISMATCH: original provider canvas"}
    held=[{"frame":f,"scope":"batch","kind":"repair","status":"pilot_hold"}
          for f in (29,48)]
    package={"package_sha256":"a"*64,"frame_contract_sha256":"b"*64,
             "independent_preimage_text_approved":True,
             "postimage_pixel_review_required":True}
    q={"items":[row,*held]}
    monkeypatch.setattr(rescue.scheduler_core,"load_queue",lambda ep:q)
    monkeypatch.setattr(rescue.activation,"load_for_dispatch",
       lambda ep,item,for_raw_recovery=False:package if for_raw_recovery else None)
    target=ep/"media/candidates/scheduled"/f"09-{rescue.PILOT_ITEM_ID}-a2.png"
    rpath=ep/"meta/provider-receipts/09-provider.json"
    legacy={"auto_resolvable":True,"code":"ASPECT_RATIO_MISMATCH",
            "ratio_delta":0.052083333,"raw_path":str(src),
            "output_path":str(target),"provider_receipt":str(rpath),
            "transaction_id":"tx9"}
    monkeypatch.setattr(rescue.legacy,"inspect_item",lambda ep,item:legacy)
    monkeypatch.setattr(rescue.canvas_normalize,"read_canvas",
                        lambda ep:(1080,1350,"4:5"))
    key="episode/frame-09"
    gen="ga1-"+"a"*48+"-a2"
    receipt={"frame":"09","generation_key":gen,"attempt_index":2,
             "fencing_token":2,"request_id":"f"*32,
             "generation_route":"codex_subscription",
             "payload_model":"gpt-image-2.5-flare","payload_quality":"high",
             "normalize_decision":"ASPECT_RATIO_MISMATCH",
             "raw_sha256":sha,"prompt_package_sha256":"a"*64,
             "frame_contract_sha256":"b"*64,
             "requested_canvas":{"width":1080,"height":1350},
             "exact_raw_canvas_guaranteed":False}
    loaded={"source":"mysql","receipt_id":"PR_real","legacy_path":"relative",
            "receipt_status":"RECORDED","payload":receipt}
    monkeypatch.setattr(rescue.unknown,"_receipt",lambda ep,item,e:(rpath,receipt,loaded))
    monkeypatch.setattr(rescue.identity,"frame_asset_key",lambda ep,f:key)
    monkeypatch.setattr(rescue.identity,"episode_id",lambda ep:"episode")
    monkeypatch.setattr(rescue.authority,"stable_generation_key",lambda ep,key,n:gen)
    state={"attempts_consumed":2,"fencing_counter":2,"active_attempt_index":None}
    monkeypatch.setattr(rescue.authority,"load_asset_state",lambda ep,key:state)
    prior={"status":"FAILED_AFTER_DISPATCH",
           "failure_class":"IMAGE_PROVIDER_SAFETY_REJECTED"}
    second={"status":"OUTCOME_UNKNOWN",
            "failure_class":"generation_failed_before_candidate_commit",
            "provider":"codex_subscription",
            "generation_key":gen,"result_ref":None,
            "dispatch_committed_at":"now","generation_observed_at":"now",
            "runner_request_id":"f"*32,
            "payload_model":"gpt-image-2.5-flare","payload_quality":"high"}
    monkeypatch.setattr(rescue.authority,"load_attempt",
                        lambda ep,key,n: prior if n==1 else second)
    return q,row,held,package,legacy,receipt,loaded,state,prior,second


def test_noncrop_fit_keeps_full_image_and_original_sha(tmp_path,monkeypatch):
    ep,src,sha=_raw(tmp_path,monkeypatch)
    dst=ep/"media/candidates/scheduled/09-final.png"
    result=rescue._normalize_no_crop(src,dst)
    assert result["crop_applied"] is False
    assert result["policy"]==rescue.POLICY
    assert result["padding"]=={"left":28,"right":28,"top":0,"bottom":0}
    with Image.open(src) as original, Image.open(dst) as output:
        assert output.format=="PNG" and output.size==(1080,1350)
        assert output.getpixel((28,0))[0]>180
        assert output.getpixel((28,1349))[1]>180
        assert output.getpixel((0,0))==output.getpixel((28,0))
        assert output.getpixel((1079,1349))==output.getpixel((1051,1349))
    assert hashlib.sha256(src.read_bytes()).hexdigest()==sha
    with pytest.raises(rescue.RecoveryDenied,match="OUTPUT_ALREADY_EXISTS"):
        rescue._normalize_no_crop(src,dst)


def test_real_shape_without_mysql_proof_cannot_enter_recovery(tmp_path,monkeypatch):
    ep,src,sha=_raw(tmp_path,monkeypatch)
    q,row,held,package,legacy,receipt,loaded,state,prior,second=_proof(monkeypatch,ep,src,sha)
    plan=rescue.inspect(ep)
    assert plan["result"]=="F009_VERIFIED_RAW_NONCROP_RECOVERY_ELIGIBLE"
    assert plan["attempt_index"]==2 and plan["raw_sha256"]==sha
    assert plan["postimage_pixel_review_required"] is True
    assert plan["paid_attempts_reserved"]==0
    # A different first failure, forged render, altered RAW or already resumed
    # paid Attempt must not be accepted as the second approved repair frame.
    prior["failure_class"]="TIMEOUT"
    with pytest.raises(rescue.RecoveryDenied):rescue.inspect(ep)
    prior["failure_class"]="IMAGE_PROVIDER_SAFETY_REJECTED"
    package["package_sha256"]="b"*64
    with pytest.raises(rescue.RecoveryDenied):rescue.inspect(ep)
    package["package_sha256"]="a"*64
    state["active_attempt_index"]=2
    with pytest.raises(rescue.RecoveryDenied):rescue.inspect(ep)
    state["active_attempt_index"]=None
    receipt["raw_sha256"]="0"*64
    with pytest.raises(rescue.RecoveryDenied):rescue.inspect(ep)


def test_only_f009_reviewed_repair_may_recover(tmp_path,monkeypatch):
    ep,src,sha=_raw(tmp_path,monkeypatch)
    q,row,held,package,legacy,receipt,loaded,state,prior,second=_proof(monkeypatch,ep,src,sha)
    for status in ("queued","pilot_hold","blocked","generated"):
        row["status"]=status
        with pytest.raises(rescue.RecoveryDenied):rescue.inspect(ep)
    row["status"]="external_blocked"
    row["kind"]="original"
    with pytest.raises(rescue.RecoveryDenied):rescue.inspect(ep)
    row["kind"]="repair"
    held[0]["status"]="queued"
    with pytest.raises(rescue.RecoveryDenied):rescue.inspect(ep)


def test_provider_sha_drift_prevents_noncrop_output(tmp_path,monkeypatch):
    ep,src,sha=_raw(tmp_path,monkeypatch)
    src.write_bytes(b"tampered")
    with pytest.raises(rescue.RecoveryDenied,match="RAW_CHANGED"):
        rescue._normalize_no_crop(src,ep/"out.png")


def test_recover_preserves_pilot_holds_and_never_calls_provider(tmp_path,monkeypatch):
    ep,src,sha=_raw(tmp_path,monkeypatch)
    q,row,held,package,legacy,receipt,loaded,state,prior,second=_proof(monkeypatch,ep,src,sha)
    plan=rescue.inspect(ep)
    monkeypatch.setattr(rescue,"inspect",lambda ep:plan)
    monkeypatch.setattr(rescue.scheduler_core,"queue_transaction",lambda ep:nullcontext())
    trace=[]
    monkeypatch.setattr(rescue.provider_capability,"finalize_receipt",
                        lambda path,operation,output:trace.append("receipt"))
    monkeypatch.setattr(rescue.receipts,"load_by_path",lambda ep,path:{
       **loaded,"receipt_status":"FINALIZED",
       "payload":{**receipt,"release_canvas":{"sha256":"canary"}}})
    def sql(ep,plan,output,sha):
        assert Path(output).is_file()
        assert plan["attempt_index"]==2 and plan["item_id"]==rescue.PILOT_ITEM_ID
        assert plan["receipt_sha256"]
        trace.append("mysql_succeeded")
    monkeypatch.setattr(rescue.unknown,"_mysql_reconcile",sql)
    monkeypatch.setattr(rescue.production_ledger,"cmd_recover_success",
                        lambda args:trace.append("ledger_corrected"))
    monkeypatch.setattr(rescue.production_recovery,"mark_terminal",
                        lambda *args,**kwargs:trace.append("terminal"))
    monkeypatch.setattr(rescue.production_recovery,"now",lambda:"now")
    monkeypatch.setattr(rescue.scheduler_core,"save_queue",
                        lambda ep,q:trace.append("queue_committed"))
    # A test episode outside the repository cannot be repo_relative; scope it
    # to the mock root while keeping the immutability and MySQL evidence gates.
    monkeypatch.setattr(rescue.unknown,"ROOT",tmp_path)
    result=rescue.recover(ep)
    assert result["status"]=="PASS"
    assert result["crop_applied"] is False
    assert result["pixel_review_completed"] is False
    assert result["image_calls"]==0
    assert row["status"]=="generated"
    assert [x["status"] for x in held]==["pilot_hold","pilot_hold"]
    assert trace==["receipt","mysql_succeeded","ledger_corrected","terminal","queue_committed"]
