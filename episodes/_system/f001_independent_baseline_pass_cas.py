"""Controlled F001 review-only PASS projection and voided, non-invoked repair gate.

PR136/137 preserved the old FAIL and emitted one completed independent review.
Only the exact prevalidated actual-pixel PASS may restore an existing original
candidate from a later *not invoked* technical repair. No image regeneration.
"""
from __future__ import annotations
import argparse
import copy
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path

import episode_identity
import episode_state_persistence
import generation_attempt_authority as generation
import logical_asset_identity
import production_ledger as core
import production_ledger_persistence as persistence
import scheduler_core
import runtime_driver
import runtime_provenance
import visual_lock_baseline_gate as baseline
import visual_lock_baseline_review_only as reviewer
import native_baseline_source_freeze as freeze
from platform.repository.mysql.mysql_production_attempt_repository import MySqlProductionAttemptRepository
from platform.repository.mysql.mysql_production_frame_repository import MySqlProductionFrameRepository
from platform.repository.mysql.mysql_production_ledger_authority_repository import MySqlProductionLedgerAuthorityRepository

ROOT=Path(__file__).resolve().parents[2]
REPORT_REL=Path("meta/runtime/independent-baseline-rereviews/f001-quota-58a1e9f4f9d437f8ea9e.json")
EXPECTED_CANDIDATE_SHA="0a9f8a2477b40c48fc1bfe93bd396be53ca1882b725a66aa2f3cac59437a135f"
EXPECTED_OLD_REVIEW_SHA="f49194b05fddc4ca3e364b13d9564b8fe0ae18e608f07e9565e9be1bad2bcd03"
EXPECTED_FRAME_CONTRACT_SHA="916a55e5765b765bfe77a11b6c1d8365300ea4fda06702ec2a614196d141db92"
EXPECTED_ORIGINAL_ATTEMPT_ID="f1f18545e61a"
EXPECTED_REPAIR_ATTEMPT_ID="5b5ee1cf3d91"
EXPECTED_REPAIR_ITEM_ID="c006c22820c9"
EXPECTED_REVIEW_SOURCE_SHA="14a0032a5207e55f3a27d00bd8e4be4dcb712b3fb6bfd1ab67b0b8b06c828905"

class ReviewPassDenied(RuntimeError):pass
def deny(message):raise ReviewPassDenied(message)
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

@contextmanager
def frozen(paths):
    if os.name!="nt":deny("WINDOWS_FROZEN_SOURCE_REQUIRED")
    handles=[]
    try:
        for p in sorted({Path(x).resolve() for x in paths},key=lambda x:str(x).casefold()):
            handles.append(freeze._windows_open_shared_read(p))
        yield
    finally:
        for h in reversed(handles):freeze._windows_close(h)

def inspect(ep,*,allow_progress=True):
    ep=Path(ep).resolve()
    if ep!=(ROOT/reviewer.REL).resolve():deny("WRONG_F001_EPISODE")
    driver=runtime_driver.status(ep)
    if (driver.get("driver_state")!="EXITED"
         or driver.get("liveness")!="DEAD"
         or driver.get("pid")!=0 or str(driver.get("exit_code"))!="22"):
        deny("DRIVER_NOT_STOPPED_RC22")
    stage,source=episode_state_persistence.load_with_source(ep)
    if source!="mysql" or (stage or {}).get("current_state")!="STORYBOARD_LOCKED":
        deny("MYSQL_STAGE_DRIFT")
    key=logical_asset_identity.frame_asset_key(ep,1)
    st=generation.load_asset_state(ep,key)
    a2=generation.load_attempt(ep,key,2) or {}
    if (st.get("attempts_consumed")!=2 or st.get("remaining_attempts")!=0
         or st.get("active_attempt_index") is not None or generation.load_attempt(ep,key,3)
         or a2.get("status")!="SUCCEEDED"):
        deny("GENERATION_ATTEMPTS_CHANGED")
    report_path=ep/REPORT_REL
    if not report_path.is_file() or report_path.is_symlink():deny("INDEPENDENT_REVIEW_PASS_NOT_FOUND")
    witness=json.loads(report_path.read_text("utf-8"))
    prov=witness.get("critic_provenance") or {}
    log=ROOT/str(prov.get("log") or "")
    if (not log.is_file() or log.is_symlink()
         or prov.get("review_scope")!="VISUAL_LOCK_BASELINE_REVIEW_ONLY"
         or prov.get("review_capability")!="vision"
         or runtime_provenance.validate_critic_provenance(prov)
         or sha(log)!=prov.get("log_sha256")):deny("INDEPENDENT_CRITIC_LOG_UNVERIFIED")
    log_text=log.read_text(encoding="utf-8-sig",errors="replace")
    if ('"type":"turn.completed"' not in log_text.replace(" ","")
        or '"type":"thread.started"' not in log_text.replace(" ","")
        or '"type":"turn.failed"' in log_text.replace(" ","")):
        deny("INDEPENDENT_CODEX_VISION_NOT_COMPLETED")
    reply=witness.get("reply") or {}
    if (witness.get("status")!="REVIEW_ONLY_PASS"
        or witness.get("review_only") is not True
        or witness.get("canonical_pass_authorized") is not False
        or witness.get("image_attempts_reserved")!=0
        or witness.get("image_generation_calls")!=0
        or witness.get("critic_returncode")!=0
        or witness.get("prior_review_sha256")!=EXPECTED_OLD_REVIEW_SHA
        or witness.get("frame_contract_sha256")!=EXPECTED_FRAME_CONTRACT_SHA
        or witness.get("image_sha256")!=EXPECTED_CANDIDATE_SHA
        or witness.get("prompt_sha256")!=EXPECTED_REVIEW_SOURCE_SHA
        or reviewer.verdict(reply)!="REVIEW_ONLY_PASS"
        or reply.get("face_boxes")!=[]
        or baseline.baseline_review_obligations(ep)["pixel_master_required"] is not False):
        deny("INDEPENDENT_IMAGE_PASS_EVIDENCE_INVALID")
    q=scheduler_core.load_queue(ep)
    original=next((i for i in q.get("items") or []
                   if i.get("id")=="ead88592f160" and i.get("kind")=="original"),None)
    repair=next((i for i in q.get("items") or []
                   if i.get("id")==EXPECTED_REPAIR_ITEM_ID and i.get("kind")=="repair"),None)
    if (not original or original.get("status")!="generated"
        or not repair or repair.get("status") not in {"blocked","superseded"}
        or repair.get("frame")!=1 or original.get("frame")!=1):
        deny("QUEUED_GENERATION_OR_REPAIR_DRIFT")
    src=baseline.generated_baseline(ep)
    if (src.get("queue_item_id")!=original["id"]
        or src.get("frame_contract_sha256")!=EXPECTED_FRAME_CONTRACT_SHA
        or src.get("sha256")!=EXPECTED_CANDIDATE_SHA):
        deny("BASELINE_GENERATED_SOURCE_CHANGED")
    asset=baseline.repo_file(src["asset_path"])
    if sha(asset)!=EXPECTED_CANDIDATE_SHA:deny("BASELINE_PNG_SHA_CHANGED")
    archive=ep/"meta/runtime/review-exports"/f"visual-lock-baseline-review-{EXPECTED_OLD_REVIEW_SHA[:16]}.json"
    canonical=ep/baseline.REL
    if canonical.is_file() and sha(canonical)==EXPECTED_OLD_REVIEW_SHA:
        prior=json.loads(canonical.read_text("utf-8"))
        if archive.is_file() and sha(archive)!=EXPECTED_OLD_REVIEW_SHA:
            deny("PRIOR_FAIL_ARCHIVE_CHANGED")
    elif archive.is_file() and sha(archive)==EXPECTED_OLD_REVIEW_SHA and allow_progress:
        prior=json.loads(archive.read_text("utf-8"))
        existing=json.loads(canonical.read_text("utf-8"))
        audit=existing.get("independent_review_reconciliation") or {}
        if (existing.get("decision")!="PASS"
            or existing.get("sha256")!=EXPECTED_CANDIDATE_SHA
            or audit.get("report_sha256")!=sha(report_path)
            or audit.get("previous_fail_sha256")!=EXPECTED_OLD_REVIEW_SHA):
            deny("CANONICAL_REVIEW_PARTIAL_DRIFT")
    else:deny("OLD_FAIL_REVIEW_NOT_SAFELY_AVAILABLE")
    if (prior.get("decision")!="FAIL" or prior.get("sha256")!=EXPECTED_CANDIDATE_SHA
        or prior.get("frame_contract_sha256")!=EXPECTED_FRAME_CONTRACT_SHA
        or prior.get("critic_provenance",{}).get("log_sha256")
             !=witness.get("prior_critic_log_sha256")):
        deny("HISTORICAL_FAIL_REVIEW_MISMATCH")
    old_log=ROOT/prior["critic_provenance"]["log"]
    if not old_log.is_file() or sha(old_log)!=witness["prior_critic_log_sha256"]:
        deny("OLD_FAIL_CRITIC_LOG_CHANGED")
    ledger=persistence.load_authority(ep)
    if not isinstance(ledger,dict):deny("PRODUCTION_LEDGER_NOT_MYSQL")
    frame=(ledger.get("frames") or {}).get("01") or {}
    if (frame.get("status") not in {"TECH_FAILED","ORIGINAL_READY","PASSED"}
         or not isinstance(frame.get("current_candidate"),dict)
         or frame["current_candidate"].get("sha256")!=EXPECTED_CANDIDATE_SHA):
        deny("LEDGER_FRAME_STATE_OR_CANDIDATE_CHANGED")
    attempts=frame.get("attempts") or []
    if (len(attempts)!=4
        or attempts[-2].get("attempt_id")!=EXPECTED_ORIGINAL_ATTEMPT_ID
        or attempts[-2].get("result")!="success"
        or attempts[-1].get("attempt_id")!=EXPECTED_REPAIR_ATTEMPT_ID
        or attempts[-1].get("kind")!="repair"
        or attempts[-1].get("result")!="technical_failure"
        or (attempts[-1].get("provider_attempt") or {}).get("status")!="NOT_INVOKED"
        or (attempts[-1].get("error") or {}).get("code")!="LOGIN_AUTH_IMAGE_TOOL_CAPABILITY_UNKNOWN"
        or (frame.get("technical_failures") or [])[-1].get("attempt_id")!=EXPECTED_REPAIR_ATTEMPT_ID):
        deny("LEDGER_REPAIR_HISTORY_UNVERIFIED")
    witness_sha=sha(report_path)
    if frame["status"]!="TECH_FAILED":
        fix=frame.get("independent_review_reconciliation") or {}
        if fix.get("report_sha256")!=witness_sha or fix.get("previous_failed_repair")!=EXPECTED_REPAIR_ATTEMPT_ID:
            deny("RECONCILED_LEDGER_NO_SOURCE_PROOF")
    return {"status":"REVIEW_PASS_CANONICAL_PROJECTION_ELIGIBLE",
        "ep":ep,"queue":q,"report":report_path,"log":log,"old_log":old_log,
        "asset":asset,"old_review":canonical,"archive":archive,"prior_review":prior,
        "witness":witness,"witness_sha":witness_sha,"ledger":ledger,
        "frame":frame,"repair":repair,"candidate":frame["current_candidate"],
        "current_status":frame["status"],"image_generation_calls":0,
        "new_paid_attempts":0,"attempts_consumed":2}

def verify_typed_projection(conn,storage_id,frame):
    """The query projection must already agree with the MySQL Ledger BLOB."""
    rows=frame.get("attempts") or []
    if len(rows)!=4:deny("TYPED_ATTEMPT_HISTORY_NOT_FOUR")
    latest=rows[-1]
    a=conn.query_one("SELECT EPISODE_ID,FRAME_NO,ATTEMPT_NO,ATTEMPT_ID,"
         "ATTEMPT_KIND,STATUS,PAYLOAD FROM TB_PRODUCTION_ATTEMPT "
         "WHERE EPISODE_ID=%s AND FRAME_NO=1 AND ATTEMPT_NO=4 FOR UPDATE",
         (storage_id,))
    f=conn.query_one("SELECT EPISODE_ID,FRAME_NO,STATUS,CURRENT_ATTEMPT_ID,"
         "CONTRACT_SHA256,APPROVED_ARTIFACT_ID FROM TB_PRODUCTION_FRAME "
         "WHERE EPISODE_ID=%s AND FRAME_NO=1 FOR UPDATE",(storage_id,))
    if not a or not f:deny("TYPED_ATTEMPT_OR_FRAME_MISSING")
    payload=a.get("PAYLOAD")
    if isinstance(payload,memoryview):payload=payload.tobytes()
    if isinstance(payload,(bytes,bytearray)):payload=payload.decode("utf-8")
    if isinstance(payload,str):payload=json.loads(payload)
    if (a.get("EPISODE_ID")!=storage_id
        or int(a.get("FRAME_NO") or 0)!=1 or int(a.get("ATTEMPT_NO") or 0)!=4
        or a.get("ATTEMPT_ID")!=EXPECTED_REPAIR_ATTEMPT_ID
        or a.get("ATTEMPT_KIND")!="repair"
        or a.get("STATUS")!="technical_failure"
        or payload!=latest
        or f.get("EPISODE_ID")!=storage_id
        or f.get("STATUS")!=frame.get("status")
        or f.get("CURRENT_ATTEMPT_ID")!=EXPECTED_REPAIR_ATTEMPT_ID
        or f.get("CONTRACT_SHA256")!=persistence._contract_sha(frame)
        or f.get("APPROVED_ARTIFACT_ID") is not None):
        deny("TYPED_LEDGER_PROJECTION_DRIFT")


def corrected_ledger(document,source):
    doc=copy.deepcopy(document)
    frame=doc["frames"]["01"]
    if frame["status"]!="TECH_FAILED":deny("LEDGER_ALREADY_CORRECTED")
    if frame.get("current_candidate")!=source["candidate"]:
        deny("CANDIDATE_CHANGED_BEFORE_CORRECTION")
    if (frame.get("approved_asset") is not None
            or int(frame.get("content_repairs_used") or 0)!=1
            or (frame.get("repair_authorization") or {}).get("approval_basis")!="delegated_auto_review"):
        deny("CONTENT_REPAIR_AUTHORITY_DRIFT")
    import production_ledger as ledger
    now=ledger.now_iso()
    # Preserve the actual technical failure, its attempt ID, and the consumed
    # delegated review allowance; only restore the *older valid* candidate.
    frame["status"]="ORIGINAL_READY"
    frame["independent_review_reconciliation"]={
        "at":now,"kind":"OLDER_ORIGINAL_CANDIDATE_REVIEWED_AFTER_NONINVOKED_REPAIR",
        "previous_status":"TECH_FAILED",
        "previous_failed_repair":EXPECTED_REPAIR_ATTEMPT_ID,
        "repair_result_remains":"technical_failure",
        "repair_provider_invoked":False,
        "previous_fail_sha256":EXPECTED_OLD_REVIEW_SHA,
        "report_sha256":source["witness_sha"],
        "candidate_sha256":EXPECTED_CANDIDATE_SHA,
        "frame_contract_sha256":EXPECTED_FRAME_CONTRACT_SHA,
        "content_repairs_used_preserved":1,
        "image_attempts_consumed":2}
    doc["updated_at"]=now
    return doc

def commit(ep,*,expected_review_sha:str,ack=False):
    if not ack:deny("EXPLICIT_REVIEW_ONLY_PASS_PROJECTION_ACK_REQUIRED")
    ep=Path(ep).resolve()
    with scheduler_core.queue_transaction(ep):
        src=inspect(ep)
        if src["witness_sha"]!=expected_review_sha:deny("INDEPENDENT_REVIEW_SHA_FENCE_CHANGED")
        paths=[src[k] for k in ("asset","report","log","old_log")]
        # Canonical/archived old FAIL also frozen while still available.
        if src["old_review"].is_file() and sha(src["old_review"])==EXPECTED_OLD_REVIEW_SHA:
            paths.append(src["old_review"])
        elif src["archive"].is_file():
            paths.append(src["archive"])
        with frozen(paths):
            fresh=inspect(ep)
            if fresh["witness_sha"]!=expected_review_sha:deny("REVIEW_SOURCE_CHANGED_DURING_CAS")
            if fresh["current_status"]=="TECH_FAILED":
                conn,repo,frames,attempts=persistence._repositories()
                try:
                    storage_id=episode_identity.storage_episode_id(ep)
                    with conn.transaction():
                        row=conn.query_one("SELECT SHA256 FROM TB_PRODUCTION_LEDGER_AUTHORITY "
                             "WHERE EPISODE_ID=%s FOR UPDATE",(storage_id,))
                        prior=repo.get(storage_id)
                        if not prior or not row or prior["sha256"]!=row.get("SHA256"):
                            deny("LEDGER_MYSQL_SOURCE_SHA_CHANGED")
                        old=(prior["document"].get("frames") or {}).get("01") or {}
                        if (old!=src["frame"] or old.get("status")!="TECH_FAILED"):
                            deny("LEDGER_MYSQL_CHANGED_DURING_CAS")
                        verify_typed_projection(conn,storage_id,old)
                        updated=corrected_ledger(prior["document"],src)
                        repo.upsert(storage_id,updated)
                        counts=persistence._persist_projection(
                            storage_id,updated,frames,attempts,frame_keys={"01"})
                        if counts!=(1,4):deny("LEDGER_TYPED_PROJECTION_COUNT_UNEXPECTED")
                        verify_typed_projection(conn,storage_id,updated["frames"]["01"])
                    persistence.invalidate(ep)
                finally:conn.close()
        # SQLite/Redis do not share a global transaction with MySQL. The source
        # guard and SHA-bound reconciled Ledger make this queue handoff resumable.
        current=scheduler_core.load_queue(ep)
        repair=next(x for x in current["items"] if x.get("id")==EXPECTED_REPAIR_ITEM_ID)
        if repair["status"]=="blocked":
            repair["status"]="superseded"
            repair["superseded_review_sha256"]=src["witness_sha"]
            repair["superseded_reason"]="independent_PASS_of_previous_original_after_noninvoked_repair"
            scheduler_core.save_queue(ep,current)
        elif repair["status"]=="superseded":
            if repair.get("superseded_review_sha256")!=src["witness_sha"]:
                deny("REPAIR_ALREADY_SUPERSEDED_BY_OTHER_EVIDENCE")
        else:deny("REPAIR_QUEUE_CHANGED_DURING_HANDOFF")
        # Immutable copy of the historical FAIL. Never strip or change its
        # original critic JSONL, input SHA, diagnosis, or original decision.
        if not src["archive"].is_file():
            src["archive"].parent.mkdir(parents=True,exist_ok=True)
            with src["archive"].open("xb") as f:f.write(src["old_review"].read_bytes())
        if sha(src["archive"])!=EXPECTED_OLD_REVIEW_SHA:
            deny("HISTORICAL_FAIL_ARCHIVE_SHA_MISMATCH")
        # New canonical PASS is not made up: copy the nine actual pixel checks
        # from the successful independent Codex Vision report.
        if sha(src["old_review"])==EXPECTED_OLD_REVIEW_SHA:
            data=copy.deepcopy(src["prior_review"])
            reply=src["witness"]["reply"]
            data.update(status="DRAFT",decision="PASS",checks=reply["checks"],
                        face_boxes=reply["face_boxes"],note=reply.get("note",""),
                        critic_provenance=src["witness"]["critic_provenance"],
                        independent_review_reconciliation={
                             "previous_fail_sha256":EXPECTED_OLD_REVIEW_SHA,
                             "report_path":baseline.repo_rel(src["report"]),
                             "report_sha256":src["witness_sha"],
                             "reviewed_original_candidate":True,
                             "did_not_rewrite_frame_contract":True,
                             "image_generation_calls":0,
                             "additional_image_attempts":0})
            baseline.write_json(src["old_review"],data)
        if baseline.approved(ep):
            return {"status":"PASS","reused":True,"new_paid_attempts":0}
        result=baseline.approve(ep)
        if not baseline.approved(ep):deny("CANONICAL_BASELINE_APPROVAL_NOT_VERIFIED")
        return {"status":"PASS","review":result,"approved":True,
            "old_fail_archived":True,"new_paid_attempts":0,
            "image_generation_calls":0,"attempts_consumed":2}

def verify_rearmed(ep):
    """Source-fenced, read-only rc22 driver restart after canonical PASS."""
    source=inspect(ep)
    if (source["current_status"] not in {"PASSED","LOCKED"}
        or not baseline.approved(source["ep"])
        or source["repair"].get("status")!="superseded"
        or source["repair"].get("superseded_review_sha256")!=source["witness_sha"]):
        deny("CANONICAL_VISUAL_LOCK_BASELINE_NOT_PASSED")
    queued=[x for x in source["queue"].get("items") or []
            if x.get("scope")=="visual_lock" and x.get("kind")=="original"
            and int(x.get("frame") or 0)!=1]
    if (len(queued)!=3 or {int(x["frame"]) for x in queued}!={5,45,47}
        or any(x.get("status")!="queued" or x.get("depends_on")!=[1]
               for x in queued)):
        deny("VISUAL_LOCK_DEPENDENT_QUEUE_CHANGED")
    driver=runtime_driver.status(source["ep"])
    driver_sha=hashlib.sha256(json.dumps(driver.get("record") or {},
        ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    return {
        "status":"VISUAL_LOCK_RC22_F001_INDEPENDENT_PASS_RECOVERABLE",
        "driver_record_sha256":driver_sha,
        "review_sha256":source["witness_sha"],
        "candidate_sha256":EXPECTED_CANDIDATE_SHA,
        "old_review_sha256":EXPECTED_OLD_REVIEW_SHA,
        "read_only":True,"production_authorization":False,
        "paid_attempts_consumed":2,"new_paid_attempts":0
    }


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--episode",required=True)
    p.add_argument("--commit",action="store_true")
    p.add_argument("--verify-rearmed",action="store_true")
    p.add_argument("--ack-real-review-no-regeneration",action="store_true")
    p.add_argument("--expected-review-sha256")
    a=p.parse_args(argv)
    try:
        ep=Path(a.episode).resolve()
        if a.commit:
            out=commit(ep,expected_review_sha=a.expected_review_sha256 or "",
                   ack=a.ack_real_review_no_regeneration)
        elif a.verify_rearmed:
            out=verify_rearmed(ep)
        else:
            src=inspect(ep)
            out={k:src[k] for k in ("status","witness_sha","current_status",
               "attempts_consumed","new_paid_attempts","image_generation_calls")}
    except Exception as exc:
        out={"status":"BLOCKED","reason":str(exc),"exception":type(exc).__name__}
    print(json.dumps(out,ensure_ascii=False,sort_keys=True,default=str))
    return 0 if out.get("status") in {"PASS","REVIEW_PASS_CANONICAL_PROJECTION_ELIGIBLE",
        "VISUAL_LOCK_RC22_F001_INDEPENDENT_PASS_RECOVERABLE"} else 2
if __name__=="__main__":raise SystemExit(main())
