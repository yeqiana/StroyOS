#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Story OS V2.1 Phase 6 bounded image scheduler.

Only the expensive image backend runs concurrently.
All Production Ledger mutations are committed sequentially by the scheduler main thread.
"""
from __future__ import annotations

import argparse
import asyncio
import concurrent.futures as cf
import datetime as dt
import json
import os
import subprocess
import time
import uuid
from pathlib import Path

import frame_contract
import environment_contract
import fast_frame_scout as frame_scout
import image_model_policy
import image_worker_pool
import rolling_frame_review
import asset_lineage
import character_visual_contract
import reference_arbitrator
import user_visual_reference_contract
import visual_lock_baseline_gate
import episode_performance
import raw_candidate_budget
import storyos_config
import model_policy
import scheduler_core
import batch_scheduler
import production_queue_store
import runtime_router
import product_runtime_adapter
import resource_library
import runtime_portability
import runtime_event_collector
import runtime_observability
import production_recovery
import production_ledger
import production_ledger_persistence
import runtime_timeout_policy
import local_visual_triage
import review_queue
import logical_asset_identity
import generation_attempt_authority

ROOT = Path(__file__).resolve().parents[2]
SYSTEM = Path(__file__).resolve().parent


def _telemetry_image(ep:Path,item:dict,event_type:str,*,queue_depth=None,duration_ms=None,wait_ms=None,status=None,failure_class=None,review_queue_depth=None)->None:
    """Emit best-effort image lifecycle telemetry without changing scheduler decisions."""
    try:
        from logical_asset_identity import episode_id, frame_asset_key
        binding=model_policy.resolve("image.payload",episode=ep)
        controller=model_policy.resolve("image.controller",episode=ep)
        generation_key=production_recovery.generation_key_for_item(ep,item)
        runtime_observability.safe_record_runtime_event(
            ep,event_type,episode_id=episode_id(ep),
            run_id=item.get("run_id"),step="IMAGE_GENERATION",logical_asset_key=frame_asset_key(ep,item["frame"]),
            frame_id=f"{int(item['frame']):02d}",model_role="image.payload",profile=binding.get("profile"),
            effective_model=binding.get("model"),reasoning_effort=binding.get("reasoning_effort"),
            model_policy_version=binding.get("policy_version"),model_policy_sha256=binding.get("model_policy_sha256"),
            provider=item.get("provider"),runner=item.get("runner"),worker_id=item.get("worker_id"),
            attempt_index=max(1,int(item.get("attempts") or 1)),generation_key=generation_key or None,
            queue_name="repair" if item.get("scope")=="repair" else "image",
            queue_depth=queue_depth,duration_ms=duration_ms,wait_ms=wait_ms,
            review_queue_depth_at_dispatch=review_queue_depth if event_type in {"WORKER_ADMITTED", "WORKER_DISPATCH_COMMITTED"} else None,
            status=status,failure_class=failure_class,source="image_scheduler",
            evidence_ref=item.get("provider_receipt") or item.get("id"),
            controller_model=controller.get("model"),controller_effort=controller.get("reasoning_effort"),
            controller_profile=controller.get("profile"),controller_policy_sha256=controller.get("model_policy_sha256"),
            payload_model=binding.get("model"),payload_quality=item.get("quality"),
            repair_wave_id=item.get("repair_wave_id"),
            source_generation_key=item.get("source_generation_key"),
            repair_generation_key=generation_key if item.get("scope")=="repair" else None)
    except Exception:
        return


def _observed_ms(start,end):
    try:
        a=dt.datetime.fromisoformat(str(start));b=dt.datetime.fromisoformat(str(end))
        return max(0.0,(b-a).total_seconds()*1000)
    except Exception:
        return None
QUEUE_REL = scheduler_core.QUEUE_REL
SCHEDULER_LOCK_REL = Path("meta/runtime-image-scheduler.lock")
_CONFIG = storyos_config.load_config()
MAX_SUPPORTED_WORKERS = int(storyos_config.get_path(_CONFIG, "production.max_inflight_images"))
DEFAULT_IMAGE_QUALITY = str(model_policy.resolve("image.payload")["quality"])
TECH_RETRY_MAX = int(storyos_config.get_path(_CONFIG, "production.technical_retry.max_attempts_per_item"))
TECH_RETRY_BACKOFF = tuple(int(x) for x in storyos_config.get_path(_CONFIG, "production.technical_retry.backoff_seconds"))
RETRYABLE_TECH_CODES = {
    "NETWORK_ERROR", "NETWORK_CONNECT", "RATE_LIMIT_429", "BACKEND_5XX", "PROVIDER_CAPACITY", "PROVIDER_QUOTA_EXHAUSTED", "TIMEOUT", "IMAGE_BACKEND_ERROR",
    "IMAGE_BACKEND_NO_OUTPUT", "IMAGE_TOOL_NO_ARTIFACT",
    "LOCAL_WORKSPACE_PERMISSION",
    "PROVIDER_ARTIFACT_SAVE_COLLISION", "WORKER_FAILED", "WORKER_INTERRUPTED_FAILURE", "WORKER_PROCESS_LOST",
    # A provider RAW that violates the frozen canvas may use the one remaining
    # real-generation slot. It does not receive a separate retry budget.
    "ASPECT_RATIO_MISMATCH",
}
# Failure at provider/tool capability preflight is not a generated-image
# failure. The image_worker_pool returns image_attempt_reserve_called=False.
# A later provider setup must explicitly restore this capability before any
# new image request is queued; do not blindly retry and exhaust worker slots.
PRE_DISPATCH_CAPABILITY_BLOCK_CODES = frozenset({
    "CODEX_NATIVE_IMAGE_PROVIDER_REQUIRED",
    "LOGIN_AUTH_RUNNER_UNAVAILABLE",
    "LOGIN_AUTH_IMAGE_TOOL_CAPABILITY_UNKNOWN",
    "LOGIN_AUTH_IMAGE_TOOL_UNAVAILABLE_FOR_VISIBLE_MODELS",
    "LOGIN_AUTH_IMAGE_TOOL_CONFIG_UNAVAILABLE",
    "LOGIN_AUTH_MODEL_CATALOG_INVALID",
    "LOGIN_AUTH_MODEL_CATALOG_FAILED",
    "LOGIN_AUTH_TRANSPORT_MODEL_UNAVAILABLE",
})

NON_REGENERATING_FAILURE_CODES = {
    "NORMALIZE_REVIEW", "NORMALIZE_TECHNICAL_FAILURE",
    "NORMALIZE_INPUT_MISSING", "NORMALIZE_OUTPUT_EXISTS", "NORMALIZE_OUTPUT_FORMAT",
    "EPISODE_CANVAS_MISMATCH", "IMAGE_MODEL_CONTRACT_MISMATCH", "IMAGE_QUALITY_CONTRACT_MISMATCH",
    "RAW_CANDIDATE_BUDGET_EXHAUSTED",
    # Shared multi-Episode capacity failures happen before Provider dispatch;
    # they never justify technical image regeneration or budget reset.
    "GLOBAL_IMAGE_CAPACITY_BUSY", "GLOBAL_IMAGE_CAPACITY_SHARED_ROOT_UNAVAILABLE",
    "GLOBAL_IMAGE_CAPACITY_LOCK_FAILED", "GLOBAL_IMAGE_CAPACITY_REQUEST_INVALID",
    "GLOBAL_IMAGE_CAPACITY_NESTED_WEIGHT_EXCEEDS_HELD",
    "EPISODE_IMAGE_LOOP_GUARD",
    "RUNTIME_CIRCUIT_OPEN",
    "IMAGE_ATTEMPT_OUTCOME_UNKNOWN", "IMAGE_ATTEMPT_AUTHORITY_UNVERIFIED",
    "CANDIDATE_COMMIT_FAILED",  # STORY_OS_V2_6_0_PERFORMANCE_RUNTIME
    "PROMPT_SOURCE_DRIFT",
    "NO_AUTOMATABLE_IMAGE_PAYLOAD_PROVIDER", "PAYLOAD_MODEL_UNSUPPORTED",
    "PAYLOAD_QUALITY_UNSUPPORTED", "PAYLOAD_ROUTE_CONFIGURATION_INVALID",
    "PAYLOAD_CAPABILITY_REGISTRY_INVALID", "PAYLOAD_CAPABILITY_CONTRACT_MISMATCH",
    "IMAGE_CONTROLLER_OR_PAYLOAD_REQUEST_BLOCKED", "IMAGE_PAYLOAD_REQUEST_INVALID",
    *PRE_DISPATCH_CAPABILITY_BLOCK_CODES,
}

READY_LEDGER_STATES = production_ledger.READY_LEDGER_STATES


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> dict:
    return story_json.read_json(path)


def write_json(path: Path,data:dict)->None:
    story_json.write_json(path, data)


def resolve_ep(raw:str)->Path:
    ep=Path(raw).resolve()
    if not ep.is_dir():raise SystemExit(f"episode directory not found: {ep}")
    try:ep.relative_to(ROOT.resolve())
    except ValueError:raise SystemExit("episode must be inside repository")
    return ep


def repo_file(raw:str)->Path:
    p=Path(raw)
    p=p.resolve() if p.is_absolute() else (ROOT/p).resolve()
    try:p.relative_to(ROOT.resolve())
    except ValueError as exc:raise ValueError(f"path escapes repository: {raw}") from exc
    if not p.is_file():raise ValueError(f"file missing: {raw}")
    return p


def repo_rel(path:Path)->str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def load_queue(ep:Path)->dict:
    return scheduler_core.load_queue(ep, max_parallel=MAX_SUPPORTED_WORKERS)


def save_queue(ep:Path,q:dict)->None:
    scheduler_core.save_queue(ep,q)


QueueMutationBusy = scheduler_core.QueueMutationBusy


queue_transaction = scheduler_core.queue_transaction


def ledger(ep:Path)->dict:
    return scheduler_core.ledger(ep)


def ledger_state(ep:Path,frame:int)->str:
    return scheduler_core.ledger_state(ep,frame)


from frame_risk import risk_priority
import story_json


def directive_dependency(ep:Path,frame:int)->list[int]:
    # STORY_OS_V211_PERF_FINAL_R2: narrative escalation never implies PNG serialization.
    # Only an explicit generation_depends_on declares a true pixel prerequisite.
    d=frame_contract.compile_frame(ep,frame,write_cache=True)["hash_material"]["frame_directive"]
    raw=d.get("generation_depends_on")
    if raw in (None,"",[]):return []
    values=raw if isinstance(raw,list) else str(raw).replace(";",",").split(",")
    out=[]
    for value in values:
        try:n=int(value)
        except Exception:continue
        if 1<=n<frame and n not in out:out.append(n)
    return sorted(out)


def narrative_escalation_from(ep:Path,frame:int)->int|None:
    d=frame_contract.compile_frame(ep,frame,write_cache=True)["hash_material"]["frame_directive"]
    try:
        n=int(d.get("escalation_from"))
        return n if 1<=n<frame else None
    except Exception:return None


def _merge_execution_references(base:list[dict], overlays:list[dict])->list[dict]:
    """Keep required identity continuity, then prefer explicit user overlays."""
    limit=int(reference_arbitrator.MAX_REFS)
    chosen=[]
    identity=[x for x in base if isinstance(x,dict) and x.get("kind")=="identity"]
    overlay_identity=[x for x in overlays if isinstance(x,dict) and x.get("kind")=="identity"]
    overlay_other=[x for x in overlays if not (isinstance(x,dict) and x.get("kind")=="identity")]
    others=[x for x in base if not (isinstance(x,dict) and x.get("kind")=="identity")]
    # Give the remaining attachment slot to an explicitly provided identity
    # before a user capture-style example, but never evict existing anchors.
    for row in [*identity, *overlay_identity, *overlay_other, *others]:
        if not isinstance(row,dict) or not row.get("path"):
            continue
        if any(x.get("path")==row.get("path") for x in chosen):
            continue
        chosen.append(row)
        if len(chosen)>=limit:
            break
    return chosen


def contract_references(ep:Path,frame:int,scope:str="batch")->list[dict]:
    refs,_=reference_arbitrator.select(ep,frame,scope=scope)
    overlays=user_visual_reference_contract.references_for_frame(ep,frame,scope)
    refs=_merge_execution_references(refs,overlays)
    # Required reference anchors are execution contracts, not documentation only.
    gates_path=ep / "meta" / "story-gates.json"
    gates={}
    try:
        if gates_path.exists():
            gates=json.loads(gates_path.read_text(encoding="utf-8"))
    except Exception:
        gates={}
    check=reference_arbitrator.validate_required_anchor_execution(ep,frame,refs,gates)
    if not check.get("ok"):
        raise RuntimeError("REQUIRED_REFERENCE_ANCHOR_MISSING:" + ",".join(check.get("missing_anchors") or []))
    return refs


def init_queue(ep:Path,force:bool=False)->dict:
    with queue_transaction(ep):
        # In Redis hot-state mode the compatibility file is intentionally absent;
        # consult the authoritative projection before deciding to initialize.
        # Otherwise every prepare cycle recreates an empty queue and discards the
        # items already admitted in Redis.
        import hot_state_bridge
        hot = hot_state_bridge.read(ep, "QUEUE")
        if not force and isinstance(hot.get("value"), dict):
            return hot["value"]
        p=scheduler_core.queue_read_path(ep)
        if p.exists() and not force:return read_json(p)
        q={"schema_version":1,"created_at":now(),"updated_at":now(),"max_parallel":MAX_SUPPORTED_WORKERS,"adaptive_parallel":MAX_SUPPORTED_WORKERS,"stable_waves":0,"items":[],"waves":[]}
        save_queue(ep,q);return q


def add_item(ep:Path,*,frame:int,kind:str,prompt_file:Path,scope:str,references:list[dict],capture_id:str,model:str,depends_on:list[int],quality:str=DEFAULT_IMAGE_QUALITY,strict_model:bool=False,replace:bool=False,production_revision_id:str|None=None)->dict:
    with queue_transaction(ep):
        q=load_queue(ep)
        key=f"{frame:02d}"
        active=[x for x in q.get("items") or [] if f"{int(x.get('frame')):02d}"==key and x.get("kind")==kind and str(x.get("production_revision_id") or "")==str(production_revision_id or "") and x.get("status") in {"queued","running","generated","tech_failed"}]
        if active and not replace:
            return active[-1]
        if replace:
            replaceable=[x for x in q.get("items") or [] if f"{int(x.get('frame')):02d}"==key and x.get("kind")==kind and str(x.get("production_revision_id") or "")==str(production_revision_id or "") and x.get("status") in {"queued","running","generated","tech_failed","blocked","scout_repair"}]
            for x in replaceable:x["status"]="superseded"
        contract=frame_contract.provenance(ep,frame)
        if frame_contract.required(ep):
            import prompt_package
            package=prompt_package.compile_frame(ep,frame,prompt_file)
            admission_snapshot={
                "package_sha256":package["package_sha256"],
                "scene_prompt_sha256":package["scene_prompt_sha256"],
                "frame_contract_sha256":package["frame_contract_sha256"],
            }
        else:
            admission_snapshot=None
        item={
            "id":uuid.uuid4().hex[:12],
            "frame":frame,
            "kind":kind,
            "scope":scope,
            "production_revision_id":str(production_revision_id) if production_revision_id else None,
            "status":"queued",
            "prompt_file":repo_rel(prompt_file),
            "references":references,
            # W-17: persist the exact execution contract instead of only the declaration.
            "reference_execution_contract":{
                "selected_at_enqueue":now(),
                "selected_references":references,
                "selected_roles":[str(x.get("role") or "") for x in references if isinstance(x,dict)],
                "selected_kinds":[str(x.get("kind") or "") for x in references if isinstance(x,dict)],
            },
            "capture_id":capture_id,
            "model":model,
            "quality":quality,
            "strict_model":bool(strict_model),
            "depends_on":sorted(set(int(x) for x in depends_on if int(x)!=frame)),
            "narrative_escalation_from":narrative_escalation_from(ep,frame),
            "priority":risk_priority(ep,frame,scope),
            "frame_contract":contract,
            "prompt_package":admission_snapshot,
            "attempts":0,
            "output_path":None,
            "log_path":None,
            "last_error":None,
            "queued_at":now(),
        }
        q.setdefault("items",[]).append(item);save_queue(ep,q)
        depth=sum(1 for row in q["items"] if row.get("status") in {"queued","running"})
        _telemetry_image(ep,item,"IMAGE_GENERATION_REQUESTED",queue_depth=depth,status="queued")
        if scope=="repair":
            _telemetry_image(ep,item,"REPAIR_ENQUEUED",queue_depth=depth,status="queued")
        return item


def parse_ref(raw:str)->dict:
    parts=raw.split("::")
    if len(parts)!=3:raise ValueError("reference must be PATH::ROLE::KIND")
    p=repo_file(parts[0].strip())
    return {"path":repo_rel(p),"role":parts[1].strip(),"kind":parts[2].strip()}


def import_visual_lock(ep:Path,prompt_dir:Path)->dict:
    plan_path=ep/"meta/visual-lock-plan.json"
    if not plan_path.is_file():raise ValueError("visual-lock-plan missing; run visual_lock_v21.py prepare")
    plan=read_json(plan_path)
    revision_id=str(plan.get("production_revision_id") or "") or None
    revision_bindings={}
    if revision_id:
        import production_revision_authority
        revision_bindings={int(row["frame"]):row for row in production_revision_authority.load_frame_bindings(ep,revision_id)}
        import prompt_package
    q=init_queue(ep)
    added=[]
    for row in plan.get("items") or []:
        frame=int(row["frame"]);prompt=prompt_dir/f"{frame:02d}.txt"
        if not prompt.is_file():raise ValueError(f"Visual Lock prompt missing: {prompt}")
        binding=revision_bindings.get(frame) if revision_id else None
        if revision_id:
            if not binding or str(row.get("production_revision_id") or "")!=revision_id:
                raise ValueError(f"Visual Lock plan is not bound to Revision frame {frame:02d}")
            package=prompt_package.compile_frame(ep,frame,prompt,write=False)
            if (str(package.get("package_sha256") or "").lower()!=str(binding.get("prompt_sha256") or "").lower()
                    or str(package.get("frame_contract_sha256") or "").lower()!=str(binding.get("frame_contract_sha256") or "").lower()):
                raise ValueError(f"Revision Prompt/Frame Contract SHA mismatch at frame {frame:02d}")
        # A predispatch capability block is still the single authoritative
        # original request. Never enqueue a second paid image Attempt simply
        # because add_item's normal active set excludes "blocked" rows.
        blocked_existing=[x for x in (load_queue(ep).get("items") or [])
                          if x.get("scope")=="visual_lock"
                          and x.get("kind")=="original"
                          and int(x.get("frame") or 0)==frame
                          and str(x.get("production_revision_id") or "")==str(revision_id or "")
                          and x.get("status") in {"blocked","external_blocked","interrupted_unknown"}]
        if blocked_existing:
            if len(blocked_existing)!=1:
                raise ValueError(f"duplicate blocked Visual Lock originals frame {frame:02d}")
            item=blocked_existing[0]
            current_sha=frame_contract.compile_frame(ep,frame,write_cache=False)["contract_sha256"]
            if (str((item.get("frame_contract") or {}).get("contract_sha256") or "")!=current_sha
                    or str((item.get("prompt_package") or {}).get("frame_contract_sha256") or "")!=current_sha):
                raise ValueError(f"blocked Visual Lock request contract stale frame {frame:02d}")
        else:
            policy=image_model_policy.for_episode(ep)
            item=add_item(ep,frame=frame,kind="original",prompt_file=prompt,scope="visual_lock",references=contract_references(ep,frame,scope="visual_lock"),capture_id=f"visual-lock-{frame:02d}",model=policy["model"],quality=policy["quality"],strict_model=bool(policy.get("strict_model")),depends_on=[int(x) for x in row.get("depends_on") or []],replace=False,production_revision_id=revision_id)
        if revision_id and str((item.get("prompt_package") or {}).get("package_sha256") or "").lower()!=str(binding.get("prompt_sha256") or "").lower():
            raise ValueError(f"queued Visual Lock Prompt SHA mismatch at frame {frame:02d}")
        added.append(item)
    return {"added":[x["id"] for x in added]}


def refresh_queued_visual_lock_references(ep:Path)->dict:
    """Re-resolve queued Visual Lock lineage references after baseline PASS.

    Initial Visual Lock rows, bounded candidates, and repair rows can all be
    queued before a provisional Pixel Master exists. Once baseline PASS creates
    that master, refresh every still-queued Visual Lock lineage request; never
    mutate already-started/generated requests.
    """
    with queue_transaction(ep):
        q=load_queue(ep);updated=[]
        for item in q.get("items") or []:
            if item.get("status")!="queued" or item.get("scope") not in {"visual_lock","repair","baseline_candidate"}:
                continue
            frame=int(item.get("frame") or 0)
            ref_scope="visual_lock" if item.get("scope")=="visual_lock" else "repair"
            refs=contract_references(ep,frame,scope=ref_scope)
            item["references"]=refs
            item["reference_execution_contract"]={
                "selected_at_enqueue":now(),
                "selected_references":refs,
                "selected_roles":[str(x.get("role") or "") for x in refs if isinstance(x,dict)],
                "selected_kinds":[str(x.get("kind") or "") for x in refs if isinstance(x,dict)],
                "refresh_reason":"baseline_pixel_master_available",
            }
            updated.append(frame)
        save_queue(ep,q)
        return {"updated_frames":sorted(updated),"count":len(updated)}


def import_batch(ep:Path,prompt_dir:Path)->dict:
    total=frame_contract.frame_count(ep);q=init_queue(ep);added=[];skipped=[]
    existing={(int(x["frame"]),x.get("kind")) for x in q.get("items") or [] if x.get("status") not in {"superseded"}}
    for frame in range(1,total+1):
        if ledger_state(ep,frame) in READY_LEDGER_STATES:
            skipped.append(frame);continue
        if (frame,"original") in existing:
            skipped.append(frame);continue
        prompt=prompt_dir/f"{frame:02d}.txt"
        if not prompt.is_file():raise ValueError(f"batch prompt missing: {prompt}")
        policy=image_model_policy.for_episode(ep)
        added.append(add_item(ep,frame=frame,kind="original",prompt_file=prompt,scope="batch",references=contract_references(ep,frame,scope="batch"),capture_id=f"batch-{frame:02d}",model=policy["model"],quality=policy["quality"],strict_model=bool(policy.get("strict_model")),depends_on=directive_dependency(ep,frame),replace=False))
    return {"added":[x["frame"] for x in added],"skipped":skipped}


def dependency_satisfied(ep:Path,q:dict,dep:int,scope:str="batch")->bool:
    # Ordinary baseline is the identity bootstrap for every downstream lane,
    # including repair/baseline-candidate rows. Historical generated pixels must
    # not satisfy this dependency after a later review reopens the baseline.
    if visual_lock_baseline_gate.is_baseline_dependency(ep,dep):
        return visual_lock_baseline_gate.approved(ep)
    state=ledger_state(ep,dep)
    if state in READY_LEDGER_STATES:return True
    rows=[x for x in q.get("items") or [] if int(x.get("frame"))==dep and x.get("status")=="generated"]
    return bool(rows)


def ready_items(ep:Path,q:dict)->tuple[list[dict],list[dict]]:
    ready=[];blocked=[]
    for item in q.get("items") or []:
        if item.get("status")!="queued":continue
        deps=[int(x) for x in item.get("depends_on") or []]
        if all(dependency_satisfied(ep,q,x,str(item.get("scope") or "batch")) for x in deps):ready.append(item)
        else:blocked.append(item)
    ready.sort(key=lambda x:(-int(x.get("priority") or 0),int(x["frame"])))
    return ready,blocked


def unresolved_generation_evidence_for_plan(ep:Path,q:dict)->list[dict]:
    """Read-only evidence blockers for historical technical image Attempts.

    Legacy `blocked` in the scheduler plan means a *queued dependency*
    cannot run. A `tech_failed` row whose shared Generation Attempt outcome
    is unknown is different: it needs review of original Provider evidence.
    Keep these separate so an empty ready/dependency list never suggests the
    Episode has no outstanding production work.
    """
    unresolved=[]
    for item in q.get("items") or []:
        if not isinstance(item,dict) or item.get("status")!="tech_failed":
            continue
        frame=int(item.get("frame") or 0)
        if frame<1:
            continue
        code=str(item.get("technical_failure_code") or _technical_retry_code(item))
        try:
            allowed,_state,reason=_technical_retry_budget(ep,item,code)
        except Exception:
            # A read-only plan must not turn an unavailable MySQL Authority
            # into permission to regenerate, nor hide unresolved Episode work.
            allowed=False
            reason="generation_attempt_authority_unavailable"
        if allowed:
            continue
        unresolved.append({
            "frame":frame,
            "technical_failure_code":code,
            "reason":reason,
            "action":"VERIFY_TECHNICAL_GENERATION_EVIDENCE",
            "retry_permitted":False,
        })
    return sorted(unresolved,key=lambda row:row["frame"])


def plan_snapshot(ep:Path,q:dict)->dict:
    """Report dependency, paid evidence, and pre-dispatch capability blocks separately.

    Snapshot only: blocked image-tool capability is unresolved production work,
    never readiness to retry or permission to reserve another paid Attempt.
    """
    ready,blocked=ready_items(ep,q)
    authority_blocked=unresolved_generation_evidence_for_plan(ep,q)
    terminal_blocks=[
        item for item in (q.get("items") or [])
        if isinstance(item,dict) and item.get("status")=="blocked"
    ]
    capability_blocked=sorted([
        {"frame":int(item.get("frame") or 0),
         "technical_failure_code":str(item.get("technical_failure_code") or ""),
         "action":"VERIFY_NATIVE_CODEX_IMAGE_CAPABILITY",
         "retry_permitted":False}
        for item in terminal_blocks
        if str(item.get("technical_failure_code") or "") in PRE_DISPATCH_CAPABILITY_BLOCK_CODES
    ],key=lambda row:row["frame"])
    return {
        "ready":[{"frame":x["frame"],"priority":x["priority"],"scope":x["scope"]} for x in ready],
        "blocked":[{"frame":x["frame"],"depends_on":x["depends_on"]} for x in blocked],
        "authority_blocked":authority_blocked,
        "requires_evidence_verification":bool(authority_blocked),
        "capability_blocked":capability_blocked,
        "capability_blocked_count":len(capability_blocked),
        "unresolved_status_blocked_count":len(terminal_blocks),
        "requires_capability_verification":bool(capability_blocked),
        "progress":scheduler_core.progress(ep,q),
    }


def current_contract_sha(ep:Path,frame:int)->str:
    return scheduler_core.current_contract_sha(ep,frame)


def ledger_begin(ep:Path,item:dict)->tuple[bool,str]:
    return scheduler_core.ledger_begin(
        ep,
        item,
        notes=f"phase6 scheduler item={item['id']} scope={item['scope']}",
    )


def backend_worker(ep:Path,item:dict,timeout:int,codex:str|None)->dict:
    # Warm Python pool: reuse scheduler/module state, never cross-frame Codex conversation state.
    return image_worker_pool.execute(ep,item,timeout,codex)


def ledger_success(ep:Path,item:dict,result:dict)->tuple[bool,str]:
    return scheduler_core.ledger_success(ep,item,result,
                                         default_quality=DEFAULT_IMAGE_QUALITY)


def ledger_tech_fail(ep:Path,item:dict,code:str,message:str)->None:
    scheduler_core.ledger_tech_fail(ep,item,code,message)


def classify_error(text:str)->str:
    # Explicit pre-dispatch capability errors must retain their distinct code,
    # instead of collapsing into IMAGE_BACKEND_ERROR and inviting retries.
    upper=str(text or "").upper()
    for code in sorted(PRE_DISPATCH_CAPABILITY_BLOCK_CODES):
        if code in upper:return code
    for code in NON_REGENERATING_FAILURE_CODES:
        if code in upper:return code
    if "ASPECT_RATIO_MISMATCH" in text:return "ASPECT_RATIO_MISMATCH"
    if "IMAGE_TOOL_NO_ARTIFACT" in text:return "IMAGE_TOOL_NO_ARTIFACT"
    if "IMAGE_BACKEND_NO_OUTPUT" in text:return "IMAGE_BACKEND_NO_OUTPUT"
    low=text.lower()
    # Prefer structured transport booleans before the broader model/backend
    # classifier.  Codex logs always print the timeout field name, including
    # when it is explicitly false; treating that token as a timeout produced
    # misleading W-98 evidence.
    if "error_is_timeout=false" in low and "error_is_connect=true" in low:
        return "NETWORK_CONNECT"
    if "error_is_timeout=true" in low:
        return "TIMEOUT"
    model_code=image_model_policy.classify_backend_error(text, source="image_backend")
    if model_code:return model_code
    if any(token in low for token in ("connection refused", "connect error", "connection error", "error sending request")):
        return "NETWORK_CONNECT"
    if "timeout" in low:return "TIMEOUT"
    if "500" in low or "502" in low or "503" in low or "5xx" in low:return "BACKEND_5XX"
    if "contract" in low and "drift" in low:return "CONTRACT_DRIFT"
    return "IMAGE_BACKEND_ERROR"


def _fence_native_rate_limit_unknown(ep:Path,item:dict,code:str)->str:
    """Never interpret Codex assistant's '429' text as a terminal image verdict.

    The image tool can be invoked without a JSONL image tool event, and the
    thread's visible reply is NOT independent proof of paid-dispatch outcome.
    Match the canonical MySQL Attempt to the durable item lifecycle first.
    This function NEVER mutates the Attempt, lease, retry budget or provider.
    """
    if code != "RATE_LIMIT_429":
        return code
    try:
        key=logical_asset_identity.frame_asset_key(ep,int(item["frame"]))
        state=generation_attempt_authority.load_asset_state(ep,key)
        consumed=int(state.get("attempts_consumed") or 0)
        if consumed <= 0:
            return code  # Truly pre-dispatch; no paid Attempt exists.
        attempt=generation_attempt_authority.load_attempt(ep,key,consumed) or {}
        if attempt.get("status") != "OUTCOME_UNKNOWN":
            return code
        lifecycle=production_recovery._read(
            production_recovery.lifecycle_path(ep,item)) or {}
        if (state.get("active_attempt_index") is not None
                or int(attempt.get("attempt_index") or 0) != consumed
                or int(lifecycle.get("attempt") or 0) != consumed
                or str(lifecycle.get("item_id") or "") != str(item.get("id") or "")
                or not str(attempt.get("generation_key") or "")
                or attempt.get("generation_key") != lifecycle.get("generation_key")):
            return "IMAGE_ATTEMPT_AUTHORITY_UNVERIFIED"
        return "IMAGE_ATTEMPT_OUTCOME_UNKNOWN"
    except Exception:
        # On MySQL outage we cannot certify a 429 is safely retryable.
        return "IMAGE_ATTEMPT_AUTHORITY_UNVERIFIED"


def _terminal_technical_status(ep:Path,item:dict,code:str)->str:
    """Choose terminal state from the shared max-2 Generation Attempt budget."""
    if code in NON_REGENERATING_FAILURE_CODES:
        return "blocked"
    if code == image_model_policy.PROVIDER_QUOTA_EXHAUSTED:
        # Account quota is an external condition, not a reason to immediately
        # consume the final shared Attempt. Keep it explicitly retryable, but
        # require a later operator retry after quota/credits are available.
        try:
            state=_shared_generation_attempt_state(ep,item)
        except Exception:
            state={}
        item["external_block"]={
            "at":now(),
            "reason":"provider_quota_exhausted",
            "code":code,
            "attempts_consumed":state.get("attempts_consumed"),
            "remaining_attempts":state.get("remaining_attempts"),
            "max_real_generation_attempts":
                generation_attempt_authority.MAX_REAL_IMAGE_GENERATION_ATTEMPTS_PER_ASSET,
        }
        return "external_blocked"
    if code in RETRYABLE_TECH_CODES:
        allowed,state,reason=_technical_retry_budget(ep,item,code)
        if not allowed:
            item["external_block"]={
                "at":now(),"reason":reason,"code":code,
                "attempts_consumed":state.get("attempts_consumed"),
                "remaining_attempts":state.get("remaining_attempts"),
                "max_real_generation_attempts":
                    generation_attempt_authority.MAX_REAL_IMAGE_GENERATION_ATTEMPTS_PER_ASSET,
            }
            return "external_blocked"
        return "tech_failed"
    return "tech_failed"


async def async_backend_worker(ep:Path,item:dict,timeout:int,codex:str|None)->dict:
    """V2.7 async runtime bridge.

    A worker function returning normally is not necessarily an image success:
    image_worker_pool reports transport/backend failures as structured results.
    Convert those results into task failures so RuntimeImageEvent semantics stay
    truthful and the scheduler can close the active ledger attempt correctly.
    """
    _telemetry_image(ep,item,"WORKER_DISPATCH_STARTED",status="started")
    if item.get("scope")=="repair":
        _telemetry_image(ep,item,"REPAIR_STARTED",status="started")
        _telemetry_image(ep,item,"REPAIR_GENERATION_STARTED",status="started")
    result=await asyncio.to_thread(backend_worker,ep,item,timeout,codex)
    output=result.get("output")
    if result.get("returncode")!=0 or not output or not Path(output).is_file():
        message=str(result.get("stdout") or "image backend returned no committed output")
        raise RuntimeError(message)
    return result


def _generation_identity_from_result(ep: Path, item: dict, result: dict | None = None) -> dict:
    """Resolve one committed Generation Attempt identity from durable evidence."""
    result = result if isinstance(result, dict) else {}
    budget = result.get("candidate_budget") if isinstance(result.get("candidate_budget"), dict) else {}
    authority = budget.get("authority") if isinstance(budget.get("authority"), dict) else {}
    lifecycle = production_recovery._read(production_recovery.lifecycle_path(ep, item))
    if not isinstance(lifecycle, dict):
        lifecycle = {}

    generation_key = str(
        budget.get("generation_key")
        or authority.get("generation_key")
        or lifecycle.get("generation_key")
        or production_recovery.generation_key_for_item(ep, item)
        or ""
    )
    attempt_index = int(
        budget.get("attempt_index")
        or authority.get("attempt_index")
        or lifecycle.get("attempt_index")
        or lifecycle.get("attempt")
        or item.get("attempt_index")
        or item.get("attempts")
        or 0
    )
    if not generation_key or attempt_index <= 0:
        return {
            "ok": False,
            "generation_key": generation_key or None,
            "attempt_index": attempt_index or None,
            "reason": "generation_identity_missing",
        }

    key = logical_asset_identity.frame_asset_key(ep, int(item.get("frame") or 0))
    try:
        attempt = generation_attempt_authority.load_attempt(ep, key, attempt_index)
    except Exception as exc:
        return {
            "ok": False,
            "generation_key": generation_key,
            "attempt_index": attempt_index,
            "reason": f"generation_attempt_authority_unavailable:{type(exc).__name__}",
        }
    if not isinstance(attempt, dict):
        return {
            "ok": False,
            "generation_key": generation_key,
            "attempt_index": attempt_index,
            "reason": "generation_attempt_authority_missing",
        }
    if str(attempt.get("generation_key") or "") != generation_key:
        return {
            "ok": False,
            "generation_key": generation_key,
            "attempt_index": attempt_index,
            "reason": "generation_key_authority_mismatch",
        }
    if str(attempt.get("status") or "").upper() != "SUCCEEDED":
        return {
            "ok": False,
            "generation_key": generation_key,
            "attempt_index": attempt_index,
            "reason": "generation_attempt_not_succeeded",
        }
    return {
        "ok": True,
        "generation_key": generation_key,
        "attempt_index": attempt_index,
        "reason": "generation_attempt_authority_verified",
    }


def _persist_generation_identity(ep: Path, item: dict, result: dict | None = None) -> dict:
    """Persist Generation identity on the canonical Queue Item after success."""
    identity = _generation_identity_from_result(ep, item, result)
    if identity.get("ok") is not True:
        return identity
    existing_key = str(item.get("generation_key") or "")
    existing_attempt = int(item.get("attempt_index") or 0)
    if existing_key and existing_key != identity["generation_key"]:
        return {**identity, "ok": False, "reason": "queue_generation_key_conflict"}
    if existing_attempt and existing_attempt != int(identity["attempt_index"]):
        return {**identity, "ok": False, "reason": "queue_attempt_index_conflict"}
    item["generation_key"] = identity["generation_key"]
    item["attempt_index"] = int(identity["attempt_index"])
    return identity


def _reconcile_generation_identity_to_ledger(ep: Path, item: dict, identity: dict) -> dict:
    """Backfill missing Ledger identity only when Queue/output/Attempt all agree."""
    if identity.get("ok") is not True:
        return {**identity, "ledger_updated": False}
    ledger = production_ledger.load_authority(ep, default={}) or {}
    key = f"{int(item.get('frame') or 0):02d}"
    frame = ((ledger.get("frames") or {}).get(key) or {})
    candidate = frame.get("current_candidate") if isinstance(frame.get("current_candidate"), dict) else None
    if not isinstance(candidate, dict):
        return {**identity, "ok": False, "ledger_updated": False,
                "reason": "ledger_current_candidate_missing"}
    item_path = str(item.get("output_path") or "").replace("\\", "/")
    candidate_path = str(candidate.get("path") or candidate.get("asset_path") or "").replace("\\", "/")
    if not item_path or candidate_path != item_path:
        return {**identity, "ok": False, "ledger_updated": False,
                "reason": "ledger_candidate_path_mismatch"}
    attempt_id = str(candidate.get("attempt_id") or "")
    attempt = next((row for row in frame.get("attempts") or []
                    if isinstance(row, dict) and str(row.get("attempt_id") or "") == attempt_id), None)
    if not isinstance(attempt, dict) or str(attempt.get("result") or "") != "success":
        return {**identity, "ok": False, "ledger_updated": False,
                "reason": "ledger_success_attempt_missing"}
    for target in (attempt, candidate):
        existing_key = str(target.get("generation_key") or "")
        existing_index = int(target.get("generation_attempt_index") or 0)
        if existing_key and existing_key != identity["generation_key"]:
            return {**identity, "ok": False, "ledger_updated": False,
                    "reason": "ledger_generation_key_conflict"}
        if existing_index and existing_index != int(identity["attempt_index"]):
            return {**identity, "ok": False, "ledger_updated": False,
                    "reason": "ledger_attempt_index_conflict"}
    attempt["generation_key"] = identity["generation_key"]
    attempt["generation_attempt_index"] = int(identity["attempt_index"])
    candidate["generation_key"] = identity["generation_key"]
    candidate["generation_attempt_index"] = int(identity["attempt_index"])
    production_ledger_persistence.persist_authority(ep, ledger)
    return {**identity, "ledger_updated": True}


def reconcile_generated_identities(ep: Path) -> dict:
    """Repair Queue + Ledger identity from immutable MySQL Attempt Authority only.

    Resume-safe: this never dispatches a Provider or reserves an Attempt.
    A complete Queue row without a persisted Ledger candidate remains untouched;
    Ledger backfill is attempted only when the canonical candidate exists.
    """
    ep = Path(ep).resolve()
    repaired = []
    ledger_repaired = []
    blocked = []
    with queue_transaction(ep):
        q = load_queue(ep)
        queue_changed = False
        for item in q.get("items") or []:
            if not isinstance(item, dict) or item.get("status") != "generated":
                continue

            queue_key = str(item.get("generation_key") or "")
            queue_attempt = int(item.get("attempt_index") or 0)
            ledger = production_ledger.load_authority(ep, default={}) or {}
            frame_key = f"{int(item.get('frame') or 0):02d}"
            frame = ((ledger.get("frames") or {}).get(frame_key) or {})
            candidate = frame.get("current_candidate") if isinstance(frame.get("current_candidate"), dict) else None

            # Legacy/unit contexts may have no canonical Ledger candidate. Keep a
            # complete Queue identity unchanged rather than manufacturing a failure.
            if queue_key and queue_attempt > 0 and not isinstance(candidate, dict):
                continue

            # If both authorities already carry identity, only detect conflict.
            if queue_key and queue_attempt > 0 and isinstance(candidate, dict):
                ledger_key = str(candidate.get("generation_key") or "")
                ledger_attempt = int(candidate.get("generation_attempt_index") or 0)
                if ledger_key and ledger_attempt:
                    if ledger_key != queue_key or ledger_attempt != queue_attempt:
                        blocked.append({
                            "id": item.get("id"), "frame": item.get("frame"),
                            "reason": "queue_ledger_generation_identity_conflict",
                        })
                    continue

            identity = _generation_identity_from_result(ep, item)
            if identity.get("ok") is not True:
                blocked.append({
                    "id": item.get("id"), "frame": item.get("frame"),
                    "reason": identity.get("reason"),
                })
                continue

            if not queue_key or queue_attempt <= 0:
                queue_identity = _persist_generation_identity(ep, item)
                if queue_identity.get("ok") is not True:
                    blocked.append({
                        "id": item.get("id"), "frame": item.get("frame"),
                        "reason": queue_identity.get("reason"),
                    })
                    continue
                repaired.append({
                    "id": item.get("id"), "frame": item.get("frame"),
                    "generation_key": queue_identity.get("generation_key"),
                    "attempt_index": queue_identity.get("attempt_index"),
                })
                queue_changed = True
                identity = queue_identity

            if isinstance(candidate, dict):
                ledger_identity = _reconcile_generation_identity_to_ledger(ep, item, identity)
                if ledger_identity.get("ok") is True and ledger_identity.get("ledger_updated"):
                    ledger_repaired.append({
                        "id": item.get("id"), "frame": item.get("frame"),
                        "generation_key": ledger_identity.get("generation_key"),
                        "attempt_index": ledger_identity.get("attempt_index"),
                    })
                elif ledger_identity.get("ok") is not True:
                    blocked.append({
                        "id": item.get("id"), "frame": item.get("frame"),
                        "reason": ledger_identity.get("reason"),
                    })
        if queue_changed:
            save_queue(ep, q)
    return {
        "repaired": repaired,
        "ledger_repaired": ledger_repaired,
        "blocked": blocked,
        "provider_dispatch_count": 0,
        "attempt_reservation_count": 0,
    }


def run_scheduler_async(ep:Path,max_workers:int,timeout:int,codex:str|None)->int:
    """V2.7 async scheduler entry.

    Execution is event-driven; ledger commits remain in scheduler context.
    Image execution no longer depends on the legacy image ThreadPool path.
    Rolling review remains isolated on its own review executor.
    """
    from platform.repository.mysql.mysql_connection_pool import set_process_role

    set_process_role("scheduler")
    try:
        with scheduler_core.queue_transaction(ep):
            return asyncio.run(_run_scheduler_async(ep,max_workers,timeout,codex))
    except QueueMutationBusy:
        return 21


async def _run_scheduler_async(ep:Path,max_workers:int,timeout:int,codex:str|None)->int:
    resource_library.ensure_fresh(ep)
    q=load_queue(ep)
    production_recovery.reconcile_locked(ep,q)
    scheduler_core.terminalize_superseded_history(ep,q)
    review_enabled=frame_scout.required(ep)
    review_cfg=storyos_config.get_path(_CONFIG,"production.review",{})
    review_changed=asyncio.Event();review_progress=asyncio.Event();review_stop=asyncio.Event()
    if review_enabled:
        review_queue.recover_claims(q)
        try:
            review_policy=model_policy.resolve("vision.fast",episode=ep)
            review_queue.reconcile_generated(q,episode=ep,policy=review_policy,
                sha256_file=frame_scout.sha256_file)
        except Exception:
            review_policy=None
    save_queue(ep,q)
    ready,_=ready_items(ep,q)
    if not ready:
        review_rows=q.get(review_queue.QUEUE_KEY) or []
        # A valid running review lease may belong to a different scheduler:
        # do not start a lane that could duplicate work or wait indefinitely.
        if review_enabled and any(row.get("status") == "running" for row in review_rows):
            return 24
        if review_enabled and review_queue.depth(q):
            review_stop.set();review_changed.set()
            await review_queue.run_lane(ep,changed=review_changed,progress=review_progress,
                stop=review_stop,codex=codex,timeout=timeout,
                max_inflight=int(review_cfg.get("max_inflight",2)))
        q = load_queue(ep)
        statuses={x.get("status") for x in q.get("items") or []}
        review_rows=q.get(review_queue.QUEUE_KEY) or []
        review_interrupted=any(
            row.get("review_kind") == review_queue.FINAL_SEMANTIC
            and row.get("status") == "blocked" for row in review_rows)
        review_active=any(row.get("status") in review_queue.ACTIVE for row in review_rows)
        if review_interrupted or "blocked" in statuses or "interrupted_unknown" in statuses:
            return 22
        if "running" in statuses or any(row.get("status") == "running" for row in review_rows):
            return 24
        if "queued" in statuses or review_active:
            return 20
        return 0

    runtime,_=runtime_router.detect()
    image_runtime,_=runtime_router.image_execution_runtime()
    if runtime in {"WORK","WEB"} and image_runtime != "CODEX":
        request=product_runtime_adapter.build_image_request(ep,runtime=runtime,queue_items=ready[:max_workers],source="image_scheduler")
        product_runtime_adapter.print_request(request)
        return product_runtime_adapter.HOST_ACTION_REQUIRED_RC
    max_workers=max(1,min(MAX_SUPPORTED_WORKERS,max_workers))
    initial_workers=max_workers
    review_task=(asyncio.create_task(review_queue.run_lane(
        ep,changed=review_changed,progress=review_progress,stop=review_stop,codex=codex,
        timeout=timeout,max_inflight=int(review_cfg.get("max_inflight",2))))
        if review_enabled else None)

    # STORY_OS_EP002_G2_REPAIR_CONCURRENCY (image lane only):
    # Repair items are independent, already-authorized one-shot content repairs.
    # They share the same first-completed lane as original items, bounded by
    # MAX_SUPPORTED_WORKERS (max_inflight_images).  Protections of the old
    # serial path are kept: a single ledger writer (event loop under the queue
    # OS lock), no duplicate dispatch (admission consumes queued rows), the raw
    # candidate budget claims in-flight inside each worker, per-item dependency
    # gating, and 3->2->1 degradation after technical failures in this run.
    has_block=False
    has_failure=False
    inflight=0
    worker_cap=initial_workers

    async def handler(item:dict)->dict:
        return await async_backend_worker(ep,item,timeout,codex)

    async def admit_more(limit:int)->list:
        """Admit up to `limit` newly ready items into this run.

        Called before the first wave and again after every completion so a
        freed worker slot is refilled first-completed instead of waiting for
        the rest of a wave. Returns only items admitted by this call.
        """
        nonlocal has_block,inflight
        if limit<=0:
            return []
        q=load_queue(ep)
        if review_enabled:
            paused,transition=review_queue.backpressure(
                q,high=int(review_cfg.get("queue_high_watermark",6)),
                low=int(review_cfg.get("queue_low_watermark",2)))
            if transition:
                event="GENERATION_REFILL_PAUSED" if transition=="PAUSED" else "GENERATION_REFILL_RESUMED"
                runtime_observability.safe_record_runtime_event(ep,event,
                    review_queue_depth=review_queue.depth(q),
                    high_watermark=int(review_cfg.get("queue_high_watermark",6)),
                    low_watermark=int(review_cfg.get("queue_low_watermark",2)),
                    oldest_review_wait_ms=review_queue.oldest_wait_ms(q),source="image_scheduler")
                save_queue(ep,q)
            while paused:
                review_progress.clear()
                await review_progress.wait()
                q=load_queue(ep)
                paused,transition=review_queue.backpressure(
                    q,high=int(review_cfg.get("queue_high_watermark",6)),
                    low=int(review_cfg.get("queue_low_watermark",2)))
                if transition:
                    runtime_observability.safe_record_runtime_event(ep,"GENERATION_REFILL_RESUMED",
                        review_queue_depth=review_queue.depth(q),
                        high_watermark=int(review_cfg.get("queue_high_watermark",6)),
                        low_watermark=int(review_cfg.get("queue_low_watermark",2)),
                        oldest_review_wait_ms=review_queue.oldest_wait_ms(q),source="image_scheduler")
                save_queue(ep,q)
        ready,_=ready_items(ep,q)
        admitted=[]
        budget = raw_candidate_budget.summary(ep, pending=len(ready))
        available = max(0, int(budget.get("available") or 0))
        if available <= 0:
            return []
        limit = min(limit, available)
        busy_frames={int(x["frame"]) for x in q.get("items") or [] if x.get("status")=="running"}
        for item in ready:
            if len(admitted)>=limit:
                break
            if int(item["frame"]) in busy_frames:
                continue
            row=next((x for x in q.get("items") or [] if x["id"]==item["id"]),None)
            if row is None or row.get("status")!="queued":
                continue
            production_recovery.prepare_execution(ep,row)
            save_queue(ep,q)
            ok,msg=ledger_begin(ep,row)
            if not ok:
                has_block=True
                row["status"]="blocked"
                row["last_error"]=msg[-1000:]
                production_recovery.mark_terminal(ep,row,"BEGIN_REJECTED",reason=row["last_error"])
                save_queue(ep,q)
                continue
            row["status"]="running"
            row["attempts"]=int(row.get("attempts") or 0)+1
            row["started_at"]=now()
            row["review_queue_depth_at_dispatch"]=review_queue.depth(q)
            _telemetry_image(ep,row,"WORKER_ADMITTED",queue_depth=max(0,len(ready)-len(admitted)-1),
                             wait_ms=_observed_ms(row.get("queued_at"),row.get("started_at")),status="committed",
                             review_queue_depth=review_queue.depth(q))
            runtime_observability.safe_record_runtime_event(ep,"GENERATION_WORK_DISPATCHED",
                logical_asset_key=logical_asset_identity.frame_asset_key(ep,row["frame"]),
                generation_key=production_recovery.generation_key_for_item(ep,row),
                queue_item_id=row.get("id"),
                review_queue_depth_at_dispatch=review_queue.depth(q),source="image_scheduler")
            production_recovery.mark_worker_pending(ep,row)
            inflight+=1
            admitted.append(row)
            busy_frames.add(int(row["frame"]))
            q.setdefault("waves",[]).append({
                "event":1,"mode":"continuous_first_completed","at":now(),
                "frame":int(row["frame"]),"status":"dispatched",
                "inflight_after":inflight,"next_parallel":worker_cap,
                "item_id":row["id"],
            })
            save_queue(ep,q)
        return admitted

    async def consume(event)->str:
        """Consume one TaskEvent; return the terminal queue status."""
        nonlocal has_block,has_failure
        image_event=runtime_event_collector.collect(event)
        q=load_queue(ep)
        item=next((x for x in q.get("items") or [] if x["id"]==image_event.item_id),None)
        if not item:
            return ""
        observed_at=now()
        observed_ms=_observed_ms(item.get("started_at"),observed_at)
        observed_result=image_event.payload.get("result") or image_event.payload
        observed_payload=observed_result.get("payload") if isinstance(observed_result,dict) else None
        obs_item={**item}
        if isinstance(observed_payload,dict):
            obs_item["provider"]=observed_payload.get("backend")
            obs_item["runner"]=(observed_result.get("worker_pool") or {}).get("mode")
            receipt=observed_payload.get("provider_receipt") or {}
            obs_item["provider_receipt"]=receipt.get("path") if isinstance(receipt,dict) else None
        _telemetry_image(ep,obs_item,"WORKER_RESULT_RECEIVED",duration_ms=observed_ms,status=image_event.event)
        _telemetry_image(ep,obs_item,"IMAGE_GENERATION_OBSERVED",duration_ms=observed_ms,
                         wait_ms=_observed_ms(item.get("queued_at"),item.get("started_at")),status=image_event.event)
        if image_event.event=="IMAGE_SUCCESS":
            result=image_event.payload.get("result") or image_event.payload
            msg=str(result.get("stdout") or result.get("error") or "")
            backend_ok=bool(
                result.get("returncode")==0
                and result.get("output")
                and Path(result["output"]).is_file()
            )
            ok=False
            triage_blocked=False
            triage_failure_code=None
            if backend_ok:
                triage=local_visual_triage.inspect_candidate(ep,item,Path(result["output"]))
                item["local_visual_triage"]=local_visual_triage.queue_summary(triage)
                if triage.get("block_commit"):
                    triage_blocked=True
                    triage_failure_code=str(triage.get("failure_code") or "NORMALIZE_TECHNICAL_FAILURE")
                    msg="LOCAL_VISUAL_TRIAGE_HARD_FAIL: "+",".join(triage.get("issue_codes") or [triage_failure_code])
                    ledger_tech_fail(ep,item,triage_failure_code,msg)
                else:
                    production_recovery.mark_terminal(ep,item,"SUCCESS_PREPARED")
                    ok,msg=ledger_success(ep,item,result)
            if ok:
                identity=_persist_generation_identity(ep,item,result)
                if identity.get("ok") is not True:
                    ok=False
                    msg="GENERATION_IDENTITY_PERSIST_FAILED:"+str(identity.get("reason") or "unknown")
                else:
                    item["status"]="generated"
                    item["output_path"]=repo_rel(Path(result["output"]))
                    if result.get("log"):
                        item["log_path"]=repo_rel(Path(result["log"]))
                    item["completed_at"]=now()
                    item["last_error"]=None
                    item.pop("technical_failure_code",None)
                    item.pop("external_block",None)
                    item.pop("retry_exhausted",None)
                    item["prompt_package"]=result.get("prompt_package")
                    production_recovery.mark_terminal(ep,item,"COMMITTED")
                    episode_performance.safe_record_queue_image_attempt(ep,item,status="generated")
                    _telemetry_image(ep,obs_item,"IMAGE_GENERATION_SUCCEEDED",duration_ms=observed_ms,status="generated")
                    _telemetry_image(ep,obs_item,"ARTIFACT_COMMITTED",duration_ms=_observed_ms(observed_at,now()),status="committed")
                    if item.get("scope")=="repair":
                        _telemetry_image(ep,obs_item,"REPAIR_FINISHED",duration_ms=observed_ms,status="generated")
                        _telemetry_image(ep,obs_item,"REPAIR_GENERATION_FINISHED",duration_ms=observed_ms,status="generated")
                    if review_enabled:
                        queued=review_queue.enqueue_generated(q,episode=ep,source_item=item,
                            artifact=Path(result["output"]),artifact_path=item["output_path"])
                        if queued.get("status")=="ENQUEUED":
                            review_changed.set()
            else:
                if not msg:
                    msg="image backend failed without terminal output"
                has_failure=True
                code=triage_failure_code if triage_blocked else ("CANDIDATE_COMMIT_FAILED" if backend_ok else classify_error(msg))
                code=_fence_native_rate_limit_unknown(ep,item,code)
                if not backend_ok: ledger_tech_fail(ep,item,code,msg)
                item["status"]=_terminal_technical_status(ep,item,code)
                item["technical_failure_code"]=code
                item.setdefault("technical_failures",[]).append({"at":now(),"attempt":int(item.get("attempts") or 0),"code":code})
                has_block=has_block or item["status"]=="blocked"
                if result.get("output"): item["candidate_output_path"]=str(result["output"])
                item["completed_at"]=now()
                item["last_error"]=runtime_portability.sanitize_diagnostic_text(str(msg)[-1600:])
                production_recovery.mark_terminal(ep,item,"BLOCKED" if item["status"]=="blocked" else "TECH_FAILED", code=code)
                episode_performance.safe_record_queue_image_attempt(
                    ep,item,status=item["status"],error_code=code)
                _telemetry_image(ep,obs_item,"IMAGE_GENERATION_FAILED",duration_ms=observed_ms,status=item["status"],failure_class=code)
                if item.get("scope")=="repair":
                    _telemetry_image(ep,obs_item,"REPAIR_FINISHED",duration_ms=observed_ms,status=item["status"],failure_class=code)
        elif image_event.event=="IMAGE_FAILED":
            has_failure=True
            msg=str(image_event.payload.get("error") or "async worker failed")
            code=classify_error(msg)
            code=_fence_native_rate_limit_unknown(ep,item,code)
            ledger_tech_fail(ep,item,code,msg)
            item["status"]=_terminal_technical_status(ep,item,code)
            item["technical_failure_code"]=code
            item.setdefault("technical_failures",[]).append({"at":now(),"attempt":int(item.get("attempts") or 0),"code":code})
            has_block=has_block or item["status"]=="blocked"
            item["completed_at"]=now()
            item["last_error"]=runtime_portability.sanitize_diagnostic_text(msg[-1600:])
            production_recovery.mark_terminal(ep,item,"BLOCKED" if item["status"]=="blocked" else "TECH_FAILED", code=code)
            episode_performance.safe_record_queue_image_attempt(
                ep,item,status=item["status"],error_code=code)
            _telemetry_image(ep,obs_item,"IMAGE_GENERATION_FAILED",duration_ms=observed_ms,status=item["status"],failure_class=code)
            if item.get("scope")=="repair":
                _telemetry_image(ep,obs_item,"REPAIR_FINISHED",duration_ms=observed_ms,status=item["status"],failure_class=code)
        q.setdefault("runtime_events",[]).append({"event":image_event.event,"task_id":image_event.item_id,"payload":runtime_event_collector.json_safe(image_event.payload),"at":now()})
        save_queue(ep,q)
        return str(item.get("status") or "")

    async def completed(event,status,active,cap):
        nonlocal inflight,worker_cap
        inflight,worker_cap=active,cap
        q=load_queue(ep)
        row=next((x for x in q.get("items") or [] if x["id"]==event.task_id),None)
        q.setdefault("waves",[]).append({
            "event":2,"mode":"continuous_first_completed","at":now(),
            "frame":int(row["frame"]) if row else None,
            "status":status or "unknown",
            "inflight_after":inflight,"next_parallel":worker_cap,
            "item_id":event.task_id,
        })
        save_queue(ep,q)

    await scheduler_core.run_execution_loop(
        [],handler,consume,workers=max_workers,admit=admit_more,completed=completed)

    if review_task:
        review_stop.set();review_changed.set()
        await review_task

    reconcile_generated_identities(ep)
    final_q=load_queue(ep)
    rc=_scheduler_terminal_rc(final_q,has_block=has_block,has_failure=has_failure,ep=ep)
    try:
        import workflow_observability
        workflow_observability.collect(ep,write=True)
    except Exception:
        pass
    return rc


def _scheduler_terminal_rc(q:dict,*,has_block:bool,has_failure:bool,ep:Path|None=None)->int:
    final_statuses={str(x.get("status") or "") for x in q.get("items") or []}
    review_rows=q.get(review_queue.QUEUE_KEY) or []
    # Image generation can finish while Final Semantic is quarantined or
    # another worker owns its review lease. A successful image run must not
    # report the whole scheduler as successful until the Review lane closes.
    if any(row.get("review_kind")==review_queue.FINAL_SEMANTIC
           and row.get("status")=="blocked" for row in review_rows):
        return 22
    if any(row.get("status")=="running" for row in review_rows):
        return 24
    if any(row.get("status")=="queued" for row in review_rows):
        return 20
    if has_block and ep is not None and not ready_items(ep,q)[0]:
        return 22
    if "tech_failed" in final_statuses:
        return 21
    external=[x for x in q.get("items") or [] if x.get("status")=="external_blocked"]
    # A provider/model is exhausted, but the system-default availability chain
    # still has another model. Keep the resident Driver in a retryable technical
    # state so the next cycle can apply the failover instead of exiting rc=24.
    if external and any(availability_fallback_model(x, episode=ep) for x in external):
        return 21
    if external:
        return 24
    return 21 if has_failure else 0


def run_scheduler_legacy_removed_path(ep:Path,max_workers:int,timeout:int,codex:str|None)->int:
    """Legacy image execution path removed in V2.7.

    Production execution must use run_scheduler_async(). This guard remains
    only to provide a clear failure for stale callers.
    """
    raise RuntimeError("LEGACY_IMAGE_SCHEDULER_REMOVED_USE_ASYNC_RUNTIME")


def _technical_retry_code(item:dict)->str:
    error=str(item.get("last_error") or "")
    # W-107: old queue rows may already have collapsed a local Windows staging
    # ACL failure into PERMISSION_403. Reclassify that narrow signature from the
    # preserved error text so recovery can open a new bounded technical epoch.
    inferred=image_model_policy.classify_backend_error(error,source="image_backend")
    code=str(item.get("technical_failure_code") or "").strip().upper()
    if inferred and (inferred==image_model_policy.LOCAL_WORKSPACE_PERMISSION
                     or code in {"", "IMAGE_BACKEND_ERROR"}):
        return inferred
    return code or inferred or classify_error(error)


def _retry_epoch_attempts(item:dict)->int:
    return max(0,int(item.get("attempts") or 0)-int(item.get("technical_retry_epoch_start_attempt") or 0))


def _shared_generation_attempt_state(ep:Path,item:dict)->dict:
    """Read the only authoritative real-image budget for this logical asset."""
    key=logical_asset_identity.frame_asset_key(ep,int(item.get("frame") or 0))
    state=generation_attempt_authority.load_asset_state(ep,key)
    return {
        "logical_asset_key":key,
        "attempts_consumed":int(state.get("attempts_consumed") or 0),
        "remaining_attempts":int(state.get("remaining_attempts") or 0),
        "active_attempt_index":state.get("active_attempt_index"),
    }


def _technical_retry_budget(ep:Path,item:dict,code:str)->tuple[bool,dict,str]:
    """Technical retry and content repair share the same global max-2 budget."""
    if str(code or "").upper() not in RETRYABLE_TECH_CODES:
        return False,{},"non_retryable_technical_failure"
    try:
        state=_shared_generation_attempt_state(ep,item)
    except Exception as exc:
        return False,{},"generation_attempt_authority_unavailable"
    if state.get("active_attempt_index") is not None:
        return False,state,"generation_attempt_already_active"
    if int(state.get("remaining_attempts") or 0) <= 0:
        return False,state,"shared_generation_attempt_budget_exhausted"
    # A terminal OUTCOME_UNKNOWN is not evidence that the previous provider
    # call failed. The shared Attempt-2 slot stays protected until a durable
    # execution/receipt reconciliation settles the previous invocation.
    consumed=int(state.get("attempts_consumed") or 0)
    if consumed:
        try:
            previous=generation_attempt_authority.load_attempt(
                ep,str(state["logical_asset_key"]),consumed)
        except Exception:
            return False,state,"previous_generation_attempt_unavailable"
        if not previous:
            return False,state,"previous_generation_attempt_missing"
        previous_status=str(previous.get("status") or "")
        if previous_status != "FAILED_AFTER_DISPATCH":
            return False,state,(
                "previous_generation_attempt_unverified"
                if previous_status in {"OUTCOME_UNKNOWN","DISPATCH_COMMITTED","RESERVED"}
                else "previous_generation_attempt_reconciliation_required"
            )
    return True,state,"shared_generation_attempt_budget_available"


def availability_fallback_model(item:dict,code:str|None=None,*,episode:Path|None=None)->str|None:
    code=str(code or _technical_retry_code(item)).strip().upper()
    if code not in {image_model_policy.PROVIDER_CAPACITY,image_model_policy.MODEL_UNAVAILABLE}:
        return None
    return image_model_policy.next_fallback_model(
        str(item.get("model") or ""),strict_model=bool(item.get("strict_model")),episode=episode)


def _apply_model_failover(item:dict,code:str,*,episode:Path|None=None)->str|None:
    """Advance one model after this model's bounded availability retries exhaust."""
    if code not in {image_model_policy.PROVIDER_CAPACITY,image_model_policy.MODEL_UNAVAILABLE}:
        return None
    if bool(item.get("strict_model")):
        return None
    current=str(item.get("model") or "").strip()
    target=availability_fallback_model(item,code,episode=episode)
    if not target:
        return None
    stamp=now()
    item.setdefault("model_failovers",[]).append({
        "at":stamp,"from":current,"to":target,"trigger_code":code,
        "attempts_before_failover":int(item.get("attempts") or 0),
    })
    item["model"]=target
    item["technical_retry_epoch_start_attempt"]=int(item.get("attempts") or 0)
    item.pop("external_block",None)
    item["last_error"]=None
    item["retry_pending"]=False
    item.pop("execution",None)
    item.pop("started_at",None)
    item.pop("completed_at",None)
    return target


def resume_authorized_budget(ep:Path,frames:list[int]|None=None)->dict:
    """Requeue only budget-blocked items whose current bounded budget now fits.

    Capacity may come from an explicit user authorization or from a deterministic
    semantic/policy budget epoch already encoded by raw_candidate_budget. This
    step never raises a limit and never guesses approval.
    """
    ep=Path(ep).resolve();wanted={int(x) for x in (frames or [])}
    with queue_transaction(ep):
        q=load_queue(ep)
        blocked=[item for item in q.get("items") or []
                 if item.get("status")=="blocked"
                 and str(item.get("technical_failure_code") or "").upper() in raw_candidate_budget.BUDGET_BLOCK_CODES
                 and (not wanted or int(item.get("frame") or 0) in wanted)]
        context=raw_candidate_budget.blocked_queue_context(ep,blocked)
        allowed=set(int(x) for x in context.get("resumable_frames") or [])
        requeued=[]
        for item in blocked:
            frame=int(item.get("frame") or 0)
            if frame not in allowed:
                continue
            item.setdefault("budget_recovery",[]).append({"at":now(),"reason":"bounded_budget_capacity_available"})
            item["status"]="queued"
            item["last_error"]=None
            item.pop("technical_failure_code",None)
            item.pop("external_block",None)
            item.pop("retry_exhausted",None)
            item.pop("execution",None)
            item.pop("started_at",None)
            item.pop("completed_at",None)
            requeued.append(frame)
        save_queue(ep,q)
        return {"status":"PASS" if requeued else "BLOCKED","requeued_frames":sorted(set(requeued)),"budget":context}


def retry_tech(ep:Path,frame:int|None=None,*,reset_exhausted:bool=False,sleep_fn=time.sleep)->dict:
    """Requeue one technical retry only when the shared max-2 budget has room.

    reset_exhausted remains a CLI-compatibility argument only. It cannot create
    a new real-generation budget epoch or bypass Generation Attempt Authority.
    A technical retry competes with content repair for the same final Attempt 2
    slot.
    """
    ep=Path(ep).resolve()

    # Normalize eligible blocked/external rows into the retryable technical lane.
    with queue_transaction(ep):
        q=load_queue(ep)
        for item in q.get("items") or []:
            if frame is not None and int(item.get("frame") or -1)!=int(frame):
                continue
            if item.get("status") not in {"blocked","external_blocked","tech_failed"}:
                continue
            code=_technical_retry_code(item)
            allowed,state,reason=_technical_retry_budget(ep,item,code)
            if not allowed:
                if code in RETRYABLE_TECH_CODES:
                    item["status"]="external_blocked"
                    item["external_block"]={
                        "at":now(),"reason":reason,"code":code,
                        "attempts_consumed":state.get("attempts_consumed"),
                        "remaining_attempts":state.get("remaining_attempts"),
                        "max_real_generation_attempts":
                            generation_attempt_authority.MAX_REAL_IMAGE_GENERATION_ATTEMPTS_PER_ASSET,
                    }
                continue
            # Availability failover may change transport/model only before the
            # next shared Attempt is reserved.
            if item.get("status")=="external_blocked":
                _apply_model_failover(item,code,episode=ep)
            item["status"]="tech_failed"
            item.pop("external_block",None)
        save_queue(ep,q)

    # Backoff is operational pacing only; it never grants extra image budget.
    preview=load_queue(ep);delays=[]
    for item in preview.get("items") or []:
        if item.get("status")!="tech_failed" or (frame is not None and int(item.get("frame") or -1)!=int(frame)):
            continue
        code=_technical_retry_code(item)
        allowed,_state,_reason=_technical_retry_budget(ep,item,code)
        if allowed and _retry_epoch_attempts(item)>0 and TECH_RETRY_BACKOFF:
            delays.append(TECH_RETRY_BACKOFF[min(
                _retry_epoch_attempts(item)-1,len(TECH_RETRY_BACKOFF)-1)])
    delay=max(delays or [0])
    if delay>0:
        sleep_fn(delay)

    with queue_transaction(ep):
        q=load_queue(ep);count=0;exhausted=[];non_retryable=[]
        for item in q.get("items") or []:
            if item.get("status")!="tech_failed" or (frame is not None and int(item.get("frame") or -1)!=int(frame)):
                continue
            code=_technical_retry_code(item)
            allowed,state,reason=_technical_retry_budget(ep,item,code)
            if code not in RETRYABLE_TECH_CODES:
                item["status"]="external_blocked"
                item["external_block"]={"at":now(),"reason":"non_retryable_technical_failure","code":code}
                non_retryable.append(int(item.get("frame") or 0));continue
            if not allowed:
                item["status"]="external_blocked"
                item["external_block"]={
                    "at":now(),"reason":reason,"code":code,
                    "attempts_consumed":state.get("attempts_consumed"),
                    "remaining_attempts":state.get("remaining_attempts"),
                    "max_real_generation_attempts":
                        generation_attempt_authority.MAX_REAL_IMAGE_GENERATION_ATTEMPTS_PER_ASSET,
                }
                exhausted.append(int(item.get("frame") or 0));continue
            item["status"]="queued"
            item["last_error"]=None
            item["retry_pending"]=False
            item["retry_backoff_seconds"]=delay
            item["generation_attempt_reason"]="TECHNICAL_RETRY"
            item["technical_retry_source_code"]=code
            item["technical_retry_authorized_at"]=now()
            item["technical_retry_shared_budget"]={
                "attempts_consumed":state.get("attempts_consumed"),
                "remaining_before_retry":state.get("remaining_attempts"),
                "max_real_generation_attempts":
                    generation_attempt_authority.MAX_REAL_IMAGE_GENERATION_ATTEMPTS_PER_ASSET,
            }
            item.pop("execution",None)
            item.pop("started_at",None)
            item.pop("completed_at",None)
            count+=1
        save_queue(ep,q)
        return {
            "requeued":count,"frame":frame,"backoff_seconds":delay,
            "exhausted_frames":sorted(set(exhausted)),
            "non_retryable_frames":sorted(set(non_retryable)),
            "budget_authority":"generation_attempt_authority",
            "max_real_generation_attempts":
                generation_attempt_authority.MAX_REAL_IMAGE_GENERATION_ATTEMPTS_PER_ASSET,
        }


def self_test()->None:
    assert MAX_SUPPORTED_WORKERS == int(storyos_config.get_path(_CONFIG, "production.max_inflight_images"))
    assert classify_error("429 Too Many Requests")=="RATE_LIMIT_429"
    assert classify_error("worker timeout")=="TIMEOUT"
    assert classify_error("unknown model")=="MODEL_UNAVAILABLE"
    assert classify_error("Selected model is at capacity. Please try a different model.")=="PROVIDER_CAPACITY"
    assert classify_error("image generation failed: network error: error sending request")=="NETWORK_ERROR"
    assert TECH_RETRY_MAX == 1 and TECH_RETRY_BACKOFF == ()
    assert classify_error("ASPECT_RATIO_MISMATCH: inspect Generation Request")=="ASPECT_RATIO_MISMATCH"
    assert image_worker_pool.CODEX_SESSION_REUSE is False
    assert rolling_frame_review.VALID == {"PASS_PREVIEW","REPAIR_NOW","UNCERTAIN"}
    assert runtime_router.image_execution_runtime()[0] in {"CODEX","PRODUCT_RUNTIME","AUTO"}
    src=Path(__file__).read_text(encoding="utf-8-sig")
    assert "LEGACY_IMAGE_SCHEDULER_REMOVED_USE_ASYNC_RUNTIME" in src
    assert "story-os-image" not in src[src.index("def run_scheduler_async"):src.index("def run_scheduler", src.index("def run_scheduler_async"))]
    body=src[src.index("def directive_dependency"):src.index("def narrative_escalation_from")]
    assert "generation_depends_on" in body and "escalation_from" not in body
    print("IMAGE SCHEDULER V2.1 PHASE6 + R2 DEPENDENCY SELF-TEST PASS")


def main()->int:
    from platform.repository.mysql.mysql_connection_pool import set_process_role

    set_process_role("scheduler")
    ap=argparse.ArgumentParser(description=__doc__);sub=ap.add_subparsers(dest="cmd",required=True)
    p=sub.add_parser("init");p.add_argument("episode_dir");p.add_argument("--force",action="store_true")
    p=sub.add_parser("add");p.add_argument("episode_dir");p.add_argument("--frame",type=int,required=True);p.add_argument("--kind",choices=["original","repair","baseline_candidate"],default="original");p.add_argument("--scope",choices=["visual_lock","batch","repair","baseline_candidate"],default="batch");p.add_argument("--prompt-file",required=True);p.add_argument("--reference",action="append",default=[]);p.add_argument("--capture-id");p.add_argument("--model");p.add_argument("--quality",choices=["high"]);p.add_argument("--depends-on",action="append",default=[]);p.add_argument("--replace",action="store_true")
    p=sub.add_parser("import-visual-lock");p.add_argument("episode_dir");p.add_argument("--prompt-dir",required=True)
    p=sub.add_parser("import-batch");p.add_argument("episode_dir");p.add_argument("--prompt-dir",required=True)
    p=sub.add_parser("plan");p.add_argument("episode_dir")
    p=sub.add_parser("run");p.add_argument("episode_dir");p.add_argument("--max-workers",type=int,default=MAX_SUPPORTED_WORKERS);p.add_argument("--timeout",type=int,default=None);p.add_argument("--codex")
    p=sub.add_parser("retry-tech");p.add_argument("episode_dir");p.add_argument("--frame",type=int);p.add_argument("--reset-exhausted",action="store_true",help="start a new bounded technical-retry epoch after the external provider has recovered")
    p=sub.add_parser("reconcile");p.add_argument("episode_dir")
    p=sub.add_parser("show");p.add_argument("episode_dir")
    sub.add_parser("self-test")
    a=ap.parse_args()
    if a.cmd=="self-test":self_test();return 0
    ep=resolve_ep(a.episode_dir)
    try:
        if a.cmd=="init":print(json.dumps(init_queue(ep,a.force),ensure_ascii=False,indent=2));return 0
        if a.cmd=="add":
            refs=[parse_ref(x) for x in a.reference];deps=[]
            for raw in a.depends_on:
                deps.extend(int(x) for x in str(raw).split(",") if x.strip())
            prompt=repo_file(a.prompt_file)
            policy=image_model_policy.for_episode(ep)
            row=add_item(ep,frame=a.frame,kind=a.kind,prompt_file=prompt,scope=a.scope,references=refs,capture_id=a.capture_id or f"scheduler-{a.frame:02d}",model=a.model or policy["model"],quality=a.quality or policy["quality"],strict_model=True if a.model else bool(policy.get("strict_model")),depends_on=deps,replace=a.replace)
            print(json.dumps(row,ensure_ascii=False,indent=2));return 0
        if a.cmd=="reconcile":
            with queue_transaction(ep):
                q=load_queue(ep)
                report=production_recovery.reconcile_locked(ep,q)
                save_queue(ep,q)
            print(json.dumps(report,ensure_ascii=False,indent=2));return 0
        if a.cmd=="import-visual-lock":print(json.dumps(import_visual_lock(ep,Path(a.prompt_dir).resolve()),ensure_ascii=False,indent=2));return 0
        if a.cmd=="import-batch":print(json.dumps(import_batch(ep,Path(a.prompt_dir).resolve()),ensure_ascii=False,indent=2));return 0
        if a.cmd=="plan":
            q=load_queue(ep)
            print(json.dumps(plan_snapshot(ep,q),ensure_ascii=False,indent=2));return 0
        if a.cmd=="run":
            run_timeout=runtime_timeout_policy.resolve("image_lane_run", a.timeout)
            if batch_scheduler.should_use(ep):
                return batch_scheduler.run(ep,a.max_workers,run_timeout,a.codex)
            return run_scheduler_async(ep,a.max_workers,run_timeout,a.codex)
        if a.cmd=="retry-tech":print(json.dumps(retry_tech(ep,a.frame,reset_exhausted=a.reset_exhausted),ensure_ascii=False,indent=2));return 0
        print(json.dumps(load_queue(ep),ensure_ascii=False,indent=2));return 0
    except (OSError,ValueError,RuntimeError,subprocess.TimeoutExpired) as exc:
        print("IMAGE SCHEDULER ERROR:",exc);return 3


if __name__=="__main__":raise SystemExit(main())

# STORY_OS_V211_RUNTIME_CLOSURE_R31

# STORY_OS_V2_5_1_1_FORCED_CANDIDATE_GATE
