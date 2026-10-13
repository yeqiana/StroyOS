#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only M00 pixel calibration inventory and SHA-bound visual-review receipt.

This is observational/advisory. It does not create generation Attempts, alter
Episode authority, call vision providers, score pixels automatically, or grant
Visual Lock / Release PASS.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SAMPLES = ROOT / "tests/fixtures/m00_pixel_calibration_samples.json"
CHECKS = (
    "photographer_and_viewpoint",
    "story_event_fidelity",
    "lighting_and_device_physics",
    "natural_action_or_stillness",
    "non_cinematic_presentation",
    "physical_image_integrity",
)
VALID_JUDGEMENTS = {"PASS", "FAIL", "UNCERTAIN"}
ADVISORY_ONLY = "M00_PIXEL_AUDIT_ADVISORY_ONLY"


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(data)
    return h.hexdigest()


def _inside(root: Path, relative: str) -> Path:
    p = Path(relative)
    if not relative or p.is_absolute() or ".." in p.parts or ":" in relative:
        raise ValueError("PIXEL_AUDIT_UNSAFE_ASSET_PATH")
    resolved = (root.resolve() / p).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError("PIXEL_AUDIT_UNSAFE_ASSET_PATH")
    return resolved


def read_samples(path: Path) -> list[dict]:
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    if (not isinstance(document, dict)
            or document.get("schema_version") != 1
            or document.get("purpose") != "read_only_pixel_audit"
            or not isinstance(document.get("samples"), list)
            or not document["samples"]):
        raise ValueError("PIXEL_AUDIT_SAMPLE_SET_INVALID")
    seen = set()
    result = []
    for item in document["samples"]:
        if not isinstance(item, dict):
            raise ValueError("PIXEL_AUDIT_SAMPLE_INVALID")
        sample_id = item.get("id")
        rel = item.get("asset_path")
        expected = item.get("sha256")
        if (not isinstance(sample_id, str) or not sample_id or sample_id in seen
                or not isinstance(rel, str)
                or not isinstance(expected, str) or len(expected) != 64
                or any(c not in "0123456789abcdef" for c in expected)):
            raise ValueError("PIXEL_AUDIT_SAMPLE_INVALID")
        _inside(ROOT, rel)  # path check only: the actual asset root may be elsewhere
        seen.add(sample_id)
        result.append({"id": sample_id, "asset_path": rel, "sha256": expected,
                       "sample_note": str(item.get("sample_note") or "")})
    return result


def _image_facts(path: Path) -> dict:
    # Pillow is only a decoder/dimension verifier; its statistics never imply
    # style quality. No EXIF, face, or aesthetic score can auto-authorize PASS.
    try:
        from PIL import Image
    except ImportError:
        return {"status": "DECODER_UNAVAILABLE"}
    try:
        with Image.open(path) as im:
            im.verify()
        with Image.open(path) as im:
            width, height = im.size
            fmt = im.format
    except Exception:
        return {"status": "DECODE_FAILURE"}
    if width <= 0 or height <= 0:
        return {"status": "DECODE_FAILURE"}
    return {"status": "PIXELS_READABLE", "width": width, "height": height, "format": fmt}


def _review_verdict(item: dict, source_sha: str, review: Any) -> tuple[str, list[str]]:
    if review is None:
        return "NEEDS_PIXEL_REVIEW", []
    if not isinstance(review, dict):
        return "REVIEW_INVALID", ["review must be an object"]
    errors = []
    if review.get("source_sha256") != source_sha:
        errors.append("review SHA does not match the actual source image")
    if not str(review.get("reviewer") or "").strip():
        errors.append("reviewer identity missing")
    if not str(review.get("observations") or "").strip():
        errors.append("pixel observations missing")
    if review.get("reviewed_with") not in {"preview", "full_image"}:
        errors.append("reviewed_with must be preview or full_image")
    checks = review.get("checks")
    if not isinstance(checks, dict) or set(checks) != set(CHECKS):
        errors.append("exactly six named checks required")
        return "REVIEW_INCOMPLETE", errors
    vals = [checks[name] for name in CHECKS]
    if any(value not in VALID_JUDGEMENTS for value in vals):
        errors.append("each check must be PASS, FAIL or UNCERTAIN")
    if errors:
        return "REVIEW_INCOMPLETE", errors
    if "FAIL" in vals:
        return "REPAIR_RECOMMENDED", []
    if "UNCERTAIN" in vals:
        return "FURTHER_PIXEL_REVIEW_REQUIRED", []
    if review["reviewed_with"] == "preview":
        return "FULL_IMAGE_REVIEW_REQUIRED", []
    return "ADVISORY_PIXEL_PASS", []


def audit(*, asset_root: Path, sample_set: Path, review_records: dict | None = None) -> dict:
    samples = read_samples(sample_set)
    reviews = review_records or {}
    if not isinstance(reviews, dict):
        raise ValueError("PIXEL_AUDIT_REVIEW_RECORDS_INVALID")
    result = []
    for item in samples:
        path = _inside(asset_root, item["asset_path"])
        row = {"id": item["id"], "asset_path": item["asset_path"],
               "expected_sha256": item["sha256"], "status": "SOURCE_MISSING"}
        if path.is_file():
            actual = digest(path)
            row["actual_sha256"] = actual
            if actual != item["sha256"]:
                row["status"] = "SOURCE_SHA_DRIFT"
            else:
                facts = _image_facts(path)
                row.update(facts)
                if facts["status"] == "PIXELS_READABLE":
                    row["status"], errors = _review_verdict(
                        item, actual, reviews.get(item["id"]))
                    if errors:
                        row["review_errors"] = errors
        result.append(row)
    by_status: dict[str, int] = {}
    for row in result:
        by_status[row["status"]] = by_status.get(row["status"], 0) + 1
    return {
        "schema_version": 1, "authority": ADVISORY_ONLY,
        "grants_visual_lock_pass": False, "grants_episode_stage": False,
        "grants_release": False, "may_call_image_generation": False,
        "sample_count": len(result), "statuses": by_status, "samples": result,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only cross-genre M00 pixel evidence audit")
    parser.add_argument("--sample-set", type=Path, default=DEFAULT_SAMPLES)
    parser.add_argument("--asset-root", type=Path, default=ROOT)
    parser.add_argument("--reviews", type=Path)
    parser.add_argument("--strict", action="store_true",
                        help="nonzero unless every item has an explicit full-image advisory PASS")
    args = parser.parse_args(argv)
    reviews = json.loads(args.reviews.read_text(encoding="utf-8-sig")) if args.reviews else None
    try:
        result = audit(asset_root=args.asset_root, sample_set=args.sample_set,
                       review_records=reviews)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc), "authority": ADVISORY_ONLY},
                         ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    # Read-only inventory defaults to exit 0 for planning; strict consumption
    # cannot silently pass a missing asset or absent/preview-only review.
    return 1 if args.strict and any(
        item["status"] != "ADVISORY_PIXEL_PASS" for item in result["samples"]
    ) else 0


if __name__ == "__main__":
    raise SystemExit(main())
