"""Recover an observed native Batch RAW from an UNKNOWN attempt, without new image calls.

A capability/model failure is NEVER an input to this path. The only source is
one immutable, SHA-verified local provider RAW with its original provider receipt,
the original Production Ledger transaction, and the original MySQL Attempt (#1, or the narrowly verified Episode13 #2).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

import canvas_normalize
import generation_attempt_authority as authority
import image_blocked_recovery as legacy
import logical_asset_identity
import native_baseline_source_freeze
import production_ledger
import production_recovery
import provider_capability
import provider_receipt_persistence
import scheduler_core

ROOT=Path(__file__).resolve().parents[2]
FAILURE="ASPECT_RATIO_MISMATCH"
SHA64=re.compile(r"[0-9a-f]{64}\Z")
HEX32=re.compile(r"[0-9a-f]{32}\Z")

class PreservedRawDenied(RuntimeError):
    pass

def _deny(why):
    raise PreservedRawDenied(why)

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def _receipt_digest(payload):
    return hashlib.sha256(json.dumps(payload,sort_keys=True,
        ensure_ascii=False,separators=(",",":")).encode("utf-8")).hexdigest()

def _receipt(ep, item, plan):
    path=Path(plan["provider_receipt"]).resolve()
    if not path.is_relative_to(ep.resolve()):
        _deny("PROVIDER_RECEIPT_PATH_OUTSIDE_EPISODE")
    loaded=provider_receipt_persistence.load_by_path(ep,path)
    value=(loaded or {}).get("payload")
    # The V2 canonical store is MySQL; legacy receipt files were retired.
    # Never manufacture a receipt file or silently fall back to missing JSON.
    if ((loaded or {}).get("source")!="mysql"
        or not (loaded or {}).get("receipt_id")
        or not (loaded or {}).get("legacy_path")
        or not isinstance(value,dict)):
        _deny("CANONICAL_MYSQL_PROVIDER_RECEIPT_REQUIRED")
    return path,value,loaded

def eligible(ep,item):
    """Read-only exact scope: native subscription/Batch, trusted bytes and UNKNOWN."""
    try:
        ep=Path(ep).resolve()
        if (item.get("status")!="external_blocked" or item.get("scope")!="batch"
                or item.get("kind")!="original" or item.get("technical_failure_code")!=FAILURE
                or item.get("output_path") or item.get("candidate_output_path")):
            return None
        plan=legacy.inspect_item(ep,item)
        if not plan.get("auto_resolvable") or plan.get("code")!=FAILURE:
            return None
        receipt_path,receipt,loaded=_receipt(ep,item,plan)
        frame=int(item["frame"])
        key=logical_asset_identity.frame_asset_key(ep,frame)
        state=authority.load_asset_state(ep,key)
        idx=int(receipt.get("attempt_index") or 0)
        if idx not in (1,2):
            return None
        # Only the three network-recovered Episode13 frames can use a second
        # real Attempt. Frame15 already succeeded and cannot enter this gate.
        if idx==2:
            first=authority.load_attempt(ep,key,1) or {}
            if (ep.name!="13_失物归还的那扇门"
                or ep.parent.name!="00_独立篇"
                or frame not in (5,10)
                or int(item.get("native_network_terminal_rearm_count") or 0)!=1
                or int(item.get("native_network_capability_requeue_count") or 0)!=1
                or first.get("status")!="FAILED_AFTER_DISPATCH"
                or first.get("failure_class")!="IMAGE_TOOL_NETWORK_ERROR_DURABLE_RECEIPT"
                or first.get("provider")!="codex_subscription"
                or first.get("result_ref")):
                return None
        old=authority.load_attempt(ep,key,idx) or {}
        gen=authority.stable_generation_key(logical_asset_identity.episode_id(ep),key,idx)
        raw=Path(plan["raw_path"]).resolve()
        if (old.get("status")!="OUTCOME_UNKNOWN"
            or old.get("failure_class")!="generation_failed_before_candidate_commit"
            or old.get("provider")!="codex_subscription"
            or old.get("payload_model")!=item.get("model")
            or old.get("payload_quality")!=item.get("quality")
            or not old.get("dispatch_committed_at")
            or not old.get("generation_observed_at")
            or old.get("result_ref") not in (None,"")
            or old.get("generation_key")!=gen
            or int(state.get("attempts_consumed") or 0)!=idx
            or state.get("active_attempt_index") is not None
            or int(state.get("fencing_counter") or 0)!=idx
            or (idx==2 and old.get("runner_request_id")!=receipt.get("request_id"))
            or receipt.get("generation_key")!=gen
            or int(receipt.get("attempt_index") or 0)!=idx
            or int(receipt.get("fencing_token") or 0)!=idx
            or receipt.get("generation_route")!="codex_subscription"
            or receipt.get("payload_model")!=old.get("payload_model")
            or receipt.get("payload_quality")!=old.get("payload_quality")
            or receipt.get("normalize_decision")!=FAILURE
            or str(receipt.get("frame") or "").zfill(2)!=f"{frame:02d}"
            or receipt.get("frame_contract_sha256")!=(item.get("frame_contract") or {}).get("contract_sha256")
            or receipt.get("prompt_package_sha256")!=(item.get("prompt_package") or {}).get("package_sha256")
            or not HEX32.fullmatch(str(receipt.get("request_id") or ""))
            or not SHA64.fullmatch(str(receipt.get("raw_sha256") or ""))
            or sha(raw)!=receipt["raw_sha256"]):
            return None
        return {**plan,"receipt_path":receipt_path,"raw_path":raw,"generation_key":gen,
                "asset_key":key,"frame":frame,"item_id":item["id"],
                "attempt_index":idx,
                "raw_sha256":receipt["raw_sha256"],
                "receipt_sha256":_receipt_digest(receipt),
                "receipt_legacy_path":loaded["legacy_path"],
                "receipt_id":loaded["receipt_id"],
                "frame_contract_sha256":receipt["frame_contract_sha256"],
                "prompt_package_sha256":receipt["prompt_package_sha256"]}
    except Exception:
        return None

@contextmanager
def _freeze_three(plan,output):
    """Freeze RAW/candidate files; MySQL provider receipt is row-locked below."""
    paths=(Path(plan["raw_path"]),Path(output))
    if os.name!="nt" or len({p.resolve() for p in paths})!=2:
        _deny("WINDOWS_EXCLUSIVE_SOURCE_FREEZE_REQUIRED")
    handles=[]
    try:
        for path in sorted(paths,key=lambda p:str(p).casefold()):
            if not path.is_file():
                _deny("PROOF_FILE_MISSING")
            handles.append(native_baseline_source_freeze._windows_open_shared_read(path))
        yield
    finally:
        for handle in reversed(handles):
            native_baseline_source_freeze._windows_close(handle)

def _mysql_reconcile(ep,plan,output,output_sha):
    """Only terminal UNKNOWN -> SUCCEEDED, under exact original MySQL fence."""
    with _freeze_three(plan,output):
        conn=authority._connect()
        try:
            with conn.transaction():
                # File SHA and persisted Provider RAW must remain the same at CAS.
                if sha(plan["raw_path"])!=plan["raw_sha256"] or sha(output)!=output_sha:
                    _deny("SOURCE_CHANGED_DURING_RECONCILIATION")
                receipt_row=conn.query_one(
                    "SELECT RECEIPT_ID,STATUS,PAYLOAD FROM TB_PROVIDER_RECEIPT "
                    "WHERE EPISODE_ID=%s AND LEGACY_PATH=%s FOR UPDATE",
                    (provider_receipt_persistence._episode_id(ep),
                     plan["receipt_legacy_path"]))
                if not receipt_row or receipt_row.get("RECEIPT_ID")!=plan["receipt_id"] or receipt_row.get("STATUS")!="FINALIZED":
                    _deny("CANONICAL_RECEIPT_LOCK_MISSING")
                raw_payload=receipt_row.get("PAYLOAD")
                if isinstance(raw_payload,(bytes,bytearray)): raw_payload=raw_payload.decode("utf-8")
                if isinstance(raw_payload,str): raw_payload=json.loads(raw_payload)
                if (not isinstance(raw_payload,dict)
                    or _receipt_digest(raw_payload)!=plan["receipt_sha256"]
                    or raw_payload.get("raw_sha256")!=plan["raw_sha256"]
                    or raw_payload.get("generation_key")!=plan["generation_key"]
                    or (raw_payload.get("release_canvas") or {}).get("sha256")!=output_sha):
                    _deny("CANONICAL_MYSQL_RECEIPT_CHANGED")
                idx=int(plan.get("attempt_index") or 1)
                if idx not in (1,2):
                    _deny("INVALID_PRESERVED_RAW_ATTEMPT_INDEX")
                state=authority._row(conn,authority._episode_id(ep),plan["asset_key"])
                row=conn.query_one(
                    "SELECT * FROM TB_GENERATION_ATTEMPT WHERE EPISODE_ID=%s "
                    "AND LOGICAL_ASSET_KEY=%s AND ATTEMPT_INDEX=%s FOR UPDATE",
                    (authority._episode_id(ep),plan["asset_key"],idx))
                context=authority._context(row) if row else {}
                if (not state or not row
                    or int(state.get("ATTEMPTS_CONSUMED") or 0)!=idx
                    or state.get("ACTIVE_ATTEMPT_INDEX") is not None
                    or int(state.get("FENCING_COUNTER") or 0)!=idx
                    or int(row.get("FENCING_TOKEN") or 0)!=idx
                    or (idx==2 and context.get("runner_request_id") is None)
                    or (idx==2 and context.get("runner_request_id")!=raw_payload.get("request_id"))
                    or row.get("STATUS")!="OUTCOME_UNKNOWN"
                    or row.get("FAILURE_CLASS")!="generation_failed_before_candidate_commit"
                    or row.get("RESULT_REF") not in (None,"")
                    or row.get("GENERATION_KEY")!=plan["generation_key"]
                    or row.get("PROVIDER")!="codex_subscription"
                    or context.get("scope")!="batch"
                    or context.get("queue_item_id")!=plan["item_id"]
                    or context.get("frame_contract_sha256")!=plan["frame_contract_sha256"]
                    or context.get("prompt_package_sha256")!=plan["prompt_package_sha256"]
                    or row.get("PAYLOAD_MODEL")!=raw_payload.get("payload_model")
                    or row.get("PAYLOAD_QUALITY")!=raw_payload.get("payload_quality")
                    or row.get("DISPATCH_COMMITTED_AT") is None
                    or row.get("GENERATION_OBSERVED_AT") is None):
                    _deny("UNKNOWN_GENERATION_FENCE_CHANGED")
                result=conn.execute(
                    "UPDATE TB_GENERATION_ATTEMPT SET STATUS='SUCCEEDED', TERMINAL_AT=%s, "
                    "RESULT_REF=%s WHERE EPISODE_ID=%s AND LOGICAL_ASSET_KEY=%s "
                    "AND ATTEMPT_INDEX=%s AND STATUS='OUTCOME_UNKNOWN' "
                    "AND GENERATION_KEY=%s AND FENCING_TOKEN=%s "
                    "AND FAILURE_CLASS='generation_failed_before_candidate_commit' AND RESULT_REF IS NULL",
                    (authority._utcnow(),str(output),authority._episode_id(ep),
                     plan["asset_key"],idx,plan["generation_key"],idx))
                if result!=1:
                    _deny("UNKNOWN_GENERATION_CAS_LOST")
                if sha(plan["raw_path"])!=plan["raw_sha256"] or sha(output)!=output_sha:
                    _deny("SOURCE_CHANGED_BEFORE_MYSQL_COMMIT")
        finally:
            conn.close()

def recover_one(ep,frame):
    """Never invokes Provider or reserves an Attempt. Queue mutation is exclusive."""
    ep=Path(ep).resolve()
    try:
        with scheduler_core.queue_transaction(ep):
            q=scheduler_core.load_queue(ep)
            row=next((x for x in q.get("items",[])
                      if x.get("scope")=="batch" and int(x.get("frame") or 0)==int(frame)),None)
            if row is None:
                return {"status":"BLOCKED","reason":"FRAME_NOT_IN_BATCH_QUEUE"}
            plan=eligible(ep,row)
            if plan is None:
                return {"status":"BLOCKED","reason":"UNVERIFIED_PRESERVED_RAW_OR_ATTEMPT"}
            output=Path(plan["output_path"])
            if output.exists():
                return {"status":"BLOCKED","reason":"CANDIDATE_ALREADY_EXISTS_REQUIRES_RECONCILIATION"}
            width,height,_=canvas_normalize.read_canvas(ep)
            normalization=canvas_normalize.normalize_provider_crop_exception(
                Path(plan["raw_path"]),output,width,height,
                reason="verified original native RAW, deterministic ratio exception only; no regeneration")
            with Image.open(output) as image:
                if image.format!="PNG" or image.size!=(width,height):
                    _deny("NORMALIZED_CANVAS_INVALID")
                image.verify()
            output_sha=sha(output)
            # Finalize receipt BEFORE SQL, then re-prove the same raw and
            # this fixed output under Windows read-only source freeze.
            receipt=provider_capability.finalize_receipt(plan["receipt_path"],normalization,output)
            latest=provider_receipt_persistence.load_by_path(ep,plan["receipt_path"])
            if (not latest or latest.get("source")!="mysql"
                or latest.get("receipt_status")!="FINALIZED"
                or latest.get("receipt_id")!=plan["receipt_id"]):
                _deny("FINALIZED_MYSQL_RECEIPT_NOT_DURABLE")
            plan["receipt_sha256"]=_receipt_digest(latest["payload"])
            _mysql_reconcile(ep,plan,output,output_sha)
            # Separate ledger/queue stage: fail closed if this late commit
            # cannot be reconciled. Never starts a second image Attempt.
            production_ledger.cmd_recover_success(SimpleNamespace(
                episode_dir=str(ep),frame=f"{int(frame):02d}",
                path=str(output),provider_receipt=str(plan["receipt_path"]),
                transaction_id=str(plan["transaction_id"]),runner_request_id=None,
                recovery_reason="sha_verified_provider_raw_post_unknown"))
            row["status"]="generated"
            row["output_path"]=output.resolve().relative_to(ROOT.resolve()).as_posix()
            row["completed_at"]=production_recovery.now()
            row["last_error"]=None
            row["attempt_index"]=int(plan.get("attempt_index") or 1)
            row["generation_key"]=plan["generation_key"]
            row["normalization_recovery"]={"kind":"verified_provider_raw_after_unknown",
                                          "crop_applied":bool(normalization.get("crop_applied")),
                                          "candidate_sha256":output_sha,"provider_receipt":receipt["path"]}
            row.pop("technical_failure_code",None)
            row.pop("external_block_reason",None)
            row.pop("retry_exhausted",None)
            production_recovery.mark_terminal(ep,row,"COMMITTED",recovery="verified_provider_raw_after_unknown")
            scheduler_core.save_queue(ep,q)
            return {"status":"PASS","frame":int(frame),"provider_calls":0,"attempts_reserved":0,
                    "candidate_sha256":output_sha}
    except scheduler_core.QueueMutationBusy:
        return {"status":"BLOCKED","reason":"QUEUE_MUTATION_BUSY"}
    except PreservedRawDenied as exc:
        return {"status":"BLOCKED","reason":str(exc)}
