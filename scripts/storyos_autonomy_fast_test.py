#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline four-slot autonomy smoke/fault-injection tests. Never starts production."""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SLOTS = {
    # 永久回归：M00/Frame Contract/Driver/Watchdog/Attempt 使用本次代码检查。
    "production-regression": [
        "tests/system/test_second_round_review_convergence.py",
        "tests/system/test_native_runner_artifact_first_success.py",
        "tests/system/test_native_direct_image_thread_archive.py",
        "tests/system/test_f001_unknown_operator_disposition.py",
        "tests/system/test_f001_attempt2_native_raw_reconcile.py",
        "tests/system/test_baseline_contract_identity_and_budget.py",
        "tests/system/test_baseline_review_only.py",
        "tests/system/test_f001_independent_baseline_pass_cas.py",
        "tests/system/test_native_f001_verified_three_followon.py",
        "tests/system/test_ep14_reviewed_visual_repair.py",
        "tests/system/test_ep14_inflight_repair_guard.py",
        "tests/system/test_ep14_exhausted_soft_visual_release.py",
        "tests/system/test_ep14_weakpass_route_and_rc22.py",
        "tests/system/test_ep14_weakpass_partial_resume.py",
        "tests/system/test_ep14_visual_machine_projection_anchor_restore.py",
        "tests/system/test_ep14_native_batch_pilot.py",
        "tests/system/test_ep14_profile_and_batch_followon.py",
        "tests/system/test_native_image_outcome_evidence.py",
        "tests/system/test_native_429_attempt_reconciliation_fence.py",
        "tests/system/test_native_repair_pilot_capability.py",
        "tests/system/test_reviewed_repair_handoff_rc4.py",
        "tests/system/test_native_repair_wave_routing.py",
        "tests/system/test_one_repair_wave.py",
        "tests/system/test_driver_exit_remediation.py",
        "tests/system/test_final_semantic_reentry_source_binding.py",
        "tests/system/test_final_semantic_failure_reentry.py",
        "tests/system/test_native_runner_stale_endpoint.py",
        "tests/system/test_driver_long_review_hot_state.py",
        "tests/system/test_repository_hygiene_contract.py",
        "tests/system/test_final_semantic_durable_output_fallback.py",
        "tests/system/test_final_semantic_atomic_closure.py",
        "tests/system/test_review_stall_diagnostic.py",
        "tests/system/test_m00_finalizer_weakpass_reentry.py",
        "tests/system/test_prompt_package_equivalent_projection.py",
        "tests/system/test_locked_story_prompt_authoring_fastpath.py",
        "tests/system/test_image_capability_blocked_plan.py",
        "tests/system/test_native_batch_reentry.py",
        "tests/system/test_native_batch_post_success_followon.py",
        "tests/system/test_image_unknown_raw_reconcile.py",
        "tests/system/test_ep14_reviewed_landscape.py",
        "tests/system/test_f045_raw_ratio_scope.py",
        "tests/system/test_native_image_failure_receipt_durability.py",
        "tests/system/test_native_runner_mysql_dispatch_identity.py",
        "tests/system/test_native_network_failure_rearm.py",
        "tests/system/test_ep14_tls_terminal_audit.py",
        "tests/system/test_ep14_network_attempt2_reentry.py",
        "tests/system/test_ep14_provider_safety_terminal.py",
        "tests/system/test_ep14_safety_content_review.py",
        "tests/system/test_ep14_visual_treatment_preview.py",
        "tests/system/test_ep14_review_staging_package.py",
        "tests/system/test_ep14_render_relock_preflight.py",
    "tests/system/test_ep14_independent_review_evidence.py",
        "tests/system/test_native_provider_safety_classification.py",
        "tests/system/test_runner_host_loop_v262.py::NextActionAutonomousBatchTests::test_preserved_native_raw_precedes_unknown_backend_block_without_retry",
        "tests/system/test_runner_host_loop_v262.py::NextActionAutonomousBatchTests::test_verified_first_batch_succeeded_unblocks_history_via_machine_action",
        "tests/system/test_native_driver_carrier_timeout.py",
        "tests/system/test_image_capability_preflight_failure_taxonomy.py",
        "tests/system/test_login_auth_payload_transport.py",
        "tests/system/test_m00_exhausted_baseline_weak_pass.py",
        "tests/system/test_projection_sha_authority_reentry.py",
        "tests/system/test_storyos_autonomy_watchdog_policy.py",
        "tests/system/test_generation_unknown_technical_retry_guard.py",
        "tests/system/test_image_scheduler_review_exit_v4.py",
        "tests/system/test_storyos_autonomy_r9_probe.py",
        "tests/system/test_runtime_recovery.py::RecoveryTests::test_retry_is_bounded_and_checkpoint_preserved",
        "tests/system/test_runtime_recovery.py::RecoveryTests::test_progress_marker_sees_metadata_only_weak_pass_progress",
    ],
    "entry": ["tests/system/test_storyos_native_codex_full_auto_entry.py"],
    "driver": ["tests/system/test_storyos_native_driver_scope.py"],
    "recovery": ["tests/system/test_storyos_autonomy_extreme.py"],
    # Fast closure runs representative fail-closed, budget and success boundaries.
    "closure": ["tests/system/test_canonical_full_auto_integration.py",
                "-k", "case5 or case9b or case14b"],
    # R2: each autonomous modification has a dedicated subsecond extreme case.
    "watchdog": ["tests/system/test_storyos_autonomy_watchdog_policy.py"],
    "budget": ["tests/system/test_storyos_autonomy_watchdog_budget.py"],
    "authority": ["tests/system/test_storyos_autonomy_watchdog_authority.py"],
    "e2e": ["tests/system/test_storyos_autonomy_watchdog_e2e.py"],
    # R3 four slots; each one fast before the integrated stress run.
    "carrier": ["tests/system/test_storyos_autonomy_r3_carrier.py"],
    "writer": ["tests/platform/test_storyos_autonomy_r3_writer.py",
               "tests/platform/test_runtime_state_store.py",
               "tests/platform/test_worker_lock_state.py"],
    "canary": ["tests/system/test_storyos_autonomy_r3_canary.py"],
    "autonomy-integration": ["tests/system/test_storyos_autonomy_r3_integration.py"],
    # R4: paid-dispatch fence / user carrier / Frame01 evidence / integrated gate.
    "dispatch-fence": ["tests/system/test_storyos_autonomy_r4_dispatch_fence.py",
                       "tests/system/test_image_payload_attempt_boundary.py",
                       "-k", "gateway or fence"],
    "carrier-integrity": ["tests/system/test_storyos_autonomy_r4_carrier.py"],
    "frame01-fence": ["tests/system/test_storyos_autonomy_r4_canary.py"],
    "r4-integration": ["tests/system/test_storyos_autonomy_r4_integration.py"],
    # R5 four-slot delivery: Git governance, receipt authority, native login,
    # and cross-boundary integration. No task runs a paid image Provider.
    "retirement": ["tests/system/test_storyos_autonomy_r5_retirement.py"],
    "provider-receipt": ["tests/system/test_storyos_autonomy_r5_provider_receipt.py"],
    "native-login": ["tests/system/test_storyos_autonomy_r5_native_login.py"],
    "r5-integrated": ["tests/system/test_storyos_autonomy_r5_integration.py"],
    # R6 four slots: retirement ref pin, ambiguous dispatch, native CLI/Frame01,
    # and cross-system fail-closed tests.
    "gc-fence": ["tests/system/test_storyos_autonomy_r6_gc.py"],
    "provider-timeout": ["tests/system/test_storyos_autonomy_r6_receipt.py"],
    "codex-frame01": ["tests/system/test_storyos_autonomy_r6_canary.py"],
    "r6-e2e": ["tests/system/test_storyos_autonomy_r6_e2e.py"],
    # R7: Git ref CAS, strict paid-edge post-commit proofs,
    # native CLI/Runner binary+version agreement, end-to-end isolation.
    "gc-atomic": ["tests/system/test_storyos_autonomy_r7_gc.py"],
    "gateway-proof": ["tests/system/test_storyos_autonomy_r7_gateway.py"],
    "native-route": ["tests/system/test_storyos_autonomy_r7_native.py"],
    "r7-closure": ["tests/system/test_storyos_autonomy_r7_closure.py"],
    # R8: split legacy UNKNOWN recovery from real Frame01 visual evidence;
    # distinguish DAG start from image admission and canonical MySQL stage.
    "frame01-real": ["tests/system/test_storyos_autonomy_r8_frame01.py",
                     "tests/system/test_storyos_visual_lock_readonly.py"],
    "native-image-readiness": ["tests/system/test_storyos_autonomy_r8_native.py"],
    "stage-drift": ["tests/system/test_storyos_autonomy_r8_stage.py"],
    "r8-integration": ["tests/system/test_storyos_autonomy_r8_integration.py"],
    # R9: authorized production pilot; every live observation is read-only,
    # and real paid delivery still goes through native canonical Gateway.
    "real-canary": ["tests/system/test_storyos_autonomy_r9_probe.py",
                    "tests/system/test_storyos_autonomy_r9_native_routing.py"],
    "watchdog-user": ["tests/system/test_storyos_autonomy_r9_watchdog_user.py",
                      "tests/system/test_storyos_autonomy_r4_carrier.py"],
    "mysql-receipt": ["tests/system/test_storyos_autonomy_r9_probe.py",
                      "tests/system/test_storyos_autonomy_r8_stage.py"],
    "r9-integrated": ["tests/system/test_storyos_autonomy_r9_integration.py"],
    # R10: concrete main-Episode reproduction of attempt-162 drift and
    # finalized review lacking official evidence, no paid image loops.
    "story-critic-authority": [
        "tests/system/test_storyos_autonomy_r10_story_attempt.py",
        "tests/system/test_storyos_autonomy_r10_runtime_admission.py"],
    "driver-lifecycle": ["tests/system/test_storyos_autonomy_r10_driver_paid.py",
                          "tests/system/test_storyos_autonomy_watchdog_policy.py"],
    "paid-attempt-proof": ["tests/system/test_storyos_autonomy_r10_driver_paid.py",
                           "tests/system/test_storyos_autonomy_r9_probe.py"],
    "r10-integrated": ["tests/system/test_storyos_autonomy_r10_integration.py"],
    # R11: Git-verified source rename and exactly preserved independent Critic
    # provenance, no imitation PASS or automatic image authorization.
    "review-relocation": ["tests/system/test_storyos_autonomy_r11_relocation.py",
                           "tests/system/test_storyos_autonomy_r11_manifest.py"],
    "review-restore-guard": ["tests/system/test_storyos_autonomy_r11_restore.py",
                             "tests/system/test_storyos_autonomy_r11_resume.py"],
    "frame01-after-review": ["tests/system/test_storyos_autonomy_r11_frame01.py"],
    "r11-closure": ["tests/system/test_storyos_autonomy_r11_closure.py"],
    # R12: fully independent, single-use native Codex Critic epoch for a
    # migrated Episode whose original reviewed formal standard SHA drifted.
    "r12-critic-epoch": ["tests/system/test_storyos_autonomy_r12_critic_epoch.py"],
    "r12-driver-gate": ["tests/system/test_storyos_autonomy_r12_driver_review.py"],
    "r12-frame01-proof": ["tests/system/test_storyos_autonomy_r12_text_pixel.py",
                          "tests/system/test_storyos_autonomy_r12_entrypoint.py"],
    "r12-integrated": ["tests/system/test_storyos_autonomy_r12_closure.py"],
    # R13: integration of R12 independently bounded native Critic with
    # pending Concept Selection A3/A4/A5 and immutable history lookup.
    "r13-critic-merge": ["tests/system/test_storyos_autonomy_r13_critic_merge.py",
                          "tests/system/test_concept_ambition_rereview_plan.py"],
    "r13-attempt-history": ["tests/system/test_storyos_autonomy_r13_attempt_history.py"],
    "r13-frame01": ["tests/system/test_storyos_autonomy_r13_frame01.py"],
    "r13-integrated": ["tests/system/test_storyos_autonomy_r13_integrated.py"],
    # R14: don't confuse a test Worktree with production, enforce exact
    # native Codex binary identity and frozen current-rubric SHA authority.
    "r14-primary-worktree": ["tests/system/test_storyos_autonomy_r14_primary.py"],
    "r14-native-identity": ["tests/system/test_storyos_autonomy_r14_identity.py"],
    "r14-critic-history": ["tests/system/test_storyos_autonomy_r14_history.py"],
    "r14-closure": ["tests/system/test_storyos_autonomy_r14_closure.py"],
    # R15: production release overlap gate, Windows read-only text Critic,
    # irreversibility and pixel/Attempt boundaries.
    "r15-release-overlap": ["tests/system/test_storyos_autonomy_r15_release.py"],
    "r15-critic-sandbox": ["tests/system/test_storyos_autonomy_r15_critic.py"],
    "r15-frame01": ["tests/system/test_storyos_autonomy_r15_frame01.py"],
    "r15-closure": ["tests/system/test_storyos_autonomy_r15_closure.py"],
    # R16: one-shot A9 native timeout reconciliation and paid DAG blocker.
    "r16-receipt": ["tests/system/test_storyos_autonomy_r16_receipt.py"],
    "r16-candidate": ["tests/system/test_storyos_autonomy_r16_candidate.py"],
    "r16-driver": ["tests/system/test_storyos_autonomy_r16_driver.py"],
    "r16-integrated": ["tests/system/test_storyos_autonomy_r16_integrated.py"],
    # Episode 15: four tiny content-draft checks, no new model dispatch.
    "ep15-subtitles": ["tests/system/test_episode15_content_repair_draft.py::test_ep15_caption_draft_all_20_frames_from_locked_source"],
    "ep15-frame15": ["tests/system/test_episode15_content_repair_draft.py::test_ep15_frame15_has_new_observable_change_and_causes_frame16"],
    "ep15-hairpin": ["tests/system/test_episode15_content_repair_draft.py::test_ep15_wooden_hairpin_source_and_carry_chain_unambiguous"],
    "ep15-a9-fence": ["tests/system/test_episode15_content_repair_draft.py::test_ep15_locked_v1_bytes_untouched_and_a9_still_nonretryable"],
    # Source revision after native A9 timeout; four small independent fences.
    "a10-source": ["tests/system/test_storyos_r17_a10_new_source.py::test_a10_independent_source_epoch_ready_but_never_pass"],
    "a10-one-shot": ["tests/system/test_storyos_r17_a10_new_source.py::test_a10_ticket_is_exclusive_and_binds_both_source_and_old_receipt"],
    "a10-native": ["tests/system/test_storyos_r17_a10_new_source.py::test_a10_native_admission_and_early_fences"],
    "a10-integration": [
        "tests/system/test_storyos_r17_a10_new_source.py::test_a10_success_cannot_be_borrowed_from_a9_or_legacy_history",
        "tests/system/test_storyos_r17_a10_new_source.py::test_a10_full_story_review_payload_has_to_verify_real_new_source",
        "tests/system/test_storyos_r17_a10_new_source.py::test_canonical_a10_pass_can_replace_only_unbound_historical_gate"],
    "r18-receipt": ["tests/system/test_storyos_r18_a10_reconciliation.py::test_runner_proof_requires_sha_and_success"],
    "r18-no-replay": [
        "tests/system/test_storyos_r18_a10_reconciliation.py::test_complete_provider_json_cannot_be_replayed_from_partial",
        "tests/system/test_storyos_r18_a10_reconciliation.py::test_reconciliation_refuses_untrusted_episode_without_writes"],
    "r18-failure": [
        "tests/system/test_storyos_r18_a10_reconciliation.py::test_a10_past_review_sha_optional_preserves_candidate_on_fail",
        "tests/system/test_storyos_r18_a10_reconciliation.py::test_fenced_record_fail_uses_existing_payload_never_model"],
    "r18-content": ["tests/system/test_storyos_r18_a10_reconciliation.py::test_two_frame_concrete_fix_is_only_a_draft"],
    "r19-story": ["tests/system/test_storyos_r19_a11_repair.py::test_r19_real_content_all_20_and_source_not_formally_passed"],
    "r19-predecessor": ["tests/system/test_storyos_r19_a11_repair.py::test_r19_one_shot_plan_readonly_and_old_fail_sha_binds"],
    "r19-one-shot": ["tests/system/test_storyos_r19_a11_repair.py::test_r19_a11_durable_ticket_only_once_prior_candidate_intact"],
    "r19-driver": ["tests/system/test_storyos_r19_a11_repair.py::test_r19_old_requests_not_replayed_and_driver_still_blocked"],
    "r20-critic-authority": ["tests/system/test_storyos_r20_pixel_authority.py::test_a11_verified_mysql_pass_supersedes_a9_timeout_but_not_history"],
    "r20-real-pixels": ["tests/system/test_storyos_r20_pixel_authority.py::test_pixel_test_receipt_sha_native_but_never_grants_production"],
    "r20-driver": ["tests/system/test_storyos_r20_pixel_authority.py::test_a11_validated_driver_preflight_does_not_claim_image_ready"],
    "r20-frame01": ["tests/system/test_storyos_r20_pixel_authority.py::test_frame01_cannot_borrow_m00_test_pixels_as_attempt"],
    "r21-driver-env": ["tests/system/test_storyos_r21_driver_runtime_env.py::test_child_native_ignores_inherited_stale_db_and_proxy"],
    "r21-fail-closed": ["tests/system/test_storyos_r21_driver_runtime_env.py::test_native_fails_closed_without_local_db_binding"],
    "r21-legacy-compat": ["tests/system/test_storyos_r21_driver_runtime_env.py::test_legacy_non_native_maintains_explicit_test_env"],
    "r21-review-image": ["tests/system/test_storyos_r21_driver_runtime_env.py::test_native_review_reuse_is_not_image_permission"],
}
FULL_STRESS = [
    "tests/platform/test_runtime_state_store.py",
    "tests/platform/test_worker_lock_state.py",
    "tests/system/test_canonical_full_auto_integration.py",
    "tests/system/test_runtime_recovery.py",
    "tests/system/test_runner_host_loop_v262.py",
    "tests/system/test_multi_episode_global_image_capacity.py",
    "tests/system/test_storyos_native_codex_whole_chain_routes.py",
]


def test_commands(*, slot: str, stress: bool = False) -> list[list[str]]:
    """Expose exact hermetic commands for independent offline regression checks."""
    selected = SLOTS if slot == "all" else {slot: SLOTS[slot]}
    commands = []
    for name, files in selected.items():
        # CI bootstrap makes platform imports deterministic on Linux and Windows.
        launcher = ([sys.executable, str(ROOT / "scripts/ci_storyos_python.py"),
                     "-m", "pytest", "--import-mode=importlib"]
                    if name == "production-regression" else
                    [sys.executable, "-m", "pytest"])
        commands.append([*launcher, "-q", *files, "--tb=short"])
    if stress:
        commands.append([sys.executable, "-m", "pytest", "-q", *FULL_STRESS,
                         "--tb=short"])
    return commands


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slot", choices=(*SLOTS, "all"), default="all")
    parser.add_argument("--stress", action="store_true",
                        help="also run full recovery/capacity/host-loop regressions")
    args = parser.parse_args(argv)
    for command in test_commands(slot=args.slot, stress=args.stress):
        print("TEST", " ".join(command[2:]), flush=True)
        result = subprocess.run(command, cwd=ROOT, check=False)
        if result.returncode != 0:
            return int(result.returncode)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
