#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Project an already selected Capture Profile into the provider's M00 prompt.

Read-only; never edits frozen Capture Profile JSON or changes an Episode device.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import capture_profile

_PHYSICS_KEYS = ("dynamic_range", "low_light", "motion", "focus", "white_balance",
                 "compression", "edge_behavior", "simulated_capture_encoding",
                 "fake_vintage_noise", "fake_low_resolution")
_INTERPRETATION = {
    "CP01": "Modern phone: use plausible in-device processing; do not add old-camera defects to simulate realism.",
    "CP02": "2012-2018 budget Android phone: if light is difficult, less highlight/shadow latitude and noisier low-light detail are plausible; autofocus/white balance/JPEG artifacts depend on conditions. Never force fake old-camera overlays.",
    "CP03": "2003-2012 compact digital still camera: limited shadow/highlight latitude, small-sensor low-light noise and possible flash reliance; focus hunting and slower shutter are conditional. No invented camcorder interlacing, film scratches, or forced motion blur.",
}


def compile_device_contract(selected: str, *, root: Path | None = None) -> dict:
    base = (root or capture_profile.ROOT).resolve()
    idx = base / "standards/capture_profiles/index.json"
    registry = json.loads(idx.read_text(encoding="utf-8-sig"))
    raw = str(selected or "").strip()
    if raw.lower() in {"", "auto"}:
        raw = str(registry["default_profile_id"])
    entries = registry.get("profiles") or []
    matches = [
        row for row in entries
        if raw in {str(row.get("profile_id")), str(row.get("name")), Path(str(row.get("file"))).stem}
    ]
    if len(matches) != 1:
        raise ValueError("M00_CAPTURE_PROFILE_UNKNOWN:" + raw)
    row = matches[0]
    source = (idx.parent / str(row["file"])).resolve()
    if not source.is_relative_to(idx.parent.resolve()) or not source.is_file():
        raise ValueError("M00_CAPTURE_PROFILE_FILE_INVALID")
    binary = source.read_bytes()
    data = json.loads(binary.decode("utf-8-sig"))
    profile_id = str(row["profile_id"])
    if data.get("profile_id") != profile_id or not isinstance(data.get("physics"), dict):
        raise ValueError("M00_CAPTURE_PROFILE_ID_OR_PHYSICS_INVALID")
    physics = data["physics"]
    required = capture_profile.CP01_REQ if profile_id == "CP01" else capture_profile.BASE_REQ
    missing = set(required).difference(physics)
    if missing:
        raise ValueError("M00_CAPTURE_PROFILE_FIELDS_MISSING:" + ",".join(sorted(missing)))
    digest = hashlib.sha256(binary).hexdigest()
    rel = source.relative_to(base).as_posix()
    lines = [
        "capture_device_id=" + profile_id,
        "capture_device_source=" + rel,
        "capture_device_sha256=" + digest,
        "capture_device_era_hint=" + str(data.get("era_hint") or "story_locked"),
    ]
    lines += [f"capture_device_{key}={physics[key]}" for key in _PHYSICS_KEYS if key in physics]
    interpretation = _INTERPRETATION.get(profile_id)
    if interpretation:
        lines.append("capture_device_physical_interpretation=" + interpretation)
    lines.append("capture_device_priority=story_era_and_locked_device_above_M00_texture")
    lines.append("capture_device_defect_policy=only_physically_explained_defects_not_decorative_filters")
    return {"profile_id": profile_id, "path": rel, "sha256": digest, "text": "\n".join(lines)}
