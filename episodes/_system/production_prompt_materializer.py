#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deterministically materialize concise Production scene prompts from Frame Contracts.

The locked Storyboard/Frame Contract remain authority. These prompts are derived
transport hints only; they do not rewrite Story, Storyboard, Visual Lock or any
canonical stage. The full Resolved Frame Contract is injected by prompt_package
at generation time.
"""
from __future__ import annotations

import re
from pathlib import Path

import frame_contract
import content_prompt_policy

PROMPT_DIR = Path("prompts/production")
MAX_CHARS = 250
MAX_BYTES = 860

# Locked user storyboards use a three-column Markdown table. Frame Contract's
# text excerpt parser may intentionally use the full-storyboard SHA fallback
# for this format; never turn that empty excerpt into a generic image prompt.
TABLE_FRAME = re.compile(r"^\|\s*(\d{1,3})\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*$")


def locked_table_beats(ep: Path, *, expected_count: int) -> dict[int, str]:
    """Resolve each exact storyboard scene; reject missing/duplicate rows."""
    _story, storyboard = frame_contract.artifact_paths(Path(ep).resolve())
    beats: dict[int, str] = {}
    for line in storyboard.read_text(encoding="utf-8-sig").splitlines():
        match = TABLE_FRAME.match(line)
        if match is None:
            continue
        frame = int(match.group(1))
        if frame in beats:
            raise ValueError(f"duplicate locked storyboard frame {frame:02d}")
        scene = str(match.group(2) or "").strip()
        if not scene:
            raise ValueError(f"empty locked storyboard frame {frame:02d}")
        beats[frame] = scene
    if set(beats) != set(range(1, expected_count + 1)):
        missing = sorted(set(range(1, expected_count + 1)) - set(beats))
        extra = sorted(set(beats) - set(range(1, expected_count + 1)))
        raise ValueError(f"locked storyboard frame mismatch missing={missing} extra={extra}")
    return beats




def _clean_storyboard_text(text: str) -> str:
    value = str(text or "").strip()
    value = re.sub(r"^\s*\d+\.\s*", "", value)
    value = value.replace("**", "").strip()
    return value


def prompt_for_contract(contract: dict, *, exact_scene: str | None = None,
                        use_common_policy: bool = False) -> str:
    frame = str(contract.get("frame") or "").zfill(2)
    beat = _clean_storyboard_text(exact_scene if exact_scene is not None else
                                  ((contract.get("storyboard_frame") or {}).get("text") or ""))
    if not beat:
        raise ValueError(f"frame {frame} has no localized scene text; refuse generic fallback")
    if use_common_policy:
        # Derived transport only; never guess a missing locked scene.
        return content_prompt_policy.build_scene_prompt(
            contract, exact_scene=beat, max_chars=MAX_CHARS, max_bytes=MAX_BYTES
        )
    suffix = "按当前Frame Contract生成；真实生活相册感、自然瞬间、普通摄影曝光，避免电影布光、海报摆拍和无依据的额外元素。"
    text = f"{beat} {suffix}".strip()
    while len(text) > MAX_CHARS or len(text.encode("utf-8")) > MAX_BYTES:
        if len(beat) <= 40:
            text = f"{beat[:40]} 按当前Frame Contract生成；真实生活相册感，非电影布光、非海报摆拍。"
            break
        beat = beat[:-8].rstrip("，。；： ")
        text = f"{beat} {suffix}".strip()
    return text


def ensure(ep: Path, *, require_locked_table: bool = False) -> dict:
    ep = Path(ep).resolve()
    total = frame_contract.frame_count(ep)
    beats = locked_table_beats(ep, expected_count=total) if require_locked_table else {}
    out_dir = ep / PROMPT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    created: list[int] = []
    reused: list[int] = []
    for frame in range(1, total + 1):
        path = out_dir / f"{frame:02d}.txt"
        if path.is_file() and path.read_text(encoding="utf-8-sig").strip():
            reused.append(frame)
            continue
        contract = frame_contract.compile_frame(ep, frame, write_cache=True)
        text = prompt_for_contract(contract, exact_scene=beats.get(frame))
        path.write_text(text + "\n", encoding="utf-8", newline="\n")
        created.append(frame)
    return {"created": created, "reused": reused, "prompt_dir": PROMPT_DIR.as_posix(), "total": total}


def _prepare_reviewed_m00_source_drafts(ep: Path) -> dict:
    """Only after current canonical Story Review succeeds.

    A skip must remain invisible to old production prompt/Frame SHA. A new
    draft is NEVER a verified delta and never an image Attempt permission.
    """
    import visual_profile
    import story_review
    import m00_storyboard_delta_sources as sources

    if visual_profile.compile_prompt_contract(ep)["profile_id"] != "M00":
        return {"status": "SKIPPED_OTHER_PROFILE"}
    if not story_review.review_required(ep):
        return {"status": "SKIPPED_NO_CANONICAL_REVIEW"}
    try:
        if story_review.verify(ep):
            return {"status": "SKIPPED_CANONICAL_REVIEW_NOT_READY"}
        if not story_review.review_authority_sha256(ep):
            return {"status": "SKIPPED_CANONICAL_REVIEW_SHA_MISSING"}
        story, board = frame_contract.artifact_paths(ep)
        return sources.prepare_drafts(
            episode=ep, story=story, storyboard=board,
            count=frame_contract.frame_count(ep), apply=True)
    except (ValueError, KeyError, UnicodeError) as exc:
        # Candidate extraction is advisory. A legacy valid storyboard shape
        # must not be blocked from image-queue preparation by this assistant.
        return {"status": "SKIPPED_DRAFT_EXTRACTION_UNSUPPORTED",
                "reason_code": str(exc).split(":")[0][:100]}


def prepare_queue(ep: Path) -> dict:
    ep = Path(ep).resolve()
    source_drafts = _prepare_reviewed_m00_source_drafts(ep)
    materialized = ensure(ep)
    import image_scheduler
    imported = image_scheduler.import_batch(ep, ep / PROMPT_DIR)
    return {"status": "PASS", "materialized": materialized, "queue": imported,
            "m00_source_drafts": source_drafts}


def self_test() -> None:
    sample = {"frame": "02", "storyboard_frame": {"text": "2. **下楼**：三人沿居民区石阶下楼。"}}
    text = prompt_for_contract(sample)
    assert "下楼" in text and "Frame Contract" in text
    assert len(text) <= 260 and len(text.encode("utf-8")) <= 900
    try:
        prompt_for_contract({"frame":"01","storyboard_frame":{"text":""}})
    except ValueError:
        pass
    else:
        raise AssertionError("must not generate generic placeholder prompts")
    print("PRODUCTION PROMPT MATERIALIZER SELF-TEST PASS")


if __name__ == "__main__":
    self_test()
