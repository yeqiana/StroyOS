#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R8 M00 one-shot native Codex Test-only alternate successor to R6 C02-R2.

This is a NEW independently identified revision, not a replay of failed R7
S01/S02, and grants no production, release or official Episode authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "episodes/_system"))
sys.path.insert(0, str(ROOT / "scripts"))
import m00_capture_profile_contract
import m00_calibration_receipts
import m00_sequence_state_delta as delta
import m00_scene_fidelity_guard
import m00_style_guard
import storyos_m00_calibration_r2 as r2
import storyos_m00_sequence_r7 as r7

CONFIG = ROOT / "standards/m00_sequence_delta_canary_r8.json"
EVIDENCE = ROOT / ".storyos/user-visual-references/test-only-calibration"
REVIEW_CHECKS = r7.CHECKS + ("observable_state_delta_vs_previous", "fixed_background_geometry")


def make_bundle(*, repo: Path = ROOT, base_visual: str | None = None) -> dict:
    root = repo.resolve()
    cfg_path = root / "standards/m00_sequence_delta_canary_r8.json"
    cfg = r2.read_json(cfg_path)
    if (cfg.get("schema_version") != 1 or cfg.get("test_only") is not True
            or cfg.get("sequence_id") != "m00-c02-delta-r8-20261013"
            or cfg.get("frame_id") != "C02-T01" or cfg.get("anchor") != "C02-R2"
            or cfg.get("capture_profile") != "CP02_cheap_android_2015"):
        raise ValueError("M00_R8_REVISION_OR_ANCHOR_INVALID")
    contract = delta.canonical(cfg.get("delta"))
    if contract["mode"] != "action":
        raise ValueError("M00_R8_EXPECTED_LOCKED_ACTION")
    parent_folder = root / ".storyos/user-visual-references/test-only-calibration/C02-R2"
    # Native original receipt and decoded PNG, not a mock-only visual acceptance.
    proof = m00_calibration_receipts.inspect_frame(parent_folder.parent, "C02-R2")
    if not proof.get("verified") or proof.get("clean_provider_completion") is not True:
        raise ValueError("M00_R8_PARENT_REAL_IMAGE_NOT_VERIFIED")
    predecessor = r2.read_json(parent_folder / "test-only-record.json")
    if predecessor.get("capture_profile") != "CP02" or predecessor.get("request_fingerprint") is None:
        raise ValueError("M00_R8_PARENT_DEVICE_OR_FINGERPRINT_INVALID")
    source = parent_folder / "generated.png"
    refs_plan_path = root / ".storyos/user-visual-references/calibration-plans/m00-four-scene-20261013.json"
    plan = r2.read_json(refs_plan_path)
    rows = [i for i in plan.get("frames", []) if isinstance(i, dict) and i.get("id") == "C02"]
    if len(rows) != 1 or rows[0].get("capture_profile") != cfg["capture_profile"]:
        raise ValueError("M00_R8_STYLE_PLAN_PROFILE_INVALID")
    style_row = (rows[0].get("references") or [None])[0]
    if not isinstance(style_row, dict) or style_row.get("kind") != "capture_style":
        raise ValueError("M00_R8_STYLE_KIND_INVALID")
    style = (root / str(style_row.get("path") or "")).resolve()
    if (not style.is_relative_to((root / ".storyos/user-visual-references").resolve())
            or not style.is_file() or r2.digest(style) != style_row.get("sha256")):
        raise ValueError("M00_R8_STYLE_SHA_INVALID")
    device = m00_capture_profile_contract.compile_device_contract(cfg["capture_profile"], root=root)
    visual_base = base_visual or r2.visual_profile_bridge_v224.compile_prompt_contract(root / "episodes")["text"]
    visual = r2.rebind_capture_device(visual_base, device["text"])
    source_scene = cfg.get("scene")
    if not isinstance(source_scene, str) or len(source_scene) < 70:
        raise ValueError("M00_R8_SOURCE_SCENE_EMPTY")
    scene = source_scene + "\n" + delta.prompt_suffix(contract)
    prompt = m00_style_guard.enforce(scene_prompt=scene, visual_contract=visual)
    prompt = m00_scene_fidelity_guard.enforce_event(
        scene_prompt=prompt, source_scene_prompt=source_scene, visual_contract=visual)
    prompt = m00_scene_fidelity_guard.enforce_motion(scene_prompt=prompt, visual_contract=visual)
    refs = [
        {"path": source.relative_to(root).as_posix(), "sha256": proof["image_sha256"],
         "kind": "identity", "role": "retain_same_person_bicycle_fixed_architecture_NOT_prior_pose"},
        {"path": style.relative_to(root).as_posix(), "sha256": r2.digest(style),
         "kind": "capture_style", "role": "camera_physics_ONLY_no_story_content"},
    ]
    identity = {
        "test_only": True, "sequence_id": cfg["sequence_id"], "frame_id": cfg["frame_id"],
        "revision": "R8_NEW_CASE_NOT_R7_RETRY", "anchor": "C02-R2",
        "anchor_image_sha256": proof["image_sha256"],
        "anchor_original_request_fingerprint": predecessor["request_fingerprint"],
        "state_delta_sha256": delta.contract_sha256(contract),
        "case_sha256": r2.digest(cfg_path), "plan_sha256": r2.digest(refs_plan_path),
        "device_sha256": device["sha256"], "style_sha256": r2.digest(style),
        "visual_sha256": hashlib.sha256(visual.encode("utf-8")).hexdigest(),
        "scene_prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "references": refs,
    }
    fingerprint = r2.stable_hash(identity)
    request = {
        "request_fingerprint": fingerprint, "payload_model": "gpt-image-2.5-flare",
        "payload_quality": "high", "canvas": {"width": 1080, "height": 1350, "aspect_ratio": "4:5"},
        "references": refs, "scene_prompt": prompt,
    }
    transport = r2.codex_subscription_image.payload_transport_prompt(request, "1080x1350", 2)
    transport += "\nTEST_ONLY_NEW_REVISION, NOT a retry of R7 S01/S02; no other tools or production authority."
    return {"identity": identity, "fingerprint": fingerprint,
            "case": {"new_frame_id": cfg["frame_id"], "observable_evidence": contract["observable_changes"]},
            "device": device, "request": request, "prompt": transport, "ref_paths": [source, style],
            "out": root / ".storyos/user-visual-references/test-only-calibration" / cfg["frame_id"]}


def pixel_distance_diagnostic(a: Path, b: Path) -> dict:
    """Non-authoritative coarse pixel metric, NEVER a semantic PASS/FAIL.

    Aggregate/color changes may reflect legitimate movement or simple
    exposure drift; architecture and pose checks still need both real images.
    """
    from PIL import Image, ImageChops, ImageStat
    with Image.open(a) as first:
        aa = first.convert("RGB").resize((64, 64))
    with Image.open(b) as second:
        bb = second.convert("RGB").resize((64, 64))
    diff = ImageChops.difference(aa, bb)
    l1 = sum(ImageStat.Stat(diff).mean) / (3 * 255)
    return {"coarse_rgb_l1": round(l1, 6), "review_only": True,
            "proves_story_progression": False,
            "proves_background_continuity": False}


def pixel_pair_advisory(*, repo: Path = ROOT, review: dict | None = None) -> dict:
    root = repo.resolve()
    base = root / ".storyos/user-visual-references/test-only-calibration"
    original = m00_calibration_receipts.inspect_frame(base, "C02-R2")
    new = m00_calibration_receipts.inspect_frame(base, "C02-T01")
    result = {
        "pair": ["C02-R2", "C02-T01"],
        "both_verified": original.get("verified", False) and new.get("verified", False),
        "source_sha256": original.get("image_sha256"), "new_sha256": new.get("image_sha256"),
        "status": "PENDING_FULL_IMAGE_PAIR_REVIEW", "advisory_only": True,
        "production_approved": False, "automatic_pass": False,
    }
    if not result["both_verified"]:
        return result
    if original["image_sha256"] == new["image_sha256"]:
        return {**result, "status": "IDENTICAL_PIXELS_DO_NOT_PROVE_NEW_ACTION"}
    result["pixel_diagnostics"] = pixel_distance_diagnostic(
        base / "C02-R2/generated.png", base / "C02-T01/generated.png")
    evidence = r2.read_json(base / "C02-T01/test-only-record.json")
    identity = evidence.get("request_identity")
    if (not isinstance(identity, dict) or
            evidence.get("request_fingerprint") != r2.stable_hash(identity) or
            identity.get("frame_id") != "C02-T01" or
            identity.get("anchor_image_sha256") != original["image_sha256"] or
            identity.get("references", [{}])[0].get("sha256") != original["image_sha256"]):
        return {**result, "status": "IMMUTABLE_REQUEST_OR_PARENT_SHA_DRIFT"}
    if review is None:
        return result
    if (not isinstance(review, dict)
            or review.get("source_sha256") != original["image_sha256"]
            or review.get("new_sha256") != new["image_sha256"]
            or review.get("reviewed_with") != "both_full_images"
            or not str(review.get("reviewer") or "").strip()
            or not str(review.get("observations") or "").strip()
            or not isinstance(review.get("checks"), dict)
            or set(review["checks"]) != set(REVIEW_CHECKS)
            or any(x not in r7.VALID for x in review["checks"].values())):
        return {**result, "status": "REVIEW_INVALID_OR_INCOMPLETE"}
    statuses = set(review["checks"].values())
    result["status"] = ("REPAIR_RECOMMENDED" if "FAIL" in statuses else
                        "UNCERTAIN_NEEDS_FULL_REVIEW" if "UNCERTAIN" in statuses else "ADVISORY_PAIR_PASS")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("plan", "run", "review"))
    parser.add_argument("--ack-testonly-paid-image", action="store_true")
    parser.add_argument("--timeout", type=int, default=420)
    parser.add_argument("--review", type=Path)
    args = parser.parse_args()
    if args.operation == "review":
        notes = r2.read_json(args.review) if args.review else None
        print(json.dumps(pixel_pair_advisory(review=notes), ensure_ascii=False))
        return 0
    bundle = make_bundle()
    if args.operation == "plan":
        print(json.dumps({
            "frame_id": bundle["case"]["new_frame_id"], "source": "C02-R2",
            "request_fingerprint": bundle["fingerprint"],
            "state_delta_sha256": bundle["identity"]["state_delta_sha256"],
            "device": bundle["device"]["profile_id"],
            "reference_kinds": [x["kind"] for x in bundle["request"]["references"]],
            "status": "READY_TESTONLY_NOT_DISPATCHED",
        }, ensure_ascii=False))
        return 0
    if not args.ack_testonly_paid_image:
        raise SystemExit("M00_R8_REAL_IMAGE_EXPLICIT_ACK_REQUIRED")
    evidence = r2.execute_bundle(bundle, timeout=args.timeout)
    print(json.dumps({"frame": evidence["frame"], "status": evidence["status"],
                      "sha256": evidence.get("output_sha256"), "dimensions": evidence.get("dimensions"),
                      "request_id": evidence["request_id"]}, ensure_ascii=False))
    return 0 if evidence["status"] == "IMAGE_CREATED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
