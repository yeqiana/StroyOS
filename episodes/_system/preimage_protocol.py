#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Commit and barrier for independently completed PREIMAGE candidates."""
from __future__ import annotations
import datetime as dt
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import authority_commit
import preimage_authority_snapshot
import preimage_task_contract as tasks
import runtime_atomic_store as atomic
import story_json

BARRIER_REL=Path("meta/runtime/preimage-authority-barrier.json")

def now(): return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")

def _patches(candidate: dict) -> list[tuple[str,dict]]:
    return [(scope, dict(candidate["payload"][scope])) for scope in candidate["authority_scope"]]

def commit_candidates(ep: Path, snapshot: dict, task_rows: list[dict], *, execution_contexts: list[dict] | None = None) -> dict:
    """Single orchestration path from candidates to committed Snapshot B.

    Each atomic patch compares the latest SHA. Any concurrent authority change
    returns STALE and stops the barrier; it is never overwritten.
    """
    tasks.validate_patch_scopes(task_rows)
    if preimage_authority_snapshot.stale_owned(ep, snapshot):
        return {"status":"STALE","reason":"owned authority scope changed","committed":False}
    candidates=[]; patches=[]
    for task in task_rows:
        candidate=tasks.read_candidate(ep,task)
        errors=tasks.verify_candidate(candidate or {},task)
        if errors: return {"status":"FAILED","reason":"; ".join(errors),"committed":False}
        candidates.append(candidate); patches.extend(_patches(candidate))
    scopes={scope for scope,_ in patches}
    result=authority_commit.commit_transaction(ep,"meta/story-gates.json",
        # The transaction compares exact on-disk bytes, unlike the snapshot's
        # newline-normalized text SHA. On Windows (CRLF), mixing them makes
        # every otherwise-valid PREIMAGE commit falsely STALE.
        expected_sha=authority_commit.sha(Path(ep)/"meta/story-gates.json"),
        authority_guard=lambda: not preimage_authority_snapshot.stale_owned(ep,snapshot),
        snapshot_id=snapshot["snapshot_id"],
        task_ids=[task["task_id"] for task in task_rows],node_ids=[task["node_id"] for task in task_rows],patches=patches,
        candidate_paths=[task["candidate_output"] for task in task_rows],
        preflight_validator=lambda: [err for task,candidate in zip(task_rows,candidates) for err in tasks.verify_candidate(candidate,task)],
        replace_existing_scopes=scopes,execution_contexts=execution_contexts)
    if result["status"] not in {"PASS","REPLAYED"}: return {"status":result["status"],"committed":False,"transaction":result}
    committed=preimage_authority_snapshot.build(ep,write=True,kind="PREIMAGE_COMMITTED_SNAPSHOT")
    barrier={"schema_version":1,"name":"PREIMAGE_AUTHORITY_READY","not_episode_stage":True,"not_gate_authority":True,
             "canonical_stage_source":"meta/episode-state.json","status":"READY","input_snapshot_id":snapshot["snapshot_id"],
             "committed_snapshot_id":committed["snapshot_id"],"created_at":now(),"commit_count":1}
    atomic.atomic_write_json(Path(ep)/BARRIER_REL,barrier)
    return {"status":"PASS","committed":True,"replayed":result["status"]=="REPLAYED","transaction":result,"committed_snapshot":committed,"barrier":barrier}

def barrier_ready(ep: Path) -> bool:
    row=story_json.read_json(Path(ep)/BARRIER_REL,default={}) or {}
    return row.get("status")=="READY" and bool(row.get("committed_snapshot_id"))

def execute_local(ep: Path, executor, *, max_workers: int = 4) -> dict:
    """Execute distinct local task invocations and then commit verified results.

    ``executor(task)`` is deliberately injected: production supplies one scoped
    worker invocation per task; tests supply a bounded fake worker.  Completion
    remains evidence/candidate based rather than scheduler asserted.
    """
    ep = Path(ep).resolve()
    # A previous atomic commit has already sealed all four PREIMAGE scopes.
    # Verify the exact committed ownership snapshot before dispatching any
    # model workers; the same READY barrier must not incur four more calls.
    barrier = story_json.read_json(ep / BARRIER_REL, default={}) or {}
    committed = story_json.read_json(
        ep / "meta/runtime/preimage-committed-snapshot.json", default={}
    ) or {}
    if barrier.get("status") == "READY" and barrier.get("committed_snapshot_id"):
        current = preimage_authority_snapshot.build(ep, write=False)
        if (committed.get("snapshot_kind") == "PREIMAGE_COMMITTED_SNAPSHOT"
                and committed.get("snapshot_id") == current.get("snapshot_id")
                == barrier["committed_snapshot_id"]
                and not preimage_authority_snapshot.stale_owned(ep, committed)):
            return {
                "status": "PASS", "recovery": "REUSED_VERIFIED_PREIMAGE_BARRIER",
                "observed_preimage_parallelism_peak": 0,
                "measurement_method": "verified_committed_snapshot_no_worker_dispatch",
                "test_evidence": False, "production_observed": False, "tasks": [],
            }

    source=preimage_authority_snapshot.build(ep,write=True,kind="PREIMAGE_INPUT_SNAPSHOT")
    rows=tasks.plan_tasks(ep,source,resume=True)
    # Retry only if the original model failed before producing a valid,
    # SHA-bound candidate. A bounded model can write the complete artifact and
    # then hang waiting for its transport to exit; audited recovery must preserve
    # the real TIMEOUT receipt rather than pay for that same content again.
    state=story_json.read_json(Path(ep)/tasks.STATE_REL,default={}) or {}
    has_timeout=any(
        isinstance(row,dict) and row.get("status")=="FAILED"
        and row.get("reason")=="worker rc=124"
        for row in (state.get("tasks") or {}).values())
    if has_timeout:
        import preimage_timeout_candidate_recovery as recovery
        proof=recovery.inspect(ep,source,rows)
        if proof.get("status")=="ELIGIBLE":
            if not recovery.recheck_unchanged(ep,proof):
                return {"status":"FAILED","reason":"candidate/receipt drift during timeout recovery",
                        "recovery":"REFUSED"}
            audit=Path(ep)/recovery.MANIFEST_REL
            audit.parent.mkdir(parents=True,exist_ok=True)
            atomic.atomic_write_json(audit,{"schema_version":1,"status":"VERIFIED_NOT_COMMITTED",
                "model_timeouts_preserved":True,"proof":proof})
            committed=commit_candidates(ep,source,rows)
            if committed.get("status") in {"PASS","REPLAYED"}:
                for task in rows:
                    entry=next(x for x in proof["tasks"] if x["task_type"]==task["task_type"])
                    if entry["was_timeout"]:
                        tasks.update_task_state(ep,task,"REUSED",
                            reason="recovered verified candidate; original model execution TIMEOUT")
                atomic.atomic_write_json(audit,{"schema_version":1,"status":"COMMITTED",
                    "model_timeouts_preserved":True,"proof":proof,
                    "commit_status":committed["status"]})
                return {"status":"PASS","recovery":"VERIFIED_TIMEOUT_CANDIDATES",
                        "observed_preimage_parallelism_peak":0,
                        "measurement_method":"reused_durable_candidate_no_model_dispatch",
                        "test_evidence":False,"production_observed":False,
                        "tasks":[{"task_type":row["task_type"],
                                  "status":"RECOVERED_CANDIDATE" if row["was_timeout"] else "REUSED",
                                  "model_execution_status":row["model_execution_status"]}
                                 for row in proof["tasks"]],
                        **committed}
            return {"status":"FAILED","reason":"candidate atomic commit failed",
                    "recovery":"REFUSED","transaction":committed}
        # If all candidates are already valid, another model dispatch is not
        # allowed to hide a missing or contradictory execution receipt.
        if all(not tasks.verify_candidate(tasks.read_candidate(ep,task) or {},task)
               for task in rows):
            return {"status":"FAILED","reason":"timeout candidate recovery refused: "+str(proof.get("reason")),
                    "recovery":"REFUSED"}
    pending=[x for x in rows if x["status"] != "REUSED"]
    import threading
    peak=0; active=0; metrics_lock=threading.Lock(); results=[]
    def call(task):
        nonlocal peak,active
        with metrics_lock:
            active += 1; peak=max(peak,active)
        try:
            tasks.update_task_state(ep,task,"RUNNING")
            return task,executor(task)
        finally:
            with metrics_lock: active -= 1
    with ThreadPoolExecutor(max_workers=min(max_workers,len(pending) or 1),thread_name_prefix="story-os-preimage") as pool:
        futures=[]
        for task in pending: futures.append(pool.submit(call,task))
        for future in as_completed(futures):
            task,value=future.result()
            candidate=tasks.read_candidate(ep,task)
            errors=tasks.verify_candidate(candidate or {},task)
            if value not in (0, None) or errors:
                tasks.update_task_state(ep,task,"FAILED",reason="; ".join(errors) or f"worker rc={value}")
                results.append({"task_type":task["task_type"],"status":"FAILED"})
            else:
                tasks.update_task_state(ep,task,"COMPLETED")
                results.append({"task_type":task["task_type"],"status":"COMPLETED"})
    if any(x["status"]=="FAILED" for x in results):
        return {"status":"FAILED","observed_preimage_parallelism_peak":peak,"measurement_method":"active_worker_enter_exit","test_evidence":False,"production_observed":False,"tasks":results}
    committed=commit_candidates(ep,source,rows)
    return {"status":committed["status"],"observed_preimage_parallelism_peak":peak,"measurement_method":"active_worker_enter_exit","test_evidence":False,"production_observed":False,"tasks":results,**committed}
