"""Offline regressions for cryptographically joined native network failure.

No model calls. No live Episode, MySQL, or Redis writes.
"""
import base64
import json
import sys
from contextlib import contextmanager, nullcontext
from pathlib import Path
from unittest.mock import patch
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/"episodes/_system")]
import native_network_failure_rearm as n

def test_original_batch_followon_must_admit_sha_verified_bounded_second_attempt(tmp_path):
    import production_native_batch_followon as followon
    ep=tmp_path/"ep"
    ep.mkdir()
    item={"id":"batch-05","frame":5,"scope":"batch","kind":"original",
          "status":"queued","model":"gpt-image-2.5-flare",
          "native_batch_verified_followon":True,
          "native_batch_success_anchor_sha256":"a"*64,
          "native_batch_followon_evidence_sha256":"b"*64}
    payload={"model":"gpt-image-2.5-flare"}
    with (patch.object(followon,"_batch",return_value=[item]),
          patch.object(followon,"_episode_authorized",return_value=True),
          patch.object(followon,"_anchor",return_value="a"*64),
          patch.object(followon.attempts,"load_asset_state",return_value={
              "attempts_consumed":1,"active_attempt_index":None,"outcome_unknown_count":1}),
          patch.object(n,"remaining_second_attempt",return_value=True)):
        assert followon.worker_eligible(ep,item,payload,{},queue={"items":[item]})
    with (patch.object(followon,"_batch",return_value=[item]),
          patch.object(followon,"_episode_authorized",return_value=True),
          patch.object(followon,"_anchor",return_value="a"*64),
          patch.object(followon.attempts,"load_asset_state",return_value={
              "attempts_consumed":1,"active_attempt_index":None,"outcome_unknown_count":1}),
          patch.object(n,"remaining_second_attempt",return_value=False)):
        assert not followon.worker_eligible(ep,item,payload,{},queue={"items":[item]})


def test_capability_preflight_denial_requeue_only_once_without_new_attempt(tmp_path):
    ep=tmp_path/"ep";ep.mkdir()
    row={"id":"batch-05","scope":"batch","kind":"original","frame":5,
        "status":"blocked","attempts":1,
        "technical_failure_code":"LOGIN_AUTH_IMAGE_TOOL_CAPABILITY_UNKNOWN",
        "last_error":"LOGIN_AUTH_IMAGE_TOOL_CAPABILITY_UNKNOWN: independent payload route unavailable",
        "native_network_terminal_rearm_count":1,
        "native_network_capability_requeue_count":0}
    q={"items":[row]}
    assert n.requeue_capability_preflight(ep,5)["reason"]=="ACK_REQUIRED"
    with (patch.object(n.scheduler_core,"queue_transaction",return_value=nullcontext()),
          patch.object(n.scheduler_core,"load_queue",return_value=q),
          patch.object(n,"remaining_second_attempt",return_value=True),
          patch.object(n.scheduler_core,"save_queue") as save):
        assert n.requeue_capability_preflight(ep,5,acknowledged=True)["status"]=="PASS"
        save.assert_called_once()
        assert row["status"]=="queued"
        assert row["attempts"]==1  # preflight did not spend provider attempt
        assert row["native_network_capability_requeue_count"]==1
        assert n.requeue_capability_preflight(ep,5,acknowledged=True)["status"]=="BLOCKED"
        save.assert_called_once()



def events(message, extra=None):
    rows=[{"type":"thread.started","thread_id":"t"},{"type":"turn.started"},
          {"type":"item.completed","item":{"type":"agent_message","text":message}}]
    if extra:rows.insert(-1,extra)
    rows.append({"type":"turn.completed"})
    router="2026-10-16T12:55:13.110006Z ERROR codex_core::tools::router: error=image generation failed: network error: error sending request"
    return ("Reading prompt from stdin...\n"+router+"\n"+"\n".join(json.dumps(x) for x in rows)+"\n").encode()


@pytest.mark.parametrize("msg",list(n.NETWORK_WORDING))
def test_native_network_error_only_exact_terminal_verdict(msg):
    assert n._network_failed_log(events(msg))
    assert not n._network_failed_log(events("Image generated successfully"))
    assert not n._network_failed_log(events(msg,{"type":"item.completed","item":{"type":"image_generation","path":"a.png"}}))
    assert not n._network_failed_log(events(msg).replace(b"turn.completed",b"turn.failed"))
    assert not n._network_failed_log(b"not valid json")

def test_mysql_terminal_cas_retains_original_unknown_and_strict_2_attempt_cap(tmp_path):
    ep=tmp_path/"ep";ep.mkdir()
    log=ep/"a.jsonl";receipt=ep/"r.json"
    log.write_bytes(b"native-log");receipt.write_bytes(b"immutable-receipt")
    proof={"asset_key":"episode/frame-05","generation_key":"ga1-"+"1"*48+"-a1",
           "item_id":"batch-05","log":log,"log_sha256":n._hash(log.read_bytes()),
           "receipt":receipt,"receipt_sha256":n._hash(receipt.read_bytes()),
           "request_id":"a"*32,"transaction_id":"txn","frame_contract_sha256":"c"*64,
           "prompt_package_sha256":"p"*64}
    context={"scope":"batch","queue_item_id":"batch-05","frame_contract_sha256":"c"*64,
             "prompt_package_sha256":"p"*64,"preserved_history":"not-reset"}
    class Conn:
        def __init__(self):
            self.writes=[]
            self.attempt={"STATUS":"OUTCOME_UNKNOWN","FENCING_TOKEN":1,
                          "GENERATION_KEY":proof["generation_key"],
                          "PROVIDER":"codex_subscription","RESULT_REF":None,
                          "DISPATCH_COMMITTED_AT":"t","GENERATION_OBSERVED_AT":"t",
                          "FAILURE_CLASS":"generation_failed_before_candidate_commit",
                          "CONTEXT":json.dumps(context)}
        @contextmanager
        def transaction(self):
            yield
        def query_one(self,*args):
            return self.attempt
        def execute(self,sql,args):
            assert "AND STATUS='OUTCOME_UNKNOWN'" in sql
            assert "AND GENERATION_KEY=%s" in sql
            self.writes.append((sql,args));return 1
        def close(self):pass
    db=Conn()
    with (patch.object(n,"_freeze_sources",return_value=nullcontext()),
          patch.object(n.authority,"_connect",return_value=db),
          patch.object(n.authority,"_episode_id",return_value="episode"),
          patch.object(n.authority,"_row",return_value={
              "ATTEMPTS_CONSUMED":1,"ACTIVE_ATTEMPT_INDEX":None,"FENCING_COUNTER":1})):
        n._commit_terminal(ep,proof)
        assert len(db.writes)==1
        assert db.writes[0][1][0]==n.FAILURE_CLASS
        ctx=json.loads(db.writes[0][1][1])
        assert ctx["runner_request_id"]=="a"*32
        assert ctx["preserved_history"]=="not-reset"
        assert ctx["upstream_billing_outcome_unverified"] is True
        assert ctx["network_failure_runner_receipt_sha256"]==proof["receipt_sha256"]
        assert "ATTEMPTS_CONSUMED" not in db.writes[0][0] # No budget refund/reset
        db.attempt["STATUS"]="FAILED_AFTER_DISPATCH"
        db.attempt["FAILURE_CLASS"]=n.FAILURE_CLASS
        n._commit_terminal(ep,proof)
        assert len(db.writes)==1
        receipt.write_bytes(b"tampered")
        with pytest.raises(n.EvidenceDenied,match="SOURCE_CHANGED"):
            n._commit_terminal(ep,proof)
        assert len(db.writes)==1


def test_network_failure_message_without_router_error_cannot_unlock_second_attempt():
    log=events("Image generation failed due to a network error.")
    without=log.replace(b" ERROR codex_core::tools::router:",b" INFO codex_core::tools::router:")
    assert not n._network_failed_log(without)
    forged=log.replace(b"error sending request",b"success")
    assert not n._network_failed_log(forged)



def _receipt_directory(tmp_path,log,bad=None):
    results=tmp_path/"results"
    results.mkdir()
    rid="a"*32
    record={"request_id":rid,"output_sha256":n._hash(log),"output_bytes":len(log),
            "output_base64":base64.b64encode(log).decode(),
            "returncode":0,"evidence":{"request_id":rid,"returncode":0,
                "task_type":"image","transport_route":"native_codex"}}
    if bad: record["evidence"].update(bad)
    (results/(rid+".json")).write_text(json.dumps(record),encoding="utf-8")
    return results,record


def test_unique_exact_runner_receipt_joins_even_without_thread_id(tmp_path):
    log=events("Image generation failed due to a network error.")
    result,_=_receipt_directory(tmp_path,log)
    with patch.object(n.codex_user_runner,"bridge_required",return_value=True),patch.object(
        n.codex_user_runner,"endpoint_path",return_value=tmp_path/"runner.json"),patch.object(
        n.codex_user_runner,"RESULT_DIR_NAME","results"):
        proof=n._matched_receipt(log)
        assert proof["request_id"]=="a"*32
        assert proof["log_sha256"]==n._hash(log)
        (result/("b"*32+".json")).write_text((result/("a"*32+".json")).read_text(),encoding="utf-8")
        with pytest.raises(n.EvidenceDenied,match="AMBIGUOUS"):
            n._matched_receipt(log)


def test_runner_result_with_artifacts_cannot_be_negative_receipt(tmp_path):
    log=events("Image generation failed due to a network error.")
    _receipt_directory(tmp_path,log,{"generated_artifacts":["image.png"]})
    with patch.object(n.codex_user_runner,"bridge_required",return_value=True),patch.object(
        n.codex_user_runner,"endpoint_path",return_value=tmp_path/"runner.json"),patch.object(
        n.codex_user_runner,"RESULT_DIR_NAME","results"):
        with pytest.raises(n.EvidenceDenied,match="NOT_VERIFIED"):
            n._matched_receipt(log)


def test_operator_ack_and_queue_save_only_after_mysql_cas(tmp_path):
    ep=tmp_path/"ep";ep.mkdir()
    item={"scope":"batch","kind":"original","frame":5,"status":"external_blocked",
          "attempts":2,"technical_failure_code":"IMAGE_BACKEND_ERROR","last_error":"NETWORK_ERROR"}
    queue={"items":[item]}
    old_log=ep/"meta/image-workers/05-original.jsonl"
    old_log.parent.mkdir(parents=True)
    old_log.write_bytes(b"original native runner output")
    proof={"receipt_sha256":"a"*64,"log_sha256":"b"*64,"log":old_log}
    assert n.rearm_one(ep,5)["reason"]=="DUPLICATE_UPSTREAM_COST_RISK_ACK_REQUIRED"
    with (patch.object(n.scheduler_core,"queue_transaction",return_value=nullcontext()),
          patch.object(n.scheduler_core,"load_queue",return_value=queue),
          patch.object(n,"inspect",return_value=proof),
          patch.object(n,"_commit_terminal") as cas,
          patch.object(n.scheduler_core,"save_queue") as save):
        result=n.rearm_one(ep,5,acknowledged=True)
        assert result["status"]=="PASS" and result["additional_attempts_consumed"]==0
        cas.assert_called_once()
        save.assert_called_once()
        assert item["status"]=="queued" and item["attempts"]==0 and item[n.RECOVERY_KEY]==1
        with patch.object(n,"inspect",side_effect=n.EvidenceDenied("CANNOT_RETRY")):
            second=n.rearm_one(ep,5,acknowledged=True)
            assert second=={"status":"BLOCKED","reason":"CANNOT_RETRY"}


def test_mysql_cas_rejects_wrong_fencing_without_mutation(tmp_path):
    ep=tmp_path/"ep";ep.mkdir()
    log=ep/"original.jsonl";receipt=ep/"receipt.json"
    log.write_bytes(b"log");receipt.write_bytes(b"receipt")
    proof={"asset_key":"ep/frame-05","generation_key":"ga1-"+"1"*48+"-a1",
           "item_id":"batch-05","log":log,"log_sha256":n._hash(log.read_bytes()),
           "receipt":receipt,"receipt_sha256":n._hash(receipt.read_bytes()),"request_id":"a"*32}
    class Conn:
        def __init__(self):
            self.updates=0
        @contextmanager
        def transaction(self):
            yield
        def query_one(self,*args):
            return {"FENCING_TOKEN":2,"GENERATION_KEY":proof["generation_key"],
                    "PROVIDER":"codex_subscription",
                    "STATUS":"OUTCOME_UNKNOWN",
                    "RESULT_REF":None,"DISPATCH_COMMITTED_AT":"t1",
                    "GENERATION_OBSERVED_AT":"t2",
                    "FAILURE_CLASS":"generation_failed_before_candidate_commit"}
        def execute(self,*args):
            self.updates+=1;return 1
        def close(self):pass
    db=Conn()
    with (patch.object(n,"_freeze_sources",return_value=nullcontext()),
          patch.object(n.authority,"_connect",return_value=db),
          patch.object(n.authority,"_episode_id",return_value="ep"),
          patch.object(n.authority,"_row",return_value={
              "ATTEMPTS_CONSUMED":1,"ACTIVE_ATTEMPT_INDEX":None,"FENCING_COUNTER":1})):
        with pytest.raises(n.EvidenceDenied,match="FENCE_CHANGED"):
            n._commit_terminal(ep,proof)
        assert db.updates==0