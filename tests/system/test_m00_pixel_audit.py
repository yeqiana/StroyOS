#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""No-image/no-DB smoke tests for actual-pixel M00 audit boundaries."""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[2] / "episodes" / "_system"
sys.path.insert(0, str(HERE))
import m00_pixel_audit as audit  # noqa: E402


class M00PixelAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.rel = "episodes/sample/media/approved/01.png"
        self.image = self.root / self.rel
        self.image.parent.mkdir(parents=True, exist_ok=True)
        from PIL import Image
        Image.new("RGB", (19, 25), (145, 120, 100)).save(self.image)
        self.sha = hashlib.sha256(self.image.read_bytes()).hexdigest()
        self.sample_set = self.root / "samples.json"
        self.save_samples(self.sha)

    def save_samples(self, sha, rel=None):
        self.sample_set.write_text(json.dumps({
            "schema_version": 1,
            "purpose": "read_only_pixel_audit",
            "samples": [
                {"id": "example", "asset_path": rel or self.rel, "sha256": sha,
                 "sample_note": "not a generation prompt"}
            ],
        }), encoding="utf-8")

    def record(self, **overrides):
        row = {
            "source_sha256": self.sha,
            "reviewer": "independent-preview-observer",
            "observations": "Camera position and available light have been inspected.",
            "reviewed_with": "full_image",
            "checks": {c: "PASS" for c in audit.CHECKS},
        }
        row.update(overrides)
        return {"example": row}

    def check(self, review=None):
        return audit.audit(asset_root=self.root, sample_set=self.sample_set,
                           review_records=review)["samples"][0]

    def test_missing_pixels_are_not_approved(self):
        self.image.unlink()
        self.assertEqual(self.check(self.record())["status"], "SOURCE_MISSING")

    def test_sha_drift_fails_closed_before_review(self):
        self.image.write_bytes(b"unexpected")
        self.assertEqual(self.check(self.record())["status"], "SOURCE_SHA_DRIFT")

    def test_broken_image_is_never_considered_a_pixel_review_pass(self):
        self.image.write_bytes(b"not an image")
        self.save_samples(hashlib.sha256(self.image.read_bytes()).hexdigest())
        self.assertEqual(self.check()["status"], "DECODE_FAILURE")

    def test_pixel_metadata_alone_never_claims_style_pass(self):
        row = self.check()
        self.assertEqual(row["status"], "NEEDS_PIXEL_REVIEW")
        self.assertEqual((row["width"], row["height"]), (19, 25))

    def test_review_must_be_bound_to_exact_sha(self):
        review = self.record(source_sha256="a" * 64)
        self.assertEqual(self.check(review)["status"], "REVIEW_INCOMPLETE")

    def test_review_requires_all_six_fields_and_notes(self):
        review = self.record()
        review["example"]["checks"].pop("story_event_fidelity")
        self.assertEqual(self.check(review)["status"], "REVIEW_INCOMPLETE")
        review = self.record(observations="")
        self.assertEqual(self.check(review)["status"], "REVIEW_INCOMPLETE")

    def test_a_preview_only_review_cannot_pass_as_full_pixel_review(self):
        self.assertEqual(self.check(self.record(reviewed_with="preview"))["status"],
                         "FULL_IMAGE_REVIEW_REQUIRED")

    def test_full_image_review_remains_advisory_even_when_all_checks_pass(self):
        result = audit.audit(asset_root=self.root, sample_set=self.sample_set,
                             review_records=self.record())
        self.assertEqual(result["samples"][0]["status"], "ADVISORY_PIXEL_PASS")
        self.assertFalse(result["grants_visual_lock_pass"])
        self.assertFalse(result["grants_episode_stage"])
        self.assertFalse(result["grants_release"])
        self.assertFalse(result["may_call_image_generation"])

    def test_failed_check_is_not_automatically_repaired(self):
        row = self.record()
        row["example"]["checks"]["non_cinematic_presentation"] = "FAIL"
        self.assertEqual(self.check(row)["status"], "REPAIR_RECOMMENDED")

    def test_uncertainty_is_not_a_pass(self):
        row = self.record()
        row["example"]["checks"]["photographer_and_viewpoint"] = "UNCERTAIN"
        self.assertEqual(self.check(row)["status"], "FURTHER_PIXEL_REVIEW_REQUIRED")

    def test_path_traversal_fails_without_touching_external_source(self):
        self.save_samples(self.sha, "../../outside.png")
        with self.assertRaisesRegex(ValueError, "UNSAFE_ASSET_PATH"):
            self.check()

    def test_strict_cli_rejects_pending_then_accepts_review_without_stage_authority(self):
        import io
        from contextlib import redirect_stdout
        argv = ["--sample-set", str(self.sample_set),
                "--asset-root", str(self.root), "--strict"]
        with redirect_stdout(io.StringIO()):
            self.assertEqual(audit.main(argv), 1)
        reviews_path = self.root / "reviews.json"
        reviews_path.write_text(json.dumps(self.record()), encoding="utf-8")
        with redirect_stdout(io.StringIO()) as stdout:
            self.assertEqual(audit.main(argv + ["--reviews", str(reviews_path)]), 0)
        receipt = json.loads(stdout.getvalue())
        self.assertFalse(receipt["grants_release"])
        self.assertFalse(receipt["grants_visual_lock_pass"])

    def test_original_test_sample_set_does_not_belong_to_generation_prompts(self):
        # The asset roster is observational and cannot become a Story prompt.

        samples = audit.read_samples(audit.DEFAULT_SAMPLES)
        self.assertGreaterEqual(len(samples), 6)
        self.assertGreaterEqual(len({s["asset_path"].split("/")[1] for s in samples}), 3)
        self.assertTrue(all(s["asset_path"].endswith(".png") for s in samples))
        # No sample action or scene is imported into M00 scene prompt compilation.
        from m00_style_guard import enforce
        from visual_profile_bridge_v224 import compile_prompt_contract
        visual = compile_prompt_contract(audit.ROOT / "episodes")
        subject = "一位成年人静静翻看相册。"
        output = enforce(scene_prompt=subject, visual_contract=visual["text"])
        for example in samples:
            self.assertNotIn(example["asset_path"], output)
            self.assertNotIn(example["sample_note"], output)


if __name__ == "__main__":
    unittest.main()
