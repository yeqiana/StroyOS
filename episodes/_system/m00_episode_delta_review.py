#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only full-pixel advisory for an explicitly locked M00 frame delta.

This does not call models, update Candidate or grant Review Authority.
The canonical Final Semantic Critic remains the ONLY production review path.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import m00_sequence_state_delta as delta

LOCK_CHECKS = (
    "identity", "wardrobe", "props", "geography", "photographer", "lighting"
)
APPROVED = {"PASS", "FAIL", "UNCERTAIN"}


def _picture(path: Path, ep: Path) -> dict:
    p = path.resolve()
    if not p.is_relative_to(ep.resolve()) or not p.is_file():
        raise ValueError("M00_EPISODE_PIXEL_OUTSIDE_EPISODE_OR_MISSING")
    from PIL import Image
    with Image.open(p) as im:
        im.verify()
    with Image.open(p) as im:
        if min(im.size) < 128:
            raise ValueError("M00_EPISODE_PIXEL_TOO_SMALL")
        dims = [im.width, im.height]
    return {"path": p.relative_to(ep.resolve()).as_posix(),
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            "dimensions": dims}


def inspect_pair(*, episode: Path, previous_image: Path, current_image: Path,
                 locked_delta: dict, review: dict | None = None) -> dict:
    """Never auto-pass by SHA/image difference, and never grant production PASS."""
    ep = Path(episode).resolve()
    contract = delta.canonical(locked_delta)
    prev = _picture(Path(previous_image), ep)
    curr = _picture(Path(current_image), ep)
    required = list(LOCK_CHECKS)
    if contract["mode"] == "action":
        required.extend("change:" + row["id"] for row in contract["observable_changes"])
    result = {
        "delta_sha256": delta.contract_sha256(contract),
        "previous": prev, "current": curr,
        "required_checks": required,
        "status": "PENDING_FULL_PIXEL_REVIEW",
        "advisory_only": True, "grants_visual_lock_pass": False,
        "grants_production_attempt": False, "automatic_repair": False,
    }
    if prev["sha256"] == curr["sha256"] and contract["mode"] == "action":
        return {**result, "status": "DUPLICATE_ACTION_PIXELS"}
    if review is None:
        return result
    if (not isinstance(review, dict)
            or review.get("delta_sha256") != result["delta_sha256"]
            or review.get("previous_sha256") != prev["sha256"]
            or review.get("current_sha256") != curr["sha256"]
            or review.get("reviewed_with") != "both_full_images"
            or not str(review.get("reviewer") or "").strip()
            or not str(review.get("observations") or "").strip()
            or not isinstance(review.get("checks"), dict)
            or set(review["checks"]) != set(required)
            or set(review["checks"].values()) - APPROVED):
        return {**result, "status": "REVIEW_SHA_OR_CHECKS_INVALID"}
    grades = set(review["checks"].values())
    result["status"] = ("REPAIR_RECOMMENDED" if "FAIL" in grades else
                        "UNCERTAIN_NEEDS_FULL_REVIEW" if "UNCERTAIN" in grades else
                        "ADVISORY_PIXEL_PASS")
    return result
