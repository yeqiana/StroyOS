#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Story OS shared production-queue / ledger primitives (B0).

image_scheduler (single-frame first-completed lane) and batch_scheduler
(5-frame logical batch lane) manage the same queue document under the same
OS advisory lock.  This module is the single implementation source for those
queue/ledger primitives; it does NOT merge the two scheduler main loops.

Lane policy stays with the consumer for B0/B1:
- dependency_satisfied: generic ledger/queue check.  Visual Lock baseline
  approval remains an image_scheduler lane rule passed by the caller.
- ready_items: generic scan; the batch lane filters scope=="batch" itself.
- ledger_begin notes are consumer-supplied so existing ledger text is kept.
"""
from __future__ import annotations

import datetime as dt
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

import production_queue_store
import hot_state_bridge

ROOT = Path(__file__).resolve().parents[2]
QUEUE_REL = production_queue_store.REL
SCHEDULER_LOCK_REL = Path("meta/runtime-image-scheduler.lock")
EMPTY_QUEUE = {"schema_version": 1, "items": [], "waves": []}
_QUEUE_LOCK_LOCAL = threading.local()


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


async def run_execution_loop(tasks, handler, consume, *, workers,
                             admit=None, completed=None, dispatched=None):
    """Single execution owner; lane callbacks own admission and ledger policy.

    A fixed task list is a batch barrier. Dynamic admission may unlock new
    dependencies after consumption. Technical failures lower this run's cap;
    two consecutive successes restore one slot. The next run starts at its
    configured limit. All callbacks execute serially.
    """
    import asyncio
    from async_task_runtime import AsyncTaskRuntime

    workers = max(1, min(5, int(workers)))
    pending = list(tasks)
    async def fixed_admit(limit):
        rows = pending[:limit]
        del pending[:limit]
        return rows
    admission = admit or fixed_admit
    pool = AsyncTaskRuntime(workers=workers)
    events = asyncio.Queue()
    runner = asyncio.create_task(pool.run(events.put))
    inflight = 0
    cap = workers
    consecutive_successes = 0
    seen = set()
    try:
        while True:
            for row in await admission(max(0, cap - inflight)):
                key = str(row['id'])
                if key in seen:
                    raise ValueError(f'duplicate scheduler dispatch: {key}')
                seen.add(key)
                await pool.submit(row, handler)
                inflight += 1
                if dispatched:
                    await dispatched(row, inflight, cap)
            if not inflight:
                break
            event = await events.get()
            status = await consume(event)
            inflight -= 1
            if status == 'tech_failed':
                cap = max(1, cap - 1)
                consecutive_successes = 0
            elif status in {'success', 'generated'}:
                consecutive_successes += 1
                if consecutive_successes >= 2:
                    cap = min(workers, cap + 1)
                    consecutive_successes = 0
            else:
                consecutive_successes = 0
            if completed:
                await completed(event, status, inflight, cap)
        await pool.queue.join()
    finally:
        # Drain submitted work before releasing resources, including on a
        # consumer exception. Never stop workers with pending queue entries.
        await pool.queue.join()
        await pool.stop()
        runner.cancel()
        await asyncio.gather(runner, return_exceptions=True)


def read_json(path: Path) -> dict:
    import story_json

    data = story_json.read_json(path)
    if not isinstance(data, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return data


def write_json(path: Path, data: dict) -> None:
    import story_json

    story_json.write_json(path, data)


def empty_queue(*, max_parallel: int | None = None) -> dict:
    """Fresh queue document shared by both lanes."""
    q = {"schema_version": 1, "created_at": now(), "updated_at": now(),
         "items": [], "waves": []}
    if max_parallel is not None:
        q["max_parallel"] = int(max_parallel)
    return q


def queue_read_path(ep: Path) -> Path:
    return production_queue_store.read_path(Path(ep).resolve())


def queue_write_path(ep: Path) -> Path:
    return production_queue_store.write_path(Path(ep).resolve())


def load_queue(ep: Path, *, max_parallel: int | None = None) -> dict:
    """Read production queue with the portability path guard.

    Missing file returns EMPTY_QUEUE (same semantics as both scheduler lanes'
    private copies).
    """
    ep = Path(ep).resolve()
    hot = hot_state_bridge.read(ep, "QUEUE")
    q = hot.get("value") if isinstance(hot.get("value"), dict) else None
    if q is None and not hot_state_bridge.file_fallback_allowed(hot):
        q = dict(EMPTY_QUEUE)
        if max_parallel is not None:
            q["max_parallel"] = int(max_parallel)
    elif q is None:
        p = production_queue_store.read_path(ep)
        if not p.is_file():
            q = dict(EMPTY_QUEUE)
            if max_parallel is not None:
                q["max_parallel"] = int(max_parallel)
            return q
        q = read_json(p)
    import runtime_portability

    errors = runtime_portability.queue_path_errors(q)
    if errors:
        raise ValueError("production queue portability guard failed: "
                         + "; ".join(errors[:8]))
    return q


def save_queue(ep: Path, q: dict) -> None:
    ep = Path(ep).resolve()
    import episode_lifecycle
    episode_lifecycle.assert_writable(ep, "production_queue.write")
    with queue_transaction(ep):
        q["updated_at"] = now()
        import storage_config
        current_mode = storage_config.hot_state_config()["mode"]
        # Redis-only means Redis is the sole queue authority. File/workspace
        # writes are retained only for file/dual compatibility modes.
        if current_mode != "redis":
            write_json(production_queue_store.write_path(ep), q)
        hot_state_bridge.mirror(ep, "QUEUE", q)


def progress(ep: Path, q: dict, *, requested_workers: int = 5) -> dict:
    """Read-only common interpretation; historical caps never control a run."""
    import storyos_config
    import raw_candidate_budget
    import story_json
    import episode_state_persistence
    configured = min(5, int(storyos_config.get_path(storyos_config.load_config(),
                                                  "production.max_inflight_images")))
    rows = list((ledger(ep).get("frames") or {}).values())
    pending = sum(x.get("status") == "queued" for x in q.get("items") or [])
    stage = episode_state_persistence.load(ep) or {}
    manifest = story_json.read_json(ep / "meta/release-manifest.json", default={})
    last = next((w for w in reversed(q.get("waves") or []) if "inflight_after" in w), {})
    return {
        "configured_limit": configured,
        "next_run_limit": max(1, min(configured, requested_workers)),
        "last_reported_inflight": last.get("inflight_after", 0),
        "last_run_effective_limit": last.get("next_parallel"),
        "historical_adaptive_parallel": q.get("adaptive_parallel"),
        "adaptive_parallel_semantics": "history_only",
        "generated_frames": sum(any(a.get("result") == "success" for a in r.get("attempts") or []) for r in rows),
        "content_passed_frames": sum(r.get("status") in {"PASSED", "WEAK_PASS", "LOCKED"} for r in rows),
        "pending_review_frames": sum(r.get("status") in {"ORIGINAL_READY", "REPAIR_READY"} for r in rows),
        "pending_decision_frames": sum(r.get("status") == "NEEDS_USER" for r in rows),
        "canonical_stage": stage.get("current_state"),
        "formal_gates": manifest.get("quality") or {},
        "publication": manifest.get("publication") or {},
        "budget": raw_candidate_budget.summary(ep, pending=pending),
    }


class QueueMutationBusy(RuntimeError):
    """A queue writer raced an active scheduler or another writer."""


@contextmanager
def queue_transaction(ep: Path):
    """Serialize queue read-modify-write against image execution.

    The OS advisory lock remains the cross-thread/process authority.  A
    thread-local depth makes the lock re-entrant only for the same Episode in
    the same thread, allowing central ``save_queue`` to protect every write
    without deadlocking callers that already own a queue transaction.
    """
    import runner_state_store

    ep = Path(ep).resolve()
    key = ep.as_posix()
    depths = getattr(_QUEUE_LOCK_LOCAL, "depths", None)
    if depths is None:
        depths = {}
        _QUEUE_LOCK_LOCAL.depths = depths
    depth = int(depths.get(key) or 0)
    if depth:
        depths[key] = depth + 1
        try:
            yield
        finally:
            remaining = int(depths.get(key) or 1) - 1
            if remaining > 0:
                depths[key] = remaining
            else:
                depths.pop(key, None)
        return

    if not runner_state_store.acquire_lock(ep, lock_rel=SCHEDULER_LOCK_REL):
        raise QueueMutationBusy("QUEUE_MUTATION_BUSY: image scheduler owns "
                                "the production queue; retry later")
    depths[key] = 1
    try:
        yield
    finally:
        depths.pop(key, None)
        runner_state_store.release_lock(ep, lock_rel=SCHEDULER_LOCK_REL)


def ledger(ep: Path) -> dict:
    from production_ledger_core import load_authority
    data = load_authority(Path(ep).resolve(), default={})
    return data if isinstance(data, dict) else {}


def ledger_state(ep: Path, frame: int) -> str:
    return str((((ledger(ep).get("frames") or {}).get(f"{frame:02d}") or {})
                .get("status") or "PENDING"))


def terminalize_superseded_history(ep: Path, q: dict) -> list[dict]:
    """Mark only provably superseded technical queue history terminal.

    This mutates ``q`` in memory; callers must hold the scheduler lock and call
    ``save_queue``. Unknown history is deliberately left untouched.
    """
    frames = ledger(ep).get("frames") or {}
    items = q.get("items") or []
    changed: list[dict] = []
    for index, item in enumerate(items):
        if item.get("status") not in {"tech_failed", "blocked", "external_blocked", "interrupted_unknown"}:
            continue
        frame_no = int(item.get("frame") or 0)
        if frame_no <= 0:
            continue
        evidence = None
        # A retry can be re-enqueued with the default kind="original" after
        # the ledger has already authorized a repair. ledger_begin correctly
        # rejects that duplicate; once the matching repair row exists, preserve
        # the rejected row as terminal history instead of letting it hard-stop
        # the whole episode forever.
        expected_kind = "repair" if "technical retry must preserve attempt kind 'repair'" in str(item.get("last_error") or "").lower() else None
        if item.get("status") == "blocked" and expected_kind:
            for matching in items:
                if (matching is not item
                        and int(matching.get("frame") or 0) == frame_no
                        and str(matching.get("kind") or "") == expected_kind
                        and matching.get("status") in {"queued", "running", "generated", "tech_failed", "external_blocked"}):
                    evidence = {"type": "queue_item", "id": matching.get("id"), "reason": "ledger_rejected_wrong_attempt_kind"}
                    break
        for later in items[index + 1:]:
            if evidence is not None:
                break
            if int(later.get("frame") or 0) == frame_no and later.get("status") == "generated":
                evidence = {"type": "queue_item", "id": later.get("id")}
                break
        frame = frames.get(f"{frame_no:02d}") or frames.get(str(frame_no)) or {}
        if evidence is None and isinstance(frame, dict):
            current = frame.get("current_candidate") or {}
            accepted = next((row for row in reversed(frame.get("retry_exhaustion_acceptances") or [])
                             if row.get("user_authorized") is True
                             and row.get("candidate_sha256") == current.get("sha256")), None)
            if frame.get("status") == "PASSED" and accepted:
                evidence = {"type": "ledger_retry_exhaustion_acceptance", "candidate_sha256": accepted.get("candidate_sha256")}
            approved = frame.get("approved_asset")
            candidate = approved if isinstance(approved, dict) and approved.get("sha256") else current
            if evidence is None and isinstance(candidate, dict) and candidate.get("sha256"):
                failed_at = str(item.get("completed_at") or item.get("started_at") or item.get("queued_at") or "")
                recorded_at = str(candidate.get("recorded_at") or "")
                if not failed_at or not recorded_at or recorded_at >= failed_at:
                    evidence = {"type": "ledger_candidate", "sha256": candidate.get("sha256"), "recorded_at": recorded_at or None}
        if evidence is None:
            continue
        item["superseded_from_status"] = item.get("status")
        item["status"] = "superseded"
        item["superseded_at"] = now()
        item["superseded_by"] = evidence
        changed.append(item)
    return changed


def dependency_satisfied(ep: Path, q: dict, dep: int,
                         extra_ok: Callable[[int], bool] | None = None) -> bool:
    """True when ledger/queue show the dependency already produced.

    extra_ok lets the image lane add its Visual Lock baseline-approval rule
    without embedding lane policy here.
    """
    import production_ledger

    if extra_ok is not None and extra_ok(int(dep)):
        return True
    if ledger_state(ep, int(dep)) in production_ledger.READY_LEDGER_STATES:
        return True
    return any(int(x.get("frame") or 0) == int(dep)
               and x.get("status") == "generated"
               for x in q.get("items") or [])


def ready_items(ep: Path, q: dict, *, scope: str | None = None,
                extra_ok: Callable[[int], bool] | None = None) -> list[dict]:
    """Queued items whose generation_depends_on prerequisites are satisfied.

    Priority desc then frame asc matches the image lane; batch items without a
    priority field sort by frame only, preserving the batch lane order.
    """
    rows = []
    for item in q.get("items") or []:
        if item.get("status") != "queued":
            continue
        if scope is not None and str(item.get("scope") or "") != scope:
            continue
        deps = [int(x) for x in item.get("depends_on") or []]
        if all(dependency_satisfied(ep, q, x, extra_ok=extra_ok) for x in deps):
            rows.append(item)
    return sorted(rows,
                  key=lambda x: (-int(x.get("priority") or 0),
                                 int(x.get("frame") or 0)))


def current_contract_sha(ep: Path, frame: int) -> str:
    import frame_contract

    prov = frame_contract.provenance(ep, int(frame))
    if not prov:
        raise ValueError(f"frame {int(frame):02d} missing Frame Contract provenance")
    return str(prov["contract_sha256"])


def _prompt_path(item: dict) -> Path:
    raw = Path(str(item["prompt_file"]))
    return raw if raw.is_absolute() else (ROOT / raw).resolve()


def _ledger_references(item: dict) -> list[str]:
    # W-21: keep the declared anchor/id with the reference so production ledger
    # execution evidence stays attributable to one identity anchor.
    out = []
    for ref in item.get("references") or []:
        value = f"{(ROOT / ref['path']).resolve()}::{ref['role']}::{ref['kind']}"
        anchor = str(ref.get("anchor") or ref.get("id") or "").strip()
        if anchor:
            value = f"{value}::{anchor}"
        out.append(value)
    return out


def ledger_begin(ep: Path, item: dict, *, notes: str | None = None,
                 batch_id: str | None = None) -> tuple[bool, str]:
    import ledger_call
    import frame_contract
    import prompt_package

    approved_scene = None
    if item.get("ep14_active_package_id"):
        try:
            import hashlib
            import production_ep14_canonical_activation as active
            approved = active.load_for_dispatch(ep, item)
            approved_scene = approved.get("scene_prompt")
            expected = (item.get("prompt_package") or {}).get("scene_prompt_sha256")
            if (not isinstance(approved_scene, str) or not approved_scene.strip()
                    or hashlib.sha256(approved_scene.encode("utf-8")).hexdigest() != expected):
                return False, "EP14_REVIEWED_LEDGER_SCENE_SHA_NOT_AUTHORIZED"
        except Exception as exc:
            return False, "EP14_REVIEWED_LEDGER_BINDING_DENIED: " + type(exc).__name__
    elif frame_contract.required(ep):
        try:
            package = prompt_package.compile_frame(ep, int(item["frame"]), _prompt_path(item))
            queued_sha = (item.get("frame_contract") or {}).get("contract_sha256")
            if queued_sha != package["frame_contract_sha256"]:
                return False, "PROMPT_SOURCE_DRIFT: queue contract changed; rebuild derived queue item"
            frozen = item.get("prompt_package")
            if isinstance(frozen, dict) and frozen.get("scene_prompt_sha256"):
                # Admission-time freeze: whatever was queued must be exactly what
                # is about to be sent. This closes the first-package case (no
                # on-disk history to compare) and the simultaneous scene+contract
                # change case; prompt edits require re-admission (replace).
                if frozen.get("scene_prompt_sha256") != package["scene_prompt_sha256"]:
                    return False, "PROMPT_SOURCE_DRIFT: queue scene prompt changed after admission; rebuild queue item"
        except (ValueError, OSError) as exc:
            return False, str(exc)

    return ledger_call.begin(
        ep,
        frame=int(item["frame"]),
        kind=item["kind"],
        prompt_file=_prompt_path(item),
        capture_id=item["capture_id"],
        model=item.get("model") or "default",
        quality=item.get("quality") or "high",
        notes=notes or f"scheduler item={item.get('id')} scope={item.get('scope')}",
        references=_ledger_references(item),
        batch_id=batch_id,
        transaction_id=str((item.get("execution") or {}).get("transaction_id") or "")
        or None,
        production_revision_id=item.get("production_revision_id"),
        reviewed_scene_prompt=approved_scene,
    )


def ledger_success(ep: Path, item: dict, result: dict,
                   *, default_quality: str = "high") -> tuple[bool, str]:
    import ledger_call

    returned_policy = (result.get("payload") or {}).get("image_model") or {}
    requested_model = str(item.get("model") or "default")
    requested_quality = str(item.get("quality") or default_quality)
    if str(returned_policy.get("model") or "") != requested_model:
        return False, (f"IMAGE_MODEL_CONTRACT_MISMATCH: returned="
                       f"{returned_policy.get('model')} requested={requested_model}")
    if str(returned_policy.get("quality") or "") != requested_quality:
        return False, (f"IMAGE_QUALITY_CONTRACT_MISMATCH: returned="
                       f"{returned_policy.get('quality')} requested={requested_quality}")
    returned = ((result.get("payload") or {}).get("frame_contract") or {})
    returned_sha = returned.get("contract_sha256")
    current = current_contract_sha(ep, int(item["frame"]))
    if returned_sha and str(returned_sha).lower() != str(current).lower():
        return False, (f"backend frame contract drift returned={returned_sha} "
                       f"current={current}")
    receipt = ((result.get("payload") or {}).get("provider_receipt") or {})
    receipt_path = receipt.get("path")
    resolved = None
    if receipt_path:
        resolved = Path(str(receipt_path))
        if not resolved.is_absolute():
            resolved = ROOT / resolved
    budget = result.get("candidate_budget") if isinstance(result.get("candidate_budget"), dict) else {}
    authority = budget.get("authority") if isinstance(budget.get("authority"), dict) else {}
    generation_key = str(
        budget.get("generation_key") or authority.get("generation_key") or ""
    ).strip() or None
    attempt_index_raw = budget.get("attempt_index") or authority.get("attempt_index")
    generation_attempt_index = int(attempt_index_raw) if attempt_index_raw else None
    return ledger_call.success(ep, frame=int(item["frame"]),
                               path=Path(str(result["output"])),
                               provider_receipt=resolved,
                               generation_key=generation_key,
                               generation_attempt_index=generation_attempt_index,
                               production_revision_id=item.get("production_revision_id"))


def ledger_tech_fail(ep: Path, item: dict, code: str, message: str) -> None:
    import ledger_call

    runner_request_id = str(((item.get("execution") or {}).get("runner_request_id")) or "").strip() or None
    ledger_call.tech_fail(ep, frame=int(item["frame"]), code=code,
                          message=message, provider_invoked=bool(runner_request_id),
                          runner_request_id=runner_request_id)


def self_test() -> None:
    import tempfile

    with tempfile.TemporaryDirectory(prefix="scheduler core self test ") as td:
        ep = Path(td)
        assert load_queue(ep) == EMPTY_QUEUE
        q = empty_queue(max_parallel=5)
        save_queue(ep, q)
        assert load_queue(ep)["max_parallel"] == 5
        with queue_transaction(ep):
            assert load_queue(ep)["schema_version"] == 1
        with queue_transaction(ep):
            with queue_transaction(ep):
                save_queue(ep, load_queue(ep))
    print("SCHEDULER CORE SELF-TEST PASS")


if __name__ == "__main__":
    self_test()
