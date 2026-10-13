#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Two linked real-image M00 Test-only frames; no Episode/MySQL authority."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "episodes/_system"))
import m00_capture_profile_contract
import m00_calibration_receipts
import m00_scene_fidelity_guard
import m00_style_guard
import storyos_m00_calibration_r2 as r2

CONFIG = ROOT / "standards/m00_sequence_canary_r7.json"
PRIVATE = ROOT / ".storyos/user-visual-references/test-only-calibration"
REFERENCE_ROOT = ROOT / ".storyos/user-visual-references"
CHECKS = (
    "character_and_clothing_continuity",
    "bicycle_and_prop_continuity",
    "photographer_reachable_viewpoint",
    "light_weather_and_location_consistency",
    "contact_balance_and_motion_progression",
    "natural_era_device_capture",
    "no_invented_story_or_cinematic_staging",
)
VALID = {"PASS", "FAIL", "UNCERTAIN"}


def _read(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("M00_R7_INVALID_CONFIG")
    return value


def _anchor_image(repo: Path, name: str) -> tuple[Path, dict]:
    root = (repo / ".storyos/user-visual-references/test-only-calibration").resolve()
    if name not in {"C02-R2", "C02-S01"}:
        raise ValueError("M00_R7_ANCHOR_NOT_ALLOWED")
    folder = root / name
    data = _read(folder / "test-only-record.json")
    if data.get("frame") != name or data.get("status") not in {
        "IMAGE_CREATED", "IMAGE_RECOVERED_AFTER_RUNNER_TIMEOUT"
    }:
        raise ValueError("M00_R7_ANCHOR_NOT_COMPLETED")
    report = m00_calibration_receipts.inspect_frame(root, name)
    if report.get("verified") is not True or not report.get("image_sha256"):
        raise ValueError("M00_R7_ANCHOR_SHA_OR_RECEIPT_INVALID")
    image = folder / "generated.png"
    return image, data


def build_bundle(frame: str, *, repo: Path = ROOT,
                 base_visual: str | None = None) -> dict:
    root = repo.resolve()
    config_path = root / "standards/m00_sequence_canary_r7.json"
    cfg = _read(config_path)
    if cfg.get("schema_version") != 1 or cfg.get("test_only") is not True:
        raise ValueError("M00_R7_NON_TEST_CONFIG")
    if cfg.get("sequence_id") != "m00-bicycle-20261013-r7":
        raise ValueError("M00_R7_SEQUENCE_MISMATCH")
    ordered = cfg.get("frames")
    if not isinstance(ordered, list) or [x.get("id") for x in ordered] != ["S01", "S02"]:
        raise ValueError("M00_R7_FRAME_ORDER_INVALID")
    slot = {"S01": 0, "S02": 1}.get(frame)
    if slot is None:
        raise ValueError("M00_R7_FRAME_NOT_ALLOWED")
    shot = ordered[slot]
    prior = "C02-R2" if slot == 0 else "C02-S01"
    if shot.get("anchor") != prior or shot.get("frame_id") != "C02-" + frame:
        raise ValueError("M00_R7_SEQUENCE_DEPENDENCY_INVALID")
    anchor, previous = _anchor_image(root, prior)
    if previous.get("capture_profile") != "CP02":
        raise ValueError("M00_R7_ANCHOR_DEVICE_DRIFT")
    # One scene-content/character reference plus one style-only reference.
    original_plan = _read(root / ".storyos/user-visual-references/calibration-plans/m00-four-scene-20261013.json")
    old = [row for row in original_plan.get("frames", []) if row.get("id") == "C02"]
    if len(old) != 1 or old[0].get("capture_profile") != cfg.get("capture_profile"):
        raise ValueError("M00_R7_SOURCE_DEVICE_MISMATCH")
    style = (old[0].get("references") or [None])[0]
    if not isinstance(style, dict) or style.get("kind") != "capture_style":
        raise ValueError("M00_R7_STYLE_REF_UNTYPED")
    style_path = (root / str(style.get("path") or "")).resolve()
    if (not style_path.is_relative_to((root / ".storyos/user-visual-references").resolve())
            or not style_path.is_file()
            or r2.digest(style_path) != style.get("sha256")):
        raise ValueError("M00_R7_STYLE_REF_SHA_INVALID")
    physical = m00_capture_profile_contract.compile_device_contract(cfg["capture_profile"], root=root)
    if physical["profile_id"] != "CP02":
        raise ValueError("M00_R7_DEVICE_NOT_CP02")
    baseline = base_visual or r2.visual_profile_bridge_v224.compile_prompt_contract(root / "episodes")["text"]
    visual = r2.rebind_capture_device(baseline, physical["text"])
    required = [cfg.get(k) for k in ("character", "prop", "location", "photographer")]
    if any(not isinstance(v, str) or len(v) < 20 for v in required):
        raise ValueError("M00_R7_SEQUENCE_AUTHORITY_MISSING")
    evidence = shot.get("evidence")
    if not isinstance(evidence, list) or len(evidence) < 5 or len(set(evidence)) != len(evidence):
        raise ValueError("M00_R7_EVIDENCE_INVALID")
    scene = "\n".join([
        "LOCKED CONTINUOUS DOCUMENTARY SEQUENCE; predecessor photograph is the immediately prior beat.",
        "LOCKED_CHARACTER=" + required[0],
        "LOCKED_PROP=" + required[1],
        "LOCKED_LOCATION=" + required[2],
        "LOCKED_PHOTOGRAPHER=" + required[3],
        "MOMENT=" + str(shot.get("moment") or ""),
        "NEXT_STORY_BEAT=" + str(shot.get("scene") or ""),
        "OBSERVABLE_CONSISTENCY=" + "；".join(evidence),
        "Use predecessor image to preserve the actual story's existing character/wardrobe/bicycle/",
        "environment only; it does not authorize copying its exact pose or camera position.",
        "Preserve photographic continuity while showing the locked next action. No split-screen/",
        "collage, frames, text, overlays, artificially forced shake or blur.",
    ])
    if len(str(shot.get("scene") or "")) < 85:
        raise ValueError("M00_R7_STORY_BEAT_UNDERDEFINED")
    prompt = m00_style_guard.enforce(scene_prompt=scene, visual_contract=visual)
    prompt = m00_scene_fidelity_guard.enforce_event(
        scene_prompt=prompt, source_scene_prompt=scene, visual_contract=visual)
    prompt = m00_scene_fidelity_guard.enforce_motion(scene_prompt=prompt, visual_contract=visual)
    refs = [
        {"path": anchor.relative_to(root).as_posix(), "sha256": r2.digest(anchor),
         "kind": "identity", "role": "same_story_person_and_visual_continuity"},
        {"path": style_path.relative_to(root).as_posix(), "sha256": r2.digest(style_path),
         "kind": "capture_style", "role": "camera_physics_only"},
    ]
    identity = {
        "test_only": True, "sequence_id": cfg["sequence_id"], "frame_id": shot["frame_id"],
        "sequence_config_sha256": r2.digest(config_path), "previous_frame_id": prior,
        "previous_image_sha256": r2.digest(anchor),
        "device_profile_sha256": physical["sha256"], "capture_device": physical["profile_id"],
        "scene_prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "visual_contract_sha256": hashlib.sha256(visual.encode("utf-8")).hexdigest(),
        "style_ref_sha256": r2.digest(style_path), "references": refs,
    }
    fingerprint = r2.stable_hash(identity)
    request = {
        "request_fingerprint": fingerprint, "payload_model": "gpt-image-2.5-flare",
        "payload_quality": "high", "canvas": {"width": 1080, "height": 1350, "aspect_ratio": "4:5"},
        "references": refs, "scene_prompt": prompt,
    }
    instructions = r2.codex_subscription_image.payload_transport_prompt(
        request, "1080x1350", len(refs))
    instructions += "\nTEST_ONLY sequence canary; no production/episode authority; do not call other tools."
    return {
        "identity": identity, "fingerprint": fingerprint,
        "case": {"new_frame_id": shot["frame_id"], "observable_evidence": evidence},
        "device": physical, "request": request,
        "prompt": instructions, "ref_paths": [anchor, style_path],
        "out": root / ".storyos/user-visual-references/test-only-calibration" / shot["frame_id"],
    }


def review_pair(frame: str, *, repo: Path = ROOT, review: dict | None = None) -> dict:
    bundle = build_bundle(frame, repo=repo)
    root = repo.resolve()
    current = bundle["case"]["new_frame_id"]
    previous = bundle["identity"]["previous_frame_id"]
    prior = m00_calibration_receipts.inspect_frame(
        root / ".storyos/user-visual-references/test-only-calibration", previous)
    after = m00_calibration_receipts.inspect_frame(
        root / ".storyos/user-visual-references/test-only-calibration", current)
    result = {
        "pair": [previous, current], "anchor_sha256": bundle["identity"]["previous_image_sha256"],
        "current_sha256": after.get("image_sha256"),
        "both_real_images_verified": prior["verified"] and after["verified"],
        "request_fingerprint": bundle["fingerprint"],
        "checks_required": list(CHECKS), "pixel_review_status": "PENDING_ACTUAL_PAIR_REVIEW",
        "advisory_only": True, "production_approved": False, "auto_repair": False,
    }
    if not (prior["verified"] and after["verified"]):
        return result
    receipt = _read(bundle["out"] / "test-only-record.json")
    if (receipt.get("request_fingerprint") != bundle["fingerprint"]
            or receipt.get("request_identity", {}).get("previous_image_sha256") != prior.get("image_sha256")):
        return {**result, "pixel_review_status": "RECEIPT_OR_PARENT_SHA_DRIFT"}
    if review is None:
        return result
    if (review.get("anchor_sha256") != prior.get("image_sha256")
            or review.get("current_sha256") != after.get("image_sha256")
            or review.get("reviewed_with") != "both_full_images"
            or not str(review.get("reviewer") or "").strip()
            or not str(review.get("observations") or "").strip()
            or not isinstance(review.get("checks"), dict)
            or set(review["checks"]) != set(CHECKS)
            or set(review["checks"].values()) - VALID):
        return {**result, "pixel_review_status": "REVIEW_INVALID_OR_INCOMPLETE"}
    results = set(review["checks"].values())
    state = "REPAIR_RECOMMENDED" if "FAIL" in results else (
        "FURTHER_REVIEW_REQUIRED" if "UNCERTAIN" in results else "ADVISORY_PAIR_PASS")
    return {**result, "pixel_review_status": state}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("plan", "run", "pair-review"))
    parser.add_argument("--frame", choices=("S01", "S02"), required=True)
    parser.add_argument("--ack-testonly-paid-image", action="store_true")
    parser.add_argument("--timeout", type=int, default=420)
    parser.add_argument("--review", type=Path)
    args = parser.parse_args()
    if args.operation == "pair-review":
        reviews = _read(args.review) if args.review else None
        print(json.dumps(review_pair(args.frame, review=reviews), ensure_ascii=False))
        return 0
    bundle = build_bundle(args.frame)
    if args.operation == "plan":
        print(json.dumps({
            "frame_id": bundle["case"]["new_frame_id"],
            "anchor": bundle["identity"]["previous_frame_id"],
            "device": bundle["device"]["profile_id"],
            "reference_kinds": [r["kind"] for r in bundle["request"]["references"]],
            "references_verified": len(bundle["ref_paths"]),
            "fingerprint": bundle["fingerprint"],
            "status": "READY_TESTONLY_NO_DISPATCH",
        }, ensure_ascii=False))
        return 0
    if not args.ack_testonly_paid_image:
        raise SystemExit("M00_R7_EXPLICIT_REAL_IMAGE_ACK_REQUIRED")
    record = r2.execute_bundle(bundle, timeout=args.timeout)
    print(json.dumps({
        "frame": record["frame"], "status": record["status"],
        "request_id": record["request_id"], "image_sha256": record.get("output_sha256"),
        "dimensions": record.get("dimensions"), "error": record.get("error_type"),
    }, ensure_ascii=False))
    return 0 if record["status"] == "IMAGE_CREATED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
