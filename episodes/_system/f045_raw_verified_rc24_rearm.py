"""Read-only, SHA-fenced rc24 restart after F045 preserved RAW recovered.

No review PASS is inferred from an image that was only normalized.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

from PIL import Image

import generation_attempt_authority as attempts
import logical_asset_identity as identity
import production_ledger_persistence as ledger_store
import runtime_driver
import scheduler_core
import visual_lock_baseline_gate as baseline
import provider_receipt_persistence
import f045_visual_lock_raw_scope as scoped

ROOT=Path(__file__).resolve().parents[2]
EP=ROOT/"episodes"/"00_独立篇"/scoped.EPISODE
RAW=Path("media/raw/45-1792839000.png")
RAW_SHA="dcf4acd37b125f63876233d2894798fe0ca3a727507164e016a2a79f79ec1abc"
FRAME_45_ID=scoped.ITEM_ID

class RecoveryDenied(RuntimeError):pass
def deny(text):raise RecoveryDenied(text)
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def inspect(ep):
    ep=Path(ep).resolve()
    if ep!=EP.resolve():deny("WRONG_EPISODE")
    driver=runtime_driver.status(ep)
    if (driver.get("driver_state")!="EXITED"
        or driver.get("liveness")!="DEAD" or driver.get("pid")!=0
        or str(driver.get("exit_code"))!="24"):
        deny("HISTORICAL_DRIVER_RC24_NOT_STOPPED")
    if not baseline.approved(ep):deny("F001_BASELINE_REVIEW_NOT_APPROVED")
    queue=scheduler_core.load_queue(ep)
    visual=[x for x in queue.get("items") or []
            if x.get("kind")=="original" and x.get("scope")=="visual_lock"]
    repair=[x for x in queue.get("items") or [] if x.get("kind")=="repair"]
    rows={int(x.get("frame") or 0):x for x in visual}
    if (len(queue.get("items") or [])!=5 or len(visual)!=4
        or set(rows)!={1,5,45,47} or len(repair)!=1
        or repair[0].get("status")!="superseded"
        or rows[45].get("id")!=FRAME_45_ID
        or any(row.get("status")!="generated" for row in visual)
        or (rows[45].get("normalization_recovery") or {}).get("kind")
                !="verified_provider_raw_after_unknown"
        or (rows[45].get("normalization_recovery") or {}).get("crop_applied") is not True):
        deny("RESTORED_VISUAL_LOCK_QUEUE_PROOF_MISSING")
    l=ledger_store.load_authority(ep)
    frames=(l or {}).get("frames") or {}
    if (frames.get("01",{}).get("status") not in {"PASSED","LOCKED"}
        or any(frames.get(f"{i:02d}",{}).get("status") not in {"ORIGINAL_READY","PASSED","LOCKED"}
               for i in (5,45,47))):
        deny("RESTORED_LEDGER_READY_STATUS_MISSING")
    records={}
    for i,n in ((1,2),(5,1),(45,1),(47,1)):
        k=identity.frame_asset_key(ep,i)
        st=attempts.load_asset_state(ep,k)
        row=attempts.load_attempt(ep,k,n) or {}
        if (st.get("attempts_consumed")!=n
            or st.get("active_attempt_index") is not None
            or row.get("status")!="SUCCEEDED"
            or attempts.load_attempt(ep,k,n+1) is not None
            or row.get("generation_key")!=rows[i].get("generation_key")):
            deny("GENERATION_ATTEMPT_SOURCE_INVALID")
        asset=ROOT/str(rows[i].get("output_path") or "")
        candidate=frames[f"{i:02d}"].get("current_candidate") or {}
        if (not asset.is_file() or not asset.is_relative_to(ep)
            or sha(asset)!=candidate.get("sha256")):
            deny("CANDIDATE_SHA_DRIFT")
        if i==45:
            with Image.open(asset) as png:
                if png.format!="PNG" or png.size!=(1080,1350):
                    deny("RESTORED_CANDIDATE_CANVAS_INVALID")
        records[i]={"generation_key":row["generation_key"],
                    "candidate_sha256":candidate["sha256"],
                    "paid_attempts_consumed":n}
    raw=ep/RAW
    if not raw.is_file() or sha(raw)!=RAW_SHA:
        deny("PRESERVED_PROVIDER_RAW_CHANGED")
    record=(frames["45"].get("attempts") or [])[-1]
    correction=record.get("recovery_correction") or {}
    if (record.get("result")!="success"
        or correction.get("previous_result")!="technical_failure"
        or correction.get("reason")!="sha_verified_provider_raw_post_unknown"):
        deny("F045_LEDGER_RECOVERY_AUDIT_MISSING")
    recovery=rows[45]["normalization_recovery"]
    if recovery.get("candidate_sha256")!=records[45]["candidate_sha256"]:
        deny("F045_NORMALIZED_SHA_NOT_BOUND_TO_QUEUE")
    receipt_path=recovery.get("provider_receipt")
    if not receipt_path:deny("F045_PROVIDER_RECEIPT_MISSING")
    rec=provider_receipt_persistence.load_by_path(ep,receipt_path)
    payload=(rec or {}).get("payload") or {}
    if ((rec or {}).get("source")!="mysql"
        or (rec or {}).get("receipt_status")!="FINALIZED"
        or payload.get("raw_sha256")!=RAW_SHA
        or (payload.get("release_canvas") or {}).get("sha256")!=records[45]["candidate_sha256"]
        or payload.get("generation_key")!=records[45]["generation_key"]):
        deny("F045_PROVIDER_RECEIPT_NOT_FINALIZED")
    canonical=json.dumps(driver.get("record") or {},sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
    return {"status":"VISUAL_LOCK_RC24_F045_RAW_RATIO_RECOVERED",
        "driver_record_sha256":hashlib.sha256(canonical).hexdigest(),
        "f045_candidate_sha256":records[45]["candidate_sha256"],
        "f045_raw_sha256":RAW_SHA,
        "f005_candidate_sha256":records[5]["candidate_sha256"],
        "f047_candidate_sha256":records[47]["candidate_sha256"],
        "f001_attempts_consumed":2,
        "new_paid_attempts":0,"read_only":True,"production_authorization":False}

def main(argv=None):
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument("--episode",required=True)
    p.add_argument("--verify-rearmed",action="store_true")
    a=p.parse_args(argv)
    try:
        out=inspect(Path(a.episode))
    except Exception as exc:
        out={"status":"BLOCKED","reason":str(exc),"exception":type(exc).__name__}
    print(json.dumps(out,ensure_ascii=False,sort_keys=True))
    return 0 if out.get("status")=="VISUAL_LOCK_RC24_F045_RAW_RATIO_RECOVERED" else 2
if __name__=="__main__":raise SystemExit(main())
