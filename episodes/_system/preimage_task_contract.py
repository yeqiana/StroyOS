#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PREIMAGE worker protocol: tasks/candidates/runtime-only resume state.

This module deliberately contains no episode-stage or Gate decision.  A task is
complete only when an independently produced candidate passes structural
verification; shared authority is committed later by ``authority_commit``.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

import runtime_atomic_store as atomic
import story_json
import runtime_request
import character_contract
import character_visual_contract
import review_record_persistence

STATE_REL = Path("meta/runtime/preimage-task-state.json")
CANDIDATE_REL = Path("meta/runtime/preimage-candidates")
TASK_TYPES = (
    "CHARACTER_FINALIZE", "ENVIRONMENT_PREPARE", "WORLD_PREPARE", "VISUAL_NARRATIVE_PREPARE",
)

# Scopes are intentionally disjoint: the commit layer fails closed if this
# invariant is ever changed by a caller or an externally returned candidate.
#
# "step" is the canonical DAG step name for the task. It lives here, beside the
# task type it belongs to, because building that name anywhere else is what broke
# PREIMAGE: producers concatenated "PREIMAGE_" + task_type and invented
# PREIMAGE_ENVIRONMENT_PREPARE / WORLD_PREPARE / VISUAL_NARRATIVE_PREPARE, names
# no registry has ever held. Every registry (config/index.yaml stage_read_sets,
# scoped_codex_worker.STEP_DIRECTIVES, runtime_node_registry executors) already
# agrees on the suffix-less form, so the suffix-less form is canonical -- the
# task type keeps its _PREPARE suffix because task state and task-results files
# are keyed on it.
TASK_SPECS = {
    "CHARACTER_FINALIZE": {
        "step": "PREIMAGE_CHARACTER_FINALIZE",
        "node_id": "character_finalize", "candidate": "character-finalize.json",
        "scope": ("character.finalize",),
        "required_read": ("meta/story-gates.json", "meta/character-contract.json", "meta/character-visual-contract.json"),
    },
    "ENVIRONMENT_PREPARE": {
        "step": "PREIMAGE_ENVIRONMENT",
        "node_id": "environment_prepare", "candidate": "environment.json",
        "scope": ("visual.environment_contract", "visual.frame_directives"),
        "required_read": ("meta/story-gates.json", "meta/story-semantic-review.json"),
    },
    "WORLD_PREPARE": {
        "step": "PREIMAGE_WORLD",
        "node_id": "world_prepare", "candidate": "world.json",
        "scope": ("visual.world_identity", "visual.world_state", "visual.temporal_continuity", "visual.wardrobe"),
        "required_read": ("meta/story-gates.json", "meta/world-identity.json", "meta/character-contract.json"),
    },
    "VISUAL_NARRATIVE_PREPARE": {
        "step": "PREIMAGE_VISUAL_NARRATIVE",
        "node_id": "visual_narrative_prepare", "candidate": "visual-narrative.json",
        "scope": ("visual.narrative_core", "visual.shot_progression", "visual.capture_grammar"),
        "required_read": ("meta/story-gates.json", "meta/shot-progression-review.json"),
    },
}


AUTHORITY_INPUT_LOADERS = {
    "meta/character-contract.json": lambda ep: character_contract.load(ep),
    "meta/character-visual-contract.json": lambda ep: character_visual_contract.load(ep),
    "meta/story-semantic-review.json": lambda ep: review_record_persistence.load_latest(
        ep,
        "STORY_SEMANTIC",
        legacy_path=Path(ep).resolve() / "meta/story-semantic-review.json",
    ),
}


def _step_index() -> dict[str, str]:
    """step -> task_type, built with a collision check.

    A plain comprehension would silently drop a duplicate step, and a duplicate
    means two tasks writing one capsule -- exactly the class of drift this index
    exists to prevent. Fail at import instead.
    """
    index: dict[str, str] = {}
    for task_type, spec in TASK_SPECS.items():
        step = spec["step"]
        if step in index:
            raise ValueError(f"duplicate canonical PREIMAGE step {step}: {index[step]} and {task_type}")
        index[step] = task_type
    return index


STEP_TO_TASK_TYPE = _step_index()
PREIMAGE_STEPS = tuple(spec["step"] for spec in TASK_SPECS.values())


def canonical_step(task_type: str) -> str:
    """The registered DAG step name for a task type. Never build this by hand."""
    spec = TASK_SPECS.get(task_type)
    if spec is None:
        raise ValueError(f"unsupported PREIMAGE task type: {task_type}")
    return spec["step"]


def task_type_for_step(step: str) -> str | None:
    """Inverse of :func:`canonical_step`, or None for a non-PREIMAGE-task step."""
    return STEP_TO_TASK_TYPE.get(step)


def registry_mismatches(
    *,
    stage_read_sets: dict,
    step_directives: dict,
    executor_steps=frozenset(),
) -> list[str]:
    """Registration gaps for every PREIMAGE task, as readable strings.

    Both lookups below are hard gates at runtime -- ``execution_capsule`` raises
    on an unknown step and ``scoped_codex_worker`` raises on an unregistered one
    -- but they are only reached after the PREIMAGE fan-out has already spent
    the host's time. These same conditions are knowable at start-up, which is
    where the answer belongs.
    """
    errors: list[str] = []
    for task_type, spec in TASK_SPECS.items():
        step = spec["step"]
        if step not in stage_read_sets:
            errors.append(f"{task_type}: {step} missing from stage_read_sets")
        if step not in step_directives:
            errors.append(f"{task_type}: {step} missing from STEP_DIRECTIVES")
        if executor_steps and step not in executor_steps:
            errors.append(f"{task_type}: {step} missing from the node registry executors")
    return errors


def assert_registries_aligned() -> None:
    """Fail before PREIMAGE work starts, not 20 minutes into it.

    Imports are lazy: ``scoped_codex_worker`` imports ``product_runtime_adapter``,
    which imports this module, so a module-level import would be a cycle.
    """
    import runtime_node_registry
    import scoped_codex_worker
    import storyos_config

    errors = registry_mismatches(
        stage_read_sets=storyos_config.load_index().get("stage_read_sets") or {},
        step_directives=scoped_codex_worker.STEP_DIRECTIVES,
        executor_steps=frozenset(
            n.get("executor") for n in runtime_node_registry.first_batch_nodes()
        ),
    )
    if errors:
        raise ValueError("PREIMAGE task registry drift: " + "; ".join(errors))


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def sha(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def candidate_path(ep: Path, task_type: str) -> Path:
    return Path(ep) / CANDIDATE_REL / TASK_SPECS[task_type]["candidate"]


def _state(ep: Path) -> dict:
    return story_json.read_json(Path(ep) / STATE_REL, default={}) or {}


def _state_base(snapshot_id: str) -> dict:
    return {
        "schema_version": 1,
        "snapshot_id": snapshot_id,
        "not_episode_stage": True,
        "not_gate_authority": True,
        "canonical_stage_source": "meta/episode-state.json",
        "tasks": {},
        "updated_at": now(),
    }


def task_contract(ep: Path, task_type: str, snapshot: dict, *, resume: bool = False) -> dict:
    if task_type not in TASK_SPECS:
        raise ValueError(f"unsupported PREIMAGE task type: {task_type}")
    spec = TASK_SPECS[task_type]
    out = candidate_path(ep, task_type)
    request = runtime_request.authority_for_episode(Path(ep).resolve()) or {}
    required_read = []
    authority_inputs = {}
    for rel in spec["required_read"]:
        if rel == runtime_request.EPISODE_REL.as_posix():
            continue
        loader = AUTHORITY_INPUT_LOADERS.get(rel)
        if loader is None:
            required_read.append(rel)
        else:
            authority_inputs[rel] = loader(Path(ep).resolve())
    return {
        "schema_version": 1,
        "task_id": f"preimage-{task_type.lower()}-{snapshot['snapshot_id'][:12]}",
        "task_type": task_type,
        "node_id": spec["node_id"],
        "episode": str(Path(ep).resolve()),
        "snapshot_id": snapshot["snapshot_id"],
        "depends_on": ["story_lock"],
        "required_read": required_read,
        "input_contract": {
            "source_authority_sha256": dict(snapshot.get("authority_sha256") or {}),
            "runtime_request_preimage": runtime_request.preimage_authority_projection(request),
            "authority_inputs": authority_inputs,
        },
        "candidate_output": out.relative_to(Path(ep)).as_posix(),
        "verifier": f"verify_{task_type.lower()}_candidate",
        "retry_policy": {"retry_failed_only": True, "stale_requires_new_snapshot": True},
        "authority_scope": list(spec["scope"]),
        "target": "candidate_only_no_shared_authority_write",
        "candidate_schema_version": 1,
        "execution_topology": "parallel_safe",
        "routing_policy": "fixed",
        "review_policy": "none",
        "control_policy": "supervised",
        "capability_requirements": ["reasoning", "filesystem"],
        "execution_budget": {"max_rounds": 1, "max_tokens": None, "timeout_seconds": 900},
        "status": "PENDING",
        "resume": bool(resume),
    }


def validate_patch_scopes(tasks: list[dict]) -> None:
    seen: dict[str, str] = {}
    for task in tasks:
        for scope in task.get("authority_scope") or []:
            if scope in seen:
                raise ValueError(f"PREIMAGE authority scope collision: {scope} ({seen[scope]}, {task.get('task_id')})")
            seen[scope] = str(task.get("task_id"))


def model_execution_evidence(candidate: dict) -> dict:
    """Normalize optional model execution telemetry without inventing missing data."""
    raw = candidate.get("model_execution") if isinstance(candidate, dict) else None
    raw = dict(raw) if isinstance(raw, dict) else {}
    errors=[]
    if raw.get("real_model_execution") is not True:
        errors.append("real_model_execution must be true")
    wall=raw.get("wall_seconds")
    if not isinstance(wall,(int,float)) or isinstance(wall,bool) or float(wall)<0:
        errors.append("wall_seconds must be a non-negative number")
    for key in ("input_tokens","output_tokens","repeated_reads"):
        value=raw.get(key)
        if type(value) is not int or value<0:
            errors.append(f"{key} must be a non-negative int")
    for key in ("failure","timeout"):
        if not isinstance(raw.get(key),bool):
            errors.append(f"{key} must be a bool")
    return {
        "schema_version":1,
        "complete":not errors,
        "errors":errors,
        "real_model_execution":raw.get("real_model_execution") is True,
        "wall_seconds":float(wall) if isinstance(wall,(int,float)) and not isinstance(wall,bool) and float(wall)>=0 else None,
        "input_tokens":raw.get("input_tokens") if type(raw.get("input_tokens")) is int and raw.get("input_tokens")>=0 else None,
        "output_tokens":raw.get("output_tokens") if type(raw.get("output_tokens")) is int and raw.get("output_tokens")>=0 else None,
        "repeated_reads":raw.get("repeated_reads") if type(raw.get("repeated_reads")) is int and raw.get("repeated_reads")>=0 else None,
        "failure":raw.get("failure") if isinstance(raw.get("failure"),bool) else None,
        "timeout":raw.get("timeout") if isinstance(raw.get("timeout"),bool) else None,
        "provider":raw.get("provider"),
        "model":raw.get("model"),
        "telemetry_source":raw.get("telemetry_source"),
    }


def verify_candidate(candidate: dict, task: dict) -> list[str]:
    errors: list[str] = []
    for key in ("schema_version", "task_id", "task_type", "snapshot_id", "source_authority_sha256", "generated_at", "status", "payload"):
        if key not in candidate:
            errors.append(f"candidate missing {key}")
    if candidate.get("task_id") != task.get("task_id"):
        errors.append("candidate task_id mismatch")
    if candidate.get("task_type") != task.get("task_type"):
        errors.append("candidate task_type mismatch")
    if candidate.get("snapshot_id") != task.get("snapshot_id"):
        errors.append("candidate snapshot_id mismatch")
    if candidate.get("source_authority_sha256") != task.get("input_contract", {}).get("source_authority_sha256"):
        errors.append("candidate source authority SHA mismatch")
    if candidate.get("status") != "COMPLETED":
        errors.append("candidate status must be COMPLETED")
    if not isinstance(candidate.get("payload"), dict) or not candidate.get("payload"):
        errors.append("candidate payload must be a non-empty object")
    if set(candidate.get("authority_scope") or []) != set(task.get("authority_scope") or []):
        errors.append("candidate authority scope mismatch")
    expected=set(task.get("authority_scope") or [])
    actual=set((candidate.get("payload") or {}).keys()) if isinstance(candidate.get("payload"),dict) else set()
    if actual != expected:
        errors.append("candidate payload keys must exactly match declared authority scopes")
    for scope in expected:
        if not isinstance((candidate.get("payload") or {}).get(scope),dict) or not candidate["payload"][scope]:
            errors.append(f"candidate payload scope must be a non-empty object: {scope}")
    verifier=globals().get(str(task.get("verifier") or ""))
    if not callable(verifier): errors.append("candidate verifier missing")
    elif not errors: errors.extend(verifier(candidate,task))
    return errors

def verify_character_finalize_candidate(candidate: dict, task: dict) -> list[str]:
    value=candidate["payload"]["character.finalize"]
    keys={"character","identity","pov","appearance"}
    return [] if any(value.get(key) not in (None,"",{},[]) for key in keys) else ["character candidate requires character/identity/pov/appearance"]

def verify_environment_prepare_candidate(candidate: dict, task: dict) -> list[str]:
    """Reject environment candidates that would fail immediately after commit."""
    env=candidate["payload"]["visual.environment_contract"]
    directives=candidate["payload"]["visual.frame_directives"]
    errors=[]
    if not isinstance(env.get("baseline"),dict) or not env["baseline"]:
        errors.append("environment candidate requires non-empty baseline")
    if not directives:
        errors.append("environment candidate requires frame directives")
    if errors:
        return errors
    try:
        import environment_contract
        ep=Path(str(task.get("episode") or ""))
        try:
            total=environment_contract.frame_count(ep)
        except (FileNotFoundError, KeyError, ValueError):
            # Protocol-only fixtures may intentionally omit release-manifest;
            # production Episodes must still have it before Frame Contract compile.
            # Derive only the validation horizon from the candidate's own directive
            # keys so semantic consistency is still checked instead of bypassed.
            frame_keys=[]
            for raw in directives:
                try: frame_keys.append(int(str(raw)))
                except (TypeError, ValueError): pass
            total=max(frame_keys) if frame_keys else 1
        errors.extend(environment_contract.validate_environment(env,total))
        errors.extend(environment_contract.validate_directives(ep,directives,total))
        errors.extend(environment_contract.validate_effective_consistency(ep,env,directives,total))
    except Exception as exc:
        errors.append(f"environment candidate validation failed: {exc}")
    return errors

def _applicable_object(value: dict) -> bool:
    return value.get("applicable") is False or bool(value)

def verify_world_prepare_candidate(candidate: dict, task: dict) -> list[str]:
    return [f"world candidate invalid: {scope}" for scope,value in candidate["payload"].items() if not _applicable_object(value)]

def verify_visual_narrative_prepare_candidate(candidate: dict, task: dict) -> list[str]:
    return [f"visual narrative candidate invalid: {scope}" for scope,value in candidate["payload"].items() if not value]

def valid_payload(task: dict) -> dict:
    """Explicit contract-shaped fixture/host template; never used by validation."""
    kind=task["task_type"]
    if kind=="CHARACTER_FINALIZE": return {"character.finalize":{"character":"locked","identity":"stable","pov":"first_person","appearance":"textual_anchor"}}
    if kind=="ENVIRONMENT_PREPARE":
        ep=Path(str(task.get("episode") or ""))
        total=1
        try:
            import environment_contract
            total=environment_contract.frame_count(ep)
        except Exception:
            pass
        directives={}
        for frame in range(1,total+1):
            directives[f"{frame:02d}"]={
                "narrative_role":"setup",
                "frame_mode":"normal_record",
                "impact_level":0,
                "required_visual_cues":[],
                "scale_reference":"",
                "escalation_from":None,
            }
        return {
            "visual.environment_contract":{
                "schema_version":1,
                "season":"stable",
                "baseline":{
                    "condition":"clear morning",
                    "time_of_day":"morning",
                    "ground_state":"dry",
                    "visibility":"clear",
                    "physical_cues":["ordinary morning daylight"],
                },
                "segments":[],
                "frame_overrides":{},
            },
            "visual.frame_directives":directives,
        }
    if kind=="WORLD_PREPARE": return {scope:{"applicable":False} for scope in task["authority_scope"]}
    return {scope:{"rule":"candidate"} for scope in task["authority_scope"]}


def read_candidate(ep: Path, task: dict) -> dict | None:
    path = Path(ep) / task["candidate_output"]
    data = story_json.read_json(path, default=None)
    return data if isinstance(data, dict) else None


def write_candidate(ep: Path, task: dict, candidate: dict) -> list[str]:
    errors = verify_candidate(candidate, task)
    if errors:
        return errors
    story_json.write_json(Path(ep) / task["candidate_output"], candidate)
    return []


def update_task_state(ep: Path, task: dict, status: str, *, request_id: str | None = None,
                      candidate_file: str | None = None, reason: str | None = None,
                      execution: dict | None = None) -> dict:
    path = Path(ep) / STATE_REL
    def mutate(current: dict) -> dict:
        if not current or current.get("snapshot_id") != task["snapshot_id"]:
            current.clear(); current.update(_state_base(task["snapshot_id"]))
        current["updated_at"] = now()
        row = dict(current.setdefault("tasks", {}).get(task["task_type"]) or {})
        row.update({"task_id": task["task_id"], "status": status, "request_id": request_id or row.get("request_id"),
                    "candidate_path": candidate_file or task["candidate_output"], "updated_at": now()})
        if reason: row["reason"] = reason
        if execution:
            current_execution = dict(row.get("execution") or {})
            current_execution.update({k: v for k, v in execution.items() if v is not None})
            row["execution"] = current_execution
        current["tasks"][task["task_type"]] = row
        return dict(current)
    return atomic.update_json(path, lambda: _state_base(task["snapshot_id"]), mutate)


def plan_tasks(ep: Path, snapshot: dict, *, resume: bool = False) -> list[dict]:
    state = _state(ep)
    tasks = [task_contract(ep, kind, snapshot, resume=resume) for kind in TASK_TYPES]
    validate_patch_scopes(tasks)
    for task in tasks:
        candidate = read_candidate(ep, task)
        row = ((state.get("tasks") or {}).get(task["task_type"]) or {}) if state.get("snapshot_id") == snapshot["snapshot_id"] else {}
        if candidate and not verify_candidate(candidate, task) and row.get("status") in {"COMPLETED", "REUSED"}:
            task["status"] = "REUSED"
        elif row.get("status") == "FAILED" and resume:
            task["status"] = "RETRY"
        elif row.get("status") == "STALE":
            task["status"] = "STALE"
    return tasks



def seal_scoped_native_candidate(ep: Path, task: dict, model_log: str | Path, *,
                                 log_start_offset: int = 0, log_end_offset: int | None = None,
                                 expected_candidate_sha256: str | None = None) -> dict:
    """Bind all *Host-owned* Candidate metadata to verified model-authored payload.

    A scoped model is allowed to author only task-owned payload. It must not be
    entrusted to transcribe 64-character input hashes into the final Candidate.
    This function is invoked only after the CLI returned zero and its real JSONL
    has a completed turn. It saves the model-authored bytes as an immutable
    diagnostic before writing a Host-bound candidate; it never repairs an
    incomplete semantic payload, forces an outcome, or fabricates telemetry.
    """
    import copy
    import agent_shadow_compare

    ep = Path(ep).resolve()
    log = Path(model_log).resolve()
    expected_log = (ep / "meta/scoped-workers").resolve()
    if not log.is_file() or not log.is_relative_to(expected_log):
        return {"status": "REFUSED", "errors": ["native model log outside declared scoped-worker evidence"]}
    end = log.stat().st_size if log_end_offset is None else log_end_offset
    if (type(log_start_offset) is not int or type(end) is not int
            or not 0 <= log_start_offset < end <= log.stat().st_size):
        return {"status": "REFUSED", "errors": ["native model log slice is not within the file"]}
    # The scoped worker uses append-only JSONL across retries. Only this
    # dispatch's new bytes may prove its completion; old successful turns
    # must never stand in for the latest invocation.
    with log.open("rb") as reader:
        reader.seek(log_start_offset)
        current_log_bytes = reader.read(end - log_start_offset)
    events = []
    for line in current_log_bytes.decode("utf-8", "replace").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            events.append(event)
    if (sum(e.get("type") == "thread.started" for e in events) != 1
            or sum(e.get("type") == "turn.completed" for e in events) != 1
            or any(e.get("type") == "turn.failed" for e in events)):
        return {"status": "REFUSED", "errors": ["native Codex completed-turn proof missing or ambiguous"]}
    p = candidate_path(ep, task["task_type"])
    if not p.is_file():
        return {"status": "REFUSED", "errors": ["scoped model did not write a Candidate"]}
    original = p.read_bytes()
    before = hashlib.sha256(original).hexdigest()
    if expected_candidate_sha256 is not None and expected_candidate_sha256 != before:
        return {"status": "REFUSED", "errors": ["candidate SHA changed after recovery proof"]}
    model_candidate = story_json.read_json(p, default=None)
    if not isinstance(model_candidate, dict):
        return {"status": "REFUSED", "errors": ["model Candidate is not a JSON object"]}
    # The model must still bind the correct immutable task/snapshot and own
    # only the declared semantic payload. Host-owned metadata can be omitted,
    # but if the model supplied identity/scope/status it must not conflict.
    if (model_candidate.get("task_id") != task["task_id"]
            or model_candidate.get("task_type") != task["task_type"]
            or model_candidate.get("snapshot_id") != task["snapshot_id"]
            or model_candidate.get("schema_version", 1) != 1
            or ("node_id" in model_candidate
                and model_candidate["node_id"] != task.get("node_id"))
            or ("authority_scope" in model_candidate
                and (not isinstance(model_candidate["authority_scope"], list)
                     or set(model_candidate["authority_scope"]) != set(task["authority_scope"])))
            or model_candidate.get("status", "COMPLETED") != "COMPLETED"):
        return {"status": "REFUSED", "errors": ["model Candidate task, snapshot, or supplied host metadata mismatch"]}
    sealed = copy.deepcopy(model_candidate)
    sealed.setdefault("schema_version", 1)
    sealed["authority_scope"] = list(task["authority_scope"])
    sealed["source_authority_sha256"] = copy.deepcopy(
        task["input_contract"]["source_authority_sha256"]
    )
    # generated_at is the Host's confirmed sealing time, not fabricated
    # retrospective model timing. The real turn/receipt keeps its own clock.
    sealed["generated_at"] = now()
    sealed["status"] = "COMPLETED"
    errors = verify_candidate(sealed, task)
    if errors:
        return {"status": "REFUSED", "errors": errors}
    # Independent domain semantics use the actual frozen Host obligations.
    # No blanket acceptance of a structurally well-formed World/Visual payload.
    kind = task["task_type"]
    if kind == "CHARACTER_FINALIZE":
        semantic = agent_shadow_compare.compare_character_finalize_semantics(task, sealed)
    elif kind == "WORLD_PREPARE":
        from agents import world_prepare_model_producer
        frozen = world_prepare_model_producer.freeze_task(ep, task)
        semantic = agent_shadow_compare.compare_world_prepare_semantics(frozen, sealed)
    elif kind == "VISUAL_NARRATIVE_PREPARE":
        from agents import visual_narrative_prepare_model_producer
        frozen = visual_narrative_prepare_model_producer.freeze_task(ep, task)
        if not visual_narrative_prepare_model_producer.frozen_sources_unchanged(ep, frozen):
            return {"status": "REFUSED", "errors": ["frozen Visual sources changed"]}
        semantic = agent_shadow_compare.compare_visual_narrative_semantics(frozen, sealed)
    else:
        semantic = {"pass": True, "errors": []}
    if semantic.get("pass") is not True:
        return {"status": "REFUSED", "errors": semantic.get("errors") or ["domain semantic contract failed"]}
    # Write a separate raw model artifact and proof BEFORE replacing any
    # Candidate. Old failed candidates are not touched by this path.
    if not isinstance(sealed.get("evidence", []), list):
        return {"status": "REFUSED", "errors": ["model Candidate evidence is not a list"]}
    recovery = ep / "meta/runtime/native-host-envelope-archive" / (
        str(task["task_id"]) + "-" + str(before) + ".json"
    )
    recovery.parent.mkdir(parents=True, exist_ok=True)
    with recovery.open("xb") as h:
        h.write(original)
    provenance = {
        "mode": "host_bound_scoped_native_candidate",
        "original_candidate_sha256": before,
        "original_candidate_path": recovery.relative_to(ep).as_posix(),
        "native_model_log_sha256": hashlib.sha256(current_log_bytes).hexdigest(),
        "native_model_log_start_offset": log_start_offset,
        "native_model_log_end_offset": end,
        "host_sealed_at": sealed["generated_at"],
        "host_bound_fields": ["generated_at", "status", "authority_scope", "source_authority_sha256"],
        "source_authority_digest_origin": "trusted_preimage_input_snapshot",
        "model_turn_completed": True,
        "authoritative_payload_unchanged": sealed.get("payload") == model_candidate.get("payload"),
    }
    sealed.setdefault("evidence", [])
    if not isinstance(sealed["evidence"], list):
        return {"status": "REFUSED", "errors": ["model Candidate evidence is not a list"]}
    sealed["evidence"].append(provenance)
    # Never fill unavailable token counts / elapsed seconds with guesses.
    if sha(p) != before:
        return {"status": "REFUSED", "errors": ["Candidate changed during Host sealing"]}
    story_json.write_json(p, sealed)
    return {"status": "PASS", "original_candidate_sha256": before,
            "sealed_candidate_sha256": sha(p), "proof": provenance}


def candidate_template(task: dict, payload: dict) -> dict:
    """Helper for host integrations/tests; callers supply independently created payload."""
    return {
        "schema_version": 1, "task_id": task["task_id"], "task_type": task["task_type"],
        "snapshot_id": task["snapshot_id"], "source_authority_sha256": task["input_contract"]["source_authority_sha256"],
        "generated_at": now(), "status": "COMPLETED", "payload": payload,
        "authority_scope": list(task["authority_scope"]), "evidence": [], "verification": {"gate_pass": None},
        "model_execution": {"independent_task": True},
    }
