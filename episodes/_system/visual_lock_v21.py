#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Story OS V2.1 Phase 5 unified four-admission Visual Lock.

V2.1 roles:
1 ordinary_baseline
2 worst_capture_condition
3 first_major_anomaly
4 high_impact_admission

The review judges actual pixels and binds each image to the current Resolved Frame Contract.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from story_os_contract import FOUR_ADMISSION_V21_POLICY, story_os_version
from visual_profile import compile_prompt_contract
import environment_contract
import frame_contract
import production_queue_store
import scheduler_core
import character_visual_contract
import visual_lock_baseline_gate
import visual_narrative_core_v22  # STORY_OS_V22_VISUAL_NARRATIVE_CORE
import propagation_core_gate
import shot_progression_gate
import critic_runtime_v211  # STORY_OS_V211_PERF_RECOVERY
import codex_user_runner
import codex_critic_runner as critic_runner
import runtime_router
import runtime_provenance
import product_review_adapter
import storyos_config
import story_json
import visual_review_schema
import runtime_timeout_policy
import visual_lock_admission_state
import episode_state_persistence
import visual_profile_review_persistence
import production_ledger

ROOT = Path(__file__).resolve().parents[2]
GATES_REL = Path("meta/story-gates.json")
REVIEW_REL = visual_profile_review_persistence.LEGACY_REL
PLAN_REL = Path("meta/visual-lock-plan.json")
CANDIDATE_REL = Path("meta/.visual-lock-review.candidate.json")
MIN_VERSION = (2, 1, 0)
ROLES = (
    "ordinary_baseline",
    "worst_capture_condition",
    "first_major_anomaly",
    "high_impact_admission",
)
BASE_CHECKS = (
    "visual_profile_match",
    "reality_first",
    "ordinary_life_density",
    "available_light",
    "unposed_capture",
    "not_cinematic",
    "causal_imperfection",
    "environment_physics_fidelity",
    "capture_credibility",
    "anomaly_scale_delivery",
    "scale_reference_fidelity",
)
V22_CHECKS = (
    "camera_authorship_physical",
    "moment_capture_credibility",
    "camera_defect_physics",
    "screen_content_physics",
)
V221_CHECKS = (
    "world_identity_fidelity",
    "character_appearance_anchor_fidelity",
    "cultural_environment_fidelity",
)

def checks_for_version(version: str) -> tuple[str, ...]:
    checks = BASE_CHECKS + (V22_CHECKS if version_tuple(version) >= (2, 2, 0) else ())
    if version_tuple(version) >= (2, 2, 1):
        checks += V221_CHECKS
    return checks


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> dict:
    return story_json.read_json(path)


def write_json(path: Path, data: dict) -> None:
    story_json.write_json(path, data)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def version_tuple(raw: object) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in str(raw or "").split("."))
    except Exception:
        return (0,)


def episode_version(ep: Path) -> str:
    versions = []
    try:
        raw = str((episode_state_persistence.load(Path(ep).resolve()) or {}).get("tool_version") or "")
        vt = version_tuple(raw)
        if vt != (0,):
            versions.append((vt, raw))
    except Exception:
        pass
    for rel in ("meta/release-manifest.json", "meta/story-gates.json"):
        p = ep / rel
        if not p.is_file():
            continue
        try:
            raw = str(read_json(p).get("tool_version") or "")
            vt = version_tuple(raw)
            if vt != (0,):
                versions.append((vt, raw))
        except Exception:
            continue
    return max(versions, key=lambda x: x[0])[1] if versions else ""


def required(ep: Path) -> bool:
    if version_tuple(episode_version(ep)) < MIN_VERSION:
        return False
    p = ep / GATES_REL
    if not p.is_file():
        return False
    try:
        gates = read_json(p)
        calibration = ((gates.get("visual") or {}).get("calibration") or {})
        if calibration.get("policy") == FOUR_ADMISSION_V21_POLICY:
            return True
        # V2.1+ strict episodes with an old three-slot calibration schema still require
        # the four-admission gate. prepare() performs the schema migration when invoked.
        return ((gates.get("machine_contract") or {}).get("strict") is True)
    except Exception:
        return False


def resolve_ep(raw: str) -> Path:
    ep = Path(raw).resolve()
    if not ep.is_dir():
        raise SystemExit(f"episode directory not found: {ep}")
    try:
        ep.relative_to(ROOT.resolve())
    except ValueError:
        raise SystemExit("episode must be inside repository")
    return ep


def repo_file(raw: object) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("calibration asset_path missing")
    p = Path(raw.strip())
    p = p.resolve() if p.is_absolute() else (ROOT / p).resolve()
    try:
        p.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise ValueError(f"calibration path escapes repository: {raw}") from exc
    if not p.is_file():
        raise ValueError(f"calibration image missing: {raw}")
    return p


def repo_rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def _severity(env: dict) -> int:
    score = 0
    condition = str(env.get("condition") or "").lower()
    visibility = str(env.get("visibility") or "").lower()
    wind = str(env.get("wind") or "").lower()
    precipitation = str(env.get("precipitation") or "").lower()
    difficult = ("storm","rain","snow","fog","mist","dust","sand","night","dark","low","poor","strong","heavy","暴","雨","雪","雾","沙","夜","暗")
    score += sum(2 for token in difficult if token in condition)
    score += sum(2 for token in difficult if token in visibility)
    score += sum(1 for token in difficult if token in wind)
    score += sum(2 for token in difficult if token in precipitation)
    score += min(5, len(env.get("physical_cues") or []))
    score += min(3, len(env.get("conditional_effects") or []))
    return score


def _rows(ep: Path) -> list[dict]:
    total = frame_contract.frame_count(ep)
    rows = []
    for n in range(1, total + 1):
        resolved = environment_contract.resolve_frame(ep, n)
        d = resolved.get("directive") or {}
        shot = shot_progression_gate.resolve_frame(ep, n).get("shot_progression") or {}
        rows.append({
            "frame": n,
            "mode": str(d.get("frame_mode") or ""),
            "role": str(d.get("narrative_role") or ""),
            "impact": int(d.get("impact_level") or 0),
            "scale_reference": str(d.get("scale_reference") or ""),
            "anomaly_logic_stage": str(shot.get("anomaly_logic_stage") or "ordinary"),
            "environment_severity": _severity(resolved.get("environment") or {}),
            "contract_sha256": frame_contract.compile_frame(ep, n, write_cache=True)["contract_sha256"],
        })
    return rows


def _semantic_first_anomaly_candidates(rows: list[dict]) -> list[dict]:
    """Prefer locked Story semantics over downstream PREIMAGE render hints."""
    semantic = [
        r for r in rows
        if str(r.get("anomaly_logic_stage") or "ordinary") != "ordinary"
    ]
    if semantic:
        return semantic
    return [r for r in rows if r["mode"] == "anomaly_reveal" or r["impact"] >= 2] or rows

def _opening_social_baseline(ep: Path, rows: list[dict]) -> dict | None:
    p=ep/"meta/opening-social-anchor.json"
    if not p.is_file():return None
    try:d=read_json(p)
    except Exception:return None
    if d.get("applicable") is not True:return None
    preferred=[]
    for x in d.get("opening_frames") or []:
        if not isinstance(x,dict) or x.get("selfie") is not True:continue
        try:n=int(x.get("frame"))
        except Exception:continue
        if n not in {1,2}:continue
        if int(x.get("people_visible") or 0)<2:continue
        if x.get("relationship_anchor") is not True:continue
        preferred.append(n)
    by_frame={int(r["frame"]):r for r in rows}
    for n in preferred:
        row=by_frame.get(n)
        if row and row.get("mode")=="normal_record" and int(row.get("impact") or 0)<=1:return row
    return None

def _pixel_master_expected(assets: list[dict]) -> dict | None:
    row=next((x for x in assets if x.get("role")=="ordinary_baseline"),None)
    if not row:return None
    return {"frame":f"{int(row['frame']):02d}","asset_path":row["asset_path"],"sha256":row["sha256"],"frame_contract_sha256":row["frame_contract_sha256"]}


def choose_plan(ep: Path) -> dict:
    if not required(ep):
        raise ValueError("Visual Lock V2.1 is only required for V2.1+ episodes")
    env_errors = environment_contract.verify(ep)
    if env_errors:
        raise ValueError("Environment Contract must PASS first: " + "; ".join(env_errors[:8]))
    vn_errors = visual_narrative_core_v22.verify_all(ep)
    if vn_errors:
        raise ValueError("V2.2 Visual Narrative Core must PASS first: " + "; ".join(vn_errors[:12]))
    fc_errors = frame_contract.verify_all(ep)
    if fc_errors:
        raise ValueError("Resolved Frame Contract must PASS first: " + "; ".join(fc_errors[:8]))
    rows = _rows(ep)
    used: set[int] = set()

    def take(candidates: list[dict]) -> dict:
        for row in candidates:
            if row["frame"] not in used:
                used.add(row["frame"])
                return row
        raise ValueError("cannot select four distinct Visual Lock admission frames")

    preferred_baseline = _opening_social_baseline(ep, rows)
    baseline = take([preferred_baseline] if preferred_baseline else sorted(
        [r for r in rows if r["mode"] == "normal_record" and r["impact"] <= 1] or rows,
        key=lambda r: (r["impact"], r["frame"])
    ))
    baseline_selection = "opening_social_anchor" if preferred_baseline else "ordinary_fallback"
    # Reserve scarce semantic roles before the generic worst-environment slot.
    # A common episode has exactly one true climax/high-impact frame; selecting
    # `worst` first can consume that frame and make a valid 1+3 plan impossible.
    ordinary_life = not propagation_core_gate.anomaly_applicable(ep)
    high = take(sorted(
        [r for r in rows if r["mode"] in {"climax_impact", "anomaly_amplified"} or r["impact"] >= 3] or rows,
        key=lambda r: (-r["impact"], r["mode"] != "climax_impact", -r["frame"])
    ))
    if ordinary_life:
        # Keep the four-admission schema stable, but reinterpret the historical
        # first_major_anomaly slot as the first strong visual/world contrast.
        # Pure daily-life episodes must never invent an anomaly just to satisfy
        # calibration planning.
        first_anomaly_candidates = [
            r for r in rows
            if r["frame"] != baseline["frame"]
            and r["impact"] >= 1
            and r["role"] in {"transition", "escalation", "climax", "payoff"}
        ] or [r for r in rows if r["frame"] != baseline["frame"]]
    else:
        first_anomaly_candidates = _semantic_first_anomaly_candidates(rows)
    first_anomaly = take(sorted(
        first_anomaly_candidates,
        key=lambda r: (r["frame"], -r["impact"])
    ))
    worst = take(sorted(
        [r for r in rows if r["frame"] != baseline["frame"]],
        key=lambda r: (-r["environment_severity"], -r["impact"], r["frame"])
    ))

    plan_rows = [
        {"id": "V-B", **baseline, "role": ROLES[0], "depends_on": []},
        {"id": "V-W", **worst, "role": ROLES[1], "depends_on": [baseline["frame"]]},
        {"id": "V-A", **first_anomaly, "role": ROLES[2], "depends_on": [baseline["frame"]]},
        {"id": "V-H", **high, "role": ROLES[3], "depends_on": [baseline["frame"]]},
    ]
    return {
        "schema_version": 1,
        "story_os_version": episode_version(ep),
        "generated_at": now(),
        "policy": {
            "baseline_first": True,
            "remaining_three_parallelizable": True,
            "calibration_count": 4,
            "baseline_selection": baseline_selection,
            "baseline_frame": baseline["frame"],
            "opening_social_anchor_machine_priority": True,
            "ordinary_life_override": ordinary_life,
            "legacy_first_major_anomaly_semantics": (
                "first_major_visual_contrast" if ordinary_life else "first_major_anomaly"
            ),
        },
        "items": plan_rows,
    }


def verify_revision_inputs(ep: Path, revision_id: str) -> list[dict]:
    """Verify every frozen Revision prompt and contract against current authorities.

    Production Revision input bindings are immutable authority. Prompt packages
    and frame contracts are derived at read time here so stale local caches can
    never make a Revision appear ready for Visual Lock.
    """
    import production_revision_authority
    import prompt_package

    bindings = production_revision_authority.load_frame_bindings(ep, revision_id)
    by_frame = {int(row.get("frame") or 0): row for row in bindings}
    expected_frames = list(range(1, frame_contract.frame_count(ep) + 1))
    if sorted(by_frame) != expected_frames:
        raise ValueError("Production Revision must match the current frozen Episode frames")
    prompt_root = Path(ep) / "prompts" / "production"
    input_shas = set()
    verified = []
    for frame in expected_frames:
        binding = by_frame[frame]
        input_sha = str(binding.get("input_sha256") or "").lower()
        if len(input_sha) != 64:
            raise ValueError(f"Revision input SHA missing at frame {frame:02d}")
        input_shas.add(input_sha)
        contract = frame_contract.compile_frame(ep, frame, write_cache=False)
        contract_sha = str(contract.get("contract_sha256") or "").lower()
        if contract_sha != str(binding.get("frame_contract_sha256") or "").lower():
            raise ValueError(f"Revision Frame Contract SHA mismatch at frame {frame:02d}")
        prompt_path = prompt_root / f"{frame:02d}.txt"
        if not prompt_path.is_file():
            raise ValueError(f"Revision production prompt missing at frame {frame:02d}")
        package = prompt_package.compile_frame(ep, frame, prompt_path, write=False)
        if (str(package.get("frame_contract_sha256") or "").lower() != contract_sha
                or str(package.get("package_sha256") or "").lower()
                != str(binding.get("prompt_sha256") or "").lower()):
            raise ValueError(f"Revision Prompt/Frame Contract SHA mismatch at frame {frame:02d}")
        verified.append({**binding, "frame_contract_sha256": contract_sha,
                         "prompt_sha256": str(package["package_sha256"]).lower()})
    if len(input_shas) != 1:
        raise ValueError("Production Revision frames do not share one frozen input SHA")
    return verified


def prepare(ep: Path, *, production_revision_id: str | None = None) -> dict:
    plan = choose_plan(ep)
    revision_id = str(production_revision_id or "").strip() or None
    revision_bindings = {}
    if revision_id:
        import production_revision_authority
        verified_bindings = verify_revision_inputs(ep, revision_id)
        revision_bindings = {int(row["frame"]): row for row in verified_bindings}
        for row in plan["items"]:
            binding = revision_bindings.get(int(row["frame"]))
            if (not binding or str(binding.get("frame_contract_sha256") or "").lower()
                    != str(row.get("contract_sha256") or "").lower()):
                raise ValueError(f"Revision Frame Contract mismatch at frame {int(row['frame']):02d}")
            row.update({
                "production_revision_id": revision_id,
                "input_sha256": binding["input_sha256"],
                "prompt_sha256": binding["prompt_sha256"],
            })
        import production_revision_authority
        state = production_revision_authority.begin_visual_lock(ep, revision_id)
        if state.get("status") != "VISUAL_LOCK_PENDING":
            raise ValueError("Revision is not ready for Visual Lock calibration")
        plan["production_revision_id"] = revision_id
    write_json(ep / PLAN_REL, plan)
    gates_path = ep / GATES_REL
    g = read_json(gates_path)
    visual = g.setdefault("visual", {})
    calibration = visual.setdefault("calibration", {})
    previous = {} if revision_id else {
        (str(item.get("role") or ""), int(item.get("frame") or 0)): item
        for item in (calibration.get("items") or []) if isinstance(item, dict)
    }
    calibration["schema_version"] = 2
    calibration["policy"] = FOUR_ADMISSION_V21_POLICY
    refreshed = []
    for row in plan["items"]:
        old = previous.get((row["role"], int(row["frame"])))
        same_contract = old and str(old.get("frame_contract_sha256") or "") == str(row["contract_sha256"])
        if same_contract:
            refreshed.append({
                "id": row["id"], "role": row["role"], "frame": row["frame"],
                "asset_path": old.get("asset_path"), "sha256": old.get("sha256"),
                "decision": old.get("decision") or "pending",
                "frame_contract_sha256": row["contract_sha256"], "note": old.get("note") or "",
                **({"production_revision_id": revision_id,
                    "input_sha256": row["input_sha256"],
                    "prompt_sha256": row["prompt_sha256"]} if revision_id else {}),
            })
        else:
            refreshed.append({
                "id": row["id"], "role": row["role"], "frame": row["frame"],
                "asset_path": None, "sha256": None, "decision": "pending",
                "frame_contract_sha256": row["contract_sha256"], "note": "",
                **({"production_revision_id": revision_id,
                    "input_sha256": row["input_sha256"],
                    "prompt_sha256": row["prompt_sha256"]} if revision_id else {}),
            })
    calibration["items"] = refreshed
    write_json(gates_path, g)
    return plan


def _find_attempt_binding(ep: Path, frame: int, asset_sha: str) -> list[str]:
    if not frame_contract.required(ep):
        return []
    ledger = production_ledger.load_authority(ep, default=None)
    if not isinstance(ledger, dict):
        return [f"frame {frame:02d} production ledger missing"]
    row = (ledger.get("frames") or {}).get(f"{frame:02d}")
    if not isinstance(row, dict):
        return [f"frame {frame:02d} production ledger row missing"]
    for attempt in reversed(row.get("attempts") or []):
        candidate = attempt.get("candidate") or {}
        if str(candidate.get("sha256") or "").lower() == asset_sha.lower():
            return frame_contract.verify_recorded_provenance(
                ep, frame, (attempt.get("request") or {}).get("frame_contract")
            )
    return [f"frame {frame:02d} calibration image has no matching generation attempt"]


def calibration_assets(ep: Path, *, metadata_only: bool = False) -> list[dict]:
    """Resolve the four locked calibration rows.

    Full mode hashes the real pixel file and binds it to the current Resolved
    Frame Contract. metadata_only is the Git-metadata scan mode used by CI
    clean checkouts where media/ is absent by design: it validates the gate
    row shape and keeps the recorded sha256/frame_contract_sha256 for the
    pure-data payload comparison without touching pixel files or derived
    caches.
    """
    g = read_json(ep / GATES_REL)
    calibration = ((g.get("visual") or {}).get("calibration") or {})
    items = calibration.get("items")
    if not isinstance(items, list) or len(items) != 4:
        raise ValueError("V2.1 Visual Lock requires exactly 4 calibration items; run visual_lock_v21.py prepare")
    by_role = {}
    out = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("calibration item must be object")
        role = str(item.get("role") or "")
        if role not in ROLES:
            raise ValueError(f"unexpected Visual Lock role: {role}")
        if role in by_role:
            raise ValueError(f"duplicate Visual Lock role: {role}")
        frame = int(item.get("frame"))
        if metadata_only:
            row = {
                "id": str(item.get("id") or role),
                "role": role,
                "frame": frame,
                "path": None,
                "asset_path": str(item.get("asset_path") or ""),
                "sha256": str(item.get("sha256") or ""),
                "frame_contract_sha256": str(item.get("frame_contract_sha256") or ""),
                "production_revision_id": str(item.get("production_revision_id") or "") or None,
                "input_sha256": str(item.get("input_sha256") or "").lower(),
                "prompt_sha256": str(item.get("prompt_sha256") or "").lower(),
                "metadata_only": True,
            }
        else:
            p = repo_file(item.get("asset_path"))
            asset_sha = sha256_file(p)
            current = frame_contract.compile_frame(ep, frame, write_cache=False)
            recorded_fc = str(item.get("frame_contract_sha256") or "")
            if recorded_fc and not frame_contract.recorded_contract_matches_current(ep, frame, recorded_fc):
                raise ValueError(f"{role} frame contract stale")
            binding_errors = _find_attempt_binding(ep, frame, asset_sha)
            if binding_errors:
                raise ValueError("; ".join(binding_errors))
            row = {
                "id": str(item.get("id") or role),
                "role": role,
                "frame": frame,
                "path": p,
                "asset_path": repo_rel(p),
                "sha256": asset_sha,
                # Pixel/review evidence stays bound to the contract that actually
                # generated these pixels. A separately recorded projection-only
                # migration may prove that old contract equivalent to current;
                # never rewrite historical critic evidence to the new SHA.
                "frame_contract_sha256": recorded_fc or current["contract_sha256"],
                "production_revision_id": str(item.get("production_revision_id") or "") or None,
                "input_sha256": str(item.get("input_sha256") or "").lower(),
                "prompt_sha256": str(item.get("prompt_sha256") or "").lower(),
                "impact_level": current["hash_material"]["frame_directive"].get("impact_level"),
                "frame_mode": current["hash_material"]["frame_directive"].get("frame_mode"),
                "scale_reference": current["hash_material"]["frame_directive"].get("scale_reference"),
                "required_visual_cues": current["hash_material"]["frame_directive"].get("required_visual_cues") or [],
                "capture_constraint": current["hash_material"].get("capture_event") or {},
            }
        by_role[role] = row
        out.append(row)
    if set(by_role) != set(ROLES):
        raise ValueError("Visual Lock role set incomplete")
    return [by_role[x] for x in ROLES]


def _dirty_detection_assets(ep: Path) -> list[dict]:
    """Resolve bindings for routing even when an existing admission is stale.

    Review/verification remains strict through ``calibration_assets``.  Routing,
    however, must convert an old Frame Contract binding into a dirty admission
    instead of crashing before the authority-refresh image can be generated.
    """
    try:
        return calibration_assets(ep)
    except ValueError:
        rows = calibration_assets(ep, metadata_only=True)
        for row in rows:
            current = frame_contract.compile_frame(ep, int(row["frame"]), write_cache=False)
            row["frame_contract_sha256"] = current["contract_sha256"]
            row["binding_stale_for_review"] = True
        return rows


def stale_generation_bindings(ep: Path) -> list[dict]:
    """Return Visual Lock frames whose current pixels were generated under an old contract.

    This is narrower than a dirty review. A stale review can be repeated; stale
    generation provenance must be regenerated before any pixel critic sees it.
    The Production Ledger current candidate is the source of truth so an older
    gate projection cannot invalidate a newer candidate by itself.
    """
    if not frame_contract.required(ep):
        return []
    gates = read_json(ep / GATES_REL)
    items = ((((gates.get("visual") or {}).get("calibration") or {}).get("items")) or [])
    ledger = production_ledger.load_authority(ep, default={}) or {}
    ledger_frames = ledger.get("frames") or {}
    stale: list[dict] = []
    for item in items:
        if not isinstance(item, dict) or item.get("frame") is None:
            continue
        frame = int(item["frame"])
        key = f"{frame:02d}"
        frame_row = ledger_frames.get(key) or ledger_frames.get(str(frame)) or {}
        candidate = frame_row.get("current_candidate") or {}
        candidate_sha = str(candidate.get("sha256") or "").lower()
        if not candidate_sha:
            continue
        attempt = next(
            (
                row for row in reversed(frame_row.get("attempts") or [])
                if str(((row or {}).get("candidate") or {}).get("sha256") or "").lower() == candidate_sha
            ),
            None,
        )
        if not isinstance(attempt, dict):
            continue
        recorded = (attempt.get("request") or {}).get("frame_contract")
        errors = frame_contract.verify_recorded_provenance(ep, frame, recorded)
        if not any("frame_contract_sha256 stale" in str(error) for error in errors):
            continue
        current = frame_contract.compile_frame(ep, frame, write_cache=False)
        stale.append({
            "frame": frame,
            "role": str(item.get("role") or ""),
            "candidate_sha256": candidate_sha,
            "candidate_path": str(candidate.get("path") or ""),
            "recorded_frame_contract_sha256": str((recorded or {}).get("contract_sha256") or ""),
            "current_frame_contract_sha256": str(current.get("contract_sha256") or ""),
            "errors": errors,
        })
    return stale


def dirty_admission_assets(ep: Path) -> list[dict]:
    """Return only admissions whose SHA-bound PASS evidence is absent/stale."""
    contract = compile_prompt_contract(ep)
    assets = _dirty_detection_assets(ep)
    return visual_lock_admission_state.dirty_assets(
        ep,
        assets,
        profile_sha256=contract["profile_sha256"],
        story_os_version=episode_version(ep),
    )


def dirty_admission_frames(ep: Path) -> list[int]:
    return sorted({int(row["frame"]) for row in dirty_admission_assets(ep)})


def bind_from_queue(ep: Path) -> dict:
    plan = read_json(ep / PLAN_REL) if (ep / PLAN_REL).is_file() else {}
    revision_id = str(plan.get("production_revision_id") or "") or None
    q = scheduler_core.load_queue(ep)
    ledger = production_ledger.load_authority(ep, default={"frames": {}}) or {"frames": {}}
    generated = {}
    for item in q.get("items") or []:
        if str(item.get("production_revision_id") or "") != str(revision_id or ""):
            continue
        if item.get("scope") not in {"visual_lock", "repair", "baseline_candidate"}:
            continue
        key = f"{int(item['frame']):02d}"
        if item.get("status") == "generated":
            generated[key] = item
            continue
        # A Fast Scout result is triage only. It may enter Visual Lock solely
        # after a direct-user exception acceptance of the identical candidate.
        if item.get("status") != "scout_repair":
            continue
        frame = (ledger.get("frames") or {}).get(key) or {}
        candidate = frame.get("current_candidate") or {}
        acceptance = (frame.get("user_exception_acceptances") or [])[-1:]
        if (
            frame.get("status") == "PASSED"
            and candidate.get("sha256") == ((item.get("lineage") or {}).get("sha256"))
            and acceptance
            and acceptance[0].get("approval_basis") == "direct_user_review_exception_acceptance"
            and acceptance[0].get("candidate_sha256") == candidate.get("sha256")
        ):
            generated[key] = item
    gates_path = ep / GATES_REL
    g = read_json(gates_path)
    items = (((g.get("visual") or {}).get("calibration") or {}).get("items") or [])
    if len(items) != 4:
        raise ValueError("Visual Lock plan missing; run prepare first")
    baseline_review = read_json(ep / visual_lock_baseline_gate.REL) if (ep / visual_lock_baseline_gate.REL).is_file() else {}
    for item in items:
        key = f"{int(item['frame']):02d}"
        if item.get("role") == "ordinary_baseline" and baseline_review.get("status") == "LOCKED" and baseline_review.get("decision") == "PASS":
            output = repo_file(baseline_review.get("asset_path"))
            expected_sha = str(baseline_review.get("sha256") or "").lower()
            actual_sha = sha256_file(output)
            if actual_sha != expected_sha:
                raise ValueError("locked baseline asset hash drift")
            item["asset_path"] = repo_rel(output)
            item["sha256"] = actual_sha
            item["decision"] = "candidate"
            item["frame_contract_sha256"] = str(baseline_review.get("frame_contract_sha256") or frame_contract.compile_frame(ep, int(key), write_cache=True)["contract_sha256"])
            continue
        qrow = generated.get(key)
        if not qrow:
            raise ValueError(f"Visual Lock frame {key} not generated by scheduler")
        output = repo_file(qrow.get("output_path"))
        item["asset_path"] = repo_rel(output)
        item["sha256"] = sha256_file(output)
        item["decision"] = "candidate"
        item["frame_contract_sha256"] = frame_contract.compile_frame(ep, int(key), write_cache=True)["contract_sha256"]
    write_json(gates_path, g)
    return {"bound": [f"{int(x['frame']):02d}" for x in items]}


def validate_payload(data: dict, *, contract: dict, assets: list[dict], version: str) -> list[str]:
    errors = []
    if data.get("schema_version") != visual_review_schema.SCHEMA_VERSION_V2:
        errors.append(f"schema_version must be {visual_review_schema.SCHEMA_VERSION_V2}")
        errors.extend(visual_review_schema.era_divergence(data, version=version))
    if data.get("story_os_version") != version:
        errors.append("story_os_version mismatch")
    if data.get("profile_id") != contract["profile_id"]:
        errors.append("profile_id mismatch")
    if str(data.get("profile_sha256") or "").lower() != contract["profile_sha256"].lower():
        errors.append("profile_sha256 mismatch")
    prov = data.get("critic_provenance") or {}
    errors.extend(runtime_provenance.validate_critic_provenance(prov))

    expected = {row["id"]: row for row in assets}
    revision_id = str(data.get("production_revision_id") or "").strip()
    bound_revisions = {str(row.get("production_revision_id") or "").strip() for row in assets}
    bound_revisions.discard("")
    if bound_revisions and (len(bound_revisions) != 1 or revision_id not in bound_revisions):
        errors.append("production_revision_id does not match all four Visual Lock assets")
    rows = data.get("calibration")
    if not isinstance(rows, list) or len(rows) != visual_review_schema.CALIBRATION_ROWS_V2:
        errors.append(
            f"Visual Lock review must contain exactly "
            f"{visual_review_schema.CALIBRATION_ROWS_V2} rows"
        )
        rows = []
    seen = set()
    for row in rows:
        rid = str(row.get("id") or "")
        seen.add(rid)
        exp = expected.get(rid)
        if exp is None:
            errors.append(f"unexpected calibration id: {rid}")
            continue
        # metadata_only rows carry the hash recorded in story-gates instead of a
        # fresh pixel hash; when the gate row has no recorded hash the check is
        # deferred to full local verification instead of guessing a value.
        exp_sha = str(exp.get("sha256") or "")
        if exp_sha and str(row.get("sha256") or "").lower() != exp_sha.lower():
            errors.append(f"{rid} sha mismatch")
        exp_fc = str(exp.get("frame_contract_sha256") or "")
        if exp_fc and str(row.get("frame_contract_sha256") or "").lower() != exp_fc.lower():
            # Historical evidence retains the exact original contract SHA.
            # A review is portable only when the old bytes provably differ
            # solely by monotonic visual-projection completion.
            if not frame_contract.recorded_contract_matches_current(
                    ep, exp["frame"], str(row.get("frame_contract_sha256") or "")):
                errors.append(f"{rid} frame_contract_sha mismatch")
        if exp and exp.get("production_revision_id"):
            for field in ("production_revision_id", "input_sha256", "prompt_sha256"):
                if str(row.get(field) or "").lower() != str(exp.get(field) or "").lower():
                    errors.append(f"{rid} {field} mismatch")
        checks = row.get("checks") or {}
        for key in checks_for_version(version):
            if checks.get(key) is not True:
                errors.append(f"{rid}.checks.{key} must be true")
        if row.get("issues") not in ([], None):
            errors.append(f"{rid}.issues must be empty for PASS")
    if seen != set(expected):
        errors.append("review ids do not match 4 Visual Lock assets")
    if data.get("issue_codes") not in ([], None):
        errors.append("issue_codes must be empty for PASS")
    if (data.get("summary") or {}).get("passed") is not True:
        errors.append("summary.passed must be true")
    return errors


def verify(ep: Path, *, metadata_only: bool = False) -> list[str]:
    """Verify the four-admission Visual Lock review.

    metadata_only (Git-metadata CI scan) validates every pure-data layer of the
    review payload and the recorded calibration hashes, but skips pixel file
    existence/hash, baseline gate and character pixel-master checks that
    require media/ present in the working tree.
    """
    if not required(ep):
        return []
    data = visual_profile_review_persistence.load(ep)
    if not isinstance(data, dict):
        return ["meta/visual-profile-review.json missing"]
    try:
        plan_path = ep / PLAN_REL
        plan = read_json(plan_path) if plan_path.is_file() else {}
        revision_id = str(plan.get("production_revision_id") or "").strip()
        if revision_id:
            verify_revision_inputs(ep, revision_id)
        contract = compile_prompt_contract(ep)
        assets = calibration_assets(ep, metadata_only=metadata_only)
        errors = validate_payload(data, contract=contract, assets=assets, version=episode_version(ep))
        weak_ids = {
            str(asset.get("id") or "")
            for asset in assets
            if (visual_lock_admission_state.valid_pass(
                ep, asset, profile_sha256=contract["profile_sha256"],
                story_os_version=episode_version(ep)
            ) or {}).get("status") == "WEAK_PASS"
        }
        direct_user_ids = {
            str(asset.get("id") or "")
            for asset in assets
            if (
                visual_lock_admission_state.valid_pass(
                    ep, asset, profile_sha256=contract["profile_sha256"],
                    story_os_version=episode_version(ep),
                ) or {}
            ).get("provenance", {}).get("approval_basis") == "direct_user_visual_admission"
        }
        projected_ids = weak_ids | direct_user_ids
        if projected_ids and errors:
            # Keep the critic FAIL payload untouched. Only the verifier projects a
            # SHA-bound policy/user decisions over row-level findings and global
            # FAIL summary; schema/provenance/hash/binding errors remain fatal.
            row_errors = tuple(f"{rid}.checks." for rid in projected_ids)
            issue_errors = {f"{rid}.issues must be empty for PASS" for rid in projected_ids}
            errors = [
                error for error in errors
                if not error.startswith(row_errors)
                and error not in issue_errors
                and error not in {"issue_codes must be empty for PASS", "summary.passed must be true"}
            ]
        if not metadata_only:
            if not errors:
                errors.extend("BASELINE_GATE:"+x for x in visual_lock_baseline_gate.validate_final_requirement(ep))
            if not errors and character_visual_contract.pixel_master_required(ep):
                expected=_pixel_master_expected(assets)
                errors.extend(character_visual_contract.validate_pixel_master(ep,expected))
        return errors
    except Exception as exc:
        return [str(exc)]


resolve_codex = critic_runner.resolve_codex
prefix = critic_runner.prefix


def critic_prompt(ep: Path, contract: dict, assets: list[dict], candidate: Path, attempt: int) -> str:
    rel_out = candidate.relative_to(ROOT).as_posix()
    count = len(assets)
    listed = "\n".join(
        f"- id={r['id']} role={r['role']} frame={r['frame']:02d} "
        f"mode={r['frame_mode']} impact={r['impact_level']} scale_reference={r['scale_reference']!r} "
        f"required_visual_cues={r.get('required_visual_cues', [])!r} "
        f"capture_event={(r.get('capture_constraint') or {})!r} "
        f"frame_contract_sha={r['frame_contract_sha256']}"
        for r in assets
    )
    return f"""You are the adversarial Story OS V2.1 Visual Lock Critic in a fresh isolated session.
Review exactly {count} DIRTY calibration/admission image(s) in the listed order. Do not generate or edit images.
Unchanged admissions with valid SHA-bound PASS evidence are intentionally omitted and MUST NOT be re-judged.

Resolved visual profile:
<visual_contract>
{contract['text']}
</visual_contract>

Rows:
{listed}

This gate deliberately allows huge/impossible anomalies. DO NOT fail an image merely because the supernatural event is large, impossible, cosmic, surreal or frightening.
Reality-first constrains HOW the event looks captured: optics, available light, atmosphere, occlusion, scale cues, device limitations, photographer behavior, ordinary-life context and causal imperfection.

Role expectations:
- ordinary_baseline: ordinary world must look convincingly real before anomaly spectacle.
- worst_capture_condition: difficult weather/light/capture state must obey physical causes; no blanket weather filter.
- first_major_anomaly: anomaly must be clearly readable yet embedded into believable reality rather than promo concept art.
- high_impact_admission: impact 3-4 must visibly deliver its promised abnormal scale/consequence, include readable real-world scale reference, and STILL look like an accidental/working record rather than a cinematic poster.

FRAME-CONTRACT VISUAL EVIDENCE (mandatory):
The row's required_visual_cues and capture_event are taken directly from the SHA-bound locked Frame Contract. Evaluate what the *particular still photo* is required to show, not hypothetical spectacle implied by the role name/impact score.
Do not require an impossible transition/motion or future consequence in a frame that explicitly depicts only its aftermath or an ordinary physical action.
Do not ignore genuine absence, poor legibility, missing props, wrong chronology, or any specified cue; if a required cue is not visible, FAIL with concrete pixel evidence.
Do not revise the locked Frame Contract, invent extra visual elements, or mark anything PASS solely because a contract says so.

ORDINARY-LIFE VISUAL LOCK OVERRIDE:
If this Episode is explicitly anomaly_applicable=false, do NOT invent or require an anomaly for calibration. The legacy first_major_anomaly slot means first_major_visual_contrast: judge whether the first strong celestial-world/life contrast is readable while ordinary behavior stays believable. high_impact_admission means high-impact world-scale daily-life imagery, not abnormal spectacle.
For pure daily-life Episodes, ordinary_life_density means credible resident/friend life and everyday activity. Do NOT require a visible job, workplace, labor tool, shift workflow, or other worker-specific evidence unless the Frame Contract for that exact frame requires it. A reusable visual profile may support worker stories without making every frame a work scene.
For camera authorship, the per-frame Capture Event is authoritative. Explicit timer/fixed-mount capture, a device resting on a railing/table, a documented companion handoff, or a story-authorized selfie are valid physical camera sources and MUST NOT be failed as GHOST_CAMERA merely because every known character appears in frame.
For worst_capture_condition in an ordinary-life Episode, judge the most constrained/least ideal capture condition actually promised by the selected Frame Contract. Do NOT demand storm, fog, darkness, extreme blur, or other hardship that the Story/Environment Contract never promised.

For every image judge the checks required for Story OS contract version {episode_version(ep)}:
{", ".join(checks_for_version(episode_version(ep)))}.
V2.2-only checks (camera authorship / moment / camera defect / screen physics) apply only when episode contract version >= 2.2.0. Do not fail legacy V2.1 episodes on V2.2-only criteria.
V2.2.1-only checks (world identity / character appearance anchor / cultural environment) apply only when episode contract version >= 2.2.1. For the default profile, visible primary/local characters should read as Chinese local residents in a believable Mainland China environment unless the Episode explicitly overrides world identity.

Interpret anomaly_scale_delivery=true on ordinary/no-anomaly frames as "the frame correctly avoids unplanned spectacle and matches its locked impact level."
Interpret scale_reference_fidelity=true on low-impact frames as "no false/contradictory scale cue"; for high impact it MUST be visibly useful.

Return ONLY valid JSON as your final response. Do not call shell/exec/PowerShell, do not read SKILL.md/AGENTS.md/repository files, and do not inspect any source beyond the four attached images plus the contract text already embedded in this prompt. The Codex CLI will persist your final response to {rel_out} automatically:
{{
  "calibration": [
    {{
      "id": "V-B",
      "checks": {{
        "visual_profile_match": true,
        "reality_first": true,
        "ordinary_life_density": true,
        "available_light": true,
        "unposed_capture": true,
        "not_cinematic": true,
        "causal_imperfection": true,
        "environment_physics_fidelity": true,
        "capture_credibility": true,
        "anomaly_scale_delivery": true,
        "scale_reference_fidelity": true,
        "camera_authorship_physical": true,
        "moment_capture_credibility": true,
        "camera_defect_physics": true,
        "screen_content_physics": true,
        "world_identity_fidelity": true,
        "character_appearance_anchor_fidelity": true,
        "cultural_environment_fidelity": true
      }},
      "issues": [],
      "notes": "specific actual-pixel evidence"
    }}
  ],
  "issue_codes": [],
  "summary": {{"passed": true}}
}}
PASS each returned admission row only if every check returned by checks_for_version for this Episode version is true on that attached image. This is attempt {attempt}.
"""


def _row_failed(ep: Path, row: dict) -> bool:
    checks = row.get("checks") or {}
    return row.get("issues") not in ([], None) or any(
        checks.get(k) is not True for k in checks_for_version(episode_version(ep))
    )


def _merge_reused_admissions(ep: Path, *, data: dict, current: list[dict], contract: dict) -> dict:
    """Merge fresh dirty-row verdicts with still-valid SHA-bound PASS rows."""
    incoming = {
        str(row.get("id") or ""): dict(row)
        for row in (data.get("calibration") or [])
        if isinstance(row, dict)
    }
    reused = visual_lock_admission_state.reusable_review_rows(
        ep,
        current,
        profile_sha256=contract["profile_sha256"],
        story_os_version=episode_version(ep),
    )
    for row in reused:
        incoming.setdefault(str(row.get("id") or ""), row)
    data["calibration"] = [incoming.get(str(asset.get("id") or ""), {}) for asset in current]
    issue_codes: list[str] = []
    for row in data["calibration"]:
        if not isinstance(row, dict):
            continue
        for code in row.get("issues") or []:
            if code not in issue_codes:
                issue_codes.append(code)
    data["issue_codes"] = issue_codes
    data["summary"] = {"passed": bool(data["calibration"]) and all(not _row_failed(ep, row) for row in data["calibration"])}
    return data


def _mark_decisions(ep: Path, data: dict) -> None:
    gates_path = ep / GATES_REL
    g = read_json(gates_path)
    items = (((g.get("visual") or {}).get("calibration") or {}).get("items") or [])
    by_id = {str(row.get("id") or ""): row for row in (data.get("calibration") or []) if isinstance(row, dict)}
    for item in items:
        if not isinstance(item, dict):
            continue
        row = by_id.get(str(item.get("id") or ""))
        if row is not None:
            item["decision"] = "failed" if _row_failed(ep, row) else "passed"
    reviews = g.setdefault("reviews", {})
    reviews["visual_admission"] = "passed" if items and all(x.get("decision") == "passed" for x in items if isinstance(x, dict)) else "failed"
    write_json(gates_path, g)


def _record_calibration_frames(ep: Path, data: dict) -> None:
    # A critic that could not access its image inputs has no content finding to
    # propagate into the production ledger. Reused PASS rows are already bound
    # and must not be replayed into the ledger.
    if "INPUT_IMAGES_UNAVAILABLE" in (data.get("issue_codes") or []):
        return
    for row in data.get("calibration") or []:
        if row.get("admission_reused") is True:
            continue
        try:
            frame = int(row.get("frame"))
        except Exception:
            continue
        decision = "repair" if _row_failed(ep, row) else "pass"
        notes = (
            "Phase5 Visual Lock critic failed actual-pixel admission"
            if decision == "repair"
            else "Phase5 Visual Lock per-frame SHA-bound admission PASS"
        )
        cp = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parent / "production_ledger.py"),
             "review", str(ep), "--frame", f"{frame:02d}", "--decision", decision,
             "--notes", notes],
            cwd=ROOT, check=False, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace"
        )
        if cp.returncode != 0:
            row.setdefault("ledger_review_warnings", []).append(cp.stdout[-1200:])


def _finalize_review_payload(
    ep: Path,
    *,
    data: dict,
    contract: dict,
    current: list[dict],
    provenance: dict,
    attempt: int,
) -> int:
    data["schema_version"] = visual_review_schema.SCHEMA_VERSION_V2
    data["story_os_version"] = episode_version(ep)
    data["profile_id"] = contract["profile_id"]
    data["profile_path"] = contract["profile_path"]
    data["profile_sha256"] = contract["profile_sha256"]
    data["critic_provenance"] = provenance
    revision_id = str(data.get("production_revision_id") or "").strip() or None
    revision_ids = {str(row.get("production_revision_id") or "").strip()
                    for row in current}
    revision_ids.discard("")
    if len(revision_ids) > 1:
        raise RuntimeError("Visual Lock assets mix Production Revisions")
    if revision_id and revision_ids != {revision_id}:
        raise RuntimeError("Visual Lock review and asset Revision bindings differ")
    if not revision_id and revision_ids:
        revision_id = next(iter(revision_ids))
    if revision_id:
        verify_revision_inputs(ep, revision_id)
        data["production_revision_id"] = revision_id
    reviewed_ids = {
        str(row.get("id") or "")
        for row in (data.get("calibration") or [])
        if isinstance(row, dict)
    }
    data = _merge_reused_admissions(ep, data=data, current=current, contract=contract)
    by_id = {r["id"]: r for r in current}
    for row in data.get("calibration") or []:
        rid = str(row.get("id") or "")
        if rid in by_id:
            row["sha256"] = by_id[rid]["sha256"]
            row["frame_contract_sha256"] = by_id[rid]["frame_contract_sha256"]
            row["frame"] = by_id[rid]["frame"]
            row["role"] = by_id[rid]["role"]
            row["production_revision_id"] = by_id[rid].get("production_revision_id")
            row["input_sha256"] = by_id[rid].get("input_sha256")
            row["prompt_sha256"] = by_id[rid].get("prompt_sha256")

    technical_codes = critic_runtime_v211.classify_issue_codes(data.get("issue_codes") or [])
    evidence_ref = provenance.get("log") or provenance.get("request_path") or "product_runtime_review"
    if technical_codes:
        visual_profile_review_persistence.save(
            ep,
            data,
            decision="TECHNICAL_FAILURE",
            source_sha256=contract["profile_sha256"],
        )
        (ep / CANDIDATE_REL).unlink(missing_ok=True)
        health = critic_runtime_v211.record_technical_failure(
            ep,
            issue_codes=technical_codes,
            attempt=attempt,
            log=str(evidence_ref),
            source="visual_lock_critic_payload",
        )
        print("VISUAL LOCK CRITIC TECHNICAL FAIL:", ",".join(technical_codes), "status=" + health["status"])
        return 11

    errors = validate_payload(data, contract=contract, assets=current, version=episode_version(ep))
    _record_calibration_frames(ep, data)
    fresh_rows = [
        row for row in (data.get("calibration") or [])
        if isinstance(row, dict) and str(row.get("id") or "") in reviewed_ids
    ]
    visual_lock_admission_state.record_rows(
        ep,
        rows=fresh_rows,
        assets=current,
        profile_sha256=contract["profile_sha256"],
        story_os_version=episode_version(ep),
        required_checks=checks_for_version(episode_version(ep)),
        provenance=provenance,
        attempt=attempt,
    )
    persisted = visual_profile_review_persistence.save(
        ep,
        data,
        decision="PASS" if not errors else "FAIL",
        source_sha256=contract["profile_sha256"],
    )
    if revision_id:
        import production_revision_authority
        official_payload = visual_profile_review_persistence.load(ep)
        if not isinstance(official_payload, dict):
            raise RuntimeError("Revision Visual Lock Review Authority could not be reloaded")
        production_revision_authority.record_visual_lock_review(
            ep,
            revision_id=revision_id,
            review_id=str(persisted.get("review_id") or ""),
            review_sha256=production_revision_authority._payload_sha(official_payload),
            payload=official_payload,
            assets=current,
        )
    (ep / CANDIDATE_REL).unlink(missing_ok=True)
    critic_runtime_v211.record_content_result(
        ep,
        passed=not errors,
        attempt=attempt,
        issue_codes=data.get("issue_codes") or [],
        log=str(evidence_ref),
    )
    _mark_decisions(ep, data)
    if errors:
        # Independent joint actual-pixel review is authoritative. If its only
        # remaining debt is SHA-bound soft quality on an exhausted baseline,
        # use the existing audited WEAK_PASS path rather than stalling.
        import visual_lock_candidate_pool
        eligible = visual_lock_candidate_pool.weak_pass_eligible_frames(ep)
        if eligible:
            accepted = visual_lock_candidate_pool.apply_weak_passes(ep, eligible)
            if accepted.get("status") == "PASS" and not verify(ep):
                print("VISUAL LOCK V2.1 POLICY WEAK_PASS; independent FAIL retained")
                return 0
        print("VISUAL LOCK V2.1 REVIEW FAIL")
        for error in errors:
            print("FAIL:", error)
        return 2
    if character_visual_contract.pixel_master_required(ep):
        expected = _pixel_master_expected(current)
        if expected is None:
            raise RuntimeError("ordinary_baseline asset missing for character pixel master")
        character_visual_contract.lock_pixel_master(
            ep,
            frame=expected["frame"],
            asset_path=expected["asset_path"],
            asset_sha256=expected["sha256"],
            frame_contract_sha256=expected["frame_contract_sha256"],
        )
    print("VISUAL LOCK V2.1 REVIEW PASS")
    return 0


def finalize_product_review(ep: Path, *, attempt: int, runtime: str) -> int:
    baseline_errors = visual_lock_baseline_gate.validate_review(ep)
    if baseline_errors and not visual_lock_baseline_gate.ready_for_joint_critic(ep):
        raise RuntimeError("ordinary_baseline separate review must PASS or have verified exhausted soft-quality evidence: " + "; ".join(baseline_errors[:8]))
    contract = compile_prompt_contract(ep)
    assets = calibration_assets(ep)
    candidate = ep / CANDIDATE_REL
    data, provenance = product_review_adapter.finalize_candidate(
        ep,
        kind="visual-lock",
        runtime=runtime,
        attempt=attempt,
        candidate_path=candidate,
    )
    rc = _finalize_review_payload(
        ep,
        data=data,
        contract=contract,
        current=assets,
        provenance=provenance,
        attempt=attempt,
    )
    if rc == 0:
        final_export = visual_profile_review_persistence.materialize_export(
            ep,
            visual_profile_review_persistence.load(ep),
        )
        if final_export is None:
            raise RuntimeError("visual profile review export missing after PASS")
        product_review_adapter.mark_complete(
            ep,
            "visual-lock",
            attempt=attempt,
            final_path=final_export,
        )
    return rc


def _direct_user_exception_frames(ep: Path, assets: list[dict]) -> list[int]:
    """Return Visual Lock assets currently backed by a direct-user exception.

    Visual Lock review attempts are global rounds, while the exception authority
    is per frame. Bind the provenance to the exact SHA/attempt that produced the
    current calibration asset so an older exception authorization cannot bless a
    newer unrelated image.
    """
    ledger = production_ledger.load_authority(Path(ep).resolve(), default=None)
    if not isinstance(ledger, dict):
        return []
    result = []
    for asset in assets:
        try:
            frame = int(asset.get("frame"))
        except Exception:
            continue
        row = ((ledger.get("frames") or {}).get(f"{frame:02d}") or {})
        candidate = row.get("current_candidate") or {}
        if str(candidate.get("sha256") or "").lower() != str(asset.get("sha256") or "").lower():
            continue
        attempt_id = str(candidate.get("attempt_id") or "")
        accepted = next(
            (x for x in reversed(row.get("attempts") or []) if str((x or {}).get("attempt_id") or "") == attempt_id),
            None,
        )
        capture_id = str(((accepted or {}).get("request") or {}).get("capture_id") or "")
        if (
            accepted
            and accepted.get("result") == "success"
            and capture_id.startswith("user-exception-")
            and int(row.get("user_exception_repairs_used") or 0) == 1
        ):
            result.append(frame)
    return sorted(set(result))


def run_critic(ep: Path, *, attempt: int, codex_raw: str | None, timeout: int | None = None) -> int:
    if timeout is None:
        timeout = runtime_timeout_policy.seconds("review_critic")
    if attempt < 1:
        raise RuntimeError("attempt must be >= 1")
    active_runtime, _ = runtime_router.detect()
    vision_runtime, _ = runtime_router.vision_review_runtime()
    if attempt > 2 and (active_runtime not in {"WORK", "WEB"} or codex_raw):
        raise RuntimeError("extended Visual Lock attempts require WORK product review after finalized source drift")
    baseline_errors=visual_lock_baseline_gate.validate_review(ep)
    if baseline_errors and not visual_lock_baseline_gate.ready_for_joint_critic(ep):
        raise RuntimeError("ordinary_baseline has no valid hard-check evidence: "+"; ".join(baseline_errors[:8]))
    contract = compile_prompt_contract(ep)
    assets = calibration_assets(ep)
    dirty_assets = visual_lock_admission_state.dirty_assets(
        ep,
        assets,
        profile_sha256=contract["profile_sha256"],
        story_os_version=episode_version(ep),
    )
    candidate = ep / CANDIDATE_REL
    candidate.unlink(missing_ok=True)
    before = {r["id"]: r["sha256"] for r in assets}
    if not dirty_assets:
        provenance = runtime_provenance.build_vision_critic_provenance(
            attempt=attempt,
            log="meta/visual-lock-admissions.json",
            review_scope="VISUAL_LOCK_REUSED_ADMISSIONS",
        )
        return _finalize_review_payload(
            ep,
            data={"calibration": [], "issue_codes": [], "summary": {"passed": True}},
            contract=contract,
            current=assets,
            provenance=provenance,
            attempt=attempt,
        )
    if vision_runtime != "CODEX" and not codex_raw:
        profile_path = Path(contract["profile_path"])
        profile_path = profile_path.resolve() if profile_path.is_absolute() else (ROOT / profile_path).resolve()
        sources = [ep / GATES_REL, profile_path, *[r["path"] for r in dirty_assets]]
        request = product_review_adapter.prepare(
            ep,
            kind="visual-lock",
            runtime=active_runtime,
            attempt=attempt,
            prompt=critic_prompt(ep, contract, dirty_assets, candidate, attempt),
            source_paths=sources,
            candidate_path=candidate,
        )
        print(json.dumps(request, ensure_ascii=False, indent=2))
        return product_review_adapter.HOST_ACTION_REQUIRED_RC
    codex = resolve_codex(codex_raw)
    # Codex's Windows image sidecar may not resolve Chinese workspace paths.
    # Supply byte-identical ASCII-only temporary attachments for this review.
    staging = codex_user_runner.workspace_path(prefix="story-os-visual-lock-")
    staged_assets = []
    for row in dirty_assets:
        staged = staging / f"{row['id']}-{int(row['frame']):02d}{Path(row['path']).suffix.lower()}"
        shutil.copy2(row["path"], staged)
        staged_assets.append(staged)
    # STORY_OS_CRITIC_MODEL_OVERRIDE: the image controller model is pinned for image
    # GENERATION. A vision critic must run on a model that can actually read attached
    # images, so use the optional dedicated critic key when configured and otherwise
    # let the Codex CLI choose its default model (same behaviour as the frame semantic
    # and caption audits). Without this, a controller model whose vision sidecar
    # rejects attachments silently yields an all-false "no pixel evidence" sentinel.
    model=runtime_router.vision_review_model()
    effort=runtime_router.vision_review_effort("final")
    log = ep / "meta" / f"visual-lock-critic-attempt-{attempt}.jsonl"
    try:
        done = critic_runner.launch(
            critic_prompt(ep, contract, dirty_assets, candidate, attempt),
            codex=codex,
            root=ROOT,
            timeout=timeout,
            output_path=candidate,
            attachments=staged_assets,
            model=model,
            reasoning_effort=effort,
            sandbox="danger-full-access" if os.name=="nt" else "workspace-write",
            log_path=log,
            extra=["--ignore-rules"],
        )
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    data = None
    recovery_basis = None
    if candidate.is_file():
        try:
            data = read_json(candidate)
        except Exception:
            data = None
    if data is None:
        recovered = critic_runner.recover_completed_agent_json(done.log_text)
        if recovered is not None:
            data = recovered
            recovery_basis = "agent_message_json_followed_by_turn_completed"
    if data is None:
        if done.returncode != 0:
            log_text = done.log_text
            codes = critic_runtime_v211.classify_log_text(log_text) or ["CRITIC_PROCESS_ERROR"]
            health = critic_runtime_v211.record_technical_failure(
                ep, issue_codes=codes, attempt=attempt,
                log=log.relative_to(ROOT).as_posix(), source="visual_lock_critic_process")
            print("VISUAL LOCK CRITIC TECHNICAL FAIL:", ",".join(codes), "status="+health["status"])
            return 11
        health = critic_runtime_v211.record_technical_failure(
            ep, issue_codes=["CRITIC_OUTPUT_MISSING"], attempt=attempt,
            log=log.relative_to(ROOT).as_posix(), source="visual_lock_critic_output")
        print("VISUAL LOCK CRITIC TECHNICAL FAIL: CRITIC_OUTPUT_MISSING status="+health["status"])
        return 11
    current = calibration_assets(ep)
    if {r["id"]: r["sha256"] for r in current} != before:
        raise RuntimeError("Visual Lock critic modified calibration images")
    exception_frames = _direct_user_exception_frames(ep, current)
    provenance = runtime_provenance.build_vision_critic_provenance(
        attempt=attempt,
        log=log.relative_to(ROOT).as_posix(),
        review_scope="VISUAL_LOCK_DIRTY_ADMISSION",
        allow_bounded_candidate_attempt=attempt > 2 and not exception_frames,
        allow_user_exception_attempt=bool(exception_frames),
    )
    if exception_frames:
        provenance["direct_user_exception_frames"] = exception_frames
    if recovery_basis:
        provenance["recovered_from_post_answer_process_failure"] = True
        provenance["recovery_basis"] = recovery_basis
        provenance["process_returncode"] = int(done.returncode)
    return _finalize_review_payload(
        ep,
        data=data,
        contract=contract,
        current=current,
        provenance=provenance,
        attempt=attempt,
    )


def reconcile_admissions(ep: Path) -> dict:
    contract = compile_prompt_contract(ep)
    assets = calibration_assets(ep)
    result = visual_lock_admission_state.reconcile_historical_passes(
        ep,
        assets=assets,
        profile_sha256=contract["profile_sha256"],
        story_os_version=episode_version(ep),
        required_checks=checks_for_version(episode_version(ep)),
    )
    result["gate_projection"] = visual_lock_admission_state.sync_gate_decisions(ep)
    return result


def accept_direct_user_admission(ep: Path, *, frame: int, user_statement: str) -> dict:
    """Project an explicit direct-user decision for one current admission.

    The exact current candidate must already be recorded as a user-exception
    candidate in the production ledger. The automatic critic result remains in
    the review payload and is never rewritten.
    """
    contract = compile_prompt_contract(ep)
    assets = calibration_assets(ep)
    asset = next((row for row in assets if int(row.get("frame") or 0) == int(frame)), None)
    if asset is None:
        raise ValueError(f"Visual Lock frame {int(frame):02d} is not a current admission")
    ledger = production_ledger.load_authority(ep, default={}) or {}
    ledger_frame = ((ledger.get("frames") or {}).get(f"{int(frame):02d}") or {})
    candidate = ledger_frame.get("current_candidate") or {}
    if ledger_frame.get("status") != "PASSED":
        raise ValueError(f"frame {int(frame):02d} must be PASSED in production ledger")
    if str(candidate.get("sha256") or "").lower() != str(asset.get("sha256") or "").lower():
        raise ValueError(f"frame {int(frame):02d} candidate SHA does not match Visual Lock asset")
    acceptance = (ledger_frame.get("user_exception_acceptances") or [])[-1:]
    if not acceptance or acceptance[0].get("approval_basis") != "direct_user_review_exception_acceptance":
        raise ValueError(f"frame {int(frame):02d} has no direct user exception acceptance")
    if str(acceptance[0].get("candidate_sha256") or "").lower() != str(asset.get("sha256") or "").lower():
        raise ValueError(f"frame {int(frame):02d} user acceptance SHA does not match current asset")
    review = visual_profile_review_persistence.load(ep) or {}
    rows = review.get("calibration") or []
    row = next((dict(item) for item in rows if str(item.get("id") or "") == str(asset.get("id") or "")), None)
    if row is None:
        raise ValueError(f"automatic Visual Lock review row missing for frame {int(frame):02d}")
    source_attempt = int((review.get("critic_provenance") or {}).get("attempt") or 0)
    entry = visual_lock_admission_state.record_direct_user_pass(
        ep,
        asset=asset,
        review_row=row,
        profile_sha256=contract["profile_sha256"],
        story_os_version=episode_version(ep),
        user_statement=user_statement,
        source_review_attempt=source_attempt,
    )
    projection = visual_lock_admission_state.sync_gate_decisions(ep)
    return {
        "frame": int(frame),
        "asset_sha256": asset.get("sha256"),
        "status": entry.get("status"),
        "approval_basis": entry.get("provenance", {}).get("approval_basis"),
        "gate_projection": projection,
    }


def self_test() -> None:
    assert len(ROLES) == 4
    assert len(BASE_CHECKS) == 11
    assert len(checks_for_version("2.1.0")) == 11
    assert len(checks_for_version("2.2.0")) == 15
    assert len(checks_for_version("2.2.1")) == 18
    assert version_tuple("2.1.0") >= MIN_VERSION
    print("VISUAL LOCK V2.2.1 VERSIONED CHECK MATRIX SELF-TEST PASS")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare"); p.add_argument("episode_dir"); p.add_argument("--production-revision")
    p = sub.add_parser("bind-from-queue"); p.add_argument("episode_dir")
    p = sub.add_parser("run-critic"); p.add_argument("episode_dir"); p.add_argument("--attempt", type=int, default=1); p.add_argument("--codex"); p.add_argument("--timeout", type=int, default=None)
    p = sub.add_parser("finalize-review"); p.add_argument("episode_dir"); p.add_argument("--attempt", type=int, default=1); p.add_argument("--runtime", choices=["WORK", "WEB"], default="WORK")
    p = sub.add_parser("reconcile-admissions"); p.add_argument("episode_dir")
    p = sub.add_parser("accept-direct-user-admission"); p.add_argument("episode_dir"); p.add_argument("--frame", type=int, required=True); p.add_argument("--user-statement", required=True)
    p = sub.add_parser("verify"); p.add_argument("episode_dir")
    p = sub.add_parser("show-plan"); p.add_argument("episode_dir")
    sub.add_parser("self-test")
    args = ap.parse_args()
    if args.cmd == "self-test":
        self_test(); return 0
    ep = resolve_ep(args.episode_dir)
    try:
        if args.cmd == "prepare":
            print(json.dumps(prepare(ep, production_revision_id=args.production_revision), ensure_ascii=False, indent=2)); return 0
        if args.cmd == "bind-from-queue":
            print(json.dumps(bind_from_queue(ep), ensure_ascii=False, indent=2)); return 0
        if args.cmd == "show-plan":
            p = ep / PLAN_REL
            if not p.is_file():
                print(json.dumps(choose_plan(ep), ensure_ascii=False, indent=2))
            else:
                print(p.read_text(encoding="utf-8"))
            return 0
        if args.cmd == "run-critic":
            return run_critic(ep, attempt=args.attempt, codex_raw=args.codex, timeout=args.timeout)
        if args.cmd == "finalize-review":
            return finalize_product_review(ep, attempt=args.attempt, runtime=args.runtime)
        if args.cmd == "reconcile-admissions":
            print(json.dumps(reconcile_admissions(ep), ensure_ascii=False, indent=2)); return 0
        if args.cmd == "accept-direct-user-admission":
            print(json.dumps(accept_direct_user_admission(ep, frame=args.frame, user_statement=args.user_statement), ensure_ascii=False, indent=2)); return 0
        errors = verify(ep)
        if errors:
            for error in errors:
                print("FAIL:", error)
            return 2
        print("VISUAL LOCK V2.1 VERIFIED")
        return 0
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        print("VISUAL LOCK ERROR:", exc)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())

# STORY_OS_V211_RUNTIME_CLOSURE_R31
