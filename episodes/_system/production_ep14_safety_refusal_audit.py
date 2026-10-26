"""Exact native image-provider safety rejection audit for Episode14.
No content reinterpretation, no new generation, no paid Attempt reservation.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from PIL import Image
import generation_attempt_authority as auth
import image_blocked_recovery as legacy
import logical_asset_identity as identity
import native_baseline_source_freeze as freeze
import native_network_failure_rearm as native
import production_ledger
import runtime_driver
import scheduler_core

ROOT=Path(__file__).resolve().parents[2]
EP=ROOT/"episodes"/"00_独立篇"/"14_深渊疗愈所_第一集_净土生命还原"
FAILURE="IMAGE_PROVIDER_SAFETY_REJECTED"
PLACEHOLDER="d0a230b1a79b71b858b7c215a0fbb0768d6459c14ea4ef80c61592629bf0e605"
# Original CLI SHA, Runner result SHA, Runner request ID.
PROOFS={
9:("6ecf93750aaa73d459766ccffad8dbb3aba7b206c31d588a82f0877f6ce956d1",
"104cf632c0a0e0c54a1236ff250cfbb1a61ef7a807a2e58cc8e616f25ead7cb8",
"0856131f8db34ab7bd01e79ba3f671ee"),
29:("2479943d3c1a16f2df526bf557a6c41119c1a56a287c16414b0a09cdc7c2ba3c",
"48aa1cb092d1401bbdbbd35374facd7b581f43de7008c01d6c765d20f7473612",
"9c11965612854451b1fec99c630c210c"),
48:("381480d8b5cafacf623b839fe661fbf9ea618b719724289aebe6c079a965558a",
"85619a2f5da93964c04d0ac0859f65f89b308fab4531e712205680fab2bbac0f",
"65af9d3acd364d179eeb87095415dac2")}

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def _scope(ep,frame):
    return Path(ep).resolve()==EP.resolve() and int(frame) in PROOFS

def inspect(ep,row):
    ep=Path(ep).resolve();frame=int(row.get("frame") or 0)
    if (not _scope(ep,frame) or row.get("scope")!="batch"
        or row.get("kind")!="original"
        or row.get("status")!="external_blocked"
        or row.get("technical_failure_code")!="IMAGE_BACKEND_ERROR"
        or row.get("output_path") or row.get("candidate_output_path")):
        return None
    logs=list((ep/"meta/image-workers").glob(f"{frame:02d}-*.jsonl"))
    raws=list((ep/"media/raw").glob(f"{frame:02d}-*.png"))
    if len(logs)!=1 or len(raws)!=1:return None
    log,raw=logs[0].resolve(),raws[0].resolve()
    if not log.is_relative_to(ep) or not raw.is_relative_to(ep):return None
    if sha(log)!=PROOFS[frame][0] or sha(raw)!=PLACEHOLDER:return None
    with Image.open(raw) as image:
        if image.format!="PNG" or image.size!=(100,100):return None
        image.verify()
    content=log.read_bytes()
    if b"moderation_blocked" not in content or len(content)>7000:return None
    events=[json.loads(x) for x in content.decode("utf-8-sig").splitlines()
            if x.startswith("{")]
    messages=[str((x.get("item") or {}).get("text") or "")
              for x in events if x.get("type")=="item.completed"
              and (x.get("item") or {}).get("type")=="agent_message"]
    if (len(messages)!=1
        or not any(t in messages[0].lower() for t in
                   ("未能生成图像","未生成图像","no image was produced"))
        or sum(x.get("type")=="turn.completed" for x in events)!=1
        or any(x.get("type")=="item.completed"
               and (x.get("item") or {}).get("type")!="agent_message"
               for x in events)):
        return None
    runner=native._matched_receipt(content)
    if tuple(runner[k] for k in ("log_sha256","receipt_sha256","request_id"))!=PROOFS[frame]:
        return None
    key=identity.frame_asset_key(ep,frame)
    state=auth.load_asset_state(ep,key) or {}
    first=auth.load_attempt(ep,key,1) or {}
    txn=(row.get("execution") or {}).get("transaction_id")
    latest=legacy._latest_attempt(production_ledger.load_authority(ep,default={}) or {},frame)
    contract=(row.get("frame_contract") or {}).get("contract_sha256")
    pkg=(row.get("prompt_package") or {}).get("package_sha256")
    if (int(state.get("attempts_consumed") or 0)!=1
        or state.get("active_attempt_index") is not None
        or int(state.get("fencing_counter") or 0)!=1
        or auth.load_attempt(ep,key,2)
        or first.get("status") not in ("OUTCOME_UNKNOWN","FAILED_AFTER_DISPATCH")
        or first.get("failure_class") not in ("generation_failed_before_candidate_commit",FAILURE)
        or first.get("provider")!="codex_subscription"
        or first.get("runner_request_id")!=runner["request_id"]
        or first.get("payload_model")!=row.get("model")
        or first.get("payload_quality")!=row.get("quality")
        or first.get("generation_key")!=auth.stable_generation_key(identity.episode_id(ep),key,1)
        or first.get("result_ref") or not first.get("dispatch_committed_at")
        or not first.get("generation_observed_at") or not txn
        or latest.get("runtime_transaction_id")!=txn
        or latest.get("result")!="technical_failure"
        or (latest.get("request") or {}).get("frame_contract_sha256")!=contract
        or not contract or not pkg):
        return None
    return {**runner,"raw":raw,"log":log,"frame":frame,"key":key,
            "item_id":row["id"],"generation_key":first["generation_key"],
            "contract":contract,"pkg":pkg}

def _cas(ep,proof):
    """Original Attempt 1 CAS, with all three source files read-frozen."""
    from contextlib import ExitStack
    import os
    if os.name!="nt":
        raise native.EvidenceDenied("WINDOWS_EXCLUSIVE_SOURCE_FREEZE_REQUIRED")
    handles=[]
    try:
        for path in sorted((proof["log"],proof["receipt"],proof["raw"]),key=str):
            handles.append(freeze._windows_open_shared_read(path))
        connection=auth._connect()
        try:
            with connection.transaction():
                if (sha(proof["log"])!=proof["log_sha256"]
                    or sha(proof["receipt"])!=proof["receipt_sha256"]
                    or sha(proof["raw"])!=PLACEHOLDER):
                    raise native.EvidenceDenied("PROVIDER_SAFETY_SOURCE_CHANGED")
                eid=auth._episode_id(ep)
                state=auth._row(connection,eid,proof["key"])
                row=connection.query_one(
                    "SELECT * FROM TB_GENERATION_ATTEMPT WHERE EPISODE_ID=%s "
                    "AND LOGICAL_ASSET_KEY=%s AND ATTEMPT_INDEX=1 FOR UPDATE",
                    (eid,proof["key"]))
                if (not state or not row
                    or int(state.get("ATTEMPTS_CONSUMED") or 0)!=1
                    or state.get("ACTIVE_ATTEMPT_INDEX") is not None
                    or int(state.get("FENCING_COUNTER") or 0)!=1
                    or int(row.get("FENCING_TOKEN") or 0)!=1
                    or row.get("GENERATION_KEY")!=proof["generation_key"]
                    or row.get("PROVIDER")!="codex_subscription"
                    or row.get("RESULT_REF")
                    or not row.get("DISPATCH_COMMITTED_AT")
                    or not row.get("GENERATION_OBSERVED_AT")):
                    raise native.EvidenceDenied("PROVIDER_SAFETY_FENCE_CHANGED")
                context=auth._context(row)
                if (context.get("scope")!="batch"
                    or context.get("queue_item_id")!=proof["item_id"]
                    or context.get("frame_contract_sha256")!=proof["contract"]
                    or context.get("prompt_package_sha256")!=proof["pkg"]
                    or context.get("runner_request_id") not in
                       (None,"",proof["request_id"])):
                    raise native.EvidenceDenied("PROVIDER_SAFETY_CONTEXT_CHANGED")
                if row["STATUS"]=="FAILED_AFTER_DISPATCH":
                    if (row.get("FAILURE_CLASS")!=FAILURE
                        or context.get("safety_refusal_receipt_sha256")!=proof["receipt_sha256"]
                        or context.get("no_automatic_original_prompt_retry") is not True):
                        raise native.EvidenceDenied("CONFLICTING_SAFETY_TERMINAL")
                    return
                if (row["STATUS"]!="OUTCOME_UNKNOWN"
                    or row.get("FAILURE_CLASS")!="generation_failed_before_candidate_commit"):
                    raise native.EvidenceDenied("UNKNOWN_SAFETY_ATTEMPT_CHANGED")
                context.update({
                    "runner_request_id":proof["request_id"],
                    "safety_refusal_receipt_sha256":proof["receipt_sha256"],
                    "safety_refusal_log_sha256":proof["log_sha256"],
                    "upstream_billing_outcome_unverified":True,
                    "requires_content_revision":True,
                    "no_automatic_original_prompt_retry":True,
                })
                affected=connection.execute(
                    "UPDATE TB_GENERATION_ATTEMPT SET STATUS='FAILED_AFTER_DISPATCH', "
                    "FAILURE_CLASS=%s, CONTEXT=%s WHERE EPISODE_ID=%s AND "
                    "LOGICAL_ASSET_KEY=%s AND ATTEMPT_INDEX=1 AND "
                    "STATUS='OUTCOME_UNKNOWN' AND GENERATION_KEY=%s "
                    "AND FENCING_TOKEN=1 AND RESULT_REF IS NULL AND "
                    "FAILURE_CLASS='generation_failed_before_candidate_commit'",
                    (FAILURE,json.dumps(context,ensure_ascii=False,sort_keys=True),
                     eid,proof["key"],proof["generation_key"]))
                if affected!=1:
                    raise native.EvidenceDenied("SAFETY_CAS_LOST")
                if (sha(proof["log"])!=proof["log_sha256"]
                    or sha(proof["receipt"])!=proof["receipt_sha256"]
                    or sha(proof["raw"])!=PLACEHOLDER):
                    raise native.EvidenceDenied("PROVIDER_SAFETY_SOURCE_CHANGED_AT_COMMIT")
        finally:
            connection.close()
    finally:
        for handle in reversed(handles):
            freeze._windows_close(handle)

def reconcile(ep,frame):
    """No new image, no retry entitlement; original queue stays blocked."""
    ep=Path(ep).resolve()
    if not _scope(ep,frame):
        return {"status":"BLOCKED","reason":"NOT_BOUND_SAFETY_FRAME"}
    d=runtime_driver.status(ep)
    if (d.get("driver_state")!="EXITED" or d.get("liveness")!="DEAD"
        or int(d.get("pid") or 0)!=0):
        return {"status":"BLOCKED","reason":"DRIVER_NOT_STOPPED"}
    try:
        with scheduler_core.queue_transaction(ep):
            q=scheduler_core.load_queue(ep)
            row=next((x for x in q.get("items",[]) if x.get("scope")=="batch"
                      and int(x.get("frame") or 0)==int(frame)),None)
            if row is None:return {"status":"BLOCKED","reason":"FRAME_NOT_IN_BATCH"}
            proof=inspect(ep,row)
            if not proof:
                return {"status":"BLOCKED","reason":"ORIGINAL_REFUSAL_NOT_VERIFIED"}
            _cas(ep,proof)
            if row.get("status")!="external_blocked":
                raise native.EvidenceDenied("QUEUE_OWNER_CHANGED")
            row.update({
                "provider_safety_refusal_receipt_sha256":proof["receipt_sha256"],
                "provider_safety_refusal_log_sha256":proof["log_sha256"],
                "no_automatic_original_prompt_retry":True,
                "requires_content_revision":True,
                "upstream_billing_outcome_unverified":True,
            })
            scheduler_core.save_queue(ep,q)
            return {"status":"PASS","frame":int(frame),
                    "first_attempt":"FAILED_AFTER_DISPATCH",
                    "failure_class":FAILURE,"queue_status":"external_blocked",
                    "provider_calls":0,"attempts_reserved":0,
                    "requires_content_revision":True,
                    "upstream_billing_outcome_unverified":True}
    except (scheduler_core.QueueMutationBusy,native.EvidenceDenied) as exc:
        return {"status":"BLOCKED","reason":str(exc)}

if __name__=="__main__":
    import argparse
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("episode_dir",type=Path)
    ap.add_argument("--frame",type=int,choices=(9,29,48),required=True)
    args=ap.parse_args()
    result=reconcile(args.episode_dir,args.frame)
    print(json.dumps(result,ensure_ascii=False))
    raise SystemExit(0 if result["status"]=="PASS" else 2)
