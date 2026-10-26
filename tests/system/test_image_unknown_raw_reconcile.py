"""Permanent offline regression for native provider RAW + MySQL UNKNOWN CAS.

No paid image calls, real MySQL, persistent Episode files, or Codex credentials.
"""
import copy
import hashlib
import json
import sys
from contextlib import contextmanager, nullcontext
from pathlib import Path
from unittest.mock import patch
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/"episodes/_system"))
import image_unknown_raw_reconcile as recovery


def evidence(tmp_path):
    ep=tmp_path/"episodes"/"00_独立篇"/"13_失物归还的那扇门"
    raw=ep/"media/raw/11-image.png"
    raw.parent.mkdir(parents=True)
    raw.write_bytes(b"already-observed-native-raw")
    receipt_path=ep/"meta/provider-receipts/11.json"
    receipt_path.parent.mkdir(parents=True)
    key="episode/frame-11"
    gen="ga1-"+"1"*48+"-a1"
    r={
        "frame":"11","generation_key":gen,"attempt_index":1,"fencing_token":1,
        "generation_route":"codex_subscription","payload_model":"gpt-image-2.5-flare",
        "payload_quality":"high","normalize_decision":"ASPECT_RATIO_MISMATCH",
        "request_id":"a"*32,"raw_sha256":recovery.sha(raw),
        "frame_contract_sha256":"c"*64,"prompt_package_sha256":"p"*64,
    }
    row={"id":"batch11","frame":11,"scope":"batch","kind":"original",
         "status":"external_blocked","technical_failure_code":"ASPECT_RATIO_MISMATCH",
         "model":"gpt-image-2.5-flare","quality":"high",
         "frame_contract":{"contract_sha256":"c"*64},
         "prompt_package":{"package_sha256":"p"*64}}
    plan={"auto_resolvable":True,"code":"ASPECT_RATIO_MISMATCH",
          "provider_receipt":str(receipt_path),"raw_path":str(raw),
          "output_path":str(ep/"media/candidates/scheduled/11-final.png"),
          "transaction_id":"tx"}
    db={"status":"OUTCOME_UNKNOWN","failure_class":"generation_failed_before_candidate_commit",
        "provider":"codex_subscription","payload_model":"gpt-image-2.5-flare",
        "payload_quality":"high","dispatch_committed_at":"t1",
        "generation_observed_at":"t2","result_ref":None,"generation_key":gen}
    st={"attempts_consumed":1,"active_attempt_index":None,"fencing_counter":1}
    loaded={"source":"mysql","receipt_id":"PR_verified","legacy_path":"episodes/a/b.json",
            "payload":r,"receipt_status":"RAW_OBSERVED"}
    return ep,raw,receipt_path,key,gen,r,row,plan,db,st,loaded


def test_mysql_only_receipt_not_file_needed_for_legitimate_source(tmp_path):
    ep,raw,rpath,key,gen,receipt,row,plan,old,state,loaded=evidence(tmp_path)
    assert not rpath.is_file()
    with (patch.object(recovery.legacy,"inspect_item",return_value=plan),
          patch.object(recovery.provider_receipt_persistence,"load_by_path",return_value=loaded),
          patch.object(recovery.logical_asset_identity,"frame_asset_key",return_value=key),
          patch.object(recovery.logical_asset_identity,"episode_id",return_value="episode"),
          patch.object(recovery.authority,"stable_generation_key",return_value=gen),
          patch.object(recovery.authority,"load_asset_state",return_value=state),
          patch.object(recovery.authority,"load_attempt",return_value=old)):
        proof=recovery.eligible(ep,row)
        assert proof and proof["receipt_id"]=="PR_verified"
        assert proof["raw_sha256"]==recovery.sha(raw)
        row["technical_failure_code"]="IMAGE_BACKEND_ERROR"
        assert recovery.eligible(ep,row) is None
        row["technical_failure_code"]="ASPECT_RATIO_MISMATCH"
        state["active_attempt_index"]=1
        assert recovery.eligible(ep,row) is None
        state["active_attempt_index"]=None
        state["attempts_consumed"]=2
        assert recovery.eligible(ep,row) is None
        state["attempts_consumed"]=1
        receipt["generation_key"]="different"
        assert recovery.eligible(ep,row) is None
        receipt["generation_key"]=gen
        raw.write_bytes(b"tampered")
        assert recovery.eligible(ep,row) is None


class FakeConnection:
    def __init__(self,plan,normalized_sha):
        self.plan=plan
        self.normalized_sha=normalized_sha
        self.writes=0
        self.fence=1
        self.status="OUTCOME_UNKNOWN"
        self.receipt={"generation_key":plan["generation_key"],
                      "raw_sha256":plan["raw_sha256"],
                      "payload_model":"gpt-image-2.5-flare","payload_quality":"high",
                      "release_canvas":{"sha256":normalized_sha}}
        self.attempt={"FENCING_TOKEN":1,"STATUS":"OUTCOME_UNKNOWN",
                      "FAILURE_CLASS":"generation_failed_before_candidate_commit",
                      "GENERATION_KEY":plan["generation_key"],"PROVIDER":"codex_subscription",
                      "PAYLOAD_MODEL":"gpt-image-2.5-flare","PAYLOAD_QUALITY":"high",
                      "RESULT_REF":None,"DISPATCH_COMMITTED_AT":"t1","GENERATION_OBSERVED_AT":"t2",
                      "CONTEXT":json.dumps({"scope":"batch","queue_item_id":"batch11",
                                            "frame_contract_sha256":"c"*64,
                                            "prompt_package_sha256":"p"*64})}
    @contextmanager
    def transaction(self):
        old=self.writes
        try:yield
        except BaseException:
            self.writes=old
            raise
    def query_one(self,sql,args):
        if "TB_PROVIDER_RECEIPT" in sql:
            return {"RECEIPT_ID":self.plan["receipt_id"],"STATUS":"FINALIZED",
                    "PAYLOAD":json.dumps(self.receipt)}
        if "TB_GENERATION_ATTEMPT" in sql:
            return self.attempt
        raise AssertionError(sql)
    def execute(self,sql,args):
        assert "AND STATUS='OUTCOME_UNKNOWN'" in sql
        assert "AND GENERATION_KEY=%s" in sql
        self.writes+=1
        return 1
    def close(self):pass


def test_atomic_cas_accepts_only_exact_original_fence_and_locked_mysql_receipt(tmp_path):
    ep,raw,receipt_path,key,gen,receipt,row,source,old,state,loaded=evidence(tmp_path)
    output=ep/"media/candidates/scheduled/11-final.png"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"deterministic-normalization")
    normalized_sha=recovery.sha(output)
    proof={**source,"raw_path":raw,"receipt_path":receipt_path,"asset_key":key,
           "generation_key":gen,"raw_sha256":recovery.sha(raw),
           "receipt_sha256":recovery._receipt_digest({
               "generation_key":gen,"raw_sha256":recovery.sha(raw),
               "payload_model":"gpt-image-2.5-flare","payload_quality":"high",
               "release_canvas":{"sha256":normalized_sha}}),
           "receipt_legacy_path":loaded["legacy_path"],"receipt_id":loaded["receipt_id"],
           "item_id":"batch11","frame_contract_sha256":"c"*64,
           "prompt_package_sha256":"p"*64}
    db=FakeConnection(proof,normalized_sha)
    with (patch.object(recovery,"_freeze_three",return_value=nullcontext()),
          patch.object(recovery.authority,"_connect",return_value=db),
          patch.object(recovery.authority,"_row",return_value={
              "ATTEMPTS_CONSUMED":1,"ACTIVE_ATTEMPT_INDEX":None,"FENCING_COUNTER":1}),
          patch.object(recovery.authority,"_episode_id",return_value="episode"),
          patch.object(recovery.provider_receipt_persistence,"_episode_id",return_value="episode")):
        recovery._mysql_reconcile(ep,proof,output,normalized_sha)
        assert db.writes==1
        db.writes=0
        db.attempt["STATUS"]="OUTCOME_UNKNOWN"
        db.attempt["FENCING_TOKEN"]=2
        with pytest.raises(recovery.PreservedRawDenied,match="UNKNOWN_GENERATION_FENCE_CHANGED"):
            recovery._mysql_reconcile(ep,proof,output,normalized_sha)
        assert db.writes==0
        db.attempt["FENCING_TOKEN"]=1
        db.receipt["raw_sha256"]="0"*64
        with pytest.raises(recovery.PreservedRawDenied,match="CANONICAL_MYSQL_RECEIPT_CHANGED"):
            recovery._mysql_reconcile(ep,proof,output,normalized_sha)
        assert db.writes==0
        db.receipt["raw_sha256"]=proof["raw_sha256"]
        raw.write_bytes(b"tampered")
        with pytest.raises(recovery.PreservedRawDenied,match="SOURCE_CHANGED"):
            recovery._mysql_reconcile(ep,proof,output,normalized_sha)
        assert db.writes==0


def test_unverified_backend_error_never_normalizes_or_releases_queue(tmp_path):
    ep,_,_,_,_,_,row,_,_,_,_=evidence(tmp_path)
    row["technical_failure_code"]="IMAGE_BACKEND_ERROR"
    q={"items":[row]}
    with (patch.object(recovery.scheduler_core,"queue_transaction",return_value=nullcontext()),
          patch.object(recovery.scheduler_core,"load_queue",return_value=q),
          patch.object(recovery.canvas_normalize,"normalize_provider_crop_exception") as norm,
          patch.object(recovery.authority,"_connect") as db,
          patch.object(recovery.scheduler_core,"save_queue") as save):
        result=recovery.recover_one(ep,11)
        assert result["status"]=="BLOCKED"
        norm.assert_not_called()
        db.assert_not_called()
        save.assert_not_called()


def test_new_action_registered_in_permanent_regression():
    main=(ROOT/"episodes/_system/machine_action_executor.py").read_text(encoding="utf-8")
    next_=(ROOT/"episodes/_system/next_action.py").read_text(encoding="utf-8")
    fast=(ROOT/"scripts/storyos_autonomy_fast_test.py").read_text(encoding="utf-8")
    assert "RECONCILE_PRESERVED_PROVIDER_RAW" in main
    assert "RECONCILE_PRESERVED_PROVIDER_RAW" in next_
    assert "image_unknown_raw_reconcile.eligible(ep,x)" in next_
    assert "test_image_unknown_raw_reconcile.py" in fast


def test_second_attempt_only_after_sha_reviewed_native_network_failure(tmp_path):
    ep,raw,rpath,key,gen,receipt,row,plan,old,state,loaded=evidence(tmp_path)
    # The raw payload and receipt remain exact and immutable; no provider call.
    row["id"]="batch05"
    row["frame"]=5
    row["native_network_terminal_rearm_count"]=1
    row["native_network_capability_requeue_count"]=1
    receipt.update({"frame":"05","attempt_index":2,"fencing_token":2,
                    "generation_key":"ga1-"+"2"*48+"-a2"})
    second=copy.deepcopy(old)
    second["generation_key"]=receipt["generation_key"]
    second["runner_request_id"]=receipt["request_id"]
    first={"status":"FAILED_AFTER_DISPATCH",
           "failure_class":"IMAGE_TOOL_NETWORK_ERROR_DURABLE_RECEIPT",
           "provider":"codex_subscription","result_ref":None}
    state.update({"attempts_consumed":2,"fencing_counter":2})
    with (patch.object(recovery.legacy,"inspect_item",return_value=plan),
          patch.object(recovery.provider_receipt_persistence,"load_by_path",return_value=loaded),
          patch.object(recovery.logical_asset_identity,"frame_asset_key",return_value=key),
          patch.object(recovery.logical_asset_identity,"episode_id",return_value="episode"),
          patch.object(recovery.authority,"stable_generation_key",return_value=receipt["generation_key"]),
          patch.object(recovery.authority,"load_asset_state",return_value=state),
          patch.object(recovery.authority,"load_attempt",
                       side_effect=lambda ep,key,index: first if index==1 else second)):
        valid=recovery.eligible(ep,row)
        assert valid is not None and valid["attempt_index"]==2
        assert valid["generation_key"]==receipt["generation_key"]
        row["native_network_terminal_rearm_count"]=0
        assert recovery.eligible(ep,row) is None
        row["native_network_terminal_rearm_count"]=1
        first["status"]="OUTCOME_UNKNOWN"
        assert recovery.eligible(ep,row) is None
        first["status"]="FAILED_AFTER_DISPATCH"
        state["active_attempt_index"]=2
        assert recovery.eligible(ep,row) is None
        state["active_attempt_index"]=None
        state["attempts_consumed"]=3
        assert recovery.eligible(ep,row) is None
        state["attempts_consumed"]=2
        second["runner_request_id"]="b"*32
        assert recovery.eligible(ep,row) is None


def test_second_attempt_mysql_cas_touches_only_fenced_attempt2(tmp_path):
    ep,raw,rpath,key,gen,receipt,row,plan,old,state,loaded=evidence(tmp_path)
    output=ep/"media/candidates/scheduled/05-final.png"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"normalized-sha-bound-existing-provider-png")
    receipt2={**receipt,"attempt_index":2,"fencing_token":2,"request_id":"a"*32,
              "generation_key":"ga1-"+"2"*48+"-a2"}
    proof={**plan,"asset_key":key,"item_id":"batch05",
           "attempt_index":2,"generation_key":receipt2["generation_key"],
           "raw_path":raw,"raw_sha256":recovery.sha(raw),
           "receipt_path":rpath,"receipt_legacy_path":loaded["legacy_path"],
           "receipt_id":loaded["receipt_id"],
           "frame_contract_sha256":"c"*64,"prompt_package_sha256":"p"*64}
    db=FakeConnection(proof,recovery.sha(output))
    db.receipt["request_id"]="a"*32
    proof["receipt_sha256"]=recovery._receipt_digest(db.receipt)
    db.attempt["FENCING_TOKEN"]=2
    context=json.loads(db.attempt["CONTEXT"])
    context["queue_item_id"]="batch05"
    context["runner_request_id"]="a"*32
    db.attempt["CONTEXT"]=json.dumps(context)
    with (patch.object(recovery,"_freeze_three",return_value=nullcontext()),
          patch.object(recovery.authority,"_connect",return_value=db),
          patch.object(recovery.authority,"_row",return_value={
              "ATTEMPTS_CONSUMED":2,"ACTIVE_ATTEMPT_INDEX":None,"FENCING_COUNTER":2}),
          patch.object(recovery.authority,"_episode_id",return_value="episode"),
          patch.object(recovery.provider_receipt_persistence,"_episode_id",return_value="episode")):
        recovery._mysql_reconcile(ep,proof,output,recovery.sha(output))
        assert db.writes==1
        db.writes=0
        db.attempt["FENCING_TOKEN"]=1
        with pytest.raises(recovery.PreservedRawDenied,match="UNKNOWN_GENERATION_FENCE_CHANGED"):
            recovery._mysql_reconcile(ep,proof,output,recovery.sha(output))
        assert db.writes==0


def test_second_attempt_cas_denies_stale_runner_identity(tmp_path):
    ep,raw,rpath,key,gen,receipt,row,plan,old,state,loaded=evidence(tmp_path)
    out=ep/"media/candidates/scheduled/05.png"
    out.parent.mkdir(parents=True)
    out.write_bytes(b"fixed")
    plan={**plan,"asset_key":key,"item_id":"batch05","attempt_index":2,
          "generation_key":"ga1-"+"2"*48+"-a2","raw_path":raw,
          "raw_sha256":recovery.sha(raw),"receipt_path":rpath,
          "receipt_legacy_path":loaded["legacy_path"],"receipt_id":loaded["receipt_id"],
          "frame_contract_sha256":"c"*64,"prompt_package_sha256":"p"*64}
    db=FakeConnection(plan,recovery.sha(out))
    db.attempt["FENCING_TOKEN"]=2
    db.receipt["request_id"]="a"*32
    plan["receipt_sha256"]=recovery._receipt_digest(db.receipt)
    db.attempt["CONTEXT"]=json.dumps({"scope":"batch","queue_item_id":"batch05",
          "frame_contract_sha256":"c"*64,"prompt_package_sha256":"p"*64,
          "runner_request_id":"unrelated"})
    with (patch.object(recovery,"_freeze_three",return_value=nullcontext()),
          patch.object(recovery.authority,"_connect",return_value=db),
          patch.object(recovery.authority,"_row",return_value={
              "ATTEMPTS_CONSUMED":2,"ACTIVE_ATTEMPT_INDEX":None,"FENCING_COUNTER":2}),
          patch.object(recovery.authority,"_episode_id",return_value="episode"),
          patch.object(recovery.provider_receipt_persistence,"_episode_id",return_value="episode")):
        with pytest.raises(recovery.PreservedRawDenied,match="UNKNOWN_GENERATION_FENCE_CHANGED"):
            recovery._mysql_reconcile(ep,plan,out,recovery.sha(out))
        assert db.writes==0

def test_ep14_surgical_near_portrait_only(tmp_path,monkeypatch):
    root=tmp_path
    monkeypatch.setattr(recovery,"ROOT",root)
    ep=root/"episodes"/"00_独立篇"/"14_深渊疗愈所_第一集_净土生命还原"
    assert [i for i in range(1,49) if recovery._near_portrait_scope(ep,i)]==[24,25,28]
    assert not recovery._near_portrait_scope(root/"episodes"/"00_独立篇"/"13_失物归还的那扇门",24)


def test_near_portrait_requires_exact_preserved_sha(tmp_path,monkeypatch):
    ep,raw,rpath,key,gen,receipt,row,plan,old,state,loaded=evidence(tmp_path)
    ep=tmp_path/"episodes"/"00_独立篇"/"14_深渊疗愈所_第一集_净土生命还原"
    raw=ep/"media/raw/24-native.png"
    raw.parent.mkdir(parents=True,exist_ok=True)
    raw.write_bytes(b"observed-image")
    rpath=ep/"meta/provider-receipts/24.json"
    rpath.parent.mkdir(parents=True,exist_ok=True)
    plan.update({"raw_path":str(raw),"provider_receipt":str(rpath),"ratio_delta":0.0625})
    receipt.update({"frame":"24","raw_sha256":recovery.sha(raw)})
    row["frame"]=24
    monkeypatch.setattr(recovery,"ROOT",tmp_path)
    monkeypatch.setitem(recovery._EP14_NEAR_PORTRAIT_RAW,24,recovery.sha(raw))
    from unittest.mock import Mock
    inspect=Mock(return_value=plan)
    with (patch.object(recovery.legacy,"inspect_item",inspect),
          patch.object(recovery.provider_receipt_persistence,"load_by_path",return_value=loaded),
          patch.object(recovery.logical_asset_identity,"frame_asset_key",return_value=key),
          patch.object(recovery.logical_asset_identity,"episode_id",return_value="episode"),
          patch.object(recovery.authority,"stable_generation_key",return_value=gen),
          patch.object(recovery.authority,"load_asset_state",return_value=state),
          patch.object(recovery.authority,"load_attempt",return_value=old)):
        assert recovery.eligible(ep,row) is not None
        assert inspect.call_args.kwargs["exception_crop_ratio_max"]==0.065
        receipt["raw_sha256"]="0"*64
        assert recovery.eligible(ep,row) is None


def test_surgical_crop_max_keeps_landscape_and_other_episodes_blocked(tmp_path):
    from PIL import Image
    import canvas_normalize as canvas
    raw=tmp_path/"native.png"
    portrait_out=tmp_path/"portrait.png"
    Image.new("RGB",(1086,1448),"white").save(raw)
    with pytest.raises(canvas.NormalizeError,match="exception refused"):
        canvas.normalize_provider_crop_exception(raw,portrait_out,1080,1350,reason="test")
    result=canvas.normalize_provider_crop_exception(
        raw,portrait_out,1080,1350,reason="verified three frames",exception_crop_ratio_max=0.065)
    assert result["crop_applied"] is True
    assert result["exception_ratio_delta_max"]==0.065
    assert Image.open(portrait_out).size==(1080,1350)
    landscape=tmp_path/"landscape.png"
    Image.new("RGB",(1448,1086),"white").save(landscape)
    with pytest.raises(canvas.NormalizeError,match="exception refused"):
        canvas.normalize_provider_crop_exception(
            landscape,tmp_path/"no-landscape.png",1080,1350,reason="test",exception_crop_ratio_max=0.065)
    with pytest.raises(canvas.NormalizeError,match="unsupported exception crop upper bound"):
        canvas.normalize_provider_crop_exception(
            landscape,tmp_path/"no-oversize.png",1080,1350,reason="test",exception_crop_ratio_max=0.07)
