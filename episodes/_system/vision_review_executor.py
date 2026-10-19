#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Local isolated Codex Vision host-action executor.

This module owns only actual-pixel review actions. It never generates images,
rewrites Story/PREIMAGE authority, approves Release, or advances episode-state.
The surrounding WORK Runtime remains the orchestration/governance authority.
"""
from __future__ import annotations

from pathlib import Path

import auto_repair_enqueue
import baseline_candidate_pool
import frame_semantic_review
import production_batch_review
import runtime_router
import story_json
import runtime_timeout_policy
import visual_lock_baseline_gate
import visual_lock_candidate_pool
import visual_lock_admission_state
import visual_lock_v21
import visual_profile_review_persistence
import production_ledger
import scheduler_core

ALLOWED_ACTIONS = {
    "REVIEW_ORDINARY_BASELINE",
    "REVIEW_VISUAL_LOCK",
    "REVIEW_GENERATED_IMAGES",
    "REVIEW_FINAL_PRODUCTION",
    "MATERIALIZE_REPAIR_WAVE",
    "REVIEW_FINAL_PATCH",
    "REVIEW_FINAL_EXCEPTION",
    "REVIEW_FINAL_CONTINUATION",
}


class VisionReviewError(RuntimeError):
    pass


def local_vision_action(action: dict) -> str | None:
    if not isinstance(action, dict):
        return None
    if str(action.get("executor") or "").upper() != "CODEX_VISION":
        return None
    name = str(action.get("action") or "")
    return name if name in ALLOWED_ACTIONS else None


def _require_capability() -> None:
    runtime, _ = runtime_router.vision_review_runtime()
    if runtime != "CODEX" or not runtime_router.local_codex_vision_allowed():
        raise VisionReviewError(f"Codex Vision review is not enabled: runtime={runtime}")


def _persisted_current_visual_lock_fail_rows(ep: Path, *, frames: list[int], attempt: int) -> list[dict]:
    """Return current SHA-bound FAIL rows already persisted for this review attempt.

    A Codex Vision process can emit and persist a complete content decision, then
    lose its transport before the terminal event. In that narrow case the content
    result is authoritative for the reviewed pixels; the trailing process failure
    must not force a duplicate review. Any missing/mismatched binding keeps the
    caller fail-closed as a technical failure.
    """
    try:
        contract = visual_lock_v21.compile_prompt_contract(ep)
        profile_sha256 = str(contract.get("profile_sha256") or "").lower()
        story_os_version = visual_lock_v21.episode_version(ep)
        assets = visual_lock_v21.calibration_assets(ep)
        by_frame = {int(asset.get("frame") or 0): asset for asset in assets}
        items = (visual_lock_admission_state.load(ep).get("items") or {})
        rows: list[dict] = []
        for frame in frames:
            asset = by_frame.get(int(frame))
            if asset is None:
                return []
            entry = items.get(str(asset.get("id") or ""))
            if not isinstance(entry, dict) or entry.get("status") != "FAIL":
                return []
            if int(entry.get("attempt") or 0) != int(attempt):
                return []
            expected = visual_lock_admission_state.binding(
                asset,
                profile_sha256=profile_sha256,
                story_os_version=story_os_version,
            )
            for key, value in expected.items():
                actual = entry.get(key)
                if key in {"sha256", "frame_contract_sha256", "profile_sha256"}:
                    actual = str(actual or "").lower()
                    value = str(value or "").lower()
                if actual != value:
                    return []
            row = entry.get("review_row")
            if not isinstance(row, dict):
                return []
            rows.append(dict(row))
        return rows
    except Exception:
        return []


def execute(ep: Path, action: dict) -> dict:
    ep = Path(ep).resolve()
    name = local_vision_action(action)
    if name is None:
        raise VisionReviewError(f"not an auto-allowed Codex Vision action: {action}")
    _require_capability()

    if name == "REVIEW_ORDINARY_BASELINE":
        if visual_lock_baseline_gate.approved(ep):
            return {"status": "REUSED", "action": name, "runtime": "CODEX_VISION", "reason": "baseline review already valid"}
        frame = visual_lock_baseline_gate.baseline_frame(ep)
        attempt = int(action.get("attempt") or baseline_candidate_pool.review_attempt(ep))
        result = visual_lock_baseline_gate.run_codex_critic(
            ep,
            attempt=attempt,
            codex_raw=None,
            timeout=runtime_timeout_policy.seconds("visual_baseline_critic"),
        )
        status = str(result.get("status") or "FAIL").upper()
        if status == "PASS":
            import image_scheduler
            refreshed = image_scheduler.refresh_queued_visual_lock_references(ep)
            return {"status": status, "action": name, "runtime": "CODEX_VISION", "result": result, "attempt": attempt, "reference_refresh": refreshed}
        if status in {"TECHNICAL_FAILURE", "TECH_FAILED"}:
            return {"status": status, "action": name, "runtime": "CODEX_VISION", "result": result, "attempt": attempt}
        review = visual_lock_baseline_gate.read_json(ep / visual_lock_baseline_gate.REL)
        failed_checks = [
            str(key) for key, value in (review.get("checks") or {}).items()
            if str(value or "").upper() != "PASS"
        ]
        repair = auto_repair_enqueue.enqueue(
            ep,
            frame=frame,
            findings=failed_checks + ([str(review.get("note") or "")] if review.get("note") else []),
            source="VISUAL_BASELINE",
            review_note="Visual Lock ordinary baseline Codex Vision content FAIL",
        )
        if repair.get("status") in {"REPAIR_ENQUEUED", "REPAIR_ALREADY_PENDING"}:
            return {"status": "REPAIR_ENQUEUED", "action": name, "runtime": "CODEX_VISION", "result": result, "repair": repair, "attempt": attempt}
        if repair.get("status") == "NEEDS_USER":
            return {"status": "NEEDS_USER", "action": name, "runtime": "CODEX_VISION", "result": result, "repair": repair, "attempt": attempt}
        return {"status": "FAIL", "action": name, "runtime": "CODEX_VISION", "result": result, "repair": repair, "attempt": attempt}

    if name == "REVIEW_VISUAL_LOCK":
        try:
            visual_lock_v21.bind_from_queue(ep)
        except Exception as exc:
            raise VisionReviewError(f"Visual Lock bind-from-queue failed: {exc}") from exc
        errors = visual_lock_v21.verify(ep, metadata_only=False)
        if not errors:
            return {"status": "REUSED", "action": name, "runtime": "CODEX_VISION", "reason": "Visual Lock review already valid"}
        frames = [int(x) for x in (action.get("frames") or []) if int(x) > 0]
        attempt = int(action.get("attempt") or max(
            max([auto_repair_enqueue.review_attempt(ep, frame) for frame in frames] or [1]),
            visual_lock_candidate_pool.review_attempt(ep),
        ))
        persisted_fail_rows = _persisted_current_visual_lock_fail_rows(
            ep,
            frames=frames,
            attempt=attempt,
        )
        if persisted_fail_rows:
            # Resume an already completed SHA-bound content decision instead of
            # dispatching the same pixels to Vision again after a process-tail failure.
            rc = 2
        else:
            rc = visual_lock_v21.run_critic(
                ep,
                attempt=attempt,
                codex_raw=None,
                timeout=runtime_timeout_policy.seconds("review_critic"),
            )
            if rc == 11:
                persisted_fail_rows = _persisted_current_visual_lock_fail_rows(
                    ep,
                    frames=frames,
                    attempt=attempt,
                )
                if not persisted_fail_rows:
                    return {"status": "TECHNICAL_FAILURE", "action": name, "runtime": "CODEX_VISION", "returncode": rc, "attempt": attempt}
                # The current pixels already have a complete SHA-bound FAIL decision.
                # Continue the normal content-failure closure without re-reviewing them.
                rc = 2
        if rc != 0:
            review = {"calibration": persisted_fail_rows} if persisted_fail_rows else (visual_profile_review_persistence.load(ep) or {})
            repairs = []
            for row in review.get("calibration") or []:
                checks = row.get("checks") or {}
                failed = row.get("issues") not in ([], None) or any(value is not True for value in checks.values())
                if not failed:
                    continue
                try:
                    frame = int(row.get("frame"))
                except Exception:
                    continue
                findings = [str(k) for k, v in checks.items() if v is not True]
                findings.extend(str(x) for x in (row.get("issues") or []))
                repair = auto_repair_enqueue.enqueue(
                    ep,
                    frame=frame,
                    findings=findings,
                    source="VISUAL_LOCK",
                    review_note="Phase5 Visual Lock critic failed actual-pixel admission",
                )
                if repair.get("status") == "NOT_REPAIRABLE" and repair.get("ledger_status") == "PASSED":
                    asset = next(
                        (item for item in visual_lock_v21.calibration_assets(ep)
                         if int(item.get("frame") or 0) == frame),
                        None,
                    )
                    if asset is not None and visual_lock_admission_state.restore_ledger_fail(
                        ep,
                        asset=asset,
                        evidence_note="Current SHA-bound Visual Lock admission failed; reopen bounded candidate lane",
                    ):
                        repair = {
                            "status": "NEEDS_USER",
                            "frame": frame,
                            "reconciled_from_visual_lock_fail": True,
                        }
                repairs.append(repair)
            if repairs and all(r.get("status") in {"REPAIR_ENQUEUED", "REPAIR_ALREADY_PENDING", "NOT_REPAIRABLE"} for r in repairs):
                enqueued = [r for r in repairs if r.get("status") in {"REPAIR_ENQUEUED", "REPAIR_ALREADY_PENDING"}]
                if enqueued:
                    return {"status": "REPAIR_ENQUEUED", "action": name, "runtime": "CODEX_VISION", "returncode": rc, "repairs": repairs, "attempt": attempt}
            if any(r.get("status") == "NEEDS_USER" for r in repairs):
                return {"status": "NEEDS_USER", "action": name, "runtime": "CODEX_VISION", "returncode": rc, "repairs": repairs, "attempt": attempt}
            return {"status": "FAIL", "action": name, "runtime": "CODEX_VISION", "returncode": rc, "repairs": repairs, "attempt": attempt}
        errors = visual_lock_v21.verify(ep, metadata_only=False)
        return {"status": "PASS" if not errors else "FAIL", "action": name, "runtime": "CODEX_VISION", "errors": errors, "attempt": attempt}

    if name == "REVIEW_FINAL_CONTINUATION":
        frames = [str(x).zfill(2) for x in (action.get("frames") or []) if str(x)]
        if not frames:
            raise VisionReviewError("REVIEW_FINAL_CONTINUATION requires at least one frame")
        rc = frame_semantic_review.run_continuation_critic(
            ep,
            targets=frames,
            codex_raw=None,
            timeout=runtime_timeout_policy.seconds("deep_semantic_review"),
        )
        if rc == 0:
            return {"status": "PASS", "action": name, "runtime": "CODEX_VISION", "frames": frames}
        if rc in {2, 3}:
            return {"status": "FAIL", "action": name, "runtime": "CODEX_VISION", "frames": frames, "returncode": rc}
        return {"status": "TECHNICAL_FAILURE", "action": name, "runtime": "CODEX_VISION", "frames": frames, "returncode": rc}

    if name == "REVIEW_FINAL_EXCEPTION":
        frames = [str(x).zfill(2) for x in (action.get("frames") or []) if str(x)]
        if not frames:
            raise VisionReviewError("REVIEW_FINAL_EXCEPTION requires at least one frame")
        rc = frame_semantic_review.run_exception_critic(
            ep,
            targets=frames,
            codex_raw=None,
            timeout=runtime_timeout_policy.seconds("deep_semantic_review"),
        )
        if rc == 0:
            return {"status": "PASS", "action": name, "runtime": "CODEX_VISION", "attempt": 3, "frames": frames}
        if rc in {2, 3}:
            return {"status": "FAIL", "action": name, "runtime": "CODEX_VISION", "attempt": 3, "frames": frames, "returncode": rc}
        return {"status": "TECHNICAL_FAILURE", "action": name, "runtime": "CODEX_VISION", "attempt": 3, "frames": frames, "returncode": rc}

    if name == "MATERIALIZE_REPAIR_WAVE":
        # Reuse the genuine first-pass review. No additional pixel Critic or
        # unauthorized image retry; the Aggregator checks the original SHA
        # receipt, Ledger states and live remaining per-frame image budget.
        import repair_aggregator
        if int(action.get("attempt") or 1) != 1:
            raise VisionReviewError("repair wave requires frozen first-pass review")
        findings = repair_aggregator.collect_first_pass_findings(ep, attempt=1)
        wave = repair_aggregator.materialize_wave(ep, attempt=1, findings=findings)
        status = str(wave.get("status") or "")
        plan = wave.get("plan") or {}
        if status in {"STARTED", "PLANNED"}:
            # Failed prompt tasks must not be falsely reported as enqueued.
            if any(row.get("repairable") and row.get("repair_status") in
                   {"ELIGIBLE", "PROMPT_TECH_FAILED"} for row in plan.get("frames") or []):
                return {"status": "TECHNICAL_FAILURE", "action": name,
                        "runtime": "CODEX_VISION", "repair_wave": wave}
            return {"status": "REPAIR_ENQUEUED", "action": name,
                    "runtime": "CODEX_VISION", "repair_wave": wave}
        if status in {"COMPLETED", "ALREADY_COMPLETED", "SECOND_AUTOMATIC_REPAIR_WAVE_FORBIDDEN"}:
            return {"status": "NEEDS_USER", "action": name,
                    "runtime": "CODEX_VISION", "repair_wave": wave}
        return {"status": "TECHNICAL_FAILURE", "action": name,
                "runtime": "CODEX_VISION", "repair_wave": wave}
    if name == "REVIEW_FINAL_PRODUCTION":
        attempt = int(action.get("attempt") or 1)
        wave_path = ep / "meta/runtime/repair-wave-1.json"
        if wave_path.is_file():
            import repair_aggregator
            current_wave = repair_aggregator.load_wave(ep)
            if current_wave.get("status") == "STARTED":
                receipt_ref = (current_wave.get("source_review_receipts") or [{}])[0].get("path")
                first_pass_evidence = story_json.read_json(ep / str(receipt_ref), default={}) if receipt_ref else {}
                resumed = repair_aggregator.materialize_wave(ep, findings=first_pass_evidence)
                q = scheduler_core.load_queue(ep)
                repair_items = [row for row in q.get("items") or []
                                if row.get("capture_id", "").startswith("repair-wave-1-")]
                eligible_count = int((current_wave.get("summary") or {}).get("eligible_repairs") or 0)
                if resumed.get("status") == "SECOND_AUTOMATIC_REPAIR_WAVE_FORBIDDEN":
                    return {"status":"NEEDS_USER","action":name,"runtime":"CODEX_VISION","repair_wave":resumed}
                if len(repair_items) < eligible_count or any(row.get("status") in {"queued","running","tech_failed","blocked"} for row in repair_items):
                    return {"status":"REPAIR_ENQUEUED","action":name,"runtime":"CODEX_VISION",
                            "attempt":attempt,"repair_wave":resumed}
        if wave_path.is_file() and attempt > 1:
            try:
                import runtime_observability
                import logical_asset_identity
                runtime_observability.safe_record_runtime_event(ep,"REPAIR_REVIEW_STARTED",
                    episode_id=logical_asset_identity.episode_id(ep),step="REPAIR_REVIEW",status="started")
            except Exception:
                pass
        rc = frame_semantic_review.run_critic(
            ep,
            attempt=attempt,
            codex_raw=None,
            timeout=runtime_timeout_policy.seconds("deep_semantic_review"),
        )
        if rc == 0:
            if wave_path.is_file() and attempt > 1:
                import repair_aggregator
                plan = repair_aggregator.load_wave(ep)
                outcomes = {str(row.get("frame_id")):"PASS" for row in plan.get("frames") or [] if row.get("repairable")}
                repair_aggregator.finalize_wave(ep,repair_reviews=outcomes)
                try:
                    runtime_observability.safe_record_runtime_event(ep,"REPAIR_REVIEW_FINISHED",
                        episode_id=logical_asset_identity.episode_id(ep),step="REPAIR_REVIEW",status="PASS")
                except Exception:
                    pass
            return {"status": "PASS", "action": name, "runtime": "CODEX_VISION", "attempt": attempt}
        if rc not in {2, 3}:
            return {"status": "TECHNICAL_FAILURE", "action": name, "runtime": "CODEX_VISION", "attempt": attempt, "returncode": rc}
        evidence_path = ep / "meta" / f"frame-semantic-candidate-attempt-{attempt}.json"
        evidence = story_json.read_json(evidence_path, default={}) if evidence_path.is_file() else {}
        failed_frames = [str(x).zfill(2) for x in (evidence.get("failed_frames") or [])]
        if wave_path.is_file() and attempt > 1:
            import repair_aggregator
            plan = repair_aggregator.load_wave(ep)
            failed = set(failed_frames)
            outcomes = {str(row.get("frame_id")): ("NEEDS_USER" if str(row.get("frame_id")) in failed else "PASS")
                        for row in plan.get("frames") or [] if row.get("repairable")}
            finalized = repair_aggregator.finalize_wave(ep,repair_reviews=outcomes)
            try:
                runtime_observability.safe_record_runtime_event(ep,"REPAIR_REVIEW_FINISHED",
                    episode_id=logical_asset_identity.episode_id(ep),step="REPAIR_REVIEW",status="NEEDS_USER")
            except Exception:
                pass
            return {"status":"NEEDS_USER","action":name,"runtime":"CODEX_VISION",
                    "attempt":attempt,"frames":failed_frames,"repair_wave":finalized}
        import repair_aggregator
        wave = repair_aggregator.materialize_wave(ep,attempt=attempt,findings=evidence)
        if wave.get("status") in {"STARTED","PLANNED"}:
            return {"status":"REPAIR_ENQUEUED","action":name,"runtime":"CODEX_VISION",
                    "attempt":attempt,"repair_wave":wave}
        ledger = production_ledger.load_authority(ep, default={}) or {}
        needs_user = [
            str(key).zfill(2) for key, value in ((ledger.get("frames") or {}).items())
            if isinstance(value, dict) and value.get("status") == "NEEDS_USER"
        ]
        if needs_user:
            return {"status": "NEEDS_USER", "action": name, "runtime": "CODEX_VISION", "attempt": attempt, "frames": needs_user, "repair_wave": wave}
        return {"status": "NEEDS_USER" if wave.get("status") == "COMPLETED" else "FAIL",
                "action": name, "runtime": "CODEX_VISION", "attempt": attempt,
                "returncode": rc, "repair_wave": wave}

    if name == "REVIEW_FINAL_PATCH":
        frames = [str(x).zfill(2) for x in (action.get("frames") or []) if str(x)]
        if not frames:
            raise VisionReviewError("REVIEW_FINAL_PATCH requires at least one frame")
        attempt = int(action.get("attempt") or 2)
        rc = frame_semantic_review.run_patch_critic(
            ep,
            targets=frames,
            attempt=attempt,
            codex_raw=None,
            timeout=runtime_timeout_policy.seconds("deep_semantic_review"),
        )
        if rc == 0:
            return {"status": "PASS", "action": name, "runtime": "CODEX_VISION", "attempt": attempt, "frames": frames}
        if rc not in {2, 3}:
            return {"status": "TECHNICAL_FAILURE", "action": name, "runtime": "CODEX_VISION", "attempt": attempt, "frames": frames, "returncode": rc}
        ledger = production_ledger.load_authority(ep, default={}) or {}
        needs_user = [
            str(key).zfill(2) for key, value in ((ledger.get("frames") or {}).items())
            if isinstance(value, dict) and value.get("status") == "NEEDS_USER"
        ]
        return {
            "status": "NEEDS_USER" if needs_user else "FAIL",
            "action": name,
            "runtime": "CODEX_VISION",
            "attempt": attempt,
            "frames": needs_user or frames,
            "returncode": rc,
        }

    batch_ids = [str(x) for x in (action.get("batch_ids") or production_batch_review.pending(ep)) if str(x)]
    if not batch_ids:
        return {"status": "REUSED", "action": name, "runtime": "CODEX_VISION", "reason": "no pending generated batch review"}
    reviewed = []
    for batch_id in batch_ids:
        try:
            reviewed.append(production_batch_review.run_codex_review(
                ep,
                batch_id,
                attempt=int(action.get("attempt") or 1),
                codex_raw=None,
                timeout=runtime_timeout_policy.seconds("review_critic"),
            ))
        except Exception as exc:
            # A malformed or incomplete isolated critic response is a bounded
            # technical failure. Keep the resident Runner alive so the next
            # cycle can retry the review instead of losing the whole queue.
            return {
                "status": "TECHNICAL_FAILURE",
                "action": name,
                "runtime": "CODEX_VISION",
                "batch_ids": batch_ids,
                "reviewed": reviewed,
                "error": str(exc),
            }
    return {"status": "PASS", "action": name, "runtime": "CODEX_VISION", "batch_ids": batch_ids, "reviews": reviewed}
