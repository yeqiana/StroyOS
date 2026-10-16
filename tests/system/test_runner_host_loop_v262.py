#!/usr/bin/env python3
"""V2.6.2 closure chain: artifact-save collision, CODEX_HOME recovery, and the
bounded continuous host loop that finally wires image dispatch into the main entry."""
from __future__ import annotations
import json, os, sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SYSTEM = ROOT / "episodes/_system"
if str(SYSTEM) not in sys.path:
    sys.path.insert(0, str(SYSTEM))

import auto_repair_enqueue
import baseline_candidate_pool
import character_appearance_anchor
import codex_subscription_image
import episode_runner
import image_artifact_collector
import image_blocked_recovery
import image_model_policy
import image_scheduler
import identity_continuity
import machine_action_executor
import next_action
import production_ledger
import production_ledger_manage
import raw_candidate_budget
import reference_arbitrator
import ledger_call
import product_runtime_adapter
import scheduler_core
import vision_review_executor
import visual_lock_baseline_gate
import visual_lock_v21
import workflow_runner

CALL_ID = "exec-863861d5-1e96-49b1-9908-139a45c06cb4"
# Exact signature captured from meta/image-workers/01-9ae48137181c-a1.jsonl (episode 10-03).
COLLISION_LINE = (
    "WARN codex_image_generation_extension::tool: failed to save generated image: "
    "当文件已存在时，无法创建该文件。 (os error 183) call_id=" + CALL_ID +
    " output_dir=C:\\Users\\79873\\.codex\\generated_images\\01a08efd-3a7f-78d2-a60c-b15adc497218"
)
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"q" * 64


class ArtifactSaveCollisionTests(unittest.TestCase):
    def test_collision_is_a_provider_technical_failure(self):
        self.assertEqual(image_model_policy.classify_backend_error(COLLISION_LINE),
                         image_model_policy.ARTIFACT_SAVE_COLLISION)

    def test_collision_is_not_charged_as_content_repair(self):
        import image_scheduler
        self.assertEqual(image_scheduler.classify_error(COLLISION_LINE),
                         image_model_policy.ARTIFACT_SAVE_COLLISION)
        self.assertNotIn(image_model_policy.ARTIFACT_SAVE_COLLISION,
                         image_scheduler.NON_REGENERATING_FAILURE_CODES)

    def test_collision_does_not_masquerade_as_model_unavailable(self):
        code = image_model_policy.classify_backend_error(COLLISION_LINE)
        self.assertNotIn(code, {image_model_policy.MODEL_UNAVAILABLE,
                                image_model_policy.RATE_LIMIT_429,
                                image_model_policy.BACKEND_5XX})

    def test_call_id_is_extracted_for_secondary_recovery(self):
        self.assertEqual(image_artifact_collector._call_ids(COLLISION_LINE), [CALL_ID])

    def test_recovery_root_follows_codex_home(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.dict(os.environ, {"CODEX_HOME": td}):
                self.assertEqual(image_artifact_collector.generated_images_root(),
                                 Path(td) / "generated_images")
            self.assertEqual(image_artifact_collector.generated_images_root(),
                             Path.home() / ".codex" / "generated_images")

    def test_recovery_finds_artifact_named_after_call_id(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory(prefix="repository-") as wd:
            hidden = Path(home) / "generated_images" / "thread-xyz" / f"{CALL_ID}.png"
            hidden.parent.mkdir(parents=True)
            hidden.write_bytes(PNG_BYTES)
            log = Path(wd) / "worker.jsonl"
            log.write_text(COLLISION_LINE, encoding="utf-8")
            with patch.dict(os.environ, {"CODEX_HOME": home}):
                self.assertEqual(image_artifact_collector.recover_codex_generated(log, Path(wd)),
                                 hidden.resolve())


class LocalImageDispatchTests(unittest.TestCase):
    def test_codex_image_executor_is_local(self):
        for name in ("GENERATE_IMAGES", "RETRY_TECHNICAL_FAILURES", "REPAIR_FAILED_IMAGES"):
            self.assertEqual(episode_runner.local_image_action({"action": name, "executor": "CODEX_IMAGE"}), name)

    def test_host_owned_actions_stay_with_the_host(self):
        rows = [{"action": "GENERATE_IMAGES", "executor": "WORK"},
                {"action": "REVIEW_GENERATED_IMAGES", "executor": "CODEX_IMAGE"},
                {"action": "PRODUCT_REVIEW", "executor": "CODEX_IMAGE"},
                {"action": "VISUAL_LOCK", "executor": "WORK"},
                {"action": "COMPLETE"}, {}, None, "GENERATE_IMAGES"]
        for row in rows:
            self.assertIsNone(episode_runner.local_image_action(row), row)

    def test_codex_vision_review_actions_are_local(self):
        for name in ("REVIEW_ORDINARY_BASELINE", "REVIEW_VISUAL_LOCK", "REVIEW_GENERATED_IMAGES", "REVIEW_FINAL_PRODUCTION", "REVIEW_FINAL_PATCH", "REVIEW_FINAL_EXCEPTION", "REVIEW_FINAL_CONTINUATION"):
            action = {"action": name, "executor": "CODEX_VISION"}
            self.assertEqual(vision_review_executor.local_vision_action(action), name)
            self.assertEqual(episode_runner.local_host_action(action), name)
        self.assertIsNone(vision_review_executor.local_vision_action({"action": "PRODUCT_REVIEW", "executor": "WORK"}))
        self.assertIsNone(vision_review_executor.local_vision_action({"action": "REVIEW_ORDINARY_BASELINE", "executor": "WORK"}))

    def test_machine_actions_are_local(self):
        for name in ("PREPARE_BASELINE_CANDIDATE", "RESOLVE_IMAGE_NORMALIZATION", "FINALIZE_VISUAL_LOCK", "PREPARE_PRODUCTION_BATCH", "FINALIZE_PRODUCTION_IMAGES"):
            action = {"action": name, "executor": "MACHINE"}
            self.assertEqual(machine_action_executor.local_machine_action(action), name)
            self.assertEqual(episode_runner.local_host_action(action), name)

    def test_work_actions_remain_host_owned(self):
        baseline = {"action": "REVIEW_ORDINARY_BASELINE", "executor": "WORK"}
        self.assertIsNone(episode_runner.local_host_action(baseline))
        self.assertIsNone(episode_runner.local_host_action({"action": "PRODUCT_REVIEW", "executor": "WORK"}))
        self.assertIsNone(episode_runner.local_host_action({"action": "REVIEW_ORDINARY_BASELINE", "executor": "WEB"}))

    def test_non_local_action_is_refused(self):
        with self.assertRaises(ValueError):
            episode_runner.run_local_image_action(Path("ep"), {"action": "VISUAL_LOCK", "executor": "WORK"})

    def test_run_local_image_action_dispatches_and_refreshes_next_action(self):
        calls, refreshed = [], []

        class FakeScheduler:
            @staticmethod
            def retry_tech(ep): calls.append(("retry_tech", str(ep)))

            @staticmethod
            def run_scheduler_async(ep, workers, timeout, codex):
                calls.append(("scheduler", workers, codex))
                return 7

        class FakeBatch:
            @staticmethod
            def should_use(ep): return False

            @staticmethod
            def run(ep, workers, timeout, codex):
                calls.append(("batch", workers))
                return 9

        class FakeConfig:
            @staticmethod
            def load_config(): return {"production": {"max_inflight_images": 3}}

            @staticmethod
            def get_path(data, dotted, default=None): return data["production"]["max_inflight_images"]

        def fake_write(ep):
            refreshed.append(str(ep))
            return {}

        modules = {"image_scheduler": FakeScheduler, "batch_scheduler": FakeBatch, "storyos_config": FakeConfig}
        with patch.dict(sys.modules, modules), \
                patch.object(episode_runner.next_action, "write", side_effect=fake_write), \
                patch.object(episode_runner.runtime_timeout_policy, "seconds", return_value=123):
            rc = episode_runner.run_local_image_action(Path("ep"), {"action": "GENERATE_IMAGES", "executor": "CODEX_IMAGE"})
            self.assertEqual(rc, 7)
            self.assertEqual(calls, [("scheduler", 3, None)])
            self.assertEqual(refreshed, ["ep"])

            calls.clear(); refreshed.clear()
            rc = episode_runner.run_local_image_action(Path("ep"), {"action": "RETRY_TECHNICAL_FAILURES", "executor": "CODEX_IMAGE"})
            self.assertEqual(rc, 7)
            self.assertEqual(calls, [("retry_tech", "ep"), ("scheduler", 3, None)])
            self.assertEqual(refreshed, ["ep"])

            calls.clear(); refreshed.clear()
            with patch.object(auto_repair_enqueue, "enqueue_marked_repairs", return_value={"repair_items_ready": 1}) as materialize:
                rc = episode_runner.run_local_image_action(Path("ep"), {"action": "REPAIR_FAILED_IMAGES", "executor": "CODEX_IMAGE"})
            self.assertEqual(rc, 7)
            materialize.assert_called_once_with(Path("ep"))
            self.assertEqual(calls, [("scheduler", 3, None)])
            self.assertEqual(refreshed, ["ep"])


class TechnicalRetryPolicyTests(unittest.TestCase):
    def _queue(self, ep: Path, row: dict) -> None:
        (ep / "meta").mkdir(parents=True, exist_ok=True)
        (ep / "meta/production-queue.json").write_text(json.dumps({"schema_version": 1, "items": [row], "waves": []}), encoding="utf-8")

    def test_network_error_is_machine_classified(self):
        self.assertEqual(image_model_policy.classify_backend_error("image generation failed: network error: error sending request"), "NETWORK_ERROR")
        self.assertEqual(image_scheduler.classify_error("NETWORK_ERROR: error sending request"), "NETWORK_ERROR")

    def test_network_error_wins_over_same_invocation_degenerate_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            tiny = Path(td) / "tiny.png"
            codex_subscription_image.Image.new("RGB", (100, 100)).save(tiny, "PNG")
            self.assertTrue(codex_subscription_image.valid_image(tiny))
            self.assertFalse(codex_subscription_image.provider_raw_candidate_viable(tiny))
            code = codex_subscription_image.logged_backend_failure(
                "image generation failed: network error: error sending request",
                returncode=0,
                candidate_valid=True,
                candidate_viable=False,
            )
            self.assertEqual(code, "NETWORK_ERROR")

    def test_good_candidate_is_not_failed_by_incidental_network_warning(self):
        with tempfile.TemporaryDirectory() as td:
            image = Path(td) / "good.png"
            minimum = int(codex_subscription_image.provider_capability.PROVIDER_RAW_MIN_DIMENSION)
            codex_subscription_image.Image.new("RGB", (minimum, minimum)).save(image, "PNG")
            self.assertTrue(codex_subscription_image.provider_raw_candidate_viable(image))
            code = codex_subscription_image.logged_backend_failure(
                "old warning: network error: error sending request",
                returncode=0,
                candidate_valid=True,
                candidate_viable=True,
            )
            self.assertIsNone(code)

    def test_degenerate_candidate_without_technical_log_keeps_canonical_raw_error(self):
        code = codex_subscription_image.logged_backend_failure(
            "image_generation completed",
            returncode=0,
            candidate_valid=True,
            candidate_viable=False,
        )
        self.assertIsNone(code)

    def test_provider_capacity_is_explicit_retryable_technical_failure(self):
        line = "Selected model is at capacity. Please try a different model."
        self.assertEqual(image_model_policy.classify_backend_error(line), "PROVIDER_CAPACITY")
        self.assertEqual(image_scheduler.classify_error(line), "PROVIDER_CAPACITY")
        self.assertEqual(image_scheduler.classify_error("PROVIDER_CAPACITY: requested=gpt-image-2"), "PROVIDER_CAPACITY")
        self.assertIn("PROVIDER_CAPACITY", image_scheduler.RETRYABLE_TECH_CODES)

    def test_local_workspace_permission_is_retryable_without_weakening_provider_403(self):
        grant_error = (
            "CODEX_USER_RUNNER_WORKSPACE_UNAVAILABLE: failed to grant runner access to "
            "D:\\repo\\runtime\\codex-user-runner\\tmp\\story-os-image-abc: Access is denied."
        )
        temp_error = (
            "[Errno 13] Permission denied: "
            "'C:\\Users\\u\\AppData\\Local\\Temp\\story-os-image-xyz\\reference-01.png'"
        )
        self.assertEqual(image_model_policy.classify_backend_error(grant_error), "LOCAL_WORKSPACE_PERMISSION")
        self.assertEqual(image_model_policy.classify_backend_error(temp_error), "LOCAL_WORKSPACE_PERMISSION")
        self.assertIn("LOCAL_WORKSPACE_PERMISSION", image_scheduler.RETRYABLE_TECH_CODES)
        self.assertEqual(image_model_policy.classify_backend_error("HTTP 403 Forbidden from image provider"), "PERMISSION_403")

    def test_legacy_permission_403_queue_row_reclassifies_from_local_error_text(self):
        item = {
            "technical_failure_code": "PERMISSION_403",
            "last_error": "[Errno 13] Permission denied: C:\\Temp\\story-os-image-abc\\reference-01.png",
        }
        self.assertEqual(image_scheduler._technical_retry_code(item), "LOCAL_WORKSPACE_PERMISSION")

    def test_worker_process_lost_must_reconcile_prior_attempt_before_retry(self):
        with tempfile.TemporaryDirectory() as td:
            ep = Path(td)
            self._queue(ep, {"id": "q1", "frame": 3, "kind": "baseline_candidate", "scope": "repair", "status": "tech_failed", "attempts": 1, "technical_failure_code": "WORKER_PROCESS_LOST", "last_error": "worker disappeared before terminal receipt"})
            state = {
                "logical_asset_key": "_external/test/frame-03",
                "attempts_consumed": 1,
                "remaining_attempts": 1,
                "active_attempt_index": None,
            }
            with patch.object(
                    image_scheduler, "_shared_generation_attempt_state",
                    return_value=state), patch.object(
                    image_scheduler.generation_attempt_authority, "load_attempt",
                    return_value=None):
                result = image_scheduler.retry_tech(
                    ep, sleep_fn=lambda _seconds: self.fail("shared final retry has no legacy backoff"))
            queue = json.loads((ep / "meta/production-queue.json").read_text(encoding="utf-8"))
            # A missing process is not proof the provider did not complete.
            self.assertEqual(result["requeued"], 0)
            self.assertEqual(result["backoff_seconds"], 0)
            self.assertEqual(queue["items"][0]["status"], "external_blocked")
            self.assertEqual(
                queue["items"][0]["external_block"]["reason"],
                "previous_generation_attempt_missing",
            )

    def test_exhausted_shared_budget_blocks_capacity_retry_immediately(self):
        item = {"id": "q1", "frame": 1, "attempts": 2}
        with tempfile.TemporaryDirectory() as td, \
             patch.object(image_scheduler, "_shared_generation_attempt_state",
                               return_value={
                                   "logical_asset_key": "_external/test/frame-01",
                                   "attempts_consumed": 2,
                                   "remaining_attempts": 0,
                                   "active_attempt_index": None,
                               }):
            status = image_scheduler._terminal_technical_status(
                Path(td), item, "PROVIDER_CAPACITY")
        self.assertEqual(status, "external_blocked")
        self.assertEqual(
            item["external_block"]["reason"],
            "shared_generation_attempt_budget_exhausted")
        self.assertEqual(item["external_block"]["code"], "PROVIDER_CAPACITY")

    def test_capacity_exhaustion_can_advance_non_strict_model_without_erasing_history(self):
        item = {"attempts": 3, "technical_retry_epoch_start_attempt": 0,
                "model": "gpt-image-2.5-flare", "strict_model": False,
                "external_block": {"reason": "technical_retry_exhausted"}}
        target = image_scheduler._apply_model_failover(item, "PROVIDER_CAPACITY")
        self.assertEqual(target, "gpt-image-2.5-sunburst")
        self.assertEqual(item["model"], "gpt-image-2.5-sunburst")
        self.assertEqual(item["technical_retry_epoch_start_attempt"], 3)
        self.assertEqual(item["model_failovers"][0]["from"], "gpt-image-2.5-flare")
        self.assertNotIn("external_block", item)

    def test_strict_model_never_auto_fails_over(self):
        item = {"attempts": 3, "model": "gpt-image-2.5-flare", "strict_model": True}
        self.assertIsNone(image_scheduler._apply_model_failover(item, "PROVIDER_CAPACITY"))
        self.assertEqual(item["model"], "gpt-image-2.5-flare")

    def test_scheduler_stays_retryable_while_an_availability_fallback_exists(self):
        queue = {"items": [{"status": "external_blocked", "model": "gpt-image-2.5-sunburst",
                            "strict_model": False, "technical_failure_code": "PROVIDER_CAPACITY"}]}
        self.assertEqual(image_scheduler._scheduler_terminal_rc(
            queue,has_block=False,has_failure=True),21)
        queue["items"][0]["model"]="gpt-image-2"
        self.assertEqual(image_scheduler._scheduler_terminal_rc(
            queue,has_block=False,has_failure=True),24)

    def test_one_remaining_shared_attempt_requeues_without_legacy_backoff(self):
        with tempfile.TemporaryDirectory() as td:
            ep = Path(td)
            self._queue(ep, {"id": "q1", "frame": 1, "kind": "baseline_candidate", "scope": "baseline_candidate", "status": "tech_failed", "attempts": 1, "technical_failure_code": "NETWORK_ERROR", "last_error": "network"})
            slept = []
            state = {
                "logical_asset_key": "_external/test/frame-01",
                "attempts_consumed": 1,
                "remaining_attempts": 1,
                "active_attempt_index": None,
            }
            # Remaining budget alone is not permission to retry. The prior
            # Provider invocation must have a durable FAILED_AFTER_DISPATCH
            # terminal Attempt before any second paid dispatch can be queued.
            with patch.object(
                    image_scheduler, "_shared_generation_attempt_state",
                    return_value=state), patch.object(
                    image_scheduler.generation_attempt_authority, "load_attempt",
                    return_value={"status": "FAILED_AFTER_DISPATCH"}):
                result = image_scheduler.retry_tech(
                    ep, sleep_fn=lambda seconds: slept.append(seconds))
            queue = json.loads((ep / "meta/production-queue.json").read_text(encoding="utf-8"))
            self.assertEqual(result["requeued"], 1)
            self.assertEqual(result["backoff_seconds"], 0)
            self.assertEqual(slept, [])
            row = queue["items"][0]
            self.assertEqual(row["status"], "queued")
            self.assertEqual(row["generation_attempt_reason"], "TECHNICAL_RETRY")
            self.assertEqual(
                row["technical_retry_shared_budget"]["remaining_before_retry"], 1)

    def test_two_consumed_shared_attempts_open_external_block_without_sleep(self):
        with tempfile.TemporaryDirectory() as td:
            ep = Path(td)
            self._queue(ep, {"id": "q1", "frame": 1, "kind": "baseline_candidate", "scope": "baseline_candidate", "status": "tech_failed", "attempts": 2, "technical_failure_code": "NETWORK_ERROR", "last_error": "network"})
            state = {
                "logical_asset_key": "_external/test/frame-01",
                "attempts_consumed": 2,
                "remaining_attempts": 0,
                "active_attempt_index": None,
            }
            with patch.object(
                    image_scheduler, "_shared_generation_attempt_state",
                    return_value=state):
                result = image_scheduler.retry_tech(
                    ep, sleep_fn=lambda _seconds: self.fail("exhausted retry must not sleep"))
            queue = json.loads((ep / "meta/production-queue.json").read_text(encoding="utf-8"))
            self.assertEqual(result["requeued"], 0)
            row = queue["items"][0]
            self.assertEqual(row["status"], "external_blocked")
            self.assertEqual(
                row["external_block"]["reason"],
                "shared_generation_attempt_budget_exhausted")

    def test_reset_exhausted_cannot_reopen_shared_generation_budget(self):
        with tempfile.TemporaryDirectory() as td:
            ep = Path(td)
            self._queue(ep, {"id": "q1", "frame": 1, "kind": "baseline_candidate", "scope": "baseline_candidate", "status": "external_blocked", "attempts": 2, "technical_failure_code": "NETWORK_ERROR", "external_block": {"reason": "shared_generation_attempt_budget_exhausted"}})
            state = {
                "logical_asset_key": "_external/test/frame-01",
                "attempts_consumed": 2,
                "remaining_attempts": 0,
                "active_attempt_index": None,
            }
            with patch.object(
                    image_scheduler, "_shared_generation_attempt_state",
                    return_value=state):
                result = image_scheduler.retry_tech(
                    ep, reset_exhausted=True,
                    sleep_fn=lambda _seconds: self.fail("exhausted retry must not sleep"))
            queue = json.loads((ep / "meta/production-queue.json").read_text(encoding="utf-8"))
            row = queue["items"][0]
            self.assertEqual(result["requeued"], 0)
            self.assertEqual(row["status"], "external_blocked")
            self.assertEqual(row["attempts"], 2)
            self.assertNotIn("technical_retry_epoch_start_attempt", row)
            self.assertEqual(
                row["external_block"]["reason"],
                "shared_generation_attempt_budget_exhausted")


class VisualLockBaselineAuthorityTests(unittest.TestCase):
    def test_bind_from_queue_prefers_locked_baseline_asset_over_historical_queue_row(self):
        queue = {"items": [
            {"frame": 1, "scope": "visual_lock", "kind": "original", "status": "generated", "output_path": "old.png"},
            {"frame": 1, "scope": "baseline_candidate", "kind": "baseline_candidate", "status": "generated", "output_path": "new.png"},
            {"frame": 5, "scope": "visual_lock", "kind": "original", "status": "generated", "output_path": "05.png"},
            {"frame": 16, "scope": "visual_lock", "kind": "original", "status": "generated", "output_path": "16.png"},
            {"frame": 17, "scope": "visual_lock", "kind": "original", "status": "generated", "output_path": "17.png"},
        ]}
        gates = {"visual": {"calibration": {"items": [
            {"frame": 1, "role": "ordinary_baseline"},
            {"frame": 5, "role": "first_major_anomaly"},
            {"frame": 16, "role": "worst_capture_condition"},
            {"frame": 17, "role": "high_impact_admission"},
        ]}}}
        baseline = {"status": "LOCKED", "decision": "PASS", "asset_path": "new.png", "sha256": "newsha", "frame_contract_sha256": "fc01"}
        ledger = {"frames": {}}
        written = {}
        def fake_read(path):
            name = str(path).replace("\\", "/")
            if name.endswith("production-queue.json"): return queue
            if name.endswith("production-ledger.json"): return ledger
            if name.endswith("story-gates.json"): return gates
            if name.endswith("visual-lock-baseline-review.json"): return baseline
            return {}
        def fake_repo_file(raw): return Path(str(raw))
        def fake_sha(path): return {"new.png":"newsha","old.png":"oldsha","05.png":"sha05","16.png":"sha16","17.png":"sha17"}[str(path)]
        with tempfile.TemporaryDirectory() as td:
            ep = Path(td)
            (ep / "meta").mkdir(parents=True, exist_ok=True)
            (ep / "meta/production-queue.json").write_text("{}", encoding="utf-8")
            with patch.object(visual_lock_v21, "read_json", side_effect=fake_read), \
                    patch.object(visual_lock_v21.scheduler_core, "load_queue", return_value=queue), \
                    patch.object(visual_lock_v21, "write_json", side_effect=lambda _p,d: written.update(d)), \
                    patch.object(visual_lock_v21, "repo_file", side_effect=fake_repo_file), \
                    patch.object(visual_lock_v21, "repo_rel", side_effect=lambda p: str(p).replace("\\", "/")), \
                    patch.object(visual_lock_v21, "sha256_file", side_effect=fake_sha), \
                    patch.object(visual_lock_v21.frame_contract, "compile_frame", side_effect=lambda _ep,f,write_cache=True: {"contract_sha256": f"fc{f:02d}"}):
                visual_lock_v21.bind_from_queue(ep)
        rows = written["visual"]["calibration"]["items"]
        baseline_row = next(x for x in rows if x["role"] == "ordinary_baseline")
        self.assertEqual(baseline_row["asset_path"], "new.png")
        self.assertEqual(baseline_row["sha256"], "newsha")
        self.assertNotEqual(baseline_row["sha256"], "oldsha")


class VisionAutoRepairTests(unittest.TestCase):
    def test_authority_refresh_rebuilds_stale_character_anchor_first(self):
        with patch.object(character_appearance_anchor, "verify", return_value=["CHARACTER_APPEARANCE_ANCHOR_STALE"]), \
                patch.object(character_appearance_anchor, "build", return_value={}) as build:
            production_ledger_manage._refresh_authority_derived_caches(Path("ep"))
        build.assert_called_once_with(Path("ep"), write=True)

    def test_user_exception_can_reopen_downstream_invalidated_passed_frame(self):
        data = {"frames": {"01": {
            "status": "PASSED", "content_repairs_used": 1,
            "current_candidate": {"sha256": "old"}, "approved_asset": {"sha256": "old"},
            "reviews": [{"decision": "pass"}],
        }}}
        args = SimpleNamespace(
            episode_dir="ep", frame="01", approval_text="继续推进啊",
            reason="later four-image actual-pixel review invalidated the earlier baseline PASS",
        )
        with patch.object(production_ledger_manage, "episode_dir", return_value=Path("ep")), \
                patch.object(production_ledger_manage, "get_ledger", return_value=(Path("ledger.json"), data)), \
                patch.object(production_ledger_manage, "save_json"):
            production_ledger_manage.cmd_authorize_user_exception_repair(args)
        frame = data["frames"]["01"]
        self.assertEqual(frame["status"], "EXCEPTION_REPAIR_AUTHORIZED")
        self.assertEqual(frame["content_repairs_used"], 1)
        self.assertEqual(frame["superseded_passes"][-1]["invalidation_basis"], "later_downstream_actual_pixel_review")
        self.assertIsNone(frame["approved_asset"])
        self.assertEqual(frame["user_exception_authorizations"][-1]["approval_text"], "继续推进啊")

    def test_user_can_accept_current_candidate_after_bounded_visual_pool_exhaustion(self):
        sha = "a" * 64
        data = {"frames": {"03": {
            "status": "NEEDS_USER", "content_repairs_used": 1,
            "current_candidate": {"sha256": sha, "path": "candidate.png"},
            "attempts": [{"result": "success", "candidate": {"sha256": sha}, "request": {}}],
        }}}
        args = SimpleNamespace(
            episode_dir="ep", frame="03", approval_text="接受当前03版本，不再重做，继续生产",
            reason="user explicitly accepts the current Visual Lock candidate with known defects",
        )
        with patch.object(production_ledger_manage, "episode_dir", return_value=Path("ep")), \
                patch.object(production_ledger_manage, "get_ledger", return_value=(Path("ledger.json"), data)), \
                patch.object(production_ledger_manage, "repo_root", return_value=Path(".")), \
                patch.object(production_ledger_manage, "sha256_file", return_value=sha), \
                patch.object(Path, "is_file", return_value=True), \
                patch.object(production_ledger_manage, "verify_attempt_frame_contract_provenance"), \
                patch.object(production_ledger_manage, "verify_attempt_visual_provenance"), \
                patch.object(production_ledger_manage, "_bounded_visual_candidate_acceptance_ready", return_value=(True, ["ANOMALY_NOT_READABLE"])), \
                patch.object(production_ledger_manage, "save_json"):
            production_ledger_manage.cmd_accept_user_exception_candidate(args)
        frame = data["frames"]["03"]
        self.assertEqual(frame["status"], "PASSED")
        acceptance = frame["user_exception_acceptances"][-1]
        self.assertEqual(acceptance["approval_basis"], "direct_user_review_exception_acceptance")
        self.assertEqual(acceptance["acceptance_scope"], "bounded_visual_candidate_pool_exhausted")
        self.assertEqual(acceptance["known_automatic_issues"], ["ANOMALY_NOT_READABLE"])
        self.assertEqual(acceptance["candidate_sha256"], sha)

    def test_bounded_visual_acceptance_refuses_without_exhausted_sha_bound_fail(self):
        data = {"frames": {"03": {
            "status": "NEEDS_USER", "content_repairs_used": 1,
            "current_candidate": {"sha256": "a" * 64, "path": "candidate.png"},
            "attempts": [],
        }}}
        args = SimpleNamespace(episode_dir="ep", frame="03", approval_text="接受", reason="continue")
        with patch.object(production_ledger_manage, "episode_dir", return_value=Path("ep")), \
                patch.object(production_ledger_manage, "get_ledger", return_value=(Path("ledger.json"), data)), \
                patch.object(production_ledger_manage, "_bounded_visual_candidate_acceptance_ready", return_value=(False, [])):
            with self.assertRaisesRegex(SystemExit, "exhausted SHA-bound Visual Lock candidate pool"):
                production_ledger_manage.cmd_accept_user_exception_candidate(args)

    def test_reopened_baseline_cannot_satisfy_dependency_with_stale_review_or_pixel_master(self):
        with patch.object(visual_lock_baseline_gate, "baseline_frame", return_value=1), \
                patch.object(visual_lock_baseline_gate, "read_json", return_value={"frames": {"01": {"status": "EXCEPTION_REPAIR_AUTHORIZED"}}}), \
                patch.object(visual_lock_baseline_gate, "validate_review", return_value=[]), \
                patch.object(visual_lock_baseline_gate.character_visual_contract, "pixel_master_required", return_value=True), \
                patch.object(visual_lock_baseline_gate.character_visual_contract, "validate_pixel_master", return_value=[]):
            self.assertFalse(visual_lock_baseline_gate.approved(Path("ep")))

    def test_exhausted_auto_pixel_repair_never_uses_legacy_force_pass(self):
        with tempfile.TemporaryDirectory() as td:
            ep = Path(td)
            with patch.object(auto_repair_enqueue, "repair_pending", return_value=False), \
                    patch.object(auto_repair_enqueue, "_ledger_frame", return_value={"status": "REPAIR_READY", "content_repairs_used": 1}), \
                    patch.object(auto_repair_enqueue.ledger_call, "review", return_value=(True, "NEEDS_USER")) as review:
                result = auto_repair_enqueue.enqueue(
                    ep, frame=18, findings=["ANOMALY_SCALE_DELIVERY"], source="VISUAL_LOCK",
                    review_note="repair pixels failed actual-pixel review",
                )
        self.assertEqual(result["status"], "NEEDS_USER")
        self.assertTrue(review.call_args.kwargs["prevent_exhaustion_force_pass"])

    def test_ordinary_repair_replaces_historical_authority_refresh_queue_identity(self):
        with tempfile.TemporaryDirectory() as td:
            ep = Path(td)
            with patch.object(auto_repair_enqueue, "repair_pending", return_value=False), \
                    patch.object(auto_repair_enqueue, "_ledger_frame", return_value={"status": "REPAIR_AUTHORIZED", "content_repairs_used": 0}), \
                    patch.object(auto_repair_enqueue, "_source_item", return_value={"depends_on": []}), \
                    patch.object(auto_repair_enqueue.image_model_policy, "for_episode", return_value={"model": "gpt-image-2", "quality": "high", "strict_model": False}), \
                    patch.object(image_scheduler, "contract_references", return_value=[]), \
                    patch.object(image_scheduler, "add_item", return_value={"id": "fresh-repair", "prompt_file": "repair.txt"}) as add:
                result = auto_repair_enqueue.enqueue(
                    ep, frame=17, findings=["WARDROBE_DRIFT"], source="FINAL_SEMANTIC",
                    review_note="later semantic critic invalidated authority-refresh pixels",
                )
        self.assertEqual(result["status"], "REPAIR_ENQUEUED")
        self.assertTrue(add.call_args.kwargs["replace"])
        self.assertEqual(add.call_args.kwargs["capture_id"], "auto-repair-FINAL_SEMANTIC-17")
        self.assertIn("17-final-semantic-a2", str(add.call_args.kwargs["prompt_file"]))

    def test_exception_repair_enqueue_is_distinct_and_replaces_historical_repair(self):
        with tempfile.TemporaryDirectory() as td:
            ep = Path(td)
            with patch.object(auto_repair_enqueue, "repair_pending", return_value=False), \
                    patch.object(auto_repair_enqueue, "_ledger_frame", return_value={"status": "EXCEPTION_REPAIR_AUTHORIZED", "content_repairs_used": 1}), \
                    patch.object(auto_repair_enqueue, "_source_item", return_value={"depends_on": []}), \
                    patch.object(auto_repair_enqueue.image_model_policy, "for_episode", return_value={"model": "gpt-image-2", "quality": "high", "strict_model": False}), \
                    patch.object(image_scheduler, "contract_references", return_value=[]), \
                    patch.object(image_scheduler, "add_item", return_value={"id": "exception", "prompt_file": "exception.txt"}) as add:
                result = auto_repair_enqueue.enqueue(
                    ep, frame=16, findings=["COMMERCIAL_HDR_LOOK"], source="VISUAL_LOCK",
                    review_note="downstream actual-pixel review failed",
                )
        self.assertEqual(result["status"], "REPAIR_ENQUEUED")
        self.assertTrue(add.call_args.kwargs["replace"])
        self.assertEqual(add.call_args.kwargs["capture_id"], "user-exception-VISUAL_LOCK-16")
        self.assertIn("user-exception-a3", str(add.call_args.kwargs["prompt_file"]))

    def test_authority_refresh_reopens_needs_user_after_contract_drift(self):
        data = {"frames": {"05": {"status": "NEEDS_USER", "content_repairs_used": 1, "reviews": [{"decision": "repair"}]}}}
        args = SimpleNamespace(
            episode_dir="ep", frame="05", approval_text="continue full-auto after profile contract correction",
            reason="visual profile authority drift M02 -> M04",
        )
        with patch.object(production_ledger_manage, "episode_dir", return_value=Path("ep")), \
                patch.object(production_ledger_manage, "get_ledger", return_value=(Path("ledger.json"), data)), \
                patch.object(production_ledger_manage, "current_frame_contract_provenance", return_value={"contract_sha256": "new-contract"}), \
                patch.object(production_ledger_manage, "save_json"):
            production_ledger_manage.cmd_authorize_authority_refresh(args)
        frame = data["frames"]["05"]
        self.assertEqual(frame["status"], "AUTHORITY_REFRESH_AUTHORIZED")
        self.assertEqual(frame["content_repairs_used"], 1)
        self.assertEqual(frame["authority_refresh_history"][-1]["previous_status"], "NEEDS_USER")
        self.assertEqual(frame["authority_refresh_authorization"]["frame_contract_sha256"], "new-contract")

    def test_authority_refresh_supersedes_historical_generated_repair(self):
        with tempfile.TemporaryDirectory() as td:
            ep = Path(td)
            with patch.object(auto_repair_enqueue, "repair_pending", return_value=False), \
                    patch.object(auto_repair_enqueue, "_ledger_frame", return_value={"status": "AUTHORITY_REFRESH_AUTHORIZED", "content_repairs_used": 1, "authority_refresh_authorization": {"frame_contract_sha256": "new-contract"}}), \
                    patch.object(auto_repair_enqueue, "_source_item", return_value={"depends_on": [1]}), \
                    patch.object(auto_repair_enqueue.image_model_policy, "for_episode", return_value={"model": "gpt-image-2", "quality": "high", "strict_model": False}), \
                    patch.object(visual_lock_baseline_gate, "baseline_frame", return_value=1), \
                    patch.object(image_scheduler, "contract_references", return_value=[{"path": "master.png", "role": "character_pixel_master", "kind": "identity"}]), \
                    patch.object(image_scheduler, "add_item", return_value={"id": "fresh", "prompt_file": "authority.txt"}) as add:
                result = auto_repair_enqueue.enqueue_authority_refresh(ep, 5)
        self.assertEqual(result["status"], "AUTHORITY_REFRESH_ENQUEUED")
        self.assertTrue(add.call_args.kwargs["replace"])
        self.assertEqual(add.call_args.kwargs["kind"], "repair")
        self.assertEqual(add.call_args.kwargs["capture_id"], "authority-refresh-05")
        self.assertIn("new-contract", auto_repair_enqueue.authority_refresh_prompt(5, "new-contract"))
        self.assertNotEqual(
            auto_repair_enqueue.authority_refresh_prompt(5, "new-contract"),
            auto_repair_enqueue.authority_refresh_prompt(5, "newer-contract"),
        )

    def test_visual_lock_exception_provenance_binds_only_current_exception_sha(self):
        with tempfile.TemporaryDirectory() as td:
            ep = Path(td)
            (ep / "meta").mkdir(parents=True)
            (ep / "meta/production-ledger.json").write_text(json.dumps({"frames": {"17": {
                "status": "REPAIR_READY",
                "user_exception_repairs_used": 1,
                "current_candidate": {"sha256": "fresh", "attempt_id": "a3"},
                "attempts": [
                    {"attempt_id": "old", "result": "success", "request": {"capture_id": "user-exception-VISUAL_LOCK-17"}},
                    {"attempt_id": "a3", "result": "success", "request": {"capture_id": "user-exception-VISUAL_LOCK-17"}},
                ],
            }}}), encoding="utf-8")
            self.assertEqual(
                visual_lock_v21._direct_user_exception_frames(ep, [{"frame": 17, "sha256": "fresh"}]),
                [17],
            )
            self.assertEqual(
                visual_lock_v21._direct_user_exception_frames(ep, [{"frame": 17, "sha256": "stale"}]),
                [],
            )

    def test_baseline_pass_promotes_approved_asset_immediately(self):
        ready = {"frames": {"01": {"status": "ORIGINAL_READY", "approved_asset": None}}}
        passed = {"frames": {"01": {"status": "PASSED", "approved_asset": None}}}
        completed = type("Completed", (), {"returncode": 0, "stdout": ""})()
        with tempfile.TemporaryDirectory() as td:
            ep = Path(td)
            (ep / "meta").mkdir(parents=True, exist_ok=True)
            (ep / "meta/production-ledger.json").write_text("{}", encoding="utf-8")
            with patch.object(visual_lock_baseline_gate.production_ledger, "authority_exists", return_value=True), \
                    patch.object(visual_lock_baseline_gate.production_ledger, "load_authority", side_effect=[ready, passed]), \
                    patch.object(visual_lock_baseline_gate.subprocess, "run", return_value=completed) as run:
                visual_lock_baseline_gate._ledger_pass(ep, 1)
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(len(commands), 2)
        self.assertIn("review", commands[0])
        self.assertIn("promote", commands[1])

    def test_baseline_content_fail_enqueues_repair_and_keeps_loop_progressing(self):
        review = {"checks": {"reality_first": "FAIL", "identity_usable": "PASS"}, "note": "too cinematic"}
        repair = {"status": "REPAIR_ENQUEUED", "frame": 1, "queue_item_id": "repair1"}
        with tempfile.TemporaryDirectory() as td, \
                patch.object(vision_review_executor, "_require_capability", return_value=None), \
                patch.object(vision_review_executor.visual_lock_baseline_gate, "approved", return_value=False), \
                patch.object(vision_review_executor.visual_lock_baseline_gate, "baseline_frame", return_value=1), \
                patch.object(vision_review_executor.visual_lock_baseline_gate, "run_codex_critic", return_value={"status": "FAIL"}), \
                patch.object(vision_review_executor.visual_lock_baseline_gate, "read_json", return_value=review), \
                patch.object(vision_review_executor.baseline_candidate_pool, "review_attempt", return_value=1), \
                patch.object(vision_review_executor.auto_repair_enqueue, "enqueue", return_value=repair) as enqueue:
            result = vision_review_executor.execute(Path(td), {"action": "REVIEW_ORDINARY_BASELINE", "executor": "CODEX_VISION"})
        self.assertEqual(result["status"], "REPAIR_ENQUEUED")
        enqueue.assert_called_once()
        self.assertIn("reality_first", enqueue.call_args.kwargs["findings"])

    def test_visual_lock_resume_reuses_persisted_fail_without_duplicate_critic(self):
        persisted = [{
            "id": "V-H", "frame": 18,
            "checks": {"not_cinematic": False},
            "issues": ["CINEMATIC_CONCEPT_ART"],
        }]
        repair = {"status": "NEEDS_USER", "frame": 18}
        with tempfile.TemporaryDirectory() as td, \
                patch.object(vision_review_executor, "_require_capability", return_value=None), \
                patch.object(vision_review_executor.visual_lock_v21, "bind_from_queue", return_value=None), \
                patch.object(vision_review_executor.visual_lock_v21, "verify", return_value=["dirty"]), \
                patch.object(vision_review_executor.visual_lock_v21, "run_critic", side_effect=AssertionError("must not duplicate Vision review")), \
                patch.object(vision_review_executor.auto_repair_enqueue, "review_attempt", return_value=3), \
                patch.object(vision_review_executor.visual_lock_candidate_pool, "review_attempt", return_value=3), \
                patch.object(vision_review_executor, "_persisted_current_visual_lock_fail_rows", return_value=persisted), \
                patch.object(vision_review_executor.auto_repair_enqueue, "enqueue", return_value=repair) as enqueue:
            result = vision_review_executor.execute(
                Path(td),
                {"action": "REVIEW_VISUAL_LOCK", "executor": "CODEX_VISION", "frames": [18]},
            )
        self.assertEqual(result["status"], "NEEDS_USER")
        enqueue.assert_called_once()

    def test_visual_lock_candidate_fail_reopens_passed_ledger_for_next_bounded_candidate(self):
        persisted = [{
            "id": "V-A", "frame": 3,
            "checks": {"anomaly_scale_delivery": False},
            "issues": ["ANOMALY_NOT_READABLE"],
        }]
        with tempfile.TemporaryDirectory() as td, \
                patch.object(vision_review_executor, "_require_capability", return_value=None), \
                patch.object(vision_review_executor.visual_lock_v21, "bind_from_queue", return_value=None), \
                patch.object(vision_review_executor.visual_lock_v21, "verify", return_value=["dirty"]), \
                patch.object(vision_review_executor.visual_lock_v21, "run_critic", side_effect=AssertionError("must reuse persisted result")), \
                patch.object(vision_review_executor.visual_lock_v21, "calibration_assets", return_value=[{"id": "V-A", "frame": 3, "sha256": "sha", "frame_contract_sha256": "fc"}]), \
                patch.object(vision_review_executor.auto_repair_enqueue, "review_attempt", return_value=3), \
                patch.object(vision_review_executor.visual_lock_candidate_pool, "review_attempt", return_value=3), \
                patch.object(vision_review_executor, "_persisted_current_visual_lock_fail_rows", return_value=persisted), \
                patch.object(vision_review_executor.auto_repair_enqueue, "enqueue", return_value={"status": "NOT_REPAIRABLE", "frame": 3, "ledger_status": "PASSED"}), \
                patch.object(vision_review_executor.visual_lock_admission_state, "restore_ledger_fail", return_value=True) as reconcile:
            result = vision_review_executor.execute(
                Path(td),
                {"action": "REVIEW_VISUAL_LOCK", "executor": "CODEX_VISION", "frames": [3]},
            )
        self.assertEqual(result["status"], "NEEDS_USER")
        self.assertTrue(result["repairs"][0]["reconciled_from_visual_lock_fail"])
        reconcile.assert_called_once()

    def test_visual_lock_post_result_transport_failure_uses_current_sha_bound_fail(self):
        persisted = [{
            "id": "V-A", "frame": 3,
            "checks": {"anomaly_scale_delivery": False},
            "issues": ["ANOMALY_NOT_READABLE"],
        }]
        repair = {"status": "NEEDS_USER", "frame": 3}
        with tempfile.TemporaryDirectory() as td, \
                patch.object(vision_review_executor, "_require_capability", return_value=None), \
                patch.object(vision_review_executor.visual_lock_v21, "bind_from_queue", return_value=None), \
                patch.object(vision_review_executor.visual_lock_v21, "verify", return_value=["dirty"]), \
                patch.object(vision_review_executor.visual_lock_v21, "run_critic", return_value=11), \
                patch.object(vision_review_executor.auto_repair_enqueue, "review_attempt", return_value=3), \
                patch.object(vision_review_executor.visual_lock_candidate_pool, "review_attempt", return_value=3), \
                patch.object(vision_review_executor, "_persisted_current_visual_lock_fail_rows", return_value=persisted), \
                patch.object(vision_review_executor.auto_repair_enqueue, "enqueue", return_value=repair) as enqueue:
            result = vision_review_executor.execute(
                Path(td),
                {"action": "REVIEW_VISUAL_LOCK", "executor": "CODEX_VISION", "frames": [3]},
            )
        self.assertEqual(result["status"], "NEEDS_USER")
        self.assertEqual(result["returncode"], 2)
        enqueue.assert_called_once()
        self.assertIn("ANOMALY_NOT_READABLE", enqueue.call_args.kwargs["findings"])

    def test_visual_lock_transport_failure_without_bound_result_stays_technical(self):
        with tempfile.TemporaryDirectory() as td, \
                patch.object(vision_review_executor, "_require_capability", return_value=None), \
                patch.object(vision_review_executor.visual_lock_v21, "bind_from_queue", return_value=None), \
                patch.object(vision_review_executor.visual_lock_v21, "verify", return_value=["dirty"]), \
                patch.object(vision_review_executor.visual_lock_v21, "run_critic", return_value=11), \
                patch.object(vision_review_executor.auto_repair_enqueue, "review_attempt", return_value=3), \
                patch.object(vision_review_executor.visual_lock_candidate_pool, "review_attempt", return_value=3), \
                patch.object(vision_review_executor, "_persisted_current_visual_lock_fail_rows", return_value=[]), \
                patch.object(vision_review_executor.auto_repair_enqueue, "enqueue") as enqueue:
            result = vision_review_executor.execute(
                Path(td),
                {"action": "REVIEW_VISUAL_LOCK", "executor": "CODEX_VISION", "frames": [3]},
            )
        self.assertEqual(result["status"], "TECHNICAL_FAILURE")
        enqueue.assert_not_called()

    def test_visual_lock_human_present_requires_identity_even_without_name_token(self):
        with tempfile.TemporaryDirectory() as td:
            ep = Path(td)
            (ep / "meta").mkdir(parents=True)
            (ep / "meta/character-visual-contract.json").write_text(
                json.dumps({"members": {"P01": {}, "P02": {}, "P03": {}, "P04": {}}}), encoding="utf-8"
            )
            hm = {"shot_progression": {"primary_subject": "四人走在石木云桥上", "human_present": True}}
            needed, character_id, reason = reference_arbitrator._identity_need(ep, hm, [], scope="repair")
        self.assertTrue(needed)
        self.assertIsNone(character_id)
        self.assertEqual(reason, "visual_lock_human_present")

    def test_visual_lock_named_hand_fragment_keeps_named_character_identity(self):
        with tempfile.TemporaryDirectory() as td:
            ep = Path(td)
            (ep / "meta").mkdir(parents=True)
            (ep / "meta/character-visual-contract.json").write_text(
                json.dumps({"members": {"P01": {}, "P02": {}}}), encoding="utf-8"
            )
            hm = {"shot_progression": {"primary_subject": "P01手突然离开镜头边缘", "human_present": True}}
            needed, character_id, reason = reference_arbitrator._identity_need(ep, hm, [], scope="visual_lock")
        self.assertTrue(needed)
        self.assertEqual(character_id, "P01")
        self.assertEqual(reason, "visual_lock_non_face_character_fragment")

    def test_frame_contract_identity_intent_exists_before_pixel_master(self):
        with tempfile.TemporaryDirectory() as td:
            ep = Path(td)
            (ep / "meta").mkdir(parents=True)
            (ep / "meta/story-gates.json").write_text(
                json.dumps({"visual": {"references": {"required": False, "items": []}}}), encoding="utf-8"
            )
            reqs = identity_continuity.contract_requirements(
                ep, 17, [], {"human_present": True, "primary_subject": "P01手臂", "action": "P01伸向P02"})
        self.assertEqual([row["character_id"] for row in reqs], ["P01", "P02"])
        self.assertTrue(all(row["anchor_state"] == "pending_pixel_master" for row in reqs))
        self.assertTrue(all(row["requirement_source"] == "shot_progression" for row in reqs))

    def test_repair_scope_baseline_dependency_uses_current_baseline_approval(self):
        q = {"items": [{"frame": 1, "status": "generated"}]}
        with patch.object(image_scheduler.visual_lock_baseline_gate, "is_baseline_dependency", return_value=True), \
                patch.object(image_scheduler.visual_lock_baseline_gate, "approved", return_value=False), \
                patch.object(image_scheduler, "ledger_state", return_value="PASSED"):
            self.assertFalse(image_scheduler.dependency_satisfied(Path("ep"), q, 1, scope="repair"))

    def test_repair_scope_dependent_keeps_new_baseline_review_routable(self):
        with tempfile.TemporaryDirectory() as td:
            ep = Path(td)
            (ep / "meta").mkdir(parents=True)
            (ep / "meta/visual-lock-baseline-review.json").write_text(json.dumps({"decision": "PASS", "sha256": "old"}), encoding="utf-8")
            q = {"items": [{"frame": 5, "scope": "repair", "status": "queued", "depends_on": [1]}]}
            with patch.object(visual_lock_baseline_gate, "baseline_frame", return_value=1), \
                    patch.object(visual_lock_baseline_gate, "approved", return_value=False), \
                    patch.object(visual_lock_baseline_gate, "generated_baseline", return_value={"asset_path": "new.png", "sha256": "new"}):
                self.assertTrue(visual_lock_baseline_gate.awaiting_review(ep, q))

    def test_baseline_review_defers_while_repair_is_pending(self):
        q = {"items": [
            {"frame": 1, "kind": "original", "scope": "visual_lock", "status": "generated"},
            {"frame": 5, "kind": "original", "scope": "visual_lock", "status": "queued", "depends_on": [1]},
            {"frame": 1, "kind": "repair", "scope": "repair", "status": "queued"},
        ]}
        with patch.object(visual_lock_baseline_gate, "approved", return_value=False), \
                patch.object(visual_lock_baseline_gate, "baseline_frame", return_value=1):
            self.assertFalse(visual_lock_baseline_gate.awaiting_review(Path("ep"), q))

    def test_review_attempt_becomes_two_after_repair_budget_is_consumed(self):
        with patch.object(auto_repair_enqueue, "_ledger_frame", return_value={"content_repairs_used": 1}):
            self.assertEqual(auto_repair_enqueue.review_attempt(Path("ep"), 1), 2)


class BaselineCandidatePoolTests(unittest.TestCase):
    def _episode(self, td: str, *, status: str = "NEEDS_USER") -> Path:
        ep = Path(td)
        (ep / "meta").mkdir(parents=True, exist_ok=True)
        (ep / "meta/visual-lock-plan.json").write_text(json.dumps({"items": [
            {"role": "ordinary_baseline", "frame": 1},
            {"role": "worst_capture_condition", "frame": 5, "depends_on": [1]},
            {"role": "first_major_visual_contrast", "frame": 16, "depends_on": [1]},
            {"role": "high_impact_admission", "frame": 17, "depends_on": [1]},
        ]}), encoding="utf-8")
        (ep / "meta/production-ledger.json").write_text(json.dumps({"frames": {"01": {
            "status": status, "content_repairs_used": 1, "attempts": [
                {"kind": "original", "result": "success", "candidate": {"sha256": "old"}},
                {"kind": "repair", "result": "success", "candidate": {"sha256": "repair"}},
            ]
        }}}), encoding="utf-8")
        (ep / "meta/production-queue.json").write_text(json.dumps({"items": []}), encoding="utf-8")
        (ep / "meta/visual-lock-baseline-review.json").write_text(json.dumps({
            "decision": "FAIL", "sha256": "repair",
            "checks": {"reality_first": "FAIL", "identity_usable": "PASS"},
            "note": "too cinematic",
        }), encoding="utf-8")
        return ep

    def test_baseline_candidate_uses_exception_raw_budget_bucket(self):
        self.assertEqual(raw_candidate_budget.kind_for_queue_item({"kind": "baseline_candidate"}), "exception")
        self.assertEqual(raw_candidate_budget.kind_for_queue_item({"kind": "repair"}), "repair")
        self.assertEqual(raw_candidate_budget.kind_for_queue_item({"kind": "repair", "capture_id": "user-exception-VISUAL_LOCK-01"}), "user_exception")
        self.assertEqual(raw_candidate_budget.limits()["user_exception"], 1)

    def test_baseline_candidate_begin_preserves_one_shot_content_repair_budget(self):
        with tempfile.TemporaryDirectory() as td:
            ep = Path(td)
            (ep / "meta").mkdir(parents=True)
            (ep / "meta/release-manifest.json").write_text(
                json.dumps({"episode": {"aspect_ratio": "4:5"}, "release": {"body_frame_count": 1}}),
                encoding="utf-8",
            )
            production_ledger.init_ledger(ep, count=1)
            ledger_path = ep / "meta/production-ledger.json"
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            ledger["frames"]["01"]["status"] = "NEEDS_USER"
            ledger["frames"]["01"]["content_repairs_used"] = 1
            ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
            prompt = ep / "candidate.txt"
            prompt.write_text("ordinary baseline phone snapshot", encoding="utf-8")
            ok, msg = ledger_call.begin(
                ep, frame=1, kind="baseline_candidate", prompt_file=prompt,
                capture_id="baseline-candidate-1", model="gpt-image-2", quality="high",
                notes="bounded baseline candidate pool",
            )
            self.assertTrue(ok, msg)
            current = json.loads(ledger_path.read_text(encoding="utf-8"))["frames"]["01"]
            self.assertEqual(current["status"], "REPAIRING")
            self.assertEqual(current["content_repairs_used"], 1)
            self.assertEqual(current["attempts"][-1]["kind"], "baseline_candidate")

    def test_review_attempt_counts_real_successful_candidates_not_technical_retries(self):
        with tempfile.TemporaryDirectory() as td:
            ep = self._episode(td)
            self.assertEqual(baseline_candidate_pool.review_attempt(ep), 2)
            ledger = json.loads((ep / "meta/production-ledger.json").read_text(encoding="utf-8"))
            ledger["frames"]["01"]["attempts"].insert(1, {"kind": "repair", "result": "technical_failure"})
            (ep / "meta/production-ledger.json").write_text(json.dumps(ledger), encoding="utf-8")
            self.assertEqual(baseline_candidate_pool.review_attempt(ep), 2)

    def test_pool_uses_two_content_slots_and_ignores_technical_only_item(self):
        with tempfile.TemporaryDirectory() as td:
            ep = self._episode(td)
            q = {"items": [
                {"frame": 1, "kind": "baseline_candidate", "scope": "baseline_candidate", "status": "tech_failed", "output_path": None},
                {"frame": 1, "kind": "baseline_candidate", "scope": "baseline_candidate", "status": "superseded", "output_path": "candidate-1.png"},
            ]}
            (ep / "meta/production-queue.json").write_text(json.dumps(q), encoding="utf-8")
            self.assertEqual(baseline_candidate_pool.successful_candidate_slots(ep), 1)

    def test_same_failed_sha_is_not_reviewed_again(self):
        q = {"items": [
            {"frame": 1, "kind": "repair", "scope": "repair", "status": "generated", "output_path": "x.png"},
            {"frame": 5, "kind": "original", "scope": "visual_lock", "status": "queued", "depends_on": [1]},
        ]}
        with tempfile.TemporaryDirectory() as td:
            ep = Path(td)
            (ep / "meta").mkdir(parents=True)
            (ep / "meta/visual-lock-baseline-review.json").write_text(
                json.dumps({"decision": "FAIL", "sha256": "same"}), encoding="utf-8")
            with patch.object(visual_lock_baseline_gate, "approved", return_value=False), \
                    patch.object(visual_lock_baseline_gate, "baseline_frame", return_value=1), \
                    patch.object(visual_lock_baseline_gate, "generated_baseline", return_value={"asset_path": "x.png", "sha256": "same"}):
                self.assertFalse(visual_lock_baseline_gate.awaiting_review(ep, q))

    def test_enqueue_next_is_baseline_candidate_not_ordinary_repair(self):
        with tempfile.TemporaryDirectory() as td:
            ep = self._episode(td)
            fake = {"id": "pool-c1", "prompt_file": "prompt.txt"}
            with patch.object(baseline_candidate_pool, "enabled", return_value=True), \
                    patch.object(baseline_candidate_pool, "max_additional_candidates", return_value=2), \
                    patch("image_scheduler.contract_references", return_value=[]), \
                    patch("image_scheduler.add_item", return_value=fake) as add:
                result = baseline_candidate_pool.enqueue_next(ep)
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["slot"], 1)
            self.assertEqual(result["content_repairs_used"], 1)
            self.assertEqual(add.call_args.kwargs["kind"], "baseline_candidate")
            self.assertEqual(add.call_args.kwargs["scope"], "baseline_candidate")
            self.assertTrue((ep / "prompts/baseline-candidates/01-candidate-1.txt").is_file())


class NextActionAutonomousBatchTests(unittest.TestCase):
    def _derive(self, *, state, queue, ledger, visual_errors=None, expected=20, reviews=None, handoff_valid=True):
        episode = Path("ep")
        def fake_read(path):
            name = str(path).replace("\\", "/")
            if name.endswith("meta/production-queue.json"):
                return queue
            if name.endswith("meta/production-ledger.json"):
                return {"frames": ledger}
            if name.endswith("meta/story-gates.json"):
                return {"reviews": reviews or {}}
            return {}
        with patch.object(next_action.runtime_portability, "assert_episode_directory", return_value=None), \
                patch.object(next_action, "read_json", side_effect=fake_read), \
                patch.object(next_action, "state", return_value=state), \
                patch.object(next_action.runtime_router, "detect", return_value=("WORK", "test")), \
                patch.object(next_action.runtime_router, "image_execution_runtime", return_value=("CODEX", "test")), \
                patch.object(next_action.runtime_router, "vision_review_runtime", return_value=("CODEX", "test")), \
                patch.object(next_action.runtime_execution, "effective_mode", return_value="full_auto"), \
                patch.object(next_action.scheduler_core, "load_queue", return_value=queue), \
                patch.object(next_action.production_ledger, "load_authority", return_value={"frames": ledger}), \
                patch.object(next_action, "pending_product_review", return_value=None), \
                patch.object(next_action.product_runtime_adapter, "reconcile", return_value=None), \
                patch.object(next_action, "_handoff_valid", return_value=handoff_valid), \
                patch.object(scheduler_core, "progress", return_value={}), \
                patch.object(next_action.visual_lock_baseline_gate, "awaiting_review", return_value=False), \
                patch.object(next_action, "_expected_frames", return_value=expected), \
                patch.object(next_action.production_batch_review, "pending", return_value=[]), \
                patch.object(next_action.visual_lock_v21, "verify", return_value=visual_errors or []):
            return next_action.derive(episode)

    def test_verified_first_batch_succeeded_unblocks_history_via_machine_action(self):
        import production_native_batch_followon as followon
        originals = [{"id": f"vl-{n}", "frame": n, "scope": "visual_lock",
                      "kind": "original", "status": "generated"} for n in (1,3,8,18)]
        batch = [{"id": f"batch-{n}", "frame": n, "scope": "batch",
                  "kind": "original", "model": "gpt-image-2.5-flare",
                  "status": "blocked",
                  "technical_failure_code": followon.FAILURE}
                 for n in range(1,21) if n not in (1,3,8,18)]
        first=next(row for row in batch if row["frame"]==2)
        first["status"]="generated"
        first.pop("technical_failure_code")
        q={"items": [*originals,*batch]}
        with patch.object(followon,"admissible",return_value=True) as gate:
            result=self._derive(state="VISUAL_CALIBRATED",queue=q,ledger={},expected=20)
        self.assertEqual((result["action"], result["executor"]),
                         ("RESUME_NATIVE_BATCH_AFTER_SUCCESS","MACHINE"))
        self.assertTrue(result["auto_recoverable"])
        self.assertFalse(result["hard_stop"])
        gate.assert_called_once()
        self.assertEqual(sum(row["status"]=="blocked" for row in batch),15)
        with patch.object(followon,"admissible",return_value=False):
            blocked=self._derive(state="VISUAL_CALIBRATED",queue=q,ledger={},expected=20)
        self.assertEqual(blocked["action"],"IMAGE_ATTEMPT_BLOCKED")
        self.assertTrue(blocked["hard_stop"])

    def test_native_frame02_proof_preempts_other_capability_blocks_only_when_valid(self):
        import production_native_batch_reentry as native_proof
        import model_policy
        originals = [{"id": f"vl-{n}", "frame": n, "scope": "visual_lock",
                      "kind": "original", "status": "generated"} for n in (1, 3, 8, 18)]
        batch = [{"id": f"batch-{n}", "frame": n, "scope": "batch",
                  "kind": "original", "model": "gpt-image-2.5-flare",
                  "status": "blocked",
                  "technical_failure_code": native_proof.FAILURE}
                 for n in range(1, 21) if n not in (1, 3, 8, 18)]
        first = next(row for row in batch if row["frame"] == 2)
        first["status"] = "queued"
        first.pop("technical_failure_code")
        first[native_proof.FLAG] = True
        q = {"items": [*originals, *batch]}
        with patch.object(image_scheduler, "ready_items", return_value=([first], [])), \
                patch.object(native_proof, "eligible", return_value=True) as valid, \
                patch.object(model_policy, "resolve", return_value={}):
            action = self._derive(state="VISUAL_CALIBRATED", queue=q,
                                  ledger={}, expected=20)
        self.assertEqual((action["action"], action["executor"]),
                         ("GENERATE_IMAGES", "CODEX_IMAGE"))
        self.assertEqual(action["frames"], [2])
        self.assertFalse(action["hard_stop"])
        valid.assert_called_once()
        self.assertEqual(sum(row["status"] == "blocked" for row in batch), 15)

        # Even when a spoofed flag is present, official Attempt/pixel
        # authority failure must preserve the existing hard stop.
        with patch.object(image_scheduler, "ready_items", return_value=([first], [])), \
                patch.object(native_proof, "eligible", return_value=False), \
                patch.object(model_policy, "resolve", return_value={}):
            blocked = self._derive(state="VISUAL_CALIBRATED", queue=q,
                                   ledger={}, expected=20)
        self.assertEqual(blocked["action"], "IMAGE_ATTEMPT_BLOCKED")
        self.assertTrue(blocked["hard_stop"])

    def test_preserved_native_raw_precedes_unknown_backend_block_without_retry(self):
        import image_unknown_raw_reconcile as recovered
        originals=[{"id":f"vl-{n}","frame":n,"scope":"visual_lock",
                    "kind":"original","status":"generated"} for n in (1,3,8,18)]
        batch=[{"id":f"batch-{n}","frame":n,"scope":"batch","kind":"original",
                "status":"generated"} for n in (2,4,6,7,9,13,14,17,19,20)]
        external=[{"id":f"batch-{n}","frame":n,"scope":"batch","kind":"original",
                   "status":"external_blocked","technical_failure_code":(
                       "ASPECT_RATIO_MISMATCH" if n in (11,12,16)
                       else "IMAGE_BACKEND_ERROR")} for n in (5,10,11,12,15,16)]
        queue={"items":[*originals,*batch,*external]}
        with patch.object(recovered,"eligible",
                          side_effect=lambda ep,item: {"verified":True} if item["frame"] in (11,12,16) else None):
            action=self._derive(state="VISUAL_CALIBRATED",queue=queue,
                                ledger={},expected=20)
        self.assertEqual((action["action"],action["executor"]),
                         ("RECONCILE_PRESERVED_PROVIDER_RAW","MACHINE"))
        self.assertEqual(action["frames"],[11,12,16])
        self.assertFalse(action["hard_stop"])
        self.assertTrue(action["auto_recoverable"])
        with patch.object(recovered,"eligible",return_value=None):
            blocked=self._derive(state="VISUAL_CALIBRATED",
                                 queue=queue,ledger={},expected=20)
        self.assertEqual(blocked["action"],"EXTERNAL_IMAGE_PROVIDER_BLOCKED")
        self.assertTrue(blocked["hard_stop"])
        self.assertEqual(sorted(blocked["frames"]),[5,10,11,12,15,16])

    def test_needs_user_baseline_routes_to_bounded_candidate_pool_before_human_stop(self):
        queue = {"items": []}
        ledger = {"01": {"status": "NEEDS_USER"}}
        with patch.object(next_action.visual_lock_baseline_gate, "baseline_frame", return_value=1), \
                patch.object(next_action.baseline_candidate_pool, "can_prepare", return_value=True), \
                patch.object(next_action.baseline_candidate_pool, "successful_candidate_slots", return_value=0), \
                patch.object(next_action.baseline_candidate_pool, "max_additional_candidates", return_value=2):
            action = self._derive(state="STORYBOARD_LOCKED", queue=queue, ledger=ledger)
        self.assertEqual((action["action"], action["executor"]), ("PREPARE_BASELINE_CANDIDATE", "MACHINE"))
        self.assertFalse(action["hard_stop"])
        self.assertTrue(action["auto_recoverable"])

    def test_soft_visual_failure_over_three_routes_to_weak_pass_before_pool_or_human_stop(self):
        frames = [1, 3, 8, 16]
        queue = {"items": [
            {"frame": n, "kind": "original", "scope": "visual_lock", "status": "generated"}
            for n in frames
        ]}
        ledger = {f"{n:02d}": {"status": "PASSED"} for n in frames}
        ledger["03"] = {"status": "NEEDS_USER", "current_candidate": {"sha256": "c" * 64}}
        with patch.object(next_action.visual_lock_candidate_pool, "weak_pass_eligible_frames", return_value=[3]), \
                patch.object(next_action.visual_lock_candidate_pool, "prepareable_frames", return_value=[]), \
                patch.object(next_action.visual_lock_candidate_pool, "exhausted_frames", return_value=[3]):
            action = self._derive(state="STORYBOARD_LOCKED", queue=queue, ledger=ledger, visual_errors=["soft visual failure"])
        self.assertEqual((action["action"], action["executor"]), ("APPLY_VISUAL_LOCK_WEAK_PASS", "MACHINE"))
        self.assertEqual(action["frames"], [3])
        self.assertTrue(action["auto_recoverable"])
        self.assertFalse(action["hard_stop"])

    def test_needs_user_frame_does_not_preempt_runnable_sibling_generation(self):
        queue = {"items": [
            {"id": "old01", "frame": 1, "kind": "original", "scope": "batch", "status": "generated"},
            {"id": "q02", "frame": 2, "kind": "original", "scope": "batch", "status": "queued"},
        ]}
        ledger = {"01": {"status": "NEEDS_USER"}, "02": {"status": "PENDING"}}
        with patch.object(image_scheduler, "ready_items", return_value=([{"frame": 2}], [])):
            action = self._derive(state="VISUAL_CALIBRATED", queue=queue, ledger=ledger, expected=2)
        self.assertEqual((action["action"], action["executor"]), ("GENERATE_IMAGES", "CODEX_IMAGE"))
        self.assertEqual(action["frames"], [2])
        self.assertFalse(action["hard_stop"])
        self.assertTrue(action["auto_recoverable"])

    def test_needs_user_frame_does_not_preempt_sibling_batch_review(self):
        queue = {"items": [
            {"id": "old01", "frame": 1, "kind": "original", "scope": "batch", "status": "generated"},
            {"id": "b02", "frame": 2, "kind": "original", "scope": "batch", "status": "review_pending", "batch_id": "batch-02"},
        ]}
        ledger = {"01": {"status": "NEEDS_USER"}, "02": {"status": "ORIGINAL_READY"}}
        with patch.object(image_scheduler, "ready_items", return_value=([], [])):
            action = self._derive(state="VISUAL_CALIBRATED", queue=queue, ledger=ledger, expected=2)
        self.assertEqual((action["action"], action["executor"]), ("REVIEW_GENERATED_IMAGES", "CODEX_VISION"))
        self.assertEqual(action["batch_ids"], ["batch-02"])
        self.assertFalse(action["hard_stop"])
        self.assertTrue(action["auto_recoverable"])

    def test_needs_user_hard_stops_only_after_machine_sibling_work_is_exhausted(self):
        queue = {"items": [
            {"id": "old01", "frame": 1, "kind": "original", "scope": "batch", "status": "generated"},
            {"id": "old02", "frame": 2, "kind": "original", "scope": "batch", "status": "generated"},
        ]}
        ledger = {"01": {"status": "NEEDS_USER"}, "02": {"status": "LOCKED"}}
        with patch.object(next_action.visual_lock_baseline_gate, "baseline_frame", return_value=None), \
                patch.object(image_scheduler, "ready_items", return_value=([], [])):
            action = self._derive(state="VISUAL_CALIBRATED", queue=queue, ledger=ledger, expected=2)
        self.assertEqual(action["action"], "USER_DECISION_REQUIRED")
        self.assertEqual(action["frames"], [1])
        self.assertTrue(action["hard_stop"])
        self.assertFalse(action["auto_recoverable"])

    def test_stale_preimage_boundary_blocks_authority_refresh_generation(self):
        frames = [1, 5, 16, 17]
        queue = {"items": [{"frame": n, "kind": "original", "scope": "visual_lock", "status": "generated"} for n in frames]}
        ledger = {f"{n:02d}": {"status": "AUTHORITY_REFRESH_AUTHORIZED", "content_repairs_used": 1} for n in frames}
        with patch.object(next_action.product_runtime_adapter, "next_host_step", return_value=("PREIMAGE_TASK_SET", None)):
            action = self._derive(state="STORYBOARD_LOCKED", queue=queue, ledger=ledger, visual_errors=["stale"], handoff_valid=False)
        self.assertEqual((action["action"], action["executor"]), ("PREIMAGE_COMPILE", "WORK"))
        self.assertEqual(action["preimage_step"], "PREIMAGE_TASK_SET")

    def test_unresolved_aspect_ratio_block_routes_to_normalization_before_visual_review(self):
        frames = [1, 5, 16, 17]
        queue = {"items": [
            *[{"frame": n, "kind": "original", "scope": "visual_lock", "status": "generated", "completed_at": "2026-09-14T10:00:00+08:00"} for n in frames],
            {"id": "r17", "frame": 17, "kind": "repair", "scope": "repair", "status": "blocked",
             "technical_failure_code": "ASPECT_RATIO_MISMATCH", "completed_at": "2026-09-14T11:00:00+08:00"},
        ]}
        ledger = {f"{n:02d}": {"status": "ORIGINAL_READY"} for n in frames}
        ledger["17"] = {"status": "TECH_FAILED", "current_candidate": {"sha256": "old", "recorded_at": "2026-09-14T10:00:00+08:00"}}
        with patch.object(next_action.image_blocked_recovery, "inspect", return_value=[{
            "frame": 17, "item_id": "r17", "code": "ASPECT_RATIO_MISMATCH",
            "auto_resolvable": True, "reason": "provider_ratio_exception_is_deterministically_recoverable",
        }]):
            action = self._derive(state="STORYBOARD_LOCKED", queue=queue, ledger=ledger, visual_errors=["stale"])
        self.assertEqual((action["action"], action["executor"]), ("RESOLVE_IMAGE_NORMALIZATION", "MACHINE"))
        self.assertEqual(action["frames"], [17])
        self.assertFalse(action["hard_stop"])

    def test_current_policy_prompt_budget_block_routes_to_machine_recompile(self):
        frames = [1, 3, 8, 16]
        blocked = {
            "id": "vl3",
            "frame": 3,
            "kind": "baseline_candidate",
            "scope": "repair",
            "status": "blocked",
            "capture_id": f"visual-lock-candidate-{next_action.visual_lock_candidate_pool.CANDIDATE_POLICY_REVISION}-03-02",
            "attempts": 0,
            "output_path": None,
            "last_error": "prompt budget exceeded: 268 chars/560 bytes; limit=260 chars/900 bytes",
            "execution": {"phase": "BEGIN_REJECTED"},
        }
        queue = {"items": [
            *[{"frame": n, "kind": "original", "scope": "visual_lock", "status": "generated", "completed_at": "2026-09-16T10:00:00+08:00"} for n in frames],
            blocked,
        ]}
        ledger = {f"{n:02d}": {"status": "PASSED"} for n in frames}
        ledger["03"] = {"status": "NEEDS_USER", "content_repairs_used": 1}
        action = self._derive(state="STORYBOARD_LOCKED", queue=queue, ledger=ledger, visual_errors=["stale"])
        self.assertEqual((action["action"], action["executor"]), ("PREPARE_VISUAL_LOCK_CANDIDATES", "MACHINE"))
        self.assertEqual(action["frames"], [3])
        self.assertTrue(action["auto_recoverable"])
        self.assertFalse(action["hard_stop"])

    def test_unrecoverable_nonregenerating_block_hard_stops_before_visual_review(self):
        frames = [1, 5, 16, 17]
        queue = {"items": [
            *[{"frame": n, "kind": "original", "scope": "visual_lock", "status": "generated", "completed_at": "2026-09-14T10:00:00+08:00"} for n in frames],
            {"id": "r17", "frame": 17, "kind": "repair", "scope": "repair", "status": "blocked",
             "technical_failure_code": "PROMPT_SOURCE_DRIFT", "completed_at": "2026-09-14T11:00:00+08:00"},
        ]}
        ledger = {f"{n:02d}": {"status": "ORIGINAL_READY"} for n in frames}
        ledger["17"] = {"status": "TECH_FAILED", "current_candidate": {"sha256": "old", "recorded_at": "2026-09-14T10:00:00+08:00"}}
        with patch.object(next_action.image_blocked_recovery, "inspect", return_value=[{
            "frame": 17, "item_id": "r17", "code": "PROMPT_SOURCE_DRIFT",
            "auto_resolvable": False, "reason": "unsupported_non_regenerating_failure",
        }]):
            action = self._derive(state="STORYBOARD_LOCKED", queue=queue, ledger=ledger, visual_errors=["stale"])
        self.assertEqual(action["action"], "IMAGE_ATTEMPT_BLOCKED")
        self.assertTrue(action["hard_stop"])
        self.assertFalse(action["auto_recoverable"])

    def test_superseded_blocked_row_is_history_not_current_route(self):
        queue = {"items": [
            {"id": "old", "frame": 17, "status": "blocked", "technical_failure_code": "ASPECT_RATIO_MISMATCH",
             "completed_at": "2026-09-14T10:00:00+08:00"},
            {"id": "new", "frame": 17, "status": "generated", "completed_at": "2026-09-14T11:00:00+08:00"},
        ]}
        ledger = {"frames": {"17": {"status": "REPAIR_READY", "current_candidate": {"sha256": "new", "recorded_at": "2026-09-14T11:00:00+08:00"}}}}
        with patch.object(next_action.scheduler_core, "load_queue", return_value=queue), \
                patch.object(next_action.production_ledger, "load_authority", return_value=ledger):
            summary = next_action.queue_summary(Path("ep"))
        self.assertEqual(summary["counts"]["blocked"], 0)
        self.assertEqual(summary["blocked_items"], [])

    def test_authority_refresh_routes_to_regeneration_before_old_visual_review(self):
        frames = [1, 5, 16, 17]
        queue = {"items": [{"frame": n, "kind": "original", "scope": "visual_lock", "status": "generated"} for n in frames]}
        ledger = {f"{n:02d}": {"status": "AUTHORITY_REFRESH_AUTHORIZED", "content_repairs_used": 1} for n in frames}
        action = self._derive(state="STORYBOARD_LOCKED", queue=queue, ledger=ledger, visual_errors=["stale"])
        self.assertEqual((action["action"], action["executor"]), ("REFRESH_AUTHORITY_IMAGES", "CODEX_IMAGE"))
        self.assertEqual(action["frames"], frames)

    def test_stale_visual_lock_generation_routes_to_machine_refresh_before_review(self):
        frames = [1, 5, 16, 17]
        queue = {"items": [{"frame": n, "kind": "original", "scope": "visual_lock", "status": "generated"} for n in frames]}
        ledger = {f"{n:02d}": {"status": "PASSED"} for n in frames}
        stale = [{
            "frame": 16,
            "recorded_frame_contract_sha256": "old",
            "current_frame_contract_sha256": "new",
            "candidate_sha256": "a" * 64,
        }]
        with patch.object(next_action.visual_lock_v21, "stale_generation_bindings", return_value=stale):
            action = self._derive(state="STORYBOARD_LOCKED", queue=queue, ledger=ledger, visual_errors=["stale"])
        self.assertEqual((action["action"], action["executor"]), ("PREPARE_STALE_VISUAL_LOCK_REFRESH", "MACHINE"))
        self.assertEqual(action["frames"], [16])
        self.assertNotIn(1, action["frames"])

    def test_machine_contract_refresh_preserves_budget_and_does_not_forge_user_approval(self):
        frame = {
            "status": "PASSED",
            "content_repairs_used": 1,
            "current_candidate": {"sha256": "c" * 64, "path": "candidate.png"},
            "attempts": [{
                "candidate": {"sha256": "c" * 64},
                "request": {"frame_contract": {"contract_sha256": "old-contract"}},
            }],
            "reviews": [{"decision": "pass"}],
        }
        data = {"frames": {"16": frame}}
        with patch.object(production_ledger_manage, "get_ledger", return_value=(Path("ledger.json"), data)), \
                patch.object(production_ledger_manage, "current_frame_contract_provenance", return_value={"contract_sha256": "new-contract"}), \
                patch.object(production_ledger_manage.resolved_frame_contract, "verify_recorded_provenance", return_value=["frame 16 generation frame_contract_sha256 stale"]), \
                patch.object(production_ledger_manage, "save_json"):
            result = production_ledger_manage.authorize_machine_contract_refresh(Path("ep"), 16, reason="canonical contract changed")
        self.assertEqual(result["status"], "AUTHORITY_REFRESH_AUTHORIZED")
        self.assertEqual(frame["status"], "AUTHORITY_REFRESH_AUTHORIZED")
        self.assertEqual(frame["content_repairs_used"], 1)
        auth = frame["authority_refresh_authorization"]
        self.assertEqual(auth["approval_basis"], "machine_verified_frame_contract_drift")
        self.assertNotIn("approval_text", auth)
        self.assertEqual(auth["previous_frame_contract_sha256"], "old-contract")
        self.assertEqual(auth["frame_contract_sha256"], "new-contract")

    def test_machine_action_authorizes_only_requested_stale_frames(self):
        with patch.object(production_ledger_manage, "authorize_machine_contract_refresh", return_value={
            "status": "AUTHORITY_REFRESH_AUTHORIZED", "frame": 16, "frame_contract_sha256": "new"
        }) as authorize:
            result = machine_action_executor.execute(Path("ep"), {
                "action": "PREPARE_STALE_VISUAL_LOCK_REFRESH", "executor": "MACHINE", "frames": [16]
            })
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["frames"], [16])
        authorize.assert_called_once()

    def test_authority_refresh_waits_for_new_baseline_master_before_dependents(self):
        queue = {"items": [
            {"frame": 1, "kind": "repair", "scope": "repair", "status": "generated"},
            {"frame": 5, "kind": "original", "scope": "visual_lock", "status": "generated"},
            {"frame": 16, "kind": "original", "scope": "visual_lock", "status": "generated"},
            {"frame": 17, "kind": "original", "scope": "visual_lock", "status": "generated"},
        ]}
        ledger = {
            "01": {"status": "REPAIR_READY", "content_repairs_used": 1},
            "05": {"status": "AUTHORITY_REFRESH_AUTHORIZED", "content_repairs_used": 1},
            "16": {"status": "AUTHORITY_REFRESH_AUTHORIZED", "content_repairs_used": 1},
            "17": {"status": "AUTHORITY_REFRESH_AUTHORIZED", "content_repairs_used": 1},
        }
        with patch.object(next_action.visual_lock_baseline_gate, "baseline_frame", return_value=1), \
                patch.object(next_action.character_visual_contract, "pixel_master_required", return_value=True), \
                patch.object(next_action.character_visual_contract, "pixel_master_reference", side_effect=ValueError("stale")):
            action = self._derive(state="STORYBOARD_LOCKED", queue=queue, ledger=ledger, visual_errors=["stale"])
        self.assertEqual((action["action"], action["executor"]), ("REVIEW_ORDINARY_BASELINE", "CODEX_VISION"))
        self.assertEqual(action["frame"], 1)

    def test_valid_visual_lock_routes_to_machine_finalizer(self):
        frames = [1, 5, 16, 17]
        queue = {"items": [{"frame": n, "kind": "original", "scope": "visual_lock", "status": "generated"} for n in frames]}
        ledger = {f"{n:02d}": {"status": "ORIGINAL_READY"} for n in frames}
        action = self._derive(state="STORYBOARD_LOCKED", queue=queue, ledger=ledger)
        self.assertEqual((action["action"], action["executor"]), ("FINALIZE_VISUAL_LOCK", "MACHINE"))

    def test_visual_calibrated_missing_originals_routes_to_batch_preparation(self):
        frames = [1, 5, 16, 17]
        queue = {"items": [{"frame": n, "kind": "original", "scope": "visual_lock", "status": "generated"} for n in frames]}
        ledger = {f"{n:02d}": {"status": "ORIGINAL_READY"} for n in frames}
        action = self._derive(state="VISUAL_CALIBRATED", queue=queue, ledger=ledger)
        self.assertEqual((action["action"], action["executor"]), ("PREPARE_PRODUCTION_BATCH", "MACHINE"))
        self.assertEqual(action["expected_frames"], 20)

    def test_superseded_original_with_current_candidate_stays_represented_during_repair(self):
        queue = {"items": [
            *[{"frame": n, "kind": "original", "scope": "batch", "status": "generated"} for n in range(1, 21) if n != 16],
            {"frame": 16, "kind": "original", "scope": "batch", "status": "superseded"},
            {"frame": 16, "kind": "repair", "scope": "repair", "status": "queued"},
        ]}
        ledger = {f"{n:02d}": {"status": "ORIGINAL_READY", "current_candidate": {"sha256": f"sha-{n}"}} for n in range(1, 21)}
        ledger["16"]["status"] = "REPAIR_AUTHORIZED"
        with patch.object(image_scheduler, "ready_items", return_value=([{"frame": 16}], [])):
            action = self._derive(state="VISUAL_CALIBRATED", queue=queue, ledger=ledger)
        self.assertEqual((action["action"], action["executor"]), ("GENERATE_IMAGES", "CODEX_IMAGE"))
        self.assertEqual(action["frames"], [16])

    def test_complete_candidates_route_to_final_semantic_vision(self):
        queue = {"items": [{"frame": n, "kind": "original", "scope": "batch", "status": "generated"} for n in range(1, 21)]}
        ledger = {f"{n:02d}": {"status": "ORIGINAL_READY"} for n in range(1, 21)}
        action = self._derive(state="VISUAL_CALIBRATED", queue=queue, ledger=ledger)
        self.assertEqual((action["action"], action["executor"]), ("REVIEW_FINAL_PRODUCTION", "CODEX_VISION"))
        self.assertEqual(action["attempt"], 1)

    def test_publish_ready_ignores_stale_ordinary_repair_residue(self):
        queue = {"items": [{"frame": n, "kind": "original", "scope": "batch", "status": "generated"} for n in range(1, 21)]}
        ledger = {f"{n:02d}": {"status": "LOCKED"} for n in range(1, 21)}
        ledger["17"] = {"status": "REPAIR_READY", "content_repairs_used": 1}
        ledger["18"] = {"status": "REPAIR_READY", "content_repairs_used": 1}
        action = self._derive(state="PUBLISH_READY", queue=queue, ledger=ledger)
        self.assertEqual((action["action"], action["executor"]), ("COMPLETE", "WORK"))
        self.assertFalse(action["work_pending"])

    def test_publish_ready_ignores_stale_needs_user_residue(self):
        queue = {"items": [{"frame": n, "kind": "original", "scope": "batch", "status": "generated"} for n in range(1, 21)]}
        ledger = {f"{n:02d}": {"status": "LOCKED"} for n in range(1, 21)}
        ledger["15"] = {"status": "NEEDS_USER", "content_repairs_used": 2}
        action = self._derive(state="PUBLISH_READY", queue=queue, ledger=ledger)
        self.assertEqual((action["action"], action["executor"]), ("COMPLETE", "WORK"))
        self.assertFalse(action["work_pending"])

    def test_publish_ready_direct_user_exception_routes_to_attempt3_exception_review_first(self):
        queue = {"items": [{"frame": n, "kind": "original", "scope": "batch", "status": "generated"} for n in range(1, 21)]}
        ledger = {f"{n:02d}": {"status": "LOCKED"} for n in range(1, 21)}
        ledger["12"] = {"status": "REPAIR_READY", "content_repairs_used": 1, "user_exception_repairs_used": 1,
                        "current_candidate": {"attempt_id": "ex12"},
                        "attempts": [{"attempt_id": "ex12", "request": {"capture_id": "user-exception-FINAL_SEMANTIC-12"}}]}
        ledger["17"] = {"status": "REPAIR_READY", "content_repairs_used": 1}
        action = self._derive(state="PUBLISH_READY", queue=queue, ledger=ledger)
        self.assertEqual((action["action"], action["executor"]), ("REVIEW_FINAL_EXCEPTION", "CODEX_VISION"))
        self.assertEqual(action["frames"], [12])

    def test_publish_ready_user_continuation_candidate_routes_to_own_patch_review(self):
        queue = {"items": [{"frame": n, "kind": "original", "scope": "batch", "status": "generated"} for n in range(1, 21)]}
        ledger = {f"{n:02d}": {"status": "LOCKED"} for n in range(1, 21)}
        ledger["12"] = {
            "status": "REPAIR_READY", "content_repairs_used": 1,
            "user_exception_repairs_used": 1, "user_continuation_repairs_used": 1,
            "current_candidate": {"attempt_id": "cont12"},
            "attempts": [{"attempt_id": "cont12", "request": {"capture_id": "user-continuation-FINAL_SEMANTIC_CONTINUATION-12-01"}}],
        }
        action = self._derive(state="PUBLISH_READY", queue=queue, ledger=ledger)
        self.assertEqual((action["action"], action["executor"]), ("REVIEW_FINAL_CONTINUATION", "CODEX_VISION"))
        self.assertEqual(action["frames"], [12])

    def test_all_locked_frames_route_to_machine_image_finalizer(self):
        queue = {"items": [{"frame": n, "kind": "original", "scope": "batch", "status": "generated"} for n in range(1, 21)]}
        ledger = {f"{n:02d}": {"status": "LOCKED"} for n in range(1, 21)}
        action = self._derive(state="VISUAL_CALIBRATED", queue=queue, ledger=ledger, reviews={"production": "pending", "continuity": "pending", "authenticity": "passed"})
        self.assertEqual((action["action"], action["executor"]), ("FINALIZE_PRODUCTION_IMAGES", "MACHINE"))

    def test_external_provider_block_has_priority_over_stale_needs_user(self):
        queue = {"items": [{"frame": 1, "kind": "baseline_candidate", "scope": "baseline_candidate", "status": "external_blocked", "external_block": {"reason": "technical_retry_exhausted"}}]}
        ledger = {"01": {"status": "TECH_FAILED", "content_repairs_used": 1}}
        with patch.object(next_action.baseline_candidate_pool, "can_prepare", return_value=False):
            action = self._derive(state="STORYBOARD_LOCKED", queue=queue, ledger=ledger)
        self.assertEqual((action["action"], action["executor"]), ("EXTERNAL_IMAGE_PROVIDER_BLOCKED", "EXTERNAL"))
        self.assertTrue(action["hard_stop"])
        self.assertFalse(action["auto_recoverable"])

    def test_capacity_block_with_fallback_routes_to_automatic_technical_retry(self):
        queue = {"items": [{"frame": 16, "kind": "repair", "scope": "repair",
                            "status": "external_blocked", "model": "gpt-image-2.5-flare",
                            "strict_model": False, "technical_failure_code": "PROVIDER_CAPACITY",
                            "external_block": {"reason": "technical_retry_exhausted"}}]}
        ledger = {"16": {"status": "TECH_FAILED", "content_repairs_used": 0}}
        action = self._derive(state="STORYBOARD_LOCKED", queue=queue, ledger=ledger)
        self.assertEqual((action["action"], action["executor"]),
                         ("RETRY_TECHNICAL_FAILURES", "CODEX_IMAGE"))
        self.assertTrue(action["auto_recoverable"])
        self.assertTrue(action["model_failover"])
        self.assertEqual(action["frames"], [16])


class ContinuousHostLoopTests(unittest.TestCase):
    def test_switch_is_read_from_config(self):
        with patch.object(workflow_runner.storyos_config, "get_path", return_value=True):
            self.assertTrue(workflow_runner.continuous_host_loop_enabled())
        with patch.object(workflow_runner.storyos_config, "get_path", return_value=None):
            self.assertFalse(workflow_runner.continuous_host_loop_enabled())

    def test_loop_runs_local_action_then_resumes_dag(self):
        seen, rc_seq = [], [product_runtime_adapter.HOST_ACTION_REQUIRED_RC, 0]

        def fake_step(ep):
            seen.append("step")
            return True, "GENERATE_IMAGES rc=0"

        def fake_dag(ep, **kw):
            seen.append("dag")
            return rc_seq.pop(0)

        with patch.object(workflow_runner, "host_loop_step", side_effect=fake_step), \
                patch.object(workflow_runner.runtime_dag, "execute", side_effect=fake_dag), \
                patch.object(workflow_runner.next_action, "write", return_value={"action": "UNSUPPORTED", "executor": "WORK"}):
            rc, note = workflow_runner.advance_host_loop(Path("ep"), codex=None, timeout=1800, run_id="r", trace_id="t")
        self.assertEqual(rc, 0)
        # The DAG keeps returning HOST_WAIT until the host-owned step appears, so the loop
        # alternates action/DAG until the DAG answers with something else.
        self.assertEqual(seen, ["step", "dag", "step", "dag"])
        self.assertIn("GENERATE_IMAGES", note)

    def test_loop_hands_back_when_host_owns_pending_action(self):
        with patch.object(workflow_runner, "host_loop_step", return_value=(False, "VISUAL_LOCK")), \
                patch.object(workflow_runner.runtime_dag, "execute", side_effect=AssertionError("DAG must not resume without a local action")):
            rc, note = workflow_runner.advance_host_loop(Path("ep"), codex=None, timeout=1800, run_id="r", trace_id="t")
        self.assertEqual(rc, product_runtime_adapter.HOST_ACTION_REQUIRED_RC)
        self.assertIn("VISUAL_LOCK", note)

    def test_loop_runs_codex_vision_review_then_resumes_dag(self):
        action = {"action": "REVIEW_ORDINARY_BASELINE", "executor": "CODEX_VISION"}
        with patch.object(episode_runner.next_action, "write", return_value=action), \
                patch.object(episode_runner, "run_local_host_action", return_value=0) as runner:
            progressed, detail = workflow_runner.host_loop_step(Path("ep"))
        self.assertTrue(progressed)
        self.assertEqual(detail, "REVIEW_ORDINARY_BASELINE rc=0")
        runner.assert_called_once_with(Path("ep"), action)

    def test_loop_is_bounded(self):
        with patch.object(workflow_runner, "host_loop_step", return_value=(True, "GENERATE_IMAGES rc=0")), \
                patch.object(workflow_runner.runtime_dag, "execute", return_value=product_runtime_adapter.HOST_ACTION_REQUIRED_RC), \
                patch.object(workflow_runner.next_action, "write", return_value={"action": "GENERATE_IMAGES", "executor": "CODEX_IMAGE"}):
            rc, note = workflow_runner.advance_host_loop(Path("ep"), codex=None, timeout=1800, run_id="r", trace_id="t", max_cycles=2)
        self.assertEqual(rc, product_runtime_adapter.HOST_ACTION_REQUIRED_RC)
        self.assertIn("max_cycles=2", note)

    def test_loop_returns_technical_failure_from_a_local_host_action(self):
        with patch.object(workflow_runner, "host_loop_step", return_value=(True, "REVIEW_ORDINARY_BASELINE rc=21")), \
                patch.object(workflow_runner.runtime_dag, "execute", side_effect=AssertionError("DAG must not run after a failed host action")):
            rc, note = workflow_runner.advance_host_loop(Path("ep"), codex=None, timeout=1800, run_id="r", trace_id="t")
        self.assertEqual(rc, 21)
        self.assertIn("host_action_technical_failure", note)

    def test_content_review_fail_is_progress_not_technical_failure(self):
        action = {"action": "REVIEW_VISUAL_LOCK", "executor": "CODEX_VISION"}
        with patch.object(episode_runner, "local_image_action", return_value=None), \
                patch.object(vision_review_executor, "local_vision_action", return_value="REVIEW_VISUAL_LOCK"), \
                patch.object(vision_review_executor, "execute", return_value={"status": "FAIL"}), \
                patch.object(episode_runner, "record_event"), \
                patch.object(episode_runner.next_action, "write", return_value={"action": "PREPARE_VISUAL_LOCK_CANDIDATE", "executor": "MACHINE"}):
            self.assertEqual(episode_runner.run_local_host_action(Path("ep"), action), 0)

    def test_authority_refresh_is_a_local_image_action(self):
        action = {"action": "REFRESH_AUTHORITY_IMAGES", "executor": "CODEX_IMAGE"}
        self.assertEqual(episode_runner.local_image_action(action), "REFRESH_AUTHORITY_IMAGES")

    def test_execute_cycle_prefers_the_local_image_action(self):
        action = {"action": "GENERATE_IMAGES", "executor": "CODEX_IMAGE"}
        with tempfile.TemporaryDirectory() as td:
            episode = Path(td)
            with patch.object(episode_runner.next_action, "write", return_value=action), \
                    patch.object(episode_runner, "run_local_image_action", return_value=5) as runner, \
                    patch.object(episode_runner.runtime_dag, "execute", side_effect=AssertionError("DAG must not run for a local image action")):
                self.assertEqual(episode_runner.execute_cycle(episode), 5)
            runner.assert_called_once()

    def test_execute_cycle_consumes_fresh_local_action_after_dag_host_wait(self):
        initial = {"action": "VISUAL_LOCK", "executor": "WORK"}
        following = {"action": "APPLY_VISUAL_LOCK_WEAK_PASS", "executor": "MACHINE", "frames": [3]}
        with tempfile.TemporaryDirectory() as td:
            episode = Path(td)
            with patch.object(episode_runner.next_action, "write", side_effect=[initial, following]), \
                    patch.object(episode_runner, "local_host_action", side_effect=[None, "APPLY_VISUAL_LOCK_WEAK_PASS"]), \
                    patch.object(episode_runner.runtime_dag, "execute", return_value=product_runtime_adapter.HOST_ACTION_REQUIRED_RC), \
                    patch.object(episode_runner, "run_local_host_action", return_value=0) as local_runner:
                self.assertEqual(episode_runner.execute_cycle(episode), 0)
            local_runner.assert_called_once_with(episode, following)

    def test_execute_cycle_falls_back_to_dag(self):
        with tempfile.TemporaryDirectory() as td:
            episode = Path(td)
            with patch.object(episode_runner.next_action, "write", return_value={"action": "VISUAL_LOCK", "executor": "WORK"}), \
                    patch.object(episode_runner.runtime_dag, "execute", return_value=product_runtime_adapter.HOST_ACTION_REQUIRED_RC):
                self.assertEqual(episode_runner.execute_cycle(episode), product_runtime_adapter.HOST_ACTION_REQUIRED_RC)


if __name__ == "__main__":
    unittest.main()
