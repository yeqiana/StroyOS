#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only independent M00 real-pixel calibration receipt integrity.

A photographed pixel file is not an approved Episode. A recovered provider
artifact after a Bridge timeout is not a clean Provider return or a retry grant.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

_SUCCESS = "IMAGE_CREATED"
_RECOVERED = "IMAGE_RECOVERED_AFTER_RUNNER_TIMEOUT"


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def inspect_frame(root: Path, frame_id: str) -> dict:
    """Fail closed on missing/tampered bytes, no review or production authority."""
    if not frame_id or any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for ch in frame_id):
        raise ValueError("M00_CALIBRATION_FRAME_ID_INVALID")
    folder = root.resolve() / frame_id
    record = folder / "test-only-record.json"
    row = {"frame": frame_id, "verified": False, "status": "MISSING_RECEIPT"}
    if not record.is_file():
        return row
    try:
        doc = json.loads(record.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {**row, "status": "INVALID_RECEIPT"}
    if not isinstance(doc, dict) or doc.get("frame") != frame_id:
        return {**row, "status": "INVALID_RECEIPT"}
    status = doc.get("status")
    if status not in {_SUCCESS, _RECOVERED}:
        return {**row, "status": "NOT_COMPLETED_OR_UNKNOWN"}
    if not isinstance(doc.get("mock"), dict) or doc["mock"].get("production_authority") is not False:
        return {**row, "status": "NOT_TEST_ONLY"}
    output = doc.get("output")
    if not isinstance(output, str) or Path(output).name != "generated.png":
        return {**row, "status": "INVALID_IMAGE_REFERENCE"}
    img = folder / "generated.png"
    if not img.is_file() or _digest(img) != doc.get("output_sha256"):
        return {**row, "status": "IMAGE_MISSING_OR_SHA_DRIFT"}
    try:
        from PIL import Image
        with Image.open(img) as im:
            im.verify()
        with Image.open(img) as im:
            dims = list(im.size)
    except (OSError, ImportError, ValueError):
        return {**row, "status": "IMAGE_UNREADABLE"}
    if dims != doc.get("dimensions"):
        return {**row, "status": "IMAGE_DIMENSION_MISMATCH"}
    if status == _RECOVERED:
        recovery = doc.get("recovery")
        if (not isinstance(recovery, dict)
                or recovery.get("runner_returncode") != 124
                or recovery.get("request_id") != doc.get("request_id")
                or recovery.get("type") != "THREAD_SCOPED_DURABLE_ARTIFACT"
                or recovery.get("different_from_clean_completion") is not True
                or not recovery.get("thread_id")):
            return {**row, "status": "RECOVERY_PROVENANCE_INVALID"}
    elif doc.get("codex_returncode") != 0:
        return {**row, "status": "PROVIDER_COMPLETION_NOT_PROVEN"}
    return {"frame": frame_id, "verified": True,
            "status": status, "image_sha256": doc["output_sha256"],
            "dimensions": dims, "clean_provider_completion": status == _SUCCESS,
            "advisory_only": True, "grants_visual_lock_pass": False,
            "grants_production_attempt": False, "may_auto_retry": False}


def inspect_batch(root: Path, frame_ids: tuple[str, ...] = ("C01", "C02", "C03", "C04")) -> dict:
    if len(set(frame_ids)) != len(frame_ids):
        raise ValueError("M00_CALIBRATION_DUPLICATE_FRAME")
    rows = [inspect_frame(root, key) for key in frame_ids]
    return {"status": "PIXELS_PRESENT" if all(row["verified"] for row in rows) else "INCOMPLETE",
            "advisory_only": True, "grants_visual_lock_pass": False,
            "total": len(rows), "verified": sum(row["verified"] for row in rows),
            "frames": rows}


def continuity_review_requirements(frames: list[dict]) -> list[dict]:
    """Produce adjacent-frame review questions; never infer a pixel-level PASS."""
    results = []
    ordered = list(frames)
    for index, frame in enumerate(ordered):
        if not isinstance(frame, dict) or not str(frame.get("frame") or ""):
            raise ValueError("M00_SEQUENCE_FRAME_INVALID")
        if index == 0:
            continue
        prev = ordered[index - 1]
        results.append({
            "pair": [prev["frame"], frame["frame"]],
            "check": [
                "same_character_and_wardrobe_unless_locked_change",
                "physically_reachable_photographer_positions",
                "prop_contact_and_state_progression",
                "time_light_weather_geography_consistency",
                "observable_new_information_or_explicit_static_hold",
            ],
            "advisory_only": True,
            "pixel_review_pass": None,
        })
    return results
