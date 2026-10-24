"""F001 Attempt #2: no-generation, SHA-proven direct Codex RAW reconciliation.

Bound to the original live F001, the canonical MySQL provider receipt,
normalization evidence, immutable direct thread archive and consumed #2 fence.
This is image-generation accounting only, NOT image review, entitlement, or
another Provider call. Preserves Attempt #1 and all past Ledger failures.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import os
import re
from contextlib import contextmanager
from pathlib import Path
from PIL import Image

import codex_user_runner
import episode_state_persistence
import f001_unknown_operator_disposition as first
import generation_attempt_authority as authority
import logical_asset_identity as identity
import native_baseline_source_freeze as freeze
import production_native_baseline_proof as baseline
import production_recovery
import production_ledger_persistence as ledger_store
import provider_receipt_persistence
import runtime_driver
import scheduler_core
from platform.repository.mysql.mysql_production_attempt_repository import MySqlProductionAttemptRepository
from platform.repository.mysql.mysql_production_frame_repository import MySqlProductionFrameRepository
from platform.repository.mysql.mysql_production_ledger_authority_repository import MySqlProductionLedgerAuthorityRepository
import episode_identity

ROOT = Path(__file__).resolve().parents[2]
RID = "cb207066b51f4641bd61722cdc7c93fc"
GEN = "ga1-fd28fc4f8b7233c7e194de17372c47476ff963d553bcc8b7-a2"
FRAME_ID = "ead88592f160"
SOURCE_ERROR = "NATIVE_BASELINE_PIXEL_TOOL_PROOF_UNVERIFIED"
RAW_REL = "media/raw/01-1792808990.png"
CAND_REL = "media/candidates/scheduled/01-ead88592f160-a3.png"
LOG_REL = "meta/image-workers/01-ead88592f160-a3.jsonl"
LIFE_REL = "meta/image-workers/01-ead88592f160-a3.lifecycle.json"
RECEIPT_REL = "meta/provider-receipts/01-1792809074.json"
CANVAS = (1080, 1350)
STATE_FLAG = "F001_A2_NATIVE_DIRECT_SHA_RECONCILED"

class ProvenanceDenied(RuntimeError):
    pass

def deny(msg):
    raise ProvenanceDenied(msg)

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def _assert_driver(ep):
    d=runtime_driver.status(ep)
    if (d.get("driver_state")!="EXITED" or d.get("exit_code")!="24"
            or d.get("pid")!=0 or d.get("liveness")!="DEAD"):
        deny("DRIVER_LIVE_OR_NON_RC24")
    return d

def _decode(path):
    if not Path(path).is_file() or Path(path).is_symlink():
        deny("PIXEL_FILE_MISSING_OR_SYMLINK")
    with Image.open(path) as im:
        if im.format!="PNG":
            deny("PROVIDER_IMAGE_NOT_PNG")
        im.verify()
    with Image.open(path) as im:
        return im.size

def inspect(ep: Path, *, queue=None, require_blocked=True) -> dict:
    ep=first.canonical_episode(ep)
    _assert_driver(ep)
    current,source=episode_state_persistence.load_with_source(ep)
    if (source!="mysql" or current.get("current_state")!="STORYBOARD_LOCKED"):
        deny("STAGE_CHANGED")
    q=queue if queue is not None else scheduler_core.load_queue(ep)
    rows=q.get("items") or []
    if len(rows)!=4 or {int(x.get("frame") or 0) for x in rows}!={1,5,45,47}:
        deny("FOUR_FRAME_QUEUE_CHANGED")
    row=next(x for x in rows if int(x.get("frame") or 0)==1)
    if (row.get("id")!=FRAME_ID or row.get("scope")!="visual_lock"
            or row.get("kind")!="original" or row.get("model")!="gpt-image-2.5-flare"
            or row.get("quality")!="high"
            or row.get("status") not in ({"external_blocked","generated"} if not require_blocked else {"external_blocked"})
            or any(x.get("status")!="queued" or x.get("depends_on")!=[1]
                   for x in rows if x is not row)):
        deny("FRAME_OR_DEPENDENCIES_CHANGED")
    if row.get("status")=="external_blocked" and (
            row.get("technical_failure_code")!="IMAGE_BACKEND_ERROR"
            or SOURCE_ERROR not in str(row.get("last_error") or "")):
        deny("UNKNOWN_BLOCK_REASON_CHANGED")
    if not first.operator_second_attempt_source(ep,row):
        deny("FIRST_ATTEMPT_DISPOSITION_NOT_PROVEN")
    key=identity.frame_asset_key(ep,1)
    s=authority.load_asset_state(ep,key)
    a=authority.load_attempt(ep,key,2) or {}
    if (s.get("attempts_consumed")!=2 or s.get("fencing_counter")!=2
            or s.get("active_attempt_index") is not None
            or authority.load_attempt(ep,key,3) is not None
            or a.get("status") not in ({"OUTCOME_UNKNOWN","SUCCEEDED"} if not require_blocked else {"OUTCOME_UNKNOWN"})
            or (a.get("status")=="OUTCOME_UNKNOWN" and a.get("failure_class")!=SOURCE_ERROR)
            or a.get("generation_key")!=GEN or a.get("runner_request_id")!=RID
            or a.get("provider")!="codex_subscription"
            or a.get("payload_model")!="gpt-image-2.5-flare"
            or a.get("payload_quality")!="high"
            or not a.get("dispatch_committed_at") or not a.get("generation_observed_at")
            or (a.get("status")=="OUTCOME_UNKNOWN" and a.get("result_ref"))):
        deny("ATTEMPT2_AUTHORITY_DRIFT")
    raw=ep/RAW_REL; candidate=ep/CAND_REL; log=ep/LOG_REL
    life=ep/LIFE_REL
    if not life.is_file():
        deny("WORKER_LIFECYCLE_MISSING")
    lifecycle=json.loads(life.read_text(encoding="utf-8"))
    if (lifecycle.get("item_id")!=FRAME_ID or lifecycle.get("state")!="BLOCKED"
            or lifecycle.get("runner_request_id")!=RID
            or lifecycle.get("generation_key")!=GEN
            or SOURCE_ERROR not in str(lifecycle.get("error") or "")):
        deny("WORKER_LIFECYCLE_DRIFT")
    if _decode(raw)!=(1122,1402) or _decode(candidate)!=CANVAS:
        deny("PIXEL_CANVAS_CHANGED")
    proof=baseline.verify_direct_runner_archived_pixel(log,raw,RID)
    if (not proof or proof.get("proof_kind")!="TRUSTED_NATIVE_DIRECT_THREAD_SCOPED_IMAGE_SHA"
            or proof.get("review_pass") is not False):
        deny("NATIVE_DIRECT_ORIGINAL_SOURCE_UNVERIFIED")
    receipt_path=codex_user_runner.task_result_path(RID)
    receipt=json.loads(receipt_path.read_text(encoding="utf-8"))
    artifact=(receipt_path.parent.parent/"image-artifacts"/RID/
              receipt["evidence"]["generated_artifacts"][0]).resolve()
    if (not artifact.is_relative_to((receipt_path.parent.parent/"image-artifacts"/RID).resolve())
            or not artifact.is_file() or artifact.is_symlink()
            or sha(artifact)!=sha(raw)):
        deny("NATIVE_THREAD_ARCHIVE_CHANGED")
    provider_path=ep/RECEIPT_REL
    loaded=provider_receipt_persistence.load_by_path(ep,provider_path)
    v=(loaded or {}).get("payload") or {}
    pkg=row.get("prompt_package") or {}
    fc=(row.get("frame_contract") or {}).get("contract_sha256")
    if ((loaded or {}).get("source")!="mysql"
            or not (loaded or {}).get("receipt_id")
            or (loaded or {}).get("status") not in {"FINALIZED",None}
            or v.get("request_id")!=RID or v.get("generation_key")!=GEN
            or v.get("attempt_index")!=2 or v.get("fencing_token")!=2
            or v.get("generation_route")!="codex_subscription"
            or v.get("payload_model")!="gpt-image-2.5-flare"
            or v.get("payload_quality")!="high"
            or v.get("raw_sha256")!=sha(raw)
            or (v.get("release_canvas") or {}).get("sha256")!=sha(candidate)
            or v.get("frame_contract_sha256")!=fc
            or v.get("prompt_package_sha256")!=pkg.get("package_sha256")
            or not re.fullmatch("[0-9a-f]{64}",str(fc or ""))):
        deny("MYSQL_PROVIDER_RECEIPT_SOURCE_DRIFT")
    return {
        "status":"F001_ATTEMPT2_NATIVE_RAW_RECONCILABLE" if a["status"]=="OUTCOME_UNKNOWN" else "F001_ATTEMPT2_ALREADY_RECONCILED",
        "episode":ep,"queue_item_id":FRAME_ID,"raw":raw,"candidate":candidate,
        "log":log,"archive":artifact,"runner_receipt":receipt_path,"life":life,
        "provider_receipt_id":loaded["receipt_id"],"provider_legacy_path":loaded["legacy_path"],
        "provider_receipt_payload":v,"provider_receipt_sha256":hashlib.sha256(json.dumps(v,sort_keys=True,ensure_ascii=False,separators=(",",":")).encode()).hexdigest(),
        "raw_sha256":sha(raw),"candidate_sha256":sha(candidate),"log_sha256":sha(log),
        "runner_receipt_sha256":sha(receipt_path),"archive_sha256":sha(artifact),
        "thread_id":proof["native_codex_thread_id"],"generation_key":GEN,
        "request_id":RID,"review_pass":False,"model_calls":0,"new_paid_attempts":0,
        "attempts_consumed":2,
        "item":row,"proof_kind":proof["proof_kind"],
    }

@contextmanager
def _freeze_sources(paths):
    if os.name!="nt":
        deny("WINDOWS_EXCLUSIVE_PROOF_SOURCE_FREEZE_REQUIRED")
    handles=[]
    try:
        for f in sorted({Path(x).resolve() for x in paths},key=lambda p:str(p).casefold()):
            handles.append(freeze._windows_open_shared_read(f))
        yield
    finally:
        for h in reversed(handles):
            freeze._windows_close(h)

def _ledger_repair(doc,source):
    data=copy.deepcopy(doc)
    f=(data.get("frames") or {}).get("01") or {}
    attempts=f.get("attempts") or []
    if (len(attempts)!=3 or f.get("status")!="TECH_FAILED"
            or f.get("current_candidate") is not None):
        deny("LEDGER_ATTEMPT_HISTORY_DRIFT")
    a=attempts[-1]
    if (a.get("result")!="technical_failure"
            or a.get("kind")!="original"
            or (a.get("request") or {}).get("frame_contract_sha256")!=
                (source["item"].get("frame_contract") or {}).get("contract_sha256")
            or (a.get("request") or {}).get("model")!="gpt-image-2.5-flare"
            or (a.get("request") or {}).get("quality")!="high"
            or SOURCE_ERROR not in str((a.get("error") or {}).get("message") or "")
            or (a.get("provider_attempt") or {}).get("status")!="NOT_INVOKED"
            or f.get("technical_failures",[])[-1].get("attempt_id")!=a.get("attempt_id")):
        deny("LEDGER_LAST_FAILURE_SOURCE_DRIFT")
    import production_ledger as core
    core.verify_attempt_visual_provenance(source["episode"],a)
    core.verify_attempt_frame_contract_provenance(source["episode"],"01",a)
    now=core.now_iso()
    rel=source["candidate"].relative_to(ROOT).as_posix()
    cand={"path":rel,"sha256":source["candidate_sha256"],"width":CANVAS[0],
          "height":CANVAS[1],"recorded_at":now,"kind":"original",
          "attempt_id":a["attempt_id"],"generation_key":GEN,"generation_attempt_index":2}
    a["recovery_correction"]={
        "at":now,"reason":"direct_native_RAW_source_verified_after_NP01_candidate_mismatch",
        "previous_result":a["result"],"previous_error":copy.deepcopy(a["error"]),
        "previous_provider_attempt":copy.deepcopy(a.get("provider_attempt")),
        "runner_request_id":RID,"generation_key":GEN,"attempt_index":2,
        "raw_png_sha256":source["raw_sha256"],"normalized_png_sha256":source["candidate_sha256"],
        "runner_receipt_sha256":source["runner_receipt_sha256"],
        "provider_receipt_sha256":source["provider_receipt_sha256"],
        "thread_id":source["thread_id"],"review_pass":False,"provider_model_attested":False}
    a["provider_attempt"]={**(a.get("provider_attempt") or {}),"status":"COMPLETED",
        "runner_request_id":RID,"completed_at":now,"proof_kind":source["proof_kind"],
        "payload_model_attested":False,"native_image_generation_jsonl_events":0}
    a.pop("error",None)
    a["result"]="success";a["candidate"]=cand
    a["generation_key"]=GEN;a["generation_attempt_index"]=2;a["completed_at"]=now
    f["current_candidate"]=cand;f["status"]="ORIGINAL_READY"
    f["technical_failures"][-1]["recovered_at"]=now
    f["technical_failures"][-1]["recovered_runner_request_id"]=RID
    data["updated_at"]=now
    return data

def _typed_lock(conn,storage_id,frame):
    rows=frame.get("attempts") or []
    if len(rows)!=3:
        deny("TYPED_LEDGER_HISTORY_COUNT_DRIFT")
    latest=rows[-1]
    a=conn.query_one("SELECT EPISODE_ID,FRAME_NO,ATTEMPT_NO,ATTEMPT_ID,"
        "ATTEMPT_KIND,STATUS,PAYLOAD FROM TB_PRODUCTION_ATTEMPT "
        "WHERE EPISODE_ID=%s AND FRAME_NO=1 AND ATTEMPT_NO=3 FOR UPDATE",(storage_id,))
    f=conn.query_one("SELECT EPISODE_ID,FRAME_NO,STATUS,CURRENT_ATTEMPT_ID,"
        "CONTRACT_SHA256,APPROVED_ARTIFACT_ID FROM TB_PRODUCTION_FRAME "
        "WHERE EPISODE_ID=%s AND FRAME_NO=1 FOR UPDATE",(storage_id,))
    if not a or not f:deny("TYPED_LEDGER_RECORDS_MISSING")
    payload=a["PAYLOAD"]
    if isinstance(payload,memoryview):payload=payload.tobytes()
    if isinstance(payload,(bytes,bytearray)):payload=payload.decode("utf-8")
    if isinstance(payload,str):payload=json.loads(payload)
    if (a.get("EPISODE_ID")!=storage_id or int(a.get("FRAME_NO") or 0)!=1
            or int(a.get("ATTEMPT_NO") or 0)!=3
            or a.get("ATTEMPT_ID")!=latest.get("attempt_id")
            or a.get("ATTEMPT_KIND")!=latest.get("kind")
            or a.get("STATUS")!=latest.get("result") or payload!=latest
            or f.get("EPISODE_ID")!=storage_id
            or f.get("STATUS")!=frame.get("status")
            or f.get("CURRENT_ATTEMPT_ID")!=latest.get("attempt_id")
            or f.get("CONTRACT_SHA256")!=ledger_store._contract_sha(frame)
            or f.get("APPROVED_ARTIFACT_ID") is not None):
        deny("TYPED_LEDGER_IDENTITY_DRIFT")

def _verify_repaired(doc,source):
    frame=(doc.get("frames") or {}).get("01") or {}
    rows=frame.get("attempts") or []
    if len(rows)!=3 or frame.get("status")!="ORIGINAL_READY":
        deny("RECONCILED_LEDGER_NOT_READY")
    a=rows[-1]; c=a.get("recovery_correction") or {}
    candidate=frame.get("current_candidate") or {}
    if (a.get("result")!="success" or a.get("generation_attempt_index")!=2
            or a.get("generation_key")!=GEN or a.get("candidate")!=candidate
            or candidate.get("path")!=source["candidate"].relative_to(ROOT).as_posix()
            or candidate.get("sha256")!=source["candidate_sha256"]
            or c.get("runner_request_id")!=RID
            or c.get("raw_png_sha256")!=source["raw_sha256"]
            or c.get("normalized_png_sha256")!=source["candidate_sha256"]
            or c.get("runner_receipt_sha256")!=source["runner_receipt_sha256"]
            or c.get("provider_receipt_sha256")!=source["provider_receipt_sha256"]
            or c.get("review_pass") is not False):
        deny("LEDGER_RECOVERY_PROOF_CHANGED")

def _create_unreviewed_proof(ep,source):
    target=ep/"meta/runtime/native-baseline-frame01-tool-proof.json"
    proof=baseline.verify_direct_runner_archived_pixel(source["log"],source["raw"],RID)
    if not proof:deny("RAW_PROVENANCE_LOST_AFTER_SQL")
    pkg=source["item"].get("prompt_package") or {}
    proof.update(schema_version=1,status="OBSERVED_AWAITING_INDEPENDENT_VISUAL_REVIEW",
        episode=str(ep),queue_item_id=FRAME_ID,logical_asset_frame=1,
        generation_key=GEN,attempt_index=2,fencing_token=2,
        runner_request_id=RID,raw_png_sha256=source["raw_sha256"],
        normalized_png_sha256=source["candidate_sha256"],
        frame_contract_sha256=pkg.get("frame_contract_sha256"),
        prompt_package_sha256=pkg.get("package_sha256"),
        visual_review_pass=False,review_pass=False)
    if target.is_file():
        if json.loads(target.read_text(encoding="utf-8"))!=proof:
            deny("UNREVIEWED_BASELINE_PROOF_DRIFT")
        return
    target.parent.mkdir(parents=True,exist_ok=True)
    with target.open("x",encoding="utf-8",newline="\n") as fp:
        json.dump(proof,fp,ensure_ascii=False,sort_keys=True,indent=2)
        fp.write("\n")

def commit(ep:Path, *, expected_sha:str, acknowledged:bool=False):
    if not acknowledged:deny("EXPLICIT_NO_REGENERATION_ACK_REQUIRED")
    ep=first.canonical_episode(ep)
    with scheduler_core.queue_transaction(ep):
        source=inspect(ep,require_blocked=False)
        if source["runner_receipt_sha256"]!=expected_sha:
            deny("RUNNER_RECEIPT_SHA_FENCE_CHANGED")
        key=identity.frame_asset_key(ep,1);eid=identity.episode_id(ep)
        paths=[source[k] for k in ("raw","candidate","log","archive",
                "runner_receipt","life")]
        already=source["status"]=="F001_ATTEMPT2_ALREADY_RECONCILED"
        conn=authority._connect()
        try:
            with _freeze_sources(paths),conn.transaction():
                fresh=inspect(ep,queue=scheduler_core.load_queue(ep),
                              require_blocked=False)
                if fresh["runner_receipt_sha256"]!=expected_sha:
                    deny("PROOF_CHANGED_DURING_MYSQL_TRANSACTION")
                st=authority._row(conn,eid,key)
                row=conn.query_one("SELECT * FROM TB_GENERATION_ATTEMPT "
                    "WHERE EPISODE_ID=%s AND LOGICAL_ASSET_KEY=%s "
                    "AND ATTEMPT_INDEX=2 FOR UPDATE",(eid,key))
                if (not st or not row or int(st.get("ATTEMPTS_CONSUMED") or 0)!=2
                        or st.get("ACTIVE_ATTEMPT_INDEX") is not None
                        or int(st.get("FENCING_COUNTER") or 0)!=2
                        or row.get("GENERATION_KEY")!=GEN
                        or int(row.get("FENCING_TOKEN") or 0)!=2
                        or row.get("PROVIDER")!="codex_subscription"
                        or authority._context(row).get("runner_request_id")!=RID):
                    deny("ATTEMPT2_MYSQL_IDENTITY_DRIFT")
                if (already and row.get("STATUS")!="SUCCEEDED"
                        or not already and (row.get("STATUS")!="OUTCOME_UNKNOWN"
                        or row.get("FAILURE_CLASS")!=SOURCE_ERROR or row.get("RESULT_REF"))):
                    deny("ATTEMPT2_UNEXPECTED_MYSQL_STATUS")
                pr=conn.query_one("SELECT RECEIPT_ID,STATUS,PAYLOAD "
                    "FROM TB_PROVIDER_RECEIPT WHERE EPISODE_ID=%s "
                    "AND LEGACY_PATH=%s FOR UPDATE",
                    (provider_receipt_persistence._episode_id(ep),
                     source["provider_legacy_path"]))
                val=pr.get("PAYLOAD") if pr else None
                if isinstance(val,memoryview):val=val.tobytes()
                if isinstance(val,(bytes,bytearray)):val=val.decode("utf-8")
                if isinstance(val,str):val=json.loads(val)
                if (not pr or pr.get("STATUS")!="FINALIZED"
                        or pr.get("RECEIPT_ID")!=source["provider_receipt_id"]
                        or val!=source["provider_receipt_payload"]):
                    deny("PROVIDER_RECEIPT_MYSQL_SOURCE_DRIFT")
                storage_id=episode_identity.storage_episode_id(ep)
                locked=conn.query_one("SELECT SHA256 FROM TB_PRODUCTION_LEDGER_AUTHORITY "
                    "WHERE EPISODE_ID=%s FOR UPDATE",(storage_id,))
                repo=MySqlProductionLedgerAuthorityRepository(conn)
                prior=repo.get(storage_id)
                if not locked or not prior or prior["sha256"]!=locked["SHA256"]:
                    deny("LEDGER_AUTHORITY_SHA_CHANGED")
                _typed_lock(conn,storage_id,prior["document"]["frames"]["01"])
                if already:
                    _verify_repaired(prior["document"],source)
                    if row.get("RESULT_REF")!=str(source["candidate"]):
                        deny("ALREADY_SUCCEEDED_RESULT_DRIFT")
                else:
                    updated=_ledger_repair(prior["document"],source)
                    repo.upsert(storage_id,updated)
                    counts=ledger_store._persist_projection(storage_id,updated,
                        MySqlProductionFrameRepository(conn),
                        MySqlProductionAttemptRepository(conn),frame_keys={"01"})
                    if counts!=(1,3):deny("TYPED_LEDGER_PROJECTION_COUNT_DRIFT")
                    _typed_lock(conn,storage_id,updated["frames"]["01"])
                    changed=conn.execute("UPDATE TB_GENERATION_ATTEMPT SET "
                        "STATUS='SUCCEEDED',FAILURE_CLASS=NULL,RESULT_REF=%s "
                        "WHERE EPISODE_ID=%s AND LOGICAL_ASSET_KEY=%s "
                        "AND ATTEMPT_INDEX=2 AND STATUS='OUTCOME_UNKNOWN' "
                        "AND FAILURE_CLASS=%s AND GENERATION_KEY=%s "
                        "AND FENCING_TOKEN=2 AND RESULT_REF IS NULL",
                        (str(source["candidate"]),eid,key,SOURCE_ERROR,GEN))
                    if changed!=1:deny("GENERATION_ATTEMPT2_CAS_LOST")
                if any(sha(source[k])!=source[v] for k,v in (
                    ("raw","raw_sha256"),("candidate","candidate_sha256"),
                    ("log","log_sha256"),("archive","archive_sha256"),
                    ("runner_receipt","runner_receipt_sha256"))):
                    deny("PIXELS_CHANGED_BEFORE_COMMIT")
            ledger_store.invalidate(ep)
        finally:
            conn.close()
        _create_unreviewed_proof(ep,source)
        q=scheduler_core.load_queue(ep)
        item=next(r for r in q["items"] if int(r.get("frame") or 0)==1)
        if item.get("id")!=FRAME_ID:deny("QUEUE_IDENTITY_CHANGED")
        rel=source["candidate"].relative_to(ROOT).as_posix()
        if item.get("status")=="generated":
            if (item.get("output_path")!=rel or item.get("generation_key")!=GEN
                    or int(item.get("attempt_index") or 0)!=2):
                deny("ALREADY_GENERATED_QUEUE_DRIFT")
            return {"status":"PASS","idempotent":True,
                    "queue_reconciled":True,"new_paid_attempts":0,
                    "visual_review_pass":False}
        if item.get("status")!="external_blocked":
            deny("QUEUE_HANDOFF_DRIFT")
        item.update(status="generated",output_path=rel,generation_key=GEN,
            attempt_index=2,completed_at=scheduler_core.now(),last_error=None,
            frame_contract_sha256=(item.get("frame_contract") or {}).get("contract_sha256"),
            prompt_package_sha256=(item.get("prompt_package") or {}).get("package_sha256"),
            unknown_reconciliation={"kind":source["proof_kind"],
                "runner_request_id":RID,"generation_key":GEN,
                "attempt_index":2,"runner_receipt_sha256":expected_sha,
                "raw_sha256":source["raw_sha256"],
                "candidate_sha256":source["candidate_sha256"],
                "pixel_review_pass":False})
        for k in ("external_block","technical_failure_code","retry_exhausted"):
            item.pop(k,None)
        production_recovery.mark_terminal(ep,item,"COMMITTED",
            recovery="F001_ATTEMPT2_NATIVE_DIRECT_RAW_PROVENANCE",
            proof_evidence_sha256=expected_sha)
        scheduler_core.save_queue(ep,q)
        return {"status":"PASS","attempt_index":2,"attempts_consumed":2,
                "new_provider_calls":0,"additional_paid_attempts":0,
                "candidate_sha256":source["candidate_sha256"],
                "visual_review_pass":False,"queue_reconciled":True,
                "idempotent":already}


def verify_rearmed(ep:Path)->dict:
    """Read-only rc24 restart admission, only after full Attempt #2 reconciliation."""
    ep=first.canonical_episode(ep)
    source=inspect(ep,require_blocked=False)
    if source["status"]!="F001_ATTEMPT2_ALREADY_RECONCILED":
        deny("ATTEMPT2_STILL_UNKNOWN")
    item=source["item"]
    if (item.get("status")!="generated"
            or item.get("generation_key")!=GEN
            or int(item.get("attempt_index") or 0)!=2
            or item.get("output_path")!=source["candidate"].relative_to(ROOT).as_posix()
            or (item.get("unknown_reconciliation") or {}).get("runner_receipt_sha256")
               !=source["runner_receipt_sha256"]
            or (item.get("unknown_reconciliation") or {}).get("pixel_review_pass") is not False):
        deny("ATTEMPT2_GENERATED_QUEUE_PROOF_DRIFT")
    ledger=ledger_store.load_authority(ep)
    if not isinstance(ledger,dict):
        deny("MYSQL_LEDGER_AUTHORITY_MISSING")
    _verify_repaired(ledger,source)
    local=ep/"meta/runtime/native-baseline-frame01-tool-proof.json"
    if not local.is_file():
        deny("UNREVIEWED_PROOF_MISSING")
    evidence=json.loads(local.read_text(encoding="utf-8"))
    if (evidence.get("proof_kind")!="TRUSTED_NATIVE_DIRECT_THREAD_SCOPED_IMAGE_SHA"
            or evidence.get("attempt_index")!=2
            or evidence.get("generation_key")!=GEN
            or evidence.get("runner_request_id")!=RID
            or evidence.get("normalized_png_sha256")!=source["candidate_sha256"]
            or evidence.get("raw_png_sha256")!=source["raw_sha256"]
            or evidence.get("review_pass") is not False
            or evidence.get("visual_review_pass") is not False):
        deny("UNREVIEWED_PROOF_IDENTITY_DRIFT")
    driver=_assert_driver(ep)
    drv_sha=hashlib.sha256(json.dumps(driver.get("record") or {},
        ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    return {"status":"VISUAL_LOCK_RC24_F001_ATTEMPT2_RECONCILED_RECOVERABLE",
        "driver_record_sha256":drv_sha,
        "runner_receipt_sha256":source["runner_receipt_sha256"],
        "candidate_sha256":source["candidate_sha256"],
        "item_id":FRAME_ID,"read_only":True,"production_authorization":False,
        "paid_attempts_consumed":2,"remaining_attempts":0,"review_pass":False}


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument("--episode",required=True)
    parser.add_argument("--commit",action="store_true")
    parser.add_argument("--verify-rearmed",action="store_true")
    parser.add_argument("--ack-real-production",action="store_true")
    parser.add_argument("--ack-no-regeneration-and-original-a2-sha",action="store_true")
    parser.add_argument("--expected-runner-receipt-sha256")
    a=parser.parse_args(argv)
    try:
        ep=first.canonical_episode(a.episode)
        if a.commit:
            out=commit(ep,expected_sha=a.expected_runner_receipt_sha256 or "",
                acknowledged=a.ack_real_production and a.ack_no_regeneration_and_original_a2_sha)
        elif a.verify_rearmed:
            out=verify_rearmed(ep)
        else:
            proof=inspect(ep)
            out={k:proof[k] for k in ("status","generation_key","request_id",
                "raw_sha256","candidate_sha256","runner_receipt_sha256",
                "proof_kind","attempts_consumed","review_pass","model_calls","new_paid_attempts")}
    except Exception as exc:
        out={"status":"BLOCKED","reason":str(exc),"exception":type(exc).__name__}
    print(json.dumps(out,ensure_ascii=False,sort_keys=True))
    return 0 if out.get("status") in {"PASS","F001_ATTEMPT2_NATIVE_RAW_RECONCILABLE",
        "VISUAL_LOCK_RC24_F001_ATTEMPT2_RECONCILED_RECOVERABLE"} else 2

if __name__=="__main__":
    raise SystemExit(main())
