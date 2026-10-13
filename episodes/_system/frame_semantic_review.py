#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import hashlib
import content_fingerprint
import json
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Iterable

from PIL import Image

from story_os_contract import story_os_version
import codex_critic_runner as critic_runner
import environment_contract as phase3_env
import frame_contract as phase4_contract
import fast_frame_scout as phase7_scout
import runtime_router
import runtime_provenance
import product_review_adapter
import production_ledger
import episode_performance
import frame_review_persistence
import story_json
import runtime_timeout_policy
import runtime_workspace
import episode_state_persistence
import local_visual_triage
import final_acceptance
import model_policy
import model_policy_persistence
import generation_attempt_authority

ROOT = Path(__file__).resolve().parents[2]
REVIEW_DIR = Path("meta/frame-reviews")
SUMMARY_REL = Path("meta/frame-semantic-review.json")
CANDIDATE_REL = Path("meta/.frame-semantic-review.candidate.json")
EXCEPTION_CANDIDATE_REL = Path("meta/.frame-semantic-exception-review.candidate.json")
EXCEPTION_PENDING_REL = Path("meta/frame-semantic-exception-pending-attempt-3.json")
CONTINUATION_CANDIDATE_REL = Path("meta/.frame-semantic-continuation-review.candidate.json")
CONTINUATION_PENDING_REL = Path("meta/frame-semantic-continuation-pending.json")
PATCH_CANDIDATE_REL = Path("meta/.frame-semantic-patch-review.candidate.json")
PATCH_PENDING_REL = Path("meta/frame-semantic-patch-pending.json")
AUDIT_REL = Path("meta/frame-semantic-audit.json")
PENDING_REQUEST_PREFIX = "frame-semantic-pending-attempt-"
TARGET_CONTRACT = (2, 0, 3, 3)
SCHEMA_VERSION = 2
ABSOLUTE_MAX_FULL_REVIEW_SHARDS = 6
FULL_REVIEW_FANOUT_MIN_FRAMES = 6
PHASE5A_SINGLE_FRAME_SCOPE = "PHASE5A_SINGLE_FRAME"

CHECKS = [
    "scene_storyboard_fidelity",
    "story_beat_fidelity",
    "key_prop_fidelity",
    "character_identity",
    "wardrobe_continuity",
    "pov_photographer_legality",
    "spatial_continuity",
    "temporal_continuity",
    "anomaly_readability",
    "caption_image_support",
    "actual_information_gain",
]

ANATOMY_CHECK = "anatomy_limb_hand_integrity"

V22_VISUAL_NARRATIVE_CHECKS = [
    "camera_authorship_physical",
    "moment_capture_credibility",
    "narrative_evidence_gain",
    "shot_grammar_diversity",
    "camera_defect_physics",
    "screen_content_physics",
    "visual_memory_continuity",
]  # STORY_OS_V22_R2_VERSION_GATED

V21_PHASE3_CHECKS = [
    "environment_physics_fidelity",
    "anomaly_escalation_fidelity",
    "scale_reference_fidelity",
]

V221_WORLD_IDENTITY_CHECKS = [
    "world_identity_fidelity",
    "character_appearance_anchor_fidelity",
    "cultural_environment_fidelity",
]

DIRECTING_V3_CHECKS = [
    "shot_scale_fidelity",
    "scene_position_uniqueness_fidelity",
    "cinematic_structure_translation_fidelity",
    "practical_lighting_design_fidelity",
    "anomaly_concealment_fidelity",
]

def directing_v3_required(ep: Path) -> bool:
    p=Path(ep)/"meta/shot-progression-review.json"
    if not p.is_file(): return False
    try: return int(read_json(p).get("schema_version") or 0) >= 3
    except Exception: return False

def checks_for_version(version: str, directing_v3: bool = False, *, anatomy_required: bool = True) -> list[str]:
    checks = CHECKS + (V21_PHASE3_CHECKS if version_tuple(version) >= (2, 1, 0) else [])
    if version_tuple(version) >= (2, 2, 0):
        checks += V22_VISUAL_NARRATIVE_CHECKS
    if version_tuple(version) >= (2, 2, 1):
        checks += V221_WORLD_IDENTITY_CHECKS
    if directing_v3:
        checks += DIRECTING_V3_CHECKS
    if anatomy_required:
        checks += [ANATOMY_CHECK]
    return checks

ISSUE_CODES = {
    "FRAME_SCENE_MISMATCH",
    "STORY_BEAT_NOT_VISIBLE",
    "KEY_PROP_DRIFT",
    "IDENTITY_DRIFT",
    "WARDROBE_DRIFT",
    "POV_ILLEGAL",
    "SPATIAL_CONTINUITY_BROKEN",
    "TEMPORAL_CONTRADICTION",
    "ANOMALY_UNREADABLE",
    "CAPTION_DEPENDENCY",
    "ACTUAL_INFORMATION_GAIN_MISSING",
    "NEAR_DUPLICATE_ACTUAL_FRAMES",
    "UNEXPLAINED_THIRD_PERSON",
    "UNPLANNED_RECORDER",
    "WEATHER_PHYSICS_MISMATCH",
    "WEATHER_CONTINUITY_BROKEN",
    "ANOMALY_SCALE_UNDERDELIVERED",
    "SCALE_REFERENCE_MISSING",
    "GHOST_CAMERA",
    "CAMERA_OWNER_UNRESOLVED",
    "MOMENT_RESULT_ONLY",
    "NARRATIVE_REDUNDANCY",
    "SHOT_GRAMMAR_REPEAT",
    "CAMERA_DEFECT_UNMOTIVATED",
    "SCREEN_CONTENT_PHYSICS_BROKEN",
    "VISUAL_MEMORY_BROKEN",
    "WORLD_IDENTITY_DRIFT",
    "CHARACTER_APPEARANCE_DRIFT",
    "CULTURAL_CONTEXT_DRIFT",
    "SHOT_SCALE_MISMATCH",
    "SCENE_POSITION_VISUAL_REPEAT",
    "CINEMATIC_TRANSLATION_FAILED",
    "LIGHTING_DESIGN_MISMATCH",
    "ANOMALY_CONCEALMENT_MISSING",
    "ANATOMY_DISTORTION",
    "LIMB_COUNT_ERROR",
    "HAND_INTEGRITY_FAILURE",
}

GLOBAL_CLOSURE_CHECKS = [
    "identity_wardrobe_continuity",
    "spatial_temporal_continuity",
    "visual_memory_continuity",
    "narrative_progression",
    "ending_payoff_coherence",
]
GLOBAL_CLOSURE_ISSUE_CODES = {
    "IDENTITY_DRIFT",
    "WARDROBE_DRIFT",
    "SPATIAL_CONTINUITY_BROKEN",
    "TEMPORAL_CONTRADICTION",
    "WEATHER_CONTINUITY_BROKEN",
    "VISUAL_MEMORY_BROKEN",
    "NARRATIVE_REDUNDANCY",
    "ACTUAL_INFORMATION_GAIN_MISSING",
    "STORY_BEAT_NOT_VISIBLE",
    "WORLD_IDENTITY_DRIFT",
    "CHARACTER_APPEARANCE_DRIFT",
    "CULTURAL_CONTEXT_DRIFT",
}


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


def sha256_json(data: object) -> str:
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def version_tuple(raw: object) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in str(raw or "").split("."))
    except ValueError:
        return (0,)


def review_required(ep: Path) -> bool:
    state = episode_state_persistence.load(Path(ep).resolve()) or {}
    if version_tuple(state.get("tool_version")) >= TARGET_CONTRACT:
        return True
    for rel in ("meta/release-manifest.json", "meta/story-gates.json"):
        p = ep / rel
        if not p.is_file():
            continue
        try:
            if version_tuple(read_json(p).get("tool_version")) >= TARGET_CONTRACT:
                return True
        except Exception:
            continue
    return False


def episode_contract_version(ep: Path) -> str:
    versions: list[tuple[tuple[int, ...], str]] = []
    state = episode_state_persistence.load(Path(ep).resolve()) or {}
    raw = str(state.get("tool_version") or "")
    vt = version_tuple(raw)
    if vt != (0,):
        versions.append((vt, raw))
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
    if versions:
        return max(versions, key=lambda x: x[0])[1]
    return story_os_version()


def repo_path(raw: object, where: str, *, require_file: bool = True) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"{where} missing")
    rel = Path(raw.strip())
    p = rel.resolve() if rel.is_absolute() else (ROOT / rel).resolve()
    try:
        p.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise ValueError(f"{where} escapes repository") from exc
    if require_file and not p.is_file():
        raise ValueError(f"{where} missing: {raw}")
    return p


def repo_rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def episode_files(ep: Path) -> tuple[Path, Path]:
    manifest = read_json(ep / "meta/release-manifest.json")
    artifacts = manifest.get("artifacts") or {}
    return (
        repo_path(artifacts.get("story"), "manifest.artifacts.story"),
        repo_path(artifacts.get("storyboard"), "manifest.artifacts.storyboard"),
    )


def stable_visual_contract(ep: Path) -> dict:
    gates = read_json(ep / "meta/story-gates.json")
    visual = gates.get("visual") or {}
    return {
        "visual_profile": gates.get("visual_profile") or {},
        "authenticity_card": visual.get("authenticity_card") or {},
        "continuity": visual.get("continuity") or {},
        "references": visual.get("references") or {},
    }


def context_hashes(ep: Path) -> dict:
    story, storyboard = episode_files(ep)
    return {
        "story_sha256": content_fingerprint.sha256_file(story),
        "storyboard_sha256": content_fingerprint.sha256_file(storyboard),
        "visual_contract_sha256": sha256_json(stable_visual_contract(ep)),
    }


def phase3_context_hashes(ep: Path, frame: str) -> dict:
    out = phase3_env.frame_hashes(ep, frame) if phase3_env.required(ep) else {}
    if phase4_contract.required(ep):
        contract = phase4_contract.compile_frame(ep, frame, write_cache=False)
        out["frame_contract_sha256"] = contract["contract_sha256"]
    return out


def source_binding(ep: Path, frame: str) -> dict:
    """Stable Story/Storyboard source footprint used by frame reviews."""
    if not phase4_contract.required(ep):
        return {}
    return phase4_contract.source_binding(ep, frame)


def review_source_bindings(ep: Path, frames: list[dict]) -> dict:
    """Freeze semantic inputs, not regenerated cache files with wall-clock stamps."""
    return {
        "story_os_version": episode_contract_version(ep),
        "contexts": context_hashes(ep),
        "frames": {row["frame"]: {
            "asset_path": row["path_rel"], "asset_sha256": row["sha256"],
            **phase3_context_hashes(ep, row["frame"]),
            "source_binding": source_binding(ep, row["frame"]),
        } for row in frames},
    }


def current_generation_binding(ep: Path, frame: str | int, asset: dict | None = None,
                               ledger: dict | None = None) -> dict:
    """Return the current frame identity used by semantic evidence reuse.

    The production ledger selects the current candidate/approved artifact; the
    generation key must come from that exact artifact or its bound attempt.
    Missing generation identity is intentionally not guessed from frame number.
    """
    ledger = ledger if isinstance(ledger, dict) else (production_ledger.load_authority(ep, default={}) or {})
    key = str(frame).zfill(2)
    row = ((ledger.get("frames") or {}).get(key) or {})
    selected = asset if isinstance(asset, dict) else None
    if selected is None:
        selected = row.get("approved_asset") if isinstance(row.get("approved_asset"), dict) else None
        if selected is None:
            selected = row.get("current_candidate") if isinstance(row.get("current_candidate"), dict) else None
    generation_key = str((selected or {}).get("generation_key") or "")
    production_revision_id = str((selected or {}).get("production_revision_id") or "")
    if not generation_key:
        attempt_id = str((selected or {}).get("attempt_id") or "")
        for attempt in reversed([x for x in (row.get("attempts") or []) if isinstance(x, dict)]):
            if attempt_id and str(attempt.get("attempt_id") or "") == attempt_id:
                generation_key = str(attempt.get("generation_key") or "")
                production_revision_id = str(attempt.get("production_revision_id") or "")
                break
    if not generation_key:
        # Promotion copies the exact pixels into approved_asset but older ledger
        # rows did not copy generation_key/attempt_id with them. Recover identity
        # only by exact artifact SHA and only when it resolves to one unique
        # generation key; never guess from frame number or latest attempt.
        selected_sha = str((selected or {}).get("sha256") or "").lower()
        matching_keys: set[str] = set()
        current_candidate = row.get("current_candidate")
        if (selected_sha and isinstance(current_candidate, dict)
                and str(current_candidate.get("sha256") or "").lower() == selected_sha):
            value = str(current_candidate.get("generation_key") or "")
            if value:
                matching_keys.add(value)
        for attempt in [x for x in (row.get("attempts") or []) if isinstance(x, dict)]:
            candidate = attempt.get("candidate") if isinstance(attempt.get("candidate"), dict) else {}
            if selected_sha and str(candidate.get("sha256") or "").lower() == selected_sha:
                value = str(candidate.get("generation_key") or attempt.get("generation_key") or "")
                if value:
                    matching_keys.add(value)
        if len(matching_keys) == 1:
            generation_key = next(iter(matching_keys))
    logical_key = generation_attempt_authority.frame_key(ep, key)
    if not production_revision_id:
        selected_attempt_id = str((selected or {}).get("attempt_id") or "")
        selected_sha = str((selected or {}).get("sha256") or "").lower()
        for attempt in reversed([x for x in (row.get("attempts") or []) if isinstance(x, dict)]):
            candidate = attempt.get("candidate") if isinstance(attempt.get("candidate"), dict) else {}
            if ((selected_attempt_id and str(attempt.get("attempt_id") or "") == selected_attempt_id)
                    or (selected_sha and str(candidate.get("sha256") or "").lower() == selected_sha)):
                production_revision_id = str(attempt.get("production_revision_id") or candidate.get("production_revision_id") or "")
                break
    binding = {"logical_asset_key": logical_key, "generation_key": generation_key or None}
    if production_revision_id:
        binding["production_revision_id"] = production_revision_id
    return binding


def bound_review_policy_sha256(ep: Path) -> str | None:
    """Read the Episode-frozen final vision role policy, never Global config."""
    try:
        policy = model_policy_persistence.load(Path(ep).resolve())
        if not isinstance(policy, dict):
            return None
    except (RuntimeError, ValueError, KeyError, TypeError):
        return None
    # The whole Episode policy snapshot is the frozen authority identity. Do not
    # resolve against current Global config during reuse or canonical verification.
    value = str(policy.get("policy_sha256") or "").strip().lower()
    return value or None


def frame_evidence_fingerprint(frame: dict, *, contexts: dict, phase3_contexts: dict,
                               policy_sha256: str | None, schema_version: int = SCHEMA_VERSION) -> str | None:
    """Canonical fingerprint for semantic reuse; excludes timestamps and paths."""
    logical_key = str(frame.get("logical_asset_key") or "")
    generation_key = str(frame.get("generation_key") or "")
    artifact_sha = str(frame.get("sha256") or "").lower()
    policy_sha = str(policy_sha256 or "").lower()
    if not all((logical_key, generation_key, artifact_sha, policy_sha)):
        return None
    payload = {
        "evidence_type": "FRAME_SEMANTIC_REVIEW",
        "logical_asset_key": logical_key,
        "generation_key": generation_key,
        "production_revision_id": str(frame.get("production_revision_id") or "") or None,
        "artifact_sha256": artifact_sha,
        "source_binding": frame.get("source_binding") or {},
        "context": contexts,
        "phase3_context": phase3_contexts,
        "model_policy_sha256": policy_sha,
        "review_schema_version": int(schema_version),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def review_evidence_fingerprint(
    frame: dict, *, contexts: dict, phase3_contexts: dict,
    policy_sha256: str | None, review_item_id: str, attempt_index: int,
    frame_contract_sha256: str | None = None,
    prompt_package_sha256: str | None = None,
    reviewer_role: str = "vision.final",
    schema_version: int = SCHEMA_VERSION,
) -> str | None:
    """Canonical identity for a queue-bound final semantic review.

    This extends the stable frame evidence fingerprint with the review work item
    and reviewer role. It deliberately excludes paths, process IDs and clocks.
    """
    base = frame_evidence_fingerprint(
        frame, contexts=contexts, phase3_contexts=phase3_contexts,
        policy_sha256=policy_sha256, schema_version=schema_version)
    item_id = str(review_item_id or "").strip()
    role = str(reviewer_role or "").strip()
    if not base or not item_id or not role:
        return None
    payload = {
        "evidence_type": "FINAL_SEMANTIC_REVIEW",
        "frame_evidence_fingerprint": base,
        "review_item_id": item_id,
        "attempt_index": int(attempt_index),
        "logical_asset_key": str(frame.get("logical_asset_key") or ""),
        "generation_key": str(frame.get("generation_key") or ""),
        "candidate_sha256": str(frame.get("sha256") or "").lower(),
        "frame_contract_sha256": str(frame_contract_sha256 or "").lower(),
        "prompt_package_sha256": str(prompt_package_sha256 or "").lower(),
        "model_policy_sha256": str(policy_sha256 or "").lower(),
        "reviewer_role": role,
        "review_schema_version": int(schema_version),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def validate_final_semantic_execution_receipt(receipt: dict, expected: dict) -> list[str]:
    """Validate durable Final Semantic execution evidence against one work item."""
    errors: list[str] = []
    if not isinstance(receipt, dict):
        return ["model execution receipt missing"]
    required = {
        "receipt_schema_version": 2,
        "status": "SUCCESS",
        "model_role": "vision.final",
        "profile": "vision_final",
        "requested_model": "gpt-6-luna",
        "effective_model": "gpt-6-luna",
        "reasoning_effort": "high",
        "effective_model_source": "EXPLICIT_RUNTIME_BINDING",
        "returncode": 0,
        "turn_completed": True,
    }
    for field, value in required.items():
        if receipt.get(field) != value:
            errors.append(f"receipt {field} mismatch")
    for field in (
        "review_item_id", "logical_asset_key", "generation_key", "production_revision_id", "attempt_index",
        "candidate_sha256", "frame_contract_sha256", "prompt_package_sha256",
        "model_policy_sha256", "evidence_fingerprint", "runner_request_id",
        "result_sha256", "result_ref", "created_at",
    ):
        actual = receipt.get(field)
        wanted = expected.get(field)
        # Revision binding is mandatory when the work item belongs to an
        # activated Revision. Legacy production records predate this field and
        # remain valid only when the expected binding is absent.
        if field == "production_revision_id" and wanted in (None, ""):
            continue
        if field == "attempt_index":
            try:
                matches = int(actual or 0) == int(wanted or 0)
            except (TypeError, ValueError):
                matches = False
        else:
            matches = str(actual or "").lower() == str(wanted or "").lower()
        if wanted not in (None, "") and not matches:
            errors.append(f"receipt {field} mismatch")
        elif actual in (None, ""):
            errors.append(f"receipt {field} missing")
    if receipt.get("provider_reported_model"):
        errors.append("receipt must not claim provider-reported model without provider evidence")
    return errors


def _read_model_execution_receipt(ep: Path, receipt_ref: str | None) -> tuple[dict | None, Path | None]:
    raw = str(receipt_ref or "").strip()
    if not raw:
        return None, None
    path = repo_path(raw, "Final Semantic model execution receipt")
    if not path.is_absolute():
        path = (ROOT / path).resolve()
    if not path.is_file():
        return None, path
    try:
        value = read_json(path)
    except Exception:
        return None, path
    return (value if isinstance(value, dict) else None), path


def _find_pending_final_semantic_receipt(
    ep: Path, *, review_item: dict, frame: dict, attempt: int,
) -> tuple[dict, Path]:
    """Find one exact receipt for the pending review item.

    Recovery is idempotent: the same receipt may already have advanced from
    PENDING_VALIDATION to SUCCESS after an earlier partial commit. A validated
    SUCCESS receipt is reusable only when every immutable review identity field
    still matches; failed/cancelled/foreign receipts are never selected.
    """
    directory = Path(ep) / "meta/provider-receipts/model-executions"
    expected = {
        "model_role": "vision.final",
        "profile": "vision_final",
        "requested_model": "gpt-6-luna",
        "effective_model": "gpt-6-luna",
        "reasoning_effort": "high",
        "model_policy_sha256": bound_review_policy_sha256(ep),
        "logical_asset_key": frame.get("logical_asset_key"),
        "generation_key": frame.get("generation_key"),
        "production_revision_id": frame.get("production_revision_id"),
        "attempt_index": int(attempt),
        "artifact_sha256": str(frame.get("sha256") or "").lower(),
        "review_item_id": str(review_item.get("review_key") or review_item.get("id") or ""),
    }
    matches: list[tuple[dict, Path]] = []
    for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
        try:
            value = read_json(path)
        except Exception:
            continue
        if not isinstance(value, dict):
            continue
        if not all(value.get(key) == expected_value for key, expected_value in expected.items()):
            continue
        status = str(value.get("status") or "")
        if status == "PENDING_VALIDATION":
            matches.append((value, path))
        elif status == "SUCCESS" and value.get("durable_result_status") == "VALIDATED":
            matches.append((value, path))
    if len(matches) != 1:
        raise RuntimeError("FINAL_SEMANTIC_PENDING_RECEIPT_NOT_UNIQUE")
    return matches[0]


def _read_durable_result_projection(
    ep: Path, receipt: dict, *, request_id: str,
) -> tuple[Path, dict]:
    """Read and validate the secret-safe durable projection without rewriting it."""
    if receipt.get("durable_result_status") != "VALIDATED":
        raise RuntimeError("FINAL_SEMANTIC_DURABLE_PROJECTION_NOT_VALIDATED")
    raw_ref = str(receipt.get("result_ref") or "").strip()
    if not raw_ref:
        raise RuntimeError("FINAL_SEMANTIC_DURABLE_PROJECTION_REF_MISSING")
    relative = Path(raw_ref)
    if relative.is_absolute():
        raise RuntimeError("FINAL_SEMANTIC_DURABLE_PROJECTION_PATH_INVALID")
    episode = Path(ep).resolve()
    projection_path = (episode / relative).resolve()
    try:
        projection_path.relative_to(episode)
    except ValueError as exc:
        raise RuntimeError("FINAL_SEMANTIC_DURABLE_PROJECTION_PATH_INVALID") from exc
    if not projection_path.is_file():
        raise RuntimeError("FINAL_SEMANTIC_DURABLE_PROJECTION_MISSING")
    expected_sha = str(receipt.get("result_sha256") or "").lower()
    if len(expected_sha) != 64 or sha256_file(projection_path).lower() != expected_sha:
        raise RuntimeError("FINAL_SEMANTIC_DURABLE_PROJECTION_SHA_MISMATCH")
    try:
        projection = json.loads(projection_path.read_bytes().decode("utf-8-sig"))
    except Exception as exc:
        raise RuntimeError("FINAL_SEMANTIC_DURABLE_PROJECTION_INVALID") from exc
    if (not isinstance(projection, dict)
            or projection.get("schema") != "storyos.user_runner_result_projection.v1"
            or str(projection.get("request_id") or "") != request_id
            or int(projection.get("returncode", -1)) != 0
            or projection.get("turn_completed") is not True
            or not isinstance(projection.get("structured_result"), dict)):
        raise RuntimeError("FINAL_SEMANTIC_DURABLE_PROJECTION_BINDING_MISMATCH")
    return projection_path, projection


def _validate_durable_result_projection(
    ep: Path, receipt: dict, *, request_id: str, durable_result: dict,
) -> Path:
    """Validate Slot2's secret-safe durable result projection without rewriting it."""
    projection_path, projection = _read_durable_result_projection(
        ep, receipt, request_id=request_id)
    if projection.get("structured_result") != durable_result:
        raise RuntimeError("FINAL_SEMANTIC_DURABLE_PROJECTION_BINDING_MISMATCH")
    return projection_path


def _finalize_final_semantic_receipt(
    ep: Path, *, receipt_ref: str | None, review_item: dict | None,
    frame: dict, candidate: Path, log_path: Path, returncode: int,
    remote: dict, contexts: dict,
) -> dict:
    """Promote a provisional runner receipt only after completed durable output."""
    receipt, path = _read_model_execution_receipt(ep, receipt_ref)
    if not isinstance(receipt, dict) or path is None:
        raise RuntimeError("FINAL_SEMANTIC_MODEL_EXECUTION_RECEIPT_MISSING")
    item = review_item if isinstance(review_item, dict) else {}
    item_id = str(item.get("review_item_id") or item.get("id") or item.get("review_key") or "")
    request_id = str((remote or {}).get("request_id") or "")
    if not item_id or not request_id or int(returncode) != 0:
        raise RuntimeError("FINAL_SEMANTIC_DURABLE_EXECUTION_BINDING_MISSING")
    try:
        import base64
        import codex_user_runner
        durable = codex_user_runner.read_task_result(request_id)
        raw = base64.b64decode(str(durable.get("output_base64") or ""), validate=True)
        durable_log = raw.decode("utf-8-sig", errors="replace")
    except Exception as exc:
        raise RuntimeError("FINAL_SEMANTIC_DURABLE_RESULT_INVALID") from exc
    if (not durable or str(durable.get("request_id") or "") != request_id
            or int(durable.get("returncode", -1)) != 0):
        raise RuntimeError("FINAL_SEMANTIC_DURABLE_RESULT_NOT_COMPLETED")
    events = []
    thread_id = ""
    for raw_line in durable_log.splitlines():
        try:
            event = json.loads(raw_line)
        except Exception:
            continue
        if isinstance(event, dict):
            events.append(event)
            if event.get("type") == "thread.started":
                thread_id = str((event.get("thread") or {}).get("id") or "")
    has_turn_completed = any(row.get("type") == "turn.completed" for row in events)
    if not has_turn_completed:
        raise RuntimeError("FINAL_SEMANTIC_TURN_NOT_COMPLETED")
    import codex_critic_runner
    if receipt.get("durable_result_status") != "VALIDATED":
        recovered_projection = codex_critic_runner._persist_final_semantic_durable_result(
            ep, {"request_id": request_id}, int(returncode), output_path=candidate,
        )
        if recovered_projection.get("durable_result_status") != "VALIDATED":
            raise RuntimeError("FINAL_SEMANTIC_STRUCTURED_RESULT_NOT_DURABLE")
        receipt.update(recovered_projection)
    durable_result = codex_critic_runner.recover_completed_agent_json(durable_log)
    if not isinstance(durable_result, dict):
        # With schema-bound `-o`, recent Codex builds can emit a prose final
        # agent_message while persisting the actual structured result to the
        # output file. Slot2 already bound that file into a SHA-verified durable
        # projection after rc=0 + turn.completed, so recover from that projection
        # rather than treating a successful review as a technical failure.
        _projection_path, projection = _read_durable_result_projection(
            ep, receipt, request_id=request_id)
        durable_result = projection.get("structured_result")
    if not isinstance(durable_result, dict):
        raise RuntimeError("FINAL_SEMANTIC_STRUCTURED_RESULT_NOT_DURABLE")
    _validate_durable_result_projection(
        ep, receipt, request_id=request_id, durable_result=durable_result)
    try:
        result = read_json(candidate)
    except Exception as exc:
        raise RuntimeError("FINAL_SEMANTIC_RESULT_INVALID") from exc
    if not isinstance(result, dict):
        raise RuntimeError("FINAL_SEMANTIC_RESULT_INVALID")
    if durable_result != result:
        raise RuntimeError("FINAL_SEMANTIC_DURABLE_RESULT_MISMATCH")
    if not log_path.is_file():
        raise RuntimeError("FINAL_SEMANTIC_RUNNER_LOG_MISSING")
    frame_no = str(frame.get("frame") or "").zfill(2)
    phase3 = phase3_context_hashes(ep, frame_no)
    policy_sha = bound_review_policy_sha256(ep)
    identity = {**frame, "source_binding": source_binding(ep, frame_no)}
    fingerprint = review_evidence_fingerprint(
        identity, contexts=contexts, phase3_contexts=phase3,
        policy_sha256=policy_sha, review_item_id=item_id,
        attempt_index=int(item.get("attempt_index") or 0),
        frame_contract_sha256=phase3.get("frame_contract_sha256"),
        prompt_package_sha256=item.get("prompt_package_sha256"),
    )
    if not fingerprint:
        raise RuntimeError("FINAL_SEMANTIC_EVIDENCE_FINGERPRINT_MISSING")
    receipt.update({
        "receipt_schema_version": 2,
        "status": "SUCCESS",
        "returncode": int(returncode),
        "turn_completed": True,
        "runner_request_id": request_id,
        "thread_id": thread_id or str((remote or {}).get("thread_id") or ""),
        "review_item_id": item_id,
        "logical_asset_key": frame.get("logical_asset_key"),
        "generation_key": frame.get("generation_key"),
        "production_revision_id": item.get("production_revision_id"),
        "attempt_index": int(item.get("attempt_index") or 0),
        "candidate_sha256": str(frame.get("sha256") or "").lower(),
        "frame_contract_sha256": phase3.get("frame_contract_sha256"),
        "prompt_package_sha256": item.get("prompt_package_sha256"),
        "model_policy_sha256": policy_sha,
        "evidence_fingerprint": fingerprint,
        "candidate_result_sha256": sha256_file(candidate),
        "execution_completion_source": "USER_RUNNER_DURABLE_RESULT",
        "effective_model_source": "EXPLICIT_RUNTIME_BINDING",
        # SUCCESS receipts are immutable replay evidence. Preserve the original
        # timestamp so deterministic recovery keeps the exact receipt SHA bound
        # by an already-decided Review Commit Manifest.
        "created_at": receipt.get("created_at") or now(),
    })
    if not receipt.get("prompt_package_sha256"):
        raise RuntimeError("FINAL_SEMANTIC_PROMPT_PACKAGE_BINDING_MISSING")
    # Keep the SUCCESS receipt in memory until the candidate, frame/source
    # bindings, queue identity, policy and fingerprint have all passed the
    # pure commit planner. The runner's durable receipt remains
    # PENDING_VALIDATION in the meantime.
    return receipt


def _commit_final_semantic_execution_receipt(
    ep: Path, *, receipt_ref: str | None, validated_receipt: dict | None,
) -> None:
    """Persist a validated execution receipt at the start of the commit phase."""
    if not isinstance(validated_receipt, dict):
        raise RuntimeError("FINAL_SEMANTIC_MODEL_EXECUTION_RECEIPT_MISSING")
    stored, path = _read_model_execution_receipt(ep, receipt_ref)
    if not isinstance(stored, dict) or path is None:
        raise RuntimeError("FINAL_SEMANTIC_MODEL_EXECUTION_RECEIPT_MISSING")
    if (stored.get("status") not in {"PENDING_VALIDATION", "SUCCESS"}
            or str(stored.get("call_id") or "") != str(validated_receipt.get("call_id") or "")):
        raise RuntimeError("FINAL_SEMANTIC_PROVISIONAL_RECEIPT_BINDING_MISMATCH")
    if stored.get("status") == "SUCCESS":
        if stored != validated_receipt:
            raise RuntimeError("FINAL_SEMANTIC_COMMITTED_RECEIPT_CONFLICT")
        return
    write_json(path, validated_receipt)


REVIEW_COMMIT_SCHEMA = "phase5a-final-semantic-review-commit/v1"


def review_commit_id(
    review_item_id: str, generation_key: str, attempt_index: int,
    evidence_fingerprint: str,
) -> str:
    """Stable idempotency key for one queue-bound Final Semantic decision."""
    identity = {
        "review_item_id": str(review_item_id or "").strip(),
        "generation_key": str(generation_key or "").strip(),
        "attempt_index": int(attempt_index),
        "evidence_fingerprint": str(evidence_fingerprint or "").lower(),
    }
    if not all((identity["review_item_id"], identity["generation_key"],
                identity["evidence_fingerprint"])) or identity["attempt_index"] not in {1, 2}:
        raise ValueError("review commit identity is incomplete")
    raw = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def review_commit_manifest_path(ep: Path, commit_id: str) -> Path:
    return Path(ep) / "meta/runtime/review-commits" / f"{str(commit_id)}.json"


def load_review_commit(ep: Path, commit_id: str) -> dict | None:
    """Load one Review commit decision for verified projection consumers."""
    path = review_commit_manifest_path(ep, commit_id)
    if not path.is_file():
        return None
    value = read_json(path)
    return value if isinstance(value, dict) else None


def find_review_commit_for_item(ep: Path, review_item_id: str) -> dict | None:
    """Find the unique decided commit for a queue item; ambiguity fails closed."""
    directory = Path(ep) / "meta/runtime/review-commits"
    if not directory.is_dir():
        return None
    matches = []
    for path in sorted(directory.glob("*.json")):
        try:
            value = read_json(path)
        except Exception as exc:
            raise RuntimeError("FINAL_SEMANTIC_REVIEW_COMMIT_MANIFEST_UNREADABLE") from exc
        if not isinstance(value, dict) or value.get("schema") != REVIEW_COMMIT_SCHEMA:
            continue
        if str(value.get("review_item_id") or "") != str(review_item_id or ""):
            continue
        expected_id = review_commit_id(
            str(value.get("review_item_id") or ""),
            str(value.get("generation_key") or ""),
            int(value.get("attempt_index") or 0),
            str(value.get("evidence_fingerprint") or ""),
        )
        commit_id = str(value.get("review_commit_id") or "")
        if commit_id != expected_id or path.stem != commit_id:
            raise RuntimeError("FINAL_SEMANTIC_REVIEW_COMMIT_IDENTITY_MISMATCH")
        matches.append({"commit_id": commit_id, "manifest": value})
    if len(matches) > 1:
        raise RuntimeError("FINAL_SEMANTIC_REVIEW_COMMIT_AMBIGUOUS")
    return matches[0] if matches else None


def review_commit_is_decided(manifest: dict | None) -> bool:
    return (isinstance(manifest, dict)
            and manifest.get("schema") == REVIEW_COMMIT_SCHEMA
            and manifest.get("status") in {"COMMIT_DECIDED", "PROJECTIONS_APPLIED"})


def _write_review_commit_decision(ep: Path, plan: dict, receipt: dict) -> str:
    """Persist a validated decision marker before applying success projections.

    The immutable pending request and candidate remain the replay input until
    local projections verify. A decided commit can therefore be re-applied by
    the normal deterministic candidate path without redispatching a model.
    Queue terminalization remains a separate required gate.
    """
    commit_id = str(plan.get("review_commit_id") or "")
    if not commit_id:
        raise RuntimeError("FINAL_SEMANTIC_REVIEW_COMMIT_ID_MISSING")
    path = review_commit_manifest_path(ep, commit_id)
    receipt_raw = json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    attempt_index = int(plan.get("attempt_index") or 0)
    request_path = pending_request_path(Path(ep), attempt_index)
    candidate_path = Path(ep) / CANDIDATE_REL
    if not request_path.is_file() or not candidate_path.is_file():
        raise RuntimeError("FINAL_SEMANTIC_REVIEW_REPLAY_INPUT_MISSING")
    manifest = {
        "schema": REVIEW_COMMIT_SCHEMA,
        "status": "COMMIT_DECIDED",
        "review_commit_id": commit_id,
        "review_item_id": plan.get("review_item_id"),
        "generation_key": plan.get("generation_key"),
        "logical_asset_key": plan.get("logical_asset_key"),
        "attempt_index": plan.get("attempt_index"),
        "review_attempt": plan.get("attempt"),
        "frame": (plan.get("frames") or [None])[0],
        "candidate_sha256": plan.get("candidate_sha256", [None])[0],
        "frame_contract_sha256": plan.get("frame_contract_sha256"),
        "prompt_package_sha256": plan.get("prompt_package_sha256"),
        "model_policy_sha256": plan.get("model_policy_sha256"),
        "evidence_fingerprint": plan.get("evidence_fingerprint"),
        "receipt_sha256": hashlib.sha256(receipt_raw).hexdigest(),
        "replay_inputs": {
            "pending_request": str(request_path.relative_to(Path(ep))).replace("\\", "/"),
            "pending_request_sha256": sha256_file(request_path),
            "candidate": str(candidate_path.relative_to(Path(ep))).replace("\\", "/"),
            "candidate_input_sha256": sha256_file(candidate_path),
        },
        "target_projections": [
            "model_execution_receipt", "production_ledger", "approved_asset",
            "frame_review", "review_summary",
        ],
        "separate_commit_required": ["review_queue_terminal"],
        "projection_recovery": "REPLAY_FROM_BOUND_PENDING_CANDIDATE",
        "created_at": now(),
        "applied_at": None,
    }
    if path.is_file():
        existing = read_json(path)
        comparable = {key: value for key, value in existing.items()
                      if key not in {"created_at", "applied_at", "status"}}
        expected_comparable = {key: value for key, value in manifest.items()
                               if key not in {"created_at", "applied_at", "status"}}
        if comparable != expected_comparable:
            raise RuntimeError("FINAL_SEMANTIC_REVIEW_COMMIT_ID_CONFLICT")
        if review_commit_is_decided(existing):
            return commit_id
    import runtime_atomic_store
    runtime_atomic_store.atomic_write_json(path, manifest)
    return commit_id


def mark_review_commit_projections_applied(ep: Path, commit_id: str) -> dict:
    """Mark successful local Review projections; Queue terminal is checked separately."""
    path = review_commit_manifest_path(ep, commit_id)
    manifest = load_review_commit(ep, commit_id)
    if not review_commit_is_decided(manifest):
        raise RuntimeError("FINAL_SEMANTIC_REVIEW_COMMIT_NOT_DECIDED")
    if manifest.get("status") == "PROJECTIONS_APPLIED":
        return manifest
    manifest["status"] = "PROJECTIONS_APPLIED"
    manifest["applied_at"] = now()
    import runtime_atomic_store
    runtime_atomic_store.atomic_write_json(path, manifest)
    return manifest


def review_commit_replay_inputs_valid(ep: Path, manifest: dict) -> bool:
    """Return true only while the immutable request/candidate replay pair matches."""
    inputs = manifest.get("replay_inputs") if isinstance(manifest, dict) else None
    if not isinstance(inputs, dict):
        return False
    ep = Path(ep).resolve()
    for path_key, sha_key in (("pending_request", "pending_request_sha256"),
                              ("candidate", "candidate_input_sha256")):
        relative = str(inputs.get(path_key) or "")
        path = (ep / relative).resolve()
        try:
            path.relative_to(ep)
        except ValueError:
            return False
        expected_sha = str(inputs.get(sha_key) or "").lower()
        if not path.is_file() or len(expected_sha) != 64 or sha256_file(path).lower() != expected_sha:
            return False
    return True


def review_commit_projections_verified(ep: Path, commit_id: str) -> bool:
    """Verify all local single-frame projections after a lost caller response.

    This intentionally does not verify or mutate Review Queue terminal state;
    the queue owner must still attach its SUCCESS receipt before authority PASS.
    """
    ep = Path(ep).resolve()
    manifest = load_review_commit(ep, commit_id)
    if not review_commit_is_decided(manifest):
        return False
    if manifest.get("projection_recovery") != "REPLAY_FROM_BOUND_PENDING_CANDIDATE":
        return False
    frame = str(manifest.get("frame") or "").zfill(2)
    if frame == "00":
        return False
    summary_path = ep / SUMMARY_REL
    if not summary_path.is_file():
        return False
    try:
        summary = read_json(summary_path)
    except Exception:
        return False
    receipt = ((summary.get("critic_provenance") or {}).get("model_execution_receipt")
               if isinstance(summary, dict) else None)
    if not isinstance(receipt, dict):
        return False
    raw = json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if hashlib.sha256(raw).hexdigest() != str(manifest.get("receipt_sha256") or ""):
        return False
    if (str(receipt.get("review_item_id") or "") != str(manifest.get("review_item_id") or "")
            or str(receipt.get("generation_key") or "") != str(manifest.get("generation_key") or "")
            or str(receipt.get("logical_asset_key") or "") != str(manifest.get("logical_asset_key") or "")
            or int(receipt.get("attempt_index") or 0) != int(manifest.get("attempt_index") or 0)
            or str(receipt.get("candidate_sha256") or "").lower() != str(manifest.get("candidate_sha256") or "").lower()
            or str(receipt.get("model_policy_sha256") or "") != str(manifest.get("model_policy_sha256") or "")
            or str(receipt.get("evidence_fingerprint") or "") != str(manifest.get("evidence_fingerprint") or "")):
        return False
    ledger = production_ledger.load_authority(ep, default={}) or {}
    row = ((ledger.get("frames") or {}).get(frame) or {})
    approved = row.get("approved_asset") if isinstance(row.get("approved_asset"), dict) else {}
    if str(row.get("status") or "").upper() not in {"PASSED", "LOCKED"}:
        return False
    expected_sha = str(manifest.get("candidate_sha256") or "").lower()
    if str(approved.get("sha256") or "").lower() != expected_sha:
        return False
    try:
        current = frame_records(ep, require_files=False, only_frames=[int(frame)])
        if len(current) != 1 or str(current[0].get("sha256") or "").lower() != expected_sha:
            return False
        return not verify_scoped_review(
            ep, current, review_scope=PHASE5A_SINGLE_FRAME_SCOPE, metadata_only=True)
    except Exception:
        return False


def _recover_review_commit_from_archive(ep: Path, manifest: dict) -> dict | None:
    """Rebuild missing local review projections from the bound review archive.

    This path is intentionally model/provider-free. It is allowed only when the
    archive proves the exact decided commit, original critic candidate byte SHA,
    SUCCESS receipt, approved pixels, pending request and current source bindings.
    """
    ep = Path(ep).resolve()
    attempt = int(manifest.get("review_attempt") or 0)
    frame_no = str(manifest.get("frame") or "").zfill(2)
    if attempt <= 0 or frame_no == "00":
        return None
    archive_path = ep / "meta" / f"frame-semantic-candidate-attempt-{attempt}.json"
    request_path = pending_request_path(ep, attempt)
    if not archive_path.is_file() or not request_path.is_file():
        return None
    try:
        archive = read_json(archive_path)
        pending = read_json(request_path)
    except Exception:
        return None
    if not isinstance(archive, dict) or not isinstance(pending, dict):
        return None
    data = archive.get("critic_result")
    provenance = archive.get("critic_provenance")
    plan = archive.get("review_commit_plan")
    review_item = pending.get("review_item")
    if not all(isinstance(value, dict) for value in (data, provenance, plan, review_item)):
        return None
    if (int(archive.get("attempt") or 0) != attempt
            or archive.get("review_scope") != PHASE5A_SINGLE_FRAME_SCOPE
            or str(provenance.get("review_commit_id") or "") != str(manifest.get("review_commit_id") or "")):
        return None

    inputs = manifest.get("replay_inputs") if isinstance(manifest.get("replay_inputs"), dict) else {}
    expected_candidate_input_sha = str(inputs.get("candidate_input_sha256") or "").lower()
    if (len(expected_candidate_input_sha) != 64
            or str(provenance.get("candidate_sha256") or "").lower() != expected_candidate_input_sha):
        return None
    pending_sha = str(inputs.get("pending_request_sha256") or "").lower()
    if len(pending_sha) != 64 or sha256_file(request_path).lower() != pending_sha:
        return None

    direct_fields = (
        "review_commit_id", "review_item_id", "generation_key", "logical_asset_key",
        "attempt_index", "frame_contract_sha256", "prompt_package_sha256",
        "model_policy_sha256", "evidence_fingerprint",
    )
    if any(plan.get(key) != manifest.get(key) for key in direct_fields):
        return None
    candidate_shas = plan.get("candidate_sha256") if isinstance(plan.get("candidate_sha256"), list) else []
    if (len(candidate_shas) != 1
            or str(candidate_shas[0] or "").lower() != str(manifest.get("candidate_sha256") or "").lower()):
        return None
    if str(review_item.get("review_key") or review_item.get("id") or "") != str(manifest.get("review_item_id") or ""):
        return None

    receipt = provenance.get("model_execution_receipt")
    if not isinstance(receipt, dict) or receipt.get("status") != "SUCCESS" or receipt.get("durable_result_status") != "VALIDATED":
        return None
    receipt_raw = json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if hashlib.sha256(receipt_raw).hexdigest() != str(manifest.get("receipt_sha256") or ""):
        return None

    try:
        current = frame_records(ep, require_files=True, only_frames=[int(frame_no)])
    except Exception:
        return None
    if len(current) != 1:
        return None
    current_frame = current[0]
    if (str(current_frame.get("sha256") or "").lower() != str(manifest.get("candidate_sha256") or "").lower()
            or str(current_frame.get("generation_key") or "") != str(manifest.get("generation_key") or "")
            or str(current_frame.get("logical_asset_key") or "") != str(manifest.get("logical_asset_key") or "")):
        return None
    reviewed_assets = archive.get("reviewed_assets") if isinstance(archive.get("reviewed_assets"), list) else []
    current_assets = [{"frame": current_frame["frame"], "path": current_frame["path_rel"],
                       "sha256": current_frame["sha256"]}]
    if reviewed_assets != current_assets:
        return None
    frozen_sources = review_source_bindings(ep, current)
    if provenance.get("review_source_bindings") != frozen_sources:
        return None

    replay_provenance = dict(provenance)
    replay_provenance["review_scope"] = PHASE5A_SINGLE_FRAME_SCOPE
    replay_provenance["reviewed_candidate_assets"] = reviewed_assets
    result = _persist_candidate(
        ep,
        data=data,
        current=current,
        contexts=context_hashes(ep),
        phashes=perceptual_rows(current),
        provenance=replay_provenance,
        frozen_sources=frozen_sources,
        verification_scope=PHASE5A_SINGLE_FRAME_SCOPE,
        review_item=review_item,
    )
    if result != 0 or not review_commit_projections_verified(ep, str(manifest.get("review_commit_id") or "")):
        return {"status": "COMMIT_INCOMPLETE", "reason": "ARCHIVE_REPLAY_DID_NOT_VERIFY",
                "apply_result": result}
    return {"status": "PROJECTIONS_APPLIED", "archive_replayed": True}


def reconcile_review_commit(ep: Path, commit_id: str) -> dict:
    """Idempotently finish a decided single-frame commit without model/provider work."""
    ep = Path(ep).resolve()
    manifest = load_review_commit(ep, commit_id)
    if not review_commit_is_decided(manifest):
        return {"status": "COMMIT_NOT_DECIDED", "review_commit_id": commit_id}
    if manifest.get("status") == "PROJECTIONS_APPLIED":
        return {"status": "PROJECTIONS_APPLIED", "review_commit_id": commit_id,
                "replayed": False}

    candidate = ep / CANDIDATE_REL
    request_path = pending_request_path(ep, int(manifest.get("review_attempt") or 0))
    if candidate.is_file() and request_path.is_file():
        if not review_commit_replay_inputs_valid(ep, manifest):
            return {"status": "COMMIT_INCOMPLETE", "review_commit_id": commit_id,
                    "reason": "REPLAY_INPUT_IDENTITY_MISMATCH", "replayed": False}
        # This path parses and validates the already durable critic candidate;
        # it never dispatches a model or image provider.
        result = apply_pending_candidate(ep, attempt=int(manifest["review_attempt"]))
        if result != 0 or not review_commit_projections_verified(ep, commit_id):
            return {"status": "COMMIT_INCOMPLETE", "review_commit_id": commit_id,
                    "reason": "REPLAY_DID_NOT_VERIFY", "replayed": True,
                    "apply_result": result}
        mark_review_commit_projections_applied(ep, commit_id)
        return {"status": "PROJECTIONS_APPLIED", "review_commit_id": commit_id,
                "replayed": True}

    # Candidate cleanup normally happens only after local verification. If it is
    # already gone, first adopt projections that still verify. Otherwise recover
    # only from the immutable archive produced by the same decided commit; this
    # never dispatches a model or image provider.
    if not candidate.exists() and review_commit_projections_verified(ep, commit_id):
        mark_review_commit_projections_applied(ep, commit_id)
        return {"status": "PROJECTIONS_APPLIED", "review_commit_id": commit_id,
                "replayed": False, "adopted_verified_projections": True}
    if not candidate.exists():
        archived = _recover_review_commit_from_archive(ep, manifest)
        if isinstance(archived, dict) and archived.get("status") == "PROJECTIONS_APPLIED":
            mark_review_commit_projections_applied(ep, commit_id)
            return {"status": "PROJECTIONS_APPLIED", "review_commit_id": commit_id,
                    "replayed": False, "archive_replayed": True}
        if isinstance(archived, dict):
            return {"review_commit_id": commit_id, "replayed": False, **archived}
    return {"status": "COMMIT_INCOMPLETE", "review_commit_id": commit_id,
            "reason": "REPLAY_INPUTS_OR_VERIFIED_PROJECTIONS_MISSING", "replayed": False}
def prepare_review_commit(
    ep: Path, *, data: dict, reviewed: list[dict], contexts: dict,
    provenance: dict, attempt: int, review_scope: str,
    review_item: dict | None = None,
) -> dict:
    """Purely validate Final Semantic authority and construct a commit plan.

    This function performs no filesystem, Ledger, queue, or Episode-stage writes.
    """
    version = episode_contract_version(ep)
    directing_v3 = directing_v3_required(ep)
    errors = validate_candidate_gate_rows(data.get("frames"), reviewed, version, directing_v3)
    rows_by_frame = {str(row.get("frame") or "").zfill(2): row
                     for row in (data.get("frames") or []) if isinstance(row, dict)}
    candidate_errors = validate_candidate_rows(
        data.get("frames"), reviewed, version=version, directing_v3=directing_v3)
    errors.extend("candidate validation: " + error for error in candidate_errors)
    global_codes = data.get("issue_codes")
    if not isinstance(global_codes, list):
        errors.append("global issue_codes must be list")
    elif any(code not in ISSUE_CODES for code in global_codes):
        errors.append(f"global issue_codes contain unknown values: {global_codes}")
    elif global_codes:
        errors.append(f"global issue_codes must be empty for PASS: {global_codes}")
    if (data.get("summary") or {}).get("passed") is not True:
        errors.append("critic summary.passed must be true")
    for error in runtime_provenance.validate_critic_provenance(provenance):
        errors.append("critic provenance invalid: " + error)
    if review_scope not in {"FULL_FRAME_SET", PHASE5A_SINGLE_FRAME_SCOPE}:
        errors.append("review scope invalid")
    review_item_id = (str((review_item or {}).get("review_item_id")
                          or (review_item or {}).get("id")
                          or (review_item or {}).get("review_key") or "").strip())
    if review_scope == PHASE5A_SINGLE_FRAME_SCOPE and (
            not isinstance(review_item, dict) or not review_item_id):
        errors.append("Phase5A final semantic review item binding missing")

    if isinstance(review_item, dict):
        frame = reviewed[0] if len(reviewed) == 1 else {}
        phase3 = phase3_context_hashes(ep, str(frame.get("frame") or "")) if frame else {}
        policy_sha = bound_review_policy_sha256(ep)
        expected_fp = review_evidence_fingerprint(
            {**frame, "source_binding": source_binding(ep, str(frame.get("frame") or ""))},
            contexts=contexts, phase3_contexts=phase3,
            policy_sha256=policy_sha, review_item_id=review_item_id,
            attempt_index=int((review_item or {}).get("attempt_index") or 0),
            frame_contract_sha256=phase3.get("frame_contract_sha256"),
            prompt_package_sha256=(review_item or {}).get("prompt_package_sha256"),
        ) if frame else None
        expected = {
            "review_item_id": review_item_id,
            "logical_asset_key": review_item.get("logical_asset_key"),
            "generation_key": review_item.get("generation_key"),
            "production_revision_id": review_item.get("production_revision_id"),
            "attempt_index": review_item.get("attempt_index"),
            "candidate_sha256": review_item.get("artifact_sha256"),
            "frame_contract_sha256": phase3.get("frame_contract_sha256"),
            "prompt_package_sha256": review_item.get("prompt_package_sha256"),
            "model_policy_sha256": policy_sha,
            "evidence_fingerprint": expected_fp,
        }
        receipt = provenance.get("model_execution_receipt")
        errors.extend(validate_final_semantic_execution_receipt(receipt, expected))
        if frame and (frame.get("logical_asset_key") != expected["logical_asset_key"]
                      or frame.get("generation_key") != expected["generation_key"]
                      or frame.get("production_revision_id") != expected["production_revision_id"]
                      or str(frame.get("sha256") or "").lower() != str(expected["candidate_sha256"] or "").lower()):
            errors.append("review item does not bind the candidate generation identity")
        if not expected["prompt_package_sha256"] or not expected["frame_contract_sha256"]:
            errors.append("review item source contract binding missing")
    elif review_scope == PHASE5A_SINGLE_FRAME_SCOPE:
        errors.append("Phase5A model execution receipt missing")
    if len(reviewed) != len(rows_by_frame) and review_scope == PHASE5A_SINGLE_FRAME_SCOPE:
        errors.append("Phase5A candidate contains frames outside the bound review item")
    if errors:
        raise RuntimeError("final semantic authority validation failed: " + "; ".join(errors))
    return {
        "attempt": int(attempt),
        "review_scope": review_scope,
        "review_item_id": review_item_id or None,
        "frames": [str(row.get("frame") or "").zfill(2) for row in reviewed],
        "candidate_sha256": [str(row.get("sha256") or "").lower() for row in reviewed],
        "ledger_actions": "prevalidated",
        **({
            "review_commit_id": review_commit_id(
                review_item_id,
                str((review_item or {}).get("generation_key") or ""),
                int((review_item or {}).get("attempt_index") or 0),
                str((receipt or {}).get("evidence_fingerprint") or ""),
            ),
            "generation_key": review_item.get("generation_key"),
            "logical_asset_key": review_item.get("logical_asset_key"),
            "attempt_index": review_item.get("attempt_index"),
            "frame_contract_sha256": expected.get("frame_contract_sha256"),
            "prompt_package_sha256": expected.get("prompt_package_sha256"),
            "model_policy_sha256": expected.get("model_policy_sha256"),
            "evidence_fingerprint": expected.get("evidence_fingerprint"),
        } if isinstance(review_item, dict) else {}),
    }


def phase4_binding_errors(ep: Path, frames: list[dict]) -> list[str]:
    if not phase4_contract.required(ep):
        return []
    errors: list[str] = []
    for frame in frames:
        # A direct user final decision is a later authority than the historical
        # generated candidate. Preserve that history, but do not reject the
        # accepted publish file for differing from its former candidate SHA.
        accepted = final_acceptance.visual_asset_for_frame(ep, frame["frame"])
        if accepted and accepted.get("sha256", "").lower() == frame["sha256"].lower():
            continue
        errors.extend(phase4_contract.verify_approved_asset_binding(ep, frame["frame"], frame["sha256"]))
    return errors



def _normalized_frame_keys(only_frames: list[int | str] | tuple[int | str, ...] | None) -> set[str] | None:
    if only_frames is None:
        return None
    keys = {f"{int(value):02d}" for value in only_frames}
    if not keys:
        raise ValueError("only_frames must not be empty")
    return keys


def frame_records(ep: Path, *, require_files: bool, only_frames: list[int | str] | tuple[int | str, ...] | None = None) -> list[dict]:
    ledger = production_ledger.load_authority(ep, default={}) or {}
    frames = ledger.get("frames")
    if not isinstance(frames, dict) or not frames:
        raise ValueError("production ledger frames missing")
    selected = _normalized_frame_keys(only_frames)
    rows: list[dict] = []
    for key in sorted(frames):
        if selected is not None and str(key).zfill(2) not in selected:
            continue
        frame = frames[key]
        if not isinstance(frame, dict):
            raise ValueError(f"ledger frame {key} invalid")
        accepted = None
        try:
            accepted = final_acceptance.visual_asset_for_frame(ep, key)
        except (RuntimeError, ValueError):
            if final_acceptance.allows(ep, "frame_semantic"):
                raise
        if accepted and final_acceptance.allows(ep, "frame_semantic"):
            asset = accepted
        else:
            if frame.get("status") not in production_ledger.ACCEPTED_LEDGER_STATES:
                raise ValueError(f"frame {key} not production-passed: {frame.get('status')!r}")
            asset = frame.get("approved_asset")
            if not isinstance(asset, dict):
                raise ValueError(f"frame {key} approved_asset missing")
        raw_path = asset.get("path") or asset.get("asset_path")
        expected_sha = str(asset.get("sha256") or "").lower()
        if len(expected_sha) != 64:
            raise ValueError(f"frame {key} approved asset sha256 invalid")
        path = repo_path(raw_path, f"frame {key} approved_asset.path", require_file=require_files)
        if require_files:
            actual = sha256_file(path)
            if actual.lower() != expected_sha:
                raise ValueError(f"frame {key} approved asset SHA drift: ledger={expected_sha}, actual={actual}")
        rows.append({
            "frame": key.zfill(2),
            "path": path,
            "path_rel": repo_rel(path),
            "sha256": expected_sha,
            **current_generation_binding(ep, key, asset, ledger),
        })
    if selected is not None:
        missing = sorted(selected - {row["frame"] for row in rows})
        if missing:
            raise ValueError(f"requested approved frames missing: {missing}")
    return rows


def reviewable_frame_records(ep: Path, *, require_files: bool, only_frames: list[int | str] | tuple[int | str, ...] | None = None) -> list[dict]:
    """Return the complete production frame set before final promotion.

    Final semantic review is the authority that grants Production PASS.  It
    therefore must be able to inspect the current candidate before
    ``approved_asset`` exists; otherwise approval and review wait on each
    other.  Already-approved rows are reused by SHA.
    """
    ledger = production_ledger.load_authority(ep, default={}) or {}
    frames = ledger.get("frames")
    if not isinstance(frames, dict) or not frames:
        raise ValueError("production ledger frames missing")
    selected = _normalized_frame_keys(only_frames)
    rows: list[dict] = []
    for key in sorted(frames):
        if selected is not None and str(key).zfill(2) not in selected:
            continue
        frame = frames[key]
        if not isinstance(frame, dict):
            raise ValueError(f"ledger frame {key} invalid")
        status = str(frame.get("status") or "")
        approved = frame.get("approved_asset") if isinstance(frame.get("approved_asset"), dict) else None
        candidate = frame.get("current_candidate") if isinstance(frame.get("current_candidate"), dict) else None
        if approved and status in production_ledger.ACCEPTED_LEDGER_STATES:
            asset = approved
            source_kind = "approved"
        elif candidate and status in production_ledger.READY_LEDGER_STATES:
            asset = candidate
            source_kind = "candidate"
        else:
            raise ValueError(f"frame {key} has no reviewable production asset: status={status!r}")
        raw_path = asset.get("path") or asset.get("asset_path")
        expected_sha = str(asset.get("sha256") or "").lower()
        if len(expected_sha) != 64:
            raise ValueError(f"frame {key} reviewable asset sha256 invalid")
        path = repo_path(raw_path, f"frame {key} {source_kind}.path", require_file=require_files)
        if require_files:
            actual = sha256_file(path)
            if actual.lower() != expected_sha:
                raise ValueError(f"frame {key} {source_kind} SHA drift: ledger={expected_sha}, actual={actual}")
        rows.append({
            "frame": key.zfill(2),
            "path": path,
            "path_rel": repo_rel(path),
            "sha256": expected_sha,
            "source_kind": source_kind,
            "ledger_status": status,
            **current_generation_binding(ep, key, asset, ledger),
        })
    if selected is not None:
        missing = sorted(selected - {row["frame"] for row in rows})
        if missing:
            raise ValueError(f"requested reviewable frames missing: {missing}")
    return rows


def reviewable_phase4_binding_errors(ep: Path, frames: list[dict]) -> list[str]:
    """Verify generation-contract binding for approved assets or live candidates."""
    if not phase4_contract.required(ep):
        return []
    ledger = production_ledger.load_authority(ep, default={}) or {}
    errors: list[str] = []
    for row in frames:
        key = row["frame"]
        if row.get("source_kind") == "approved":
            errors.extend(phase4_contract.verify_approved_asset_binding(ep, key, row["sha256"]))
            continue
        frame = ((ledger.get("frames") or {}).get(key) or {})
        candidate = frame.get("current_candidate") or {}
        attempt_id = str(candidate.get("attempt_id") or "")
        attempt = next((x for x in (frame.get("attempts") or []) if str(x.get("attempt_id") or "") == attempt_id), None)
        if not isinstance(attempt, dict):
            errors.append(f"frame {key} candidate generation attempt missing")
            continue
        expected = str(phase4_contract.compile_frame(ep, int(key), write_cache=False).get("contract_sha256") or "").lower()
        requested = str(((attempt.get("request") or {}).get("frame_contract_sha256")) or "").lower()
        # A direct user contract exception is an explicit, frame-scoped
        # compatibility decision for the four legacy pixels.  The canonical
        # Frame Contract helper already verifies that the old SHA, current
        # SHA, and approval sidecar all match; final semantic review must use
        # that same authority instead of applying a stricter second rule.
        if not requested or not phase4_contract.recorded_contract_matches_current(ep, int(key), requested):
            # A direct user-authorized retry-exhaustion fallback may retain a
            # hash-bound older candidate after an explicitly authorized
            # authority refresh. This is a continuity exception only: the
            # ledger records visual_quality_reviewed=false and both hashes.
            acceptances = frame.get("retry_exhaustion_acceptances") or []
            fallback = acceptances[-1] if acceptances else {}
            refresh = frame.get("authority_refresh_authorization") or {}
            if not (
                fallback.get("authority_refresh_fallback") is True
                and str(fallback.get("current_frame_contract_sha256") or "").lower() == expected
                and str(fallback.get("candidate_attempt_frame_contract_sha256") or "").lower() == requested
                and str(refresh.get("frame_contract_sha256") or "").lower() == expected
                and fallback.get("visual_quality_reviewed") is False
            ):
                errors.append(f"frame {key} candidate Frame Contract drift: attempt={requested or 'missing'} current={expected}")
    return errors


def _bits_to_hex(bits: Iterable[bool]) -> str:
    value = 0
    count = 0
    for bit in bits:
        value = (value << 1) | int(bool(bit))
        count += 1
    width = max(1, (count + 3) // 4)
    return f"{value:0{width}x}"


def _flat_pixels(image: Image.Image) -> list[int]:
    getter = getattr(image, "get_flattened_data", None)
    return list(getter() if callable(getter) else image.getdata())


def dhash256(path: Path) -> str:
    with Image.open(path) as im:
        gray = im.convert("L").resize((17, 16), Image.Resampling.LANCZOS)
        px = _flat_pixels(gray)
    bits = []
    for y in range(16):
        row = y * 17
        for x in range(16):
            bits.append(px[row + x] > px[row + x + 1])
    return _bits_to_hex(bits)


def ahash256(path: Path) -> str:
    with Image.open(path) as im:
        gray = im.convert("L").resize((16, 16), Image.Resampling.LANCZOS)
        px = _flat_pixels(gray)
    avg = sum(px) / len(px)
    return _bits_to_hex(v >= avg for v in px)


def hamming_hex(a: str, b: str) -> int:
    return (int(a, 16) ^ int(b, 16)).bit_count()


def perceptual_rows(frames: list[dict]) -> list[dict]:
    out = []
    for row in frames:
        out.append({
            "frame": row["frame"],
            "asset_sha256": row["sha256"],
            "dhash256": dhash256(row["path"]),
            "ahash256": ahash256(row["path"]),
        })
    return out


def duplicate_pairs(phashes: list[dict]) -> list[dict]:
    by_frame = {row["frame"]: row for row in phashes}
    keys = sorted(by_frame)
    pairs: list[dict] = []
    for idx, key in enumerate(keys):
        left = by_frame[key]
        # Adjacent near-duplicates are a hard production failure.
        if idx + 1 < len(keys):
            right = by_frame[keys[idx + 1]]
            d = hamming_hex(left["dhash256"], right["dhash256"])
            a = hamming_hex(left["ahash256"], right["ahash256"])
            if d <= 8 and a <= 12:
                pairs.append({"frames": [key, right["frame"]], "dhash_distance": d, "ahash_distance": a, "kind": "adjacent_near_duplicate"})
        # Non-adjacent exact/virtually exact duplicates are also forbidden.
        for other_key in keys[idx + 2:]:
            right = by_frame[other_key]
            d = hamming_hex(left["dhash256"], right["dhash256"])
            a = hamming_hex(left["ahash256"], right["ahash256"])
            if d <= 2 and a <= 3:
                pairs.append({"frames": [key, other_key], "dhash_distance": d, "ahash_distance": a, "kind": "nonadjacent_near_duplicate"})
    return pairs


def validate_candidate_rows(rows: object, expected_frames: list[dict], version: str = "2.0.3.6", directing_v3: bool = False, forced_frames: set[str] | None = None) -> list[str]:
    errors: list[str] = []
    expected = {row["frame"] for row in expected_frames}
    if not isinstance(rows, list) or len(rows) != len(expected_frames):
        return [f"critic must return exactly {len(expected_frames)} frame rows"]
    seen: set[str] = set()
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            errors.append(f"frames[{idx}] must be object")
            continue
        key = str(row.get("frame") or "").zfill(2)
        if key not in expected:
            errors.append(f"unexpected frame row: {key}")
            continue
        if key in seen:
            errors.append(f"duplicate frame row: {key}")
        seen.add(key)
        if key in (forced_frames or set()):
            continue
        checks = row.get("checks") or {}
        for check in checks_for_version(version, directing_v3):
            if checks.get(check) is not True:
                errors.append(f"frame {key} checks.{check} must be true")
        codes = row.get("issue_codes")
        if not isinstance(codes, list):
            errors.append(f"frame {key} issue_codes must be list")
        elif codes:
            unknown = [x for x in codes if x not in ISSUE_CODES]
            if unknown:
                errors.append(f"frame {key} unknown issue_codes: {unknown}")
            errors.append(f"frame {key} issue_codes must be empty for PASS: {codes}")
        if row.get("decision") != "pass":
            errors.append(f"frame {key} decision must be pass")
    if seen != expected:
        errors.append(f"critic frame set mismatch: expected={sorted(expected)}, actual={sorted(seen)}")
    return errors


def validate_candidate_gate_rows(rows: object, expected_frames: list[dict], version: str, directing_v3: bool) -> list[str]:
    """Validate a final critic result before it is allowed to mutate the ledger.

    Unlike ``validate_candidate_rows`` this accepts both pass and fail rows so
    failed candidates can enter the existing repair flow.  Schema/provenance
    errors never change Production Ledger state.
    """
    errors: list[str] = []
    expected = {row["frame"] for row in expected_frames}
    if not isinstance(rows, list) or len(rows) != len(expected_frames):
        return [f"critic must return exactly {len(expected_frames)} frame rows"]
    seen: set[str] = set()
    required_checks = checks_for_version(version, directing_v3)
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            errors.append(f"frames[{idx}] must be object")
            continue
        key = str(row.get("frame") or "").zfill(2)
        if key not in expected:
            errors.append(f"unexpected frame row: {key}")
            continue
        if key in seen:
            errors.append(f"duplicate frame row: {key}")
        seen.add(key)
        checks = row.get("checks")
        if not isinstance(checks, dict):
            errors.append(f"frame {key} checks must be object")
            continue
        missing = [name for name in required_checks if not isinstance(checks.get(name), bool)]
        if missing:
            errors.append(f"frame {key} checks missing/non-bool: {missing}")
        codes = row.get("issue_codes")
        if not isinstance(codes, list):
            errors.append(f"frame {key} issue_codes must be list")
            codes = []
        unknown = [x for x in codes if x not in ISSUE_CODES]
        if unknown:
            errors.append(f"frame {key} unknown issue_codes: {unknown}")
        decision = str(row.get("decision") or "")
        if decision not in {"pass", "fail"}:
            errors.append(f"frame {key} decision must be pass or fail")
        elif decision == "pass" and (codes or any(checks.get(name) is not True for name in required_checks)):
            errors.append(f"frame {key} pass requires all checks true and no issue_codes")
        elif decision == "fail" and not codes and all(checks.get(name) is True for name in required_checks):
            errors.append(f"frame {key} fail requires a visible failed check or issue_code")
    if seen != expected:
        errors.append(f"critic frame set mismatch: expected={sorted(expected)}, actual={sorted(seen)}")
    return errors


def pending_request_path(ep: Path, attempt: int) -> Path:
    return ep / "meta" / f"{PENDING_REQUEST_PREFIX}{attempt}.json"


def _pending_request_payload(ep: Path, frames: list[dict], attempt: int,
                             review_scope: str = "FULL_FRAME_SET",
                             review_item: dict | None = None) -> dict:
    return {
        "schema_version": 1,
        "attempt": attempt,
        "review_scope": review_scope,
        "review_item": dict(review_item) if isinstance(review_item, dict) else None,
        "recorded_at": now(),
        "contexts": context_hashes(ep),
        "assets": [
            {"frame": row["frame"], "path": row["path_rel"], "sha256": row["sha256"]}
            for row in frames
        ],
    }


def _ledger_frame(ep: Path, frame: str) -> dict:
    return (((production_ledger.load_authority(ep, default={}) or {}).get("frames") or {}).get(str(frame).zfill(2)) or {})


def _forced_marker(ep: Path, frame: str, sha: str) -> dict | None:
    row = _ledger_frame(ep, frame)
    for marker in reversed(row.get("forced_passes") or []):
        if (marker.get("forced_pass") is True
                and str(marker.get("candidate_sha256") or "").lower() == sha.lower()
                and int(marker.get("content_repairs_used") or 0) >= int(marker.get("content_repair_limit") or 0)):
            return marker
    return None


def _apply_candidate_gate(
    ep: Path,
    *,
    data: dict,
    reviewed: list[dict],
    contexts: dict,
    provenance: dict,
    attempt: int,
    review_scope: str = "FULL_FRAME_SET",
    review_item: dict | None = None,
) -> int:
    """Let the final semantic critic close candidate -> PASS -> approved -> lock."""
    version = episode_contract_version(ep)
    directing_v3 = directing_v3_required(ep)
    errors = validate_candidate_gate_rows(data.get("frames"), reviewed, version, directing_v3)
    global_codes = data.get("issue_codes")
    if not isinstance(global_codes, list):
        errors.append("global issue_codes must be list")
    elif any(code not in ISSUE_CODES for code in global_codes):
        errors.append(f"global issue_codes contain unknown values: {global_codes}")
    if errors:
        print("FRAME SEMANTIC CANDIDATE GATE INVALID")
        for error in errors:
            print("FAIL:", error)
        return 3

    # Final Semantic authority, source bindings, receipt and evidence identity
    # must all validate before the first Ledger/projection mutation.
    commit_plan = prepare_review_commit(
        ep, data=data, reviewed=reviewed, contexts=contexts,
        provenance=provenance, attempt=attempt, review_scope=review_scope,
        review_item=review_item,
    )

    rows = {str(row.get("frame") or "").zfill(2): row for row in data.get("frames") or []}

    # Preflight every Ledger transition before writing any PASS/LOCK state.  Final
    # semantic review is a set-level decision: a predictable policy failure on a
    # later frame (for example an already-LOCKED frame whose ordinary repair
    # budget is exhausted) must not happen after earlier PASS frames were already
    # promoted and locked.  We still keep per-frame durable writes, but all known
    # state/policy incompatibilities are resolved into an explicit plan first and
    # failures are applied before passes.
    ledger_data = production_ledger.load_authority(ep, default={}) or {}
    ledger_frames = ledger_data.get("frames") or {}
    repair_limit = production_ledger.content_repair_limit(ledger_data)
    plan: list[tuple[str, dict, dict, str]] = []
    preflight_errors: list[str] = []
    for source in reviewed:
        key = source["frame"]
        review = rows[key]
        frame = ledger_frames.get(key) or {}
        status = str(frame.get("status") or "")
        decision = str(review.get("decision") or "")
        if decision == "pass":
            if status not in {"ORIGINAL_READY", "REPAIR_READY", "PASSED", "LOCKED"}:
                preflight_errors.append(f"frame {key} cannot close PASS from status={status}")
            else:
                plan.append(("pass", source, review, status))
            continue
        # A Final Semantic FAIL is authoritative review evidence, not the
        # ordinary image-content critic's retry-exhaustion acceptance policy.
        # Never force-pass a candidate that this review has just rejected.
        if status in {"LOCKED", "PASSED"}:
            plan.append(("escalate_needs_user", source, review, status))
        elif status == "NEEDS_USER":
            plan.append(("retain_needs_user", source, review, status))
        elif status in {"ORIGINAL_READY", "REPAIR_READY"}:
            plan.append(("review_failure", source, review, status))
        else:
            preflight_errors.append(f"frame {key} cannot close FAIL from status={status}")
    if preflight_errors:
        raise RuntimeError("final semantic Ledger preflight failed: " + "; ".join(preflight_errors))

    # Validate all remaining source/generation bindings before any PASS/LOCK
    # write. The Ledger attempt already contains the canonical request contract;
    # validate that recorded contract directly instead of waiting for the
    # approved projection to exist.
    frozen_sources = review_source_bindings(ep, reviewed)
    if provenance.get("review_source_bindings") != frozen_sources:
        raise RuntimeError("final semantic source bindings changed before commit")
    for source in reviewed:
        key = source["frame"]
        if phase4_contract.required(ep):
            ledger_row = ledger_frames.get(key) or {}
            matching_attempt = next((entry for entry in reversed(ledger_row.get("attempts") or [])
                                    if str(((entry.get("candidate") or {}).get("sha256") or "")).lower()
                                    == str(source.get("sha256") or "").lower()), None)
            if not isinstance(matching_attempt, dict):
                raise RuntimeError(f"frame {key} has no generation attempt bound to candidate SHA")
            phase4_errors = phase4_contract.verify_recorded_provenance(
                ep, key, (matching_attempt.get("request") or {}).get("frame_contract"))
            if phase4_errors:
                raise RuntimeError("approved Frame Contract preflight failed: " + "; ".join(phase4_errors))

    # These checks used to run after cmd_review/cmd_promote/cmd_lock.  They are
    # deterministic checks over the exact candidate bytes and recorded source
    # contract, so run them while this is still a read-only validation phase.
    # A failed contract must never leave an approved file or LOCKED Ledger row.
    for source in reviewed:
        path = Path(source["path"])
        if not path.is_file() or sha256_file(path).lower() != str(source.get("sha256") or "").lower():
            raise RuntimeError(f"frame {source['frame']} candidate changed before Review commit")

    review_commit = None
    if isinstance(review_item, dict):
        receipt = provenance.get("model_execution_receipt")
        review_commit = _write_review_commit_decision(ep, commit_plan, receipt)
        provenance = dict(provenance)
        provenance["review_commit_id"] = review_commit
        # The Final Semantic Model Execution Receipt is part of this commit,
        # not something promoted to SUCCESS before the authority checks above.
        _commit_final_semantic_execution_receipt(
            ep,
            receipt_ref=provenance.get("model_execution_receipt_ref"),
            validated_receipt=provenance.get("model_execution_receipt"),
        )

    failures: list[str] = []
    forced_frames: list[str] = []
    # Failure transitions first: if an unexpected write-time problem still occurs,
    # no newly passing frame has been promoted/locked by this invocation yet.
    for operation, source, review, _status in [x for x in plan if x[0] != "pass"]:
        key = source["frame"]
        notes = "Final semantic critic candidate review: " + str(review.get("notes") or review.get("issue_codes") or "")
        failures.append(key)
        if operation == "escalate_needs_user":
            production_ledger.mark_review_needs_user(ep, key, reason=notes[:500])
            continue
        if operation == "retain_needs_user":
            continue
        if operation == "authorize_locked_repair":
            production_ledger.cmd_authorize_repair(SimpleNamespace(
                episode_dir=str(ep), frame=key,
                note=notes[:500], delegated_auto=True))
            continue
        production_ledger.cmd_review(SimpleNamespace(
            episode_dir=str(ep), frame=key, decision="repair", notes=notes[:500],
            prevent_exhaustion_force_pass=True))
        status = str(_ledger_frame(ep, key).get("status") or "")
        if status == "CONTENT_FAILED":
            production_ledger.cmd_authorize_repair(SimpleNamespace(
                episode_dir=str(ep), frame=key,
                note=notes[:500], delegated_auto=True))

    for operation, source, review, _status in [x for x in plan if x[0] == "pass"]:
        key = source["frame"]
        status = str(_ledger_frame(ep, key).get("status") or "")
        notes = "Final semantic critic candidate review: " + str(review.get("notes") or review.get("issue_codes") or "")
        if status in {"ORIGINAL_READY", "REPAIR_READY"}:
            production_ledger.cmd_review(SimpleNamespace(
                episode_dir=str(ep), frame=key, decision="pass", notes=notes[:500]))
            status = str(_ledger_frame(ep, key).get("status") or "")
        if status == "PASSED":
            production_ledger.cmd_promote(SimpleNamespace(episode_dir=str(ep), frame=key))
            production_ledger.cmd_lock(SimpleNamespace(
                episode_dir=str(ep), frame=key,
                reason=f"final semantic critic attempt {attempt} PASS"))
        elif status != "LOCKED":
            raise RuntimeError(f"frame {key} cannot close PASS from status={status}")

    evidence = {
        "schema_version": 1,
        "attempt": attempt,
        "review_scope": (PHASE5A_SINGLE_FRAME_SCOPE if review_scope == PHASE5A_SINGLE_FRAME_SCOPE else "CANDIDATE_FULL_FRAME_SET"),
        "critic_provenance": provenance,
        "reviewed_assets": [{"frame": x["frame"], "path": x["path_rel"], "sha256": x["sha256"]} for x in reviewed],
        "critic_result": data,
        "failed_frames": failures,
        "forced_pass_frames": forced_frames,
        "recorded_at": now(),
    }
    evidence["review_commit_plan"] = commit_plan
    write_json(ep / "meta" / f"frame-semantic-candidate-attempt-{attempt}.json", evidence)
    if failures:
        print("FRAME SEMANTIC REVIEW FAIL: repair required frames=" + ",".join(failures))
        return 2

    reviewed_keys = [row["frame"] for row in reviewed]
    approved = frame_records(
        ep, require_files=True,
        only_frames=reviewed_keys if review_scope == PHASE5A_SINGLE_FRAME_SCOPE else None,
    )
    before_sha = {row["frame"]: row["sha256"] for row in reviewed}
    after_sha = {row["frame"]: row["sha256"] for row in approved}
    if before_sha != after_sha:
        # cmd_promote writes only a projection of the already prevalidated
        # candidate.  If storage corrupts it, classify the projection as
        # unverified; do not turn that late IO anomaly into a Review PASS.
        print("FRAME SEMANTIC REVIEW PROJECTION UNVERIFIED: approved pixels differ from candidate")
        return 2
    approved_sources = review_source_bindings(ep, approved)
    provenance = dict(provenance)
    provenance["review_scope"] = (
        PHASE5A_SINGLE_FRAME_SCOPE
        if review_scope == PHASE5A_SINGLE_FRAME_SCOPE else "FULL_FRAME_SET"
    )
    provenance["reviewed_candidate_assets"] = evidence["reviewed_assets"]
    result = _persist_candidate(
        ep,
        data=data,
        current=approved,
        contexts=contexts,
        phashes=perceptual_rows(approved),
        provenance=provenance,
        frozen_sources=approved_sources,
        verification_scope=review_scope,
        review_item=review_item,
    )
    if review_commit and result == 0:
        mark_review_commit_projections_applied(ep, review_commit)
    return result


def _pending_assets_match_exact_promotion(
    expected_assets: list[dict], actual_assets: list[dict], ledger: dict,
) -> bool:
    """Allow candidate->approved path drift only for the exact same pixels.

    This is recovery for a partially committed review: the pending request still
    names the candidate path while the ledger has already promoted those bytes.
    Frame, SHA, candidate path, approved path and source_sha256 must all bind.
    """
    if len(expected_assets) != len(actual_assets):
        return False
    actual_by_frame = {
        str(row.get("frame") or "").zfill(2): row
        for row in actual_assets if isinstance(row, dict)
    }
    frames = ledger.get("frames") if isinstance(ledger, dict) else None
    if not isinstance(frames, dict):
        return False
    for expected in expected_assets:
        if not isinstance(expected, dict):
            return False
        key = str(expected.get("frame") or "").zfill(2)
        actual = actual_by_frame.get(key)
        row = frames.get(key)
        if not isinstance(actual, dict) or not isinstance(row, dict):
            return False
        sha = str(expected.get("sha256") or "").lower()
        if len(sha) != 64 or str(actual.get("sha256") or "").lower() != sha:
            return False
        if str(row.get("status") or "") not in production_ledger.ACCEPTED_LEDGER_STATES:
            return False
        candidate = row.get("current_candidate")
        approved = row.get("approved_asset")
        if not isinstance(candidate, dict) or not isinstance(approved, dict):
            return False
        normalize = lambda value: str(value or "").replace("\\", "/")
        if normalize(expected.get("path")) != normalize(candidate.get("path") or candidate.get("asset_path")):
            return False
        if normalize(actual.get("path")) != normalize(approved.get("path") or approved.get("asset_path")):
            return False
        if str(candidate.get("sha256") or "").lower() != sha:
            return False
        if str(approved.get("sha256") or "").lower() != sha:
            return False
        if str(approved.get("source_sha256") or "").lower() != sha:
            return False
    return True


def apply_pending_candidate(ep: Path, *, attempt: int) -> int:
    """Resume a critic whose parent process vanished after the model wrote JSON."""
    request_path = pending_request_path(ep, attempt)
    candidate = ep / CANDIDATE_REL
    log = ep / "meta" / f"frame-semantic-critic-attempt-{attempt}.jsonl"
    if not request_path.is_file():
        raise RuntimeError(f"pending semantic request missing: {request_path}")
    if not candidate.is_file():
        raise RuntimeError(f"semantic candidate missing: {candidate}")
    pending = read_json(request_path)
    expected_assets = pending.get("assets")
    if not isinstance(expected_assets, list) or not expected_assets:
        raise RuntimeError("pending semantic request asset set missing")
    target_frames = [row.get("frame") for row in expected_assets
                     if isinstance(row, dict) and row.get("frame") is not None]
    if len(target_frames) != len(expected_assets):
        raise RuntimeError("pending semantic request asset set invalid")
    review_scope = str(pending.get("review_scope") or "")
    if not review_scope:
        # Older pending requests predate persisted scope. Recover a one-frame
        # subset only inside the explicit, non-promotable Phase 5A workspace.
        try:
            marker = read_json(ep / "meta" / "phase5a-canary.json")
        except Exception:
            marker = None
        if (isinstance(marker, dict)
                and marker.get("workspace_class") == "TEST_ONLY"
                and marker.get("promotion_class") == "NON_PROMOTABLE"
                and marker.get("canary_type") == "PHASE5A_COLLABORATIVE_REGRESSION"
                and len(expected_assets) == 1):
            review_scope = PHASE5A_SINGLE_FRAME_SCOPE
        else:
            review_scope = "FULL_FRAME_SET"
    if review_scope not in {"FULL_FRAME_SET", PHASE5A_SINGLE_FRAME_SCOPE}:
        raise RuntimeError("pending semantic request review scope invalid")
    current = reviewable_frame_records(
        ep, require_files=True,
        only_frames=target_frames if review_scope == PHASE5A_SINGLE_FRAME_SCOPE else None)
    actual_assets = [{"frame": x["frame"], "path": x["path_rel"], "sha256": x["sha256"]} for x in current]
    if expected_assets != actual_assets:
        ledger = production_ledger.load_authority(ep, default={}) or {}
        if not _pending_assets_match_exact_promotion(expected_assets, actual_assets, ledger):
            raise RuntimeError("pending semantic request asset set drifted; refuse orphan recovery")
    if pending.get("contexts") != context_hashes(ep):
        raise RuntimeError("pending semantic request Story/Storyboard/visual context drifted")
    binding_errors = reviewable_phase4_binding_errors(ep, current)
    if binding_errors:
        raise RuntimeError("pending semantic request Frame Contract drifted: " + "; ".join(binding_errors))
    data = read_json(candidate)
    review_item = pending.get("review_item") if isinstance(pending.get("review_item"), dict) else None
    sharded_path = ep / "meta" / f"frame-semantic-sharded-attempt-{attempt}.json"
    if sharded_path.is_file():
        sharded = read_json(sharded_path)
        expected_coverage = [row["frame"] for row in current]
        if int(sharded.get("attempt") or 0) != attempt:
            raise RuntimeError("sharded semantic recovery attempt mismatch")
        if sharded.get("target_coverage") != expected_coverage:
            raise RuntimeError("sharded semantic recovery target coverage mismatch")
        if str(sharded.get("candidate_sha256") or "").lower() != sha256_file(candidate).lower():
            raise RuntimeError("sharded semantic recovery merged candidate SHA mismatch")
        if str(sharded.get("source_bindings_sha256") or "").lower() != sha256_json(review_source_bindings(ep, current)).lower():
            raise RuntimeError("sharded semantic recovery source binding drift")
        shards = sharded.get("shards") or []
        if int(sharded.get("shard_count") or 0) != len(shards) or len(shards) < 2:
            raise RuntimeError("sharded semantic recovery evidence incomplete")
        shard_logs = [str(row.get("log_path") or "") for row in shards if isinstance(row, dict)]
        if len(shard_logs) != len(shards) or any(not value for value in shard_logs):
            raise RuntimeError("sharded semantic recovery log bindings incomplete")
        for raw in shard_logs:
            path = repo_path(raw, "sharded semantic recovery log")
            if not path.is_file():
                raise RuntimeError(f"sharded semantic recovery log missing: {raw}")
        closure = sharded.get("global_closure") or {}
        closure_status = str(closure.get("status") or "")
        if int(sharded.get("schema_version") or 1) >= 2:
            if closure_status not in {"COMPLETED", "SKIPPED_LOCAL_FAILURE"}:
                raise RuntimeError("sharded semantic recovery global closure status invalid")
            if closure_status == "COMPLETED":
                closure_log_raw = str(closure.get("log_path") or "")
                closure_candidate_raw = str(closure.get("candidate_path") or "")
                if not closure_log_raw or not closure_candidate_raw:
                    raise RuntimeError("sharded semantic recovery global closure bindings incomplete")
                closure_log = repo_path(closure_log_raw, "sharded semantic recovery global closure log")
                closure_candidate = repo_path(
                    closure_candidate_raw, "sharded semantic recovery global closure candidate")
                if str(closure.get("candidate_sha256") or "").lower() != sha256_file(closure_candidate).lower():
                    raise RuntimeError("sharded semantic recovery global closure candidate SHA mismatch")
        provenance = runtime_provenance.build_vision_critic_provenance(
            attempt=attempt, log=shard_logs[0], review_scope="FULL_FRAME_SET")
        provenance.update({
            "sharded_review": True,
            "shard_count": len(shards),
            "max_review_inflight": int(sharded.get("max_review_inflight") or 0),
            "shard_logs": shard_logs,
            "sharded_evidence": repo_rel(sharded_path),
            "global_closure_status": closure_status or None,
            "global_closure_passed": closure.get("passed"),
            "global_closure_log": closure.get("log_path"),
        })
    else:
        if not log.is_file():
            raise RuntimeError(f"semantic critic log missing: {log}")
        log_rel = log.relative_to(ROOT).as_posix() if log.stat().st_size > 0 else None
        provenance = runtime_provenance.build_vision_critic_provenance(
            attempt=attempt, log=log_rel, review_scope=review_scope)
        if log.stat().st_size <= 0:
            provenance["critic_stdout_log_empty_after_parent_timeout"] = True
    provenance["anatomy_integrity_enforced"] = True
    provenance["recovered_after_parent_timeout"] = True
    provenance["candidate_sha256"] = sha256_file(candidate)
    if isinstance(review_item, dict):
        if len(current) != 1:
            raise RuntimeError("FINAL_SEMANTIC_PENDING_FRAME_SCOPE_INVALID")
        provisional, receipt_path = _find_pending_final_semantic_receipt(
            ep, review_item=review_item, frame=current[0], attempt=attempt)
        request_id = str(provisional.get("runner_request_id") or "")
        if not request_id:
            raise RuntimeError("FINAL_SEMANTIC_DURABLE_EXECUTION_BINDING_MISSING")
        receipt = _finalize_final_semantic_receipt(
            ep,
            receipt_ref=repo_rel(receipt_path),
            review_item=review_item,
            frame=current[0],
            candidate=candidate,
            log_path=log,
            returncode=int(provisional.get("returncode", -1)),
            remote={"request_id": request_id, "thread_id": provisional.get("thread_id")},
            contexts=context_hashes(ep),
        )
        provenance.update({
            "review_scope": review_scope,
            "review_item_id": str(review_item.get("review_key") or review_item.get("id") or ""),
            "review_source_bindings": review_source_bindings(ep, current),
            "prompt_package_sha256": review_item.get("prompt_package_sha256"),
            "model_execution_receipt": receipt,
            "model_execution_receipt_ref": repo_rel(receipt_path),
        })
    return _apply_candidate_gate(
        ep,
        data=data,
        reviewed=current,
        contexts=context_hashes(ep),
        provenance=provenance,
        attempt=attempt,
        review_scope=review_scope,
        review_item=review_item,
    )


def recover_completed_shards_after_parent_timeout(ep: Path, *, attempt: int) -> int | None:
    """Recover completed local-failure shards without re-running Vision.

    The previous parent may have timed out after every shard wrote a valid
    candidate but before the merged candidate/evidence was committed. Recovery
    is allowed only when the pending request still binds the exact current
    assets and Story/Storyboard/visual contexts. All-local-PASS still requires
    the global closure critic and therefore is not synthesized here.
    """
    ep = Path(ep).resolve()
    request_path = pending_request_path(ep, attempt)
    if not request_path.is_file():
        return None

    current = reviewable_frame_records(ep, require_files=True)
    pending = read_json(request_path)
    expected_assets = pending.get("assets")
    actual_assets = [
        {"frame": row["frame"], "path": row["path_rel"], "sha256": row["sha256"]}
        for row in current
    ]
    if expected_assets != actual_assets or pending.get("contexts") != context_hashes(ep):
        return None
    binding_errors = reviewable_phase4_binding_errors(ep, current)
    if binding_errors:
        return None

    shards = _full_review_shards(current)
    if len(shards) < 2:
        return None

    version = episode_contract_version(ep)
    directing_v3 = directing_v3_required(ep)
    results = []
    for shard in shards:
        index = int(shard["index"])
        candidate = ep / "meta" / f".frame-semantic-shard-{attempt}-{index}.candidate.json"
        log = ep / "meta" / f"frame-semantic-critic-attempt-{attempt}-shard-{index}.jsonl"
        if not candidate.is_file() or not log.is_file():
            return None
        data = read_json(candidate)
        errors = validate_candidate_gate_rows(
            data.get("frames"), shard["selected"], version, directing_v3)
        global_codes = data.get("issue_codes")
        if not isinstance(global_codes, list):
            errors.append("global issue_codes must be list")
        else:
            unknown = [code for code in global_codes if code not in ISSUE_CODES]
            if unknown:
                errors.append(f"global issue_codes contain unknown values: {unknown}")
        decisions = [
            str(row.get("decision") or "")
            for row in (data.get("frames") or [])
            if isinstance(row, dict)
        ]
        expected_summary = bool(decisions) and all(value == "pass" for value in decisions)
        if (data.get("summary") or {}).get("passed") is not expected_summary:
            errors.append("critic summary.passed does not match shard frame decisions")
        if errors:
            return None
        results.append({
            "index": index,
            "target_frames": list(shard["target_frames"]),
            "context_frames": list(shard["context_frames"]),
            "selected_frames": [row["frame"] for row in shard["selected"]],
            "candidate_path": repo_rel(candidate),
            "candidate_sha256": sha256_file(candidate),
            "log_path": repo_rel(log),
            "data": data,
        })

    merged = _merge_full_review_shards(results, current)
    if bool((merged.get("summary") or {}).get("passed")):
        # A local PASS still needs the global closure critic. Never fabricate it.
        return None
    merge_errors = validate_candidate_gate_rows(
        merged.get("frames"), current, version, directing_v3)
    if merge_errors:
        return None

    candidate = ep / CANDIDATE_REL
    write_json(candidate, merged)
    frozen_sources = review_source_bindings(ep, current)
    evidence_path = ep / "meta" / f"frame-semantic-sharded-attempt-{attempt}.json"
    write_json(evidence_path, {
        "schema_version": 2,
        "attempt": attempt,
        "review_scope": "SHARDED_FULL_FRAME_SET",
        "recorded_at": now(),
        "shard_count": len(results),
        # Parent timeout means the exact observed peak is unavailable here.
        "max_review_inflight": 0,
        "target_coverage": [row["frame"] for row in current],
        "candidate_path": repo_rel(candidate),
        "candidate_sha256": sha256_file(candidate),
        "source_bindings_sha256": sha256_json(frozen_sources),
        "recovered_after_parent_timeout": True,
        "global_closure": {
            "status": "SKIPPED_LOCAL_FAILURE",
            "anchor_frames": [],
            "reason": "one or more local shard observations already failed",
        },
        "shards": [{
            "index": result["index"],
            "target_frames": result["target_frames"],
            "context_frames": result["context_frames"],
            "selected_frames": result["selected_frames"],
            "candidate_path": result["candidate_path"],
            "candidate_sha256": result["candidate_sha256"],
            "log_path": result["log_path"],
        } for result in results],
    })
    return apply_pending_candidate(ep, attempt=attempt)


def validate_bound_review(data: dict, *, frame: dict, contexts: dict, version: str, metadata_only: bool, phase3_contexts: dict | None = None, directing_v3: bool = False, ep: Path | None = None) -> list[str]:
    errors: list[str] = []
    key = frame["frame"]
    provenance = data.get("critic_provenance") or {}
    forced = _forced_marker(ep, key, frame["sha256"]) if ep is not None and data.get("forced_pass") is True else None
    if data.get("forced_pass") is True and forced is None:
        errors.append(f"frame {key} forced PASS has no matching ledger evidence")
    if data.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"frame {key} schema_version must be {SCHEMA_VERSION}")
    if data.get("story_os_version") != version:
        errors.append(f"frame {key} story_os_version mismatch")
    if str(data.get("frame") or "").zfill(2) != key:
        errors.append(f"frame review number mismatch for {key}")
    if str(data.get("asset_sha256") or "").lower() != frame["sha256"].lower():
        errors.append(f"frame {key} asset_sha256 does not bind current approved asset")
    if ep is not None and phase4_contract.required(ep):
        expected_logical_key = str(frame.get("logical_asset_key") or "")
        expected_generation_key = str(frame.get("generation_key") or "")
        if not expected_logical_key or str(data.get("logical_asset_key") or "") != expected_logical_key:
            errors.append(f"frame {key} logical_asset_key does not bind the current logical asset")
        if not expected_generation_key or str(data.get("generation_key") or "") != expected_generation_key:
            errors.append(f"frame {key} generation_key does not bind the current candidate")
        expected_policy_sha = bound_review_policy_sha256(ep)
        recorded_policy_sha = str(data.get("model_policy_sha256") or "").lower()
        if not expected_policy_sha or recorded_policy_sha != expected_policy_sha:
            errors.append(f"frame {key} model_policy_sha256 does not bind the Episode-frozen policy")
        expected_identity = {
            "logical_asset_key": expected_logical_key,
            "generation_key": expected_generation_key,
            "sha256": frame["sha256"],
            "source_binding": source_binding(ep, key),
        }
        phase3 = phase3_contexts or phase3_context_hashes(ep, key)
        if provenance.get("review_scope") == PHASE5A_SINGLE_FRAME_SCOPE:
            review_item_id = str(data.get("review_item_id") or "")
            review_attempt_index = int(data.get("attempt_index") or 0)
            prompt_sha = str(provenance.get("prompt_package_sha256") or "")
            expected_fingerprint = review_evidence_fingerprint(
                expected_identity, contexts=contexts, phase3_contexts=phase3,
                policy_sha256=expected_policy_sha, review_item_id=review_item_id,
                attempt_index=review_attempt_index,
                frame_contract_sha256=phase3.get("frame_contract_sha256"),
                prompt_package_sha256=prompt_sha,
            )
            receipt = provenance.get("model_execution_receipt")
            receipt_expected = {
                "review_item_id": review_item_id,
                "logical_asset_key": expected_logical_key,
                "generation_key": expected_generation_key,
                "attempt_index": review_attempt_index,
                "candidate_sha256": frame["sha256"],
                "frame_contract_sha256": phase3.get("frame_contract_sha256"),
                "prompt_package_sha256": prompt_sha,
                "model_policy_sha256": expected_policy_sha,
                "evidence_fingerprint": expected_fingerprint,
            }
            errors.extend(validate_final_semantic_execution_receipt(receipt, receipt_expected))
        else:
            expected_fingerprint = frame_evidence_fingerprint(
                expected_identity, contexts=contexts,
                phase3_contexts=phase3,
                policy_sha256=expected_policy_sha,
            )
        if not expected_fingerprint or str(data.get("evidence_fingerprint") or "").lower() != expected_fingerprint:
            errors.append(f"frame {key} evidence_fingerprint does not bind current evidence identity")
    if str(data.get("asset_path") or "") != frame["path_rel"]:
        errors.append(f"frame {key} asset_path mismatch")
    for field, expected in contexts.items():
        if str(data.get(field) or "").lower() != str(expected).lower():
            errors.append(f"frame {key} {field} mismatch")
    for field, expected in (phase3_contexts or {}).items():
        if str(data.get(field) or "").lower() != str(expected).lower():
            errors.append(f"frame {key} {field} mismatch")
    expected_binding = source_binding(ep, frame["frame"]) if ep is not None else None
    if expected_binding and data.get("source_binding") != expected_binding:
        errors.append(f"frame {key} source_binding mismatch")
    for error in runtime_provenance.validate_critic_provenance(provenance):
        errors.append(f"frame {key} {error}")
    if provenance.get("review_scope") not in {"FULL_FRAME_SET", "INCREMENTAL_CONTEXT_SET", PHASE5A_SINGLE_FRAME_SCOPE}:
        errors.append(f"frame {key} critic review_scope is not an allowed production/scoped scope")
    attempt = provenance.get("attempt")
    if attempt not in {1, 2} and not (attempt == 3 and provenance.get("direct_user_exception_review") is True):
        errors.append(f"frame {key} critic attempt must be 1/2, or 3 for a direct-user-exception re-review")
    checks = data.get("checks") or {}
    anatomy_required = provenance.get("anatomy_integrity_enforced") is True
    for check in checks_for_version(version, directing_v3, anatomy_required=anatomy_required):
        if forced is None and checks.get(check) is not True:
            errors.append(f"frame {key} checks.{check} must be true")
    codes = data.get("issue_codes")
    if not isinstance(codes, list):
        errors.append(f"frame {key} issue_codes must be list")
    elif codes and forced is None:
        errors.append(f"frame {key} issue_codes not empty: {codes}")
    if data.get("decision") != "pass" and forced is None:
        errors.append(f"frame {key} decision must be pass")
    if not metadata_only:
        path = frame["path"]
        if not path.is_file():
            errors.append(f"frame {key} approved asset missing")
        else:
            actual = sha256_file(path)
            if actual.lower() != frame["sha256"].lower():
                errors.append(f"frame {key} actual asset SHA drift")
    return errors


def verify_episode(ep: Path, *, metadata_only: bool = False, write_audit: bool = False) -> list[str]:
    if not review_required(ep):
        return []
    errors: list[str] = []
    try:
        frames = frame_records(ep, require_files=not metadata_only)
        contexts = context_hashes(ep)
        errors.extend(phase4_binding_errors(ep, frames))
    except Exception as exc:
        return [str(exc)]

    summary_path = ep / SUMMARY_REL
    if not summary_path.is_file():
        errors.append("meta/frame-semantic-review.json missing")
        summary = None
    else:
        try:
            summary = read_json(summary_path)
        except Exception as exc:
            errors.append(str(exc))
            summary = None

    expected_version = episode_contract_version(ep)
    if summary is not None:
        if summary.get("schema_version") != SCHEMA_VERSION:
            errors.append(f"frame semantic summary schema_version must be {SCHEMA_VERSION}")
        if summary.get("story_os_version") != expected_version:
            errors.append("frame semantic summary story_os_version mismatch")
        for field, expected in contexts.items():
            if str(summary.get(field) or "").lower() != str(expected).lower():
                errors.append(f"frame semantic summary {field} mismatch")
        provenance = summary.get("critic_provenance") or {}
        for error in runtime_provenance.validate_critic_provenance(provenance):
            errors.append("frame semantic summary critic provenance invalid: " + error)
        if provenance.get("review_scope") not in {"FULL_FRAME_SET", "BASELINE_PLUS_PATCHES"}:
            errors.append("frame semantic summary must prove FULL_FRAME_SET or BASELINE_PLUS_PATCHES review")
        bound = summary.get("frames")
        expected_bound = [{"frame": row["frame"], "asset_sha256": row["sha256"]} for row in frames]
        if bound != expected_bound:
            errors.append("frame semantic summary asset set does not match current approved frame set")
        if (summary.get("summary") or {}).get("passed") is not True:
            errors.append("frame semantic summary is not PASS")
        if summary.get("issue_codes") not in ([], None) and not summary.get("forced_pass_frames"):
            errors.append(f"frame semantic summary issue_codes not empty: {summary.get('issue_codes')}")

    directing_v3 = directing_v3_required(ep)
    for frame in frames:
        data = frame_review_persistence.load(ep, int(frame["frame"]))
        if not isinstance(data, dict):
            errors.append(f"missing frame semantic review: {REVIEW_DIR.as_posix()}/{frame['frame']}.json")
            continue
        try:
            errors.extend(validate_bound_review(data, frame=frame, contexts=contexts, version=expected_version, metadata_only=metadata_only, phase3_contexts=phase3_context_hashes(ep, frame["frame"]), directing_v3=directing_v3, ep=ep))
        except Exception as exc:
            errors.append(f"frame {frame['frame']} review source validation failed: {exc}")

    phashes: list[dict] = []
    duplicates: list[dict] = []
    if not metadata_only and not errors:
        try:
            phashes = perceptual_rows(frames)
            duplicates = duplicate_pairs(phashes)
            if duplicates:
                for pair in duplicates:
                    errors.append(
                        "near-duplicate actual frames forbidden: "
                        + "/".join(pair["frames"])
                        + f" dhash={pair['dhash_distance']} ahash={pair['ahash_distance']}"
                    )
        except Exception as exc:
            errors.append(f"perceptual duplicate audit failed: {exc}")

    if write_audit:
        audit = {
            "schema_version": 1,
            "story_os_version": expected_version,
            "checked_at": now(),
            "metadata_only": metadata_only,
            "frame_count": len(frames),
            "perceptual_hashes": phashes,
            "near_duplicate_pairs": duplicates,
            "errors": errors,
            "summary": {"passed": not errors},
        }
        # Keep the audit reproducible: snapshot verification may re-run this
        # audit repeatedly, so do not rewrite (and re-hash) the evidence file
        # when only the wall-clock checked_at would change.
        audit_path = ep / AUDIT_REL
        changed = True
        if audit_path.is_file():
            try:
                old = read_json(audit_path)
                old.pop("checked_at", None)
                fresh = dict(audit)
                fresh.pop("checked_at", None)
                changed = old != fresh
            except Exception:
                changed = True
        if changed:
            write_json(audit_path, audit)
    return errors


def verify_scoped_review(ep: Path, frames: list[dict], *, review_scope: str, metadata_only: bool = False) -> list[str]:
    if review_scope != PHASE5A_SINGLE_FRAME_SCOPE:
        return [f"unsupported scoped review scope: {review_scope}"]
    errors: list[str] = []
    contexts = context_hashes(ep)
    errors.extend(phase4_binding_errors(ep, frames))
    summary_path = ep / SUMMARY_REL
    if not summary_path.is_file():
        return ["meta/frame-semantic-review.json missing"]
    try:
        summary = read_json(summary_path)
    except Exception as exc:
        return [str(exc)]
    version = episode_contract_version(ep)
    if summary.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"frame semantic summary schema_version must be {SCHEMA_VERSION}")
    if summary.get("story_os_version") != version:
        errors.append("frame semantic summary story_os_version mismatch")
    for field, expected in contexts.items():
        if str(summary.get(field) or "").lower() != str(expected).lower():
            errors.append(f"frame semantic summary {field} mismatch")
    provenance = summary.get("critic_provenance") or {}
    for error in runtime_provenance.validate_critic_provenance(provenance):
        errors.append("frame semantic summary critic provenance invalid: " + error)
    if provenance.get("review_scope") != review_scope:
        errors.append("frame semantic summary review_scope mismatch")
    expected_bound = [{"frame": row["frame"], "asset_sha256": row["sha256"]} for row in frames]
    if summary.get("frames") != expected_bound:
        errors.append("frame semantic summary asset set does not match scoped reviewed frame set")
    if (summary.get("summary") or {}).get("passed") is not True:
        errors.append("frame semantic summary is not PASS")
    if summary.get("issue_codes") not in ([], None) and not summary.get("forced_pass_frames"):
        errors.append(f"frame semantic summary issue_codes not empty: {summary.get('issue_codes')}")
    directing_v3 = directing_v3_required(ep)
    for frame in frames:
        data = frame_review_persistence.load(ep, int(frame["frame"]))
        if not isinstance(data, dict):
            errors.append(f"missing frame semantic review: {REVIEW_DIR.as_posix()}/{frame['frame']}.json")
            continue
        errors.extend(validate_bound_review(
            data, frame=frame, contexts=contexts, version=version, metadata_only=metadata_only,
            phase3_contexts=phase3_context_hashes(ep, frame["frame"]),
            directing_v3=directing_v3, ep=ep))
    return errors


def reconcile_review_projection(ep: Path, *, write_report: bool = False) -> dict:
    """Classify existing PASS/LOCK projections without repairing history or rerunning work.

    The report is diagnostic authority only. It never changes Ledger status,
    approved pixels, review queue state, Episode stage, or model/provider work.
    """
    ep = Path(ep).resolve()
    import production_ledger
    import production_queue_store
    import logical_asset_identity

    ledger = production_ledger.load_authority(ep, default={}) or {}
    queue_path = production_queue_store.read_path(ep)
    try:
        queue = read_json(queue_path) if queue_path.is_file() else {}
    except Exception:
        queue = {}
    queue_items = queue.get("review_work_items") if isinstance(queue, dict) else []
    queue_items = queue_items if isinstance(queue_items, list) else []
    projections = []
    for frame_key, row in sorted((ledger.get("frames") or {}).items()):
        if not isinstance(row, dict):
            continue
        approved = row.get("approved_asset") if isinstance(row.get("approved_asset"), dict) else {}
        if not approved and isinstance(row.get("current_candidate"), dict):
            approved = row["current_candidate"]
        if str(row.get("status") or "").upper() not in {"PASSED", "LOCKED"} and not approved:
            continue
        frame_no = str(frame_key).zfill(2)
        review = frame_review_persistence.load(ep, int(frame_no))
        provenance = (review.get("critic_provenance") or {}) if isinstance(review, dict) else {}
        model_receipt = review_receipt_for_frame(ep, frame_no)
        review_item_id = str((review or {}).get("review_item_id") or "")
        matching = [item for item in queue_items if isinstance(item, dict)
                    and item.get("review_key") == review_item_id]
        queue_terminal = next((item for item in matching
                               if item.get("status") == "finalized"
                               and isinstance(item.get("receipt"), dict)
                               and item["receipt"].get("status") == "SUCCESS"), None)
        errors = []
        if not isinstance(review, dict):
            errors.append("frame review record missing")
        else:
            try:
                frames = frame_records(ep, require_files=False, only_frames=[int(frame_no)])
                errors.extend(verify_scoped_review(
                    ep, frames, review_scope=PHASE5A_SINGLE_FRAME_SCOPE, metadata_only=True))
            except Exception as exc:
                errors.append(str(exc))
        if not isinstance(model_receipt, dict):
            errors.append("Final Semantic Model Execution Receipt missing")
        if not queue_terminal:
            errors.append("Review Queue terminal SUCCESS receipt missing")
        projections.append({
            "frame": frame_no,
            "ledger_status": str(row.get("status") or ""),
            "approved_sha256": str(approved.get("sha256") or "").lower(),
            "review_item_id": review_item_id or None,
            "classification": "VERIFIED" if not errors else "UNVERIFIED_REVIEW_PROJECTION",
            "errors": sorted(set(errors)),
        })
    report = {
        "schema_version": 1,
        "episode_id": logical_asset_identity.episode_id(ep),
        "authority": "DIAGNOSTIC_ONLY",
        "model_dispatch_count": 0,
        "provider_dispatch_count": 0,
        "projections": projections,
        "status": ("UNVERIFIED_REVIEW_PROJECTION"
                   if any(item["classification"] != "VERIFIED" for item in projections)
                   else "VERIFIED" if projections else "NO_REVIEW_PROJECTIONS"),
    }
    if write_report:
        report_path = ep / "meta" / "review-projection-reconciliation.json"
        current = read_json(report_path) if report_path.is_file() else None
        if current != report:
            write_json(report_path, report)
    return report


def review_receipt_for_frame(ep: Path, frame: str | int) -> dict | None:
    """Read the persisted Final Semantic receipt for one frame, if present."""
    try:
        data = frame_review_persistence.load(Path(ep).resolve(), int(frame))
    except Exception:
        return None
    provenance = data.get("critic_provenance") if isinstance(data, dict) else None
    receipt = provenance.get("model_execution_receipt") if isinstance(provenance, dict) else None
    return receipt if isinstance(receipt, dict) else None


resolve_codex = critic_runner.resolve_codex
command_prefix = critic_runner.prefix


def _local_triage_prompt_block(ep: Path, rows: list[dict]) -> str:
    hints = []
    for row in rows:
        try:
            hint = local_visual_triage.hint_for_frame(
                ep, int(row["frame"]), str(row.get("sha256") or "")
            )
        except Exception:
            hint = ""
        if hint:
            hints.append(hint)
    return "\n".join(hints) if hints else "none"


def critic_prompt(ep: Path, frames: list[dict], candidate: Path, attempt: int, *, review_scope: str = "FULL_FRAME_SET") -> str:
    rel_ep = ep.relative_to(ROOT).as_posix()
    story, storyboard = episode_files(ep)
    rel_story = story.relative_to(ROOT).as_posix()
    rel_storyboard = storyboard.relative_to(ROOT).as_posix()
    rel_gates = (ep / "meta/story-gates.json").relative_to(ROOT).as_posix()
    rel_out = candidate.relative_to(ROOT).as_posix()
    mapping = "\n".join(f"- attachment/frame {row['frame']}: {row['path_rel']}" for row in frames)
    local_triage_block = _local_triage_prompt_block(ep, frames)
    version = episode_contract_version(ep)
    directing_v3 = directing_v3_required(ep)
    # STORY_OS_V221_PROMPT_ALIGN: the Required-shape sample must list exactly the
    # checks enforced by validate_* for this episode version, otherwise every
    # critic attempt fails with "checks.X must be true" for keys never requested.
    required_checks = checks_for_version(version, directing_v3)
    checks_block = ",\n".join(f'        "{name}": true' for name in required_checks)
    scope_intro = (
        f"You are reviewing a NON_PROMOTABLE Phase5A single-frame Production Subpath canary for exactly {rel_ep}. "
        "Judge only the supplied actual frame against the complete locked Story/storyboard/Frame Contract context; "
        "do not require ungenerated Episode frames."
        if review_scope == PHASE5A_SINGLE_FRAME_SCOPE
        else f"You are reviewing the COMPLETE final approved frame set for exactly {rel_ep}."
    )
    return f"""You are an adversarial Production Frame Semantic Critic in a FRESH isolated session.
Do NOT generate or edit images. Do NOT rewrite the story. Do NOT trust previous PASS labels.
{scope_intro}

Read these locked sources before judging:
- {rel_story}
- {rel_storyboard}
- {rel_gates}
- standards/制作规范_正式版.md
- standards/生产帧语义强制规范_V1.0.md
- standards/Resolved_Frame_Contract规范_V1.0.md
- standards/Fast_Frame_Scout_与_Final_Candidate_Snapshot规范_V1.0.md
Fast Scout evidence is triage only. Do NOT trust PASS_FAST as a final pass; independently judge every supplied actual frame.
Resolved Frame Contracts: {runtime_workspace.workspace_path(ep, phase4_contract.CACHE_ROOT).as_posix()}/NN.json. The frame review must honor the SAME contract SHA used by the generation attempt.

Attached images are in numeric order and map as follows:
{mapping}

Local Visual Triage pre-scan (advisory only; never authoritative):
{local_triage_block}

This is critic attempt {attempt}. Judge the ACTUAL pixels against Story Lock + storyboard + authenticity/continuity anchors.
Episode contract version: {episode_contract_version(ep)}. V2.2-only Visual Narrative checks and issue codes apply ONLY when version >= 2.2.0. Earlier episodes must not fail on V2.2-only criteria.
The visual-profile critic is a different job. A frame can look perfectly M00 and STILL FAIL here if it depicts the wrong person, wrong wardrobe, wrong timeline, illegal camera viewpoint, wrong prop, unreadable anomaly, or merely lets the caption claim evidence that the pixels do not show.

Hard rules for EVERY frame:
1. scene_storyboard_fidelity: the actual place/action/composition must be the storyboarded scene, not a generic substitute.
2. story_beat_fidelity: the image must visibly carry the intended narrative beat. Do not let prose rescue a missing event.
3. key_prop_fidelity: locked prop structure, material, scale, count and state must match. A generic green beer bottle cannot stand in for a locked thick micro-city glass vessel if the story depends on the city being visibly inside it.
4. character_identity + wardrobe_continuity: character age/sex/identity/garment anchors must not drift. If a frame suddenly shows another protagonist, FAIL.
5. pov_photographer_legality: obey the authenticity card. If the first-person photographer is fully visible or both hands are occupied while no legal second capture source exists, FAIL. Unexplained third-person coverage is a hard failure.
6. spatial_continuity + temporal_continuity: location relationships and timeline must agree with neighboring frames. A father who already left for hospital cannot silently reappear in the factory.
7. anomaly_readability: the abnormal fact the frame is supposed to prove must be visually legible. If the caption says a river tilted, a red mark aligned with a chimney, or old photos all contain one white arc, those relationships must actually be readable in pixels.
8. caption_image_support: planned text may add context but must not invent the core visual evidence.
9. actual_information_gain: compare ACTUAL adjacent images, not just storyboard descriptions.
10. environment_physics_fidelity: V2.1 weather/environment must obey the resolved physical conditions; weather is not a blanket filter.
11. anomaly_escalation_fidelity: impact 3-4 / anomaly_amplified / climax_impact must visibly exceed escalation_from; caption-only escalation fails.
12. scale_reference_fidelity: high-impact frames must visibly use the locked real-world scale reference so abnormal size is readable.
13. camera_authorship_physical: photographer/camera source must exist physically; ghost/floating/omniscient coverage is a hard failure.
14. moment_capture_credibility: frame must feel captured during an action with a plausible save reason, not posed after the event.
15. narrative_evidence_gain: each frame after the opening must add real story/evidence information; another angle of the same unchanged fact is NARRATIVE_REDUNDANCY.
16. shot_grammar_diversity: first-person is diegetic camera logic, not a repeated hand+phone+distant-anomaly template.
17. camera_defect_physics: blur/noise/reflection/underexposure must have a plausible physical cause.
18. screen_content_physics: phone/map/dashboard/time/camera UI must be internally, perspectivally and narratively coherent.
19. visual_memory_continuity: character/wardrobe/vehicle/props/route/weather/light/anomaly evidence must persist unless explicitly changed.
19a. When adjoining frames belong to the same sequence, independently compare ACTUAL attached pixels for recognizable person/clothes consistency, physically reachable photographer positions, prop contact/state changes, and evidence progression. Static quiet beats are valid where storyboarded; do not manufacture blur or movement to satisfy this. A photorealistic but semantically unchanged repeat is not a continuity success. Do not import unrelated style-reference people, actions or locations.
19b. For M00 frames where the authoritative Resolved Frame Contract explicitly contains [M00 LOCKED ADJACENT STATE TRANSITION], compare the exact previous and current ACTUAL images: all LOCKED_* invariants must persist, and every CHANGE_* BEFORE/AFTER/VERIFY_IN_PIXELS action must be visibly supported; copied previous pose or reconstructed fixed doors/walls/planters FAILS, however stillness marked BEAT_MODE=static must not be punished. An advisory numeric pixel difference or Test-only review receipt is NEVER official Final Semantic PASS. Never invent any change where this explicit source-bound block is absent.
20. anatomy_limb_hand_integrity: visible human anatomy must be physically plausible. Extra/missing/fused limbs, impossible joint topology, duplicated or melted fingers/hands, detached body parts, or severe anatomy deformation are hard failures even when identity/story/POV are otherwise correct.
21. For shot-progression schema_version >=3 only: shot_scale_fidelity must match the locked shot_scale; scene_position_uniqueness_fidelity must not collapse different planned positions into visibly repeated camera setups; cinematic_structure_translation_fidelity must use the locked structural technique without becoming an exact film-still recreation; practical_lighting_design_fidelity must honor the declared real light source/contrast/suspense function; anomaly_concealment_fidelity must visibly use the locked mirror/water/glass/fog/light-shadow/screen/occlusion carrier when declared.
22. PASS only if all required checks are true, issue_codes is empty and decision=pass.

Use issue codes only from this set:
{', '.join(sorted(ISSUE_CODES))}

Write ONLY valid JSON to {rel_out}. Do not modify any other repository file.
Required shape:
{{
  "frames": [
    {{
      "frame": "01",
      "checks": {{
{checks_block}
      }},
      "issue_codes": [],
      "notes": "specific pixel-level evidence",
      "decision": "pass"
    }}
  ],
  "issue_codes": [],
  "summary": {{"passed": true, "notes": "overall continuity/payoff judgment"}}
}}
Return one row for EVERY attached frame. If any hard check fails, mark it false, add the specific issue code, set that frame decision=fail and summary.passed=false.
"""


def _prepare_final_semantic_shadow_best_effort(ep: Path, attempt: int) -> dict | None:
    """Prepare the advisory lane without allowing it to block canonical review."""
    try:
        try:
            import final_semantic_critic_adapter
        except ModuleNotFoundError:
            from agents import final_semantic_critic_adapter
        return final_semantic_critic_adapter.schedule_shadow_best_effort(ep, attempt=attempt)
    except Exception as exc:  # pragma: no cover - defensive fallback around a non-authoritative lane
        print(f"WARN: Final Semantic Critic Shadow wiring unavailable: {type(exc).__name__}: {exc}")
        return None


def _full_review_parallelism(frame_count: int) -> int:
    """Choose bounded Final Semantic fan-out from frame count and the canonical config cap."""
    count = max(0, int(frame_count))
    cap = min(runtime_router.vision_review_max_inflight_final(), ABSOLUTE_MAX_FULL_REVIEW_SHARDS)
    if count <= 5:
        desired = 1
    elif count <= 10:
        desired = 2
    elif count <= 15:
        desired = 3
    elif count <= 20:
        desired = 4
    else:
        desired = 5
    return max(1, min(desired, cap))


def _full_review_shards(frames: list[dict], max_shards: int | None = None) -> list[dict]:
    """Split FULL review targets into contiguous shards with read-only neighbor context.

    Every frame is owned by exactly one target shard.  Immediate neighbors may be
    repeated as context, so a boundary continuity defect can veto the owner's PASS
    during conservative merge without giving any shard Ledger authority.
    """
    ordered = sorted(frames, key=lambda row: int(row["frame"]))
    if not ordered:
        return []
    configured_cap = min(runtime_router.vision_review_max_inflight_final(), ABSOLUTE_MAX_FULL_REVIEW_SHARDS)
    requested = _full_review_parallelism(len(ordered)) if max_shards is None else int(max_shards)
    shard_count = max(1, min(requested, configured_cap, len(ordered)))
    base_size, extra = divmod(len(ordered), shard_count)
    shards: list[dict] = []
    offset = 0
    for index in range(shard_count):
        size = base_size + (1 if index < extra else 0)
        start, end = offset, offset + size
        targets = ordered[start:end]
        selected_start = max(0, start - 1)
        selected_end = min(len(ordered), end + 1)
        selected = ordered[selected_start:selected_end]
        # Frame01 and the final frame are cheap global visual-memory anchors.
        # Repeating them as read-only context gives each shard whole-episode
        # orientation without serializing every frame through one critic.
        selected_by_key = {row["frame"]: row for row in selected}
        selected_by_key.setdefault(ordered[0]["frame"], ordered[0])
        selected_by_key.setdefault(ordered[-1]["frame"], ordered[-1])
        selected = [selected_by_key[key] for key in sorted(selected_by_key, key=int)]
        target_keys = [row["frame"] for row in targets]
        target_set = set(target_keys)
        shards.append({
            "index": index + 1,
            "target_frames": target_keys,
            "context_frames": [row["frame"] for row in selected if row["frame"] not in target_set],
            "selected": selected,
        })
        offset = end
    coverage = [key for shard in shards for key in shard["target_frames"]]
    expected = [row["frame"] for row in ordered]
    if sorted(coverage) != sorted(expected) or len(coverage) != len(set(coverage)):
        raise RuntimeError("full semantic shard target coverage must be exact and non-overlapping")
    return shards


def _sharded_critic_prompt(ep: Path, shard: dict, candidate: Path, attempt: int) -> str:
    selected = shard["selected"]
    base_prompt = critic_prompt(ep, selected, candidate, attempt)
    rel_ep = ep.relative_to(ROOT).as_posix()
    original = f"You are reviewing the COMPLETE final approved frame set for exactly {rel_ep}."
    replacement = (
        f"You are one NON-AUTHORITATIVE shard of the complete final frame review for exactly {rel_ep}.\n"
        f"TARGET frames owned by this shard: {', '.join(shard['target_frames'])}.\n"
        f"Read-only CONTEXT frames: {', '.join(shard['context_frames']) or '<none>'}.\n"
        "Judge EVERY supplied frame with the same full hard checks. Context failures must be reported; "
        "the parent will conservatively merge overlapping judgments. Do not assume frames outside this shard PASS."
    )
    if original not in base_prompt:
        raise RuntimeError("full semantic critic prompt anchor drifted")
    return base_prompt.replace(original, replacement, 1)


def _launch_full_review_shard(
    ep: Path,
    shard: dict,
    *,
    attempt: int,
    codex: Path,
    timeout: int,
) -> dict:
    index = int(shard["index"])
    candidate = ep / "meta" / f".frame-semantic-shard-{attempt}-{index}.candidate.json"
    log = ep / "meta" / f"frame-semantic-critic-attempt-{attempt}-shard-{index}.jsonl"
    candidate.unlink(missing_ok=True)
    completed = critic_runner.launch(
        _sharded_critic_prompt(ep, shard, candidate, attempt),
        codex=codex,
        root=ROOT,
        timeout=timeout,
        sandbox="workspace-write",
        model=runtime_router.vision_review_model(),
        reasoning_effort=runtime_router.vision_review_effort("final"),
        attachments=[row["path"] for row in shard["selected"]],
        log_path=log,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"final semantic shard {index} failed rc={completed.returncode}; log={log}")
    if not candidate.is_file():
        raise RuntimeError(f"final semantic shard {index} did not produce {candidate}")
    data = read_json(candidate)
    version = episode_contract_version(ep)
    directing_v3 = directing_v3_required(ep)
    errors = validate_candidate_gate_rows(data.get("frames"), shard["selected"], version, directing_v3)
    global_codes = data.get("issue_codes")
    if not isinstance(global_codes, list):
        errors.append("global issue_codes must be list")
    else:
        unknown = [code for code in global_codes if code not in ISSUE_CODES]
        if unknown:
            errors.append(f"global issue_codes contain unknown values: {unknown}")
    decisions = [str(row.get("decision") or "") for row in (data.get("frames") or []) if isinstance(row, dict)]
    expected_summary = bool(decisions) and all(value == "pass" for value in decisions)
    if (data.get("summary") or {}).get("passed") is not expected_summary:
        errors.append("critic summary.passed does not match shard frame decisions")
    if errors:
        raise RuntimeError(f"final semantic shard {index} candidate invalid: " + "; ".join(errors))
    return {
        "index": index,
        "target_frames": list(shard["target_frames"]),
        "context_frames": list(shard["context_frames"]),
        "selected_frames": [row["frame"] for row in shard["selected"]],
        "candidate_path": repo_rel(candidate),
        "candidate_sha256": sha256_file(candidate),
        "log_path": repo_rel(log),
        "data": data,
    }


def _execute_full_review_shards(
    ep: Path,
    shards: list[dict],
    *,
    attempt: int,
    codex: Path,
    timeout: int,
) -> tuple[list[dict], int]:
    """Run read-only critic shards concurrently and return only after all settle."""
    if not shards:
        raise RuntimeError("full semantic review requires at least one shard")
    max_workers = min(runtime_router.vision_review_max_inflight_final(), ABSOLUTE_MAX_FULL_REVIEW_SHARDS, len(shards))
    counter_lock = threading.Lock()
    active = 0
    peak = 0

    def invoke(shard: dict) -> dict:
        nonlocal active, peak
        with counter_lock:
            active += 1
            peak = max(peak, active)
        try:
            return _launch_full_review_shard(
                ep, shard, attempt=attempt, codex=codex, timeout=timeout)
        finally:
            with counter_lock:
                active -= 1

    results: list[dict] = []
    failures: list[str] = []
    with cf.ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="final-semantic") as pool:
        futures = {pool.submit(invoke, shard): shard for shard in shards}
        for future in cf.as_completed(futures):
            shard = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:
                failures.append(f"shard {shard['index']}: {type(exc).__name__}: {exc}")
    if failures:
        raise RuntimeError("final semantic sharded critic failed closed: " + " | ".join(sorted(failures)))
    return sorted(results, key=lambda row: int(row["index"])), peak


def _merge_full_review_shards(results: list[dict], frames: list[dict]) -> dict:
    """Conservatively merge overlapping shard judgments into one full-set result."""
    expected = [row["frame"] for row in sorted(frames, key=lambda item: int(item["frame"]))]
    owned = [key for result in results for key in result.get("target_frames") or []]
    if sorted(owned) != sorted(expected) or len(owned) != len(set(owned)):
        raise RuntimeError("final semantic shard owner coverage mismatch")
    observations: dict[str, list[tuple[int, dict]]] = {key: [] for key in expected}
    top_codes: list[str] = []
    for result in results:
        index = int(result["index"])
        data = result.get("data") or {}
        for code in data.get("issue_codes") or []:
            if code not in top_codes:
                top_codes.append(code)
        for row in data.get("frames") or []:
            if not isinstance(row, dict):
                continue
            key = str(row.get("frame") or "").zfill(2)
            if key in observations:
                observations[key].append((index, row))
            for code in row.get("issue_codes") or []:
                if code not in top_codes:
                    top_codes.append(code)
    # Check names are identical across all rows for one Episode; use the first
    # observation as the superset and AND every supplied boolean conservatively.
    merged_rows: list[dict] = []
    for key in expected:
        seen = observations.get(key) or []
        if not seen:
            raise RuntimeError(f"final semantic shard merge missing frame {key}")
        check_names: set[str] = set()
        for _, row in seen:
            check_names.update((row.get("checks") or {}).keys())
        checks = {
            name: all((row.get("checks") or {}).get(name) is True for _, row in seen)
            for name in sorted(check_names)
        }
        codes: list[str] = []
        notes: list[str] = []
        any_fail = False
        for index, row in seen:
            if str(row.get("decision") or "") != "pass":
                any_fail = True
            for code in row.get("issue_codes") or []:
                if code not in codes:
                    codes.append(code)
            note = str(row.get("notes") or "").strip()
            if note:
                notes.append(f"s{index}:{note}")
        all_checks = bool(checks) and all(checks.values())
        decision = "pass" if not any_fail and all_checks and not codes else "fail"
        merged_rows.append({
            "frame": key,
            "checks": checks,
            "issue_codes": codes,
            "notes": " | ".join(notes)[:2000],
            "decision": decision,
        })
    passed = all(row["decision"] == "pass" for row in merged_rows)
    return {
        "frames": merged_rows,
        "issue_codes": top_codes,
        "summary": {"passed": passed, "notes": f"conservative merge of {len(results)} final semantic shards"},
    }


def _global_closure_anchor_rows(frames: list[dict], shards: list[dict]) -> list[dict]:
    """Pick only whole-episode and cross-shard boundary anchors for closure review."""
    ordered = sorted(frames, key=lambda row: int(row["frame"]))
    if not ordered:
        return []
    by_key = {row["frame"]: row for row in ordered}
    keys = {ordered[0]["frame"], ordered[-1]["frame"]}
    for shard in shards:
        targets = list(shard.get("target_frames") or [])
        if targets:
            keys.add(str(targets[0]).zfill(2))
            keys.add(str(targets[-1]).zfill(2))
    return [by_key[key] for key in sorted(keys, key=int) if key in by_key]


def _global_closure_prompt(
    ep: Path,
    anchors: list[dict],
    shard_results: list[dict],
    candidate: Path,
    attempt: int,
) -> str:
    story, storyboard = episode_files(ep)
    rel_ep = ep.relative_to(ROOT).as_posix()
    rel_out = repo_rel(candidate)
    anchor_lines = "\n".join(
        f"- Frame {row['frame']}: {row['path_rel']}" for row in anchors)
    shard_digest = [{
        "index": row["index"],
        "target_frames": row["target_frames"],
        "summary": (row.get("data") or {}).get("summary") or {},
        "issue_codes": (row.get("data") or {}).get("issue_codes") or [],
    } for row in shard_results]
    return f"""You are the FINAL GLOBAL CLOSURE critic for exactly {rel_ep}.
Local pixel/detail review has already been completed by bounded parallel shards. Do NOT redo anatomy, local scene fidelity, or other per-frame checks unless a supplied boundary image reveals a cross-shard contradiction.

Read these locked sources:
- Story: {repo_rel(story)}
- Storyboard: {repo_rel(storyboard)}
- Episode visual contract: {rel_ep}/meta/story-gates.json

Read-only boundary/whole-episode anchor images:
{anchor_lines}

Shard summaries (NON-AUTHORITATIVE; use as context, not as proof):
{json.dumps(shard_digest, ensure_ascii=False, indent=2)}

Judge ONLY these five cross-shard checks:
1. identity_wardrobe_continuity: the same people and wardrobe persist coherently across shard boundaries.
2. spatial_temporal_continuity: route/location/time/weather progression has no cross-shard contradiction.
3. visual_memory_continuity: vehicles, props, environment and anomaly evidence persist unless the locked story changes them.
4. narrative_progression: each shard advances evidence/story; boundaries do not collapse into unexplained repetition or missing information gain.
5. ending_payoff_coherence: the final boundary and ending pay off the established sequence without contradicting earlier evidence.

Allowed issue codes for this closure only:
{', '.join(sorted(GLOBAL_CLOSURE_ISSUE_CODES))}

If a cross-shard failure exists, affected_frames MUST contain the supplied boundary frame(s) that expose it. Do not name an unattached frame. If all five checks pass, affected_frames and issue_codes must both be empty.

Write ONLY valid JSON to {rel_out}:
{{
  "boundary_checks": {{
    "identity_wardrobe_continuity": true,
    "spatial_temporal_continuity": true,
    "visual_memory_continuity": true,
    "narrative_progression": true,
    "ending_payoff_coherence": true
  }},
  "affected_frames": [],
  "issue_codes": [],
  "notes": "specific cross-shard evidence",
  "summary": {{"passed": true}}
}}
This is attempt {attempt}. Do not modify any other repository file.
"""


def _validate_global_closure_candidate(data: object, anchors: list[dict]) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["global closure candidate must be object"]
    checks = data.get("boundary_checks")
    if not isinstance(checks, dict):
        errors.append("global closure boundary_checks must be object")
        checks = {}
    missing = [name for name in GLOBAL_CLOSURE_CHECKS if not isinstance(checks.get(name), bool)]
    if missing:
        errors.append(f"global closure checks missing/non-bool: {missing}")
    unknown_checks = [name for name in checks if name not in GLOBAL_CLOSURE_CHECKS]
    if unknown_checks:
        errors.append(f"global closure unknown checks: {unknown_checks}")

    codes = data.get("issue_codes")
    if not isinstance(codes, list):
        errors.append("global closure issue_codes must be list")
        codes = []
    unknown_codes = [code for code in codes if code not in GLOBAL_CLOSURE_ISSUE_CODES]
    if unknown_codes:
        errors.append(f"global closure unknown issue_codes: {unknown_codes}")

    affected_raw = data.get("affected_frames")
    if not isinstance(affected_raw, list):
        errors.append("global closure affected_frames must be list")
        affected_raw = []
    affected = [str(value).zfill(2) for value in affected_raw]
    allowed = {row["frame"] for row in anchors}
    outside = [key for key in affected if key not in allowed]
    if outside:
        errors.append(f"global closure affected_frames not attached: {outside}")
    if len(affected) != len(set(affected)):
        errors.append("global closure affected_frames must be unique")

    summary = data.get("summary")
    passed = summary.get("passed") if isinstance(summary, dict) else None
    if not isinstance(passed, bool):
        errors.append("global closure summary.passed must be bool")
        passed = False
    expected_passed = (
        all(checks.get(name) is True for name in GLOBAL_CLOSURE_CHECKS)
        and not codes and not affected
    )
    if passed is not expected_passed:
        errors.append("global closure summary.passed does not match checks/issues/affected_frames")
    if passed is False and (not codes or not affected):
        errors.append("global closure FAIL requires issue_codes and affected_frames")
    return errors


def _launch_global_closure(
    ep: Path,
    *,
    anchors: list[dict],
    shard_results: list[dict],
    attempt: int,
    codex: Path,
    timeout: int,
) -> dict:
    candidate = ep / "meta" / f".frame-semantic-global-closure-{attempt}.candidate.json"
    log = ep / "meta" / f"frame-semantic-global-closure-attempt-{attempt}.jsonl"
    candidate.unlink(missing_ok=True)
    completed = critic_runner.launch(
        _global_closure_prompt(ep, anchors, shard_results, candidate, attempt),
        codex=codex,
        root=ROOT,
        timeout=timeout,
        sandbox="workspace-write",
        model=runtime_router.vision_review_model(),
        reasoning_effort=runtime_router.vision_review_effort("final"),
        attachments=[row["path"] for row in anchors],
        log_path=log,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"final semantic global closure failed rc={completed.returncode}; log={log}")
    if not candidate.is_file():
        raise RuntimeError(f"final semantic global closure did not produce {candidate}")
    data = read_json(candidate)
    errors = _validate_global_closure_candidate(data, anchors)
    if errors:
        raise RuntimeError("final semantic global closure candidate invalid: " + "; ".join(errors))
    return {
        "status": "COMPLETED",
        "anchor_frames": [row["frame"] for row in anchors],
        "candidate_path": repo_rel(candidate),
        "candidate_sha256": sha256_file(candidate),
        "log_path": repo_rel(log),
        "data": data,
    }


def _apply_global_closure(merged: dict, closure: dict) -> dict:
    """Let closure veto boundary frames without granting it direct Ledger authority."""
    out = json.loads(json.dumps(merged, ensure_ascii=False))
    passed = bool((closure.get("summary") or {}).get("passed"))
    note = str(closure.get("notes") or "").strip()
    summary = out.setdefault("summary", {})
    previous = str(summary.get("notes") or "").strip()
    if passed:
        summary["passed"] = bool(summary.get("passed"))
        summary["notes"] = (previous + " | global closure PASS").strip(" |")
        return out

    affected = {str(value).zfill(2) for value in closure.get("affected_frames") or []}
    codes = [code for code in closure.get("issue_codes") or [] if code in GLOBAL_CLOSURE_ISSUE_CODES]
    for row in out.get("frames") or []:
        key = str(row.get("frame") or "").zfill(2)
        if key not in affected:
            continue
        row["decision"] = "fail"
        row_codes = row.setdefault("issue_codes", [])
        for code in codes:
            if code not in row_codes:
                row_codes.append(code)
        row_note = str(row.get("notes") or "").strip()
        closure_note = f"global-closure:{note}" if note else "global-closure:cross-shard contradiction"
        row["notes"] = (row_note + " | " + closure_note).strip(" |")[:2000]
    top_codes = out.setdefault("issue_codes", [])
    for code in codes:
        if code not in top_codes:
            top_codes.append(code)
    summary["passed"] = False
    summary["notes"] = (previous + " | global closure FAIL: " + (note or ",".join(codes))).strip(" |")
    return out


def _run_sharded_full_critic(
    ep: Path,
    *,
    frames: list[dict],
    attempt: int,
    codex: Path,
    timeout: int,
    candidate_gate: bool,
    contexts: dict,
    frozen_sources: dict,
    before: dict[str, str],
    stable_before: dict,
    phashes: list[dict],
) -> int:
    shards = _full_review_shards(frames)
    results, peak = _execute_full_review_shards(
        ep, shards, attempt=attempt, codex=codex, timeout=timeout)

    current = reviewable_frame_records(ep, require_files=True) if candidate_gate else frame_records(ep, require_files=True)
    if {row["frame"]: sha256_file(row["path"]) for row in current} != before:
        raise RuntimeError("sharded frame semantic critic reviewed assets drifted during review")
    story, storyboard = episode_files(ep)
    stable_after = {
        "story": sha256_file(story),
        "storyboard": sha256_file(storyboard),
        "visual": sha256_json(stable_visual_contract(ep)),
    }
    if stable_after != stable_before:
        raise RuntimeError("sharded frame semantic critic Story/Storyboard/visual context drifted")
    if review_source_bindings(ep, current) != frozen_sources:
        raise RuntimeError("sharded frame semantic critic source bindings drifted")

    merged = _merge_full_review_shards(results, current)
    closure_evidence: dict = {
        "status": "SKIPPED_LOCAL_FAILURE",
        "anchor_frames": [],
        "reason": "one or more local shard observations already failed",
    }
    if bool((merged.get("summary") or {}).get("passed")):
        anchors = _global_closure_anchor_rows(current, shards)
        closure = _launch_global_closure(
            ep,
            anchors=anchors,
            shard_results=results,
            attempt=attempt,
            codex=codex,
            timeout=timeout,
        )
        # The lightweight closure is still part of the same frozen review set.
        # It may veto a merged PASS, but source drift invalidates the whole round.
        current_after_closure = (
            reviewable_frame_records(ep, require_files=True)
            if candidate_gate else frame_records(ep, require_files=True)
        )
        if {row["frame"]: sha256_file(row["path"]) for row in current_after_closure} != before:
            raise RuntimeError("global closure reviewed assets drifted during review")
        story_after, storyboard_after = episode_files(ep)
        stable_after_closure = {
            "story": sha256_file(story_after),
            "storyboard": sha256_file(storyboard_after),
            "visual": sha256_json(stable_visual_contract(ep)),
        }
        if stable_after_closure != stable_before:
            raise RuntimeError("global closure Story/Storyboard/visual context drifted")
        if review_source_bindings(ep, current_after_closure) != frozen_sources:
            raise RuntimeError("global closure source bindings drifted")
        merged = _apply_global_closure(merged, closure["data"])
        closure_evidence = {key: value for key, value in closure.items() if key != "data"}
        closure_evidence["passed"] = bool((closure["data"].get("summary") or {}).get("passed"))

    version = episode_contract_version(ep)
    directing_v3 = directing_v3_required(ep)
    merge_errors = validate_candidate_gate_rows(merged.get("frames"), current, version, directing_v3)
    if merge_errors:
        raise RuntimeError("sharded frame semantic merged candidate invalid: " + "; ".join(merge_errors))
    candidate = ep / CANDIDATE_REL
    write_json(candidate, merged)
    evidence_path = ep / "meta" / f"frame-semantic-sharded-attempt-{attempt}.json"
    evidence = {
        "schema_version": 2,
        "attempt": attempt,
        "review_scope": "SHARDED_FULL_FRAME_SET",
        "recorded_at": now(),
        "shard_count": len(results),
        "max_review_inflight": peak,
        "target_coverage": [row["frame"] for row in current],
        "candidate_path": repo_rel(candidate),
        "candidate_sha256": sha256_file(candidate),
        "source_bindings_sha256": sha256_json(frozen_sources),
        "global_closure": closure_evidence,
        "shards": [{
            "index": result["index"],
            "target_frames": result["target_frames"],
            "context_frames": result["context_frames"],
            "selected_frames": result["selected_frames"],
            "candidate_path": result["candidate_path"],
            "candidate_sha256": result["candidate_sha256"],
            "log_path": result["log_path"],
        } for result in results],
    }
    write_json(evidence_path, evidence)
    first_log = results[0]["log_path"] if results else None
    provenance = runtime_provenance.build_vision_critic_provenance(
        attempt=attempt, log=first_log, review_scope="FULL_FRAME_SET")
    provenance.update({
        "anatomy_integrity_enforced": True,
        "sharded_review": True,
        "shard_count": len(results),
        "max_review_inflight": peak,
        "shard_logs": [result["log_path"] for result in results],
        "sharded_evidence": repo_rel(evidence_path),
        "global_closure_status": closure_evidence.get("status"),
        "global_closure_passed": closure_evidence.get("passed"),
        "global_closure_log": closure_evidence.get("log_path"),
    })
    if candidate_gate:
        return _apply_candidate_gate(
            ep, data=merged, reviewed=current, contexts=contexts,
            provenance=provenance, attempt=attempt)
    return _persist_candidate(
        ep, data=merged, current=current, contexts=contexts, phashes=phashes,
        provenance=provenance, frozen_sources=frozen_sources)


def _rebind_incremental_captions(ep: Path) -> None:
    """Keep the V2.0.3.4 caption binding fresh for frame semantic evidence.

    Caption binding is a release/delivery concern. A verified formal review may
    exist before ``release-manifest.json`` is created; in that state the reuse
    path must stay metadata-only and must not rescan frame assets.
    """
    if not (ep / "meta/release-manifest.json").is_file():
        return
    try:
        import incremental_frame_review as incremental

        if not incremental.review_required(ep):
            return
        result = incremental.rebind_captions(ep)
        if not result.get("rebound"):
            print(f"WARN: incremental caption rebind skipped ({result.get('reason')})")
        elif result.get("errors"):
            for error in result["errors"]:
                print("WARN: incremental caption rebind verify:", error)
    except Exception as exc:  # pragma: no cover - defensive, never fails the review
        print(f"WARN: incremental caption rebind failed: {exc}")


def _persist_candidate(
    ep: Path,
    *,
    data: dict,
    current: list[dict],
    contexts: dict,
    phashes: list[dict],
    provenance: dict,
    frozen_sources: dict,
    verification_scope: str = "FULL_FRAME_SET",
    review_item: dict | None = None,
) -> int:
    if review_source_bindings(ep, current) != frozen_sources:
        raise RuntimeError("frame semantic review sources drifted during review; candidate cannot be rebound")
    version = episode_contract_version(ep)
    directing_v3 = directing_v3_required(ep)
    policy_sha = bound_review_policy_sha256(ep)
    rows_by_frame = {str(row.get("frame") or "").zfill(2): row for row in (data.get("frames") or []) if isinstance(row, dict)}
    forced = {row["frame"]: (_forced_marker(ep, row["frame"], row["sha256"])
              if rows_by_frame.get(row["frame"], {}).get("decision") != "pass" else None) for row in current}
    forced_frames = {key for key, marker in forced.items() if marker is not None}
    candidate_errors = validate_candidate_rows(data.get("frames"), current, version=version, directing_v3=directing_v3, forced_frames=forced_frames)
    global_codes = data.get("issue_codes")
    if not isinstance(global_codes, list):
        candidate_errors.append("global issue_codes must be list")
        global_codes = []
    elif global_codes and not forced_frames:
        candidate_errors.append(f"global issue_codes must be empty for PASS: {global_codes}")
    if (data.get("summary") or {}).get("passed") is not True and not forced_frames:
        candidate_errors.append("critic summary.passed must be true")

    for frame in current:
        source = rows_by_frame.get(frame["frame"], {})
        phase3_contexts = phase3_context_hashes(ep, frame["frame"])
        identity = {
            "logical_asset_key": frame.get("logical_asset_key"),
            "generation_key": frame.get("generation_key"),
            "sha256": frame["sha256"],
            "source_binding": frozen_sources["frames"][frame["frame"]].get("source_binding") or {},
        }
        bound = {
            "schema_version": SCHEMA_VERSION,
            "story_os_version": version,
            "frame": frame["frame"],
            "asset_path": frame["path_rel"],
            "asset_sha256": frame["sha256"],
            **contexts,
            **frozen_sources["frames"][frame["frame"]],
            "logical_asset_key": frame.get("logical_asset_key"),
            "generation_key": frame.get("generation_key"),
            "model_policy_sha256": policy_sha,
            "evidence_fingerprint": (
                review_evidence_fingerprint(
                    identity, contexts=contexts, phase3_contexts=phase3_contexts,
                    policy_sha256=policy_sha,
                    review_item_id=str((review_item or {}).get("review_key") or ""),
                    attempt_index=int((review_item or {}).get("attempt_index") or 0),
                    # Phase3 contract is the verified authority. Review Queue's
                    # copied frame_contract_sha256 may be blank on older rows and
                    # must not poison the durable review fingerprint.
                    frame_contract_sha256=phase3_contexts.get("frame_contract_sha256"),
                    prompt_package_sha256=(review_item or {}).get("prompt_package_sha256"),
                ) if verification_scope == PHASE5A_SINGLE_FRAME_SCOPE else
                frame_evidence_fingerprint(
                    identity, contexts=contexts, phase3_contexts=phase3_contexts,
                    policy_sha256=policy_sha)
            ),
            "review_item_id": str((review_item or {}).get("review_key") or "") or None,
            "attempt_index": int((review_item or {}).get("attempt_index") or 0) or None,
            "critic_provenance": provenance,
            "checks": source.get("checks") or {},
            "issue_codes": source.get("issue_codes") if isinstance(source.get("issue_codes"), list) else ["FRAME_SCENE_MISMATCH"],
            "notes": source.get("notes") or "",
            "decision": source.get("decision") or "fail",
            "forced_pass": frame["frame"] in forced_frames,
        }
        frame_review_persistence.save(ep, bound)

    summary = {
        "schema_version": SCHEMA_VERSION,
        "story_os_version": version,
        **contexts,
        "critic_provenance": provenance,
        "model_policy_sha256": policy_sha,
        "frames": [{"frame": row["frame"], "asset_sha256": row["sha256"]} for row in current],
        "perceptual_hashes": phashes,
        "near_duplicate_pairs": [],
        "issue_codes": global_codes,
        "critic_summary": data.get("summary") or {},
        "forced_pass_frames": sorted(forced_frames),
        "summary": {"passed": not candidate_errors},
    }
    write_json(ep / SUMMARY_REL, summary)
    _rebind_incremental_captions(ep)

    verify_errors = (
        verify_scoped_review(ep, current, review_scope=verification_scope, metadata_only=False)
        if verification_scope == PHASE5A_SINGLE_FRAME_SCOPE
        else verify_episode(ep, metadata_only=False, write_audit=True)
    )
    errors = candidate_errors + [x for x in verify_errors if x not in candidate_errors]
    if errors:
        print("FRAME SEMANTIC REVIEW FAIL")
        for error in errors:
            print("FAIL:", error)
        return 2
    # Keep the source candidate and pending request until every local
    # projection has passed verification. If the process stops earlier, the
    # queue recovery path can replay this same bound decision without a model
    # call. Deletion is cleanup only, after verified projections exist.
    (ep / CANDIDATE_REL).unlink(missing_ok=True)
    print("FRAME SEMANTIC REVIEW PASS")
    return 0


def finalize_product_review(ep: Path, *, attempt: int, runtime: str) -> int:
    frames = frame_records(ep, require_files=True)
    contexts = context_hashes(ep)
    frozen_sources = review_source_bindings(ep, frames)
    binding_errors = phase4_binding_errors(ep, frames)
    if binding_errors:
        for error in binding_errors:
            print("FAIL:", error)
        return 2
    phashes = perceptual_rows(frames)
    duplicates = duplicate_pairs(phashes)
    if duplicates:
        for pair in duplicates:
            print("FRAME SEMANTIC REVIEW FAIL: NEAR_DUPLICATE_ACTUAL_FRAMES", pair)
        return 2
    candidate = ep / CANDIDATE_REL
    data, provenance = product_review_adapter.finalize_candidate(
        ep,
        kind="frame-semantic",
        runtime=runtime,
        attempt=attempt,
        candidate_path=candidate,
        source_bindings=frozen_sources,
    )
    provenance["review_scope"] = "FULL_FRAME_SET"
    rc = _persist_candidate(
        ep,
        data=data,
        current=frames,
        contexts=contexts,
        phashes=phashes,
        provenance=provenance,
        frozen_sources=frozen_sources,
        review_item=None,
    )
    if rc == 0:
        product_review_adapter.mark_complete(ep, "frame-semantic", attempt=attempt, final_path=ep / SUMMARY_REL)
    return rc


def _run_critic_uninstrumented(
    ep: Path, *, attempt: int, codex_raw: str | None, timeout: int | None = None,
    target_frames: list[int | str] | tuple[int | str, ...] | None = None,
    review_scope: str = "FULL_FRAME_SET",
    review_item: dict | None = None,
) -> int:
    if timeout is None:
        timeout = runtime_timeout_policy.seconds("deep_semantic_review")
    if attempt not in {1, 2}:
        raise RuntimeError("attempt must be 1 or 2; only one automatic content-repair round is permitted")
    if (target_frames is None and (ep / SUMMARY_REL).is_file()
            and review_required(ep) and not verify_episode(ep)):
        try:
            prior_frames = (read_json(ep / SUMMARY_REL).get("frames") or [])
            episode_performance.safe_update_named_span(
                ep, episode_performance.review_span_name("FULL", attempt),
                {"target_frame_count": len(prior_frames), "shard_count": 0, "review_reused": True},
            )
        except Exception:
            pass
        _rebind_incremental_captions(ep)
        print("FRAME SEMANTIC REVIEW REUSED: current assets, contracts and critic evidence verified")
        return 0
    candidate_gate = False
    if target_frames is not None:
        if review_scope != PHASE5A_SINGLE_FRAME_SCOPE:
            raise RuntimeError("target_frames require PHASE5A_SINGLE_FRAME review scope")
        frames = reviewable_frame_records(ep, require_files=True, only_frames=target_frames)
        candidate_gate = True
    else:
        try:
            frames = frame_records(ep, require_files=True)
        except ValueError:
            frames = reviewable_frame_records(ep, require_files=True)
            candidate_gate = True
    episode_performance.safe_update_named_span(
        ep,
        episode_performance.review_span_name("FULL", attempt),
        {
            "target_frame_count": len(frames),
            "shard_count": _full_review_parallelism(len(frames)) if len(frames) >= FULL_REVIEW_FANOUT_MIN_FRAMES else 1,
        },
    )
    contexts = context_hashes(ep)
    binding_errors = reviewable_phase4_binding_errors(ep, frames) if candidate_gate else phase4_binding_errors(ep, frames)
    if binding_errors:
        print("FRAME SEMANTIC REVIEW FAIL: stale/missing generation Frame Contract")
        for error in binding_errors:
            print("FAIL:", error)
        return 2

    # Cheap deterministic failure before spending a critic call.
    phashes = perceptual_rows(frames)
    duplicates = duplicate_pairs(phashes)
    if duplicates:
        write_json(ep / AUDIT_REL, {
            "schema_version": 1,
            "story_os_version": story_os_version(),
            "checked_at": now(),
            "frame_count": len(frames),
            "perceptual_hashes": phashes,
            "near_duplicate_pairs": duplicates,
            "errors": ["NEAR_DUPLICATE_ACTUAL_FRAMES"],
            "summary": {"passed": False},
        })
        for pair in duplicates:
            print("FRAME SEMANTIC REVIEW FAIL: NEAR_DUPLICATE_ACTUAL_FRAMES", pair)
        return 2

    candidate = ep / CANDIDATE_REL
    frozen_sources = review_source_bindings(ep, frames)
    before = {row["frame"]: sha256_file(row["path"]) for row in frames}
    story, storyboard = episode_files(ep)
    stable_before = {
        "story": sha256_file(story),
        "storyboard": sha256_file(storyboard),
        "visual": sha256_json(stable_visual_contract(ep)),
    }

    if len(frames) >= FULL_REVIEW_FANOUT_MIN_FRAMES:
        recovered = recover_completed_shards_after_parent_timeout(ep, attempt=attempt)
        if recovered is not None:
            print("FRAME SEMANTIC REVIEW RECOVERED: completed shards committed after parent timeout")
            return recovered

    # Advisory Final Semantic Critic gets a distinct Product Review request.
    # It is prepared from the same frozen frame set before canonical review,
    # but its failure is deliberately unable to affect the existing reviewer.
    _prepare_final_semantic_shadow_best_effort(ep, attempt)

    active_runtime, _ = runtime_router.detect()
    vision_runtime, _ = runtime_router.vision_review_runtime()
    if vision_runtime != "CODEX" and not codex_raw:
        sources = [
            story,
            storyboard,
            ep / "meta/story-gates.json",
            ROOT / "standards/制作规范_正式版.md",
            ROOT / "standards/生产帧语义强制规范_V1.0.md",
            ROOT / "standards/Resolved_Frame_Contract规范_V1.0.md",
            ROOT / "standards/Fast_Frame_Scout_与_Final_Candidate_Snapshot规范_V1.0.md",
            *[row["path"] for row in frames],
        ]
        request = product_review_adapter.prepare(
            ep,
            kind="frame-semantic",
            runtime=active_runtime,
            attempt=attempt,
            prompt=critic_prompt(ep, frames, candidate, attempt, review_scope=review_scope),
            source_paths=sources,
            candidate_path=candidate,
            source_bindings=frozen_sources,
        )
        print(json.dumps(request, ensure_ascii=False, indent=2))
        return product_review_adapter.HOST_ACTION_REQUIRED_RC

    candidate.unlink(missing_ok=True)
    write_json(pending_request_path(ep, attempt),
               _pending_request_payload(ep, frames, attempt, review_scope=review_scope,
                                        review_item=review_item))
    codex = resolve_codex(codex_raw)
    if len(frames) >= FULL_REVIEW_FANOUT_MIN_FRAMES:
        return _run_sharded_full_critic(
            ep,
            frames=frames,
            attempt=attempt,
            codex=codex,
            timeout=timeout,
            candidate_gate=candidate_gate,
            contexts=contexts,
            frozen_sources=frozen_sources,
            before=before,
            stable_before=stable_before,
            phashes=phashes,
        )
    log = ep / "meta" / f"frame-semantic-critic-attempt-{attempt}.jsonl"
    critic_binding = model_policy.resolve("vision.final", episode=ep)
    critic_asset = frames[0] if frames else {}
    completed = critic_runner.launch(
        critic_prompt(ep, frames, candidate, attempt, review_scope=review_scope),
        codex=codex,
        root=ROOT,
        timeout=timeout,
        sandbox="workspace-write",
        model=critic_binding["model"],
        reasoning_effort=critic_binding["reasoning_effort"],
        attachments=[row["path"] for row in frames],
        log_path=log,
        model_execution_context={
            "episode": ep,
            "model_role": "vision.final",
            "profile": critic_binding["profile"],
            "model_policy_version": critic_binding["policy_version"],
            "model_policy_sha256": critic_binding["model_policy_sha256"],
            "logical_asset_key": critic_asset.get("logical_asset_key"),
            "generation_key": critic_asset.get("generation_key"),
            "attempt_index": attempt,
            "artifact_sha256": critic_asset.get("sha256"),
            "review_item_id": str((review_item or {}).get("review_key") or "") if isinstance(review_item, dict) else "",
            "runner_request_id": str((review_item or {}).get("runner_request_id") or "") if isinstance(review_item, dict) else "",
            "defer_final_semantic_success": isinstance(review_item, dict),
        },
    )
    if completed.returncode != 0:
        raise RuntimeError(f"isolated frame semantic critic failed rc={completed.returncode}; log={log}")
    if not candidate.is_file():
        raise RuntimeError(f"frame semantic critic did not produce {candidate}")

    current = (
        reviewable_frame_records(ep, require_files=True, only_frames=target_frames)
        if candidate_gate and target_frames is not None else
        reviewable_frame_records(ep, require_files=True) if candidate_gate else
        frame_records(ep, require_files=True)
    )
    if {row["frame"]: sha256_file(row["path"]) for row in current} != before:
        raise RuntimeError("frame semantic critic modified reviewed image assets")
    stable_after = {
        "story": sha256_file(story),
        "storyboard": sha256_file(storyboard),
        "visual": sha256_json(stable_visual_contract(ep)),
    }
    if stable_after != stable_before:
        raise RuntimeError("frame semantic critic modified Story Lock / storyboard / visual continuity context")

    data = read_json(candidate)
    provenance = runtime_provenance.build_vision_critic_provenance(
        attempt=attempt, log=log.relative_to(ROOT).as_posix(), review_scope=review_scope
    )
    provenance["anatomy_integrity_enforced"] = True
    receipt = None
    if isinstance(review_item, dict):
        receipt = _finalize_final_semantic_receipt(
            ep, receipt_ref=completed.model_execution_receipt,
            review_item=review_item, frame=critic_asset, candidate=candidate,
            log_path=log, returncode=int(completed.returncode), remote=completed.remote or {},
            contexts=contexts,
        )
    elif completed.model_execution_receipt:
        receipt, _receipt_path = _read_model_execution_receipt(ep, completed.model_execution_receipt)
    provenance["model_execution_receipt"] = receipt
    provenance["model_execution_receipt_ref"] = completed.model_execution_receipt
    provenance["review_item_id"] = str((review_item or {}).get("review_key") or "") if isinstance(review_item, dict) else None
    provenance["review_source_bindings"] = frozen_sources
    if isinstance(review_item, dict):
        provenance["prompt_package_sha256"] = review_item.get("prompt_package_sha256")
    if candidate_gate:
        return _apply_candidate_gate(
            ep,
            data=data,
            reviewed=current,
            contexts=contexts,
            provenance=provenance,
            attempt=attempt,
            review_scope=review_scope,
            review_item=review_item,
        )
    return _persist_candidate(
        ep,
        data=data,
        current=current,
        contexts=contexts,
        phashes=phashes,
        provenance=provenance,
        frozen_sources=frozen_sources,
        review_item=review_item,
    )


def run_critic(
    ep: Path, *, attempt: int, codex_raw: str | None, timeout: int | None = None,
    target_frames: list[int | str] | tuple[int | str, ...] | None = None,
    review_scope: str = "FULL_FRAME_SET",
    review_item: dict | None = None,
) -> int:
    """Run a full review or explicit non-promotable Phase5A scoped review."""
    episode_performance.safe_begin_review_span(ep, "FULL", attempt)
    try:
        result = _run_critic_uninstrumented(
            ep, attempt=attempt, codex_raw=codex_raw, timeout=timeout,
            target_frames=target_frames, review_scope=review_scope, review_item=review_item,
        )
    except BaseException as exc:
        episode_performance.safe_end_review_span(
            ep, "FULL", attempt, status="ERROR", metadata={"error_type": type(exc).__name__})
        raise
    # The product runtime completes asynchronously. Keep the same attempt span
    # open so its waiting interval is reported as HOST_WAIT by the state ledger.
    if result == product_review_adapter.HOST_ACTION_REQUIRED_RC:
        return result
    status = episode_performance.review_status_for_code(result)
    episode_performance.safe_end_review_span(ep, "FULL", attempt, status=status, metadata={"result_code": result})
    return result


def _parse_exception_frames(raw: str) -> list[str]:
    frames: list[str] = []
    for part in str(raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit():
            raise ValueError(f"invalid exception frame: {part!r}")
        key = f"{int(part):02d}"
        if key not in frames:
            frames.append(key)
    if not frames:
        raise ValueError("at least one exception frame is required")
    if len(frames) > 5:
        raise ValueError("exception semantic review is limited to at most 5 target frames")
    return sorted(frames)


def _exception_context_keys(all_keys: list[str], targets: list[str]) -> list[str]:
    nums = sorted(int(x) for x in all_keys)
    allowed = set(nums)
    total = max(nums) if nums else 0
    selected: set[int] = set()
    for raw in targets:
        n = int(raw)
        radius = 2 if n >= max(1, total - 2) else 1
        for value in range(n - radius, n + radius + 1):
            if value in allowed:
                selected.add(value)
    return [f"{x:02d}" for x in sorted(selected)]


def _exception_review_records(ep: Path, targets: list[str], *, require_files: bool = True) -> tuple[list[dict], list[str]]:
    ledger = production_ledger.load_authority(ep, default={}) or {}
    frames = ledger.get("frames") or {}
    all_keys = sorted(k for k in frames if str(k).isdigit())
    missing = [key for key in targets if key not in frames]
    if missing:
        raise ValueError(f"unknown exception review frames: {missing}")
    context_keys = _exception_context_keys(all_keys, targets)
    rows: list[dict] = []
    for key in context_keys:
        frame = frames.get(key) or {}
        status = str(frame.get("status") or "")
        is_target = key in targets
        if is_target:
            if status != "REPAIR_READY":
                raise ValueError(f"exception review target {key} requires REPAIR_READY, got {status}")
            if int(frame.get("content_repairs_used") or 0) != 1 or int(frame.get("user_exception_repairs_used") or 0) != 1:
                raise ValueError(f"exception review target {key} requires one ordinary and one direct-user exception repair")
            asset = frame.get("current_candidate")
            source_kind = "candidate"
        else:
            if status not in production_ledger.ACCEPTED_LEDGER_STATES:
                raise ValueError(f"exception review context {key} must already be approved/locked, got {status}")
            asset = frame.get("approved_asset")
            source_kind = "approved"
        if not isinstance(asset, dict):
            raise ValueError(f"exception review {source_kind} missing for frame {key}")
        raw_path = asset.get("path") or asset.get("asset_path")
        sha = str(asset.get("sha256") or "").lower()
        if len(sha) != 64:
            raise ValueError(f"exception review frame {key} sha256 invalid")
        path = repo_path(raw_path, f"exception review frame {key} {source_kind}", require_file=require_files)
        if require_files and sha256_file(path).lower() != sha:
            raise ValueError(f"exception review frame {key} asset SHA drift")
        rows.append({
            "frame": key,
            "path": path,
            "path_rel": repo_rel(path),
            "sha256": sha,
            "source_kind": source_kind,
            "ledger_status": status,
            "exception_target": is_target,
        })
    return rows, context_keys


def _exception_review_prompt(ep: Path, rows: list[dict], targets: list[str], candidate: Path) -> str:
    story, storyboard = episode_files(ep)
    version = episode_contract_version(ep)
    directing_v3 = directing_v3_required(ep)
    checks = checks_for_version(version, directing_v3)
    checks_block = ",\n".join(f'        "{name}": true' for name in checks)
    mapping = "\n".join(
        f"- {'TARGET' if row['exception_target'] else 'CONTEXT'} frame {row['frame']}: {row['path_rel']}"
        for row in rows
    )
    local_triage_block = _local_triage_prompt_block(ep, rows)
    return f"""You are a FRESH isolated final Production Frame Semantic Critic.
This is a DIRECT-USER-EXCEPTION re-review. Do NOT generate or edit images and do NOT trust earlier PASS/FAIL labels.
Only the TARGET frames may change Production Ledger state. CONTEXT frames are already locked and are supplied only to judge continuity.
Targets: {', '.join(targets)}.

Read these locked authorities before judging:
- {story.relative_to(ROOT).as_posix()}
- {storyboard.relative_to(ROOT).as_posix()}
- {(ep / 'meta/story-gates.json').relative_to(ROOT).as_posix()}
- standards/制作规范_正式版.md
- standards/生产帧语义强制规范_V1.0.md
- standards/Resolved_Frame_Contract规范_V1.0.md
Resolved Frame Contracts live at {runtime_workspace.workspace_path(ep, phase4_contract.CACHE_ROOT).as_posix()}/NN.json.

Attached mapping:
{mapping}

Local Visual Triage pre-scan (advisory only; never authoritative):
{local_triage_block}

Judge ACTUAL pixels against Story Lock, storyboard, Frame Contract, camera-authorship physics, world identity, continuity and anomaly readability.
PASS only when every required check is true and issue_codes is empty. Context rows must also remain valid; if a context row is inconsistent with a target, fail the relevant row rather than hiding the conflict.
Use issue codes only from: {', '.join(sorted(ISSUE_CODES))}

Write ONLY valid JSON to {candidate.relative_to(ROOT).as_posix()} with exactly one row for every attached frame:
{{
  "frames": [{{
    "frame": "01",
    "checks": {{
{checks_block}
    }},
    "issue_codes": [],
    "notes": "specific pixel-level evidence",
    "decision": "pass"
  }}],
  "issue_codes": [],
  "summary": {{"passed": true, "notes": "exception patch judgment"}}
}}
If any supplied row fails, set that row decision=fail and summary.passed=false.
"""


def _exception_pending_payload(ep: Path, rows: list[dict], targets: list[str]) -> dict:
    return {
        "schema_version": 1,
        "attempt": 3,
        "recorded_at": now(),
        "targets": targets,
        "contexts": context_hashes(ep),
        "assets": [{"frame": r["frame"], "path": r["path_rel"], "sha256": r["sha256"]} for r in rows],
    }


def _apply_exception_review(ep: Path, *, data: dict, rows: list[dict], targets: list[str], provenance: dict) -> int:
    version = episode_contract_version(ep)
    directing_v3 = directing_v3_required(ep)
    errors = validate_candidate_gate_rows(data.get("frames"), rows, version, directing_v3)
    codes = data.get("issue_codes")
    if not isinstance(codes, list):
        errors.append("global issue_codes must be list")
    elif any(code not in ISSUE_CODES for code in codes):
        errors.append(f"global issue_codes contain unknown values: {codes}")
    if errors:
        print("EXCEPTION FRAME SEMANTIC REVIEW INVALID")
        for error in errors:
            print("FAIL:", error)
        return 3

    by_key = {str(row.get("frame") or "").zfill(2): row for row in data.get("frames") or []}
    context_failures = [row["frame"] for row in rows if not row["exception_target"] and by_key[row["frame"]].get("decision") != "pass"]
    evidence = {
        "schema_version": 1,
        "attempt": 3,
        "review_scope": "DIRECT_USER_EXCEPTION_PATCH",
        "targets": targets,
        "critic_provenance": provenance,
        "reviewed_assets": [{"frame": r["frame"], "path": r["path_rel"], "sha256": r["sha256"]} for r in rows],
        "critic_result": data,
        "context_failures": context_failures,
        "recorded_at": now(),
    }
    write_json(ep / "meta/frame-semantic-exception-attempt-3.json", evidence)
    if context_failures:
        print("EXCEPTION FRAME SEMANTIC REVIEW FAIL: locked context failed=" + ",".join(context_failures))
        return 2

    contexts = context_hashes(ep)
    frozen = review_source_bindings(ep, rows)
    failures: list[str] = []
    for source in rows:
        key = source["frame"]
        if key not in targets:
            continue
        result = by_key[key]
        status = str(_ledger_frame(ep, key).get("status") or "")
        if status != "REPAIR_READY":
            raise RuntimeError(f"exception target {key} drifted from REPAIR_READY to {status}")
        note = "Direct-user exception semantic critic attempt 3: " + str(result.get("notes") or result.get("issue_codes") or "")
        if result.get("decision") == "pass":
            production_ledger.cmd_review(SimpleNamespace(
                episode_dir=str(ep), frame=key, decision="pass", notes=note[:500]))
            production_ledger.cmd_promote(SimpleNamespace(episode_dir=str(ep), frame=key))
            production_ledger.cmd_lock(SimpleNamespace(
                episode_dir=str(ep), frame=key, reason="direct-user exception semantic critic attempt 3 PASS"))
            locked = _ledger_frame(ep, key)
            approved = locked.get("approved_asset") or {}
            if str(approved.get("sha256") or "").lower() != source["sha256"].lower():
                raise RuntimeError(f"exception target {key} promotion changed reviewed pixels")
            bound = {
                "schema_version": SCHEMA_VERSION,
                "story_os_version": version,
                "frame": key,
                "asset_path": str(approved.get("path") or ""),
                "asset_sha256": str(approved.get("sha256") or "").lower(),
                **contexts,
                **phase3_context_hashes(ep, key),
                "source_binding": source_binding(ep, key),
                "critic_provenance": provenance,
                "checks": result.get("checks") or {},
                "issue_codes": result.get("issue_codes") or [],
                "notes": result.get("notes") or "",
                "decision": "pass",
            }
            frame_review_persistence.save(ep, bound)
        else:
            production_ledger.cmd_review(SimpleNamespace(
                episode_dir=str(ep), frame=key, decision="repair", notes=note[:500]))
            failures.append(key)

    evidence["failed_targets"] = failures
    evidence["completed_at"] = now()
    write_json(ep / "meta/frame-semantic-exception-attempt-3.json", evidence)
    if failures:
        print("EXCEPTION FRAME SEMANTIC REVIEW FAIL: targets=" + ",".join(failures))
        return 2
    print("EXCEPTION FRAME SEMANTIC REVIEW PASS: targets=" + ",".join(targets))
    return 0


def _review_instrumented(ep: Path, kind: str, attempt_number: int, lane: str | None,
                         metadata: dict, runner, **kwargs) -> int:
    """Run one review entry point with best-effort timing telemetry.

    Telemetry is fail-soft and never changes the review result or the episode
    state; a telemetry failure surfaces as no span rather than a raised error.
    """
    episode_performance.safe_begin_review_span(ep, kind, attempt_number, metadata=metadata, lane=lane)
    try:
        result = runner(ep, **kwargs)
    except BaseException as exc:
        episode_performance.safe_end_review_span(
            ep, kind, attempt_number, status="ERROR", lane=lane,
            metadata={"error_type": type(exc).__name__})
        raise
    episode_performance.safe_end_review_span(
        ep, kind, attempt_number, lane=lane,
        status=episode_performance.review_status_for_code(result),
        metadata={"result_code": result})
    return result


def run_exception_critic(ep: Path, *, targets: list[str], codex_raw: str | None, timeout: int | None = None) -> int:
    return _review_instrumented(
        ep, "PATCH", 3, "EXCEPTION",
        {"target_frame_count": len(targets), "shard_count": 1,
         "targets": [str(x).zfill(2) for x in targets]},
        _run_exception_critic_uninstrumented,
        targets=targets, codex_raw=codex_raw, timeout=timeout)


def _run_exception_critic_uninstrumented(ep: Path, *, targets: list[str], codex_raw: str | None, timeout: int | None = None) -> int:
    if timeout is None:
        timeout = runtime_timeout_policy.seconds("deep_semantic_review")
    rows, _ = _exception_review_records(ep, targets, require_files=True)
    binding_errors = reviewable_phase4_binding_errors(ep, rows)
    if binding_errors:
        for error in binding_errors:
            print("FAIL:", error)
        return 2
    candidate = ep / EXCEPTION_CANDIDATE_REL
    candidate.unlink(missing_ok=True)
    write_json(ep / EXCEPTION_PENDING_REL, _exception_pending_payload(ep, rows, targets))
    log = ep / "meta/frame-semantic-exception-critic-attempt-3.jsonl"
    completed = critic_runner.launch(
        _exception_review_prompt(ep, rows, targets, candidate),
        codex=resolve_codex(codex_raw),
        root=ROOT,
        timeout=timeout,
        sandbox="workspace-write",
        model=runtime_router.vision_review_model(),
        reasoning_effort=runtime_router.vision_review_effort("final"),
        attachments=[row["path"] for row in rows],
        log_path=log,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"isolated exception semantic critic failed rc={completed.returncode}; log={log}")
    if not candidate.is_file():
        raise RuntimeError(f"exception semantic critic did not produce {candidate}")
    current, _ = _exception_review_records(ep, targets, require_files=True)
    expected = [{"frame": r["frame"], "path": r["path_rel"], "sha256": r["sha256"]} for r in rows]
    actual = [{"frame": r["frame"], "path": r["path_rel"], "sha256": r["sha256"]} for r in current]
    if expected != actual:
        raise RuntimeError("exception semantic review assets drifted during review")
    provenance = runtime_provenance.build_critic_provenance(
        "CODEX", attempt=3, log=log.relative_to(ROOT).as_posix(), allow_user_exception_attempt=True)
    provenance["review_scope"] = "INCREMENTAL_CONTEXT_SET"
    provenance["anatomy_integrity_enforced"] = True
    provenance["direct_user_exception_frames"] = targets
    return _apply_exception_review(ep, data=read_json(candidate), rows=current, targets=targets, provenance=provenance)


def apply_exception_candidate(ep: Path) -> int:
    pending_path = ep / EXCEPTION_PENDING_REL
    candidate = ep / EXCEPTION_CANDIDATE_REL
    log = ep / "meta/frame-semantic-exception-critic-attempt-3.jsonl"
    if not pending_path.is_file() or not candidate.is_file():
        raise RuntimeError("exception semantic pending/candidate evidence missing")
    pending = read_json(pending_path)
    targets = [str(x).zfill(2) for x in (pending.get("targets") or [])]
    rows, _ = _exception_review_records(ep, targets, require_files=True)
    assets = [{"frame": r["frame"], "path": r["path_rel"], "sha256": r["sha256"]} for r in rows]
    if pending.get("assets") != assets:
        raise RuntimeError("exception semantic pending asset set drifted")
    if pending.get("contexts") != context_hashes(ep):
        raise RuntimeError("exception semantic Story/Storyboard/visual context drifted")
    binding_errors = reviewable_phase4_binding_errors(ep, rows)
    if binding_errors:
        raise RuntimeError("exception semantic Frame Contract drifted: " + "; ".join(binding_errors))
    log_rel = log.relative_to(ROOT).as_posix() if log.is_file() and log.stat().st_size > 0 else None
    provenance = runtime_provenance.build_critic_provenance(
        "CODEX", attempt=3, log=log_rel, allow_user_exception_attempt=True)
    provenance["review_scope"] = "INCREMENTAL_CONTEXT_SET"
    provenance["anatomy_integrity_enforced"] = True
    provenance["direct_user_exception_frames"] = targets
    provenance["recovered_after_parent_timeout"] = True
    provenance["candidate_sha256"] = sha256_file(candidate)
    if not log_rel:
        provenance["critic_stdout_log_empty_after_parent_timeout"] = True
    return _apply_exception_review(ep, data=read_json(candidate), rows=rows, targets=targets, provenance=provenance)


def _frame_current_capture_id(frame: dict) -> str:
    current = frame.get("current_candidate") if isinstance(frame, dict) else None
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


def _ordinary_patch_review_records(ep: Path, targets: list[str], *, require_files: bool = True) -> tuple[list[dict], list[str]]:
    """Return ordinary-repair targets plus locked continuity context.

    W-103: ordinary repair candidates are intentionally different from the
    direct-user exception/continuation lanes.  They may be reviewed as a bounded
    patch only while every non-target frame is still LOCKED.  Context frames are
    read-only review evidence; only targets may mutate the Production Ledger.
    """
    ledger = production_ledger.load_authority(ep, default={}) or {}
    frames = ledger.get("frames") or {}
    all_keys = sorted(k for k in frames if str(k).isdigit())
    missing = [key for key in targets if key not in frames]
    if missing:
        raise ValueError(f"unknown ordinary patch review frames: {missing}")
    if not targets:
        raise ValueError("ordinary patch review requires at least one target")
    if len(targets) / max(1, len(all_keys)) > 0.25:
        raise ValueError("ordinary patch review exceeds 25% dirty-frame limit")
    target_set = set(targets)
    for key in all_keys:
        if key in target_set:
            continue
        status = str((frames.get(key) or {}).get("status") or "")
        if status != "LOCKED":
            raise ValueError(f"ordinary patch sibling {key} must remain LOCKED, got {status}")

    context_keys = _exception_context_keys(all_keys, targets)
    rows: list[dict] = []
    for key in context_keys:
        frame = frames.get(key) or {}
        status = str(frame.get("status") or "")
        is_target = key in target_set
        if is_target:
            if status != "REPAIR_READY":
                raise ValueError(f"ordinary patch target {key} requires REPAIR_READY, got {status}")
            if int(frame.get("content_repairs_used") or 0) <= 0:
                raise ValueError(f"ordinary patch target {key} has not consumed its ordinary repair")
            capture_id = _frame_current_capture_id(frame)
            if capture_id.startswith("user-continuation-") or capture_id.startswith("user-exception-"):
                raise ValueError(f"ordinary patch target {key} belongs to a direct-user review lane")
            asset = frame.get("current_candidate")
            source_kind = "candidate"
        else:
            if status != "LOCKED":
                raise ValueError(f"ordinary patch context {key} must be LOCKED, got {status}")
            asset = frame.get("approved_asset")
            source_kind = "approved"
        if not isinstance(asset, dict):
            raise ValueError(f"ordinary patch {source_kind} missing for frame {key}")
        raw_path = asset.get("path") or asset.get("asset_path")
        sha = str(asset.get("sha256") or "").lower()
        if len(sha) != 64:
            raise ValueError(f"ordinary patch frame {key} sha256 invalid")
        path = repo_path(raw_path, f"ordinary patch frame {key} {source_kind}", require_file=require_files)
        if require_files and sha256_file(path).lower() != sha:
            raise ValueError(f"ordinary patch frame {key} asset SHA drift")
        rows.append({
            "frame": key,
            "path": path,
            "path_rel": repo_rel(path),
            "sha256": sha,
            "source_kind": source_kind,
            "ledger_status": status,
            "patch_target": is_target,
        })
    return rows, context_keys


def ordinary_patch_eligible(ep: Path, targets: list[str]) -> bool:
    """Fail-closed admission for W-103 candidate-aware incremental review."""
    targets = sorted({str(x).zfill(2) for x in targets if str(x)})
    try:
        rows, _ = _ordinary_patch_review_records(ep, targets, require_files=True)
        ledger = production_ledger.load_authority(ep, default={}) or {}
        frames = ledger.get("frames") or {}
        contexts = context_hashes(ep)
        version = episode_contract_version(ep)
        directing_v3 = directing_v3_required(ep)
        target_set = set(targets)
        # Reusing a locked sibling is allowed only when its previous critic
        # evidence is still bound to the current pixels and all semantic inputs.
        for key, frame in sorted(frames.items()):
            key = str(key).zfill(2)
            if key in target_set or not isinstance(frame, dict):
                continue
            approved = frame.get("approved_asset") or {}
            raw_path = approved.get("path") or approved.get("asset_path")
            sha = str(approved.get("sha256") or "").lower()
            path = repo_path(raw_path, f"ordinary patch sibling {key} approved_asset")
            record = {"frame": key, "path": path, "path_rel": repo_rel(path), "sha256": sha}
            review = frame_review_persistence.load(ep, int(key))
            if not isinstance(review, dict):
                return False
            if review.get("decision") != "pass" or review.get("issue_codes") not in ([], None):
                return False
            if validate_bound_review(
                review,
                frame=record,
                contexts=contexts,
                version=version,
                metadata_only=True,
                phase3_contexts=phase3_context_hashes(ep, key),
                directing_v3=directing_v3,
                ep=ep,
            ):
                return False
        # Candidate generation contract must also be current before spending a critic.
        if reviewable_phase4_binding_errors(ep, rows):
            return False
        return True
    except Exception:
        return False


def _ordinary_patch_prompt(ep: Path, rows: list[dict], targets: list[str], candidate: Path) -> str:
    story, storyboard = episode_files(ep)
    version = episode_contract_version(ep)
    directing_v3 = directing_v3_required(ep)
    checks = checks_for_version(version, directing_v3)
    checks_block = ",\n".join(f'        "{name}": true' for name in checks)
    mapping = "\n".join(
        f"- {'TARGET' if row['patch_target'] else 'CONTEXT'} frame {row['frame']}: {row['path_rel']}"
        for row in rows
    )
    local_triage_block = _local_triage_prompt_block(ep, rows)
    return f"""You are a FRESH isolated final Production Frame Semantic Critic.
This is a BOUNDED ORDINARY-REPAIR PATCH review. Do NOT generate or edit images and do NOT trust earlier labels.
Only TARGET frames may change Production Ledger state. CONTEXT frames are already LOCKED and are supplied only to judge continuity.
Targets: {', '.join(targets)}.

Read these locked authorities before judging:
- {story.relative_to(ROOT).as_posix()}
- {storyboard.relative_to(ROOT).as_posix()}
- {(ep / 'meta/story-gates.json').relative_to(ROOT).as_posix()}
- standards/制作规范_正式版.md
- standards/生产帧语义强制规范_V1.0.md
- standards/Resolved_Frame_Contract规范_V1.0.md

Attached mapping:
{mapping}

Local Visual Triage pre-scan (advisory only; never authoritative):
{local_triage_block}

Judge ACTUAL pixels against Story Lock, storyboard, Frame Contract, camera-authorship physics, world identity, continuity and anomaly readability.
PASS only when every required check is true and issue_codes is empty. A CONTEXT failure invalidates this patch review and must not be hidden.
Use issue codes only from: {', '.join(sorted(ISSUE_CODES))}

Write ONLY valid JSON to {candidate.relative_to(ROOT).as_posix()} with exactly one row for every attached frame:
{{
  "frames": [{{
    "frame": "01",
    "checks": {{
{checks_block}
    }},
    "issue_codes": [],
    "notes": "specific pixel-level evidence",
    "decision": "pass"
  }}],
  "issue_codes": [],
  "summary": {{"passed": true, "notes": "bounded ordinary repair patch judgment"}}
}}
If any supplied row fails, set that row decision=fail and summary.passed=false.
"""


def _ordinary_patch_pending_payload(ep: Path, rows: list[dict], targets: list[str], attempt: int) -> dict:
    return {
        "schema_version": 1,
        "attempt": attempt,
        "recorded_at": now(),
        "targets": targets,
        "contexts": context_hashes(ep),
        "assets": [{"frame": r["frame"], "path": r["path_rel"], "sha256": r["sha256"]} for r in rows],
    }


def _refresh_patch_summary(ep: Path, *, provenance: dict, targets: list[str], context_frames: list[str]) -> None:
    approved = frame_records(ep, require_files=True)
    phashes = perceptual_rows(approved)
    duplicates = duplicate_pairs(phashes)
    if duplicates:
        raise RuntimeError("ordinary patch produced a near-duplicate final set")
    contexts = context_hashes(ep)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "story_os_version": episode_contract_version(ep),
        **contexts,
        "critic_provenance": {
            **provenance,
            "review_scope": "BASELINE_PLUS_PATCHES",
            "dirty_roots": targets,
            "context_frames": context_frames,
        },
        "frames": [{"frame": row["frame"], "asset_sha256": row["sha256"]} for row in approved],
        "perceptual_hashes": phashes,
        "near_duplicate_pairs": [],
        "issue_codes": [],
        "critic_summary": {"passed": True, "notes": "baseline plus bounded ordinary repair patch"},
        "incremental_contract": {
            "version": 1,
            "mode": "candidate_patch",
            "dirty_roots": targets,
            "context_frames": context_frames,
        },
        "summary": {"passed": True},
    }
    write_json(ep / SUMMARY_REL, summary)
    _rebind_incremental_captions(ep)


def _apply_ordinary_patch_review(ep: Path, *, data: dict, rows: list[dict], targets: list[str], provenance: dict, attempt: int) -> int:
    version = episode_contract_version(ep)
    directing_v3 = directing_v3_required(ep)
    errors = validate_candidate_gate_rows(data.get("frames"), rows, version, directing_v3)
    codes = data.get("issue_codes")
    if not isinstance(codes, list):
        errors.append("global issue_codes must be list")
    elif any(code not in ISSUE_CODES for code in codes):
        errors.append(f"global issue_codes contain unknown values: {codes}")
    if errors:
        print("ORDINARY PATCH FRAME SEMANTIC REVIEW INVALID")
        for error in errors:
            print("FAIL:", error)
        return 3
    by_key = {str(row.get("frame") or "").zfill(2): row for row in data.get("frames") or []}
    context_failures = [
        row["frame"] for row in rows
        if not row["patch_target"] and by_key[row["frame"]].get("decision") != "pass"
    ]
    context_frames = [row["frame"] for row in rows]
    evidence = {
        "schema_version": 1,
        "attempt": attempt,
        "review_scope": "ORDINARY_REPAIR_PATCH",
        "targets": targets,
        "critic_provenance": provenance,
        "reviewed_assets": [{"frame": r["frame"], "path": r["path_rel"], "sha256": r["sha256"]} for r in rows],
        "critic_result": data,
        "context_failures": context_failures,
        "recorded_at": now(),
    }
    evidence_path = ep / "meta" / f"frame-semantic-patch-attempt-{attempt}.json"
    write_json(evidence_path, evidence)
    if context_failures:
        print("ORDINARY PATCH FRAME SEMANTIC REVIEW FAIL: locked context failed=" + ",".join(context_failures))
        return 2

    # Preflight all targets before any target mutation.  Failure transitions are
    # then applied first, preserving the W-71 single-writer closure rule.
    for key in targets:
        status = str(_ledger_frame(ep, key).get("status") or "")
        if status != "REPAIR_READY":
            raise RuntimeError(f"ordinary patch target {key} drifted from REPAIR_READY to {status}")
    failures = [key for key in targets if by_key[key].get("decision") != "pass"]
    for key in failures:
        result = by_key[key]
        note = "Ordinary repair patch semantic critic: " + str(result.get("notes") or result.get("issue_codes") or "")
        # Canonical Ledger transition: a REPAIR_READY candidate reviewed as
        # repair automatically becomes NEEDS_USER.  Do not bypass cmd_review
        # with the later-review escalation helper (it only accepts LOCKED/PASSED).
        production_ledger.cmd_review(SimpleNamespace(
            episode_dir=str(ep), frame=key, decision="repair", notes=note[:500]))

    contexts = context_hashes(ep) if len(failures) < len(targets) else {}
    for source in rows:
        key = source["frame"]
        if key not in targets or key in failures:
            continue
        result = by_key[key]
        note = "Ordinary repair patch semantic critic: " + str(result.get("notes") or "")
        production_ledger.cmd_review(SimpleNamespace(
            episode_dir=str(ep), frame=key, decision="pass", notes=note[:500]))
        production_ledger.cmd_promote(SimpleNamespace(episode_dir=str(ep), frame=key))
        production_ledger.cmd_lock(SimpleNamespace(
            episode_dir=str(ep), frame=key, reason=f"ordinary repair patch semantic critic attempt {attempt} PASS"))
        locked = _ledger_frame(ep, key)
        approved = locked.get("approved_asset") or {}
        if str(approved.get("sha256") or "").lower() != source["sha256"].lower():
            raise RuntimeError(f"ordinary patch target {key} promotion changed reviewed pixels")
        bound = {
            "schema_version": SCHEMA_VERSION,
            "story_os_version": version,
            "frame": key,
            "asset_path": str(approved.get("path") or ""),
            "asset_sha256": str(approved.get("sha256") or "").lower(),
            **contexts,
            **phase3_context_hashes(ep, key),
            "source_binding": source_binding(ep, key),
            "critic_provenance": provenance,
            "checks": result.get("checks") or {},
            "issue_codes": result.get("issue_codes") or [],
            "notes": result.get("notes") or "",
            "decision": "pass",
        }
        frame_review_persistence.save(ep, bound)

    evidence["failed_targets"] = failures
    evidence["completed_at"] = now()
    write_json(evidence_path, evidence)
    if failures:
        print("ORDINARY PATCH FRAME SEMANTIC REVIEW FAIL: targets=" + ",".join(failures))
        return 2
    _refresh_patch_summary(ep, provenance=provenance, targets=targets, context_frames=context_frames)
    verify_errors = verify_episode(ep, metadata_only=False, write_audit=True)
    if verify_errors:
        raise RuntimeError("ordinary patch final semantic verification failed: " + "; ".join(verify_errors))
    print("ORDINARY PATCH FRAME SEMANTIC REVIEW PASS: targets=" + ",".join(targets))
    return 0


def run_patch_critic(ep: Path, *, targets: list[str], attempt: int, codex_raw: str | None, timeout: int | None = None) -> int:
    return _review_instrumented(
        ep, "PATCH", attempt, "FINAL_PATCH",
        {"target_frame_count": len(targets), "shard_count": 1,
         "targets": [str(x).zfill(2) for x in targets]},
        _run_patch_critic_uninstrumented,
        targets=targets, attempt=attempt, codex_raw=codex_raw, timeout=timeout)


def _run_patch_critic_uninstrumented(ep: Path, *, targets: list[str], attempt: int, codex_raw: str | None, timeout: int | None = None) -> int:
    if timeout is None:
        timeout = runtime_timeout_policy.seconds("deep_semantic_review")
    targets = sorted({str(x).zfill(2) for x in targets if str(x)})
    if not ordinary_patch_eligible(ep, targets):
        raise RuntimeError("ordinary patch eligibility failed; use full final semantic review")
    rows, _ = _ordinary_patch_review_records(ep, targets, require_files=True)
    # Far-away duplicates are still a set-level invariant even though the critic
    # sees only local continuity context.
    all_rows = reviewable_frame_records(ep, require_files=True)
    if duplicate_pairs(perceptual_rows(all_rows)):
        print("ORDINARY PATCH FRAME SEMANTIC REVIEW FAIL: NEAR_DUPLICATE_ACTUAL_FRAMES")
        return 2
    candidate = ep / PATCH_CANDIDATE_REL
    candidate.unlink(missing_ok=True)
    write_json(ep / PATCH_PENDING_REL, _ordinary_patch_pending_payload(ep, rows, targets, attempt))
    before = [{"frame": r["frame"], "path": r["path_rel"], "sha256": r["sha256"]} for r in rows]
    log = ep / "meta" / f"frame-semantic-patch-critic-attempt-{attempt}.jsonl"
    completed = critic_runner.launch(
        _ordinary_patch_prompt(ep, rows, targets, candidate),
        codex=resolve_codex(codex_raw),
        root=ROOT,
        timeout=timeout,
        sandbox="workspace-write",
        model=runtime_router.vision_review_model(),
        reasoning_effort=runtime_router.vision_review_effort("final"),
        attachments=[row["path"] for row in rows],
        log_path=log,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"isolated ordinary patch semantic critic failed rc={completed.returncode}; log={log}")
    if not candidate.is_file():
        raise RuntimeError(f"ordinary patch semantic critic did not produce {candidate}")
    current, _ = _ordinary_patch_review_records(ep, targets, require_files=True)
    after = [{"frame": r["frame"], "path": r["path_rel"], "sha256": r["sha256"]} for r in current]
    if before != after:
        raise RuntimeError("ordinary patch semantic review assets drifted during review")
    provenance = runtime_provenance.build_vision_critic_provenance(
        attempt=attempt, log=log.relative_to(ROOT).as_posix(), review_scope="INCREMENTAL_CONTEXT_SET")
    provenance["anatomy_integrity_enforced"] = True
    provenance["ordinary_repair_patch_frames"] = targets
    return _apply_ordinary_patch_review(
        ep, data=read_json(candidate), rows=current, targets=targets, provenance=provenance, attempt=attempt)


def _continuation_review_records(ep: Path, targets: list[str], *, require_files: bool = True) -> tuple[list[dict], int]:
    ledger = production_ledger.load_authority(ep, default={}) or {}
    frames = ledger.get("frames") or {}
    all_keys = sorted(k for k in frames if str(k).isdigit())
    missing = [key for key in targets if key not in frames]
    if missing:
        raise ValueError(f"unknown continuation review frames: {missing}")
    context_keys = _exception_context_keys(all_keys, targets)
    rows: list[dict] = []
    target_indices: list[int] = []
    for key in context_keys:
        frame = frames.get(key) or {}
        status = str(frame.get("status") or "")
        is_target = key in targets
        continuation_index = 0
        if is_target:
            if status != "REPAIR_READY":
                raise ValueError(f"continuation review target {key} requires REPAIR_READY, got {status}")
            continuation_index = int(frame.get("user_continuation_repairs_used") or 0)
            if continuation_index <= 0:
                raise ValueError(f"continuation review target {key} has no consumed user continuation candidate")
            capture_id = _frame_current_capture_id(frame)
            if not capture_id.startswith("user-continuation-"):
                raise ValueError(f"continuation review target {key} current candidate is not user-continuation provenance")
            authorizations = [row for row in (frame.get("user_continuation_authorizations") or []) if isinstance(row, dict)]
            if not any(
                int(row.get("continuation_index") or 0) == continuation_index
                and row.get("user_approved") is True
                and str(row.get("approval_text") or "").strip()
                for row in authorizations
            ):
                raise ValueError(f"continuation review target {key} lacks matching direct-user continuation authorization")
            asset = frame.get("current_candidate")
            source_kind = "candidate"
            target_indices.append(continuation_index)
        else:
            if status not in production_ledger.ACCEPTED_LEDGER_STATES:
                raise ValueError(f"continuation review context {key} must already be approved/locked, got {status}")
            asset = frame.get("approved_asset")
            source_kind = "approved"
        if not isinstance(asset, dict):
            raise ValueError(f"continuation review {source_kind} missing for frame {key}")
        raw_path = asset.get("path") or asset.get("asset_path")
        sha = str(asset.get("sha256") or "").lower()
        if len(sha) != 64:
            raise ValueError(f"continuation review frame {key} sha256 invalid")
        path = repo_path(raw_path, f"continuation review frame {key} {source_kind}", require_file=require_files)
        if require_files and sha256_file(path).lower() != sha:
            raise ValueError(f"continuation review frame {key} asset SHA drift")
        rows.append({
            "frame": key,
            "path": path,
            "path_rel": repo_rel(path),
            "sha256": sha,
            "source_kind": source_kind,
            "ledger_status": status,
            "continuation_target": is_target,
            "continuation_index": continuation_index,
        })
    if not target_indices:
        raise ValueError("continuation review has no target continuation index")
    return rows, 3 + max(target_indices)


def _continuation_review_prompt(ep: Path, rows: list[dict], targets: list[str], candidate: Path) -> str:
    story, storyboard = episode_files(ep)
    version = episode_contract_version(ep)
    directing_v3 = directing_v3_required(ep)
    checks = checks_for_version(version, directing_v3)
    checks_block = ",\n".join(f'        "{name}": true' for name in checks)
    mapping = "\n".join(
        f"- {'TARGET' if row['continuation_target'] else 'CONTEXT'} frame {row['frame']}: {row['path_rel']}"
        for row in rows
    )
    return f"""You are a FRESH isolated final Production Frame Semantic Critic.
This is a DIRECT-USER-CONTINUATION re-review of newly generated pixels. Do NOT generate or edit images and do NOT trust earlier PASS/FAIL labels.
Only TARGET frames may change Production Ledger state. CONTEXT frames are already locked and are supplied only to judge continuity.
Targets: {', '.join(targets)}.

Read these locked authorities before judging:
- {story.relative_to(ROOT).as_posix()}
- {storyboard.relative_to(ROOT).as_posix()}
- {(ep / 'meta/story-gates.json').relative_to(ROOT).as_posix()}
- standards/制作规范_正式版.md
- standards/生产帧语义强制规范_V1.0.md
- standards/Resolved_Frame_Contract规范_V1.0.md
Resolved Frame Contracts live at {runtime_workspace.workspace_path(ep, phase4_contract.CACHE_ROOT).as_posix()}/NN.json.

Attached mapping:
{mapping}

Judge ACTUAL pixels against Story Lock, storyboard, Frame Contract, camera-authorship physics, world identity, continuity and anomaly readability.
PASS only when every required check is true and issue_codes is empty. Context rows must also remain valid; if a context row is inconsistent with a target, fail the relevant row rather than hiding the conflict.
Use issue codes only from: {', '.join(sorted(ISSUE_CODES))}

Write ONLY valid JSON to {candidate.relative_to(ROOT).as_posix()} with exactly one row for every attached frame:
{{
  "frames": [{{
    "frame": "01",
    "checks": {{
{checks_block}
    }},
    "issue_codes": [],
    "notes": "specific pixel-level evidence",
    "decision": "pass"
  }}],
  "issue_codes": [],
  "summary": {{"passed": true, "notes": "continuation patch judgment"}}
}}
If any supplied row fails, set that row decision=fail and summary.passed=false.
"""


def _continuation_pending_payload(ep: Path, rows: list[dict], targets: list[str], attempt: int) -> dict:
    return {
        "schema_version": 1,
        "attempt": attempt,
        "recorded_at": now(),
        "targets": targets,
        "contexts": context_hashes(ep),
        "assets": [{"frame": r["frame"], "path": r["path_rel"], "sha256": r["sha256"]} for r in rows],
    }


def _apply_continuation_review(ep: Path, *, data: dict, rows: list[dict], targets: list[str], provenance: dict, attempt: int) -> int:
    version = episode_contract_version(ep)
    directing_v3 = directing_v3_required(ep)
    errors = validate_candidate_gate_rows(data.get("frames"), rows, version, directing_v3)
    codes = data.get("issue_codes")
    if not isinstance(codes, list):
        errors.append("global issue_codes must be list")
    elif any(code not in ISSUE_CODES for code in codes):
        errors.append(f"global issue_codes contain unknown values: {codes}")
    if errors:
        print("CONTINUATION FRAME SEMANTIC REVIEW INVALID")
        for error in errors:
            print("FAIL:", error)
        return 3

    by_key = {str(row.get("frame") or "").zfill(2): row for row in data.get("frames") or []}
    context_failures = [row["frame"] for row in rows if not row["continuation_target"] and by_key[row["frame"]].get("decision") != "pass"]
    evidence_path = ep / "meta" / f"frame-semantic-continuation-attempt-{attempt}.json"
    evidence = {
        "schema_version": 1,
        "attempt": attempt,
        "review_scope": "DIRECT_USER_CONTINUATION_PATCH",
        "targets": targets,
        "critic_provenance": provenance,
        "reviewed_assets": [{"frame": r["frame"], "path": r["path_rel"], "sha256": r["sha256"]} for r in rows],
        "critic_result": data,
        "context_failures": context_failures,
        "recorded_at": now(),
    }
    write_json(evidence_path, evidence)
    if context_failures:
        print("CONTINUATION FRAME SEMANTIC REVIEW FAIL: locked context failed=" + ",".join(context_failures))
        return 2

    contexts = context_hashes(ep)
    failures: list[str] = []
    for source in rows:
        key = source["frame"]
        if key not in targets:
            continue
        result = by_key[key]
        status = str(_ledger_frame(ep, key).get("status") or "")
        if status != "REPAIR_READY":
            raise RuntimeError(f"continuation target {key} drifted from REPAIR_READY to {status}")
        note = f"Direct-user continuation semantic critic attempt {attempt}: " + str(result.get("notes") or result.get("issue_codes") or "")
        if result.get("decision") == "pass":
            production_ledger.cmd_review(SimpleNamespace(
                episode_dir=str(ep), frame=key, decision="pass", notes=note[:500]))
            production_ledger.cmd_promote(SimpleNamespace(episode_dir=str(ep), frame=key))
            production_ledger.cmd_lock(SimpleNamespace(
                episode_dir=str(ep), frame=key, reason=f"direct-user continuation semantic critic attempt {attempt} PASS"))
            locked = _ledger_frame(ep, key)
            approved = locked.get("approved_asset") or {}
            if str(approved.get("sha256") or "").lower() != source["sha256"].lower():
                raise RuntimeError(f"continuation target {key} promotion changed reviewed pixels")
            bound = {
                "schema_version": SCHEMA_VERSION,
                "story_os_version": version,
                "frame": key,
                "asset_path": str(approved.get("path") or ""),
                "asset_sha256": str(approved.get("sha256") or "").lower(),
                **contexts,
                **phase3_context_hashes(ep, key),
                "source_binding": source_binding(ep, key),
                "critic_provenance": provenance,
                "checks": result.get("checks") or {},
                "issue_codes": result.get("issue_codes") or [],
                "notes": result.get("notes") or "",
                "decision": "pass",
            }
            frame_review_persistence.save(ep, bound)
        else:
            production_ledger.cmd_review(SimpleNamespace(
                episode_dir=str(ep), frame=key, decision="repair", notes=note[:500]))
            failures.append(key)

    evidence["failed_targets"] = failures
    evidence["completed_at"] = now()
    write_json(evidence_path, evidence)
    if failures:
        print("CONTINUATION FRAME SEMANTIC REVIEW FAIL: targets=" + ",".join(failures))
        return 2
    print("CONTINUATION FRAME SEMANTIC REVIEW PASS: targets=" + ",".join(targets))
    return 0


def run_continuation_critic(ep: Path, *, targets: list[str], codex_raw: str | None, timeout: int | None = None) -> int:
    """Run a continuation review, timing it once its attempt number is known."""
    state: dict = {"attempt": None}

    def note(attempt: int, frame_count: int) -> None:
        state["attempt"] = int(attempt)
        episode_performance.safe_begin_review_span(
            ep, "PATCH", attempt, lane="CONTINUATION",
            metadata={"target_frame_count": len(targets), "review_frame_count": frame_count,
                      "shard_count": 1, "targets": [str(x).zfill(2) for x in targets]})

    try:
        result = _run_continuation_critic_uninstrumented(
            ep, targets=targets, codex_raw=codex_raw, timeout=timeout, on_attempt=note)
    except BaseException as exc:
        if state["attempt"] is not None:
            episode_performance.safe_end_review_span(
                ep, "PATCH", state["attempt"], status="ERROR", lane="CONTINUATION",
                metadata={"error_type": type(exc).__name__})
        raise
    if state["attempt"] is not None:
        episode_performance.safe_end_review_span(
            ep, "PATCH", state["attempt"], lane="CONTINUATION",
            status=episode_performance.review_status_for_code(result),
            metadata={"result_code": result})
    return result


def _run_continuation_critic_uninstrumented(
    ep: Path, *, targets: list[str], codex_raw: str | None, timeout: int | None = None,
    on_attempt=None,
) -> int:
    if timeout is None:
        timeout = runtime_timeout_policy.seconds("deep_semantic_review")
    rows, attempt = _continuation_review_records(ep, targets, require_files=True)
    if on_attempt is not None:
        on_attempt(int(attempt), len(rows))
    binding_errors = reviewable_phase4_binding_errors(ep, rows)
    if binding_errors:
        for error in binding_errors:
            print("FAIL:", error)
        return 2
    candidate = ep / CONTINUATION_CANDIDATE_REL
    candidate.unlink(missing_ok=True)
    write_json(ep / CONTINUATION_PENDING_REL, _continuation_pending_payload(ep, rows, targets, attempt))
    log = ep / "meta" / f"frame-semantic-continuation-critic-attempt-{attempt}.jsonl"
    completed = critic_runner.launch(
        _continuation_review_prompt(ep, rows, targets, candidate),
        codex=resolve_codex(codex_raw),
        root=ROOT,
        timeout=timeout,
        sandbox="workspace-write",
        model=runtime_router.vision_review_model(),
        reasoning_effort=runtime_router.vision_review_effort("final"),
        attachments=[row["path"] for row in rows],
        log_path=log,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"isolated continuation semantic critic failed rc={completed.returncode}; log={log}")
    if not candidate.is_file():
        raise RuntimeError(f"continuation semantic critic did not produce {candidate}")
    current, current_attempt = _continuation_review_records(ep, targets, require_files=True)
    if current_attempt != attempt:
        raise RuntimeError("continuation semantic review attempt drifted during review")
    expected = [{"frame": r["frame"], "path": r["path_rel"], "sha256": r["sha256"]} for r in rows]
    actual = [{"frame": r["frame"], "path": r["path_rel"], "sha256": r["sha256"]} for r in current]
    if expected != actual:
        raise RuntimeError("continuation semantic review assets drifted during review")
    provenance = runtime_provenance.build_critic_provenance(
        "CODEX", attempt=attempt, log=log.relative_to(ROOT).as_posix(), allow_user_continuation_attempt=True)
    provenance["review_scope"] = "INCREMENTAL_CONTEXT_SET"
    provenance["anatomy_integrity_enforced"] = True
    provenance["direct_user_continuation_frames"] = targets
    return _apply_continuation_review(
        ep, data=read_json(candidate), rows=current, targets=targets, provenance=provenance, attempt=attempt)


def apply_continuation_candidate(ep: Path) -> int:
    pending_path = ep / CONTINUATION_PENDING_REL
    candidate = ep / CONTINUATION_CANDIDATE_REL
    if not pending_path.is_file() or not candidate.is_file():
        raise RuntimeError("continuation semantic pending/candidate evidence missing")
    pending = read_json(pending_path)
    targets = [str(x).zfill(2) for x in (pending.get("targets") or [])]
    rows, attempt = _continuation_review_records(ep, targets, require_files=True)
    if int(pending.get("attempt") or 0) != attempt:
        raise RuntimeError("continuation semantic pending attempt drifted")
    assets = [{"frame": r["frame"], "path": r["path_rel"], "sha256": r["sha256"]} for r in rows]
    if pending.get("assets") != assets:
        raise RuntimeError("continuation semantic pending asset set drifted")
    if pending.get("contexts") != context_hashes(ep):
        raise RuntimeError("continuation semantic Story/Storyboard/visual context drifted")
    binding_errors = reviewable_phase4_binding_errors(ep, rows)
    if binding_errors:
        raise RuntimeError("continuation semantic Frame Contract drifted: " + "; ".join(binding_errors))
    log = ep / "meta" / f"frame-semantic-continuation-critic-attempt-{attempt}.jsonl"
    log_rel = log.relative_to(ROOT).as_posix() if log.is_file() and log.stat().st_size > 0 else None
    provenance = runtime_provenance.build_critic_provenance(
        "CODEX", attempt=attempt, log=log_rel, allow_user_continuation_attempt=True)
    provenance["review_scope"] = "INCREMENTAL_CONTEXT_SET"
    provenance["anatomy_integrity_enforced"] = True
    provenance["direct_user_continuation_frames"] = targets
    provenance["recovered_after_parent_timeout"] = True
    provenance["candidate_sha256"] = sha256_file(candidate)
    if not log_rel:
        provenance["critic_stdout_log_empty_after_parent_timeout"] = True
    return _apply_continuation_review(
        ep, data=read_json(candidate), rows=rows, targets=targets, provenance=provenance, attempt=attempt)


def self_test() -> None:
    h = "a" * 64
    contexts = {
        "story_sha256": "b" * 64,
        "storyboard_sha256": "c" * 64,
        "visual_contract_sha256": "d" * 64,
    }
    frame = {"frame": "01", "path_rel": "episodes/x/production/approved/01.png", "sha256": h, "path": Path("/tmp/no-file")}
    payload = {
        "schema_version": SCHEMA_VERSION,
        "story_os_version": story_os_version(),
        "frame": "01",
        "asset_path": frame["path_rel"],
        "asset_sha256": h,
        **contexts,
        "critic_provenance": {"runtime": "CODEX_ISOLATED", "isolated_session": True, "review_scope": "FULL_FRAME_SET", "attempt": 1},
        "checks": {key: True for key in checks_for_version(story_os_version())},
        "issue_codes": [],
        "decision": "pass",
        "source_binding": {},
    }
    assert validate_bound_review(payload, frame=frame, contexts=contexts, version=story_os_version(), metadata_only=True) == []
    payload["asset_sha256"] = "e" * 64
    assert any("asset_sha256" in x for x in validate_bound_review(payload, frame=frame, contexts=contexts, version=story_os_version(), metadata_only=True))
    candidate = [{"frame": "01", "checks": {key: True for key in checks_for_version(story_os_version())}, "issue_codes": [], "decision": "pass"}]
    assert validate_candidate_rows(candidate, [frame]) == []
    candidate[0]["checks"]["temporal_continuity"] = False
    assert validate_candidate_rows(candidate, [frame])
    assert hamming_hex("0" * 64, "0" * 64) == 0
    print("FRAME SEMANTIC REVIEW SELF-TEST PASS")


def main() -> int:
    ap = argparse.ArgumentParser(description="Story OS V2.0.3.3 actual-frame semantic fidelity critic")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run-critic")
    p.add_argument("episode_dir")
    p.add_argument("--attempt", type=int, default=1)
    p.add_argument("--codex")
    p.add_argument("--timeout", type=int, default=None)
    p = sub.add_parser("apply-candidate")
    p.add_argument("episode_dir")
    p.add_argument("--attempt", type=int, default=1)
    p = sub.add_parser("continuation-review")
    p.add_argument("episode_dir")
    p.add_argument("--frames", required=True, help="comma-separated direct-user-continuation target frames")
    p.add_argument("--codex")
    p.add_argument("--timeout", type=int, default=None)
    p = sub.add_parser("apply-continuation-candidate")
    p.add_argument("episode_dir")
    p = sub.add_parser("exception-review")
    p.add_argument("episode_dir")
    p.add_argument("--frames", required=True, help="comma-separated direct-user-exception target frames")
    p.add_argument("--codex")
    p.add_argument("--timeout", type=int, default=None)
    p = sub.add_parser("apply-exception-candidate")
    p.add_argument("episode_dir")
    p = sub.add_parser("finalize-review")
    p.add_argument("episode_dir")
    p.add_argument("--attempt", type=int, default=1)
    p.add_argument("--runtime", choices=["WORK", "WEB"], default="WORK")
    p = sub.add_parser("verify")
    p.add_argument("episode_dir")
    p.add_argument("--metadata-only", action="store_true")
    p = sub.add_parser("audit")
    p.add_argument("episode_dir")
    p = sub.add_parser("show")
    p.add_argument("episode_dir")
    sub.add_parser("self-test")
    args = ap.parse_args()

    if args.cmd == "self-test":
        self_test()
        return 0
    ep = Path(args.episode_dir).resolve()
    if not ep.is_dir():
        raise SystemExit(f"episode directory not found: {ep}")
    if args.cmd == "run-critic":
        try:
            return run_critic(ep, attempt=args.attempt, codex_raw=args.codex, timeout=args.timeout)
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
            print("FRAME SEMANTIC REVIEW ERROR:", exc)
            return 3
    if args.cmd == "apply-candidate":
        try:
            return apply_pending_candidate(ep, attempt=args.attempt)
        except (OSError, RuntimeError, ValueError) as exc:
            print("FRAME SEMANTIC RECOVERY ERROR:", exc)
            return 3
    if args.cmd == "continuation-review":
        try:
            return run_continuation_critic(
                ep, targets=_parse_exception_frames(args.frames), codex_raw=args.codex, timeout=args.timeout)
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
            print("CONTINUATION FRAME SEMANTIC REVIEW ERROR:", exc)
            return 3
    if args.cmd == "apply-continuation-candidate":
        try:
            return apply_continuation_candidate(ep)
        except (OSError, RuntimeError, ValueError) as exc:
            print("CONTINUATION FRAME SEMANTIC RECOVERY ERROR:", exc)
            return 3
    if args.cmd == "exception-review":
        try:
            return run_exception_critic(
                ep, targets=_parse_exception_frames(args.frames), codex_raw=args.codex, timeout=args.timeout)
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
            print("EXCEPTION FRAME SEMANTIC REVIEW ERROR:", exc)
            return 3
    if args.cmd == "apply-exception-candidate":
        try:
            return apply_exception_candidate(ep)
        except (OSError, RuntimeError, ValueError) as exc:
            print("EXCEPTION FRAME SEMANTIC RECOVERY ERROR:", exc)
            return 3
    if args.cmd == "finalize-review":
        try:
            return finalize_product_review(ep, attempt=args.attempt, runtime=args.runtime)
        except (OSError, RuntimeError, ValueError) as exc:
            print("FRAME SEMANTIC REVIEW FINALIZE ERROR:", exc)
            return 3
    if args.cmd == "show":
        p = ep / SUMMARY_REL
        print(p.read_text(encoding="utf-8") if p.is_file() else "NO FRAME SEMANTIC REVIEW")
        return 0
    errors = verify_episode(ep, metadata_only=(args.cmd == "verify" and args.metadata_only), write_audit=(args.cmd == "audit"))
    if errors:
        for error in errors:
            print("FAIL:", error)
        return 2
    print("FRAME SEMANTIC REVIEW VERIFY PASS" if args.cmd == "verify" else "FRAME SEMANTIC AUDIT PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
