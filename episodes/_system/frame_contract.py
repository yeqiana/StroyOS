#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Story OS V2.1 Phase 4 Resolved Frame Contract compiler.

Authority stays in Story / Storyboard / story-gates / Visual Profile.
Files under meta/runtime/contracts are derived caches only.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import contextvars
import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from story_os_contract import story_os_version
from visual_profile import compile_prompt_contract
import environment_contract
import character_contract
import capture_event_contract
import world_state
import character_visual_contract
import shot_progression_gate
import temporal_continuity_gate
import wardrobe_contract
import visual_narrative_core_v22  # STORY_OS_V22_VISUAL_NARRATIVE_CORE
import world_identity_contract  # STORY_OS_V221_WORLD_IDENTITY
import character_appearance_anchor  # STORY_OS_V221_CHARACTER_CONTINUITY
import identity_continuity  # STORY_OS_P1_1_IDENTITY_CONTINUITY
import story_semantic_trace  # STORY_OS_W22_STORY_SEMANTIC_TRACE
import story_dna_trace  # STORY_OS_V3_E003_STORY_DNA_TRACE
import story_json
import content_fingerprint
import preimage_authority_snapshot
import runtime_node_execution
import storyos_config
import runtime_workspace
import storage_config
import production_ledger
import episode_state_persistence
import episode_contract_persistence
import m00_episode_state_delta

ROOT = Path(__file__).resolve().parents[2]
CACHE_ROOT = Path("meta/runtime/contracts/frames")
EXPORT_ROOT = Path("exports/frame-contracts")
INDEX_REL = Path("meta/runtime/contracts/frame-contract-index.json")
PROJECTION_MIGRATION_REL = Path("meta/runtime/frame-contract-projection-migrations.json")
CONTRACT_EXCEPTION_REL = Path("meta/runtime/frame-contract-exceptions.json")
MIN_VERSION = (2, 1, 0)
SCHEMA_VERSION = 1
MAX_EXCERPT = 2200


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> dict:
    return story_json.read_json(path)


def write_json(path: Path, data: dict) -> None:
    story_json.write_json(path, data)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return content_fingerprint.sha256_file(path)


def sha256_json(data: Any) -> str:
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(raw)


def version_tuple(raw: object) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in str(raw or "").split("."))
    except Exception:
        return (0,)


def episode_version(ep: Path) -> str:
    versions: list[tuple[tuple[int, ...], str]] = []
    # Test/temporary compile fixtures may intentionally omit episode-state.json.
    # In that case there is no state authority to read; version evidence below
    # remains the only valid source.  Do not force storage-mode configuration
    # just to inspect an unversioned derived-cache fixture.
    state_path = Path(ep).resolve() / "meta/episode-state.json"
    state = episode_state_persistence.load(Path(ep).resolve()) or {} if state_path.is_file() else {}
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
    # Directories without any version evidence (legacy / test fixtures) are not
    # V2.1 episodes; do not force Resolved Frame Contract binding on them.
    return max(versions, key=lambda x: x[0])[1] if versions else ""


def required(ep: Path) -> bool:
    return version_tuple(episode_version(ep)) >= MIN_VERSION


def resolve_ep(raw: str) -> Path:
    ep = Path(raw).resolve()
    if not ep.is_dir():
        raise SystemExit(f"episode directory not found: {ep}")
    try:
        ep.relative_to(ROOT.resolve())
    except ValueError:
        raise SystemExit("episode must be inside repository")
    return ep


def repo_path(raw: object, where: str, *, must_exist: bool = True) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"{where} missing")
    p = Path(raw.strip())
    p = p.resolve() if p.is_absolute() else (ROOT / p).resolve()
    try:
        p.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise ValueError(f"{where} escapes repository") from exc
    if must_exist and not p.is_file():
        raise ValueError(f"{where} missing: {raw}")
    return p


def repo_rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def normalize_contract_path(raw: object, *, base: Path | None = None) -> str | None:
    """Return stable repository-relative POSIX paths for derived contracts.

    Frame Contract is hashed and moved between workers. Absolute Windows paths
    or slash variants must never enter contract material because they make the
    same logical contract produce different SHA values on another machine.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    p = Path(text)
    if p.is_absolute():
        p = p.resolve()
    elif base is not None:
        p = (base / p).resolve()
    else:
        p = (ROOT / p).resolve()
    try:
        return p.relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return Path(text).as_posix()


def manifest(ep: Path) -> dict:
    return read_json(ep / "meta/release-manifest.json")


def gates(ep: Path) -> dict:
    return read_json(ep / "meta/story-gates.json")


def artifact_paths(ep: Path) -> tuple[Path, Path]:
    artifacts = manifest(ep).get("artifacts") or {}
    return (
        repo_path(artifacts.get("story"), "manifest.artifacts.story"),
        repo_path(artifacts.get("storyboard"), "manifest.artifacts.storyboard"),
    )


def frame_count(ep: Path) -> int:
    n = ((manifest(ep).get("release") or {}).get("body_frame_count"))
    if isinstance(n, bool) or not isinstance(n, int) or n <= 0:
        raise ValueError("release.body_frame_count must be > 0")
    return n


def _frame_from_json(value: Any, frame: int) -> Any | None:
    if isinstance(value, dict):
        # Direct frame-number keys.
        for key in (str(frame), f"{frame:02d}"):
            if key in value:
                return value[key]
        # Common collections.
        for key in ("frames", "storyboard", "shots", "images", "beats"):
            if key in value:
                found = _frame_from_json(value[key], frame)
                if found is not None:
                    return found
        # Rows carrying a frame identifier.
        raw = value.get("frame") or value.get("number") or value.get("image") or value.get("shot")
        try:
            if raw is not None and int(str(raw).strip()) == frame:
                return value
        except Exception:
            pass
        for child in value.values():
            if isinstance(child, (dict, list)):
                found = _frame_from_json(child, frame)
                if found is not None:
                    return found
    elif isinstance(value, list):
        for item in value:
            found = _frame_from_json(item, frame)
            if found is not None:
                return found
    return None


def extract_frame_excerpt(path: Path, frame: int) -> dict:
    raw = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() == ".json":
        try:
            data = json.loads(raw)
            found = _frame_from_json(data, frame)
            if found is not None:
                text = json.dumps(found, ensure_ascii=False, sort_keys=True)
                return {"mode": "json_frame", "text": text[:MAX_EXCERPT], "sha256": sha256_bytes(text.encode("utf-8"))}
        except Exception:
            pass

    lines = raw.splitlines()
    # Supports "图 01", "Frame 01", "镜头01", bare numbered headings.
    start = None
    marker = re.compile(
        rf"^\s*(?:#{{1,6}}\s*)?(?:(?:图|镜头|画面|frame|shot)\s*)?0*{frame}(?:\s|[：:、.｜|]|$)",
        re.I,
    )
    any_marker = re.compile(
        r"^\s*(?:#{1,6}\s*)?(?:(?:图|镜头|画面|frame|shot)\s*)?0*\d{1,3}(?:\s|[：:、.｜|]|$)",
        re.I,
    )
    for i, line in enumerate(lines):
        if marker.search(line):
            start = i
            break
    if start is not None:
        end = min(len(lines), start + 40)
        for j in range(start + 1, min(len(lines), start + 60)):
            if any_marker.search(lines[j]):
                end = j
                break
        text = "\n".join(lines[start:end]).strip()[:MAX_EXCERPT]
        if text:
            return {"mode": "text_frame", "text": text, "sha256": sha256_bytes(text.encode("utf-8"))}

    # Safe fallback: broad invalidation if the storyboard format cannot be localized.
    return {
        "mode": "whole_storyboard_fallback",
        "text": "",
        "sha256": sha256_file(path),
    }


def resolved_references(ep: Path, frame: int) -> list[dict]:
    visual = (gates(ep).get("visual") or {})
    out: list[dict] = []
    for item in ((visual.get("references") or {}).get("items") or []):
        if not isinstance(item, dict):
            continue
        applies = item.get("frames") or item.get("frame_scope")
        if isinstance(applies, list):
            normalized = set()
            for x in applies:
                try:
                    normalized.add(int(x))
                except Exception:
                    pass
            if normalized and frame not in normalized:
                continue
        raw = item.get("path")
        row = {
            "id": item.get("id"),
            "role": item.get("role"),
            "kind": item.get("reference_kind") or item.get("kind"),
            "decision": item.get("decision"),
            "path": raw,
        }
        if isinstance(raw, str) and raw.strip():
            try:
                p = repo_path(raw, "visual.references.items.path")
                row["path"] = repo_rel(p)
                row["sha256"] = sha256_file(p)
            except Exception:
                row["sha256"] = None
        out.append(row)
    return out


def source_binding(ep: Path, frame: int | str) -> dict:
    """Stable derived footprint of the locked source material feeding one frame.

    This binding is review evidence, not part of the Frame Contract hash on
    purpose: adding it to hash_material would invalidate every historical
    contract SHA without changing the authoritative storyboard.
    """
    contract = compile_frame(ep, frame, write_cache=False)
    return contract.get("source_binding") or {
        "story": contract.get("source_trace", {}).get("story") or {},
        "storyboard": contract.get("source_trace", {}).get("storyboard") or {},
        "extraction_mode": (contract.get("storyboard_frame") or {}).get("mode"),
        "frame_sha256": (contract.get("storyboard_frame") or {}).get("sha256"),
    }


def _compact_json(value: object, limit: int = 1800) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return text if len(text) <= limit else text[:limit] + "…"


@episode_contract_persistence.operation_cached
def compile_frame(ep: Path, frame: int | str, *, write_cache: bool = True) -> dict:
    ep = Path(ep).resolve()
    total = frame_count(ep)
    try:
        n = int(frame)
    except Exception as exc:
        raise ValueError(f"invalid frame: {frame}") from exc
    if not 1 <= n <= total:
        raise ValueError(f"frame out of range: {n}/{total}")
    key = f"{n:02d}"

    story_path, storyboard_path = artifact_paths(ep)
    g = gates(ep)
    visual = g.get("visual") or {}
    character = character_contract.load(ep) or {}
    visual_profile = compile_prompt_contract(ep)
    env = environment_contract.resolve_frame(ep, n)
    directive = env.get("directive") or {}
    capture_event = capture_event_contract.resolve_frame(ep,n) if capture_event_contract.exists(ep) else {"capture_event":{},"capture_event_sha256":None}
    world = world_state.resolve_frame(ep,n) if (ep/world_state.REL).is_file() else {"world_state":{},"world_state_sha256":None}
    character_visual = character_visual_contract.load(ep) or {}
    progression = shot_progression_gate.resolve_frame(ep,n) if (ep/shot_progression_gate.REL).is_file() else {"shot_progression":{}}
    temporal = temporal_continuity_gate.resolve_frame(ep,n) if (ep/temporal_continuity_gate.REL).is_file() else {"temporal_state":{}}
    wardrobe = wardrobe_contract.resolve_frame(ep,n) if wardrobe_contract.exists(ep) else {"wardrobe":{}}
    visual_narrative_active = visual_narrative_core_v22.required(ep)
    visual_narrative = visual_narrative_core_v22.resolve_frame(ep,n) if visual_narrative_active else None
    world_identity_active = world_identity_contract.required(ep)
    world_identity = world_identity_contract.effective(ep) if world_identity_active else None
    character_anchor = None
    if world_identity_active:
        # The appearance anchor is a derived cache shared by every frame. Rewriting
        # the same file once per compile/verify frame is redundant and can trigger
        # Windows file/path failures during verify_all's second compile pass.
        ca_errors = character_appearance_anchor.verify(ep)
        ca_errors.extend(character_appearance_anchor.verify_frame01_identity_anchor(ep))
        if ca_errors:
            raise ValueError("; ".join(ca_errors))
        character_anchor = character_appearance_anchor.build(ep, write=False)
    excerpt = extract_frame_excerpt(storyboard_path, n)
    adjacent_state = m00_episode_state_delta.source_transition(
        storyboard_path, n, visual_profile["profile_id"], episode=ep)
    # An absent opt-in changes neither the derived contract SHA nor legacy prompt.
    refs = resolved_references(ep, n)
    # P1-1: per-frame identity requirement is derived review evidence. It is
    # deliberately excluded from hash_material so publishing it cannot invalidate
    # historical contract SHAs (same policy as source_binding).
    identity_requirements = identity_continuity.contract_requirements(
        ep, n, refs, progression.get("shot_progression") or {})

    source_trace = {
        "story": {"path": repo_rel(story_path), "sha256": sha256_file(story_path)},
        "storyboard": {"path": repo_rel(storyboard_path), "sha256": sha256_file(storyboard_path)},
        "story_gates": {"path": repo_rel(ep / "meta/story-gates.json"), "sha256": sha256_file(ep / "meta/story-gates.json")},
        "visual_profile": {
            "path": normalize_contract_path(visual_profile.get("profile_path")),
            "sha256": visual_profile["profile_sha256"],
        },
        "character_contract": {
            "path": character_contract.REL.as_posix(),
            "sha256": character_contract.authority_sha256(ep),
        },
        "capture_event_contract": {"path":capture_event_contract.REL.as_posix(),"sha256":capture_event_contract.authority_sha256(ep)},
        "world_state": {"path":world_state.REL.as_posix(),"sha256":sha256_file(ep/world_state.REL) if (ep/world_state.REL).is_file() else None},
        "character_visual_contract": {"path":character_visual_contract.REL.as_posix(),"sha256":character_visual_contract.authority_sha256(ep)},
        "shot_progression": {"path":shot_progression_gate.REL.as_posix(),"sha256":sha256_file(ep/shot_progression_gate.REL) if (ep/shot_progression_gate.REL).is_file() else None},
        "temporal_continuity": {"path":temporal_continuity_gate.REL.as_posix(),"sha256":sha256_file(ep/temporal_continuity_gate.REL) if (ep/temporal_continuity_gate.REL).is_file() else None},
        "wardrobe_contract": {"path":wardrobe_contract.REL.as_posix(),"sha256":wardrobe_contract.authority_sha256(ep)},
        "world_identity_default": {"path":world_identity_contract.DEFAULT_REL.as_posix(),"sha256":sha256_file(ROOT/world_identity_contract.DEFAULT_REL) if world_identity_active else None},
        "world_identity_override": {"path":world_identity_contract.OVERRIDE_REL.as_posix(),"sha256":world_identity_contract.override_sha256(ep) if world_identity_active else None},
        "character_appearance_anchor": {"path":character_appearance_anchor.REL.as_posix(),"sha256":sha256_file(ep/character_appearance_anchor.REL) if world_identity_active and (ep/character_appearance_anchor.REL).is_file() else None},
    }

    # W-22: per-frame story semantic requirement is derived review evidence. Like
    # source_binding it is deliberately excluded from hash_material so publishing
    # it cannot invalidate historical contract SHAs.
    story_semantic_requirements = story_semantic_trace.contract_requirements(
        ep, n, source_trace["story"])
    dna = story_json.read_json(ep / story_dna_trace.REL, default={}) or {}
    story_dna_mapping = ((dna.get("frame_mapping") or {}).get(key)
                         if isinstance(dna, dict) else None)
    if not isinstance(story_dna_mapping, dict):
        # No intent is invented. This visible pending block makes missing DNA
        # evidence detectable at PUBLISH_READY without changing contract SHA.
        story_dna_mapping = {"story_goal": None, "emotional_goal": None,
                             "reversal_contribution": None, "required": False}

    # Hash material is deliberately per-frame where possible.
    # storyboard source SHA is trace-only; localized excerpt SHA avoids all-frame invalidation.
    hash_material = {
        "schema_version": SCHEMA_VERSION,
        "frame": key,
        "story_sha256": source_trace["story"]["sha256"],
        "storyboard_frame_sha256": excerpt["sha256"],
        "storyboard_extraction_mode": excerpt["mode"],
        "visual_profile": {
            "profile_id": visual_profile["profile_id"],
            "profile_path": normalize_contract_path(visual_profile.get("profile_path")),
            "profile_sha256": visual_profile["profile_sha256"],
            "capture_profile": visual_profile["capture_profile"],
        },
        "authenticity_card": visual.get("authenticity_card") or {},
        "character_contract": character,
        "continuity": visual.get("continuity") or {},
        "environment": env.get("environment") or {},
        "active_environment_segments": env.get("active_segments") or [],
        "environment_frame_sha256": env["environment_frame_sha256"],
        "frame_directive": directive,
        "frame_directive_sha256": env["frame_directive_sha256"],
        "capture_event": capture_event.get("capture_event") or {},
        "capture_event_sha256": capture_event.get("capture_event_sha256"),
        "world_state": world.get("world_state") or {},
        "world_state_sha256": world.get("world_state_sha256"),
        "character_visual_contract": character_visual,
        "shot_progression": progression.get("shot_progression") or {},
        "temporal_state": temporal.get("temporal_state") or {},
        "wardrobe": wardrobe.get("wardrobe") or {},
        "references": refs,
    }
    if adjacent_state is not None:
        # Bound to the selected locked storyboard frame *and its predecessor*;
        # changing a prior shot invalidates only dependent opt-in frame contracts.
        hash_material["m00_adjacent_state_delta"] = adjacent_state
    if visual_narrative_active:
        hash_material["visual_narrative"] = visual_narrative.get("visual_narrative") or {}
        hash_material["visual_narrative_sha256"] = visual_narrative.get("visual_narrative_sha256")
    if world_identity_active:
        hash_material["world_identity"] = world_identity
        hash_material["world_identity_sha256"] = world_identity.get("effective_sha256")
        hash_material["character_appearance_anchor"] = character_anchor
        hash_material["character_appearance_anchor_sha256"] = character_anchor.get("anchor_sha256")
    contract_sha = sha256_json(hash_material)

    prompt_lines = [
        f"RESOLVED FRAME CONTRACT | frame={key} | sha256={contract_sha}",
        "This derived contract is mandatory. Locked sources outrank ad-hoc prompt wording.",
        "",
        "[STORYBOARD FRAME]",
        excerpt["text"] or f"localized excerpt unavailable; bind storyboard frame hash={excerpt['sha256']}",
        "",
        "[VISUAL DNA]",
        visual_profile["text"],
        "",
        "[CAPTURE / AUTHENTICITY]",
        _compact_json(visual.get("authenticity_card") or {}),
        "",
        "[CHARACTER / POV CONTRACT]",
        _compact_json(character, 2800),
        "",
        "[WORLD IDENTITY V2.2.1]" if world_identity_active else "[WORLD IDENTITY NOT APPLICABLE]",
        world_identity_contract.prompt_block(ep) if world_identity_active else "",
        "",
        "[CHARACTER APPEARANCE ANCHOR V2.2.1]" if world_identity_active else "[CHARACTER APPEARANCE ANCHOR NOT APPLICABLE]",
        character_appearance_anchor.prompt_block(ep) if world_identity_active else "",
        "",
        "[CONTINUITY]",
        _compact_json(visual.get("continuity") or {}),
        "",
        "[ENVIRONMENT PHYSICS]",
        _compact_json(env.get("environment") or {}),
        "",
        "[CAPTURE EVENT]",
        _compact_json(capture_event.get("capture_event") or {}),
        "",
        "[PERSISTENT WORLD STATE]",
        _compact_json(world.get("world_state") or {}, 2600),
        "",
        "[CHARACTER VISUAL / ORIGINAL IDENTITY]",
        _compact_json(character_visual, 2600),
        "",
        "[SHOT PROGRESSION / ACTION / ANOMALY LOGIC]",
        _compact_json(progression.get("shot_progression") or {}, 1800),
        "",
        "[TEMPORAL CONTINUITY]",
        _compact_json(temporal.get("temporal_state") or {}, 1600),
        "",
        "[SCENE-AWARE WARDROBE]",
        _compact_json(wardrobe.get("wardrobe") or {}, 2400),
        "",
        "[FRAME DIRECTIVE]",
        _compact_json(directive),
        "",
        "[REFERENCES CONTRACT]",
        _compact_json(refs),
        "",
        "Hard rule: reality constrains capture physics, not anomaly scale. "
        "Do not weaken impact_level or remove required scale references to make the scene easier.",
    ]

    if adjacent_state is not None:
        marker = prompt_lines.index("[FRAME DIRECTIVE]")
        prompt_lines[marker:marker] = [
            "[M00 STORY-LOCKED ADJACENT DELTA | exact source]",
            m00_episode_state_delta.delta.prompt_suffix(adjacent_state["delta"]),
            "",
        ]
    if visual_narrative_active:
        marker = prompt_lines.index("[FRAME DIRECTIVE]")
        prompt_lines[marker:marker] = [
            "[VISUAL NARRATIVE CORE V2.2]",
            _compact_json(visual_narrative.get("visual_narrative") or {}, 3600),
            "",
        ]

    result = {
        "schema_version": SCHEMA_VERSION,
        "story_os_version": episode_version(ep),
        "frame": key,
        "derived_cache": True,
        "authority": ("Story + Storyboard + Character Contract + Character Visual + Shot Progression + "
                      + ("Visual Narrative Core V2.2 + " if visual_narrative_active else "")
                      + ("World Identity V2.2.1 + Character Appearance Anchor + " if world_identity_active else "")
                      + "Capture Event + World State + Temporal + Wardrobe + story-gates + Visual Profile"),
        "generated_at": now(),
        "source_trace": source_trace,
        "storyboard_frame": excerpt,
        "source_binding": {
            "story": {"path": repo_rel(story_path), "sha256": source_trace["story"]["sha256"]},
            "storyboard": {"path": repo_rel(storyboard_path), "sha256": source_trace["storyboard"]["sha256"]},
            "extraction_mode": excerpt["mode"],
            "frame_sha256": excerpt["sha256"],
        },
        "identity_requirements": identity_requirements,
        "story_semantic_requirements": story_semantic_requirements,
        "story_dna_mapping": story_dna_mapping,
        "hash_material": hash_material,
        "contract_sha256": contract_sha,
        "prompt_contract": "\n".join(prompt_lines),
    }
    if adjacent_state is not None:
        result["m00_adjacent_state_delta"] = adjacent_state
    if write_cache:
        mode = storage_config.episode_meta_store_config()["mode"]
        if mode != "mysql":
            write_json(cache_write_path(ep, key), result)
        # json keeps only the compatibility cache; dual writes both; mysql
        # persists the contract without recreating the per-frame JSON cache.
        import frame_contract_persistence
        frame_contract_persistence.persist(ep, result)
    return result


@episode_contract_persistence.operation_cached
def compile_all(ep: Path) -> dict:
    ep = Path(ep).resolve()
    # E003 is created at the same canonical boundary as the resolved frame
    # contracts. It is a gate-evidence document, never a stage/state document.
    # Missing editorial fields remain visibly invalid at PUBLISH_READY rather
    # than being inferred or filled with a fabricated PASS.
    if not (ep / story_dna_trace.REL).is_file():
        story_dna_trace.build(ep)
    if required(ep):
        errors = environment_contract.verify(ep)
        if errors:
            raise ValueError("Phase 3 Environment Contract must PASS before Frame Contract compile: " + "; ".join(errors[:8]))
        vn_errors = visual_narrative_core_v22.verify_all(ep)
        if vn_errors:
            raise ValueError("V2.2 Visual Narrative Core must PASS before Frame Contract compile: " + "; ".join(vn_errors[:12]))
        if world_identity_contract.required(ep):
            wi_errors = world_identity_contract.verify(ep)
            if wi_errors:
                raise ValueError("V2.2.1 World Identity must PASS before Frame Contract compile: " + "; ".join(wi_errors[:12]))
            character_appearance_anchor.build(ep, write=True)
            ca_errors = character_appearance_anchor.verify(ep)
            if ca_errors:
                raise ValueError("V2.2.1 Character Appearance Anchor must PASS before Frame Contract compile: " + "; ".join(ca_errors[:12]))
    # The split PREIMAGE protocol has a distinct committed snapshot.  Derived
    # frame work must never start while Candidate authority is still pending.
    task_state = story_json.read_json(ep / "meta/runtime/preimage-task-state.json", default={}) or {}
    if task_state:
        import preimage_protocol
        committed_path = ep / "meta/runtime/preimage-committed-snapshot.json"
        if not preimage_protocol.barrier_ready(ep) or not committed_path.is_file():
            raise ValueError("PREIMAGE_AUTHORITY_READY required before Frame Contract compile")
        snapshot = story_json.read_json(committed_path, default={}) or {}
        if not snapshot or preimage_authority_snapshot.stale(ep, snapshot):
            raise ValueError("STALE PREIMAGE_COMMITTED_SNAPSHOT before Frame Contract compile")
    else:
        snapshot=preimage_authority_snapshot.build(ep,write=True)
    total=frame_count(ep)
    workers=int(storyos_config.get_path(storyos_config.load_config(),"runtime.workers.derived",6))
    failures=[]; compiled={}
    def one(n):
        started=runtime_node_execution.now()
        try:
            row=compile_frame(ep,n,write_cache=True)
            stale=preimage_authority_snapshot.stale(ep,snapshot)
            runtime_node_execution.record(ep,node_id="frame_contract_compile",task_id=f"frame-{n:02d}",snapshot_id=snapshot["snapshot_id"],worker_id=f"frame-{n:02d}",start_time=started,end_time=runtime_node_execution.now(),status="STALE" if stale else "PASS",stale=stale,output_sha=row["contract_sha256"],evidence=[(CACHE_ROOT/f"{n:02d}.json").as_posix()])
            if stale: raise ValueError("STALE authority snapshot")
            return row
        except Exception as exc:
            runtime_node_execution.record(ep,node_id="frame_contract_compile",task_id=f"frame-{n:02d}",snapshot_id=snapshot["snapshot_id"],worker_id=f"frame-{n:02d}",start_time=started,end_time=runtime_node_execution.now(),status="FAILED",failure_type="technical_failure",output=str(exc)[:500])
            raise
    if storyos_config.get_path(storyos_config.load_config(),"runtime.preimage_parallel_enabled",False):
        with cf.ThreadPoolExecutor(max_workers=workers,thread_name_prefix="storyos-frame") as pool:
            futures={pool.submit(contextvars.copy_context().run,one,n):n for n in range(1,total+1)}
            for future,n in [(f,futures[f]) for f in cf.as_completed(futures)]:
                try: compiled[n]=future.result()
                except Exception as exc: failures.append(f"frame {n:02d}: {exc}")
    else:
        for n in range(1,total+1):
            try: compiled[n]=one(n)
            except Exception as exc: failures.append(f"frame {n:02d}: {exc}")
    if failures: raise ValueError("Frame Contract compile failures: "+"; ".join(failures))
    if preimage_authority_snapshot.stale(ep,snapshot): raise ValueError("STALE authority snapshot before frame index commit")
    rows = []
    for n in range(1,total + 1):
        row=compiled[n]
        rows.append({
            "frame": row["frame"],
            "path": (CACHE_ROOT / f"{row['frame']}.json").as_posix(),
            "contract_sha256": row["contract_sha256"],
            "storyboard_frame_sha256": row["hash_material"]["storyboard_frame_sha256"],
            "environment_frame_sha256": row["hash_material"]["environment_frame_sha256"],
            "frame_directive_sha256": row["hash_material"]["frame_directive_sha256"],
        })
    index = {
        "schema_version": 1,
        "story_os_version": episode_version(ep),
        "derived_cache": True,
        "compiled_at": now(),
        "frame_count": len(rows),
        "frames": rows,
        "index_sha256": sha256_json(rows),
    }
    write_json(ep / INDEX_REL, index)
    return index


def cache_rel(frame: int | str) -> Path:
    return CACHE_ROOT / f"{int(frame):02d}.json"


def cache_read_path(ep: Path, frame: int | str) -> Path:
    return runtime_workspace.resolve_read_path(Path(ep).resolve(), cache_rel(frame))


def cache_write_path(ep: Path, frame: int | str) -> Path:
    return runtime_workspace.workspace_path(Path(ep).resolve(), cache_rel(frame))


def cache_read_dirs(ep: Path) -> tuple[Path, ...]:
    return runtime_workspace.read_candidates(Path(ep).resolve(), CACHE_ROOT)


def cache_path(ep: Path, frame: int | str) -> Path:
    """Backward-compatible physical read path for the derived frame cache."""
    return cache_read_path(ep, frame)


def load_cached_contract(ep: Path, frame: int | str) -> dict | None:
    """Repository-first read in dual mode, with the physical cache as fallback."""
    import frame_contract_persistence

    return frame_contract_persistence.load_latest(
        Path(ep).resolve(), frame, legacy_path=cache_read_path(ep, frame)
    )


def materialize_export(ep: Path, frame: int | str) -> Path:
    """Materialize the current resolved contract for tools that require a file input.

    MySQL mode intentionally does not recreate the legacy per-frame cache. Review
    adapters still need an immutable source file to attach, so export the verified
    repository-backed payload into Runtime Workspace without changing authority.
    """
    ep = Path(ep).resolve()
    key = f"{int(frame):02d}"
    payload = load_cached_contract(ep, frame)
    if not isinstance(payload, dict):
        payload = compile_frame(ep, frame, write_cache=True)
        payload = load_cached_contract(ep, frame) or payload
    current = compile_frame(ep, frame, write_cache=False)
    if str(payload.get("contract_sha256") or "").lower() != str(current.get("contract_sha256") or "").lower():
        if not recorded_contract_matches_current(ep, frame, payload.get("contract_sha256")):
            raise ValueError(f"frame {key} resolved contract stale")
    return runtime_workspace.write_json(ep, EXPORT_ROOT / f"{key}.json", payload)


def _monotonic_projection_fill(old: object, new: object) -> bool:
    """Allow only empty->derived-value completion; never rewrite existing authority."""
    if old is None or old == "":
        return True
    if isinstance(old, dict):
        if not isinstance(new, dict):
            return False
        return all(key in new and _monotonic_projection_fill(value, new[key]) for key, value in old.items())
    if isinstance(old, list):
        return old == new
    return old == new


def _projection_only_upgrade(cached: dict, current: dict) -> bool:
    old_material = cached.get("hash_material") or {}
    new_material = current.get("hash_material") or {}
    if not isinstance(old_material, dict) or not isinstance(new_material, dict):
        return False
    old_rest = dict(old_material)
    new_rest = dict(new_material)
    old_auth = old_rest.pop("authenticity_card", None)
    new_auth = new_rest.pop("authenticity_card", None)
    old_cont = old_rest.pop("continuity", None)
    new_cont = new_rest.pop("continuity", None)
    return (
        old_rest == new_rest
        and _monotonic_projection_fill(old_auth, new_auth)
        and _monotonic_projection_fill(old_cont, new_cont)
    )


def _migration_rows(ep: Path) -> list[dict]:
    data = story_json.read_json(Path(ep).resolve() / PROJECTION_MIGRATION_REL, default={})
    rows = data.get("items") if isinstance(data, dict) else []
    return rows if isinstance(rows, list) else []


def _contract_exception_rows(ep: Path) -> list[dict]:
    """Read explicit user-approved old-contract bindings for this Episode.

    These bindings are a narrow compatibility boundary for already generated
    pixels. They never rewrite the current Frame Contract and require direct
    user approval recorded in the sidecar.
    """
    data = story_json.read_json(Path(ep).resolve() / CONTRACT_EXCEPTION_REL, default={})
    rows = data.get("items") if isinstance(data, dict) else []
    return rows if isinstance(rows, list) else []


def recorded_contract_matches_current(ep: Path, frame: int | str, recorded_sha256: str) -> bool:
    """Accept exact SHA or a recorded, strictly projection-only old->new migration."""
    ep = Path(ep).resolve()
    key = f"{int(frame):02d}"
    recorded = str(recorded_sha256 or "").lower()
    current = compile_frame(ep, frame, write_cache=False)
    current_sha = str(current.get("contract_sha256") or "").lower()
    if recorded and recorded == current_sha:
        return True
    for row in _contract_exception_rows(ep):
        if (
            str(row.get("frame") or "").zfill(2) == key
            and str(row.get("from_contract_sha256") or "").lower() == recorded
            and str(row.get("to_contract_sha256") or "").lower() == current_sha
            and row.get("user_approved") is True
            and row.get("delegated_auto_review") is False
            and str(row.get("approval_basis") or "") == "direct_user_contract_exception"
            and str(row.get("user_statement") or "").strip()
        ):
            return True
    for row in _migration_rows(ep):
        if (
            str(row.get("frame") or "").zfill(2) == key
            and str(row.get("from_contract_sha256") or "").lower() == recorded
            and str(row.get("to_contract_sha256") or "").lower() == current_sha
            and row.get("reason") == "machine_visual_projection_only"
        ):
            return True
    path = cache_path(ep, frame)
    if not recorded or not path.is_file():
        return False
    try:
        cached = read_json(path)
    except Exception:
        return False
    return (
        str(cached.get("contract_sha256") or "").lower() == recorded
        and _projection_only_upgrade(cached, current)
    )


def record_projection_migrations(ep: Path) -> dict:
    """Freeze semantic-equivalence evidence before refreshing derived frame caches."""
    ep = Path(ep).resolve()
    existing = story_json.read_json(ep / PROJECTION_MIGRATION_REL, default={})
    items = list(existing.get("items") or []) if isinstance(existing, dict) else []
    known = {
        (str(row.get("frame") or "").zfill(2), str(row.get("from_contract_sha256") or "").lower(), str(row.get("to_contract_sha256") or "").lower())
        for row in items if isinstance(row, dict)
    }
    added = []
    for frame in range(1, frame_count(ep) + 1):
        cached = load_cached_contract(ep, frame)
        if not isinstance(cached, dict):
            continue
        current = compile_frame(ep, frame, write_cache=False)
        old_sha = str(cached.get("contract_sha256") or "").lower()
        new_sha = str(current.get("contract_sha256") or "").lower()
        if not old_sha or old_sha == new_sha:
            continue
        if not _projection_only_upgrade(cached, current):
            continue
        marker = (f"{frame:02d}", old_sha, new_sha)
        if marker in known:
            continue
        row = {
            "frame": f"{frame:02d}",
            "from_contract_sha256": old_sha,
            "to_contract_sha256": new_sha,
            "reason": "machine_visual_projection_only",
            "allowed_projection_keys": ["authenticity_card", "continuity"],
            "recorded_at": now(),
        }
        items.append(row)
        added.append(row)
        known.add(marker)
    if added:
        story_json.write_json(ep / PROJECTION_MIGRATION_REL, {
            "schema_version": 1,
            "items": items,
        })
    return {"status": "PASS", "added": added, "count": len(added)}


def provenance(ep: Path, frame: int | str) -> dict | None:
    if not required(ep):
        return None
    row = compile_frame(ep, frame, write_cache=True)
    return {
        "schema_version": SCHEMA_VERSION,
        "path": (CACHE_ROOT / f"{row['frame']}.json").as_posix(),
        "contract_sha256": row["contract_sha256"],
    }


def verify_frame(ep: Path, frame: int | str) -> list[str]:
    if not required(ep):
        return []
    current = compile_frame(ep, frame, write_cache=False)
    cached = load_cached_contract(ep, frame)
    return _verify_compiled_frame(ep, frame, current, cached)


def _verify_compiled_frame(ep: Path, frame: int | str, current: dict, cached: object) -> list[str]:
    if not isinstance(cached, dict):
        return [f"resolved frame contract cache missing: {cache_rel(frame).as_posix()}"]
    errors = []
    if cached.get("derived_cache") is not True:
        errors.append(f"frame {int(frame):02d} cache must declare derived_cache=true")
    if cached.get("contract_sha256") != current["contract_sha256"] and not recorded_contract_matches_current(ep, frame, cached.get("contract_sha256")):
        errors.append(f"frame {int(frame):02d} resolved contract stale")
    if cached.get("frame") != current["frame"]:
        errors.append(f"frame {int(frame):02d} cache frame mismatch")
    return errors


@episode_contract_persistence.operation_cached
def verify_all(ep: Path) -> list[str]:
    if not required(ep):
        return []
    errors = []
    try:
        total = frame_count(ep)
        env_errors = environment_contract.verify(ep)
        if env_errors:
            errors.extend(env_errors)
            return errors
        compiled = []
        for n in range(1, total + 1):
            current = compile_frame(ep, n, write_cache=False)
            cached = load_cached_contract(ep, n)
            errors.extend(_verify_compiled_frame(ep, n, current, cached))
            compiled.append((current, cached))
        index_path = ep / INDEX_REL
        if not index_path.is_file():
            errors.append("frame-contract-index.json missing; run compile-all")
        else:
            idx = read_json(index_path)
            rows = idx.get("frames")
            if not isinstance(rows, list) or len(rows) != total:
                errors.append("frame contract index frame count mismatch")
            else:
                expected = []
                for n, (row, cached) in enumerate(compiled, start=1):
                    effective_contract_sha = row["contract_sha256"]
                    if isinstance(cached, dict):
                        cached_sha = str(cached.get("contract_sha256") or "")
                        if cached_sha and recorded_contract_matches_current(ep, n, cached_sha):
                            # Keep the committed PREIMAGE index immutable when the
                            # only delta is a recorded machine projection fill.
                            effective_contract_sha = cached_sha
                    expected.append({
                        "frame": row["frame"],
                        "path": (CACHE_ROOT / f"{row['frame']}.json").as_posix(),
                        "contract_sha256": effective_contract_sha,
                        "storyboard_frame_sha256": row["hash_material"]["storyboard_frame_sha256"],
                        "environment_frame_sha256": row["hash_material"]["environment_frame_sha256"],
                        "frame_directive_sha256": row["hash_material"]["frame_directive_sha256"],
                    })
                if idx.get("index_sha256") != sha256_json(expected):
                    errors.append("frame contract index stale")
    except Exception as exc:
        errors.append(str(exc))
    return errors


def verify_recorded_provenance(ep: Path, frame: int | str, recorded: object) -> list[str]:
    if not required(ep):
        return []
    if not isinstance(recorded, dict):
        return [f"frame {int(frame):02d} generation request missing frame_contract provenance"]
    current = compile_frame(ep, frame, write_cache=False)
    errors = []
    if not recorded_contract_matches_current(ep, frame, str(recorded.get("contract_sha256") or "")):
        errors.append(f"frame {int(frame):02d} generation frame_contract_sha256 stale")
    expected_path = (CACHE_ROOT / f"{int(frame):02d}.json").as_posix()
    if str(recorded.get("path") or "") != expected_path:
        errors.append(f"frame {int(frame):02d} generation frame_contract path mismatch")
    return errors


def verify_approved_asset_binding(ep: Path, frame: int | str, asset_sha256: str) -> list[str]:
    """Prove the approved pixels came from an attempt bound to the current frame contract."""
    if not required(ep):
        return []
    key = f"{int(frame):02d}"
    try:
        ledger = production_ledger.load_authority(ep, default=None)
        if not isinstance(ledger, dict):
            return [f"frame {key} production ledger missing for frame-contract binding"]
        row = (ledger.get("frames") or {}).get(key)
        if not isinstance(row, dict):
            return [f"frame {key} production ledger row missing"]
        approved = row.get("approved_asset") or {}
        if str(approved.get("sha256") or "").lower() != str(asset_sha256 or "").lower():
            return [f"frame {key} approved asset SHA not bound by production ledger"]
        matched = None
        for attempt in reversed(row.get("attempts") or []):
            candidate = attempt.get("candidate") or {}
            if str(candidate.get("sha256") or "").lower() == str(asset_sha256 or "").lower():
                matched = attempt
                break
        if not isinstance(matched, dict):
            return [f"frame {key} no generation attempt matches approved asset SHA"]
        return verify_recorded_provenance(ep, key, (matched.get("request") or {}).get("frame_contract"))
    except Exception as exc:
        return [f"frame {key} frame-contract ledger verification failed: {exc}"]


def self_test() -> None:
    assert version_tuple("2.1.0") >= MIN_VERSION
    assert sha256_json({"b": 2, "a": 1}) == sha256_json({"a": 1, "b": 2})
    sample = {"frames": [{"frame": 2, "beat": "x"}, {"frame": 3, "beat": "y"}]}
    assert (_frame_from_json(sample, 2) or {}).get("beat") == "x"
    print("RESOLVED FRAME CONTRACT V2.1 PHASE4 SELF-TEST PASS")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("compile-all"); p.add_argument("episode_dir")
    p = sub.add_parser("compile"); p.add_argument("episode_dir"); p.add_argument("--frame", type=int, required=True)
    p = sub.add_parser("verify"); p.add_argument("episode_dir"); p.add_argument("--frame", type=int)
    p = sub.add_parser("show"); p.add_argument("episode_dir"); p.add_argument("--frame", type=int, required=True); p.add_argument("--prompt", action="store_true")
    sub.add_parser("self-test")
    args = ap.parse_args()
    if args.cmd == "self-test":
        self_test(); return 0
    ep = resolve_ep(args.episode_dir)
    try:
        if args.cmd == "compile-all":
            idx = compile_all(ep)
            print(f"FRAME CONTRACT COMPILE PASS: {idx['frame_count']} frames index_sha256={idx['index_sha256']}")
            return 0
        if args.cmd == "compile":
            row = compile_frame(ep, args.frame, write_cache=True)
            print(json.dumps({"frame": row["frame"], "contract_sha256": row["contract_sha256"], "path": (CACHE_ROOT / f"{row['frame']}.json").as_posix()}, ensure_ascii=False, indent=2))
            return 0
        if args.cmd == "show":
            row = compile_frame(ep, args.frame, write_cache=False)
            print(row["prompt_contract"] if args.prompt else json.dumps(row, ensure_ascii=False, indent=2))
            return 0
        errors = verify_frame(ep, args.frame) if args.frame else verify_all(ep)
        if errors:
            for error in errors:
                print("FAIL:", error)
            return 2
        print("RESOLVED FRAME CONTRACT VERIFIED")
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print("FRAME CONTRACT ERROR:", exc)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
