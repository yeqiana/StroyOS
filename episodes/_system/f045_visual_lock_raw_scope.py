"""Strict episode14 F045 source scope for pre-paid RAW ratio recovery."""
from pathlib import Path
import generation_attempt_authority as attempts
import logical_asset_identity as identity
import production_ledger_persistence as persistence
import runtime_driver
import scheduler_core
import visual_lock_baseline_gate as baseline

ROOT=Path(__file__).resolve().parents[2]
EPISODE="14_深渊疗愈所_第一集_净土生命还原"
FRAME=45
ITEM_ID="a1b0232cf35c"
CONTRACT_SHA="2d2def920a7501b87487bf55733226b70d73af961015bd58b3c92facf161a128"

def allowed(ep,item):
    try:
        ep=Path(ep).resolve()
        if (ep!=(ROOT/"episodes"/"00_独立篇"/EPISODE).resolve()
            or item.get("scope")!="visual_lock"
            or item.get("kind")!="original"
            or int(item.get("frame") or 0)!=FRAME
            or item.get("id")!=ITEM_ID
            or item.get("status")!="external_blocked"
            or item.get("technical_failure_code")!="ASPECT_RATIO_MISMATCH"
            or (item.get("frame_contract") or {}).get("contract_sha256")!=CONTRACT_SHA):
            return False
        driver=runtime_driver.status(ep)
        if (driver.get("driver_state")!="EXITED"
            or driver.get("liveness")!="DEAD"
            or driver.get("pid")!=0
            or str(driver.get("exit_code"))!="24"):
            return False
        if not baseline.approved(ep):return False
        q=scheduler_core.load_queue(ep)
        visual={int(x["frame"]):x for x in q.get("items") or []
                if x.get("scope")=="visual_lock" and x.get("kind")=="original"}
        repair=[x for x in q.get("items") or [] if x.get("kind")=="repair"]
        if (len(q.get("items") or [])!=5 or set(visual)!={1,5,45,47}
            or len(repair)!=1 or repair[0].get("status")!="superseded"
            or visual[45].get("id")!=item.get("id")
            or visual[1].get("status")!="generated"
            or any(visual[f].get("status")!="generated" for f in (5,47))):
            return False
        ledger=persistence.load_authority(ep)
        frames=(ledger or {}).get("frames") or {}
        if (frames.get("01",{}).get("status") not in {"PASSED","LOCKED"}
            or frames.get("45",{}).get("status")!="TECH_FAILED"
            or any(frames.get(f"{f:02d}",{}).get("status") not in {"ORIGINAL_READY","PASSED","LOCKED"}
                   for f in (5,47))):
            return False
        for f,n in ((1,2),(5,1),(45,1),(47,1)):
            key=identity.frame_asset_key(ep,f)
            state=attempts.load_asset_state(ep,key)
            last=attempts.load_attempt(ep,key,n) or {}
            if (state.get("attempts_consumed")!=n
                or state.get("active_attempt_index") is not None
                or (f!=45 and last.get("status")!="SUCCEEDED")
                or (f==45 and (last.get("status")!="OUTCOME_UNKNOWN"
                     or last.get("failure_class")!="generation_failed_before_candidate_commit"))
                or (f==45 and attempts.load_attempt(ep,key,2) is not None)):
                return False
        return True
    except Exception:
        return False
