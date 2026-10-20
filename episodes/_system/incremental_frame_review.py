#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

import codex_critic_runner as critic_runner
import frame_semantic_review as base
import frame_review_persistence
# STORY_OS_V22_VISUAL_NARRATIVE_CORE
from story_os_contract import story_os_version
import final_acceptance
import production_ledger
import runtime_router
import runtime_provenance
import story_json
import runtime_timeout_policy
import visual_reality_score
import episode_performance
import verified_review_authority

ROOT = Path(__file__).resolve().parents[2]
STATE_REL = Path("meta/incremental-frame-review.json")
AUDIT_REL = Path("meta/incremental-frame-audit.json")
CANDIDATE_REL = Path("meta/.incremental-frame-review.candidate.json")
TARGET = (2, 0, 3, 4)


def now() -> str:
    return base.now()


def read_json(path: Path) -> dict:
    return story_json.read_json(path)


def write_json(path: Path, data: dict) -> None:
    story_json.write_json(path, data)


def version_tuple(raw: object) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in str(raw or "").split("."))
    except ValueError:
        return (0,)


def review_required(ep: Path) -> bool:
    return base.review_required(ep)


def _sha_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _repo_rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def _manifest_caption_path(ep: Path) -> Path | None:
    manifest_path = ep / "meta/release-manifest.json"
    if manifest_path.is_file():
        try:
            manifest = read_json(manifest_path)
            artifacts = manifest.get("artifacts") or {}
            for key in ("captions", "subtitles", "caption_source", "subtitle_source"):
                raw = artifacts.get(key)
                if isinstance(raw, str) and raw.strip():
                    p = Path(raw)
                    p = p.resolve() if p.is_absolute() else (ROOT / p).resolve()
                    if p.is_file():
                        return p
        except Exception:
            pass
    for rel in (
        "text/subtitles.yaml", "text/subtitles.yml", "text/captions.yaml", "text/captions.yml",
        "text/subtitles.json", "text/captions.json", "subtitles.yaml", "captions.yaml",
    ):
        p = ep / rel
        if p.is_file():
            return p
    return None


def _extract_json_captions(data: object) -> dict[str, str]:
    out: dict[str, str] = {}
    if isinstance(data, dict):
        for key in ("captions", "subtitles", "frames"):
            nested = data.get(key)
            if nested is not None:
                found = _extract_json_captions(nested)
                if found:
                    return found
        for k, v in data.items():
            ks = str(k).strip().zfill(2) if str(k).strip().isdigit() else ""
            if ks and len(ks) == 2:
                if isinstance(v, str):
                    out[ks] = v
                elif isinstance(v, dict):
                    text = v.get("text") or v.get("caption") or v.get("subtitle")
                    if isinstance(text, str):
                        out[ks] = text
    elif isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            raw = item.get("frame") or item.get("number") or item.get("id")
            if str(raw).isdigit():
                text = item.get("text") or item.get("caption") or item.get("subtitle")
                if isinstance(text, str):
                    out[str(int(raw)).zfill(2)] = text
    return out


def _extract_yaml_captions(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    current: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        m = re.match(r"^\s*['\"]?(\d{1,2})['\"]?\s*:\s*(.*?)\s*$", line)
        if m:
            key = str(int(m.group(1))).zfill(2)
            val = m.group(2).strip().strip("'\"")
            if val and val not in {"|", ">", "{}", "[]"}:
                out[key] = val
            current = key
            continue
        m = re.match(r"^\s*-?\s*frame\s*:\s*['\"]?(\d{1,2})['\"]?\s*$", line, re.I)
        if m:
            current = str(int(m.group(1))).zfill(2)
            continue
        if current:
            m = re.match(r"^\s*(?:text|caption|subtitle)\s*:\s*(.*?)\s*$", line, re.I)
            if m:
                out[current] = m.group(1).strip().strip("'\"")
                current = None
    return out


def caption_state(ep: Path, frames: list[dict]) -> dict:
    source = _manifest_caption_path(ep)
    frame_keys = [row["frame"] for row in frames]
    if source is None:
        empty = _sha_text("")
        return {
            "source_path": None,
            "source_sha256": empty,
            "mode": "none",
            "frame_sha256": {key: empty for key in frame_keys},
        }
    raw = source.read_text(encoding="utf-8", errors="replace")
    source_sha = _sha_text(raw)
    captions: dict[str, str] = {}
    if source.suffix.lower() == ".json":
        try:
            captions = _extract_json_captions(json.loads(raw))
        except Exception:
            captions = {}
    else:
        captions = _extract_yaml_captions(raw)
    if captions:
        hashes = {key: _sha_text(captions.get(key, "")) for key in frame_keys}
        mode = "per_frame"
    else:
        # Safe fallback: if parser cannot split the file, any caption edit invalidates every frame.
        hashes = {key: source_sha for key in frame_keys}
        mode = "whole_source_fallback"
    return {
        "source_path": _repo_rel(source),
        "source_sha256": source_sha,
        "mode": mode,
        "frame_sha256": hashes,
    }


def _review_path(ep: Path, frame: str) -> Path:
    return ep / base.REVIEW_DIR / f"{frame}.json"


def _review_data(ep: Path, frame: str) -> dict | None:
    # Frame Review Authority may be MySQL-backed. Never infer "missing review"
    # from the absence of the legacy filesystem projection.
    try:
        value = frame_review_persistence.load(Path(ep).resolve(), int(frame))
    except Exception:
        return None
    return value if isinstance(value, dict) else None


def _context_match(data: dict, contexts: dict) -> bool:
    return all(str(data.get(k) or "").lower() == str(v).lower() for k, v in contexts.items())


def _binding_match(data: dict, ep: Path, frame: str) -> bool:
    expected = base.source_binding(ep, frame)
    if not expected:
        return True
    return data.get("source_binding") == expected


def _phase5a_scoped_evidence_allowed(ep: Path, data: dict | None = None) -> bool:
    marker = Path(ep) / "meta" / "phase5a-canary.json"
    if not marker.is_file():
        return False
    try:
        value = read_json(marker)
    except Exception:
        return False
    provenance = (data or {}).get("critic_provenance") or {}
    return (
        isinstance(value, dict)
        and value.get("workspace_class") == "TEST_ONLY"
        and value.get("promotion_class") == "NON_PROMOTABLE"
        and value.get("canary_type") == "PHASE5A_COLLABORATIVE_REGRESSION"
        and provenance.get("review_scope") == base.PHASE5A_SINGLE_FRAME_SCOPE
    )


def _expected_review_fingerprint(ep: Path, data: dict, frame: dict,
                                 contexts: dict, phase3: dict,
                                 policy_sha256: str | None) -> str | None:
    identity = {
        "logical_asset_key": frame.get("logical_asset_key"),
        "generation_key": frame.get("generation_key"),
        "sha256": frame.get("sha256"),
        "source_binding": base.source_binding(ep, frame["frame"]),
    }
    provenance = data.get("critic_provenance") or {}
    if _phase5a_scoped_evidence_allowed(ep, data):
        return base.review_evidence_fingerprint(
            identity, contexts=contexts, phase3_contexts=phase3,
            policy_sha256=policy_sha256,
            review_item_id=str(data.get("review_item_id") or ""),
            attempt_index=int(data.get("attempt_index") or 0),
            frame_contract_sha256=phase3.get("frame_contract_sha256"),
            prompt_package_sha256=str(provenance.get("prompt_package_sha256") or ""),
        )
    return base.frame_evidence_fingerprint(
        identity, contexts=contexts, phase3_contexts=phase3,
        policy_sha256=policy_sha256)


def _scope_ok(data: dict, ep: Path | None = None) -> bool:
    p = data.get("critic_provenance") or {}
    if runtime_provenance.validate_critic_provenance(p):
        return False
    scope = p.get("review_scope")
    if scope in {"FULL_FRAME_SET", "INCREMENTAL_CONTEXT_SET"}:
        return True
    return bool(ep is not None and scope == base.PHASE5A_SINGLE_FRAME_SCOPE
                and _phase5a_scoped_evidence_allowed(ep, data))


def _review_clean(ep: Path, data: dict | None, frame: dict, contexts: dict, caption_hash: str,
                  version: str, directing_v3: bool, *, policy_sha256: str | None = None) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if not isinstance(data, dict):
        return False, ["missing_review"]
    if str(data.get("story_os_version") or "") != version:
        reasons.append("review_version_changed")
    if str(data.get("asset_sha256") or "").lower() != frame["sha256"].lower():
        reasons.append("asset_sha_changed")
    if str(data.get("asset_path") or "") != frame["path_rel"]:
        reasons.append("asset_path_changed")
    if not _context_match(data, contexts):
        reasons.append("story_visual_context_changed")
    if not _binding_match(data, ep, frame["frame"]):
        reasons.append("story_source_binding_changed")
    phase3 = base.phase3_context_hashes(ep, frame["frame"])
    for field, expected in phase3.items():
        if str(data.get(field) or "").lower() != str(expected).lower():
            reasons.append("phase3_frame_context_changed")
            break
    expected_identity = {
        "logical_asset_key": frame.get("logical_asset_key"),
        "generation_key": frame.get("generation_key"),
        "sha256": frame.get("sha256"),
        "source_binding": base.source_binding(ep, frame["frame"]),
    }
    if not expected_identity["generation_key"]:
        reasons.append("current_generation_missing")
    elif str(data.get("generation_key") or "") != str(expected_identity["generation_key"]):
        reasons.append("current_generation_changed")
    if not expected_identity["logical_asset_key"] or data.get("logical_asset_key") != expected_identity["logical_asset_key"]:
        reasons.append("logical_asset_binding_changed")
    if not policy_sha256:
        reasons.append("model_policy_binding_missing")
    elif str(data.get("model_policy_sha256") or "").lower() != str(policy_sha256).lower():
        reasons.append("policy_sha_changed")
    expected_fingerprint = _expected_review_fingerprint(
        ep, data, frame, contexts, phase3, policy_sha256)
    if not expected_fingerprint:
        reasons.append("evidence_fingerprint_inputs_missing")
    elif str(data.get("evidence_fingerprint") or "").lower() != expected_fingerprint:
        reasons.append("evidence_fingerprint_invalid")
    # STORY_OS_V2_6_0_PERFORMANCE_RUNTIME:
    # Caption changes are audited independently by caption_image_audit.py and MUST NOT dirty visual review.
    if not _scope_ok(data, ep):
        reasons.append("review_scope_invalid")
    issue_codes = data.get("issue_codes")
    if data.get("decision") != "pass" or not isinstance(issue_codes, list) or issue_codes:
        reasons.append("review_not_pass")
    checks = data.get("checks") or {}
    for name in base.checks_for_version(version, directing_v3):
        if checks.get(name) is not True:
            reasons.append(f"check_failed:{name}")
    if base.validate_bound_review(data, frame=frame, contexts=contexts, version=version,
                                  metadata_only=True, phase3_contexts=phase3, directing_v3=directing_v3):
        reasons.append("bound_review_invalid")
    return not reasons, reasons


def _context_frames(keys: list[str], dirty: list[str]) -> list[str]:
    nums = sorted(int(k) for k in keys)
    allowed = set(nums)
    total = max(nums) if nums else 0
    chosen: set[int] = set()
    for raw in dirty:
        n = int(raw)
        radius = 2 if n >= max(1, total - 2) else 1
        for i in range(n - radius, n + radius + 1):
            if i in allowed:
                chosen.add(i)
    return [f"{n:02d}" for n in sorted(chosen)]


def _pending_ledger_plan(ep: Path) -> dict | None:
    """Describe unfinished production without asking final-review code to consume it.

    Incremental semantic review only owns PASSED/LOCKED assets. Transitional ledger
    states belong to image generation/recovery. In particular, an authority refresh is
    a deliberate regeneration boundary, not a malformed production-passed frame.
    """
    ledger = production_ledger.load_authority(ep, default=None)
    if not isinstance(ledger, dict):
        return None
    frames = ledger.get("frames")
    if not isinstance(frames, dict) or not frames:
        return None
    pending: dict[str, str] = {}
    for raw_key, row in frames.items():
        if not isinstance(row, dict):
            continue
        key = str(raw_key).zfill(2)
        status = str(row.get("status") or "")
        if status not in production_ledger.ACCEPTED_LEDGER_STATES:
            pending[key] = status or "UNKNOWN"
    if not pending:
        return None
    authority_refresh = sorted(
        key for key, status in pending.items() if status == "AUTHORITY_REFRESH_AUTHORIZED"
    )
    return {
        "action": "AWAITING_AUTHORITY_REFRESH" if authority_refresh else "AWAITING_PRODUCTION",
        "dirty_frames": authority_refresh if authority_refresh else sorted(pending),
        "reused_frames": [],
        "missing_evidence_frames": [],
        "context_frames": [],
        "reasons": {key: [f"ledger_status:{status}"] for key, status in sorted(pending.items())},
        "pending_frames": sorted(pending),
        "pending_statuses": dict(sorted(pending.items())),
        "authority_refresh_frames": authority_refresh,
        "accepted_known_defect_frames": [],
        "accepted_reasons": {},
        "caption_mode": "deferred_until_production_ready",
    }


def build_plan(ep: Path) -> dict:
    if not review_required(ep):
        return {"action": "NOT_REQUIRED", "dirty_frames": [], "reused_frames": [],
                "missing_evidence_frames": [], "context_frames": [], "reasons": ["legacy_contract"]}
    pending_plan = _pending_ledger_plan(ep)
    if pending_plan is not None:
        return pending_plan
    authority = verified_review_authority.verify_episode_review_authority(ep, metadata_only=False)
    if authority["status"] == "BLOCKED":
        return {
            "action": "BLOCKED_UNVERIFIED_REVIEW_AUTHORITY",
            "dirty_frames": [], "reused_frames": [], "missing_evidence_frames": [],
            "context_frames": [], "reasons": authority["errors"],
        }
    frames = base.frame_records(ep, require_files=True)
    contexts = base.context_hashes(ep)
    captions = caption_state(ep, frames)
    version = base.episode_contract_version(ep)
    directing_v3 = base.directing_v3_required(ep)
    policy_sha = base.bound_review_policy_sha256(ep)
    dirty: list[str] = []
    reused: list[str] = []
    missing: list[str] = []
    reasons: dict[str, list[str]] = {}
    old_fingerprints: dict[str, str | None] = {}
    new_fingerprints: dict[str, str | None] = {}
    accepted: list[str] = []
    accepted_reasons: dict[str, list[str]] = {}
    context_change = False
    for frame in frames:
        data = _review_data(ep, frame["frame"])
        phase3 = base.phase3_context_hashes(ep, frame["frame"])
        identity = {
            "logical_asset_key": frame.get("logical_asset_key"),
            "generation_key": frame.get("generation_key"),
            "sha256": frame.get("sha256"),
            "source_binding": base.source_binding(ep, frame["frame"]),
        }
        new_fingerprint = (_expected_review_fingerprint(
            ep, data, frame, contexts, phase3, policy_sha)
            if isinstance(data, dict) else
            base.frame_evidence_fingerprint(
                identity, contexts=contexts, phase3_contexts=phase3,
                policy_sha256=policy_sha))
        new_fingerprints[frame["frame"]] = new_fingerprint
        old_fingerprints[frame["frame"]] = (
            str(data.get("evidence_fingerprint")) if isinstance(data, dict)
            and data.get("evidence_fingerprint") else None)
        clean, why = _review_clean(ep, data, frame, contexts, captions["frame_sha256"][frame["frame"]],
                                   version, directing_v3, policy_sha256=policy_sha)
        if not clean:
            if data is None:
                missing.append(frame["frame"])
            # A direct-user final acceptance (meta/final-acceptance.json) converts a
            # known-defect frame into an accepted one so it does not re-enter the repair
            # queue forever. It is recorded explicitly, never silently treated as clean.
            if final_acceptance.covers(ep, frame["frame"]):
                accepted.append(frame["frame"])
                accepted_reasons[frame["frame"]] = why
                continue
            dirty.append(frame["frame"])
            reasons[frame["frame"]] = why
            if {"story_visual_context_changed", "review_version_changed", "story_source_binding_changed"}.intersection(why):
                context_change = True
        else:
            reused.append(frame["frame"])
    if not dirty:
        return {
            "action": "NOOP",
            "dirty_frames": [],
            "reused_frames": reused,
            "missing_evidence_frames": missing,
            "old_fingerprints": old_fingerprints,
            "new_fingerprints": new_fingerprints,
            "context_frames": [],
            "reasons": {},
            "accepted_known_defect_frames": accepted,
            "accepted_reasons": accepted_reasons,
            "caption_mode": captions["mode"],
        }
    ratio = len(dirty) / max(1, len(frames))
    # First-ever review must establish a whole-episode baseline. Once clean
    # SHA-bound evidence exists, a large repair wave must not force rerunning
    # every unaffected frame merely because its dirty ratio exceeds 25%.
    first_review = bool(frames) and len(missing) == len(frames) and not reused and not accepted
    action = "FULL" if context_change or first_review else "PATCH"
    return {
        "action": action,
        "dirty_frames": dirty,
        "reused_frames": reused,
        "missing_evidence_frames": missing,
        "old_fingerprints": old_fingerprints,
        "new_fingerprints": new_fingerprints,
        "context_frames": [row["frame"] for row in frames] if action == "FULL" else _context_frames([r["frame"] for r in frames], dirty),
        "reasons": reasons,
        "accepted_known_defect_frames": accepted,
        "accepted_reasons": accepted_reasons,
        "dirty_ratio": round(ratio, 4),
        "review_scope_reason": "GLOBAL_CONTEXT_CHANGED" if context_change else ("FIRST_REVIEW" if first_review else "DIRTY_FRAME_PATCH"),
        "caption_mode": captions["mode"],
    }


def _prompt(ep: Path, selected: list[dict], dirty: list[str], candidate: Path, attempt: int, captions: dict) -> str:
    story, storyboard = base.episode_files(ep)
    version = base.episode_contract_version(ep)
    directing_v3 = base.directing_v3_required(ep)
    rel_ep = ep.relative_to(ROOT).as_posix()
    dirty_set = set(dirty)
    mapping = "\n".join(
        f"- {'DIRTY TARGET' if r['frame'] in dirty_set else 'CONTEXT ONLY'} frame {r['frame']}: {r['path_rel']}"
        for r in selected)
    dirty_text = ", ".join(dirty)
    caption_source = captions.get("source_path") or "<no caption source>"
    return f"""You are an adversarial Story OS incremental Production Frame Semantic Critic in a FRESH isolated session.
Do NOT generate or edit images. Do NOT trust previous PASS labels.
Review the dirty target frames for {rel_ep}: {dirty_text}.
Neighbor frames marked CONTEXT ONLY are read-only evidence supplied only to judge continuity; do not re-review or return rows for them.

Read:
- {story.relative_to(ROOT).as_posix()}
- {storyboard.relative_to(ROOT).as_posix()}
- {(ep / 'meta/story-gates.json').relative_to(ROOT).as_posix()}
- {caption_source}
- standards/制作规范_正式版.md
- standards/生产帧语义强制规范_V1.0.md

Attached mapping:
{mapping}

Attempt {attempt}. Judge ACTUAL pixels for each DIRTY TARGET. Every target frame must pass all checks:
{', '.join(base.checks_for_version(version, directing_v3))}
Hard failures include wrong scene/beat/prop/person/wardrobe, illegal POV, ghost camera, broken space/time continuity, unreadable anomaly, caption inventing missing evidence, missing actual information gain, narrative redundancy, repeated shot grammar, unmotivated camera defects, impossible screen/UI physics, broken visual memory, wrong locked shot scale, visually repeated planned camera position, failed cinematic-structure translation, invented/non-matching light, or missing declared reflection/fog/light-shadow/occlusion anomaly carrier.
Episode contract version: {version}. V2.2-only Visual Narrative checks and issue codes apply ONLY when version >= 2.2.0; legacy episodes must not fail on V2.2-only criteria.
Return one row for EVERY dirty target frame and no rows for context-only frames.
Use issue codes only from: {', '.join(sorted(base.ISSUE_CODES))}

Write ONLY JSON to {candidate.relative_to(ROOT).as_posix()} with shape:
{{"frames":[{{"frame":"01","checks":{{"scene_storyboard_fidelity":true,"story_beat_fidelity":true,"key_prop_fidelity":true,"character_identity":true,"wardrobe_continuity":true,"pov_photographer_legality":true,"spatial_continuity":true,"temporal_continuity":true,"anomaly_readability":true,"caption_image_support":true,"actual_information_gain":true,"environment_physics_fidelity":true,"anomaly_escalation_fidelity":true,"scale_reference_fidelity":true,"camera_authorship_physical":true,"moment_capture_credibility":true,"narrative_evidence_gain":true,"shot_grammar_diversity":true,"camera_defect_physics":true,"screen_content_physics":true,"visual_memory_continuity":true,"shot_scale_fidelity":true,"scene_position_uniqueness_fidelity":true,"cinematic_structure_translation_fidelity":true,"practical_lighting_design_fidelity":true,"anomaly_concealment_fidelity":true}},"issue_codes":[],"notes":"pixel-level evidence","decision":"pass"}}],"issue_codes":[],"summary":{{"passed":true,"notes":"incremental context judgment"}}}}
If any supplied frame fails, summary.passed=false.
"""


def _decorate_full(ep: Path) -> None:
    frames = base.frame_records(ep, require_files=True)
    captions = caption_state(ep, frames)
    for frame in frames:
        p = _review_path(ep, frame["frame"])
        data = read_json(p)
        data["caption_sha256"] = captions["frame_sha256"][frame["frame"]]
        write_json(p, data)
    summary_path = ep / base.SUMMARY_REL
    summary = read_json(summary_path)
    summary["caption_source"] = captions["source_path"]
    summary["caption_source_sha256"] = captions["source_sha256"]
    summary["caption_mode"] = captions["mode"]
    summary["caption_frame_sha256"] = captions["frame_sha256"]
    summary["incremental_contract"] = {"version": 1, "mode": "full_baseline"}
    write_json(summary_path, summary)


def rebind_captions(ep: Path, *, allow_dirty: bool = False) -> dict:
    """Re-bind current caption SHAs onto an already-current frame semantic review.

    V2.0.3.4 binds captions into both the per-frame reviews and the summary.
    A full critic rewrite (frame_semantic_review._persist_candidate) writes those
    files without the caption binding, and build_plan() intentionally ignores
    caption drift because asset drift is what triggers a re-review.  This helper
    heals only the caption binding, and refuses to bind unless the plan says the
    assets/contracts themselves are still current.
    """
    if not review_required(ep):
        return {"rebound": False, "reason": "legacy_contract"}
    plan = build_plan(ep)
    if plan["action"] != "NOOP" and not allow_dirty:
        return {"rebound": False, "reason": "review_dirty", "plan": plan}
    _decorate_full(ep)
    frames = base.frame_records(ep, require_files=True)
    captions = caption_state(ep, frames)
    errors = verify_episode(ep, metadata_only=False, write_audit=True)
    return {
        "rebound": True,
        "plan_action": plan["action"],
        "caption_source": captions["source_path"],
        "caption_source_sha256": captions["source_sha256"],
        "errors": errors,
    }


def _run_patch_uninstrumented(ep: Path, plan: dict, *, attempt: int, codex_raw: str | None, timeout: int) -> int:
    all_frames = base.frame_records(ep, require_files=True)
    binding_errors = base.phase4_binding_errors(ep, all_frames)
    if binding_errors:
        print("INCREMENTAL FRAME REVIEW FAIL: stale/missing generation Frame Contract")
        for error in binding_errors:
            print("FAIL:", error)
        return 2
    by_key = {r["frame"]: r for r in all_frames}
    selected = [by_key[k] for k in plan["context_frames"]]
    targets = [by_key[k] for k in plan["dirty_frames"]]
    contexts = base.context_hashes(ep)
    captions = caption_state(ep, all_frames)
    frozen_sources = base.review_source_bindings(ep, all_frames)

    phashes = base.perceptual_rows(all_frames)
    duplicates = base.duplicate_pairs(phashes)
    if duplicates:
        write_json(ep / AUDIT_REL, {"checked_at": now(), "action": "PATCH", "errors": ["NEAR_DUPLICATE_ACTUAL_FRAMES"], "near_duplicate_pairs": duplicates, "summary": {"passed": False}})
        print("INCREMENTAL FRAME REVIEW FAIL: deterministic near-duplicate check")
        return 2

    candidate = ep / CANDIDATE_REL
    candidate.unlink(missing_ok=True)
    before = {r["frame"]: base.sha256_file(r["path"]) for r in all_frames}
    codex = critic_runner.resolve_codex(codex_raw)
    log = ep / "meta" / f"incremental-frame-critic-attempt-{attempt}.jsonl"
    completed = critic_runner.launch(
        _prompt(ep, selected, plan["dirty_frames"], candidate, attempt, captions),
        codex=codex,
        root=ROOT,
        timeout=timeout,
        sandbox="workspace-write",
        model=runtime_router.vision_review_model(),
        reasoning_effort=runtime_router.vision_review_effort("default"),
        attachments=[row["path"] for row in selected],
        log_path=log,
    )
    if completed.returncode != 0 or not candidate.is_file():
        raise RuntimeError(f"incremental critic failed rc={completed.returncode}; log={log}")

    current = base.frame_records(ep, require_files=True)
    if {r["frame"]: base.sha256_file(r["path"]) for r in current} != before:
        raise RuntimeError("incremental critic modified approved image assets")
    if base.review_source_bindings(ep, current) != frozen_sources:
        raise RuntimeError("incremental critic sources drifted during review; candidate cannot be rebound")
    data = read_json(candidate)
    version = base.episode_contract_version(ep)
    directing_v3 = base.directing_v3_required(ep)
    candidate_errors = base.validate_candidate_rows(data.get("frames"), targets, version=version, directing_v3=directing_v3)
    global_codes = data.get("issue_codes")
    if not isinstance(global_codes, list):
        candidate_errors.append("global issue_codes must be list")
        global_codes = []
    elif global_codes:
        candidate_errors.append(f"global issue_codes must be empty for PASS: {global_codes}")
    if (data.get("summary") or {}).get("passed") is not True:
        candidate_errors.append("critic summary.passed must be true")

    rows_by_frame = {str(r.get("frame") or "").zfill(2): r for r in (data.get("frames") or []) if isinstance(r, dict)}
    provenance = runtime_provenance.build_vision_critic_provenance(
        attempt=attempt,
        log=_repo_rel(log),
        review_scope="INCREMENTAL_CONTEXT_SET",
    )
    provenance.update({
        "dirty_roots": plan["dirty_frames"],
        "context_frames": plan["context_frames"],
    })
    policy_sha = base.bound_review_policy_sha256(ep)
    for frame in targets:
        source = rows_by_frame.get(frame["frame"], {})
        phase3_contexts = base.phase3_context_hashes(ep, frame["frame"])
        identity = {
            "logical_asset_key": frame.get("logical_asset_key"),
            "generation_key": frame.get("generation_key"),
            "sha256": frame["sha256"],
            "source_binding": frozen_sources["frames"][frame["frame"]].get("source_binding") or {},
        }
        bound = {
            "schema_version": base.SCHEMA_VERSION,
            "story_os_version": version,
            "frame": frame["frame"],
            "asset_path": frame["path_rel"],
            "asset_sha256": frame["sha256"],
            **contexts,
            **frozen_sources["frames"][frame["frame"]],
            "logical_asset_key": frame.get("logical_asset_key"),
            "generation_key": frame.get("generation_key"),
            "model_policy_sha256": policy_sha,
            "evidence_fingerprint": base.frame_evidence_fingerprint(
                identity, contexts=contexts, phase3_contexts=phase3_contexts,
                policy_sha256=policy_sha),
            "caption_sha256": captions["frame_sha256"][frame["frame"]],
            "critic_provenance": provenance,
            "checks": source.get("checks") or {},
            "issue_codes": source.get("issue_codes") if isinstance(source.get("issue_codes"), list) else ["FRAME_SCENE_MISMATCH"],
            "notes": source.get("notes") or "",
            "decision": source.get("decision") or "fail",
        }
        write_json(_review_path(ep, frame["frame"]), bound)

    summary = {
        "schema_version": base.SCHEMA_VERSION,
        "story_os_version": version,
        **contexts,
        "critic_provenance": {
            **provenance,
            "review_scope": "BASELINE_PLUS_PATCHES",
        },
        "model_policy_sha256": policy_sha,
        "frames": [{"frame": r["frame"], "asset_sha256": r["sha256"]} for r in current],
        "caption_source": captions["source_path"],
        "caption_source_sha256": captions["source_sha256"],
        "caption_mode": captions["mode"],
        "caption_frame_sha256": captions["frame_sha256"],
        "perceptual_hashes": phashes,
        "near_duplicate_pairs": [],
        "issue_codes": global_codes,
        "critic_summary": data.get("summary") or {},
        "incremental_contract": {
            "version": 1,
            "mode": "baseline_plus_patches",
            "dirty_roots": plan["dirty_frames"],
            "context_frames": plan["context_frames"],
            "reused_frames": plan.get("reused_frames", []),
        },
        "summary": {"passed": not candidate_errors},
    }
    write_json(ep / base.SUMMARY_REL, summary)
    candidate.unlink(missing_ok=True)

    errors = candidate_errors + [e for e in verify_episode(ep, metadata_only=False, write_audit=True) if e not in candidate_errors]
    if errors:
        print("INCREMENTAL FRAME REVIEW FAIL")
        for error in errors:
            print("FAIL:", error)
        return 2
    print(f"INCREMENTAL FRAME REVIEW PASS: dirty={plan['dirty_frames']} context={plan['context_frames']}")
    return 0


def _run_patch(ep: Path, plan: dict, *, attempt: int, codex_raw: str | None, timeout: int) -> int:
    dirty = plan.get("dirty_frames") if isinstance(plan.get("dirty_frames"), list) else []
    contexts = plan.get("context_frames") if isinstance(plan.get("context_frames"), list) else []
    episode_performance.safe_begin_review_span(ep, "PATCH", attempt, metadata={
        "target_frame_count": len(dirty),
        "shard_count": 1,
        "dirty_frames": list(dirty),
        "context_frame_count": len(contexts),
    })
    try:
        result = _run_patch_uninstrumented(ep, plan, attempt=attempt, codex_raw=codex_raw, timeout=timeout)
    except BaseException as exc:
        episode_performance.safe_end_review_span(
            ep, "PATCH", attempt, status="ERROR", metadata={"error_type": type(exc).__name__})
        raise
    episode_performance.safe_end_review_span(
        ep, "PATCH", attempt, status=episode_performance.review_status_for_code(result),
        metadata={"result_code": result})
    return result


def verify_episode(ep: Path, *, metadata_only: bool = False, write_audit: bool = False) -> list[str]:
    if not review_required(ep):
        return list(base.verify_episode(ep, metadata_only=metadata_only, write_audit=False))

    # Phase5A is an explicitly TEST_ONLY, NON_PROMOTABLE single-frame canary.
    # Its authoritative Final Semantic evidence is intentionally scoped and must
    # not be rejected by the full-Episode baseline/caption contract. Production
    # Episodes continue through base.verify_episode() unchanged.
    scoped_phase5a = False
    scoped_frames: list[dict] = []
    try:
        scoped_frames = base.frame_records(ep, require_files=not metadata_only)
        if len(scoped_frames) == 1:
            scoped_data = _review_data(ep, scoped_frames[0]["frame"])
            scoped_phase5a = _phase5a_scoped_evidence_allowed(ep, scoped_data)
    except Exception:
        scoped_phase5a = False
    errors = list(
        base.verify_scoped_review(
            ep, scoped_frames,
            review_scope=base.PHASE5A_SINGLE_FRAME_SCOPE,
            metadata_only=metadata_only,
        )
        if scoped_phase5a else
        base.verify_episode(ep, metadata_only=metadata_only, write_audit=False)
    )
    authority = verified_review_authority.verify_episode_review_authority(
        ep, metadata_only=metadata_only)
    errors.extend(authority["errors"])
    # E005 is an automated risk detector only. If present, a low score makes
    # the review dirty/repairable; it does not manufacture a visual PASS.
    score_path = Path(ep) / visual_reality_score.REL
    if score_path.is_file() and not metadata_only:
        errors.extend(visual_reality_score.verify(ep))
    version = base.episode_contract_version(ep)
    if version_tuple(version) < TARGET:
        if write_audit:
            write_json(ep / AUDIT_REL, {"checked_at": now(), "legacy_contract": version, "errors": errors, "summary": {"passed": not errors}})
        return errors
    if not scoped_phase5a:
        try:
            frames = base.frame_records(ep, require_files=not metadata_only)
            captions = caption_state(ep, frames)
            for frame in frames:
                data = _review_data(ep, frame["frame"])
                if not isinstance(data, dict):
                    errors.append(f"missing incremental-bound frame review: {frame['frame']}")
                    continue
                expected = captions["frame_sha256"][frame["frame"]]
                if str(data.get("caption_sha256") or "").lower() != expected.lower():
                    errors.append(f"frame {frame['frame']} caption_sha256 stale")
            summary_path = ep / base.SUMMARY_REL
            if summary_path.is_file():
                summary = read_json(summary_path)
                if summary.get("caption_source_sha256") != captions["source_sha256"]:
                    errors.append("frame semantic summary caption source SHA stale")
                if summary.get("caption_frame_sha256") != captions["frame_sha256"]:
                    errors.append("frame semantic summary caption frame hashes stale")
                if not isinstance(summary.get("incremental_contract"), dict):
                    errors.append("frame semantic summary missing incremental_contract")
        except Exception as exc:
            errors.append(str(exc))
    if write_audit:
        write_json(ep / AUDIT_REL, {
            "schema_version": 1,
            "story_os_version": version,
            "checked_at": now(),
            "metadata_only": metadata_only,
            "errors": errors,
            "summary": {"passed": not errors},
        })
    return errors


def run_review(ep: Path, *, attempt: int, codex_raw: str | None, timeout: int | None = None) -> int:
    if timeout is None:
        timeout = runtime_timeout_policy.seconds("deep_semantic_review")
    if attempt not in {1, 2}:
        raise RuntimeError("attempt must be 1 or 2")
    plan = build_plan(ep)
    write_json(ep / STATE_REL, {"schema_version": 1, "story_os_version": story_os_version(), "planned_at": now(), **plan})
    action = plan["action"]
    if action == "NOT_REQUIRED":
        print("INCREMENTAL FRAME REVIEW SKIP: legacy contract")
        return 0
    if action == "BLOCKED_UNVERIFIED_REVIEW_AUTHORITY":
        for error in plan.get("reasons") or []:
            print("FAIL:", error)
        return 3
    if action == "NOOP":
        errors = verify_episode(ep, metadata_only=False, write_audit=True)
        if errors:
            for e in errors:
                print("FAIL:", e)
            return 2
        print("INCREMENTAL FRAME REVIEW REUSE: 0 critic calls")
        return 0
    if action in {"AWAITING_AUTHORITY_REFRESH", "AWAITING_PRODUCTION"}:
        print(f"INCREMENTAL FRAME REVIEW DEFER: action={action} pending={plan.get('pending_frames') or []}")
        return 3
    active_runtime, _ = runtime_router.detect()
    vision_runtime, _ = runtime_router.vision_review_runtime()
    if action == "FULL" or (action == "PATCH" and vision_runtime != "CODEX" and not codex_raw):
        reason = "vision runtime requires product review" if action == "PATCH" else "dirty/context threshold"
        print(f"INCREMENTAL FRAME REVIEW ESCALATE FULL: dirty={plan['dirty_frames']} reason={reason}")
        rc = base.run_critic(ep, attempt=attempt, codex_raw=codex_raw, timeout=timeout)
        if rc == 0:
            _decorate_full(ep)
            errors = verify_episode(ep, metadata_only=False, write_audit=True)
            if errors:
                for e in errors:
                    print("FAIL:", e)
                return 2
        return rc
    return _run_patch(ep, plan, attempt=attempt, codex_raw=codex_raw, timeout=timeout)


def self_test() -> None:
    assert _extract_yaml_captions('captions:\n  1: "a"\n  02: b\n') == {"01": "a", "02": "b"}
    assert _extract_json_captions({"captions": {"1": "x", "02": "y"}}) == {"01": "x", "02": "y"}
    keys = [f"{i:02d}" for i in range(1, 21)]
    assert _context_frames(keys, ["02"]) == ["01", "02", "03"]
    assert _context_frames(keys, ["19"]) == ["17", "18", "19", "20"]
    print("INCREMENTAL FRAME REVIEW SELF-TEST PASS")


def main() -> int:
    ap = argparse.ArgumentParser(description="Story OS V2.0.3.4 incremental actual-frame semantic review")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan"); p.add_argument("episode_dir")
    p = sub.add_parser("review"); p.add_argument("episode_dir"); p.add_argument("--attempt", type=int, default=1); p.add_argument("--codex"); p.add_argument("--timeout", type=int, default=None)
    p = sub.add_parser("verify"); p.add_argument("episode_dir"); p.add_argument("--metadata-only", action="store_true")
    p = sub.add_parser("audit"); p.add_argument("episode_dir")
    p = sub.add_parser("rebind-captions"); p.add_argument("episode_dir"); p.add_argument("--allow-dirty", action="store_true")
    sub.add_parser("self-test")
    args = ap.parse_args()
    if args.cmd == "self-test":
        self_test(); return 0
    ep = Path(args.episode_dir).resolve()
    if not ep.is_dir():
        raise SystemExit(f"episode directory not found: {ep}")
    if args.cmd == "plan":
        print(json.dumps(build_plan(ep), ensure_ascii=False, indent=2)); return 0
    if args.cmd == "review":
        try:
            return run_review(ep, attempt=args.attempt, codex_raw=args.codex, timeout=args.timeout)
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
            print("INCREMENTAL FRAME REVIEW ERROR:", exc); return 3
    if args.cmd == "rebind-captions":
        result = rebind_captions(ep, allow_dirty=args.allow_dirty)
        print(json.dumps({k: v for k, v in result.items() if k != "plan"}, ensure_ascii=False, indent=2))
        if not result.get("rebound"):
            print("INCREMENTAL CAPTION REBIND SKIPPED")
            return 3
        errors = result.get("errors") or []
        if errors:
            for e in errors:
                print("FAIL:", e)
            print("INCREMENTAL CAPTION REBIND FAIL")
            return 2
        print("INCREMENTAL CAPTION REBIND PASS")
        return 0
    errors = verify_episode(ep, metadata_only=(args.cmd == "verify" and args.metadata_only), write_audit=(args.cmd == "audit"))
    if errors:
        for e in errors: print("FAIL:", e)
        return 2
    print("INCREMENTAL FRAME REVIEW VERIFY PASS" if args.cmd == "verify" else "INCREMENTAL FRAME AUDIT PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
