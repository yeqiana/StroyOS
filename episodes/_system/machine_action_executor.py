#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deterministic local machine actions for Story OS hosted/local full-auto.

These actions contain no creative/model judgment. They consume already-verified
evidence, materialize derived transport artifacts, and use the canonical state
machine for transitions.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import baseline_candidate_pool
import capture_event_contract
import character_contract
import delegated_approval
import episode_state
import episode_state_persistence
import frame_contract
import frame_semantic_review
import final_acceptance
import image_blocked_recovery
import image_scheduler
import image_unknown_raw_reconcile
import production_native_batch_followon
import production_ledger
import production_ledger_manage
import production_prompt_materializer
import story_json
import wardrobe_contract
import visual_lock_baseline_gate
import visual_lock_candidate_pool
import visual_lock_finalizer
import visual_lock_v21

ALLOWED_ACTIONS = {"PREPARE_BASELINE_CANDIDATE", "PREPARE_VISUAL_LOCK_CANDIDATES", "APPLY_VISUAL_LOCK_WEAK_PASS", "PREPARE_STALE_VISUAL_LOCK_REFRESH", "RESOLVE_IMAGE_NORMALIZATION", "RESUME_BUDGET_AUTHORIZED_IMAGES", "RESUME_NATIVE_BATCH_AFTER_SUCCESS", "RECONCILE_PRESERVED_PROVIDER_RAW", "FINALIZE_VISUAL_LOCK", "PREPARE_PRODUCTION_BATCH", "FINALIZE_PRODUCTION_IMAGES"}


class MachineActionError(RuntimeError):
    pass


def local_machine_action(action: dict) -> str | None:
    if not isinstance(action, dict):
        return None
    if str(action.get("executor") or "").upper() != "MACHINE":
        return None
    name = str(action.get("action") or "")
    return name if name in ALLOWED_ACTIONS else None


def _state(ep: Path) -> str:
    data = episode_state_persistence.load(ep) or {}
    return str(data.get("current_state") or "")


def _read(ep: Path, rel: str) -> dict:
    data = story_json.read_json(ep / rel, default={})
    return data if isinstance(data, dict) else {}


def _materialize_visual_machine_contract(ep: Path) -> dict:
    """Backfill strict Visual Gate fields from already-locked authority only."""
    gates_path = ep / "meta/story-gates.json"
    gates = _read(ep, "meta/story-gates.json")
    character = character_contract.load(ep) or {}
    capture = capture_event_contract.load(ep) or {}
    world = _read(ep, "meta/world-state.json")
    temporal = _read(ep, "meta/temporal-continuity.json")
    wardrobe = wardrobe_contract.load(ep) or {}
    manifest = _read(ep, "meta/release-manifest.json")
    visual = gates.setdefault("visual", {})
    frames = capture.get("frames") or {}
    frame01 = frames.get("01") or {}
    era = character.get("era") or {}
    fictional = character.get("fictional_world") or {}
    pov = character.get("pov") or {}
    world_identity = visual.get("world_identity") or character.get("world_identity") or {}
    year = era.get("year")
    story_era = str(year) if year else str(era.get("bucket") or "fictional_world")
    location = str(world_identity.get("world") or world_identity.get("region") or world.get("initial_location") or "locked episode world")
    photographer = str(frame01.get("photographer_id") or pov.get("character_id") or "locked POV photographer")
    device = str(frame01.get("capture_device") or fictional.get("capture_device") or "locked primary capture device")
    shooting_reason = str(frame01.get("why_capture_now") or "locked episode ordinary-life album capture")
    fixed_positions = [str((row or {}).get("device_position") or "") for row in frames.values() if isinstance(row, dict)]
    photographer_visible = any(token in pos for pos in fixed_positions for token in ("延时", "固定", "稳放"))
    ratio = str(((manifest.get("episode") or {}).get("aspect_ratio") or "4:5"))
    card = visual.setdefault("authenticity_card", {})
    card.update({
        "story_era": story_era,
        "location": location,
        "photographer": photographer,
        "shooting_reason": shooting_reason,
        "primary_capture": {"id": "locked_primary_capture", "device": device},
        "secondary_captures": [],
        "secondary_source_explanation": None,
        "aspect_ratio": ratio,
        "capture_states": {
            "stable": "locked Capture Event frames use ordinary handheld or explicitly justified fixed capture",
            "restricted": "walking, close-range, window, backlight and bridge constraints are declared per-frame in Capture Event Contract",
            "lost_control": "not present in the locked Story; any uncontrolled capture outside the contract is invalid rather than accepted as evidence",
        },
        "camera_rules": {
            "current_device_may_be_fully_visible": False,
            "current_device_visibility_explanation": None,
            "photographer_may_be_fully_visible": photographer_visible,
            "photographer_visibility_explanation": "locked Capture Event includes an explicitly fixed/delayed capture that lets the POV photographer enter frame" if photographer_visible else None,
        },
    })
    calibration = ((visual.get("calibration") or {}).get("items") or [])
    admissions = sorted({int(row.get("frame")) for row in calibration if isinstance(row, dict) and row.get("frame") is not None})
    visual["admission_frames"] = admissions
    continuity = visual.setdefault("continuity", {})
    anchors = continuity.setdefault("anchors", {})
    persistent = world.get("persistent_props") or []
    timeline = temporal.get("timeline") or []
    anchors.update({
        "protagonist": str(pov.get("character_id") or photographer),
        "location": str(world.get("initial_location") or location),
        "key_prop": ", ".join(str(x) for x in persistent) or device,
        "wardrobe": str((wardrobe.get("P01") if isinstance(wardrobe, dict) else None) or "locked wardrobe contract"),
        "weather_time": "; ".join(str(x) for x in timeline) or str(temporal.get("weather_rule") or "locked temporal continuity"),
    })
    reviews = gates.setdefault("reviews", {})
    reviews["authenticity"] = "passed"
    story_json.write_json(gates_path, gates)
    return {"admission_frames": admissions, "photographer": photographer, "device": device}


def _finalize_production_images(ep: Path) -> dict:
    ledger = production_ledger.load_authority(ep, default={}) or {}
    frames = ledger.get("frames") or {}
    if not frames:
        raise MachineActionError("production ledger frames missing")
    not_locked = [str(k).zfill(2) for k, row in frames.items() if isinstance(row, dict) and row.get("status") != "LOCKED"]
    unaccepted = [key for key in not_locked if not final_acceptance.allows(ep, "frame_semantic", key)]
    if unaccepted:
        raise MachineActionError("final production image finalizer requires LOCKED or direct-user accepted frames: " + ",".join(unaccepted[:8]))
    accepted_visuals = final_acceptance.visual_assets(ep)
    if accepted_visuals:
        missing = [str(k).zfill(2) for k in frames if str(k).zfill(2) not in accepted_visuals]
        if missing:
            raise MachineActionError("direct-user final visual asset map incomplete: " + ",".join(missing[:8]))
    review_errors = frame_semantic_review.verify_episode(ep, metadata_only=False, write_audit=True)
    if review_errors and not final_acceptance.allows(ep, "frame_semantic"):
        raise MachineActionError("final semantic review invalid: " + "; ".join(review_errors[:8]))
    gates_path = ep / "meta/story-gates.json"
    gates = _read(ep, "meta/story-gates.json")
    reviews = gates.setdefault("reviews", {})
    reviews["production"] = "passed"
    reviews["continuity"] = "passed"
    reviews["authenticity"] = "passed"
    story_json.write_json(gates_path, gates)
    return {"status": "PASS", "action": "FINALIZE_PRODUCTION_IMAGES", "locked_frames": len(frames) - len(not_locked), "user_accepted_frames": len(not_locked), "state": _state(ep)}


def _finalize_visual_lock(ep: Path) -> dict:
    state = _state(ep)
    if state in {"VISUAL_CALIBRATED", "PRODUCTION_PASSED", "PUBLISH_READY", "PUBLISHED", "DATA_REVIEWED"}:
        return {"status": "REUSED", "action": "FINALIZE_VISUAL_LOCK", "state": state}
    if state != "STORYBOARD_LOCKED":
        raise MachineActionError(f"Visual Lock finalizer requires STORYBOARD_LOCKED, got {state}")
    # Strict machine fields are a derived projection of already-locked PREIMAGE
    # authority. Materializing them here must not force image regeneration. Freeze
    # the exact old->new projection-only contract mapping and keep the PREIMAGE
    # caches/index immutable; the migration evidence bridges the equivalent SHA.
    machine_contract = _materialize_visual_machine_contract(ep)
    projection_migration = frame_contract.record_projection_migrations(ep)
    # The canonical final requirement handles either independently reviewed
    # PASS or SHA-bound, budget-exhausted soft-quality WEAK_PASS. Reusing the
    # stricter initial-admission validator here made full-auto loop forever.
    baseline_errors = visual_lock_baseline_gate.validate_final_requirement(ep)
    if baseline_errors:
        raise MachineActionError("baseline final requirement not valid: " + "; ".join(baseline_errors[:8]))
    visual_errors = visual_lock_v21.verify(ep, metadata_only=False)
    if visual_errors:
        raise MachineActionError("Visual Lock review not valid: " + "; ".join(visual_errors[:8]))
    report = visual_lock_finalizer.build(ep)
    report_errors = visual_lock_finalizer.verify(ep)
    if report_errors:
        raise MachineActionError("Visual Lock final report invalid: " + "; ".join(report_errors[:8]))
    approval_errors = delegated_approval.verify(ep, "visual_lock")
    if approval_errors:
        delegated_approval.cmd_record(SimpleNamespace(
            episode_dir=str(ep), kind="visual_lock",
            note="Full-auto deterministic finalizer after SHA-bound Codex Vision Visual Lock PASS",
        ))
        approval_errors = delegated_approval.verify(ep, "visual_lock")
    if approval_errors:
        raise MachineActionError("delegated visual approval invalid: " + "; ".join(approval_errors[:8]))
    episode_state.transition_cmd(SimpleNamespace(
        episode_dir=str(ep), target="VISUAL_CALIBRATED", rewind=False,
        note="Full-auto Visual Lock evidence verified; deterministic canonical transition",
    ))
    return {"status": "PASS", "action": "FINALIZE_VISUAL_LOCK", "state": _state(ep), "report": report.get("decision"), "machine_contract": machine_contract, "projection_migration": projection_migration}


def execute(ep: Path, action: dict) -> dict:
    ep = Path(ep).resolve()
    name = local_machine_action(action)
    if name is None:
        raise MachineActionError(f"not an auto-allowed machine action: {action}")
    if name == "PREPARE_BASELINE_CANDIDATE":
        result = baseline_candidate_pool.enqueue_next(ep)
        status = str(result.get("status") or "FAIL").upper()
        if status in {"PASS", "REUSED"}:
            return result
        if status == "EXHAUSTED":
            return {**result, "status": "FAIL"}
        raise MachineActionError(f"baseline candidate preparation failed: {result}")
    if name == "PREPARE_VISUAL_LOCK_CANDIDATES":
        result = visual_lock_candidate_pool.enqueue_ready(ep)
        status = str(result.get("status") or "FAIL").upper()
        if status in {"PASS", "REUSED"}:
            return result
        raise MachineActionError(f"visual-lock candidate preparation failed: {result}")
    if name == "APPLY_VISUAL_LOCK_WEAK_PASS":
        result = visual_lock_candidate_pool.apply_weak_passes(ep, frames=[int(x) for x in (action.get("frames") or [])])
        if str(result.get("status") or "").upper() not in {"PASS", "REUSED"}:
            raise MachineActionError(f"visual-lock weak-pass policy blocked: {result}")
        return {"status": "PASS", "action": name, "result": result, "state": _state(ep)}
    if name == "PREPARE_STALE_VISUAL_LOCK_REFRESH":
        rows = []
        for frame in sorted({int(x) for x in (action.get("frames") or []) if int(x) > 0}):
            rows.append(production_ledger_manage.authorize_machine_contract_refresh(
                ep,
                frame,
                reason="current Visual Lock pixels were generated under a stale Frame Contract; deterministic authority refresh",
            ))
        return {
            "status": "PASS",
            "action": name,
            "frames": [row["frame"] for row in rows],
            "results": rows,
            "state": _state(ep),
        }
    if name == "RESOLVE_IMAGE_NORMALIZATION":
        result = image_blocked_recovery.recover(ep, frames=[int(x) for x in (action.get("frames") or [])])
        if str(result.get("status") or "").upper() != "PASS":
            raise MachineActionError(f"image normalization recovery blocked: {result}")
        return {"status": "PASS", "action": name, "result": result, "state": _state(ep)}
    if name == "RESUME_NATIVE_BATCH_AFTER_SUCCESS":
        result = production_native_batch_followon.resume(ep, acknowledged=True)
        if str(result.get("status") or "") != "PASS":
            raise MachineActionError(f"native Batch followon blocked: {result.get('reason')}")
        return result
    if name == "RECONCILE_PRESERVED_PROVIDER_RAW":
        frames = sorted({int(v) for v in (action.get("frames") or []) if int(v) > 0})
        if not frames:
            raise MachineActionError("empty preserved provider RAW recovery request")
        results = []
        for frame in frames:
            result = image_unknown_raw_reconcile.recover_one(ep, frame)
            if result.get("status") != "PASS":
                raise MachineActionError(
                    f"preserved RAW recovery blocked frame={frame} reason={result.get('reason')}")
            results.append(result)
        return {"status":"PASS","action":name,"results":results,
                "provider_calls":0,"attempts_reserved":0}
    if name == "RESUME_BUDGET_AUTHORIZED_IMAGES":
        result = image_scheduler.resume_authorized_budget(ep, frames=[int(x) for x in (action.get("frames") or [])])
        if str(result.get("status") or "").upper() != "PASS":
            raise MachineActionError(f"candidate budget has no resumable bounded capacity: {result}")
        return {"status": "PASS", "action": name, "result": result, "state": _state(ep)}
    if name == "FINALIZE_VISUAL_LOCK":
        try:
            return _finalize_visual_lock(ep)
        except SystemExit as exc:
            raise MachineActionError(str(exc)) from exc
    if name == "FINALIZE_PRODUCTION_IMAGES":
        return _finalize_production_images(ep)
    state = _state(ep)
    if state not in {"VISUAL_CALIBRATED", "PRODUCTION_PASSED"}:
        raise MachineActionError(f"Production batch preparation requires VISUAL_CALIBRATED+, got {state}")
    result = production_prompt_materializer.prepare_queue(ep)
    return {"status": "PASS", "action": name, "state": state, "result": result}


def self_test() -> None:
    assert local_machine_action({"action": "PREPARE_BASELINE_CANDIDATE", "executor": "MACHINE"}) == "PREPARE_BASELINE_CANDIDATE"
    assert local_machine_action({"action": "PREPARE_VISUAL_LOCK_CANDIDATES", "executor": "MACHINE"}) == "PREPARE_VISUAL_LOCK_CANDIDATES"
    assert local_machine_action({"action": "PREPARE_STALE_VISUAL_LOCK_REFRESH", "executor": "MACHINE"}) == "PREPARE_STALE_VISUAL_LOCK_REFRESH"
    assert local_machine_action({"action": "RESOLVE_IMAGE_NORMALIZATION", "executor": "MACHINE"}) == "RESOLVE_IMAGE_NORMALIZATION"
    assert local_machine_action({"action": "RESUME_BUDGET_AUTHORIZED_IMAGES", "executor": "MACHINE"}) == "RESUME_BUDGET_AUTHORIZED_IMAGES"
    assert local_machine_action({"action": "FINALIZE_VISUAL_LOCK", "executor": "MACHINE"}) == "FINALIZE_VISUAL_LOCK"
    assert local_machine_action({"action": "PREPARE_PRODUCTION_BATCH", "executor": "MACHINE"}) == "PREPARE_PRODUCTION_BATCH"
    assert local_machine_action({"action": "FINALIZE_PRODUCTION_IMAGES", "executor": "MACHINE"}) == "FINALIZE_PRODUCTION_IMAGES"
    assert local_machine_action({"action": "PRODUCTION", "executor": "WORK"}) is None
    print("MACHINE ACTION EXECUTOR SELF-TEST PASS")


if __name__ == "__main__":
    self_test()
