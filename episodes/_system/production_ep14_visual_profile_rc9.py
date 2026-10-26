"""Episode14 delegated visual-profile adjudication after reviewed WEAK_PASS pixels.

An M00 selector default is NOT a human approval. Only the canonical prior
full-auto delegated approval + immutable exhausted-pixel quality acceptance can
authorize the normal delegated_auto confirmation and production freeze.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
import platform as _stdlib_platform
from pathlib import Path

_root_platform=str(Path(__file__).resolve().parents[2]/"platform")
if not hasattr(_stdlib_platform,"__path__"):
    _stdlib_platform.__path__=[_root_platform]
elif _root_platform not in _stdlib_platform.__path__:
    _stdlib_platform.__path__.append(_root_platform)
ROOT=Path(__file__).resolve().parents[2]
if str(ROOT/"scripts") not in sys.path:sys.path.insert(0,str(ROOT/"scripts"))

import delegated_approval
import episode_state_persistence
import generation_attempt_authority as attempts
import image_payload_transport
import logical_asset_identity
import production_ledger
import runtime_checkpoint
import runtime_driver
import runtime_request
import scheduler_core
import story_json
import visual_lock_baseline_gate
import visual_lock_finalizer
import visual_lock_v21
import visual_profile_closure
import visual_profile_gate
import visual_profile_lock_lifecycle as lifecycle

EP=ROOT/"episodes"/"00_独立篇"/"14_深渊疗愈所_第一集_净土生命还原"
PROFILES=EP/"meta"/"visual-profile.json"
M00="standards/visual_profiles/M00_MP4_网吧_流水席_旧数码.json"
AUTH="StoryOS delegated-auto Visual Lock authority"
RECOVERY="EP14_RC9_DELEGATED_PROFILE_FROZEN_BATCH_FOLLOWON_RECOVERABLE"

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def _base(ep):
    ep=Path(ep).resolve()
    if ep!=EP.resolve():return None
    try:
        checkpoint=runtime_checkpoint.load(ep,{})
        request=runtime_request.effective_for_episode(ep) or {}
        gates=story_json.read_json(ep/"meta/story-gates.json")
        report=story_json.read_json(ep/"meta/visual-lock-final-report.json")
        profile=story_json.read_json(ep/"meta/visual-profile.json")
        ledger=production_ledger.load_authority(ep,default={}) or {}
        q=scheduler_core.load_queue(ep)
        if (episode_state_persistence.load_with_source(ep)[1]!="mysql"
            or episode_state_persistence.load(ep).get("current_state")!="VISUAL_CALIBRATED"
            or checkpoint.get("continuous_execution_authorized") is not True
            or checkpoint.get("approval_basis") not in {"delegated_continuous_execution","delegated_auto_review"}
            or request.get("mode")!="full_auto"
            or (request.get("runtime") or {}).get("execution_mode")!="dag"
            or delegated_approval.verify(ep,"visual_lock")
            or (gates.get("reviews") or {}).get("visual_admission")!="passed"
            or report.get("decision")!="PASS"
            or visual_lock_baseline_gate.validate_final_requirement(ep)
            or visual_lock_v21.verify(ep,metadata_only=False)
            or visual_lock_finalizer.verify(ep)
            or profile.get("profile_id")!="M00" or profile.get("profile_path")!=M00
            or profile.get("status")!="defaulted"
            or (profile.get("selection") or {}).get("source")!="rule_engine"
            or (profile.get("selection_evidence") or {}).get("reason")!=["no_rule_matched","default=M00"]
            or len([x for x in q.get("items") or [] if x.get("scope")=="batch"])!=44
            or len([x for x in q.get("items") or [] if x.get("scope")!="batch"])!=11):
            return None
        for frame in (1,5,45,47):
            f=(ledger.get("frames") or {}).get(f"{frame:02d}") or {}
            if (f.get("status")!="WEAK_PASS"
                or int(attempts.load_asset_state(ep,logical_asset_identity.frame_asset_key(ep,frame)).get("attempts_consumed") or 0)!=2
                or not (f.get("current_candidate") or {}).get("sha256")):
                return None
        f2=(ledger.get("frames") or {}).get("02") or {}
        if (f2.get("status")!="ORIGINAL_READY"
            or not (f2.get("current_candidate") or {}).get("sha256")):
            return None
        key=logical_asset_identity.frame_asset_key(ep,2)
        st=attempts.load_asset_state(ep,key)
        a=attempts.load_attempt(ep,key,1) or {}
        if (int(st.get("attempts_consumed") or 0)!=1
            or st.get("active_attempt_index") is not None
            or a.get("status")!="SUCCEEDED"
            or a.get("provider")!="codex_subscription"
            or a.get("generation_key")!=(f2.get("current_candidate") or {}).get("generation_key")):
            return None
        return {"ep":ep,"profile":profile,"ledger":ledger,
                "report_sha":sha(ep/"meta/visual-lock-final-report.json"),
                "profile_sha":sha(ep/"meta/visual-profile.json"),
                "f002_sha":f2["current_candidate"]["sha256"]}
    except Exception:
        return None

def eligible(ep):
    d=_base(ep)
    if d is None:return {"status":"BLOCKED","reason":"DELEGATION_OR_PIXELS_UNVERIFIED"}
    lock=d["profile"]
    state=lock.get("lifecycle_state")
    if (state=="SELECTED" and lock.get("confirmation_mode")=="pending"
        and lock.get("confirmed_by") is None and lock.get("confirmed_at") is None):
        return {"status":"READY_TO_ADJUDICATE","profile_id":"M00",
            "profile_sha256":d["profile_sha"],"report_sha256":d["report_sha"],
            "f002_sha256":d["f002_sha"],"independent_fail_preserved":True}
    if (state in {"LOCKED","FROZEN"}
        and lock.get("confirmation_mode")=="delegated_auto"
        and lock.get("confirmed_by")==AUTH
        and d["report_sha"] in str((lock.get("confirmation") or {}).get("reason") or "")):
        return {"status":"CONFIRMED_BY_EXISTING_DELEGATION","profile_id":"M00"}
    return {"status":"BLOCKED","reason":"PROFILE_LIFECYCLE_UNTRUSTED"}

def _driver_stopped(ep):
    try:
        d=runtime_driver.status(ep)
        log=Path(str(d.get("log") or "")).resolve()
        return bool(
            d.get("driver_state")=="EXITED" and d.get("liveness")=="DEAD"
            and int(d.get("pid") or 0)==0 and str(d.get("exit_code"))=="9"
            and log.is_relative_to((Path(ep).resolve()/"meta/runtime/driver-logs").resolve())
            and log.is_file()
            and "VISUAL_PROFILE_NOT_LOCKED" in log.read_text("utf-8",errors="replace")
            and "DRIVER EXIT rc=9" in log.read_text("utf-8",errors="replace")
        )
    except Exception:
        return False

def apply(ep,*,acknowledged=False):
    if not acknowledged:return {"status":"BLOCKED","reason":"EXPLICIT_PRODUCTION_ACK_REQUIRED"}
    ep=Path(ep).resolve()
    if not _driver_stopped(ep):
        return {"status":"BLOCKED","reason":"RC9_DRIVER_NOT_CONFIRMED_STOPPED"}
    proof=eligible(ep)
    if proof["status"]=="BLOCKED":return proof
    if proof["status"]=="READY_TO_ADJUDICATE":
        # All checked prior approval and pixel authorities must stay unchanged.
        again=eligible(ep)
        if again!=proof:return {"status":"BLOCKED","reason":"SOURCE_CHANGED"}
        lifecycle.confirm_visual_lock(
            ep,confirmed_by=AUTH,mode="delegated_auto",profile_id="M00",
            reason=("Full-auto delegated visual-lock decision; source_report_sha256="
                +proof["report_sha256"]+"; 4 independently failed pixels admitted "
                "only by exhausted 2/2 WEAK_PASS policy, not as visual quality PASS"))
    after=eligible(ep)
    if after.get("status")!="CONFIRMED_BY_EXISTING_DELEGATION":
        return {"status":"BLOCKED","reason":"DELEGATED_CONFIRMATION_NOT_VERIFIED"}
    frozen=visual_profile_closure.reconcile_episode(ep)
    if frozen.get("status") not in {"frozen","noop"}:
        return {"status":"BLOCKED","reason":"CANONICAL_FREEZE_FAILED","detail":frozen}
    check=visual_profile_gate.validate_visual_profile_for_production(ep,stage="release")
    if check.get("status")!="pass":
        return {"status":"BLOCKED","reason":"RELEASE_GATE_FAILED","errors":check.get("errors")}
    return {"status":"PASS","profile":"M00","lifecycle":"FROZEN",
            "mode":"delegated_auto","user_approved":False,
            "new_image_attempts":0,"independent_vision_fail_preserved":True}

def verify_rc9(ep):
    import storyos_driver_exit_remediation as exits
    ep=Path(ep).resolve()
    proof=eligible(ep)
    if proof.get("status")!="CONFIRMED_BY_EXISTING_DELEGATION":
        return {"status":"BLOCKED","reason":"PROFILE_NOT_ADJUDICATED"}
    if visual_profile_gate.validate_visual_profile_for_production(ep,stage="release").get("status")!="pass":
        return {"status":"BLOCKED","reason":"PROFILE_NOT_FROZEN"}
    d=runtime_driver.status(ep)
    log=Path(str(d.get("log") or "")).resolve()
    if (d.get("driver_state")!="EXITED" or d.get("liveness")!="DEAD"
        or int(d.get("pid") or 0)!=0 or str(d.get("exit_code"))!="9"
        or not log.is_relative_to((ep/"meta/runtime/driver-logs").resolve())
        or not log.is_file()
        or "VISUAL_PROFILE_NOT_LOCKED" not in log.read_text("utf-8",errors="replace")
        or "DRIVER EXIT rc=9" not in log.read_text("utf-8",errors="replace")):
        return {"status":"BLOCKED","reason":"EXACT_RC9_LOG_NOT_VERIFIED"}
    import production_native_batch_followon
    if not production_native_batch_followon.admissible(ep,scheduler_core.load_queue(ep)):
        return {"status":"BLOCKED","reason":"F002_AND_43_QUEUE_NOT_VERIFIED"}
    return {"status":RECOVERY,"driver_record_sha256":exits.canonical_sha(d.get("record") or {}),
            "profile_sha256":sha(ep/"meta/visual-profile.json"),
            "driver_log_sha256":sha(log),"new_image_attempts":0,
            "read_only":True,"production_authorization":False}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--episode",required=True)
    ap.add_argument("--apply",action="store_true")
    ap.add_argument("--ack-real-production",action="store_true")
    ap.add_argument("--verify-rearmed",action="store_true")
    a=ap.parse_args()
    r=(verify_rc9(a.episode) if a.verify_rearmed else
       apply(a.episode,acknowledged=a.ack_real_production) if a.apply
       else eligible(a.episode))
    print(json.dumps(r,ensure_ascii=False,default=str))
    return 0 if r.get("status") in {"PASS","READY_TO_ADJUDICATE","CONFIRMED_BY_EXISTING_DELEGATION",RECOVERY} else 2
if __name__=="__main__":raise SystemExit(main())
