#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import argparse, concurrent.futures as cf, hashlib, json, subprocess, sys, time, uuid
from pathlib import Path

import quota_observability
import execution_capsule
import character_contract
import character_visual_contract
import capture_event_contract
import voice_contract
import wardrobe_contract
import episode_state_persistence
import review_record_persistence
import visual_profile_review_persistence
import production_ledger
import provisional_release
import preproduction_handoff
import resource_library
import intro_policy
import multi_level_cache
import runtime_execution
import runtime_request
import story_narrative_form
import scoped_codex_worker
import runtime_mode_router
import directing_quality
import world_identity_contract  # STORY_OS_V221_WORLD_IDENTITY
import character_appearance_anchor  # STORY_OS_V221_CHARACTER_CONTINUITY
import workflow_performance as perf
import workflow_step_protocol as proto
import speculative_production  # STORY_OS_V211_PERF_RECOVERY
import performance_guard_v211
import runtime_trace
import runtime_router
import product_runtime_adapter
import next_action
import episode_performance
import runtime_observability
import runtime_timeout_policy
import runtime_node_registry
import runtime_node_execution
import runtime_node_evidence
import storyos_config
import runtime_scheduler
import runtime_checkpoint
import runtime_command
import runtime_ownership
import validate_episode
import machine_gate
import evidence_gate

ROOT=Path(__file__).resolve().parents[2]
SYSTEM=Path(__file__).resolve().parent
DAG_FILE=ROOT/"runtimes/runtime-dag.json"
from story_os_contract import canonical_stages
STAGES=tuple(canonical_stages())

# STORY_OS_PHASE461_VISUAL_PROFILE_CLOSURE: returned when the pre-resume Visual Profile
# reconciliation refuses to continue (a committed production asset exists on a profile that
# nobody has confirmed).
RECONCILE_BLOCKED_RC=9

# STORY_OS_V211_INCREMENTAL_PLAN_REUSE: the incremental planner's real input surface,
# read off incremental_closure.plan(). The generic input_hash cannot be reused for this
# step: its evidence_paths is meta/runtime-checkpoint.json, which checkpoint() rewrites
# on every step of every pass. These are the files plan() actually inspects, including
# production-ledger.json because it moves with pixel assets and changes the frame plan.
INCREMENTAL_PLAN_STEP="INCREMENTAL_PLAN"
INCREMENTAL_PLAN_INPUTS=[
    "meta/episode-state.json","meta/story-gates.json","meta/story-semantic-review.json",
    "meta/visual-profile-review.json","meta/production-ledger.json",
    "meta/subtitle-layout-audit.json","meta/text-audit.json",
]



def _assert_preimage_storage_schema() -> None:
    """Gate hosted PREIMAGE derivation on exact V2 schema, never on a legacy alias.

    This is structure admission only, not Episode stage or review authority.
    """
    import storage_config
    if storage_config.episode_meta_store_config()["mode"] not in {"mysql", "dual"}:
        return
    import preimage_storage_preflight
    result = preimage_storage_preflight.inspect()
    if not result.get("schema_check_passed"):
        raise RuntimeError(
            f"PREIMAGE_V2_SCHEMA_BLOCKED:{result.get('status') or 'UNKNOWN'}")


def dispatch_critic_runnable(task_type, *, adapter, episode_dir, attempt,
                             legacy_target, route_decision=None,
                             production_enabled=None, adapter_kwargs=None):
    """Dispatch one existing Critic request through the DAG/Scheduler owner.

    This is an execution substep, not an Episode stage. The Scheduler is the
    only component that authorizes a production target; adapters receive that
    authorization and runners only consume the resulting target.
    """
    return runtime_scheduler.dispatch_critic_runnable(
        task_type, adapter=adapter, episode_dir=episode_dir, attempt=attempt,
        legacy_target=legacy_target, route_decision=route_decision,
        production_enabled=production_enabled, adapter_kwargs=adapter_kwargs,
    )


def dispatch_pending_critic(task_type, *, adapter, episode_dir, attempt,
                            adapter_kwargs=None):
    """Load the frozen Critic request, then enter the Scheduler-owned runnable."""
    ep = Path(episode_dir).resolve()
    if not hasattr(adapter, "REQUEST_KIND") or not callable(
            getattr(adapter, "legacy_execution_target", None)):
        raise ValueError("Critic adapter must expose REQUEST_KIND and legacy_execution_target")
    import product_review_adapter
    request_path = product_review_adapter.request_path(ep, adapter.REQUEST_KIND, attempt=attempt)
    request = product_review_adapter._read_json(request_path)
    if request.get("status") != product_review_adapter.AWAITING:
        return {"status": "BLOCKED", "failure_class": "CRITIC_REQUEST_NOT_AWAITING",
                "request_id": request.get("request_id"), "adapter_called": False}
    return dispatch_critic_runnable(
        task_type, adapter=adapter, episode_dir=ep, attempt=attempt,
        legacy_target=adapter.legacy_execution_target(ep),
        route_decision=request.get("capability_route_decision"),
        adapter_kwargs=adapter_kwargs,
    )


def _story_review_authority_sha(ep):
    return review_record_persistence.authority_sha256(
        Path(ep).resolve(),
        "STORY_SEMANTIC",
        legacy_path=Path(ep).resolve()/"meta/story-semantic-review.json",
    )


AUTHORITY_HASHERS={
    "meta/episode-state.json":episode_state_persistence.authority_sha256,
    character_contract.REL.as_posix():character_contract.authority_sha256,
    character_visual_contract.REL.as_posix():character_visual_contract.authority_sha256,
    capture_event_contract.REL.as_posix():capture_event_contract.authority_sha256,
    voice_contract.REL.as_posix():voice_contract.authority_sha256,
    wardrobe_contract.REL.as_posix():wardrobe_contract.authority_sha256,
    "meta/story-semantic-review.json":_story_review_authority_sha,
    "meta/visual-profile-review.json":visual_profile_review_persistence.authority_sha256,
    "meta/production-ledger.json":production_ledger.authority_sha256,
}


def _evidence_input_hash(ep,paths):
    files=[];authority=[]
    for rel in paths:
        rel=str(rel)
        hasher=AUTHORITY_HASHERS.get(rel)
        if hasher is None:
            files.append(rel)
            continue
        digest=hasher(Path(ep).resolve())
        authority.append(f"{rel}={digest or 'MISSING'}")
    file_hash=proto.evidence_hash(ep,files)
    return hashlib.sha256(
        ("|".join([file_hash,*authority])).encode("utf-8")
    ).hexdigest()


def _model_identity(ep, resolved_role):
    """Return the frozen Model Policy identity used by this step, if applicable."""
    role = str(resolved_role or "").strip()
    if not role:
        return {"model_policy_sha256": "", "resolved_role": "", "effective_model": "",
                "reasoning_effort": ""}
    try:
        import model_policy
        import model_policy_persistence
    except ModuleNotFoundError:
        # Keeps this branch usable while the policy module is introduced in its
        # own logical commit. New policy-aware results use a different hash shape.
        return {"model_policy_sha256": "", "resolved_role": role, "effective_model": "",
                "reasoning_effort": ""}
    bound = model_policy_persistence.load(Path(ep).resolve())
    policy_sha = str((bound or {}).get("policy_sha256") or "").lower()
    # Real production requests are frozen before dispatch. The unbound branch
    # supports planning/test fixtures and legacy Episodes; workers still refuse
    # to execute without an Episode binding.
    resolved = model_policy.resolve(role, episode=Path(ep).resolve()) if bound else model_policy.resolve(role)
    if not isinstance(resolved, dict):
        resolved = {}
    return {
        "model_policy_sha256": policy_sha or str(resolved.get("model_policy_sha256") or "").lower(),
        "resolved_role": str(resolved.get("resolved_role") or role),
        "effective_model": str(resolved.get("model") or resolved.get("effective_model") or ""),
        "reasoning_effort": str(resolved.get("reasoning_effort") or ""),
    }


def _step_input_hash(ep, paths, *, resolved_role=""):
    evidence_hash=_evidence_input_hash(ep,paths)
    request=runtime_request.authority_for_episode(ep) or {}
    request_hash=runtime_request.authority_sha256(request)
    identity = {
        "identity_schema_version": 2,
        "runtime_request_sha": request_hash,
        "evidence_sha": evidence_hash,
        **_model_identity(ep, resolved_role),
    }
    raw=json.dumps(identity,ensure_ascii=False,sort_keys=True,separators=(",",":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


MODEL_ROLE_BY_STEP = {
    "CREATIVE_STORY": "story.authoring",
    "PREIMAGE_COMPILE": "preimage.frame_contract",
    "VISUAL_LOCK": "vision.visual_lock",
    "PRODUCTION": "image.controller",
    "RELEASE": "release",
    "PROMPT_AUTHORING": "prompt.production",
}


def _freeze_model_policy_before_dispatch(ep):
    """Freeze and validate policy after Request binding, before DAG model work."""
    if not runtime_request.authority_for_episode(ep):
        return ["Runtime Request is not bound; Model Policy cannot be frozen before dispatch"]
    try:
        import model_policy
        model_policy.freeze_for_episode(ep)
        return model_policy.validate_bound_policy(ep)
    except Exception as exc:
        return [str(exc)]


def reconcile_visual_profile_closure(ep):
    """Phase 4.6.1: reconcile the Visual Profile closure before the DAG resumes.

    A promote hook only runs at a promotion, so a production asset committed while the profile
    was not yet LOCKED can leave LOCKED + committed asset + not FROZEN with no later trigger.
    This is the single runtime recovery point for that state. It only *consumes*
    visual_profile_closure.reconcile_episode: no registry, lifecycle or asset-commit rule is
    re-implemented here, and nothing is confirmed.

    Returns None when the runtime may continue (frozen / noop / skipped), or a list of blocking
    lines when it may not. A refused recovery (VISUAL_PROFILE_NOT_LOCKED) must not be turned
    into a pass, so this returns a block rather than a diagnostic.
    """
    try:
        import visual_profile_closure as closure
        report=closure.reconcile_episode(ep)
    except Exception as exc:
        return ["visual profile closure reconcile unavailable: "+type(exc).__name__+": "+str(exc)]
    status=str(report.get("status") or "")
    if status!=closure.RESULT_FAIL:
        return None
    return [
        "visual profile closure reconcile refused: "+str(report.get("code")),
        "lifecycle_state="+str(report.get("lifecycle_state")),
        str(report.get("detail") or ""),
    ]

def run(cmd):
    return runtime_command.run_argv([str(x) for x in cmd],cwd=ROOT,capture=True)
def load_dag():
    d=json.loads(DAG_FILE.read_text(encoding="utf-8-sig"))
    if d.get("schema_version")!=1: raise ValueError("invalid runtime-dag schema")
    return d
def state(ep):
    return (episode_state_persistence.load(Path(ep).resolve()) or {}).get("current_state")
def stage_at_least(cur,target):
    return cur in STAGES and target in STAGES and STAGES.index(cur)>=STAGES.index(target)
def request_mode(ep):
    return runtime_execution.effective_mode(ep)
def validate_target(ep,target):
    ep=Path(ep).resolve()
    findings=validate_episode.validate_episode(ep,ROOT,False,target)
    failed=[str(x) for x in findings if getattr(x,"level",None)=="FAIL"]
    if failed: return False,"\n".join(failed)[-5000:]
    findings=machine_gate.validate(ep,target,metadata_only=False)
    failed=[str(x) for x in findings if getattr(x,"level",None)=="FAIL"]
    if failed: return False,"\n".join(failed)[-5000:]
    ok,messages=evidence_gate.run_gate(ep,target)
    if not ok: return False,"\n".join(str(x) for x in messages)[-5000:]
    return True,"PASS"

# STORY_OS_V262_DAG_STOP_TARGET: an explicit --until target lets a bounded pass end on a chosen
# stage instead of running the whole DAG. It is a caller-imposed stop, never a second stage
# authority: the stop only counts once the canonical state has advanced AND the same three gates
# that guard advancement accept that stage, so --until can never report "reached" for a stage the
# Episode has not actually validated. Default None means every existing caller is unaffected.
STOP_TARGET_REACHED="STOP_TARGET_REACHED"

def stop_target_reached(ep,target):
    """Return (reached, detail) for an --until stop target.

    The canonical state read is cheap and happens first, so the three gate subprocesses are
    spawned only once the Episode has actually arrived at the target.
    """
    cur=state(ep)
    if not stage_at_least(cur,target):
        return False,"current_state="+str(cur)
    ok,msg=validate_target(ep,target)
    if not ok:
        return False,"gate rejected "+target+": "+str(msg)[-800:]
    return True,"PASS"
def checkpoint(ep,step,status,elapsed,note,attempt=1,input_hash=None,output_hash=None,returncode=None):
    try:
        runtime_checkpoint.record_step(
            ep,step=step,status=status,attempt=attempt,finished_at=proto.now(),note=note,
            input_hash=input_hash,output_hash=output_hash,
            elapsed_seconds=elapsed,returncode=returncode)
    except FileNotFoundError:
        # Compatibility with the former subprocess path: runtime_checkpoint.py
        # returned non-zero when the file was absent, but DAG intentionally did
        # not treat that recovery-projection failure as stage authority.
        return None

def spec_rows():
    d=load_dag(); rows=[]
    for x in d["steps"]:
        rows.append(proto.StepSpec(
            step_id=x["id"],executor=x["executor"],depends_on=tuple(x.get("depends_on") or []),
            covers=tuple(x.get("covers") or []),target_state=x.get("target_state"),
            evidence_paths=tuple(x.get("evidence_paths") or []),expensive=bool(x.get("expensive")),
            model_role=x.get("model_role")))
    return rows


def normalize_node_contracts(nodes):
    """Validate scheduling-only nodes without reading or writing Episode state."""
    if isinstance(nodes, dict):
        nodes = nodes.get("nodes")
    if not isinstance(nodes, list):
        raise ValueError("node contract must contain a nodes list")
    result = []
    ids = set()
    for index, raw in enumerate(nodes):
        if not isinstance(raw, dict):
            raise ValueError(f"node at index {index} must be an object")
        node_id = str(raw.get("node_id") or "").strip()
        if not node_id or node_id in ids:
            raise ValueError(f"node_id must be unique and non-empty: {node_id!r}")
        depends_on = raw.get("depends_on") or []
        if not isinstance(depends_on, list) or any(not str(x).strip() for x in depends_on):
            raise ValueError(f"node {node_id} has invalid depends_on")
        item = dict(raw)
        item["node_id"] = node_id
        item["depends_on"] = [str(x) for x in depends_on]
        item["_order"] = index
        result.append(item)
        ids.add(node_id)
    unknown = sorted({dep for item in result for dep in item["depends_on"] if dep not in ids})
    if unknown:
        raise ValueError("unknown node dependencies: " + ", ".join(unknown))
    return result


def resolve_node_dependencies(nodes, *, completed=(), failed=()):
    """Return ready, waiting and downstream-blocked nodes for one scheduling pass.

    This is deliberately a pure function.  It neither executes a node nor records
    a runtime status, so it cannot become an Episode stage authority.
    """
    rows = normalize_node_contracts(nodes)
    completed = {str(value) for value in completed}
    failed = {str(value) for value in failed}
    known = {row["node_id"] for row in rows}
    unknown_outcomes = (completed | failed) - known
    if unknown_outcomes:
        raise ValueError("unknown completed/failed nodes: " + ", ".join(sorted(unknown_outcomes)))
    if completed & failed:
        raise ValueError("a node cannot be both completed and failed")

    blocked = set()
    changed = True
    while changed:
        changed = False
        for row in rows:
            node_id = row["node_id"]
            if node_id in completed or node_id in failed or node_id in blocked:
                continue
            if any(dep in failed or dep in blocked for dep in row["depends_on"]):
                blocked.add(node_id)
                changed = True

    ready = []
    waiting = []
    for row in rows:
        node_id = row["node_id"]
        if node_id in completed or node_id in failed or node_id in blocked:
            continue
        if set(row["depends_on"]).issubset(completed):
            ready.append(row)
        else:
            waiting.append(row)
    return {"ready": ready, "waiting": waiting, "blocked": [
        row for row in rows if row["node_id"] in blocked
    ]}

def production_scheduler_resources() -> dict:
    """Resolved capacity presented to the top-level production scheduler.

    Top-level Runtime steps stay serial unless their Node Contract explicitly
    declares ``parallel_safe``.  The snapshot therefore exposes real lane
    capacity without forcing unsafe composite steps to run concurrently.  Image
    concurrency remains delegated to image_scheduler and PREIMAGE concurrency to
    its task protocol, but the scheduler no longer plans against a fake global
    ``max_workers=1`` resource model.
    """
    config=storyos_config.load_config()
    authority=max(1,int(storyos_config.get_path(config,"runtime.workers.local_codex_preimage",4)))
    derived=max(1,int(storyos_config.get_path(config,"runtime.workers.derived",6)))
    image=max(1,int(storyos_config.get_path(config,"production.max_inflight_images",5)))
    max_workers=max(authority,derived,image,1)
    return {
        "max_workers":max_workers,
        "current_workers":0,
        "runtime_capacity":{
            "text":1,
            "review":1,
            "preimage":authority,
            "authority":authority,
            "derived":derived,
            "image":image,
        },
    }


def plan(ep):
    cur=state(ep); saved=proto.load_state(ep)
    out=[]
    for s in spec_rows():
        row={"step":s.step_id,"executor":s.executor,"depends_on":list(s.depends_on),"target_state":s.target_state,"covers":list(s.covers),"current_state":cur}
        if s.target_state and stage_at_least(cur,s.target_state):
            ok,_=validate_target(ep,s.target_state); row["action"]="REUSE" if ok else "VERIFY_OR_REPAIR"
        else:
            row["action"]="RUN"
        prev=(saved.get("steps") or {}).get(s.step_id)
        if prev: row["previous"]=prev
        out.append(row)
    return {"current_state":cur,"steps":out}


def incremental_runtime_strategy(incremental_plan, step_id, current_state):
    """Map the consumed incremental plan to the existing Runtime production step.

    The planner remains advisory: only the existing production step may run frame
    verification, and it does so through incremental_frame_review's canonical
    verifier. Transitional ledger states continue through the normal scheduler.
    """
    if not isinstance(incremental_plan, dict):
        return "RUN_WORKER"
    if step_id in {"CREATIVE_STORY", "VISUAL_LOCK"}:
        evidence_key = "story" if step_id == "CREATIVE_STORY" else "visual"
        evidence_state = _plan_evidence_state(incremental_plan, evidence_key)
        target_stage = "STORYBOARD_LOCKED" if evidence_key == "story" else "VISUAL_CALIBRATED"
        # These DAG nodes also author/finalize their respective domains. Only
        # narrow a reached-stage verifier failure to the existing critic path;
        # do not skip authoring/calibration just because a review receipt exists.
        if not stage_at_least(current_state, target_stage):
            return "RUN_WORKER"
        if evidence_state in {"DIRTY", "MISSING"}:
            return "VERIFY_STORY_EVIDENCE" if evidence_key == "story" else "VERIFY_VISUAL_EVIDENCE"
        return "RUN_WORKER"
    if step_id != "PRODUCTION":
        return "RUN_WORKER"
    if not stage_at_least(current_state, "PRODUCTION_PASSED"):
        return "RUN_WORKER"
    frame_plan = incremental_plan.get("frame_plan")
    if not isinstance(frame_plan, dict):
        return "RUN_WORKER"
    action = str(frame_plan.get("action") or "").upper()
    if action in {"NOOP", "NOT_REQUIRED"}:
        return "REUSE_FRAME_EVIDENCE"
    if action in {"PATCH", "FULL"}:
        return "VERIFY_INCREMENTALLY"
    return "RUN_WORKER"


def _recover_verified_story_without_model(ep, current_state):
    """Reconcile formal Story PASS only inside the authorized canonical Driver.

    0: official PASS was reused and canonical stage advanced.
    None: no official PASS yet; normal authoring may proceed.
    22: fail closed, NEVER dispatch another authoring model.
    """
    if current_state != "IDEA_LOCKED":
        return None, "NO_IDEA_LOCKED_RECOVERY_REQUIRED"
    report = character_contract.approved_story_rebind(ep, write=False)
    status = str(report.get("status") or "")
    if status == "NO_OFFICIAL_STORY_PASS":
        return None, status
    if status not in {"ALREADY_BOUND", "VERIFIED_REBIND_READY"}:
        return 22, "OFFICIAL_STORY_REUSE_BLOCKED:" + status
    if status == "VERIFIED_REBIND_READY":
        updated = character_contract.approved_story_rebind(ep, write=True)
        if updated.get("status") not in {"REBOUND_VERIFIED", "ALREADY_BOUND"}:
            return 22, "APPROVED_CHARACTER_BINDING_FAILED:" + str(updated.get("status"))
    # Only the existing Episode State transition is allowed to advance stage.
    # It verifies all three gates and persists MySQL state atomically.
    cp = run([sys.executable, SYSTEM / "episode_state.py", "transition",
              ep, "STORYBOARD_LOCKED", "--note",
              "verified official Story PASS; Character Contract CAS reconciled"])
    if cp.returncode != 0 or not stage_at_least(state(ep), "STORYBOARD_LOCKED"):
        return 22, "VERIFIED_STORY_STAGE_GATE_BLOCKED:" + str(cp.stdout)[-1000:]
    return 0, "VERIFIED_OFFICIAL_STORY_REUSED_NO_AUTHORING_MODEL"


def _plan_evidence_state(incremental_plan, key):
    if not isinstance(incremental_plan, dict):
        return ""
    value = incremental_plan.get(key)
    if isinstance(value, dict):
        value = value.get("state") or value.get("status") or value.get("action")
    return str(value or "").upper()


def _unsupported_missing_evidence(incremental_plan):
    """Fail closed when closure identifies missing authority with no narrow repair path."""
    if not isinstance(incremental_plan, dict):
        return "incremental plan unavailable"
    known = {"meta/story-semantic-review.json", "meta/visual-profile-review.json",
             "meta/production-ledger.json", "meta/subtitle-layout-audit.json"}
    missing = [str(item) for item in incremental_plan.get("missing") or []]
    unknown = sorted(set(missing) - known)
    if unknown:
        return "unsupported missing evidence: " + ", ".join(unknown)
    # Production Ledger absence cannot be reconstructed by a review-only step.
    if "meta/production-ledger.json" in missing:
        return "missing production ledger requires explicit production recovery"
    return None


def _run_targeted_review(ep, *, kind, attempt, codex, timeout, run_id, trace_id):
    """Resume an existing scoped request or dispatch only the requested critic."""
    import product_review_adapter

    if kind == "story-semantic":
        block=story_narrative_form.failed_locked_review_block(ep)
        if block:return 22,block
        import story_review_attempt_admission
        import story_review
        # DAG step counters include dozens of REUSED runs; they are NOT Critic
        # attempt indexes. The official review and scoped lifecycle own those.
        rows = {}
        candidates = {}
        for index in (1, 2):
            scoped = product_review_adapter.request_path(
                Path(ep).resolve(), kind, attempt=index)
            if product_review_adapter._request_exists(scoped):
                rows[index] = product_review_adapter._read_json(scoped)
                try:
                    candidate_path = (ROOT / str(rows[index].get("candidate_path") or "")).resolve()
                    candidates[index] = candidate_path.is_relative_to(ROOT) and candidate_path.is_file()
                except (TypeError, ValueError, OSError):
                    candidates[index] = False
        official = story_review.load_review(Path(ep).resolve())
        selection = story_review_attempt_admission.decide(
            dag_attempt=attempt, official_review=official if official else None,
            request_rows=rows, candidate_exists=candidates)
        if selection["status"]=="EXISTING_REVIEW_MUST_BE_REVALIDATED":
            errors=story_review.verify(Path(ep).resolve())
            if errors:
                return 22, "OFFICIAL_MIGRATED_STORY_REVIEW_UNVERIFIED:" + ";".join(str(e) for e in errors[:6])
            return 0, "VERIFIED_OFFICIAL_MIGRATED_STORY_REVIEW_REUSE_NO_MODEL_CALL"
        if selection["status"] not in {
                "DISPATCH_BOUNDED_STORY_CRITIC",
                "EXISTING_REVIEW_REQUIRES_FINALIZATION"}:
            return 22, "STORY_REVIEW_ATTEMPT_AUTHORITY_BLOCKED:" + selection["status"]
        attempt = selection["attempt"]
    request = product_review_adapter.request_path(Path(ep).resolve(), kind, attempt=attempt)
    if product_review_adapter._request_exists(request):
        saved = product_review_adapter._read_json(request)
        candidate = (ROOT / str(saved.get("candidate_path") or "")).resolve()
        if saved.get("status") == product_review_adapter.AWAITING:
            if candidate.is_file():
                command = "story_review.py" if kind == "story-semantic" else "visual_review.py"
                argv = [sys.executable, SYSTEM / command, "finalize-review", ep,
                        "--attempt", str(attempt), "--runtime", "WORK"]
                result = run(argv)
                return result.returncode, result.stdout[-5000:]
            runtime_observability.safe_record_runtime_event(
                ep, "INCREMENTAL_VERIFY_FINISHED", run_id=run_id, trace_id=trace_id,
                step="INCREMENTAL_PLAN", status="HOST_WAIT", evidence_type=kind,
                reason="existing scoped review request awaits host candidate",
                evidence_ref=saved.get("request_id"), source="runtime_dag")
            return product_review_adapter.HOST_ACTION_REQUIRED_RC, json.dumps(saved, ensure_ascii=False)
        # Terminal or stale request cannot silently authorize a new attempt here.
        return 4, f"scoped {kind} request is not awaiting: {saved.get('status')}"
    cli = "story_review.py" if kind == "story-semantic" else "visual_review.py"
    argv = [sys.executable, SYSTEM / cli, "run-critic", ep,
            "--attempt", str(attempt), "--timeout", str(timeout)]
    if codex:
        argv.extend(["--codex", codex])
    result = run(argv)
    return result.returncode, result.stdout[-5000:]


def _incremental_plan_policy_sha(ep):
    try:
        import model_policy_persistence
        bound = model_policy_persistence.load(Path(ep).resolve()) or {}
        return str(bound.get("policy_sha256") or "")
    except Exception:
        return ""


def _record_incremental_plan_events(ep, incremental_plan, *, run_id, trace_id):
    """Emit transparent reuse/invalidation/missing evidence observations."""
    if not isinstance(incremental_plan, dict):
        return
    policy_sha = _incremental_plan_policy_sha(ep)
    labels = (("story", "story-semantic-review"),
              ("visual", "visual-profile-review"),
              ("subtitle", "subtitle-layout-audit"))
    for key, evidence_type in labels:
        evidence_plan = incremental_plan.get("evidence_plan")
        details = incremental_plan.get("details")
        value = (evidence_plan.get(key) if isinstance(evidence_plan, dict) else None)
        if not isinstance(value, dict):
            value = details.get(key) if isinstance(details, dict) else None
        if not isinstance(value, dict):
            value = incremental_plan.get(key)
        value = value if isinstance(value, dict) else {}

        state_value = str(value.get("state") or value.get("status") or "").upper()
        action_value = str(value.get("action") or "").upper()
        if not state_value:
            state_value = str(incremental_plan.get(key) or "").upper()
        ref = (value.get("evidence_ref") or value.get("ref") or
               value.get("receipt_ref") or {
                   "story": "meta/story-semantic-review.json",
                   "visual": "meta/visual-profile-review.json",
                   "subtitle": "meta/subtitle-layout-audit.json",
               }[key])
        fingerprint = (value.get("evidence_fingerprint") or value.get("fingerprint"))
        source_sha = (value.get("source_sha") or value.get("source_artifact_sha") or
                      value.get("source_artifact_sha256") or value.get("source_sha256"))
        if not source_sha and isinstance(value.get("source"), dict):
            source = value["source"]
            source_sha = (source.get("sha256") or source.get("source_sha") or
                          source.get("artifact_sha256"))
        item_policy_sha = (value.get("policy_sha") or value.get("policy_sha256") or
                           value.get("model_policy_sha256") or policy_sha)
        reason = value.get("reason")
        if isinstance(reason, (list, tuple)):
            reason = ",".join(str(item) for item in reason)
        event = {"run_id": run_id, "trace_id": trace_id, "step": INCREMENTAL_PLAN_STEP,
                 "evidence_type": evidence_type, "evidence_ref": ref,
                 "evidence_fingerprint": fingerprint, "source_sha": source_sha,
                 "policy_sha": item_policy_sha, "old_fingerprint": value.get("old_fingerprint"),
                 "new_fingerprint": value.get("new_fingerprint") or fingerprint,
                 "reason": reason, "source": "runtime_dag"}
        if state_value in {"CLEAN", "REUSE", "REUSED"} or action_value in {"REUSE", "REUSED"}:
            runtime_observability.safe_record_runtime_event(ep, "EVIDENCE_REUSED", **event)
        elif state_value in {"DIRTY", "INVALID", "INVALIDATED"} or action_value in {
                "VERIFY", "RECOMPUTE", "INVALIDATE"}:
            runtime_observability.safe_record_runtime_event(ep, "EVIDENCE_INVALIDATED", **event)
        elif state_value in {"MISSING", "MISSING_EVIDENCE"} or action_value in {
                "GENERATE_EVIDENCE", "RECOVER_MISSING"}:
            runtime_observability.safe_record_runtime_event(ep, "EVIDENCE_MISSING", **event)

    frame_plan = incremental_plan.get("frame_plan")
    if not isinstance(frame_plan, dict):
        return
    action = str(frame_plan.get("action") or "").upper()
    dirty = list(frame_plan.get("dirty_frames") or [])
    reused = list(frame_plan.get("reused_frames") or [])
    context = list(frame_plan.get("context_frames") or [])
    missing = list(frame_plan.get("missing_evidence_frames") or [])
    frame_metadata = {}
    if not reused or dirty:
        try:
            import frame_semantic_review
            rows = frame_semantic_review.frame_records(Path(ep).resolve(), require_files=False)
            frame_metadata = {str(row.get("frame")): row for row in rows}
            if not reused:
                accepted = {str(item).zfill(2) for item in
                            frame_plan.get("accepted_known_defect_frames") or []}
                changed = {str(item).zfill(2) for item in dirty}
                reused = sorted(set(frame_metadata) - accepted - changed)
        except Exception:
            frame_metadata = {}
    if action in {"NOOP", "NOT_REQUIRED"}:
        runtime_observability.safe_record_runtime_event(
            ep, "FRAME_REVIEW_REUSED", run_id=run_id, trace_id=trace_id,
            step="PRODUCTION", evidence_type="frame-review", policy_sha=policy_sha,
            reused_frames=reused, reuse_count=len(reused), reason=action,
            source="runtime_dag")
    elif action in {"PATCH", "FULL"}:
        for frame in dirty:
            runtime_observability.safe_record_runtime_event(
                ep, "EVIDENCE_INVALIDATED", run_id=run_id, trace_id=trace_id,
                step="INCREMENTAL_PLAN", evidence_type="frame-review",
                evidence_ref=str(frame), frame_id=str(frame).zfill(2),
                source_sha=(frame_metadata.get(str(frame).zfill(2)) or {}).get("sha256"),
                generation_key=(frame_metadata.get(str(frame).zfill(2)) or {}).get("generation_key"),
                policy_sha=policy_sha,
                old_fingerprint=(frame_plan.get("old_fingerprints") or {}).get(str(frame).zfill(2)),
                new_fingerprint=(frame_plan.get("new_fingerprints") or {}).get(str(frame).zfill(2)),
                reason=",".join((frame_plan.get("reasons") or {}).get(str(frame), [])) or action,
                source="runtime_dag")
        runtime_observability.safe_record_runtime_event(
            ep, "FRAME_REVIEW_RECOMPUTED", run_id=run_id, trace_id=trace_id,
            step="PRODUCTION", evidence_type="frame-review", policy_sha=policy_sha,
            dirty_frames=dirty, reused_frames=reused, context_frames=context,
            missing_evidence_frames=missing, recompute_count=len(dirty),
            reuse_count=len(reused), missing_count=len(missing),
            full_review_count=1 if action == "FULL" else 0,
            patch_review_count=1 if action == "PATCH" else 0,
            reason=action, source="runtime_dag")
    for frame in missing:
        runtime_observability.safe_record_runtime_event(
            ep, "EVIDENCE_MISSING", run_id=run_id, trace_id=trace_id,
            step="INCREMENTAL_PLAN", evidence_type="frame-review",
            evidence_ref=str(frame), policy_sha=policy_sha,
            reason="MISSING_EVIDENCE", source="runtime_dag")


def _run_incremental_frame_verification(ep, *, attempt, codex, timeout, run_id, trace_id,
                                       command="review"):
    started_monotonic = time.monotonic()
    started = runtime_node_execution.now()
    runtime_observability.safe_record_runtime_event(
        ep, "INCREMENTAL_VERIFY_STARTED", run_id=run_id, trace_id=trace_id,
        step="PRODUCTION", started_at=started, source="runtime_dag")
    argv = [sys.executable, SYSTEM / "incremental_frame_review.py", command, ep]
    if command == "review":
        argv.extend(["--attempt", str(attempt), "--timeout", str(timeout)])
    if command == "review" and codex:
        argv.extend(["--codex", codex])
    result = run(argv)
    finished = runtime_node_execution.now()
    runtime_observability.safe_record_runtime_event(
        ep, "INCREMENTAL_VERIFY_FINISHED", run_id=run_id, trace_id=trace_id,
        step="PRODUCTION", started_at=started, finished_at=finished,
        duration_ms=(time.monotonic() - started_monotonic) * 1000,
        status="PASS" if result.returncode == 0 else "FAILED",
        failure_class=None if result.returncode == 0 else str(result.returncode),
        source="runtime_dag")
    return result.returncode, result.stdout[-5000:]

def run_release_preflight_recovery(ep: Path, codex=None, timeout=None) -> tuple[int, str]:
    """Run targeted release evidence recovery after the scoped RELEASE worker.

    The scoped worker creates captions/copy/assets.  This hook reuses the
    existing prepare-auto recovery only after those sources exist, so stale
    caption/compliance/release-review evidence does not force a second full
    RELEASE worker invocation.  Non-zero results are preserved fail-closed.
    """
    import argparse
    import release_preflight
    try:
        rc = int(release_preflight.cmd_prepare_auto(argparse.Namespace(
            episode_dir=str(ep), codex=codex, timeout=timeout,
        )))
    except Exception as exc:
        return 4, f"RELEASE PREFLIGHT AUTO RECOVERY FAIL: {exc}"
    if rc != 0:
        return rc, f"RELEASE PREFLIGHT AUTO RECOVERY rc={rc}"
    return 0, "RELEASE PREFLIGHT AUTO RECOVERY PASS"


def execute(ep,codex=None,timeout=None,run_id=None,trace_id=None,until=None):
    """Give direct DAG invocations the same active/wait accounting as a runner."""
    # A bounded-run contract error must fail before telemetry creates any durable
    # evidence. _execute keeps the same guard for callers that intentionally use
    # the lower-level helper.
    if until is not None and until not in STAGES:
        raise ValueError("unknown runtime DAG stop target: "+str(until))
    runtime_ownership.assert_v3_owner("runtime_dag.execute")

    # Performance telemetry is explicitly fail-soft and is never a production
    # gate. A temporary test repository, unavailable metric authority, or other
    # observability failure must not prevent the DAG from executing.
    telemetry_available=True
    try:
        sessions=(episode_performance.load(ep,True).get("execution_sessions") or [])
        open_session=next((row for row in reversed(sessions) if not row.get("ended_at")),None)
    except Exception:
        telemetry_available=False
        open_session=None
    owned=telemetry_available and open_session is None
    session=open_session.get("session_id") if open_session else None
    telemetry_owned=False
    if owned:
        session=episode_performance.safe_begin_execution_session(ep,source="runtime_dag")
        telemetry_owned=session is not None
    elif telemetry_available and (open_session or {}).get("source")=="runtime_dag":
        telemetry_owned=True
    if telemetry_owned:
        episode_performance.safe_transition_execution_state(ep,"ACTIVE",session_id=session,source="runtime_dag")
    rc=None
    event_run_id=run_id or session or uuid.uuid4().hex
    event_started=time.monotonic()
    try:
        import logical_asset_identity
        runtime_observability.safe_record_runtime_event(
            ep,"EPISODE_RUN_STARTED",episode_id=logical_asset_identity.episode_id(ep),run_id=event_run_id,
            trace_id=trace_id,source="runtime_dag.execute")
    except Exception:
        pass
    try:
        rc=_execute(ep,codex=codex,timeout=timeout,run_id=run_id,trace_id=trace_id,until=until,
                    telemetry_run_id=event_run_id)
        return rc
    finally:
        try:
            import logical_asset_identity
            runtime_observability.safe_record_runtime_event(
                ep,"EPISODE_RUN_FINISHED",episode_id=logical_asset_identity.episode_id(ep),run_id=event_run_id,
                trace_id=trace_id,duration_ms=(time.monotonic()-event_started)*1000,
                status="PASS" if rc==0 else ("HOST_WAIT" if rc==product_runtime_adapter.HOST_ACTION_REQUIRED_RC else "FAILED"),
                source="runtime_dag.execute")
        except Exception:
            pass
        if telemetry_owned:
            state=episode_performance.execution_state_for_result(rc if rc is not None else 1)
            episode_performance.safe_transition_execution_state(ep,state,session_id=session,source="runtime_dag")
            if state=="IDLE":
                episode_performance.safe_finish_execution_session(ep,session_id=session,status="COMPLETE" if rc==0 else "BLOCKED")


def preimage_worker_timeout(task: dict, supervisor_timeout: int | None) -> int:
    """Honor each PREIMAGE candidate's bounded execution budget.

    The supervisor may run for hours, but a single image-planning candidate may
    not inherit that entire budget. This is also the deadline persisted in the
    User Runner / in-flight recovery record.
    """
    budget = (task.get("execution_budget") or {}).get("timeout_seconds")
    if type(budget) is not int or budget <= 0:
        raise ValueError("PREIMAGE worker has no valid positive timeout_seconds budget")
    if supervisor_timeout is None:
        return budget
    if type(supervisor_timeout) is not int or supervisor_timeout <= 0:
        raise ValueError("supervisor timeout must be a positive integer")
    return min(budget, supervisor_timeout)


def _execute(ep,codex=None,timeout=None,run_id=None,trace_id=None,until=None,telemetry_run_id=None):
    # W-11: a recorded production-owner switch only becomes effective when the
    # Production Kernel consumes it. Direct DAG execution is a production entry,
    # so fail closed before any reconcile/executor side effect.
    runtime_ownership.assert_v3_owner("runtime_dag.execute")
    # STORY_OS_V262_DAG_STOP_TARGET: a stop target is a canonical Episode stage, never a step id.
    # Reject an unknown target before any reconcile, lock or executor exists.
    if until is not None and until not in STAGES:
        raise ValueError("unknown runtime DAG stop target: "+str(until))
    # Direct DAG callers (including bounded recovery/test harnesses) may not be
    # wrapped by workflow_runner. Give their spans a real local context instead
    # of allowing uncorrelatable SPAN_* events; the normal wrapper still owns
    # the durable TRACE_START/TRACE_END lifecycle.
    trace_run_id = run_id or "dag_" + uuid.uuid4().hex
    event_run_id = telemetry_run_id or run_id or trace_run_id
    trace_id = trace_id or "ST_" + uuid.uuid4().hex[:16]
    blocked=reconcile_visual_profile_closure(ep)
    if blocked is not None:
        # Phase 4.6.1: an unreconcilable Visual Profile closure fails closed. It is never
        # reported as a pass, and no production step is started.
        print("VISUAL PROFILE CLOSURE RECONCILE BLOCKED")
        for line in blocked: print(line)
        return RECONCILE_BLOCKED_RC
    dag=load_dag(); specs=spec_rows(); total_start=time.monotonic()
    if timeout is None:
        timeout = runtime_timeout_policy.seconds("codex_supervisor_run")
    mode=request_mode(ep)
    mode_errors=runtime_mode_router.guard(ep,mode)
    if mode_errors:
        print("RUNTIME_MODE_GUARD_FAIL")
        for err in mode_errors: print(err)
        return 8
    if mode in {"repair_only", "release_only"} and not (
            mode == "release_only" and state(ep) == "PUBLISH_READY"):
        # Special repair/release modes dispatch a scoped model directly, bypassing
        # the normal scheduler loop. Freeze at the common boundary first.
        policy_errors=_freeze_model_policy_before_dispatch(ep)
        if policy_errors:
            print("MODEL POLICY BIND FAIL")
            for err in policy_errors: print(err)
            return 8
    special_rc=runtime_mode_router.dispatch_special(ep,mode,codex,timeout)
    if special_rc is not None: return special_rc
    if mode=="image_continue":
        preproduction_handoff.migrate_legacy_boundary(ep)  # STORY_OS_V211_PERF_RECOVERY
        handoff_errors=preproduction_handoff.verify(ep)
        if handoff_errors:
            print("HANDOFF VERIFY FAIL")
            for err in handoff_errors:print(err)
            return 6
        resource_library.resolve(ep,write=True)
    provisional_future=None
    background=cf.ThreadPoolExecutor(max_workers=1,thread_name_prefix="story-os-release-prep")
    # V3 V2.1: retain existing executors and evidence/Gate behavior, but let the
    # scheduler release the next real Runtime step from its declared dependencies.
    # max_workers remains 1 because these composite legacy steps are not yet safe
    # to execute concurrently.
    step_by_id={spec.step_id: spec for spec in specs}
    completed_nodes=set()
    node_contract=runtime_node_registry.runtime_step_nodes(specs)
    scheduler_resources=production_scheduler_resources()
    incremental_plan=None
    if until:
        # Already at or past the target: stopping is a no-op, so do not spawn INCREMENTAL_PLAN
        # or any other step merely to arrive back here.
        reached,detail=stop_target_reached(ep,until)
        if reached:
            background.shutdown(wait=False,cancel_futures=True)
            print(STOP_TARGET_REACHED+" "+until+" (already valid)")
            return 0
    if mode not in {"data_review", "repair_only", "release_only"}:
        # Normal scheduler modes freeze after the no-op target check but before
        # the scheduler can release its first model executor.
        policy_errors=_freeze_model_policy_before_dispatch(ep)
        if policy_errors:
            background.shutdown(wait=False,cancel_futures=True)
            print("MODEL POLICY BIND FAIL")
            for err in policy_errors: print(err)
            return 8
    while len(completed_nodes)<len(specs):
        wave=runtime_scheduler.schedule(
            node_contract,
            completed=completed_nodes,
            max_workers=scheduler_resources["max_workers"],
            resource_snapshot=scheduler_resources,
        )
        if not wave["dispatch"]:
            background.shutdown(wait=False,cancel_futures=True)
            print("RUNTIME DAG SCHEDULER BLOCKED", json.dumps({
                "waiting":[x["node_id"] for x in wave["waiting"]],
                "blocked":[x["node_id"] for x in wave["blocked"]],
            },ensure_ascii=True))
            return 2
        s=step_by_id[wave["dispatch"][0]["node_id"]]
        node_started=runtime_node_execution.now()
        node_t0=time.monotonic()
        cur=state(ep)
        if s.step_id == "CREATIVE_STORY" and cur == "IDEA_LOCKED":
            approval_rc, approval_note = _recover_verified_story_without_model(ep, cur)
            if approval_rc == 22:
                runtime_observability.safe_record_runtime_event(
                    ep, "STEP_FAILED", run_id=event_run_id, trace_id=trace_id,
                    step=s.step_id, status="BLOCKED", failure_class="22",
                    reason=approval_note, source="runtime_dag")
                background.shutdown(wait=False, cancel_futures=True)
                print("OFFICIAL_STORY_RECOVERY_BLOCKED", approval_note)
                return 22
            if approval_rc == 0:
                cur = state(ep)
        if s.step_id=="CREATIVE_STORY" and not stage_at_least(cur,"STORYBOARD_LOCKED"):
            directing_quality.before_step(ep,s.step_id)
            preparation_started=proto.now()
            character_contract.prepare(ep,force=False)
            character_visual_contract.prepare(ep,force=False)
            runtime_node_evidence.record(
                ep,node_id="character_prepare",start_time=preparation_started,end_time=proto.now(),
                status="PASS",attempt=1,output="character + character_visual contract scaffolds prepared",
                evidence=["meta/character-contract.json","meta/character-visual-contract.json"])
        prior=(proto.load_state(ep).get("steps") or {}).get(s.step_id) or {}
        attempt=int(prior.get("attempt") or 0)+1
        resolved_role=getattr(s,"model_role",None) or MODEL_ROLE_BY_STEP.get(s.step_id,"")
        input_hash=_step_input_hash(ep,["meta/episode-state.json",*s.evidence_paths],resolved_role=resolved_role)
        if s.step_id==INCREMENTAL_PLAN_STEP:
            input_hash=_evidence_input_hash(ep,INCREMENTAL_PLAN_INPUTS)
        if s.step_id=="PREIMAGE_COMPILE":
            handoff_valid=False
            try:
                handoff_valid=(ep/"meta/preproduction-handoff.json").is_file() and not preproduction_handoff.verify(ep)
            except Exception:
                handoff_valid=False
            if handoff_valid or stage_at_least(cur,"VISUAL_CALIBRATED"):
                reason="preproduction handoff already valid" if handoff_valid else "downstream stage already valid; legacy preimage not backfilled"
                out_hash=_evidence_input_hash(ep,["meta/episode-state.json",*s.evidence_paths])
                reused_elapsed=time.monotonic()-node_t0
                res=proto.StepResult(s.step_id,"REUSED",attempt,node_started,runtime_node_execution.now(),reused_elapsed,input_hash,out_hash,reason,0)
                proto.save_result(ep,res); checkpoint(ep,s.step_id,"REUSED",reused_elapsed,reason,attempt,input_hash,out_hash)
                if run_id: perf.record_step(ep,run_id,s.step_id,"REUSED",reused_elapsed,reason)
                episode_performance.safe_end_stage(ep,s.step_id,status="REUSED",metadata={"reused":True,"reason":reason})
                next_action.write(ep)
                runtime_node_evidence.record(
                    ep,node_id=s.step_id,start_time=res.started_at,end_time=res.finished_at,
                    status="REUSED",attempt=attempt,output=reason,evidence=s.evidence_paths)
                completed_nodes.add(s.step_id)
                if mode=="preproduction_only":
                    background.shutdown(wait=False,cancel_futures=True)
                    return 0
                continue
        if s.target_state and stage_at_least(cur,s.target_state):
            ok,msg=validate_target(ep,s.target_state)
            if s.step_id == "CREATIVE_STORY" and not ok:
                background.shutdown(wait=False,cancel_futures=True)
                print("VERIFIED_STORY_STAGE_INVALID_NO_MODEL_REPLAY", msg)
                return 22
            if ok:
                out_hash=_evidence_input_hash(ep,["meta/episode-state.json",*s.evidence_paths])
                reused_elapsed=time.monotonic()-node_t0
                res=proto.StepResult(s.step_id,"REUSED",attempt,node_started,runtime_node_execution.now(),reused_elapsed,input_hash,out_hash,"target already valid",0)
                proto.save_result(ep,res); checkpoint(ep,s.step_id,"REUSED",reused_elapsed,"target already valid",attempt,input_hash,out_hash)
                if run_id: perf.record_step(ep,run_id,s.step_id,"REUSED",reused_elapsed,"target already valid")
                episode_performance.safe_end_stage(ep,s.step_id,status="REUSED",metadata={"reused":True,"target_state":s.target_state})
                _t=time.monotonic()
                _sp=runtime_trace.start_span(ep,s.step_id,category="workflow_step",trace_id=trace_id,run_id=trace_run_id,attrs={"reused":True})
                runtime_trace.end_span(ep,_sp,name=s.step_id,category="workflow_step",status="REUSED",started_monotonic=_t,trace_id=trace_id,run_id=trace_run_id,attrs={"target_state":s.target_state})
                runtime_node_evidence.record(
                    ep,node_id=s.step_id,start_time=res.started_at,end_time=res.finished_at,
                    status="REUSED",attempt=attempt,output="target already valid",evidence=s.evidence_paths)
                runtime_observability.safe_record_runtime_event(
                    ep,"STEP_READY",run_id=event_run_id,trace_id=trace_id,step=s.step_id,
                    timestamp=node_started,source="runtime_dag")
                runtime_observability.safe_record_runtime_event(
                    ep,"STEP_FINISHED",run_id=event_run_id,trace_id=trace_id,step=s.step_id,
                    timestamp=res.finished_at,duration_ms=reused_elapsed*1000,status="REUSED",source="runtime_dag")
                completed_nodes.add(s.step_id)
                continue
        started_at=runtime_node_execution.now(); t0=time.monotonic(); rc=0; note=""
        runtime_observability.safe_record_runtime_event(
            ep,"STEP_READY",run_id=event_run_id,trace_id=trace_id,step=s.step_id,
            timestamp=node_started,source="runtime_dag")
        runtime_observability.safe_record_runtime_event(
            ep,"STEP_STARTED",run_id=event_run_id,trace_id=trace_id,step=s.step_id,
            timestamp=started_at,source="runtime_dag")
        runtime_observability.safe_record_runtime_event(
            ep,"STEP_DISPATCHED",run_id=event_run_id,trace_id=trace_id,step=s.step_id,
            timestamp=started_at,source="runtime_dag")
        episode_performance.safe_begin_stage(ep,s.step_id,source="runtime_dag",metadata={"executor":s.executor,"target_state":s.target_state})
        trace_span=runtime_trace.start_span(ep,s.step_id,category="workflow_step",trace_id=trace_id,run_id=trace_run_id,attrs={"executor":s.executor,"target_state":s.target_state})
        if s.step_id=="PREIMAGE_COMPILE":
            resource_library.resolve(ep,write=True)
            intro_policy.resolve(ep,write=True)
        if s.executor=="machine_incremental_plan":
            runtime_observability.safe_record_runtime_event(
                ep,"INCREMENTAL_PLAN_STARTED",run_id=event_run_id,trace_id=trace_id,
                step=s.step_id,source="runtime_dag")
            cp=run([sys.executable,SYSTEM/"incremental_closure.py","plan",ep,"--json"])
            rc=cp.returncode; note=cp.stdout[-5000:]
            try:
                incremental_plan=json.loads(cp.stdout)
            except (TypeError, ValueError):
                incremental_plan=None
                if rc==0:
                    rc=4
                    note="INCREMENTAL PLAN OUTPUT INVALID JSON: "+cp.stdout[-1000:]
            runtime_observability.safe_record_runtime_event(
                ep,"INCREMENTAL_PLAN_FINISHED",run_id=event_run_id,trace_id=trace_id,
                step=s.step_id,status="PASS" if rc==0 else "FAILED",
                failure_class=None if rc==0 else str(rc),
                reason=(incremental_plan or {}).get("action"),source="runtime_dag")
            if rc==0 and incremental_plan is not None:
                _record_incremental_plan_events(
                    ep,incremental_plan,run_id=event_run_id,trace_id=trace_id)
                blocker=_unsupported_missing_evidence(incremental_plan)
                if blocker:
                    rc=4
                    note="MISSING_EVIDENCE_FAIL_CLOSED: "+blocker
        elif (s.step_id=="CREATIVE_STORY" and (block := story_narrative_form.failed_locked_review_block(ep))):
            rc=22;note=block
        elif (s.step_id=="CREATIVE_STORY" and incremental_runtime_strategy(
                incremental_plan,s.step_id,cur)=="VERIFY_STORY_EVIDENCE"):
            rc,note=_run_targeted_review(
                ep,kind="story-semantic",attempt=attempt,codex=codex,
                timeout=timeout,run_id=event_run_id,trace_id=trace_id)
        elif (s.step_id=="VISUAL_LOCK" and incremental_runtime_strategy(
                incremental_plan,s.step_id,cur)=="VERIFY_VISUAL_EVIDENCE"):
            try:
                import visual_review
                review_kind=("visual-lock" if visual_review.is_v21(Path(ep).resolve())
                             else "visual-profile-legacy")
                rc,note=_run_targeted_review(
                    ep,kind=review_kind,attempt=attempt,codex=codex,
                    timeout=timeout,run_id=event_run_id,trace_id=trace_id)
            except Exception as exc:
                rc=4
                note="TARGETED VISUAL REVIEW ROUTING FAIL: "+str(exc)
        elif (s.step_id=="RELEASE" and _plan_evidence_state(
                incremental_plan,"subtitle") in {"MISSING","DIRTY"}):
            cp=run([sys.executable,SYSTEM/"subtitle_layout.py","audit",ep])
            rc=cp.returncode
            note="TARGETED SUBTITLE AUDIT: "+cp.stdout[-4000:]
        elif (s.step_id=="PRODUCTION" and incremental_runtime_strategy(
                incremental_plan,s.step_id,cur)=="REUSE_FRAME_EVIDENCE"):
            rc,note=_run_incremental_frame_verification(
                ep,attempt=attempt,codex=codex,timeout=timeout,run_id=event_run_id,
                trace_id=trace_id,command="verify")
        elif (s.step_id=="PRODUCTION" and incremental_runtime_strategy(
                incremental_plan,s.step_id,cur)=="VERIFY_INCREMENTALLY"):
            rc,note=_run_incremental_frame_verification(
                ep,attempt=attempt,codex=codex,timeout=timeout,run_id=event_run_id,
                trace_id=trace_id,command="review")
        elif s.step_id=="PROMPT_AUTHORING":
            import locked_story_prompt_authoring
            if locked_story_prompt_authoring.applicable(ep):
                # Already-locked user story: Frame Contract/Storyboard together
                # contain the authoritative per-frame scene. Generate derived
                # transport hints + SHA-bound packages without 3600s of redundant
                # model rewriting, then keep the official DAG postcondition path.
                try:
                    output=locked_story_prompt_authoring.run(ep)
                    note=json.dumps({
                        "execution":"LOCKED_STORY_DETERMINISTIC_PROMPTS",
                        "model_dispatched":False,
                        "count":output["frame_count"],
                        "audit":"meta/runtime/locked-story-prompt-authoring.json",
                    },ensure_ascii=True)
                    rc=0
                except Exception as exc:
                    rc=4
                    note="LOCKED STORY PROMPT AUTHORING FAIL: "+str(exc)
            else:
                execution_capsule.compile_capsule(ep,s.step_id,write=True)
                step_timeout=min(timeout,int(dag.get("scoped_worker_timeout_seconds") or runtime_timeout_policy.seconds("codex_scoped_step")))
                rc,log=scoped_codex_worker.run_step(ep,s.step_id,codex_raw=codex,timeout=step_timeout)
                note=(note+" "+f"log={log}").strip()
        elif s.executor in {"scoped_model","scoped_codex"}:
            execution_capsule.compile_capsule(ep,s.step_id,write=True)
            active_runtime,_=runtime_router.detect()
            if active_runtime in {"WORK","WEB"} and not codex:
                deterministic_preimage_step=None
                if s.step_id=="PREIMAGE_COMPILE":
                    host_step,_=product_runtime_adapter.next_host_step(ep,mode)
                    if host_step=="PREIMAGE_FRAME_CONTRACT_COMPILE":
                        import frame_contract
                        import preimage_directing_materializer
                        try:
                            _assert_preimage_storage_schema()
                            materialized=preimage_directing_materializer.ensure(ep)
                            index=frame_contract.compile_all(ep)
                            deterministic_preimage_step=host_step
                            note=json.dumps({"deterministic_step":host_step,"directing_contracts":materialized.get("contracts"),"frame_contract_index_sha256":index.get("index_sha256")},ensure_ascii=True)
                        except Exception as exc:
                            rc=4
                            note=f"PREIMAGE FRAME CONTRACT COMPILE FAIL: {exc}"
                    elif host_step=="PREIMAGE_VERIFY":
                        import frame_contract
                        import preimage_directing_materializer
                        try:
                            _assert_preimage_storage_schema()
                            materialized=preimage_directing_materializer.ensure(ep)
                            # A hosted authority commit can make the strict directing
                            # contracts appear after an earlier Frame Contract compile.
                            # Recompile here so final PREIMAGE verification binds the
                            # exact materialized contract SHAs instead of stale/missing ones.
                            index=frame_contract.compile_all(ep)
                            deterministic_preimage_step=host_step
                            note=json.dumps({"deterministic_step":host_step,"reason":"current authority exists; materialize strict directing contracts and verify/build handoff locally","directing_contracts":materialized.get("contracts"),"frame_contract_index_sha256":index.get("index_sha256")},ensure_ascii=True)
                        except Exception as exc:
                            rc=4
                            note=f"PREIMAGE VERIFY MATERIALIZATION FAIL: {exc}"
                if deterministic_preimage_step is not None:
                    rc=0
                elif rc==0:
                    request=product_runtime_adapter.build_request(
                        ep,runtime=active_runtime,mode=mode,resume=True,source=f"runtime_dag:{s.step_id}")
                    rc=product_runtime_adapter.HOST_ACTION_REQUIRED_RC
                    note=json.dumps(request,ensure_ascii=True)
            elif s.step_id=="PREIMAGE_COMPILE":
                # A local explicit CODEX run executes four bounded workers.  It
                # is not a threaded wrapper around the legacy composite prompt.
                import preimage_protocol
                import preimage_task_contract
                # Fail here, before the fan-out, if any task's step is missing
                # from a registry: the alternative is discovering it inside a
                # worker 20 minutes in, with the other three already running.
                preimage_task_contract.assert_registries_aligned()
                # This branch is the explicit local-Codex PREIMAGE fallback only.
                # WORK + Workspace Provider production goes through the host-action branch above;
                # its concurrency is owned by the host transport, not this local pool.
                workers=int(storyos_config.get_path(storyos_config.load_config(),"runtime.workers.local_codex_preimage") or 4)
                def _worker(task):
                    step=preimage_task_contract.canonical_step(task["task_type"])
                    execution_capsule.compile_capsule(ep,step,write=True)
                    # The scoped model log is append-only across attempts;
                    # only bytes written by THIS execution may prove its
                    # completed Codex turn when Host seals a Candidate.
                    scoped_log=ep/"meta/scoped-workers"/f"{step.lower()}.jsonl"
                    log_offset=scoped_log.stat().st_size if scoped_log.is_file() else 0
                    value, _log=scoped_codex_worker.run_step(
                        ep,step,codex_raw=codex,
                        timeout=preimage_worker_timeout(task,timeout))
                    if value == 0:
                        # The scoped model writes the semantic Candidate, not
                        # the authority digest. Bind trusted task/snapshot SHA
                        # only after a genuine completed native turn and full
                        # semantic verification. Preserve raw model bytes.
                        sealed=preimage_task_contract.seal_scoped_native_candidate(
                            ep, task, _log, log_start_offset=log_offset)
                        if sealed.get("status") != "PASS":
                            # A failed payload/semantic check remains FAILED.
                            # Do not crash sibling tasks or fabricate progress.
                            return 4
                    return value
                outcome=preimage_protocol.execute_local(ep,_worker,max_workers=workers)
                rc=0 if outcome.get("status")=="PASS" else 4
                if rc == 0:
                    import frame_contract
                    import preimage_directing_materializer
                    try:
                        # A committed PREIMAGE authority round licenses only deterministic
                        # derivation, not new model judgment: materialize the strict per-frame
                        # directing contracts from the committed authority before compiling
                        # Frame Contracts.  This mirrors the WORK/Product host branch above;
                        # without it a local CODEX run commits authority and then fails its own
                        # PREIMAGE directing-quality gate because those four contracts were
                        # never materialized.
                        materialized=preimage_directing_materializer.ensure(ep)
                        outcome["directing_contracts"]=materialized.get("contracts")
                        index=frame_contract.compile_all(ep)
                        outcome["frame_contract_index_sha256"]=index.get("index_sha256")
                    except Exception as exc:
                        rc=4; outcome["frame_contract_compile_error"]=str(exc)
                note=(note+" "+json.dumps(outcome,ensure_ascii=True))[-5000:]
            else:
                if s.step_id=="RELEASE" and provisional_future is not None:
                    try:
                        prep=provisional_future.result(timeout=120)
                        note=f"provisional_release={prep}"
                    except Exception as exc:
                        note=f"provisional_release_nonblocking_failure={exc}"
                step_timeout=min(timeout,int(dag.get("scoped_worker_timeout_seconds") or runtime_timeout_policy.seconds("codex_scoped_step")))
                rc,log=scoped_codex_worker.run_step(ep,s.step_id,codex_raw=codex,timeout=step_timeout); note=(note+" "+f"log={log}").strip()
        else:
            rc=2; note=f"unknown executor {s.executor}"
        elapsed=time.monotonic()-t0
        if rc==0 and s.step_id=="CREATIVE_STORY":
            character_errors=character_contract.validate(ep,require_locked=True)
            if character_errors:
                rc=4
                note=(note+"\nCHARACTER CONTRACT FAIL\n"+"\n".join(character_errors))[-5000:]
            elif world_identity_contract.required(ep):
                world_errors=world_identity_contract.verify(ep)
                if world_errors:
                    rc=4
                    note=(note+"\nWORLD IDENTITY FAIL\n"+"\n".join(world_errors))[-5000:]
                else:
                    try:
                        character_appearance_anchor.build(ep,write=True)
                        anchor_errors=character_appearance_anchor.verify(ep)
                    except Exception as exc:
                        anchor_errors=[str(exc)]
                    if anchor_errors:
                        rc=4
                        note=(note+"\nCHARACTER APPEARANCE ANCHOR FAIL\n"+"\n".join(anchor_errors))[-5000:]
        if rc==0 and s.step_id=="PREIMAGE_COMPILE":
            quality_errors=directing_quality.verify_preimage(ep)
            if quality_errors:
                rc=4
                note=(note+"\nPREIMAGE DIRECTING QUALITY FAIL\n"+"\n".join(quality_errors))[-5000:]
            else:
                try:
                    handoff=preproduction_handoff.build(ep,source_runtime="chatgpt_or_codex")
                    note=(note+"\npreproduction_handoff="+str(handoff.get("manifest_sha256") or ""))[-5000:]
                except Exception as exc:
                    rc=7
                    note=(note+"\nPREPRODUCTION HANDOFF FAIL: "+str(exc))[-5000:]
        if rc==0:
            quality_errors=directing_quality.after_step(ep,s.step_id)
            if quality_errors:
                rc=4
                note=(note+"\nDIRECTING QUALITY FAIL\n"+"\n".join(quality_errors))[-5000:]
        if rc==0 and s.step_id=="RELEASE":
            recovery_rc,recovery_note=run_release_preflight_recovery(ep,codex=codex,timeout=timeout)
            note=(note+"\n"+recovery_note)[-5000:]
            if recovery_rc!=0:
                rc=recovery_rc
        if rc==0 and s.target_state:
            ok,msg=validate_target(ep,s.target_state)
            if not ok: rc=4; note=(note+"\nPOSTCONDITION FAIL\n"+msg)[-5000:]
        status="PASS" if rc==0 else ("HOST_WAIT" if rc==product_runtime_adapter.HOST_ACTION_REQUIRED_RC else ("BLOCKED" if rc in {124,3,4,22} else "FAILED"))
        runtime_observability.safe_record_runtime_event(
            ep,"STEP_FINISHED" if rc==0 else "STEP_FAILED",run_id=event_run_id,trace_id=trace_id,
            step=s.step_id,timestamp=runtime_node_execution.now(),duration_ms=elapsed*1000,
            status=status,failure_class=None if rc==0 else str(rc),source="runtime_dag")
        out_hash=_evidence_input_hash(ep,["meta/episode-state.json",*s.evidence_paths])
        res=proto.StepResult(s.step_id,status,attempt,started_at,runtime_node_execution.now(),elapsed,input_hash,out_hash,note,rc)
        proto.save_result(ep,res); checkpoint(ep,s.step_id,status,elapsed,note[-1200:],attempt,input_hash,out_hash,returncode=rc)
        runtime_node_evidence.record(
            ep,node_id=s.step_id,start_time=started_at,end_time=res.finished_at,status=status,
            attempt=attempt,output=note[-1200:],evidence=s.evidence_paths)
        if run_id: perf.record_step(ep,run_id,s.step_id,status,elapsed,note[-500:])
        runtime_trace.end_span(ep,trace_span,name=s.step_id,category="workflow_step",status=status,started_monotonic=t0,trace_id=trace_id,run_id=trace_run_id,attrs={"rc":rc,"attempt":attempt})
        if status != "HOST_WAIT":
            episode_performance.safe_end_stage(ep,s.step_id,status=status,metadata={"rc":rc,"attempt":attempt})
        try: quota_observability.snapshot(ep,note=f"after {s.step_id}")
        except Exception: pass
        try: performance_guard_v211.observe(ep,run_id,context=s.step_id)
        except Exception: pass
        next_action.write(ep)
        if rc!=0:
            # STORY_OS_V211_PERF_RECOVERY: on Visual Lock infrastructure failure,
            # generate at most six non-approvable candidates instead of idling.
            if s.step_id=="VISUAL_LOCK" and mode=="image_continue":
                try:
                    spec=speculative_production.run(ep,codex=codex,timeout=runtime_timeout_policy.clamp("image_lane_run", int(timeout)),max_frames=6)
                    spec_elapsed=float(spec.get("elapsed_seconds") or 0.0)
                    if run_id: perf.record_step(ep,run_id,"SPECULATIVE_PRODUCTION","PASS" if spec.get("status")=="GENERATED_CANDIDATES" else "SKIPPED",spec_elapsed,json.dumps(spec,ensure_ascii=True)[:500])
                    checkpoint(ep,"SPECULATIVE_PRODUCTION","PASS" if spec.get("status")=="GENERATED_CANDIDATES" else "SKIPPED",spec_elapsed,json.dumps(spec,ensure_ascii=True)[:1000])
                except Exception as exc:
                    if run_id: perf.record_step(ep,run_id,"SPECULATIVE_PRODUCTION","FAILED",0.0,str(exc)[:500])
            background.shutdown(wait=False,cancel_futures=True)
            return rc
        completed_nodes.add(s.step_id)
        if until:
            reached,detail=stop_target_reached(ep,until)
            if reached:
                # The step already wrote its checkpoint, node evidence, trace span and
                # next-action above, so a clean stop here loses no evidence.
                background.shutdown(wait=False,cancel_futures=True)
                print(STOP_TARGET_REACHED+" "+until+" after "+s.step_id)
                return 0
        if mode=="preproduction_only" and s.step_id=="PREIMAGE_COMPILE":
            try:
                # 900s was the historical review-critic default; build() now owns that default.
                provisional_release.build(ep,codex)
            except Exception as exc:
                print("PROVISIONAL RELEASE NONBLOCKING:",exc)
            background.shutdown(wait=False,cancel_futures=True)
            next_action.write(ep)
            return 0
        if s.step_id=="CREATIVE_STORY" and provisional_future is None and bool(dag.get("provisional_release_parallel",True)):
            provisional_future=background.submit(provisional_release.build,ep,codex)
    background.shutdown(wait=False)
    return 0

def self_test():
    rows=spec_rows()
    assert [x.step_id for x in rows]==["INCREMENTAL_PLAN","CREATIVE_STORY","PREIMAGE_COMPILE","PROMPT_AUTHORING","VISUAL_LOCK","PRODUCTION","RELEASE"]
    by_id={row.step_id:row for row in rows}
    assert by_id["PROMPT_AUTHORING"].depends_on==("PREIMAGE_COMPILE",)
    assert by_id["VISUAL_LOCK"].depends_on==("PROMPT_AUTHORING",)
    assert rows[-1].target_state=="PUBLISH_READY"
    # STORY_OS_V262_DAG_STOP_TARGET: --until takes a canonical stage, and every step's
    # declared target_state must be one, so a stop target and a step target are comparable.
    assert "PRODUCTION_PASSED" in STAGES, STAGES
    assert "PRODUCTION" not in STAGES, "a step id is not a stage"
    for row in rows:
        assert row.target_state is None or row.target_state in STAGES, row
    assert stage_at_least("PRODUCTION_PASSED","PRODUCTION_PASSED")
    assert not stage_at_least("VISUAL_CALIBRATED","PRODUCTION_PASSED")
    print("RUNTIME DAG V1 SELF-TEST PASS")

def main():
    ap=argparse.ArgumentParser(); sub=ap.add_subparsers(dest="cmd",required=True)
    p=sub.add_parser("plan"); p.add_argument("episode_dir")
    for n in ("run","resume"):
        p=sub.add_parser(n); p.add_argument("episode_dir"); p.add_argument("--codex"); p.add_argument("--timeout",type=int,default=None)
        p.add_argument("--until",choices=STAGES,default=None,help="stop cleanly once this canonical stage is reached and validated")
    p=sub.add_parser("show"); p.add_argument("episode_dir")
    sub.add_parser("self-test"); a=ap.parse_args()
    if a.cmd=="self-test": self_test(); return 0
    ep=Path(a.episode_dir).resolve()
    if a.cmd=="plan": print(json.dumps(plan(ep),ensure_ascii=True,indent=2)); return 0
    if a.cmd=="show": print(json.dumps(proto.load_state(ep),ensure_ascii=True,indent=2)); return 0
    return execute(ep,codex=a.codex,timeout=runtime_timeout_policy.resolve("codex_supervisor_run", a.timeout),until=a.until)

if __name__=="__main__": raise SystemExit(main())

# STORY_OS_V211_RUNTIME_CLOSURE_R31
