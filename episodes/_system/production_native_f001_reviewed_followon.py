"""Scoped follow-on after independently PASSED F001 native direct pixels.

No provider calls. A *fresh* secondary no-image visibility probe remains
mandatory in the existing Worker. A Generation Attempt is reserved only later
by the unchanged MySQL budget/Gateway.
"""
from __future__ import annotations
import hashlib
from pathlib import Path

import episode_state_persistence
import generation_attempt_authority as attempts
import image_payload_transport
import logical_asset_identity as identity
import production_ledger_persistence as ledger_store
import runtime_request
import runtime_router
import scheduler_core
import storage_config
import story_json
import visual_lock_baseline_gate as baseline
import production_native_baseline_proof as native
import f001_attempt2_native_raw_reconcile as f001

ROOT=Path(__file__).resolve().parents[2]
EPISODE="14_深渊疗愈所_第一集_净土生命还原"
FRAMES={5,45,47}
SHA="0a9f8a2477b40c48fc1bfe93bd396be53ca1882b725a66aa2f3cac59437a135f"
REPORT=Path("meta/runtime/independent-baseline-rereviews/f001-quota-58a1e9f4f9d437f8ea9e.json")

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def eligible(ep,item,payload,controller,*,queue_override=None):
    try:
        ep=Path(ep).resolve()
        frame=int(item.get("frame") or 0)
        if (ep.name!=EPISODE or ep.parent.name!="00_独立篇"
            or not ep.is_relative_to(ROOT/"episodes")
            or frame not in FRAMES or item.get("scope")!="visual_lock"
            or item.get("kind")!="original"
            or item.get("status") not in {"queued","running","generating"}
            or item.get("model")!="gpt-image-2.5-flare"
            or item.get("quality")!="high"):
            return False
        r=runtime_request.effective_for_episode(ep) or {}
        db=storage_config.mysql_connection_kwargs()
        if (r.get("mode")!="full_auto"
            or (r.get("runtime") or {}).get("execution_mode")!="dag"
            or runtime_router.image_execution_runtime()[0]!="CODEX"
            or str(db.get("host")) not in {"127.0.0.1","localhost"}
            or int(db.get("port") or 0)!=13307
            or (episode_state_persistence.load(ep) or {}).get("current_state")!="STORYBOARD_LOCKED"
            or image_payload_transport.selected_route(1).get("provider")!="codex_subscription"
            or payload.get("model")!="gpt-image-2.5-flare"
            or payload.get("quality")!="high"
            or controller.get("model")!="gpt-6-luna"
            or controller.get("reasoning_effort")!="high"):
            return False
        q=queue_override if queue_override is not None else scheduler_core.load_queue(ep)
        original=[x for x in q.get("items") or [] if x.get("scope")=="visual_lock" and x.get("kind")=="original"]
        repairs=[x for x in q.get("items") or [] if x.get("kind")=="repair"]
        by={int(x.get("frame") or 0):x for x in original}
        if (len(q.get("items") or [])!=5 or len(original)!=4 or len(repairs)!=1
            or set(by)!={1,*FRAMES} or by[1].get("id")!="ead88592f160"
            or by[1].get("status")!="generated"
            or by[frame].get("id")!=item.get("id")
            or repairs[0].get("id")!="c006c22820c9"
            or repairs[0].get("status")!="superseded"
            or any(x.get("status") not in {"queued","running","generating","generated"}
                  or x.get("depends_on")!=[1]
                  for n,x in by.items() if n!=1)
            or not baseline.approved(ep)):
            return False
        plan=story_json.read_json(ep/"meta/visual-lock-plan.json").get("items") or []
        from frame_contract import compile_frame
        expected=[(1,"ordinary_baseline"),(45,"worst_capture_condition"),
                  (5,"first_major_anomaly"),(47,"high_impact_admission")]
        if ([(int(x.get("frame") or 0),x.get("role")) for x in plan]!=expected
            or [x.get("depends_on") for x in plan]!=[[],[1],[1],[1]]
            or any(x.get("contract_sha256")!=compile_frame(
                ep,int(x["frame"]),write_cache=False)["contract_sha256"]
                for x in plan)):
            return False
        d=ledger_store.load_authority(ep)
        row=((d or {}).get("frames") or {}).get("01") or {}
        candidate=row.get("current_candidate") or {}
        approved=row.get("approved_asset") or {}
        if (row.get("status") not in {"PASSED","LOCKED"}
            or candidate.get("sha256")!=SHA or approved.get("sha256")!=SHA
            or by[1].get("unknown_reconciliation",{}).get("candidate_sha256")!=SHA):
            return False
        report=ep/REPORT
        if not report.is_file():return False
        proof=story_json.read_json(report)
        if (proof.get("status")!="REVIEW_ONLY_PASS"
            or proof.get("image_generation_calls")!=0
            or proof.get("image_attempts_reserved")!=0
            or (row.get("independent_review_reconciliation") or {}).get("report_sha256")!=sha(report)
            or repairs[0].get("superseded_review_sha256")!=sha(report)):
            return False
        prior=story_json.read_json(ep/baseline.REL)
        info=prior.get("independent_review_reconciliation") or {}
        if (prior.get("decision")!="PASS" or prior.get("sha256")!=SHA
            or info.get("report_sha256")!=sha(report)):
            return False
        key=identity.frame_asset_key(ep,1)
        state=attempts.load_asset_state(ep,key)
        a2=attempts.load_attempt(ep,key,2) or {}
        if (state.get("attempts_consumed")!=2 or state.get("remaining_attempts")!=0
            or state.get("active_attempt_index") is not None
            or attempts.load_attempt(ep,key,3) is not None
            or a2.get("status")!="SUCCEEDED" or a2.get("provider")!="codex_subscription"
            or a2.get("generation_key")!=by[1].get("generation_key")
            or a2.get("payload_model")!=payload.get("model")):
            return False
        target_key=identity.frame_asset_key(ep,frame)
        target=attempts.load_asset_state(ep,target_key)
        if (target.get("attempts_consumed")!=0
            or target.get("active_attempt_index") is not None
            or attempts.load_attempt(ep,target_key,1)):
            return False
        raw=ep/f001.RAW_REL
        log=ep/f001.LOG_REL
        pixel=native.verify_direct_runner_archived_pixel(log,raw,f001.RID)
        evidence=story_json.read_json(ep/"meta/runtime/native-baseline-frame01-tool-proof.json")
        image=ROOT/str(by[1].get("output_path") or "")
        return bool(pixel
            and pixel.get("proof_kind")=="TRUSTED_NATIVE_DIRECT_THREAD_SCOPED_IMAGE_SHA"
            and evidence.get("runner_request_id")==f001.RID
            and evidence.get("raw_png_sha256")==sha(raw)
            and evidence.get("normalized_png_sha256")==SHA
            and image.is_file() and sha(image)==SHA)
    except Exception:
        return False
