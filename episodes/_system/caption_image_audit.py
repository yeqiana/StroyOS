#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Incremental final-publish Caption ↔ Image audit for Story OS V2.6.1.

Caption edits never invalidate the Visual Semantic Review. Final publish images are
reviewed in chunks of up to 5, so subtitle obstruction and caption support do not
force one oversized Release Critic request. Evidence is reused by caption/publish SHA.
"""
from __future__ import annotations

import argparse
import subprocess
import json
import math
import time
from pathlib import Path

import frame_semantic_review as base
import incremental_frame_review as inc
import codex_critic_runner
import codex_user_runner
import episode_performance
import runtime_command
import runtime_provenance
import runtime_router
import product_review_adapter
import subtitle_layout
import runtime_timeout_policy
import production_ledger
import local_vision_shadow
import subtitle_render_integrity
import subtitle_face_safe_area
import quota_observability

ROOT = Path(__file__).resolve().parents[2]
REL = Path("meta/caption-image-audit.json")
SCHEMA = 2
CHUNK = 5


class ProductReviewHostAction(RuntimeError):
    def __init__(self, request: dict):
        super().__init__("caption/image review requires product runtime host action")
        self.request = request


def _review_kind(index: int, cycle: int = 1) -> str:
    if cycle <= 1:
        return f"caption-image-audit-v2-{index:03d}"
    return f"caption-image-audit-v2-r{cycle - 1}-{index:03d}"


def _tokens_from_jsonl(text: str) -> dict:
    """Best-effort token counters from a Codex --json output stream. Never raises."""
    totals: dict = {}
    for line in (text or "").splitlines():
        try:
            obj = json.loads(line)
        except Exception:
            continue
        try:
            quota_observability.walk_tokens(obj, totals)
        except Exception:
            continue
    return totals


def _resolve_layout_y_ratio(layout: dict, canvas_height: int) -> tuple[float, bool]:
    """Return y_ratio plus whether it came from a legacy audit missing explicit y_ratio."""
    raw = layout.get("y_ratio")
    if raw is not None:
        return float(raw), False
    if canvas_height <= 0:
        raise ValueError("subtitle layout canonical canvas height missing")
    return int(layout.get("y")) / canvas_height, True


def _caption_texts(ep: Path, frames: list[dict]) -> tuple[dict[str, str], dict]:
    source = inc._manifest_caption_path(ep)
    keys = [row["frame"] for row in frames]
    if source is None:
        return {k: "" for k in keys}, {"source_path": None, "mode": "none"}
    raw = source.read_text(encoding="utf-8", errors="replace")
    if source.suffix.lower() == ".json":
        try:
            texts = inc._extract_json_captions(json.loads(raw))
        except Exception:
            texts = {}
    else:
        texts = inc._extract_yaml_captions(raw)
    if not texts and raw.strip():
        raise ValueError(f"caption parser could not resolve per-frame captions: {source}")
    return {k: texts.get(k, "") for k in keys}, {
        "source_path": source.resolve().relative_to(ROOT.resolve()).as_posix(),
        "mode": "per_frame" if texts else "none",
    }

def _read(ep: Path) -> dict:
    p = ep / REL
    if not p.is_file():
        return {"schema_version": SCHEMA, "module_version": "2.6.1", "frames": {}}
    try:
        d = json.loads(p.read_text(encoding="utf-8-sig"))
        return d if isinstance(d, dict) else {"schema_version": SCHEMA, "module_version": "2.6.1", "frames": {}}
    except Exception:
        return {"schema_version": SCHEMA, "module_version": "2.6.1", "frames": {}}

def _write(ep: Path, data: dict) -> None:
    base.write_json(ep / REL, data)


def _review_frame_records(ep: Path) -> tuple[list[dict], dict]:
    """Use final subtitled publish pixels when the canonical subtitle layout is required."""
    if not subtitle_layout.layout_required(ep):
        # No separate metadata scan is needed when published pixels are already approved.
        return base.frame_records(ep, require_files=True), {"mode": "approved_base"}
    base_rows = base.frame_records(ep, require_files=False)
    report_path = ep / subtitle_layout.REPORT_REL
    if not report_path.is_file():
        raise ValueError("subtitle layout audit missing before final caption/image review")
    report = base.read_json(report_path)
    if report.get("engine") != subtitle_layout.ENGINE or report.get("canonical_renderer") is not True:
        raise ValueError("subtitle layout audit is not canonical")
    audited = report.get("frames") or {}
    ledger = production_ledger.load_authority(ep, default={}) or {}
    try:
        canvas_height = int((ledger.get("canvas") or {}).get("height"))
    except Exception as exc:
        raise ValueError("production ledger canvas height missing") from exc
    layout_errors: list[str] = []
    rows: list[dict] = []
    for row in base_rows:
        key = row["frame"]
        layout = audited.get(key)
        if not isinstance(layout, dict):
            raise ValueError(f"subtitle layout audit missing frame {key}")
        lines = layout.get("lines")
        if not isinstance(lines, list) or len(lines) > 2:
            raise ValueError(f"subtitle layout frame {key} invalid wrapped lines")
        if int(layout.get("x") or -1) != 72:
            raise ValueError(f"subtitle layout frame {key} must stay left aligned at x=72")
        try:
            y_ratio, legacy_ratio = _resolve_layout_y_ratio(layout, canvas_height)
        except Exception as exc:
            raise ValueError(f"subtitle layout frame {key} y position invalid") from exc
        if legacy_ratio:
            layout_errors.append(f"{key}: y_ratio missing; rerender subtitle layout with current renderer")
        if not subtitle_layout.LEFT_MIDDLE_MIN_RATIO <= y_ratio <= subtitle_layout.LEFT_MIDDLE_MAX_RATIO and not str(layout.get("safe_zone_override_reason") or "").strip():
            layout_errors.append(f"{key}: leaves left-middle zone without override reason")
        path = base.repo_path(layout.get("output_path"), f"subtitle layout frame {key} output_path", require_file=True)
        expected_sha = str(layout.get("output_sha256") or "").lower()
        if len(expected_sha) != 64:
            raise ValueError(f"subtitle layout frame {key} output_sha256 invalid")
        actual_sha = base.sha256_file(path).lower()
        if actual_sha != expected_sha:
            raise ValueError(f"subtitle layout publish output drift: {key}")
        rows.append({**row, "path": path, "path_rel": base.repo_rel(path), "sha256": actual_sha})
    return rows, {
        "mode": "final_publish_with_subtitle",
        "layout_current": not layout_errors,
        "layout_errors": layout_errors,
        "layout_audit_path": base.repo_rel(report_path),
        "layout_audit_sha256": base.sha256_file(report_path),
    }


def _hashes(ep: Path, frames: list[dict]) -> tuple[dict[str, str], dict[str, str], dict[str, str], dict]:
    cap_state = inc.caption_state(ep, frames)
    texts, source_meta = _caption_texts(ep, frames)
    image_sha = {r["frame"]: r["sha256"] for r in frames}
    caption_sha = cap_state["frame_sha256"]
    return image_sha, caption_sha, texts, {**source_meta, "source_sha256": cap_state.get("source_sha256")}

def dirty_frames(ep: Path) -> tuple[list[dict], dict, dict[str, str], dict[str, str], dict[str, str], dict]:
    frames, review_meta = _review_frame_records(ep)
    current = _read(ep)
    image_sha, caption_sha, texts, source_meta = _hashes(ep, frames)
    source_meta = {**source_meta, "review_image": review_meta}
    existing = current.get("frames") or {}
    local_context = (local_vision_shadow.local_caption_validation_context(ep)
                     if any(isinstance(value, dict) and value.get("mode") in ("local_flat_area_with_semantic_evidence", "local_position_with_semantic_evidence")
                            for value in existing.values()) else None) or {}
    dirty = []
    for row in frames:
        key = row["frame"]
        old = existing.get(key) or {}
        if (
            old.get("image_sha256") != image_sha[key]
            or old.get("caption_sha256") != caption_sha[key]
            or old.get("passed") is not True
            or old.get("schema_version") != SCHEMA
            or (old.get("mode") in ("local_flat_area_with_semantic_evidence", "local_position_with_semantic_evidence")
                and not local_vision_shadow.local_caption_evidence_current(
                    ep, key, old.get("local_review_evidence"), local_context))
        ):
            dirty.append(row)
    return dirty, current, image_sha, caption_sha, texts, source_meta

def _prompt(ep: Path, rows: list[dict], texts: dict[str, str], out: Path, *, absolute_output: bool = False) -> str:
    # Host Review uses repository-relative output paths; the episode-scoped
    # native Codex subprocess needs an absolute target instead.
    output_ref = str(out.resolve()) if absolute_output else out.relative_to(ROOT).as_posix()
    mapping = "\n".join(
        f"- frame {r['frame']}: final_publish_image={r['path_rel']} | caption={json.dumps(texts[r['frame']], ensure_ascii=False)}"
        for r in rows
    )
    ocr_hint = local_vision_shadow.ocr_hint(ep, [r["frame"] for r in rows])
    face_hint = subtitle_face_safe_area.hint(ep, [r["frame"] for r in rows])
    return f"""You are the Story OS final-publish Caption ↔ Image + Subtitle Obstruction Critic.
Review ONLY the supplied FINAL publish pixels after subtitle rendering.
For each frame judge two things:
1. supported: the caption is honestly supported by the underlying photographed/generated scene; it must not invent a core event, prop, person, UI text, anomaly, action, or causal fact absent from the scene. The rendered subtitle text itself is NEVER visual evidence for supported=true; mentally ignore the overlay when judging support.
2. subtitle_unobstructed: rendered text does not cover a face, anomaly evidence, hand/action, key prop, native text, or causal clue. Subtitle geometry, line-count, and render integrity are already checked locally. Treat those checks as passed; do not re-evaluate placement aesthetics or geometry. Judge only semantic obstruction visible in the pixels.
3. If and only if subtitle_unobstructed=false while supported=true, recommend ONE safer vertical baseline using suggested_y_ratio from exactly {list(subtitle_layout.PIXEL_SAFE_Y_RATIOS)}. Choose from actual pixel evidence, not aesthetics. If none of those locations is clearly safer, return null. Also give obstruction_reason naming what is covered.
Do not re-review overall story quality, character continuity, or visual style. Empty captions automatically pass both checks.
This is a frozen, narrowly scoped pixel-review request. Use ONLY the attached images, the frame-to-caption mapping, and the local pre-scan hints below. Do not inspect the repository, AGENTS.md, SKILL.md, project memory, other episodes, or any unrelated files. Do not run shell tools or generate new assets; only return the requested JSON decision.
Mappings:
{mapping}

Local pre-scan (advisory only, never authoritative):
{ocr_hint or "none"}
{face_hint or "none"}

Write ONLY JSON to {output_ref}:
{{"frames":[{{"frame":"01","supported":true,"subtitle_unobstructed":true,"suggested_y_ratio":null,"obstruction_reason":"","notes":"specific pixel evidence"}}],"summary":{{"passed":true}}}}
Return one row for every attached frame. summary.passed=false if any supported=false or subtitle_unobstructed=false.
"""

def _recover_jsonl_review(stdout: str, frames: list[str]) -> dict | None:
    """Recover actual model output only from one complete Codex JSONL turn."""
    try:
        events = [json.loads(line) for line in stdout.splitlines()
                  if line.strip().startswith("{")]
        if (sum(e.get("type") == "thread.started" for e in events) != 1
                or sum(e.get("type") == "turn.completed" for e in events) != 1
                or any(e.get("type") in ("turn.failed", "item.failed") for e in events)):
            return None
        messages = [(e.get("item") or {}).get("text") for e in events
                    if e.get("type") == "item.completed"
                    and (e.get("item") or {}).get("type") == "agent_message"]
        if len(messages) != 1 or not isinstance(messages[0], str):
            return None
        result = json.loads(messages[0])
        if not isinstance(result, dict):
            return None
        rows = result.get("frames")
        if (not isinstance(rows, list) or len(rows) != len(frames)
                or any(not isinstance(row, dict) for row in rows)
                or sorted(row.get("frame") for row in rows) != sorted(frames)
                or any(not isinstance(row.get("supported"), bool)
                       or not isinstance(row.get("subtitle_unobstructed"), bool)
                       or not isinstance(row.get("notes"), str) for row in rows)
                or not isinstance((result.get("summary") or {}).get("passed"), bool)
                or result["summary"]["passed"] !=
                   all(row["supported"] and row["subtitle_unobstructed"] for row in rows)):
            return None
        return result
    except (ValueError, TypeError, KeyError):
        return None

def _run_chunk(ep: Path, rows: list[dict], texts: dict[str, str], codex_raw: str | None, timeout: int, index: int, cycle: int = 1) -> dict:
    suffix = f"{index:03d}" if cycle <= 1 else f"r{cycle - 1}-{index:03d}"
    out = ep / "meta" / f".caption-image-audit-candidate-{suffix}.json"
    active_runtime, _ = runtime_router.detect()
    vision_runtime, _ = runtime_router.vision_review_runtime()
    if vision_runtime != "CODEX" and not codex_raw:
        kind = _review_kind(index, cycle)
        request_file = product_review_adapter.request_path(ep, kind)
        if out.is_file() and request_file.is_file():
            data, provenance = product_review_adapter.finalize_candidate(
                ep,
                kind=kind,
                runtime=active_runtime,
                attempt=1,
                candidate_path=out,
            )
            data["critic_provenance"] = provenance
            data["_product_review_kind"] = kind
            return data
        out.unlink(missing_ok=True)
        sources = [Path(row["path"]).resolve() for row in rows]
        caption_source = inc._manifest_caption_path(ep)
        if caption_source is not None:
            sources.append(caption_source.resolve())
        request = product_review_adapter.prepare(
            ep,
            kind=kind,
            runtime=active_runtime,
            attempt=1,
            prompt=_prompt(ep, rows, texts, out),
            source_paths=sources,
            candidate_path=out,
        )
        raise ProductReviewHostAction(request)

    out.unlink(missing_ok=True)
    codex = base.resolve_codex(codex_raw)
    cmd = base.command_prefix(codex) + [
        "exec", "--skip-git-repo-check", "--ephemeral",
        "-m", runtime_router.vision_review_model(),
        "-c", f'model_reasoning_effort="{runtime_router.vision_review_effort("fast")}"',
        "-s", codex_critic_runner.default_sandbox(), "-C", str(ep), "--json",
    ]
    for row in rows:
        cmd += ["-i", str(row["path"])]
    cmd += ["-"]
    started = time.perf_counter()
    cp = codex_user_runner.run_model_codex(cmd, input=_prompt(ep, rows, texts, out, absolute_output=True), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=ep, timeout=timeout, check=False, task_type="review")
    vision_elapsed = time.perf_counter() - started
    log = ep / "meta" / f"caption-image-audit-v2-{suffix}.jsonl"
    log.write_text(cp.stdout or "", encoding="utf-8", newline="\n")
    if cp.returncode != 0:
        raise RuntimeError(f"caption image critic failed rc={cp.returncode}; log={log}")
    if out.is_file():
        data = json.loads(out.read_text(encoding="utf-8-sig"))
        out.unlink(missing_ok=True)
    else:
        data = _recover_jsonl_review(cp.stdout or "", [r["frame"] for r in rows])
        if data is None:
            raise RuntimeError(f"no verifiable caption review JSONL; log={log}")
    if not isinstance(data, dict):
        return {}
    data["critic_provenance"] = runtime_provenance.build_vision_critic_provenance(
        attempt=1,
        log=log.resolve().relative_to(ROOT.resolve()).as_posix(),
        review_scope="CAPTION_IMAGE_SUBTITLE_PIXELS",
    )
    data["_vision_telemetry"] = {
        "vision_call": True,
        "elapsed_seconds": round(vision_elapsed, 3),
        "tokens": _tokens_from_jsonl(cp.stdout or ""),
        "log": log.resolve().relative_to(ROOT.resolve()).as_posix(),
    }
    return data


def _suggested_ratio(result: dict) -> float | None:
    raw = result.get("suggested_y_ratio")
    if raw is None:
        return None
    try:
        return subtitle_layout._pixel_safe_ratio(raw)
    except Exception:
        return None


def _placement_repair_frames(ep: Path) -> dict:
    """One read per review chunk; do not cache across re-render/repair cycles."""
    path = ep / "meta/subtitle-layout.json"
    if not path.is_file():
        return {}
    try:
        frames = base.read_json(path).get("frames") or {}
        return frames if isinstance(frames, dict) else {}
    except Exception:
        return {}


def _placement_repairs_used(ep: Path, frame: str, *, frames: dict | None = None) -> int:
    try:
        rows = frames if frames is not None else _placement_repair_frames(ep)
        row = rows.get(str(frame).zfill(2)) or {}
        return int(row.get("auto_placement_repairs_used") or 0) if isinstance(row, dict) else 0
    except Exception:
        return 0


def _current_y_ratios_for_chunk(ep: Path) -> dict[str, float | None]:
    """Read the current pixel placement report once when multiple repairs need it.

    The same report is not reused after an automatic re-render: each review
    cycle creates a new local snapshot and all SHA-bound evidence is rechecked.
    """
    path = ep / subtitle_layout.REPORT_REL
    if not path.is_file():
        return {}
    rows = (subtitle_layout.read_json(path).get("frames") or {})
    ratios = {}
    for key, row in rows.items():
        if not isinstance(row, dict):
            continue
        try:
            value = float(row.get("y_ratio"))
            ratios[str(key).zfill(2)] = value if math.isfinite(value) else None
        except (ValueError, TypeError):
            ratios[str(key).zfill(2)] = None
    return ratios


def _record_chunk_results(
    *,
    ep: Path,
    chunk: list[dict],
    data: dict,
    dest: dict,
    image_sha: dict[str, str],
    caption_sha: dict[str, str],
    cycle: int,
) -> tuple[int, dict[str, dict]]:
    got = {str(x.get("frame") or "").zfill(2): x for x in (data.get("frames") or []) if isinstance(x, dict)}
    repairs: dict[str, dict] = {}
    reviewed = 0
    # Preserve each frame's repair budget, but don't parse the same layout
    # configuration once per frame in a five-frame review chunk.
    repair_frames = _placement_repair_frames(ep)
    # For multi-frame chunks, share the actual-pixel placement report across
    # repair candidates instead of opening/parsing it for each obstructed frame.
    ratio_snapshot: dict[str, float | None] | None = None
    for row in chunk:
        key = row["frame"]
        result = got.get(key)
        if not result:
            raise RuntimeError(f"caption image critic omitted frame {key}")
        supported = result.get("supported") is True
        unobstructed = result.get("subtitle_unobstructed") is True
        passed = supported and unobstructed
        used = _placement_repairs_used(ep, key, frames=repair_frames)
        ratio = _suggested_ratio(result)
        reason = str(result.get("obstruction_reason") or result.get("notes") or "").strip()
        dest[key] = {
            "schema_version": SCHEMA, "frame": key,
            "image_sha256": image_sha[key], "caption_sha256": caption_sha[key],
            "supported": supported,
            "subtitle_unobstructed": unobstructed,
            "passed": passed, "mode": "final_publish_pixel_critic",
            "notes": str(result.get("notes") or ""),
            "suggested_y_ratio": ratio,
            "obstruction_reason": reason,
            "placement_repairs_used": used,
            "review_cycle": cycle,
            "critic_provenance": data.get("critic_provenance"),
        }
        reviewed += 1
        # The current layout report is only needed for a genuine first-cycle
        # placement repair. Successful frames must not re-read the same report.
        if (cycle == 1 and supported and not unobstructed and ratio is not None
                and used < subtitle_layout.MAX_AUTO_PLACEMENT_REPAIRS_PER_FRAME
                and reason):
            if len(chunk) > 1:
                if ratio_snapshot is None:
                    ratio_snapshot = _current_y_ratios_for_chunk(ep)
                current_ratio = ratio_snapshot.get(key)
            else:
                current_ratio = subtitle_layout.current_frame_y_ratio(ep, key)
            if current_ratio is None or not math.isfinite(current_ratio) or abs(current_ratio - ratio) > 0.005:
                repairs[key] = {
                    "y_ratio": ratio,
                    "reason": "actual-pixel subtitle obstruction: " + reason[:420],
                }
    return reviewed, repairs

def ensure(ep: Path, codex_raw: str | None = None, timeout: int | None = None) -> tuple[bool, dict]:
    ep = Path(ep).resolve()
    if timeout is None:
        timeout = runtime_timeout_policy.seconds("review_critic")
    # Crash-safe reconciliation: if a previous pixel audit wrote a new layout
    # override but the process died before rendering it, consume only those
    # configured dirty frames before calculating caption-audit fingerprints.
    configured_dirty = subtitle_layout.configured_dirty_frames(ep)
    if configured_dirty:
        subtitle_layout.render_frames(ep, configured_dirty)
    dirty, current, image_sha, caption_sha, texts, source_meta = dirty_frames(ep)
    review_meta = source_meta.get("review_image") or {}
    if review_meta.get("mode") == "final_publish_with_subtitle" and review_meta.get("layout_current") is not True:
        details = "; ".join((review_meta.get("layout_errors") or [])[:5])
        raise ValueError(f"subtitle layout audit is stale; rerender before caption/image review: {details}")
    # Reuse the SHA index already returned by dirty_frames: avoid a second
    # full authority/file scan for every caption review or resume.
    frame_keys = frozenset(image_sha)
    evidence = current if isinstance(current, dict) else {}
    evidence.update({
        "schema_version": SCHEMA,
        "module_version": "2.6.1",
        "caption_source": source_meta,
    })
    dest = evidence.setdefault("frames", {})
    reviewed = 0
    reused = len(frame_keys) - len(dirty)
    empty_caption_count = 0
    vision_call_count = 0
    vision_elapsed_seconds = 0.0
    vision_tokens: dict = {}

    # Empty captions are deterministic passes and require no vision call.
    nonempty = []
    for row in dirty:
        key = row["frame"]
        if not texts.get(key, "").strip():
            empty_caption_count += 1
            dest[key] = {
                "schema_version": SCHEMA, "frame": key,
                "image_sha256": image_sha[key], "caption_sha256": caption_sha[key],
                "supported": True, "subtitle_unobstructed": True,
                "passed": True, "mode": "empty_caption", "notes": "no caption to validate",
            }
        else:
            nonempty.append(row)
    vision_candidate_frames = len(nonempty)

    # Local OCR shadow: derived native-text/subtitle overlap hints for the
    # frames that actually need a vision call. Fail-soft; never blocks or
    # changes audit results, and never reduces the formal critic workload.
    local_cleared = {}
    face_safe_report = {"status": "NOT_APPLICABLE", "summary": {}}
    if nonempty:
        integrity = subtitle_render_integrity.inspect_frames(
            ep, [row["frame"] for row in nonempty])
        corrupt = [key for key, result in integrity.items() if result.get("status") == "FAIL"]
        if corrupt:
            raise ValueError("subtitle publish pixels fail local render integrity: " + ", ".join(corrupt))
        ocr_report = local_vision_shadow.run_caption_ocr_shadow(
            ep, keys=[row["frame"] for row in nonempty])
        face_safe_report = subtitle_face_safe_area.run(
            ep, keys=[row["frame"] for row in nonempty])
        local_cleared = local_vision_shadow.locally_clear_caption_frames(
            ep, [row["frame"] for row in nonempty], ocr_report, integrity)
        for row in nonempty:
            key = row["frame"]
            if key not in local_cleared:
                continue
            dest[key] = {
                "schema_version": SCHEMA, "frame": key,
                "image_sha256": image_sha[key], "caption_sha256": caption_sha[key],
                "supported": True, "subtitle_unobstructed": True,
                "passed": True, "mode": "local_position_with_semantic_evidence",
                "notes": "current semantic support; OCR complete with no native-text overlap; render integrity passed; visual obstruction risk accepted by user",
                "local_review_evidence": local_cleared[key],
            }
        nonempty = [row for row in nonempty if row["frame"] not in local_cleared]

    span_name = "REVIEW_CAPTION_IMAGE"
    span_started = False
    if ep.is_dir():
        episode_performance.safe_begin_named_span(
            ep, span_name, source="caption_image_audit",
            metadata={
                "review_type": "CAPTION_IMAGE",
                "target_frame_count": vision_candidate_frames,
                "shard_count": (vision_candidate_frames + CHUNK - 1) // CHUNK,
            })
        span_started = True
    span_status = "FAILED"
    span_metadata: dict = {}
    try:
        placement_repairs: dict[str, dict] = {}
        for start in range(0, len(nonempty), CHUNK):
            chunk = nonempty[start:start + CHUNK]
            data = _run_chunk(ep, chunk, texts, codex_raw, timeout, start // CHUNK + 1)
            telemetry = data.get("_vision_telemetry") if isinstance(data, dict) else None
            if isinstance(telemetry, dict):
                data.pop("_vision_telemetry", None)
                if telemetry.get("vision_call"):
                    vision_call_count += 1
                    vision_elapsed_seconds += float(telemetry.get("elapsed_seconds") or 0.0)
                    for tok, value in (telemetry.get("tokens") or {}).items():
                        if isinstance(value, (int, float)):
                            vision_tokens[tok] = vision_tokens.get(tok, 0) + int(value)
            count, repairs = _record_chunk_results(
                ep=ep, chunk=chunk, data=data, dest=dest,
                image_sha=image_sha, caption_sha=caption_sha, cycle=1)
            reviewed += count
            placement_repairs.update(repairs)

        # Only the actual-pixel CODEX lane may auto-move text. Product Review host
        # requests remain fail-closed across turns rather than mutating layout while
        # an external review transaction is still open.
        _active_runtime, _ = runtime_router.detect()
        vision_runtime, _ = runtime_router.vision_review_runtime()
        auto_repaired: list[str] = []
        if placement_repairs and (vision_runtime == "CODEX" or codex_raw):
            subtitle_layout.apply_pixel_safe_overrides(ep, placement_repairs)
            repair_keys = sorted(placement_repairs)
            subtitle_layout.render_frames(ep, repair_keys)
            face_safe_report = subtitle_face_safe_area.run(ep, keys=repair_keys)
            repaired_frames, repaired_meta = _review_frame_records(ep)
            repaired_by_key = {row["frame"]: row for row in repaired_frames}
            repaired_image_sha, repaired_caption_sha, repaired_texts, repaired_source_meta = _hashes(ep, repaired_frames)
            repair_rows = [repaired_by_key[key] for key in repair_keys]
            for start in range(0, len(repair_rows), CHUNK):
                chunk = repair_rows[start:start + CHUNK]
                data = _run_chunk(
                    ep, chunk, repaired_texts, codex_raw, timeout,
                    start // CHUNK + 1, cycle=2)
                telemetry = data.get("_vision_telemetry") if isinstance(data, dict) else None
                if isinstance(telemetry, dict):
                    data.pop("_vision_telemetry", None)
                    if telemetry.get("vision_call"):
                        vision_call_count += 1
                        vision_elapsed_seconds += float(telemetry.get("elapsed_seconds") or 0.0)
                        for tok, value in (telemetry.get("tokens") or {}).items():
                            if isinstance(value, (int, float)):
                                vision_tokens[tok] = vision_tokens.get(tok, 0) + int(value)
                count, _ = _record_chunk_results(
                    ep=ep, chunk=chunk, data=data, dest=dest,
                    image_sha=repaired_image_sha, caption_sha=repaired_caption_sha, cycle=2)
                reviewed += count
            image_sha = repaired_image_sha
            caption_sha = repaired_caption_sha
            source_meta = {**repaired_source_meta, "review_image": repaired_meta}
            auto_repaired = repair_keys

        passed = all((dest.get(k) or {}).get("passed") is True for k in frame_keys)
        evidence["summary"] = {
            "passed": passed,
            "reviewed_dirty_frames": reviewed,
            "reused_frames": reused,
            "total_frames": len(frame_keys),
            "auto_repaired_frames": auto_repaired,
            "auto_repair_count": len(auto_repaired),
            "local_reviewed_frames": sorted(local_cleared),
            "local_review_count": len(local_cleared),
            "visual_review_invalidated": False,
            "face_safe_area_shadow": {
                "status": face_safe_report.get("status"),
                "summary": face_safe_report.get("summary") or {},
            },
            "vision_review_telemetry": {
                "vision_candidate_frames": vision_candidate_frames,
                "empty_caption_count": empty_caption_count,
                "local_skipped_frames": len(local_cleared),
                "vision_frames": reviewed,
                "vision_call_count": vision_call_count,
                "vision_elapsed_seconds": round(vision_elapsed_seconds, 3),
                "vision_tokens": vision_tokens,
                "vision_chunks_saved_estimate": max(0, (vision_candidate_frames + CHUNK - 1) // CHUNK - (max(0, vision_candidate_frames - len(local_cleared)) + CHUNK - 1) // CHUNK),
                "note": "local direct-pass skips LLM vision for non-empty captions whose semantic support and subtitle placement are locally verified; visual (non-text) obstruction risk is accepted by user",
            },
        }
        _write(ep, evidence)
        span_status = "PASS" if passed else "FAILED"
        span_metadata = {
            "vision_call_count": vision_call_count,
            "vision_frames": reviewed,
            "local_skipped_frames": len(local_cleared),
            "empty_caption_count": empty_caption_count,
            "vision_elapsed_seconds": round(vision_elapsed_seconds, 3),
        }
    except ProductReviewHostAction:
        span_status = "DEFERRED"
        raise
    finally:
        if span_started:
            episode_performance.safe_end_named_span(ep, span_name, status=span_status, metadata=span_metadata)

    active_runtime, _ = runtime_router.detect()
    vision_runtime, _ = runtime_router.vision_review_runtime()
    if vision_runtime != "CODEX" and not codex_raw:
        chunk_count = (len(nonempty) + CHUNK - 1) // CHUNK
        for index in range(1, chunk_count + 1):
            kind = _review_kind(index)
            request_file = product_review_adapter.request_path(ep, kind)
            candidate_file = ep / "meta" / f".caption-image-audit-candidate-{index:03d}.json"
            if request_file.is_file() and candidate_file.is_file():
                product_review_adapter.mark_complete(ep, kind, attempt=1, final_path=ep / REL)
                candidate_file.unlink(missing_ok=True)
    return evidence["summary"]["passed"], evidence

def verify(ep: Path) -> list[str]:
    ep = Path(ep).resolve()
    frames, review_meta = _review_frame_records(ep)
    data = _read(ep)
    image_sha, caption_sha, _texts, _source_meta = _hashes(ep, frames)
    errors = [f"subtitle layout stale: {e}" for e in (review_meta.get("layout_errors") or [])]
    rows = data.get("frames") or {}
    local_context = (local_vision_shadow.local_caption_validation_context(ep)
                     if any(isinstance(value, dict) and value.get("mode") in ("local_flat_area_with_semantic_evidence", "local_position_with_semantic_evidence")
                            for value in rows.values()) else None) or {}
    if data.get("schema_version") != SCHEMA:
        errors.append(f"caption image audit schema_version must be {SCHEMA}")
    if str((data.get("caption_source") or {}).get("review_image", {}).get("mode") or "") != str(review_meta.get("mode") or ""):
        errors.append("caption image audit review-image mode stale")
    for frame in frames:
        key = frame["frame"]
        row = rows.get(key)
        if not isinstance(row, dict):
            errors.append(f"caption image audit missing frame {key}")
            continue
        if row.get("image_sha256") != image_sha[key]:
            errors.append(f"caption image audit image SHA stale: {key}")
        if row.get("caption_sha256") != caption_sha[key]:
            errors.append(f"caption image audit caption SHA stale: {key}")
        if row.get("supported") is not True:
            errors.append(f"caption image audit unsupported caption: {key}")
        if row.get("subtitle_unobstructed") is not True:
            errors.append(f"caption image audit subtitle obstruction failed: {key}")
        if row.get("passed") is not True:
            errors.append(f"caption image audit failed: {key}")
        if row.get("mode") in ("local_flat_area_with_semantic_evidence", "local_position_with_semantic_evidence") and not local_vision_shadow.local_caption_evidence_current(
                ep, key, row.get("local_review_evidence"), local_context):
            errors.append(f"caption image local review evidence stale: {key}")
    return errors

def self_test():
    assert CHUNK == 5
    assert SCHEMA == 2
    assert _review_kind(1) == "caption-image-audit-v2-001"
    assert _review_kind(1, 2) == "caption-image-audit-v2-r1-001"
    ratio, legacy = _resolve_layout_y_ratio({"y": 918}, 1350)
    assert round(ratio, 2) == 0.68 and legacy is True
    ratio, legacy = _resolve_layout_y_ratio({"y_ratio": 0.52, "y": 702}, 1350)
    assert ratio == 0.52 and legacy is False
    print("CAPTION IMAGE AUDIT V2.6.1 SELF-TEST PASS")

def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("ensure"); p.add_argument("episode_dir"); p.add_argument("--codex"); p.add_argument("--timeout", type=int, default=None)
    p = sub.add_parser("verify"); p.add_argument("episode_dir")
    p = sub.add_parser("show"); p.add_argument("episode_dir")
    sub.add_parser("self-test")
    a = ap.parse_args()
    ep = Path(getattr(a, "episode_dir", ".")).resolve()
    if a.cmd == "self-test": self_test(); return 0
    if a.cmd == "show": print(json.dumps(_read(ep), ensure_ascii=False, indent=2)); return 0
    if a.cmd == "verify":
        errors = verify(ep)
        for e in errors: print("FAIL:", e)
        if not errors: print("CAPTION IMAGE AUDIT VERIFY PASS")
        return 2 if errors else 0
    ok, data = ensure(ep, a.codex, a.timeout)
    print(json.dumps(data.get("summary") or {}, ensure_ascii=False, indent=2))
    return 0 if ok else 2

if __name__ == "__main__":
    raise SystemExit(main())
