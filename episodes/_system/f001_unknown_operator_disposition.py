"""One-shot F001 operator disposition of a consumed but unprovable native image.

No image is validated, no quota is refunded, and this does not call a Provider.
The local *production acceptance* failed; upstream generation/billing remains
unknown, explicitly recorded in the preserved Generation Attempt CONTEXT.
Only a separately authorized Attempt #2 may be admitted by the normal Gateway.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path

import codex_user_runner
import episode_state_persistence
import generation_attempt_authority as authority
import logical_asset_identity
import production_recovery
import scheduler_core

ROOT=Path(__file__).resolve().parents[2]
EPISODE_REL="episodes/00_独立篇/14_深渊疗愈所_第一集_净土生命还原"
ITEM_ID="ead88592f160"
REQUEST="4f075d7d3f54461597da8b0cb41b6133"
EXPECTED_ERROR="NATIVE_BASELINE_PIXEL_TOOL_PROOF_UNVERIFIED"
DISPOSITION_CLASS="LOCAL_PIXEL_PROVENANCE_UNVERIFIED"
RECOVERY_FIELD="operator_unknown_disposition_v1"
ACK="ACK_UPSTREAM_RESULT_AND_BILLING_UNKNOWN_ACCEPT_SECOND_PAID_ATTEMPT"
RAW_SHA="4674fd6233afdeaed53cc8d701138fe510c2c2eba37ee908394aa5c9bb5466ce"
CANDIDATE_SHA="56e2725185f5b70304603fb5f41959d7addd9b2e0f5fc04b8aeeeabd3a2e5b08"


class DispositionDenied(RuntimeError):
    pass


def _deny(code):
    raise DispositionDenied(code)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical_episode(value):
    ep=Path(value).resolve()
    if ep != (ROOT/EPISODE_REL).resolve() or not ep.is_dir():
        _deny("F001_EPISODE_SCOPE_NOT_AUTHORIZED")
    return ep


def source_report(ep, *, queue=None, attempt=None, state=None) -> dict:
    """Read-only exact published evidence; no model/queue/SQL writes."""
    ep=canonical_episode(ep)
    stage, stage_source=episode_state_persistence.load_with_source(ep)
    if (stage_source!="mysql" or not isinstance(stage,dict)
            or stage.get("current_state")!="STORYBOARD_LOCKED"):
        _deny("F001_MYSQL_STAGE_NOT_STORYBOARD_LOCKED")
    q=queue if queue is not None else scheduler_core.load_queue(ep)
    items=q.get("items") or []
    if (len(items)!=4 or {int(x.get("frame") or 0) for x in items}!={1,5,45,47}):
        _deny("F001_FOUR_FRAME_QUEUE_DRIFT")
    row=next(x for x in items if int(x.get("frame") or 0)==1)
    if (row.get("id")!=ITEM_ID or row.get("scope")!="visual_lock"
            or row.get("model")!="gpt-image-2.5-flare" or row.get("quality")!="high"
            or row.get("status") not in {"external_blocked","queued"}
            or any(x.get("status")!="queued" or list(x.get("depends_on") or [])!=[1]
                   for x in items if x is not row)):
        _deny("F001_QUEUE_OR_DEPENDENCY_DRIFT")
    key=logical_asset_identity.frame_asset_key(ep,1)
    a=attempt if attempt is not None else authority.load_attempt(ep,key,1)
    st=state if state is not None else authority.load_asset_state(ep,key)
    if (not a or a.get("generation_key")!=authority.stable_generation_key(
            logical_asset_identity.episode_id(ep),key,1)
            or int(a.get("attempt_index") or 0)!=1
            or a.get("runner_request_id")!=REQUEST
            or a.get("provider")!="codex_subscription"
            or a.get("payload_model")!="gpt-image-2.5-flare"
            or a.get("payload_quality")!="high"
            or not a.get("dispatch_committed_at")
            or not a.get("generation_observed_at")
            or a.get("result_ref")
            or int(st.get("attempts_consumed") or -1)!=1
            or int(st.get("fencing_counter") or -1)!=1
            or st.get("active_attempt_index") is not None):
        _deny("F001_MYSQL_ATTEMPT_IDENTITY_DRIFT")
    if a.get("status") not in {"OUTCOME_UNKNOWN","FAILED_AFTER_DISPATCH"}:
        _deny("F001_UNEXPECTED_ATTEMPT_STATUS")
    if a.get("status")=="OUTCOME_UNKNOWN" and a.get("failure_class")!=EXPECTED_ERROR:
        _deny("F001_UNKNOWN_FAILURE_CLASS_DRIFT")
    if a.get("status")=="FAILED_AFTER_DISPATCH" and a.get("failure_class")!=DISPOSITION_CLASS:
        _deny("F001_ALREADY_TERMINAL_CONFLICT")
    if row.get("status")=="queued" and a.get("status")!="FAILED_AFTER_DISPATCH":
        _deny("F001_PREMATURE_QUEUE_REARM")
    lifecycle=production_recovery._read(production_recovery.lifecycle_path(ep,row)) or {}
    if (lifecycle.get("item_id")!=ITEM_ID or
            lifecycle.get("state")!="BLOCKED" or
            lifecycle.get("runner_request_id")!=REQUEST or
            lifecycle.get("generation_key")!=a.get("generation_key") or
            EXPECTED_ERROR not in str(lifecycle.get("error") or "")):
        _deny("F001_ORIGINAL_WORKER_SOURCE_DRIFT")
    raw=ep/"media/raw/01-1792765368.png"
    candidate=ep/"media/candidates/scheduled/01-ead88592f160-a2.png"
    log=ep/"meta/image-workers/01-ead88592f160-a2.jsonl"
    if (not raw.is_file() or not candidate.is_file() or not log.is_file()
            or sha(raw)!=RAW_SHA or sha(candidate)!=CANDIDATE_SHA):
        _deny("F001_ORIGINAL_PIXELS_CHANGED")
    receipt=ROOT/"runtime/codex-user-runner/task-results"/(REQUEST+".json")
    if not receipt.is_file():
        _deny("F001_ORIGINAL_RUNNER_RECEIPT_MISSING")
    saved=json.loads(receipt.read_text(encoding="utf-8"))
    output=base64.b64decode(saved.get("output_base64") or "",validate=True)
    if (saved.get("request_id")!=REQUEST or saved.get("returncode")!=0
            or (saved.get("evidence") or {}).get("task_type")!="image"
            or (saved.get("evidence") or {}).get("transport_route")!="native_codex"
            or (saved.get("evidence") or {}).get("generated_artifacts")
            or (saved.get("evidence") or {}).get("thread_ids")
            or output!=log.read_bytes()
            or sha(log)!=saved.get("output_sha256")
            or len(output)!=saved.get("output_bytes")):
        _deny("F001_UNKNOWN_RECEIPT_CHANGED_OR_PROVENANCE_RECOVERED")
    events=[]
    for line in output.decode("utf-8","replace").splitlines():
        try: event=json.loads(line)
        except ValueError: continue
        if isinstance(event,dict):events.append(event)
    if (sum(x.get("type")=="thread.started" for x in events)!=1
            or sum(x.get("type")=="turn.completed" for x in events)!=1
            or any(x.get("type")=="turn.failed" for x in events)):
        _deny("F001_CODEX_LOG_NOT_CLOSED")
    return {
        "status":"F001_UNKNOWN_MANUAL_DISPOSITION_ELIGIBLE"
                 if a["status"]=="OUTCOME_UNKNOWN" else "F001_ALREADY_TERMINAL_DISPOSITION",
        "episode":EPISODE_REL,"frame":1,"item_id":ITEM_ID,
        "generation_key":a["generation_key"],"request_id":REQUEST,
        "prior_status":"OUTCOME_UNKNOWN","prior_failure_class":EXPECTED_ERROR,
        "raw_sha256":RAW_SHA,"candidate_sha256":CANDIDATE_SHA,
        "log_sha256":sha(log),"receipt_sha256":sha(receipt),
        "source_acceptance_verified":False,
        "upstream_generation_outcome_verified":False,
        "upstream_billing_outcome_verified":False,
        "additional_image_calls":0,"attempts_refunded":0,
    }


def _approval_evidence(report):
    return {k:report[k] for k in (
        "episode","frame","item_id","generation_key","request_id",
        "prior_status","prior_failure_class","raw_sha256","candidate_sha256",
        "log_sha256","receipt_sha256")}


def _require_historical_rc24_driver(ep):
    import runtime_driver
    driver=runtime_driver.status(ep)
    if (driver.get("driver_state")!="EXITED"
            or driver.get("exit_code")!="24"
            or driver.get("pid")!=0
            or driver.get("liveness")!="DEAD"):
        _deny("F001_LIVE_OR_DIFFERENT_DRIVER_MUST_NOT_BE_REARMED")
    return driver


def commit(ep, *, acknowledged=False):
    """No paid model calls. Atomically close only local acceptance failure."""
    if not acknowledged:
        return {"status":"BLOCKED","reason":"DUPLICATE_BILLING_RISK_ACK_REQUIRED"}
    ep=canonical_episode(ep)
    _require_historical_rc24_driver(ep)
    with scheduler_core.queue_transaction(ep):
        _require_historical_rc24_driver(ep)
        q=scheduler_core.load_queue(ep)
        report=source_report(ep,queue=q)
        key=logical_asset_identity.frame_asset_key(ep,1)
        conn=authority._connect()
        try:
            with conn.transaction():
                state=authority._row(conn,authority._episode_id(ep),key)
                row=conn.query_one(
                    "SELECT * FROM TB_GENERATION_ATTEMPT WHERE EPISODE_ID=%s "
                    "AND LOGICAL_ASSET_KEY=%s AND ATTEMPT_INDEX=1 FOR UPDATE",
                    (authority._episode_id(ep),key))
                if not state or not row:
                    _deny("F001_LOCKED_MYSQL_ROW_MISSING")
                ctx=authority._context(row)
                if (int(state.get("ATTEMPTS_CONSUMED") or 0)!=1
                    or state.get("ACTIVE_ATTEMPT_INDEX") is not None
                    or int(state.get("FENCING_COUNTER") or 0)!=1
                    or int(row.get("FENCING_TOKEN") or 0)!=1
                    or row.get("GENERATION_KEY")!=report["generation_key"]
                    or row.get("PAYLOAD_MODEL")!="gpt-image-2.5-flare"
                    or row.get("PAYLOAD_QUALITY")!="high"
                    or row.get("DISPATCH_COMMITTED_AT") is None
                    or row.get("GENERATION_OBSERVED_AT") is None
                    or row.get("RESULT_REF")
                    or ctx.get("runner_request_id")!=REQUEST):
                    _deny("F001_MYSQL_CAS_FENCE_CHANGED")
                evidence=_approval_evidence(report)
                existing=ctx.get(RECOVERY_FIELD)
                if row.get("STATUS")=="FAILED_AFTER_DISPATCH":
                    if (row.get("FAILURE_CLASS")!=DISPOSITION_CLASS
                            or not isinstance(existing,dict)
                            or existing.get("ack")!=ACK
                            or existing.get("evidence")!=evidence):
                        _deny("F001_TERMINAL_ACK_DRIFT")
                elif (row.get("STATUS")=="OUTCOME_UNKNOWN"
                      and row.get("FAILURE_CLASS")==EXPECTED_ERROR
                      and not existing):
                    ctx[RECOVERY_FIELD]={
                        "ack":ACK,"evidence":evidence,
                        "local_acceptance_failed":True,
                        "upstream_generation_outcome_unverified":True,
                        "upstream_billing_outcome_unverified":True,
                        "additional_paid_generation_authorized":1,
                    }
                    changed=conn.execute(
                        "UPDATE TB_GENERATION_ATTEMPT SET STATUS='FAILED_AFTER_DISPATCH', "
                        "FAILURE_CLASS=%s, CONTEXT=%s WHERE EPISODE_ID=%s "
                        "AND LOGICAL_ASSET_KEY=%s AND ATTEMPT_INDEX=1 "
                        "AND STATUS='OUTCOME_UNKNOWN' AND FAILURE_CLASS=%s "
                        "AND GENERATION_KEY=%s AND FENCING_TOKEN=1 AND RESULT_REF IS NULL",
                        (DISPOSITION_CLASS,json.dumps(ctx,sort_keys=True,ensure_ascii=False),
                         authority._episode_id(ep),key,EXPECTED_ERROR,report["generation_key"]))
                    if changed!=1:_deny("F001_MYSQL_CAS_LOST")
                else:
                    _deny("F001_UNKNOWN_STATUS_OR_APPROVAL_CONFLICT")
                # Failure of a live SHA or receipt check aborts SQL before commit.
                source_report(ep,queue=q,attempt={
                    "generation_key":row["GENERATION_KEY"],"attempt_index":1,
                    "runner_request_id":REQUEST,"provider":row["PROVIDER"],
                    "payload_model":row["PAYLOAD_MODEL"],
                    "payload_quality":row["PAYLOAD_QUALITY"],
                    "dispatch_committed_at":row["DISPATCH_COMMITTED_AT"],
                    "generation_observed_at":row["GENERATION_OBSERVED_AT"],
                    "result_ref":row.get("RESULT_REF"),
                    "status":row["STATUS"],"failure_class":row["FAILURE_CLASS"],
                },state={
                    "attempts_consumed":state["ATTEMPTS_CONSUMED"],
                    "fencing_counter":state["FENCING_COUNTER"],
                    "active_attempt_index":state["ACTIVE_ATTEMPT_INDEX"]
                })
        finally:
            conn.close()
        item=next(x for x in q["items"] if int(x.get("frame") or 0)==1)
        if item["status"]!="queued":
            item["status"]="queued"
            item["last_error"]=None
            item["generation_attempt_reason"]="TECHNICAL_RETRY"
            item["technical_retry_source_code"]="IMAGE_BACKEND_ERROR"
            item["operator_unknown_disposition_v1"]=report["receipt_sha256"]
            item.pop("external_block",None)
            item.pop("technical_failure_code",None)
            item.pop("retry_exhausted",None)
            item.pop("execution",None)
            item.pop("started_at",None)
            item.pop("completed_at",None)
            scheduler_core.save_queue(ep,q)
        return {"status":"PASS","frame":1,"attempts_consumed":1,
                "remaining_real_attempt_budget":1,
                "provider_calls":0,"additional_paid_attempts":0,
                "upstream_billing_outcome_unverified":True,
                "receipt_sha256":report["receipt_sha256"]}



def operator_second_attempt_source(ep, item) -> bool:
    """Worker-time read-only guard; survives current Runner lifecycle rewrites.

    The previous BLOCKED lifecycle can be overwritten by WORKER_STARTED before
    pre-dispatch, so this guard uses the previously fenced MySQL acknowledgement,
    preserved RAW/Candidate and original Runner receipt instead.
    """
    try:
        ep=canonical_episode(ep)
        if (item.get("id")!=ITEM_ID or item.get("scope")!="visual_lock"
                or item.get("kind")!="original" or int(item.get("frame") or 0)!=1
                or item.get("model")!="gpt-image-2.5-flare" or item.get("quality")!="high"
                or item.get("generation_attempt_reason")!="TECHNICAL_RETRY"
                or item.get("technical_retry_source_code")!="IMAGE_BACKEND_ERROR"):
            return False
        receipt=ROOT/"runtime/codex-user-runner/task-results"/(REQUEST+".json")
        raw=ep/"media/raw/01-1792765368.png"
        candidate=ep/"media/candidates/scheduled/01-ead88592f160-a2.png"
        log=ep/"meta/image-workers/01-ead88592f160-a2.jsonl"
        if (not all(x.is_file() for x in (receipt,raw,candidate,log))
                or sha(receipt)!=item.get("operator_unknown_disposition_v1")
                or sha(raw)!=RAW_SHA or sha(candidate)!=CANDIDATE_SHA):
            return False
        key=logical_asset_identity.frame_asset_key(ep,1)
        a=authority.load_attempt(ep,key,1) or {}
        if (a.get("status")!="FAILED_AFTER_DISPATCH"
                or a.get("failure_class")!=DISPOSITION_CLASS
                or a.get("generation_key")!=authority.stable_generation_key(
                    logical_asset_identity.episode_id(ep),key,1)
                or a.get("runner_request_id")!=REQUEST
                or a.get("result_ref")
                or a.get("provider")!="codex_subscription"
                or a.get("payload_model")!="gpt-image-2.5-flare"
                or a.get("payload_quality")!="high"
                or not a.get("dispatch_committed_at")
                or not a.get("generation_observed_at")):
            return False
        conn=authority._connect()
        try:
            rawrow=conn.query_one(
                "SELECT CONTEXT FROM TB_GENERATION_ATTEMPT "
                "WHERE EPISODE_ID=%s AND LOGICAL_ASSET_KEY=%s AND ATTEMPT_INDEX=1",
                (authority._episode_id(ep),key))
        finally:
            conn.close()
        ctx=authority._context(rawrow or {})
        consent=ctx.get(RECOVERY_FIELD)
        if (not isinstance(consent,dict) or consent.get("ack")!=ACK
                or consent.get("local_acceptance_failed") is not True
                or consent.get("upstream_generation_outcome_unverified") is not True
                or consent.get("upstream_billing_outcome_unverified") is not True
                or consent.get("additional_paid_generation_authorized")!=1):
            return False
        evidence=consent.get("evidence") or {}
        return bool(
            evidence.get("episode")==EPISODE_REL
            and evidence.get("item_id")==ITEM_ID
            and evidence.get("generation_key")==a["generation_key"]
            and evidence.get("request_id")==REQUEST
            and evidence.get("prior_status")=="OUTCOME_UNKNOWN"
            and evidence.get("prior_failure_class")==EXPECTED_ERROR
            and evidence.get("receipt_sha256")==sha(receipt)
            and evidence.get("log_sha256")==sha(log)
            and evidence.get("raw_sha256")==RAW_SHA
            and evidence.get("candidate_sha256")==CANDIDATE_SHA
        )
    except (OSError,ValueError,TypeError,KeyError,DispositionDenied):
        return False

def verify_rearmed(ep, *, queue=None, attempt=None, state=None, record=None) -> dict:
    """Strict read-only Driver recovery gate; only prior rc24 F001."""
    ep=canonical_episode(ep)
    report=source_report(ep,queue=queue,attempt=attempt,state=state)
    if report["status"]!="F001_ALREADY_TERMINAL_DISPOSITION":
        _deny("F001_NOT_TERMINAL")
    q=queue if queue is not None else scheduler_core.load_queue(ep)
    row=next(x for x in q["items"] if int(x["frame"])==1)
    if (row.get("status")!="queued" or
            row.get("operator_unknown_disposition_v1")!=report["receipt_sha256"]):
        _deny("F001_REARM_RECEIPT_INVALID")
    driver=record
    if driver is None:
        import runtime_driver
        driver=runtime_driver.status(ep)
    if (driver.get("driver_state")!="EXITED" or driver.get("exit_code")!="24"
            or driver.get("pid")!=0 or driver.get("liveness")!="DEAD"):
        _deny("F001_DRIVER_RC24_NOT_PROVEN")
    key=logical_asset_identity.frame_asset_key(ep,1)
    a=attempt if attempt is not None else authority.load_attempt(ep,key,1)
    # The existing MySQL row must contain the one-shot operator acknowledgement.
    if a is not None and not isinstance(a.get(RECOVERY_FIELD),dict):
        # load_attempt returns a minimal projection; check CONTEXT below.
        conn=authority._connect()
        try:
            raw=conn.query_one(
                "SELECT STATUS,FAILURE_CLASS,CONTEXT FROM TB_GENERATION_ATTEMPT "
                "WHERE EPISODE_ID=%s AND LOGICAL_ASSET_KEY=%s AND ATTEMPT_INDEX=1",
                (authority._episode_id(ep),key))
        finally:conn.close()
        context=authority._context(raw or {})
    else:
        context=a.get(RECOVERY_FIELD) if a else {}
    approval=context.get(RECOVERY_FIELD) if RECOVERY_FIELD in context else context
    if (not isinstance(approval,dict) or approval.get("ack")!=ACK
            or approval.get("evidence")!=_approval_evidence(report)):
        _deny("F001_OPERATOR_ACK_NOT_CURRENT")
    return {"status":"VISUAL_LOCK_RC24_OPERATOR_DISPOSITION_REARM_RECOVERABLE",
            "read_only":True,"production_authorization":False,
            "frame":1,"item_id":ITEM_ID,
            "receipt_sha256":report["receipt_sha256"],
            "driver_record_sha256":hashlib.sha256(json.dumps(
                driver.get("record") or {},sort_keys=True,ensure_ascii=False,
                separators=(",",":")).encode()).hexdigest()}


def main(argv=None):
    pa=argparse.ArgumentParser()
    pa.add_argument("--episode",required=True)
    pa.add_argument("--commit",action="store_true")
    pa.add_argument("--ack-real-production",action="store_true")
    pa.add_argument("--verify-rearmed",action="store_true")
    pa.add_argument("--ack-upstream-billing-unknown-and-final-attempt",action="store_true")
    args=pa.parse_args(argv)
    try:
        ep=canonical_episode(args.episode)
        out=(commit(ep,acknowledged=(args.ack_real_production and
                  args.ack_upstream_billing_unknown_and_final_attempt))
             if args.commit else verify_rearmed(ep) if args.verify_rearmed
             else source_report(ep))
    except (DispositionDenied,OSError,ValueError,TypeError,KeyError) as exc:
        out={"status":"BLOCKED","reason":str(exc),"read_only":not args.commit}
    print(json.dumps(out,ensure_ascii=False,sort_keys=True))
    return 0 if out.get("status") in {
        "PASS","F001_UNKNOWN_MANUAL_DISPOSITION_ELIGIBLE",
        "F001_ALREADY_TERMINAL_DISPOSITION",
        "VISUAL_LOCK_RC24_OPERATOR_DISPOSITION_REARM_RECOVERABLE"} else 2

if __name__=="__main__":
    raise SystemExit(main())
