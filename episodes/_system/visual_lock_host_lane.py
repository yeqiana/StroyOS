"""Canonical CODEX Visual Lock host lane (only called by an explicit Driver).

An AI text worker acknowledging its instructions is not four pixel images.
Existing authorities own the only valid progression:
- Visual Lock V2.1 selector owns the 4 distinct SHA-bound frame plan.
- Image Scheduler owns attempts / bounded image concurrency and 1+3 barrier.
- Independent Codex Vision owns pixel review; Machine Action owns stage PASS.
This module neither manufactures an image nor writes a review decision.
"""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import story_json

PLAN_REL=Path("meta/visual-lock-plan.json")
GATES_REL=Path("meta/story-gates.json")
REQUIRED_ANCHORS=("location","key_prop","weather_time")
ROLES=("ordinary_baseline","worst_capture_condition",
       "first_major_anomaly","high_impact_admission")


class VisualLockHostBlocked(RuntimeError):
    """Fail closed without replaying the generic Visual Lock text worker."""


def _json(path: Path) -> dict:
    result=story_json.read_json(path,default={})
    return result if isinstance(result,dict) else {}


def _anchor_sources(ep: Path) -> dict:
    """Resolve physical anchors from authored, frozen PREIMAGE sources only."""
    world=_json(ep/"meta/world-state.json")
    temporal=_json(ep/"meta/temporal-continuity.json")
    state=world.get("initial_state") or {}
    if not isinstance(state,dict):
        raise VisualLockHostBlocked("WORLD_INITIAL_STATE_INVALID")
    recorder=state.get("recorder") or {}
    frames=temporal.get("frames") or []
    first=frames[0] if isinstance(frames,list) and frames and isinstance(frames[0],dict) else {}
    props=state.get("props") or {}
    key_prop=(next((str(v).strip() for v in props.values()
                    if isinstance(v,str) and v.strip()),"")
              if isinstance(props,dict) else "")
    if not key_prop:
        key_prop=str(recorder.get("active_device") or "").strip()
    location=str(state.get("location") or "").strip()
    daypart=str(first.get("daypart") or state.get("time") or "").strip()
    weather=str(first.get("weather") or state.get("weather") or "").strip()
    values={"location":location,"key_prop":key_prop,
            "weather_time":f"{daypart}; {weather}" if daypart and weather else ""}
    if (world.get("status")!="LOCKED" or temporal.get("status")!="LOCKED"
            or not all(values.values())):
        raise VisualLockHostBlocked("FROZEN_CONTINUITY_ANCHOR_SOURCE_MISSING")
    return values


def _same_plan(a: dict,b: dict)->bool:
    rows1=a.get("items") or []
    rows2=b.get("items") or []
    if len(rows1)!=4 or len(rows2)!=4:
        return False
    return all(
        isinstance(x,dict) and isinstance(y,dict)
        and all(str(x.get(k) or "")==str(y.get(k) or "")
                for k in ("role","id","frame","contract_sha256"))
        for x,y in zip(rows1,rows2)
    )


def ensure_plan(ep: Path) -> dict:
    """One deterministic, reusable plan; never silently replace source drift."""
    import visual_lock_v21
    ep=Path(ep).resolve()
    proposed=visual_lock_v21.choose_plan(ep)  # validates all current contracts
    items=proposed["items"]
    frames=[int(x["frame"]) for x in items]
    if (len(frames)!=4 or len(set(frames))!=4
            or tuple(x["role"] for x in items)!=ROLES):
        raise VisualLockHostBlocked("FOUR_DISTINCT_VISUAL_FRAMES_NOT_PROVEN")
    existing=_json(ep/PLAN_REL)
    if existing and not _same_plan(existing,proposed):
        raise VisualLockHostBlocked("EXISTING_VISUAL_PLAN_SOURCE_DRIFT_REQUIRES_RECONCILIATION")
    anchors=_anchor_sources(ep)
    g=_json(ep/GATES_REL)
    if not g:
        raise VisualLockHostBlocked("VISUAL_GATE_SOURCE_MISSING")
    visual=g.get("visual") or {}
    continuity=visual.get("continuity") or {}
    prior=continuity.get("anchors") or {}
    for name in REQUIRED_ANCHORS:
        value=prior.get(name)
        if value is not None and str(value).strip() and str(value).strip()!=anchors[name]:
            # A prior human-locked anchor is not silently overwritten by a
            # different derived assertion (both could look superficially valid).
            raise VisualLockHostBlocked("FROZEN_VISUAL_ANCHOR_CONFLICT:"+name)
    if not existing:
        visual_lock_v21.prepare(ep)
    g=_json(ep/GATES_REL)
    visual=g.setdefault("visual",{})
    continuity=visual.setdefault("continuity",{})
    fixed=continuity.setdefault("anchors",{})
    changed=False
    for name,value in anchors.items():
        if not str(fixed.get(name) or "").strip():
            fixed[name]=value
            changed=True
    if visual.get("admission_frames")!=sorted(frames):
        if visual.get("admission_frames"):
            raise VisualLockHostBlocked("EXISTING_ADMISSION_FRAMES_DRIFT")
        visual["admission_frames"]=sorted(frames)
        changed=True
    if changed:
        # Do not set authenticity or visual_admission PASS. They require real
        # image pixels, independent review, and a canonical machine finalizer.
        story_json.write_json(ep/GATES_REL,g)
    return {"status":"REUSED" if existing else "PLANNED",
            "frames":frames,"anchors":anchors,"model_calls":0,
            "image_attempts_reserved":0}


def _run_native_image_scheduler(ep: Path, *, workers: int, timeout: int,
                                codex: str | None) -> int:
    """Keep the Scheduler's process-scoped MySQL role out of the Driver.

    The normal CLI owns real image attempts and provider retries; this helper
    never launches a model by itself or changes the shared budget.
    """
    script=Path(__file__).resolve().parent/"image_scheduler.py"
    cmd=[sys.executable,str(script),"run",str(ep),
         "--max-workers",str(workers),"--timeout",str(timeout)]
    if codex:
        cmd.extend(["--codex",str(codex)])
    return subprocess.run(cmd,cwd=Path(__file__).resolve().parents[2],
                          check=False,capture_output=True,text=True,
                          encoding="utf-8",errors="replace").returncode


def run(ep: Path, *, codex: str|None=None, timeout: int=3600) -> dict:
    """Continue 1 baseline + 3 reviews, never skipping a bounded source gate."""
    import image_scheduler
    import visual_lock_baseline_gate
    import visual_lock_v21
    import vision_review_executor
    import machine_action_executor
    import episode_state_persistence

    ep=Path(ep).resolve()
    if (episode_state_persistence.load(ep) or {}).get("current_state")!="STORYBOARD_LOCKED":
        raise VisualLockHostBlocked("VISUAL_LOCK_STAGE_NOT_STORYBOARD_LOCKED")
    plan=ensure_plan(ep)
    images=ep/"prompts/production"
    for frame in plan["frames"]:
        if not (images/f"{frame:02d}.txt").is_file():
            raise VisualLockHostBlocked(f"VISUAL_LOCK_PROMPT_MISSING:{frame:02d}")
    image_scheduler.import_visual_lock(ep,images)
    first=_run_native_image_scheduler(
        ep,workers=4,timeout=int(timeout),codex=codex)
    if first not in {0,20}:
        raise VisualLockHostBlocked(f"VISUAL_LOCK_SCHEDULER_BASELINE_BLOCKED:rc={first}")

    if not visual_lock_baseline_gate.approved(ep):
        try:
            visual_lock_baseline_gate.generated_baseline(ep)
        except (OSError,ValueError) as exc:
            raise VisualLockHostBlocked("BASELINE_ACTUAL_PIXELS_NOT_READY") from exc
        reviewed=vision_review_executor.execute(
            ep,{"executor":"CODEX_VISION","action":"REVIEW_ORDINARY_BASELINE"})
        if reviewed.get("status") not in {"PASS","REUSED"}:
            raise VisualLockHostBlocked("BASELINE_REVIEW_NOT_PASSED:"
                                        +str(reviewed.get("status")))
    if not visual_lock_baseline_gate.approved(ep):
        raise VisualLockHostBlocked("BASELINE_PIXEL_SHA_NOT_APPROVED")

    second=_run_native_image_scheduler(
        ep,workers=3,timeout=int(timeout),codex=codex)
    if second != 0:
        raise VisualLockHostBlocked(f"VISUAL_LOCK_REMAINING_THREE_NOT_COMPLETE:rc={second}")
    # The real-pixel bind enforces provenance: each image must have a matching
    # Generation Attempt and current Frame Contract SHA.
    visual_lock_v21.bind_from_queue(ep)
    if visual_lock_v21.verify(ep):
        reviewed=vision_review_executor.execute(
            ep,{"executor":"CODEX_VISION","action":"REVIEW_VISUAL_LOCK",
                "frames":plan["frames"]})
        if reviewed.get("status") not in {"PASS","REUSED"}:
            raise VisualLockHostBlocked("FOUR_FRAME_INDEPENDENT_REVIEW_NOT_PASSED:"
                                        +str(reviewed.get("status")))
    if visual_lock_v21.verify(ep):
        raise VisualLockHostBlocked("FOUR_PIXEL_REVIEW_SOURCE_UNVERIFIED")
    final=machine_action_executor.execute(
        ep,{"executor":"MACHINE","action":"FINALIZE_VISUAL_LOCK"})
    if final.get("status") not in {"PASS","REUSED"}:
        raise VisualLockHostBlocked("FINAL_VISUAL_LOCK_NOT_ACCEPTED")
    if (episode_state_persistence.load(ep) or {}).get("current_state")!="VISUAL_CALIBRATED":
        raise VisualLockHostBlocked("CANONICAL_VISUAL_STAGE_NOT_ADVANCED")
    return {"status":"PASS","source":"CANONICAL_HOST_PIXEL_LANE",
            "frames":plan["frames"],"review":final.get("report")}
