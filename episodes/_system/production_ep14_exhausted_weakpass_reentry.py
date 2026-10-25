"""Read-only rc22 reentry gate for completed, audited Episode14 weak Visual Lock.

Zero-image authority: proves exhausted 2/2 MySQL generations, preserved actual
Vision FAIL, immutable current candidate pixels, and all obsolete extra
candidate attempts superseded without ever being dispatched.
"""
from __future__ import annotations
import argparse,hashlib,json,sys
import platform as _stdlib_platform
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
_repo_platform=str(ROOT/"platform")
if not hasattr(_stdlib_platform,"__path__"):
    _stdlib_platform.__path__=[_repo_platform]
elif _repo_platform not in _stdlib_platform.__path__:
    _stdlib_platform.__path__.append(_repo_platform)
for path in (ROOT,ROOT/"scripts"):
    if str(path) not in sys.path:sys.path.insert(0,str(path))

import episode_state_persistence
import generation_attempt_authority as attempts
import logical_asset_identity as identities
import production_ledger_persistence
import runtime_driver
import scheduler_core
import visual_lock_admission_state as admission
import visual_lock_baseline_gate as baseline
import storyos_driver_exit_remediation as exit_tools

EXPECTED={5:"771048aed8ca",45:"42ca8cbc3884",47:"ae074a3d3c27"}
EPISODE=(ROOT/"episodes"/"00_独立篇"/
         "14_深渊疗愈所_第一集_净土生命还原")

class SourceUnverified(RuntimeError):pass

def require(yes,reason):
    if not yes:raise SourceUnverified(reason)

def sha_bytes(b):return hashlib.sha256(b).hexdigest()
def candidate_sha(ep,asset):
    path=Path(str(asset.get("path") or ""))
    if not path.is_absolute():path=ROOT/path
    path=path.resolve()
    require(path.is_relative_to(ep) and path.is_file(),"CANDIDATE_FILE_MISSING_OR_FOREIGN")
    return sha_bytes(path.read_bytes())

def inspect(ep):
    ep=Path(ep).resolve()
    require(ep==EPISODE.resolve(),"WRONG_EPISODE")
    drv=runtime_driver.status(ep)
    require(drv.get("driver_state")=="EXITED"
            and drv.get("liveness")=="DEAD"
            and drv.get("pid")==0
            and str(drv.get("exit_code"))=="22","DRIVER_RC22_NOT_DEAD")
    state=(episode_state_persistence.load(ep) or {}).get("current_state")
    require(state in {"STORYBOARD_LOCKED","VISUAL_CALIBRATED"},
            "EPISODE_STAGE_NOT_ALLOWED")
    require(baseline.approved(ep),"F001_BASELINE_NOT_APPROVED")
    queue=scheduler_core.load_queue(ep)
    rows=queue.get("items") or []
    originals={int(x.get("frame") or 0):x for x in rows
               if x.get("scope")=="visual_lock" and x.get("kind")=="original"}
    repairs={int(x.get("frame") or 0):x for x in rows
             if x.get("scope")=="repair" and x.get("kind")=="repair"}
    extras={int(x.get("frame") or 0):x for x in rows
            if x.get("kind")=="baseline_candidate"}
    require(len(rows)==11 and set(originals)=={1,5,45,47}
            and set(repairs)=={1,5,45,47}
            and set(extras)==set(EXPECTED)
            and all(x.get("status")=="generated" for x in originals.values())
            and repairs[1].get("status")=="superseded"
            and all(repairs[i].get("status")=="generated" for i in EXPECTED),
            "FOUR_IMAGES_AND_REPAIR_QUEUE_NOT_COMPLETE")
    require(all(extras[i].get("id")==EXPECTED[i]
                and extras[i].get("status")=="superseded"
                and extras[i].get("superseded_reason")==
                    "ep14_2of2_soft_vision_weak_pass"
                and extras[i].get("technical_failure_code")==
                    "LOGIN_AUTH_IMAGE_TOOL_CAPABILITY_UNKNOWN"
                and extras[i].get("output_path") is None
                for i in EXPECTED),"OLD_PREDISPATCH_CANDIDATES_NOT_AUDIT_SUPERSEDED")
    registry=(admission.load(ep) or {}).get("items") or {}
    relevant=[v for v in registry.values()
              if isinstance(v,dict) and int(v.get("frame") or 0) in {1,5,45,47}]
    require(len(relevant)==4 and
            {int(x["frame"]) for x in relevant}=={1,5,45,47},
            "FOUR_WEAK_ADMISSIONS_MISSING")
    ledger=production_ledger_persistence.load_authority(ep)
    lp=ledger.get("frames") or {}
    digest={}
    for row in relevant:
        frame=int(row["frame"])
        current=(lp.get(f"{frame:02d}") or {})
        asset=current.get("current_candidate") or {}
        original_failure=(row.get("weak_pass") or {}).get("prior_independent_fail") or {}
        require(row.get("status")=="WEAK_PASS"
                and (row.get("weak_pass") or {}).get("approved_by_policy")==
                    "episode14_paid_2of2_soft_visual_quality"
                and current.get("status")=="WEAK_PASS"
                and (current.get("weak_pass") or {}).get("approved_by_policy")==
                    "episode14_paid_2of2_soft_visual_quality"
                and original_failure.get("status")=="FAIL"
                and original_failure.get("sha256")==row.get("sha256")
                and original_failure.get("frame_contract_sha256")==
                    row.get("frame_contract_sha256")
                and ((original_failure.get("provenance") or {}).get("review_capability")=="vision")
                and asset.get("sha256")==row.get("sha256"),
                "WEAK_PASS_ORIGINAL_VISION_FAIL_PROVENANCE_INVALID")
        require(candidate_sha(ep,asset)==asset.get("sha256"),
                "CURRENT_PNG_SHA_UNVERIFIED")
        key=identities.frame_asset_key(ep,frame)
        a=attempts.load_asset_state(ep,key)
        a2=attempts.load_attempt(ep,key,2) or {}
        require(a.get("attempts_consumed")==2 and a.get("remaining_attempts")==0
                and a.get("active_attempt_index") is None
                and a2.get("status")=="SUCCEEDED"
                and attempts.load_attempt(ep,key,3) is None,
                "MY_SQL_ATTEMPT_BUDGET_NOT_FINAL")
        digest[frame]=asset["sha256"]
    queue_fingerprint=sha_bytes(json.dumps(
        [{k:x.get(k) for k in ("id","frame","kind","status","superseded_reason",
                               "technical_failure_code","output_path")}
         for x in rows],sort_keys=True,ensure_ascii=False,
        separators=(",",":")).encode("utf-8"))
    return {
        "status":"VISUAL_LOCK_RC22_EP14_EXHAUSTED_WEAK_PASS_RECOVERABLE",
        "driver_record_sha256":exit_tools.canonical_sha(drv.get("record") or {}),
        "queue_fingerprint":queue_fingerprint,
        "candidate_sha256_by_frame":{str(k):v for k,v in sorted(digest.items())},
        "new_model_calls":0,"new_paid_attempts":0,
        "read_only":True,"production_authorization":False
    }

def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--episode",required=True)
    p.add_argument("--verify-rearmed",action="store_true")
    a=p.parse_args(argv)
    try:out=inspect(a.episode)
    except Exception as exc:out={"status":"BLOCKED","reason":str(exc),"error_class":type(exc).__name__}
    print(json.dumps(out,ensure_ascii=False,sort_keys=True))
    return 0 if out["status"]=="VISUAL_LOCK_RC22_EP14_EXHAUSTED_WEAK_PASS_RECOVERABLE" else 2

if __name__=="__main__":raise SystemExit(main())
