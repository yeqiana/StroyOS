from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SYSTEM = ROOT / "episodes" / "_system"
if str(SYSTEM) not in sys.path:
    sys.path.insert(0, str(SYSTEM))

import frame_semantic_review as semantic
import incremental_frame_review as incremental


class IncrementalFrameReusePhase4Tests(unittest.TestCase):
    def test_review_data_reads_canonical_persistence_without_file_projection(self) -> None:
        evidence = {"frame": "01", "decision": "pass"}
        ep = ROOT / "episodes" / "test"
        with mock.patch.object(
            incremental.frame_review_persistence, "load", return_value=evidence
        ) as load:
            self.assertEqual(evidence, incremental._review_data(ep, "01"))
        load.assert_called_once_with(ep.resolve(), 1)

    def test_phase5a_scoped_canary_verify_does_not_require_full_incremental_baseline(self) -> None:
        ep = ROOT / "episodes" / "test"
        frame = {"frame": "01", "sha256": "a" * 64, "path_rel": "approved/01.png"}
        review = {"critic_provenance": {"review_scope": semantic.PHASE5A_SINGLE_FRAME_SCOPE}}
        with (
            mock.patch.object(incremental, "review_required", return_value=True),
            mock.patch.object(incremental.base, "frame_records", return_value=[frame]),
            mock.patch.object(incremental, "_review_data", return_value=review),
            mock.patch.object(incremental, "_phase5a_scoped_evidence_allowed", return_value=True),
            mock.patch.object(incremental.base, "verify_scoped_review", return_value=[]) as scoped,
            mock.patch.object(incremental.base, "verify_episode", return_value=["full-only-error"]) as full,
            mock.patch.object(incremental.verified_review_authority, "verify_episode_review_authority",
                              return_value={"status": "PASS", "errors": []}),
            mock.patch.object(incremental.base, "episode_contract_version", return_value="2.1.0"),
            mock.patch.object(incremental, "caption_state") as captions,
        ):
            self.assertEqual([], incremental.verify_episode(ep, metadata_only=True))
        scoped.assert_called_once()
        full.assert_not_called()
        captions.assert_not_called()

    def test_formal_episode_verify_keeps_full_episode_authority(self) -> None:
        ep = ROOT / "episodes" / "test"
        frame = {"frame": "01", "sha256": "a" * 64, "path_rel": "approved/01.png"}
        with (
            mock.patch.object(incremental, "review_required", return_value=True),
            mock.patch.object(incremental.base, "frame_records", return_value=[frame]),
            mock.patch.object(incremental, "_review_data", return_value={}),
            mock.patch.object(incremental, "_phase5a_scoped_evidence_allowed", return_value=False),
            mock.patch.object(incremental.base, "verify_episode", return_value=["full-authority-error"]) as full,
            mock.patch.object(incremental.verified_review_authority, "verify_episode_review_authority",
                              return_value={"status": "PASS", "errors": []}),
            mock.patch.object(incremental.base, "episode_contract_version", return_value="2.0.3.3"),
        ):
            self.assertEqual(["full-authority-error"], incremental.verify_episode(ep, metadata_only=True))
        full.assert_called_once()

    def _frames(self, *, changed: str | None = None, attempt2: str | None = None) -> list[dict]:
        frames = []
        for number in range(1, 21):
            key = f"{number:02d}"
            sha = f"{number:064x}"
            generation = f"generation-{key}-1"
            if changed == key:
                sha = "f" * 64
            if attempt2 == key:
                generation = f"generation-{key}-2"
            frames.append({
                "frame": key,
                "sha256": sha,
                "path_rel": f"episodes/test/assets/{key}.png",
                "logical_asset_key": f"episodes/test/frame-{key}",
                "generation_key": generation,
            })
        return frames

    def _evidence(self, frame: dict) -> dict:
        contexts = {"story_sha256": "story-stable", "visual_sha256": "visual-stable"}
        phase3 = {"frame_contract_sha256": f"contract-{frame['frame']}"}
        identity = {
            "logical_asset_key": frame["logical_asset_key"],
            "generation_key": frame["generation_key"],
            "sha256": frame["sha256"],
            "source_binding": {},
        }
        return {
            "schema_version": semantic.SCHEMA_VERSION,
            "story_os_version": "2.0.3.4",
            "asset_sha256": frame["sha256"],
            "asset_path": frame["path_rel"],
            **contexts,
            **phase3,
            "source_binding": {},
            "logical_asset_key": frame["logical_asset_key"],
            "generation_key": frame["generation_key"],
            "model_policy_sha256": "frozen-policy-sha",
            "evidence_fingerprint": semantic.frame_evidence_fingerprint(
                identity,
                contexts=contexts,
                phase3_contexts=phase3,
                policy_sha256="frozen-policy-sha",
            ),
            "critic_provenance": {"review_scope": "FULL_FRAME_SET"},
            "decision": "pass",
            "issue_codes": [],
            "checks": {},
        }

    def _planned(self, *, frames: list[dict], missing: set[str] | None = None,
                 missing_issue_codes: set[str] | None = None,
                 caption_sha: str = "caption-stable",
                 contexts: dict[str, str] | None = None) -> dict:
        records = {frame["frame"]: self._evidence(frame) for frame in self._frames()}
        for key in missing or set():
            records.pop(key, None)
        for key in missing_issue_codes or set():
            records[key].pop("issue_codes", None)
        current_contexts = contexts or {"story_sha256": "story-stable", "visual_sha256": "visual-stable"}
        with (
            mock.patch.object(incremental, "review_required", return_value=True),
            mock.patch.object(incremental.base, "frame_records", return_value=frames),
            mock.patch.object(incremental.base, "context_hashes", return_value=current_contexts),
            mock.patch.object(incremental, "caption_state", return_value={
                "mode": "per_frame", "source_path": "captions.json", "source_sha256": "caption-source",
                "frame_sha256": {frame["frame"]: caption_sha for frame in frames}}),
            mock.patch.object(incremental.base, "episode_contract_version", return_value="2.0.3.4"),
            mock.patch.object(incremental.base, "directing_v3_required", return_value=False),
            mock.patch.object(incremental.base, "bound_review_policy_sha256", return_value="frozen-policy-sha"),
            mock.patch.object(incremental, "_review_data", side_effect=lambda _ep, key: records.get(key)),
            mock.patch.object(incremental.base, "phase3_context_hashes", side_effect=lambda _ep, key: {
                "frame_contract_sha256": f"contract-{key}"}),
            mock.patch.object(incremental.base, "source_binding", return_value={}),
            mock.patch.object(incremental.base, "validate_bound_review", return_value=[]),
            mock.patch.object(incremental.base, "checks_for_version", return_value=[]),
            mock.patch.object(incremental.runtime_provenance, "validate_critic_provenance", return_value=[]),
        ):
            return incremental.build_plan(ROOT / "episodes" / "test")

    def test_unchanged_frames_reuse_and_caption_drift_stays_independent(self) -> None:
        frames = self._frames()
        plan = self._planned(frames=frames, caption_sha="caption-changed")
        self.assertEqual("NOOP", plan["action"])
        self.assertEqual([], plan["dirty_frames"])
        self.assertEqual([], plan["missing_evidence_frames"])
        self.assertEqual([row["frame"] for row in frames], plan["reused_frames"])

    def test_single_artifact_change_keeps_context_separate_from_dirty(self) -> None:
        frames = self._frames(changed="03")
        plan = self._planned(frames=frames)
        self.assertEqual("PATCH", plan["action"])
        self.assertEqual(["03"], plan["dirty_frames"])
        self.assertEqual(["02", "03", "04"], plan["context_frames"])
        self.assertNotIn("02", plan["dirty_frames"])
        self.assertNotIn("04", plan["dirty_frames"])
        self.assertEqual(19, len(plan["reused_frames"]))

    def test_repair_attempt2_becomes_current_and_attempt1_review_is_not_reused(self) -> None:
        frames = self._frames(attempt2="03")
        plan = self._planned(frames=frames)
        self.assertEqual("PATCH", plan["action"])
        self.assertEqual(["03"], plan["dirty_frames"])
        self.assertIn("current_generation_changed", plan["reasons"]["03"])

    def test_three_repaired_frames_are_only_dirty_model_targets(self) -> None:
        frames = self._frames()
        for key in ("03", "07", "11"):
            row = next(item for item in frames if item["frame"] == key)
            row["sha256"] = "f" * 64
            row["generation_key"] = f"generation-{key}-2"
        plan = self._planned(frames=frames)
        self.assertEqual("PATCH", plan["action"])
        self.assertEqual(["03", "07", "11"], plan["dirty_frames"])
        self.assertEqual(["02", "03", "04", "06", "07", "08", "10", "11", "12"],
                         plan["context_frames"])
        self.assertEqual(17, len(plan["reused_frames"]))

    def test_six_repaired_frames_do_not_trigger_full_review_by_ratio(self) -> None:
        frames = self._frames()
        for key in ("02", "05", "08", "11", "14", "17"):
            row = next(item for item in frames if item["frame"] == key)
            row["sha256"] = "f" * 64
            row["generation_key"] = f"generation-{key}-2"
        plan = self._planned(frames=frames)
        self.assertEqual("PATCH", plan["action"])
        self.assertEqual(0.3, plan["dirty_ratio"])
        self.assertEqual(6, len(plan["dirty_frames"]))
        self.assertEqual(14, len(plan["reused_frames"]))
        self.assertEqual("DIRTY_FRAME_PATCH", plan["review_scope_reason"])

    def test_first_review_all_missing_still_requires_full_baseline(self) -> None:
        plan = self._planned(frames=self._frames(), missing={f"{i:02d}" for i in range(1, 21)})
        self.assertEqual("FULL", plan["action"])
        self.assertEqual("FIRST_REVIEW", plan["review_scope_reason"])
        self.assertEqual(20, len(plan["missing_evidence_frames"]))

    def test_story_source_drift_invalidates_global_frame_context(self) -> None:
        plan = self._planned(frames=self._frames(), contexts={
            "story_sha256": "story-changed", "visual_sha256": "visual-stable"})
        self.assertEqual("FULL", plan["action"])
        self.assertEqual(20, len(plan["dirty_frames"]))
        self.assertEqual([], plan["reused_frames"])

    def test_missing_review_evidence_fails_closed_without_promoting_context(self) -> None:
        frames = self._frames()
        plan = self._planned(frames=frames, missing={"03"})
        self.assertEqual("PATCH", plan["action"])
        self.assertEqual(["03"], plan["dirty_frames"])
        self.assertEqual(["03"], plan["missing_evidence_frames"])
        self.assertEqual(["02", "03", "04"], plan["context_frames"])

    def test_frame_review_missing_issue_codes_is_not_reusable(self) -> None:
        plan = self._planned(frames=self._frames(), missing_issue_codes={"03"})
        self.assertEqual(["03"], plan["dirty_frames"])
        self.assertIn("review_not_pass", plan["reasons"]["03"])

    def test_fingerprint_changes_on_generation_or_policy_but_not_path_or_timestamp(self) -> None:
        frame = self._frames()[0]
        base_kwargs = {"contexts": {"story": "s1"}, "phase3_contexts": {"contract": "c1"},
                       "policy_sha256": "policy-a"}
        first = semantic.frame_evidence_fingerprint(frame, **base_kwargs)
        moved = {**frame, "path_rel": "episodes/test/moved.png", "recorded_at": "later"}
        self.assertEqual(first, semantic.frame_evidence_fingerprint(moved, **base_kwargs))
        self.assertNotEqual(first, semantic.frame_evidence_fingerprint(
            {**frame, "generation_key": "generation-01-2"}, **base_kwargs))
        self.assertNotEqual(first, semantic.frame_evidence_fingerprint(
            frame, **{**base_kwargs, "policy_sha256": "policy-b"}))

    def test_synthetic_benchmark_only_calls_critic_for_dirty_targets(self) -> None:
        """Deterministic synthetic model workload: 300 ms per target, no Provider calls."""
        frames = self._frames()
        one = self._planned(frames=[{**row, "sha256": "f" * 64} if row["frame"] == "03" else row
                                   for row in frames])
        three_changed = {key: {**row, "sha256": "f" * 64, "generation_key": f"generation-{key}-2"}
                         for key, row in ((row["frame"], row) for row in frames) if key in {"03", "07", "11"}}
        three = self._planned(frames=[three_changed.get(row["frame"], row) for row in frames])
        full_reverify_calls = len(frames)
        one_calls = len(one["dirty_frames"])
        three_calls = len(three["dirty_frames"])
        self.assertEqual((20, 1, 3), (full_reverify_calls, one_calls, three_calls))
        self.assertEqual(95.0, round(100 * (full_reverify_calls - one_calls) / full_reverify_calls, 1))
        self.assertEqual(85.0, round(100 * (full_reverify_calls - three_calls) / full_reverify_calls, 1))
        # Deterministic projected review wall in milliseconds; this does not sleep or
        # invoke an external model and reflects only actual target-frame calls.
        self.assertEqual(6000, full_reverify_calls * 300)
        self.assertEqual(300, one_calls * 300)
        self.assertEqual(900, three_calls * 300)


if __name__ == "__main__":
    unittest.main()
