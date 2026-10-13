#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Scene-specific documentary fidelity without writing new story facts.

The M00 mother profile describes *how* events look. The frozen scene is the
only source of *what* occurs. This guard is deterministic and fingerprinted.
"""
from __future__ import annotations

import re

import m00_style_guard

EVENT_BEGIN = "[M00 LOCKED VISIBLE EVENT | source scene]"
EVENT_END = "[END M00 LOCKED VISIBLE EVENT]"
MOTION_BEGIN = "[M00 PHYSICAL ACTION EVIDENCE]"
MOTION_END = "[END M00 PHYSICAL ACTION EVIDENCE]"
_PLACEHOLDER = re.compile(
    r"(?:由故事定义|尚未定义|待定义|待补充|自行设计|某种未知|某个未定义).{0,20}(?:异常|现象|物体|事件)"
    r"|(?:异常|现象|物体|事件).{0,20}(?:由故事定义|尚未定义|待定义|待补充)",
    flags=re.IGNORECASE,
)


def enforce_event(*, scene_prompt: str, source_scene_prompt: str, visual_contract: str) -> str:
    if not m00_style_guard.is_m00(visual_contract):
        return scene_prompt
    source = str(source_scene_prompt or "").strip()
    if not source:
        raise ValueError("M00_FRAME_EVENT_SOURCE_MISSING")
    if _PLACEHOLDER.search(source):
        raise ValueError("M00_VISIBLE_EVENT_UNDERDEFINED")
    if EVENT_BEGIN in source or EVENT_END in source:
        raise ValueError("M00_FRAME_EVENT_SOURCE_INJECTION")
    append = (
        EVENT_BEGIN + "\n"
        "FROZEN_SOURCE_EVENT (not a style reference; source Story/Frame Contract prevails):\n"
        + source
        + "\nShow the exact locked story beat as observable pixels. If the beat "
        "requires an anomaly, its observable form, position, size, contrast, "
        "and the character's attention must come from the Story/Storyboard; "
        "do NOT substitute a plausible everyday activity for a missing event. "
        "Do NOT invent an anomaly for a scene that does not require one. "
        "Stillness is fully valid when the locked event is static.\n"
        + EVENT_END
    )
    if EVENT_BEGIN in scene_prompt or EVENT_END in scene_prompt:
        if scene_prompt.endswith(append) and scene_prompt.count(EVENT_BEGIN) == 1:
            return scene_prompt
        raise ValueError("M00_FRAME_EVENT_GUARD_INJECTION")
    return scene_prompt.rstrip() + "\n\n" + append


def enforce_motion(*, scene_prompt: str, visual_contract: str) -> str:
    if not m00_style_guard.is_m00(visual_contract):
        return scene_prompt
    appendix = (
        MOTION_BEGIN + "\n"
        "For a locked physical action, preserve who touches which object, which "
        "hand or body part applies force, contact continuity, body weight and "
        "balance, object location before/after, and a plausible in-progress "
        "capture instant. A bicycle being moved must visually read as being "
        "moved, not merely a person standing next to it. Apply the same "
        "principle across subjects without requiring any specific action. "
        "For a locked static shot, do not add movement, artificial shaking, "
        "tilted horizons, or blur. Blur is warranted only by shutter/camera/"
        "subject physics, not by a style checklist.\n"
        + MOTION_END
    )
    if MOTION_BEGIN in scene_prompt or MOTION_END in scene_prompt:
        if scene_prompt.endswith(appendix) and scene_prompt.count(MOTION_BEGIN) == 1:
            return scene_prompt
        raise ValueError("M00_FRAME_MOTION_GUARD_INJECTION")
    return scene_prompt.rstrip() + "\n\n" + appendix
