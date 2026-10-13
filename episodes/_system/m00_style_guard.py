#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Preserve the locked M00 capture semantics through Image Controller rewriting.

The visual profile + capture grammar remain the sole source of style rules.
This module selects a minimal immutable projection from their compiled text;
it neither authors scene content nor changes an Episode's frozen profile SHA.
"""
from __future__ import annotations

_BEGIN = "[M00 DOCUMENTARY CAPTURE GUARD | locked visual contract]"
_END = "[END M00 DOCUMENTARY CAPTURE GUARD]"
_REQUIRED = {
    "reality_first": "true",
    "practical_available_light": "true",
    "cinematic_lighting": "forbidden_by_default",
    "commercial_hdr": "forbidden",
    "beautification": "forbidden",
    "camera_authorship": "required",
    "ghost_camera": "forbidden",
    "defects_must_have_physical_cause": "true",
    "lock_texture_not_scene": "true",
}
_PROJECT = (
    "reality_first",
    "composition",
    "people",
    "practical_available_light",
    "cinematic_lighting",
    "commercial_hdr",
    "beautification",
    "skin_rendering",
    "color",
    "dynamic_range",
    "motion_blur",
    "visual_polish_ceiling",
    "camera_authorship",
    "ghost_camera",
    "camera_operator",
    "camera_position",
    "handheld",
    "unposed",
    "imperfect_framing",
    "defects_must_have_physical_cause",
    "lock_texture_not_scene",
    "anti_homogeneity_rule",
)


def is_m00(visual_contract: str) -> bool:
    lines = str(visual_contract or "").splitlines()
    return bool(lines) and lines[0].startswith("profile=M00 |")


def locked_capture_projection(visual_contract: str) -> str:
    """Fail closed when a claimed M00 contract lacks its original physical DNA."""
    fields = {}
    for line in str(visual_contract).splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key in _PROJECT:
            fields[key] = value.strip()
    missing = [k for k, v in _REQUIRED.items() if fields.get(k) != v]
    for key in ("anti_homogeneity_rule", "composition", "camera_operator", "camera_position"):
        if not fields.get(key):
            missing.append(key)
    if missing:
        raise ValueError("M00_STYLE_GUARD_SOURCE_INVALID:" + ",".join(missing))
    return "\n".join(f"{key}={fields[key]}" for key in _PROJECT if key in fields)


def enforce(*, scene_prompt: str, visual_contract: str) -> str:
    """Append a deterministic style-only guard to the final Payload scene prompt.

    The Controller's scene stays intact. No action, event, device era, location,
    cast, or prop is copied from style example images into this guard.
    """
    if not is_m00(visual_contract):
        return scene_prompt
    projection = locked_capture_projection(visual_contract)
    guard = (
        f"{_BEGIN}\n"
        "The locked Story/Storyboard/Frame Contract alone defines subjects, actions, "
        "location, props, cast, event intensity, camera owner and camera device. "
        "This block controls only documentary image appearance and plausible capture.\n"
        "Stillness, subtle activity and fast motion are all valid when story-accurate; "
        "never invent motion, blur, drama or an extra event to look candid. "
        "Camera imperfections must have physical causes, never be decorative.\n"
        f"{projection}\n{_END}"
    )
    if _BEGIN in scene_prompt or _END in scene_prompt:
        if scene_prompt.endswith(guard) and scene_prompt.count(_BEGIN) == 1:
            return scene_prompt
        raise ValueError("M00_STYLE_GUARD_CONTROLLER_INJECTION")
    return scene_prompt.rstrip() + "\n\n" + guard
