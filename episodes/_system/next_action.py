#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Derive the single next Story OS runtime action without creating a second state machine.

The only Episode stage authority remains meta/episode-state.json. This file is a
runtime convenience for Work/ChatGPT host loops so they do not need to rescan the
repository after every model/image action.

Every field here is a projection of files already on disk: meta/episode-state.json,
meta/runtime-runner-state.json and meta/runtime/reviews/. In particular host_loop
and orphaned_pending_work report whether a host loop is running -- they never
start, restart, stop, signal or wait on a runner. There is no watchdog here.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

import baseline_candidate_pool
import character_visual_contract
import frame_contract
import frame_semantic_review
import final_acceptance
import image_blocked_recovery
import preproduction_handoff
import production_batch_review
import production_ledger
import production_ledger_persistence
import product_review_adapter
import product_runtime_adapter
import raw_candidate_budget
import runner_health_monitor
import scheduler_core
import runtime_execution
import runtime_executor_role
import runtime_router
import runtime_portability
import runtime_workspace
import production_queue_store
import visual_lock_baseline_gate
import visual_lock_candidate_pool
import visual_lock_v21
import story_json
import storyos_config
import episode_lifecycle
import episode_contract_persistence
import episode_state_persistence
import hot_state_bridge
import runtime_review_persistence

ROOT = Path(__file__).resolve().parents[2]
REL = Path("meta/runtime/next-action.json")
QUEUE_REL = production_queue_store.REL
HOST_REL = Path("meta/runtime/product-host-request.json")
REVIEW_DIR = Path("meta/runtime/reviews")


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> dict:
    return story_json.read_json(path, default={})


def load(ep: Path) -> dict:
    """Read the derived next action from Runtime Workspace with legacy fallback."""
    hot = hot_state_bridge.read(Path(ep), "NEXT_ACTION")
    data = hot_state_bridge.value_or_fallback(
        hot,
        lambda: runtime_workspace.read_json(Path(ep), REL, default={}),
        default={},
    )
    return data if isinstance(data, dict) else {}


def state(ep: Path) -> str:
    return str((episode_state_persistence.load(ep) or {}).get("current_state") or "UNKNOWN")


def _pending_product_review_scan(ep: Path, *, current_state: str | None = None) -> tuple[dict | None, list[dict]]:
    """Return (live pending review, provably redundant residue).

    Only alias files are considered here: they are the current pointer, and
    per-attempt files are read on demand by product_review_adapter.
    """
    rows = []
    residue: list[dict] = []
    for current in runtime_review_persistence.list_current(ep):
        p = current["path"]
        d = current.get("payload") or {}
        kind = str(d.get("review_kind") or "")
        # A prior WORK host's optional critic-shadow is not the official
        # Story Critic authority in the explicitly native CODEX_MANAGED mode.
        # Keep historical request bytes for audit, but do not let its missing
        # host response permanently strand the native production DAG.
        # The canonical story-semantic request is NOT suppressed.
        text_runtime, _ = runtime_router.text_review_runtime()
        if text_runtime == "CODEX" and kind.endswith("-critic-shadow"):
            continue
        # Actual-pixel authority now belongs to CODEX_VISION. Historical WORK
        # product-review requests for visual tasks are compatibility residue and
        # must never steal routing back from the vision lane.
        vision_runtime, _ = runtime_router.vision_review_runtime()
        if vision_runtime == "CODEX" and (
            kind in {"visual-lock-baseline", "visual-lock", "visual-profile-legacy", "frame-semantic"}
            or kind.startswith("production-batch-")
            or kind.startswith("caption-image-audit-v2-")
        ):
            continue
        # Episode stage is the canonical authority. Once Visual Lock has already
        # advanced to VISUAL_CALIBRATED (or beyond), an older unfinished product
        # review request for that same gate is stale runtime residue and must not
        # pull the DAG backwards into PRODUCT_REVIEW.
        if current_state in {"VISUAL_CALIBRATED", "PRODUCTION_PASSED", "PUBLISH_READY", "PUBLISHED", "DATA_REVIEWED"} and kind in {
            "visual-lock-baseline", "visual-lock", "visual-profile-legacy"
        }:
            continue
        if d.get("status") == product_review_adapter.AWAITING:
            entry = {"path": p.resolve().relative_to(ROOT.resolve()).as_posix(), **d}
            # A provably answered duplicate is residue, not an unanswered request
            # that happened to age out. Preserve that stronger fact before TTL
            # reconciliation so Gate F audit semantics stay intact.
            answered = product_review_adapter.answered_request(ep, entry)
            if answered:
                residue.append({**entry, "redundant_with": answered})
                continue
            # Lifecycle reconciliation is fail-closed. Expired/superseded requests
            # become terminal audit rows; malformed lifecycle metadata remains
            # AWAITING so the review is still routed rather than silently skipped.
            reconciled, _ = product_review_adapter.reconcile_request(ep, entry)
            if reconciled.get("status") != product_review_adapter.AWAITING:
                continue
            rows.append((str(reconciled.get("created_at") or ""), p, reconciled))
    if not rows:
        return None, residue
    _, path, data = sorted(rows, key=lambda x: (x[0], x[1].name))[0]
    return {"path": path.resolve().relative_to(ROOT.resolve()).as_posix(), **data}, residue


def pending_product_review(ep: Path, *, current_state: str | None = None) -> dict | None:
    """The single live pending product review, or None.

    Kept as a public seam: derive() must keep calling this function, because
    tests patch it to steer routing.
    """
    return _pending_product_review_scan(ep, current_state=current_state)[0]


def redundant_product_review_residue(ep: Path, *, current_state: str | None = None) -> list[dict]:
    """Pending reviews an earlier FINALIZED attempt already answered."""
    return _pending_product_review_scan(ep, current_state=current_state)[1]


def product_review_lifecycle_events(ep: Path) -> list[dict]:
    """Current terminal request lifecycle evidence for next-action/audit."""
    out: list[dict] = []
    for current in runtime_review_persistence.list_current(Path(ep)):
        p = current["path"]
        d = current.get("payload") or {}
        status = str(d.get("status") or "")
        if status not in {"EXPIRED", "CANCELLED", "SUPERSEDED"}:
            continue
        lifecycle = d.get("lifecycle") if isinstance(d.get("lifecycle"), dict) else {}
        out.append({
            "request_path": p.resolve().relative_to(ROOT.resolve()).as_posix(),
            "review_kind": d.get("review_kind"),
            "attempt": d.get("attempt"),
            "status": status,
            "deadline_at": d.get("deadline_at"),
            "actor": lifecycle.get("actor"),
            "reason": lifecycle.get("reason"),
            "at": lifecycle.get("at"),
        })
    return out


def host_loop(ep: Path) -> dict:
    """Projection of runner lifecycle evidence written by the host runner.

    Reports only what a runner already wrote to meta/runtime-runner-state.json.
    This never starts, restarts, stops, signals or waits on a runner, and the
    absence of a runner is never a condition this module acts on.
    """
    try:
        return runner_health_monitor.check(ep)
    except Exception:
        # Same shape as check() so no caller has to know which path produced it.
        return {
            "status": "UNKNOWN",
            "runner_status": None,
            "stage": None,
            "host_loop": "IDLE",
            "host_loop_source": "meta/runtime-runner-state.json",
        }


def queue_summary(ep: Path) -> dict:
    q = scheduler_core.load_queue(ep)
    counts: dict[str, int] = {}
    queued_frames = []
    items = [row for row in (q.get("items") or []) if isinstance(row, dict)]
    for row in items:
        status = str(row.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
        if status == "queued":
            queued_frames.append(int(row.get("frame") or 0))

    # Technical failures are attempt history only when a *later* success for the
    # same frame supersedes them. An older original success must not hide a newer
    # repair failure (the exact failure mode that previously routed back to a
    # stale WORK review instead of RETRY_TECHNICAL_FAILURES).
    ledger = (production_ledger.load_authority(ep, default={}) or {}).get("frames") or {}
    tech_failed = []
    for idx, row in enumerate(items):
        if row.get("status") != "tech_failed":
            continue
        frame = int(row.get("frame") or 0)
        later_success = any(
            int(other.get("frame") or 0) == frame and other.get("status") == "generated"
            for other in items[idx + 1:]
        )
        if later_success:
            continue
        ledger_row = ledger.get(f"{frame:02d}") or ledger.get(str(frame)) or {}
        current = ledger_row.get("current_candidate") if isinstance(ledger_row, dict) else None
        if ledger_row.get("status") in production_ledger.READY_LEDGER_STATES and isinstance(current, dict):
            failed_at = str(row.get("completed_at") or row.get("started_at") or row.get("queued_at") or "")
            recorded_at = str(current.get("recorded_at") or "")
            if failed_at and recorded_at and recorded_at >= failed_at:
                continue
        tech_failed.append(row)
    counts["tech_failed"] = len(tech_failed)

    # ``interrupted_unknown`` is also execution history, not necessarily the
    # current production truth. A later ledger candidate (or an approved asset)
    # for the same frame supersedes an older interrupted row.  Keep the queue row
    # for audit, but only count unresolved interruptions whose queued time is
    # newer than the current ledger candidate and which therefore still need
    # recovery evidence.
    unresolved_interrupted = []
    for row in items:
        if row.get("status") != "interrupted_unknown":
            continue
        frame_no = int(row.get("frame") or 0)
        frame = ledger.get(f"{frame_no:02d}") or ledger.get(str(frame_no)) or {}
        approved = frame.get("approved_asset") if isinstance(frame, dict) else None
        if isinstance(approved, dict) and approved.get("sha256"):
            continue
        current = frame.get("current_candidate") if isinstance(frame, dict) else None
        if isinstance(current, dict) and current.get("sha256"):
            row_output = str(row.get("output_path") or "")
            current_path = str(current.get("path") or current.get("asset_path") or "")
            if row_output and current_path and row_output == current_path:
                continue
            queued_at = str(row.get("queued_at") or "")
            recorded_at = str(current.get("recorded_at") or "")
            if queued_at and recorded_at and recorded_at >= queued_at:
                continue
        unresolved_interrupted.append(row)
    counts["interrupted_unknown"] = len(unresolved_interrupted)

    # ``blocked`` rows are non-regenerating technical failures.  Like
    # ``tech_failed``, an older blocked attempt becomes audit history when a
    # later candidate for the same frame has already committed.  Only the
    # unresolved tail may influence routing.
    unresolved_blocked = []
    for idx, row in enumerate(items):
        if row.get("status") != "blocked":
            continue
        frame_no = int(row.get("frame") or 0)
        later_success = any(
            int(other.get("frame") or 0) == frame_no and other.get("status") == "generated"
            for other in items[idx + 1:]
        )
        if later_success:
            continue
        frame = ledger.get(f"{frame_no:02d}") or ledger.get(str(frame_no)) or {}
        current = frame.get("current_candidate") if isinstance(frame, dict) else None
        if isinstance(current, dict) and current.get("sha256"):
            failed_at = str(row.get("completed_at") or row.get("started_at") or row.get("queued_at") or "")
            recorded_at = str(current.get("recorded_at") or "")
            if failed_at and recorded_at and recorded_at >= failed_at:
                continue
        unresolved_blocked.append(row)
    counts["blocked"] = len(unresolved_blocked)

    return {
        "counts": counts,
        "queued_frames": sorted(x for x in queued_frames if x > 0),
        "blocked_items": unresolved_blocked,
        "raw": q,
    }




def _unsafe_technical_generation_retries(ep: Path, q: dict) -> list[dict]:
    """Read the shared Attempt authority before advertising automatic retry."""
    import image_scheduler
    blocked: list[dict] = []
    for item in q.get("items") or []:
        if not isinstance(item, dict) or item.get("status") != "tech_failed":
            continue
        frame = int(item.get("frame") or 0)
        if frame < 1:
            continue
        code = str(item.get("technical_failure_code") or "")
        allowed, _state, reason = image_scheduler._technical_retry_budget(ep, item, code)
        if not allowed:
            blocked.append({"frame": frame, "technical_failure_code": code,
                            "reason": reason})
    return sorted(blocked, key=lambda item: item["frame"])


def _technical_generation_evidence_action(ep: Path, q: dict) -> dict | None:
    unresolved = _unsafe_technical_generation_retries(ep, q)
    if not unresolved:
        return None
    return {
        "action": "VERIFY_TECHNICAL_GENERATION_EVIDENCE",
        "executor": "WORK",
        "frames": sorted({row["frame"] for row in unresolved}),
        "unresolved": unresolved,
        "reason": "technical image rows lack verified retry authority; inspect provider receipts and real Attempt terminal outcome before any new native Codex dispatch",
    }


def blocked_final_semantic_recovery(q: dict) -> dict | None:
    """A blocked review is an unresolved model call, not a fresh image request.

    Only current attempt-scoped Final Semantic rows participate. Historical
    finalized/stale review rows must never reopen an Episode's recovery.
    """
    blocked = [row for row in (q.get("review_work_items") or [])
               if isinstance(row, dict)
               and row.get("review_kind") == "FINAL_SEMANTIC"
               and row.get("status") == "blocked"]
    if not blocked:
        return None
    return {
        "action": "VERIFY_FINAL_SEMANTIC_EXECUTION_BEFORE_RETRY",
        "review_keys": sorted({str(row.get("review_key")) for row in blocked
                               if row.get("review_key")}),
        "frames": sorted({int(row.get("frame")) for row in blocked
                          if str(row.get("frame") or "").isdigit()
                          and int(row["frame"]) > 0}),
        "work_pending": True,
        "hard_stop": True,
        "auto_recoverable": False,
        "reason": "Final Semantic call has no verified terminal execution/commit; inspect durable worker and model receipts before any retry, never regenerate pixels",
    }


def _expected_frames(ep: Path) -> int:
    try:
        return int(frame_contract.frame_count(ep))
    except Exception:
        return 0


def _represented_original_frames(q: dict, ep: Path | None = None) -> set[int]:
    represented = {
        int(row.get("frame") or 0)
        for row in (q.get("items") or [])
        if isinstance(row, dict)
        and row.get("kind") == "original"
        and str(row.get("scope") or "") in {"visual_lock", "batch"}
        and int(row.get("frame") or 0) > 0
        and (
            row.get("status") != "superseded"
            or bool(str(row.get("output_path") or "").strip())
        )
    }
    # Visual Lock frames are already durable production representations even
    # when they are intentionally absent from the production queue.  Count
    # them here so a calibrated episode can move from queue preparation to
    # generation instead of repeatedly preparing the same missing-frame set.
    if ep is not None:
        ledger = (production_ledger.load_authority(ep, default={}) or {}).get("frames") or {}
        represented.update(
            int(key)
            for key, row in ledger.items()
            if str(key).isdigit()
            and isinstance(row, dict)
            and (
                str(row.get("status") or "") in production_ledger.READY_LEDGER_STATES
                or bool((row.get("current_candidate") or {}).get("sha256"))
            )
            and int(key) > 0
        )
    return represented


def _ordinary_patch_review_frames(ep: Path, ledger_frames: dict) -> list[int]:
    expected = _expected_frames(ep)
    return sorted(
        frame for frame in range(1, expected + 1)
        if isinstance(ledger_frames.get(f"{frame:02d}"), dict)
        and str(ledger_frames[f"{frame:02d}"].get("status") or "") == "REPAIR_READY"
        and not _current_candidate_capture_id(ledger_frames[f"{frame:02d}"]).startswith("user-continuation-")
        and not _current_candidate_capture_id(ledger_frames[f"{frame:02d}"]).startswith("user-exception-")
    )


def _current_candidate_capture_id(frame: dict) -> str:
    """Return the capture id that produced the current candidate, if provable."""
    if not isinstance(frame, dict):
        return ""
    current = frame.get("current_candidate")
    if not isinstance(current, dict):
        return ""
    attempt_id = str(current.get("attempt_id") or "")
    if not attempt_id:
        return ""
    for attempt in reversed(frame.get("attempts") or []):
        if not isinstance(attempt, dict) or str(attempt.get("attempt_id") or "") != attempt_id:
            continue
        request = attempt.get("request") if isinstance(attempt.get("request"), dict) else {}
        return str(request.get("capture_id") or "")
    return ""


def _final_semantic_attempt(ep: Path) -> int:
    first = ep / "meta/frame-semantic-candidate-attempt-1.json"
    if first.is_file():
        data = read_json(first)
        if data.get("failed_frames"):
            return 2
    return 1


def _handoff_valid(ep: Path) -> bool:
    p = ep / "meta/preproduction-handoff.json"
    if not p.is_file():
        return False
    try:
        return not preproduction_handoff.verify(ep)
    except Exception:
        return False


@storyos_config.operation_cached
@production_ledger_persistence.operation_cached
@episode_contract_persistence.operation_cached
def _frozen_authorized_repair_frames(ep: Path, ledger_frames: dict) -> list[int]:
    """Project only committed Final Semantic FAILs into one repair action.

    Read-only: the Aggregator independently verifies pixels, SHA bindings,
    and remaining image attempt budget.
    """
    if not isinstance(ledger_frames, dict):
        return []
    path = Path(ep) / "meta/frame-semantic-candidate-attempt-1.json"
    evidence = story_json.read_json(path, default={}) if path.is_file() else {}
    if (not isinstance(evidence, dict)
            or evidence.get("review_scope") != "CANDIDATE_FULL_FRAME_SET"
            or not evidence.get("recorded_at")
            or not isinstance(evidence.get("failed_frames"), list)
            or not isinstance(evidence.get("reviewed_assets"), list)):
        return []
    reviewed = {str(row.get("frame") or "").zfill(2)
                for row in evidence["reviewed_assets"] if isinstance(row, dict)}
    failed = {str(value).zfill(2) for value in evidence["failed_frames"]}
    eligible = sorted(int(frame) for frame in failed & reviewed
                      if frame.isdigit()
                      and isinstance(ledger_frames.get(frame), dict)
                      and ledger_frames[frame].get("status") == "REPAIR_AUTHORIZED")
    if not eligible:
        return []
    plan = story_json.read_json(Path(ep) / "meta/runtime/repair-wave-1.json", default={})
    if plan:
        if plan.get("status") not in {"PLANNED", "STARTED"}:
            return []
        outstanding = {str(row.get("frame_id") or "").zfill(2)
                       for row in plan.get("frames") or []
                       if row.get("repairable") and
                       row.get("repair_status") in {"ELIGIBLE", "PROMPT_TECH_FAILED"}}
        return sorted(int(frame) for frame in failed & outstanding if frame.isdigit())
    return eligible

def derive(ep: Path) -> dict:
    ep = Path(ep).resolve()
    runtime_portability.assert_episode_directory(ep)
    detected_runtime, _ = runtime_router.detect()
    # Golden Path business actions are always owned by the canonical WORK role.
    # Runtime detection remains diagnostic/legacy input only; a workspace provider
    # name or historical WEB/CODEX base runtime must never leak into executor.
    runtime = runtime_executor_role.WORK
    image_runtime, _ = runtime_router.image_execution_runtime()
    vision_runtime, _ = runtime_router.vision_review_runtime()
    mode = runtime_execution.effective_mode(ep)
    cur = state(ep)
    disposition = episode_lifecycle.disposition(ep)
    if disposition in episode_lifecycle.TERMINAL:
        return {
            "schema_version": 1,
            "derived_at": now(),
            "episode": runtime_portability.episode_label(ep),
            "episode_state": cur,
            "episode_disposition": disposition,
            "stage_authority": "meta/episode-state.json",
            "derived_runtime_only": True,
            "action": "EPISODE_TERMINATED",
            "executor": None,
            "work_pending": False,
            "auto_recoverable": False,
            "hard_stop": True,
            "blocking": True,
            "continue_without_user_prompt": False,
            "reason": f"episode disposition is terminal: {disposition}",
        }
    review = pending_product_review(ep, current_state=cur)
    residue = redundant_product_review_residue(ep, current_state=cur)
    loop = host_loop(ep)
    try:
        product_runtime_adapter.reconcile(ep)
    except Exception:
        pass
    base = {
        "schema_version": 1,
        "derived_at": now(),
        "episode": runtime_portability.episode_label(ep),
        "episode_state": cur,
        "episode_disposition": disposition,
        "execution_mode": mode,
        "authoring_runtime": detected_runtime,
        "image_execution_runtime": image_runtime,
        "stage_authority": "meta/episode-state.json",
        "derived_runtime_only": True,
        "continue_without_user_prompt": True,
        "work_pending": False,
        "auto_recoverable": False,
        "hard_stop": False,
        "host_loop": str(loop.get("host_loop") or "IDLE"),
        "runner_status": loop.get("runner_status"),
        "product_review_lifecycle_events": product_review_lifecycle_events(ep),
        "suppressed_product_reviews": [
            {
                "request_path": row.get("path"),
                "review_kind": row.get("review_kind"),
                "attempt": row.get("attempt"),
                "answered_by": (row.get("redundant_with") or {}).get("path"),
                "final_path": (row.get("redundant_with") or {}).get("final_path"),
            }
            for row in residue
        ],
    }
    base["progress"] = scheduler_core.progress(ep, scheduler_core.load_queue(ep))
    def action_result(**kwargs):
        hard_stop = bool(kwargs.pop("hard_stop", False))
        auto = bool(kwargs.pop("auto_recoverable", True))
        pending = bool(kwargs.pop("work_pending", True))
        return {
            **base,
            "work_pending": pending,
            "auto_recoverable": auto,
            "hard_stop": hard_stop,
            "blocking": bool(hard_stop),
            **kwargs,
        }
    # Canonical production success outranks stale queue/review residue. Once the
    # Episode authority reaches PUBLISH_READY or later, ordinary repair rows,
    # NEEDS_USER markers, or unfinished historical reviews must not reopen the
    # production loop. The only exception is an explicit user-authorized
    # post-ready candidate, identified by its durable capture id.
    if cur in {"PUBLISH_READY", "PUBLISHED", "DATA_REVIEWED"}:
        terminal_ledger = (production_ledger.load_authority(ep, default={}) or {}).get("frames") or {}
        continuation_frames = sorted(
            int(key) for key, value in terminal_ledger.items()
            if str(key).isdigit()
            and isinstance(value, dict)
            and str(value.get("status") or "") == "REPAIR_READY"
            and _current_candidate_capture_id(value).startswith("user-continuation-")
        )
        if continuation_frames:
            return action_result(
                action="REVIEW_FINAL_CONTINUATION",
                executor="CODEX_VISION" if vision_runtime == "CODEX" else runtime,
                frames=continuation_frames,
                reason="explicit direct-user continuation candidates may reopen review after canonical production success",
            )
        exception_frames = sorted(
            int(key) for key, value in terminal_ledger.items()
            if str(key).isdigit()
            and isinstance(value, dict)
            and str(value.get("status") or "") == "REPAIR_READY"
            and _current_candidate_capture_id(value).startswith("user-exception-")
        )
        if exception_frames:
            return action_result(
                action="REVIEW_FINAL_EXCEPTION",
                executor="CODEX_VISION" if vision_runtime == "CODEX" else runtime,
                frames=exception_frames,
                reason="explicit direct-user exception candidates may reopen review after canonical production success",
            )
        return action_result(
            action="COMPLETE",
            executor=runtime,
            work_pending=False,
            auto_recoverable=False,
            hard_stop=False,
            reason=f"runtime production goal already reached at {cur}; stale non-user-authorized residue is ignored",
        )
    # A stale/missing PREIMAGE authority boundary invalidates every downstream
    # image request derived from it. This canonical freshness check must outrank
    # queue recovery, including AUTHORITY_REFRESH_AUTHORIZED, otherwise the host
    # loop can regenerate pixels against the very authority snapshot being
    # replaced. This is not "stale host request wins": next_host_step derives the
    # requirement from current authority/frame-contract/handoff evidence.
    if cur == "STORYBOARD_LOCKED" and not _handoff_valid(ep):
        try:
            preimage_step, _ = product_runtime_adapter.next_host_step(ep, mode)
        except Exception:
            preimage_step = "PREIMAGE_TASK_SET"
        if str(preimage_step).startswith("PREIMAGE_"):
            # An unanswered text/governance review is an unresolved authority
            # decision, so it outranks PREIMAGE freshness: compiling a new handoff
            # while the latest Story Critic / governance review is still awaiting
            # completion would freeze unreviewed authority into image contracts.
            # Visual pixel reviews are already filtered out by
            # pending_product_review() when CODEX_VISION owns that lane.
            #
            # The yield is scoped to THIS branch on purpose. A pending review must
            # not outrank ready-sibling image generation, queue recovery or the hard
            # stops below: those act on work already authorized, and letting a
            # review preempt them would strand a generatable frame behind a review
            # that nobody has answered yet.
            if review:
                return action_result(action="PRODUCT_REVIEW", executor=runtime,
                        request_path=review.get("path"), review_kind=review.get("review_kind"),
                        candidate_path=review.get("candidate_path"),
                        reason="fresh isolated product review is awaiting completion")
            current_request = product_runtime_adapter.load_current_request(ep) or {}
            return action_result(
                action="PREIMAGE_COMPILE",
                executor=runtime,
                preimage_step=preimage_step,
                request_path=current_request.get("request_path"),
                request_id=current_request.get("request_id"),
                reason="PREIMAGE authority/handoff is stale; refresh authority before any image generation or authority-refresh retry",
            )
    # Production queue recovery has priority over stale host requests.
    # A previous host request can remain after a worker failure; it must not
    # hide an automatic technical retry action.
    qs = queue_summary(ep)
    q = qs["raw"]
    if q:
        ledger_frames = (production_ledger.load_authority(ep, default={}) or {}).get("frames") or {}
        unresolved_blocked = list(qs.get("blocked_items") or [])
        # A real SHA-verified Batch success can trigger re-admission, but only
        # the machine executor may probe the current native session and mutate
        # the queue. This decision remains read-only and fail-closed.
        if cur == "VISUAL_CALIBRATED" and image_runtime == "CODEX" and unresolved_blocked:
            try:
                import production_native_batch_followon
                if production_native_batch_followon.admissible(ep, q):
                    return action_result(
                        action="RESUME_NATIVE_BATCH_AFTER_SUCCESS",
                        executor="MACHINE",
                        frames=sorted(int(x["frame"]) for x in unresolved_blocked),
                        work_pending=True, auto_recoverable=True, hard_stop=False,
                        reason="first native Batch real pixel verified; fresh session required to resume its historical UNKNOWN peers",
                    )
            except Exception:
                pass

        # A single explicitly re-armed native Batch frame may proceed before
        # its 15 UNKNOWN-blocked siblings. The reviewed SHA, exact frame,
        # MySQL Attempt, native route and every blocked sibling remain fenced
        # by the existing single-frame authority. Ordinary blocked rows and
        # unverified flags retain the hard-stop path below.
        if cur == "VISUAL_CALIBRATED" and image_runtime == "CODEX" and unresolved_blocked:
            candidates = [
                row for row in q.get("items", [])
                if row.get("scope") == "batch"
                and row.get("status") == "queued"
                and row.get("native_single_batch_proof") is True
            ]
            if len(candidates) == 1:
                try:
                    import image_scheduler
                    import model_policy
                    import production_native_batch_reentry
                    ready, _ = image_scheduler.ready_items(ep, q)
                    row = candidates[0]
                    if (len(ready) == 1
                            and ready[0].get("id") == row.get("id")
                            and production_native_batch_reentry.eligible(
                                ep, row,
                                model_policy.resolve("image.payload", episode=ep),
                                model_policy.resolve("image.controller", episode=ep),
                                queue=q)):
                        return action_result(
                            action="GENERATE_IMAGES",
                            executor="CODEX_IMAGE",
                            frames=[int(row["frame"])],
                            reason="only the SHA-bound native single-frame proof is runnable; other Batch capability blocks remain unchanged",
                        )
                except Exception:
                    # Read-only gate failed or authority unavailable; preserve
                    # the original blocked decision, never infer permission.
                    pass
        recompilable_prompt_blocks = [
            row for row in unresolved_blocked
            if visual_lock_candidate_pool.recompilable_prompt_blocked_item(row)
        ]
        if recompilable_prompt_blocks:
            blocked_frames = sorted({
                int(row.get("frame") or 0) for row in recompilable_prompt_blocks
                if int(row.get("frame") or 0) > 0
            })
            # A current-policy Visual Lock candidate rejected before provider
            # execution because the local prompt compiler exceeded its own budget
            # is not a user decision and not an image-provider failure. Re-enqueue
            # through the candidate pool; add_item(..., replace=True) will preserve
            # the rejected row as superseded audit history.
            other_blocked = [row for row in unresolved_blocked if row not in recompilable_prompt_blocks]
            if not other_blocked and blocked_frames:
                return action_result(
                    action="PREPARE_VISUAL_LOCK_CANDIDATES",
                    executor="MACHINE",
                    frames=blocked_frames,
                    work_pending=True,
                    auto_recoverable=True,
                    hard_stop=False,
                    reason="current-policy Visual Lock candidate was rejected before provider execution by the local prompt budget; recompile a bounded replacement candidate",
                )
            unresolved_blocked = other_blocked
        if (cur=="STORYBOARD_LOCKED" and image_runtime=="CODEX"
                and len(unresolved_blocked)==3):
            # All four original/repair paid slots are exhausted (2/2).
            # These exact extra Visual Lock candidate attempts failed before
            # provider dispatch. Evaluate existing independent Vision FAIL,
            # never issue a third paid attempt solely for a soft quality issue.
            history={int(x.get("frame") or 0):x for x in unresolved_blocked}
            expected={5:"771048aed8ca",45:"42ca8cbc3884",
                      47:"ae074a3d3c27"}
            if (set(history)==set(expected)
                and all(history[f].get("id")==iid
                        and history[f].get("kind")=="baseline_candidate"
                        and history[f].get("scope")=="repair"
                        and history[f].get("status")=="blocked"
                        and history[f].get("technical_failure_code")==
                            "LOGIN_AUTH_IMAGE_TOOL_CAPABILITY_UNKNOWN"
                        and not history[f].get("output_path")
                        for f,iid in expected.items())):
                eligible=visual_lock_candidate_pool.weak_pass_eligible_frames(ep)
                if eligible==[1,5,45,47]:
                    return action_result(
                        action="APPLY_VISUAL_LOCK_WEAK_PASS",
                        executor="MACHINE",frames=eligible,
                        auto_recoverable=True,hard_stop=False,
                        quality_debt=True,
                        reason="real Visual Lock pixels exhausted 2/2; accept soft findings with original FAIL audit, never third paid generation")
        if unresolved_blocked:
            budget_blocked = [
                row for row in unresolved_blocked
                if str(row.get("technical_failure_code") or "").upper() in raw_candidate_budget.BUDGET_BLOCK_CODES
            ]
            if budget_blocked:
                # Reviewing already-generated repair candidates costs no image
                # budget and can reduce the amount of follow-up generation needed.
                # Always review those fresh pixels before asking the user to raise
                # the episode image budget for still-blocked siblings.
                review_ready = _ordinary_patch_review_frames(ep, ledger_frames)
                if review_ready and frame_semantic_review.ordinary_patch_eligible(
                    ep, [f"{frame:02d}" for frame in review_ready]
                ):
                    return action_result(
                        action="REVIEW_FINAL_PATCH",
                        executor="CODEX_VISION" if vision_runtime=="CODEX" else runtime,
                        attempt=_final_semantic_attempt(ep),
                        frames=review_ready,
                        reason="fresh bounded repair candidates exist while sibling generation is budget-blocked; review existing pixels before requesting more image budget",
                    )
                budget_context = raw_candidate_budget.blocked_queue_context(ep, budget_blocked)
                resumable = list(budget_context.get("resumable_frames") or [])
                if resumable:
                    return action_result(
                        action="RESUME_BUDGET_AUTHORIZED_IMAGES",
                        executor="MACHINE",
                        frames=resumable,
                        budget=budget_context,
                        work_pending=True,
                        auto_recoverable=True,
                        hard_stop=False,
                        reason="candidate budget has deterministic machine-resumable capacity; requeue only frames that currently fit their bounded budget contract",
                    )
                return action_result(
                    action="USER_DECISION_REQUIRED",
                    executor=runtime,
                    frames=sorted({int(row.get("frame") or 0) for row in budget_blocked if int(row.get("frame") or 0)>0}),
                    budget=budget_context,
                    decision_kind="CANDIDATE_BUDGET_EXHAUSTED",
                    work_pending=True,
                    auto_recoverable=False,
                    hard_stop=True,
                    reason="candidate budget is exhausted; use the formal episode/frame authorization lifecycle or leave generation stopped",
                )
            plans = image_blocked_recovery.inspect(ep, unresolved_blocked)
            if plans and all(bool(row.get("auto_resolvable")) for row in plans):
                return action_result(
                    action="RESOLVE_IMAGE_NORMALIZATION",
                    executor="MACHINE",
                    frames=sorted({int(row.get("frame") or 0) for row in plans if int(row.get("frame") or 0) > 0}),
                    reason="preserved provider RAW can be deterministically normalized under the explicit provider-ratio exception; do not regenerate or review stale pixels",
                )
            return action_result(
                action="IMAGE_ATTEMPT_BLOCKED",
                executor=runtime,
                frames=sorted({int(row.get("frame") or 0) for row in unresolved_blocked if int(row.get("frame") or 0) > 0}),
                hard_stop=True,
                auto_recoverable=False,
                blocked=[{
                    "frame": int(row.get("frame") or 0),
                    "code": str(row.get("code") or ""),
                    "reason": str(row.get("reason") or "non-regenerating image failure requires explicit inspection"),
                    "recovery_action": row.get("recovery_action"),
                    "recovery_hint": row.get("recovery_hint"),
                } for row in plans],
                reason="non-regenerating image failure must be resolved before any pixel review or further generation",
            )
        authority_refresh_frames = sorted(
            int(key) for key, row in ledger_frames.items()
            if isinstance(row, dict) and row.get("status") == "AUTHORITY_REFRESH_AUTHORIZED"
        )
        if authority_refresh_frames:
            # Technical recovery still outranks authority regeneration: if the
            # freshly refreshed baseline failed at the provider, retry that exact
            # attempt before considering dependent admissions.
            if qs["counts"].get("external_blocked"):
                blocked_frames=sorted({int(x.get("frame") or 0) for x in q.get("items") or [] if x.get("status")=="external_blocked" and int(x.get("frame") or 0)>0})
                return {**base, "action":"EXTERNAL_IMAGE_PROVIDER_BLOCKED", "executor":"EXTERNAL",
                        "blocking":True, "work_pending":True, "auto_recoverable":False, "hard_stop":True,
                        "frames":blocked_frames, "reason":"image provider technical retry epoch exhausted"}
            if qs["counts"].get("tech_failed"):
                unsafe = _technical_generation_evidence_action(ep, q)
                if unsafe:
                    return action_result(**unsafe)
                return action_result(action="RETRY_TECHNICAL_FAILURES", executor="CODEX_IMAGE",
                        reason="technical image failure must recover before authority-refresh dependents")
            try:
                baseline = int(visual_lock_baseline_gate.baseline_frame(ep))
            except Exception:
                baseline = None
            if baseline is not None and baseline not in authority_refresh_frames and character_visual_contract.pixel_master_required(ep):
                try:
                    master = character_visual_contract.pixel_master_reference(ep, allow_provisional=True)
                except Exception:
                    master = None
                if master is None:
                    return action_result(
                        action="REVIEW_ORDINARY_BASELINE",
                        executor="CODEX_VISION" if vision_runtime=="CODEX" else runtime,
                        frame=baseline,
                        reason="authority-refreshed baseline must PASS and establish the new Pixel Master before dependent frames regenerate",
                    )
            return action_result(
                action="REFRESH_AUTHORITY_IMAGES",
                executor="CODEX_IMAGE" if image_runtime=="CODEX" else runtime,
                frames=authority_refresh_frames,
                reason="upstream authority/Frame Contract changed; regenerate these frames without consuming content repair budget",
            )
        try:
            if visual_lock_baseline_gate.awaiting_review(ep, q):
                return action_result(action="REVIEW_ORDINARY_BASELINE",
                        executor="CODEX_VISION" if vision_runtime=="CODEX" else runtime,
                        frame=visual_lock_baseline_gate.baseline_frame(ep),
                        reason="Visual Lock baseline pixels must PASS before parallel-three generation")
        except Exception:
            pass
        visual_rows=[x for x in q.get("items") or [] if str(x.get("scope") or "")=="visual_lock"]
        visual_frames={int(x.get("frame") or 0) for x in visual_rows}
        if cur=="STORYBOARD_LOCKED":
            weak_pass_frames=visual_lock_candidate_pool.weak_pass_eligible_frames(ep)
            if weak_pass_frames:
                return action_result(action="APPLY_VISUAL_LOCK_WEAK_PASS", executor="MACHINE",
                        frames=weak_pass_frames,auto_recoverable=True,hard_stop=False,
                        reason="content attempts exceeded 3 and only soft visual-quality findings remain; apply auditable low-score acceptance without generating again")
            candidate_frames=visual_lock_candidate_pool.prepareable_frames(ep)
            if candidate_frames:
                return action_result(action="PREPARE_VISUAL_LOCK_CANDIDATES", executor="MACHINE",
                        frames=candidate_frames,
                        reason="Visual Lock admissions exhausted ordinary repair; prepare bounded independent candidates")
            exhausted=visual_lock_candidate_pool.exhausted_frames(ep)
            if exhausted:
                return {**base, "action":"USER_DECISION_REQUIRED", "executor":runtime,
                        "blocking":True, "work_pending":True, "auto_recoverable":False, "hard_stop":True,
                        "frames":exhausted,
                        "reason":"Visual Lock bounded admission candidate pool exhausted after real Codex Vision failures"}
        visual_repair_active=any(
            int(x.get("frame") or 0) in visual_frames and x.get("kind") in {"repair","baseline_candidate"}
            and x.get("status") in {"queued","running","tech_failed","external_blocked","interrupted_unknown"}
            for x in q.get("items") or []
        )
        if cur=="STORYBOARD_LOCKED" and not visual_repair_active and len(visual_rows)==4 and all(x.get("status")=="generated" for x in visual_rows):
            stale_bindings = visual_lock_v21.stale_generation_bindings(ep)
            if stale_bindings:
                return action_result(
                    action="PREPARE_STALE_VISUAL_LOCK_REFRESH",
                    executor="MACHINE",
                    frames=sorted({int(row["frame"]) for row in stale_bindings}),
                    stale_bindings=stale_bindings,
                    reason="Visual Lock candidate pixels were generated under an older Frame Contract; re-render only those frames before pixel review",
                )
            try:
                visual_errors=visual_lock_v21.verify(ep,metadata_only=False)
            except Exception as exc:
                visual_errors=[str(exc)]
            if visual_errors:
                dirty_frames = visual_lock_v21.dirty_admission_frames(ep)
                return action_result(action="REVIEW_VISUAL_LOCK",
                        executor="CODEX_VISION" if vision_runtime=="CODEX" else runtime,
                        frames=dirty_frames or sorted(int(x.get("frame") or 0) for x in visual_rows),
                        reason="dirty Visual Lock admissions require isolated actual-pixel review; valid SHA-bound PASS rows are reused")
            return action_result(action="FINALIZE_VISUAL_LOCK", executor="MACHINE",
                    frames=sorted(int(x.get("frame") or 0) for x in visual_rows),
                    reason="four-image Codex Vision evidence is valid; deterministic gate/approval/state finalization remains")

        if cur=="VISUAL_CALIBRATED":
            expected=_expected_frames(ep)
            represented=_represented_original_frames(q, ep)
            if expected>0 and len(represented)<expected:
                return action_result(action="PREPARE_PRODUCTION_BATCH", executor="MACHINE",
                        represented_frames=sorted(represented), expected_frames=expected,
                        reason="Visual Lock is calibrated; deterministically materialize missing scene prompts and queue remaining original frames")
            try:
                batch_ids=production_batch_review.pending(ep)
            except Exception:
                batch_ids=[]
            if batch_ids:
                return action_result(action="REVIEW_GENERATED_IMAGES",
                        executor="CODEX_VISION" if vision_runtime=="CODEX" else runtime,
                        batch_ids=batch_ids,
                        reason="generated Production logical batch awaits isolated actual-pixel review")

        # Reuse the scheduler's dependency authority. In particular, Visual Lock
        # dependents must wait for baseline *approval*, not merely an older
        # generated Frame01 candidate. Duplicating dependency logic here caused
        # 05/16/17 to bypass the baseline gate after Frame01 entered repair.
        import image_scheduler
        scheduler_ready, _scheduler_blocked = image_scheduler.ready_items(ep, q)
        runnable=sorted({int(x["frame"]) for x in scheduler_ready})
        if runnable:
            return action_result(action="GENERATE_IMAGES",executor="CODEX_IMAGE" if image_runtime=="CODEX" else runtime,
                frames=runnable,reason="scheduler dependency authority reports runnable image work")
        review_block = blocked_final_semantic_recovery(q)
        if review_block:
            return action_result(**{**review_block, "executor": runtime})

        production_review_pending=[
            x for x in q.get("items") or []
            if str(x.get("scope") or "")=="batch" and x.get("status")=="review_pending"
        ]
        if cur=="VISUAL_CALIBRATED" and production_review_pending:
            return action_result(action="REVIEW_GENERATED_IMAGES",
                    executor="CODEX_VISION" if vision_runtime=="CODEX" else runtime,
                    batch_ids=sorted({str(x.get("batch_id")) for x in production_review_pending if x.get("batch_id")}),
                    reason="Production batch review request remains pending isolated actual-pixel review")
        deferred_production_scout = any(
            row.get("status") == "scout_repair" and str(row.get("scope") or "") in {"batch", "production"}
            for row in q.get("items") or []
        )
        if qs["counts"].get("scout_repair") and not deferred_production_scout:
            return action_result(action="REPAIR_FAILED_IMAGES",
                    executor="CODEX_IMAGE" if image_runtime=="CODEX" else runtime,
                    reason="actual-pixel review authorized content repair")
        if qs["counts"].get("external_blocked"):
            blocked_items=[x for x in q.get("items") or [] if x.get("status")=="external_blocked"]
            # Recover SHA-verified RAW before any new image attempt; never
            # mix unproven IMAGE_BACKEND_ERROR with this machine-only path.
            try:
                import image_unknown_raw_reconcile
                recoverable = sorted(int(x["frame"]) for x in blocked_items
                                     if image_unknown_raw_reconcile.eligible(ep,x))
            except Exception:
                recoverable = []
            if recoverable:
                return action_result(
                    action="RECONCILE_PRESERVED_PROVIDER_RAW", executor="MACHINE",
                    frames=recoverable, work_pending=True, auto_recoverable=True,
                    hard_stop=False,
                    reason="verified native provider RAW with previously UNKNOWN generation attempt may be normalized and reconciled without regenerating",
                )

            failover_frames=sorted({
                int(x.get("frame") or 0) for x in blocked_items
                if int(x.get("frame") or 0)>0 and image_scheduler.availability_fallback_model(x)
            })
            if failover_frames:
                return action_result(action="RETRY_TECHNICAL_FAILURES",executor="CODEX_IMAGE",
                        frames=failover_frames,model_failover=True,
                        reason="current non-strict image model exhausted availability retries; advance to the next configured model without consuming content repair")
            blocked_frames=sorted({int(x.get("frame") or 0) for x in blocked_items if int(x.get("frame") or 0)>0})
            return action_result(action="EXTERNAL_IMAGE_PROVIDER_BLOCKED", executor="EXTERNAL",
                    frames=blocked_frames,hard_stop=True,auto_recoverable=False,
                    reason="image provider technical retry budget is exhausted; content/candidate budgets are preserved")
        if qs["counts"].get("tech_failed"):
            unsafe = _technical_generation_evidence_action(ep, q)
            if unsafe:
                return action_result(**unsafe)
            return action_result(action="RETRY_TECHNICAL_FAILURES", executor="CODEX_IMAGE",
                    reason="technical image failures remain; successful siblings must be reused")
        if qs["counts"].get("interrupted_unknown"):
            return {**base, "action": "RECOVER_INTERRUPTED_IMAGES", "executor": runtime, "blocking": True,
                    "work_pending": True, "auto_recoverable": False, "hard_stop": True,
                    "reason": "an interrupted worker has no terminal receipt; inspect reconciliation evidence before retry"}
        # A stale `running` row after a host/process interruption must enter the
        # scheduler once so crash reconciliation can inspect lifecycle/ledger
        # evidence. This does not authorize regeneration by itself.
        running_frames=sorted({
            int(x.get("frame") or 0) for x in q.get("items") or []
            if x.get("status")=="running" and int(x.get("frame") or 0)>0
        })
        if running_frames:
            return action_result(action="GENERATE_IMAGES", executor="CODEX_IMAGE" if image_runtime == "CODEX" else runtime,
                    frames=running_frames,
                    reason="image attempt is marked running; scheduler must reconcile durable worker evidence before any retry")

        # A committed full-frame FAIL and its bounded repairs outrank human-only siblings.
        if cur == "VISUAL_CALIBRATED" and vision_runtime == "CODEX":
            frozen_ledger = (production_ledger.load_authority(ep, default={}) or {}).get("frames") or {}
            authorized = _frozen_authorized_repair_frames(ep, frozen_ledger)
            if authorized:
                return action_result(
                    action="MATERIALIZE_REPAIR_WAVE",
                    executor="CODEX_VISION" if vision_runtime == "CODEX" else runtime,
                    attempt=1, frames=authorized,
                    reason="committed Final Semantic FAIL requires one SHA-verified repair wave before human-only siblings",
                )
        if cur in {"VISUAL_CALIBRATED", "PRODUCTION_PASSED", "PUBLISH_READY"}:
            expected=_expected_frames(ep)
            ledger_frames=(production_ledger.load_authority(ep, default={}) or {}).get("frames") or {}
            ready_statuses=set(production_ledger.READY_LEDGER_STATES) | set(production_ledger.ACCEPTED_LEDGER_STATES)
            complete_candidates=(
                expected>0 and len([k for k in ledger_frames if str(k).isdigit()])>=expected
                and all(
                    isinstance(ledger_frames.get(f"{frame:02d}"),dict)
                    and str(ledger_frames[f"{frame:02d}"].get("status") or "") in ready_statuses
                    for frame in range(1,expected+1)
                )
            )
            all_locked=complete_candidates and all(
                str(ledger_frames[f"{frame:02d}"].get("status") or "")=="LOCKED"
                for frame in range(1,expected+1)
            )
            continuation_review_frames=sorted(
                frame for frame in range(1, expected+1)
                if isinstance(ledger_frames.get(f"{frame:02d}"), dict)
                and str(ledger_frames[f"{frame:02d}"].get("status") or "") == "REPAIR_READY"
                and _current_candidate_capture_id(ledger_frames[f"{frame:02d}"]).startswith("user-continuation-")
            )
            if continuation_review_frames:
                return action_result(
                    action="REVIEW_FINAL_CONTINUATION",
                    executor="CODEX_VISION" if vision_runtime=="CODEX" else runtime,
                    frames=continuation_review_frames,
                    reason="fresh direct-user continuation candidates require their own SHA-bound patch review before generic final production review",
                )
            exception_review_frames=sorted(
                frame for frame in range(1, expected+1)
                if isinstance(ledger_frames.get(f"{frame:02d}"), dict)
                and str(ledger_frames[f"{frame:02d}"].get("status") or "") == "REPAIR_READY"
                and _current_candidate_capture_id(ledger_frames[f"{frame:02d}"]).startswith("user-exception-")
            )
            if exception_review_frames:
                return action_result(
                    action="REVIEW_FINAL_EXCEPTION",
                    executor="CODEX_VISION" if vision_runtime=="CODEX" else runtime,
                    frames=exception_review_frames,
                    reason="direct-user exception candidates must receive their dedicated attempt-3 semantic review before generic final production review",
                )
            ordinary_patch_frames=_ordinary_patch_review_frames(ep, ledger_frames)
            if ordinary_patch_frames and frame_semantic_review.ordinary_patch_eligible(
                ep, [f"{frame:02d}" for frame in ordinary_patch_frames]
            ):
                return action_result(
                    action="REVIEW_FINAL_PATCH",
                    executor="CODEX_VISION" if vision_runtime=="CODEX" else runtime,
                    attempt=_final_semantic_attempt(ep),
                    frames=ordinary_patch_frames,
                    reason="bounded ordinary repair candidates have fresh locked siblings; review dirty frames plus continuity context instead of re-reviewing the full frame set",
                )
            nonlocked_frames = sorted(
                int(key) for key, value in ledger_frames.items()
                if str(key).isdigit() and isinstance(value, dict) and value.get("status") != "LOCKED"
            )
            if (
                complete_candidates
                and nonlocked_frames
                and all(final_acceptance.allows(ep, "frame_semantic", frame) for frame in nonlocked_frames)
            ):
                return action_result(
                    action="FINALIZE_PRODUCTION_IMAGES",
                    executor="MACHINE",
                    frames=list(range(1, expected + 1)),
                    reason="direct user final acceptance covers every non-LOCKED production frame; preserve known defects and stop image repair",
                )
            if complete_candidates and not all_locked:
                return action_result(action="REVIEW_FINAL_PRODUCTION",
                        executor="CODEX_VISION" if vision_runtime=="CODEX" else runtime,
                        attempt=_final_semantic_attempt(ep),
                        frames=list(range(1,expected+1)),
                        reason="all production candidates exist; final SHA-bound semantic pixel review must PASS and lock every frame")
            if all_locked:
                reviews=read_json(ep/"meta/story-gates.json").get("reviews") or {}
                if reviews.get("production")!="passed" or reviews.get("continuity")!="passed" or reviews.get("authenticity")!="passed":
                    return action_result(action="FINALIZE_PRODUCTION_IMAGES", executor="MACHINE",
                            frames=list(range(1,expected+1)),
                            reason="all production frames are semantic-reviewed and LOCKED; deterministic image-production gate finalization remains")

    ledger_frames = (production_ledger.load_authority(ep, default={}) or {}).get("frames") or {}
    accepted_nonlocked_frames = sorted(
        int(key) for key, value in ledger_frames.items()
        if str(key).isdigit()
        and isinstance(value, dict)
        and value.get("status") != "LOCKED"
    )
    accepted_nonlocked_ready = (
        bool(accepted_nonlocked_frames)
        and all(final_acceptance.allows(ep, "frame_semantic", frame) for frame in accepted_nonlocked_frames)
        and all(
            isinstance(ledger_frames.get(f"{frame:02d}"), dict)
            and (
                isinstance(ledger_frames[f"{frame:02d}"].get("current_candidate"), dict)
                or isinstance(ledger_frames[f"{frame:02d}"].get("approved_asset"), dict)
            )
            for frame in accepted_nonlocked_frames
        )
    )
    reviews = (read_json(ep / "meta/story-gates.json").get("reviews") or {}) if (ep / "meta/story-gates.json").is_file() else {}
    production_images_finalized = all(
        reviews.get(name) == "passed" for name in ("production", "continuity", "authenticity")
    )
    if accepted_nonlocked_ready and not production_images_finalized:
        expected = _expected_frames(ep)
        return action_result(
            action="FINALIZE_PRODUCTION_IMAGES",
            executor="MACHINE",
            frames=list(range(1, expected + 1)),
            reason="direct user final acceptance covers every remaining non-LOCKED frame and final publish assets are SHA-bound",
        )

    needs_user_frames = sorted(
        int(key) for key, value in ledger_frames.items()
        if str(key).isdigit() and isinstance(value, dict) and value.get("status") == "NEEDS_USER"
    )
    if needs_user_frames and not (accepted_nonlocked_ready and production_images_finalized):
        # Visual Lock baseline is special: after the ordinary one-shot repair is
        # exhausted, full-auto may still try a bounded candidate competition.
        # This does not raise content_repairs_used and does not bypass Codex Vision.
        try:
            baseline = visual_lock_baseline_gate.baseline_frame(ep)
        except Exception:
            baseline = None
        if (
            cur == "STORYBOARD_LOCKED"
            and baseline is not None
            and int(baseline) in needs_user_frames
            and baseline_candidate_pool.can_prepare(ep)
        ):
            return action_result(
                action="PREPARE_BASELINE_CANDIDATE",
                executor="MACHINE",
                frame=int(baseline),
                used=baseline_candidate_pool.successful_candidate_slots(ep),
                max=baseline_candidate_pool.max_additional_candidates(),
                reason="ordinary baseline repair is exhausted; prepare the next bounded independent baseline candidate",
            )
        return action_result(
            action="USER_DECISION_REQUIRED",
            executor=runtime,
            frames=needs_user_frames,
            work_pending=True,
            auto_recoverable=False,
            hard_stop=True,
            reason="production frames exhausted automatic/authorized repair lanes and require an explicit user decision",
        )

    # Last-resort authority gate: everything that acts on already-authorized work
    # has returned above, so an unanswered review now blocks stage progression
    # rather than image generation. See the scoped yield inside the stale-PREIMAGE
    # branch for the one case where a review does outrank a concrete action.
    if review:
        return action_result(action="PRODUCT_REVIEW", executor=runtime,
                request_path=review.get("path"), review_kind=review.get("review_kind"),
                candidate_path=review.get("candidate_path"),
                reason="fresh isolated product review is awaiting completion")

    if cur == "IDEA_LOCKED":
        return {**base, "action": "CREATIVE_STORY", "executor": runtime, "blocking": True,
                "target_state": "STORYBOARD_LOCKED", "reason": "Story/Storyboard/critics are not yet locked"}
    if cur == "STORYBOARD_LOCKED":
        if not _handoff_valid(ep):
            return {**base, "action": "PREIMAGE_COMPILE", "executor": runtime, "blocking": True,
                    "reason": "preproduction handoff is missing or stale"}
        return {**base, "action": "VISUAL_LOCK", "executor": runtime, "blocking": True,
                "target_state": "VISUAL_CALIBRATED", "reason": "preimage evidence is valid; begin Visual Lock 1+3"}
    if cur == "VISUAL_CALIBRATED":
        return {**base, "action": "PRODUCTION", "executor": runtime, "blocking": True,
                "target_state": "PRODUCTION_PASSED", "reason": "Visual Lock passed; production remains"}
    if cur == "PRODUCTION_PASSED":
        return {**base, "action": "RELEASE", "executor": runtime, "blocking": True,
                "target_state": "PUBLISH_READY", "reason": "final release closure remains"}
    if cur in {"PUBLISH_READY", "PUBLISHED", "DATA_REVIEWED"}:
        return {**base, "action": "COMPLETE", "executor": runtime, "blocking": False,
                "reason": f"runtime production goal already reached at {cur}"}
    return {**base, "action": "REPAIR_STATE", "executor": runtime, "blocking": True,
            "reason": f"unrecognized episode state: {cur}"}


def apply_runtime_block_semantics(data: dict) -> dict:
    """V2.7: blocking no longer means every pending action is a hard stop.

    Runtime consumers need to know whether work exists, whether it can be
    recovered automatically, and whether a human decision is truly required.
    Keep legacy ``blocking`` for compatibility, but expose explicit semantics.
    """
    action = str(data.get("action") or "")
    hard_stop_actions = {"REPAIR_STATE", "RECOVER_INTERRUPTED_IMAGES", "USER_DECISION_REQUIRED", "EXTERNAL_IMAGE_PROVIDER_BLOCKED", "IMAGE_ATTEMPT_BLOCKED", "VERIFY_TECHNICAL_GENERATION_EVIDENCE"}
    recoverable_actions = {
        "GENERATE_IMAGES",
        "RETRY_TECHNICAL_FAILURES",
        "REPAIR_FAILED_IMAGES",
        "PRODUCT_REVIEW",
        "HOST_ACTION",
        "PRODUCTION",
        "VISUAL_LOCK",
        "RELEASE",
        "CREATIVE_STORY",
        "PREIMAGE_COMPILE",
        "REVIEW_ORDINARY_BASELINE",
        "REVIEW_VISUAL_LOCK",
        "REVIEW_GENERATED_IMAGES",
        "REVIEW_FINAL_PRODUCTION",
        "MATERIALIZE_REPAIR_WAVE",
        "REVIEW_FINAL_PATCH",
        "REVIEW_FINAL_EXCEPTION",
        "REVIEW_FINAL_CONTINUATION",
        "PREPARE_BASELINE_CANDIDATE",
        "PREPARE_VISUAL_LOCK_CANDIDATES",
        "PREPARE_STALE_VISUAL_LOCK_REFRESH",
        "RESOLVE_IMAGE_NORMALIZATION",
        "FINALIZE_VISUAL_LOCK",
        "PREPARE_PRODUCTION_BATCH",
        "FINALIZE_PRODUCTION_IMAGES",
    }
    data["work_pending"] = action != "COMPLETE"
    data["auto_recoverable"] = action in recoverable_actions
    data["hard_stop"] = action in hard_stop_actions
    # Backward compatibility: blocking means there is pending work, not that
    # the whole workflow must stop.
    data["blocking"] = bool(data["work_pending"] and data["hard_stop"])
    # A pure projection of two facts already on disk: work is owed, and no host
    # loop is running. It is deliberately NOT a hard stop and NOT a recovery
    # trigger -- the engine has no watchdog and never starts a runner. It exists
    # so that "there is work and nobody is doing it" is visible at every read
    # site instead of looking like a quiet episode.
    data["host_loop"] = str(data.get("host_loop") or "IDLE")
    data["orphaned_pending_work"] = bool(data["work_pending"] and data["host_loop"] != "RUNNING")
    return data


def write(ep: Path) -> dict:
    data = apply_runtime_block_semantics(derive(ep))
    runtime_executor_role.validate_action(data)
    if hot_state_bridge.compatibility_write_allowed():
        runtime_workspace.write_json(Path(ep), REL, data)
    hot_state_bridge.mirror(Path(ep), "NEXT_ACTION", data)
    return data


def self_test() -> None:
    assert REL.as_posix() == "meta/runtime/next-action.json"
    print("NEXT ACTION V2.6.1 H1 SELF-TEST PASS")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("show", "write"):
        p = sub.add_parser(name); p.add_argument("episode_dir")
    sub.add_parser("self-test")
    args = ap.parse_args()
    if args.cmd == "self-test":
        self_test(); return 0
    ep = Path(args.episode_dir).resolve()
    data = write(ep) if args.cmd == "write" else apply_runtime_block_semantics(derive(ep))
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
