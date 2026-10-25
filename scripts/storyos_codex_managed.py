#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Explicit native-Codex-only StoryOS full-auto entrypoint.

This is an admission/transport wrapper, never a second production scheduler.
`plan` is read-only. `run`, `start` and `create` require explicit acknowledgement.
`start` delegates to the existing resident runtime_driver; the other commands
use the canonical story_os.py workflow.
Existing UNKNOWN Generation Attempts fail closed before any work starts.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from phase9_runtime_launcher import RUNTIME_ENV_KEYS, load_runtime_env_file
import storyos_driver_exit_remediation as exit_remediation

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ENV = ROOT / ".storyos/runtime-launcher/runtime.env"
SYSTEM = ROOT / "episodes/_system"
EPISODES = ROOT / "episodes"
DB_KEYS = ("STORYOS_MYSQL_HOST", "STORYOS_MYSQL_PORT",
           "STORYOS_MYSQL_USER", "STORYOS_MYSQL_PWD", "STORYOS_MYSQL_DB")
# A login-session native Codex execution must never inherit an OpenCodex
# OpenAI-compatible endpoint or an unrelated API-key based provider.
PROXY_OVERRIDE_KEYS = ("OPENAI_BASE_URL", "OPENAI_API_BASE",
                       "CODEX_BASE_URL", "STORY_OS_OPENCODEX_URL",
                       "OPENAI_API_KEY", "STORY_OS_WEBCODEX_AVAILABLE",
                       "WEBCODEX_SERVICE_ROOT", "WEBCODEX_ENV_FILE")
FORBIDDEN_MODE_KEYS = ("STORY_OS_RUNTIME", "STORY_OS_IMAGE_RUNTIME")


def native_environment(*, source: dict[str, str] | None = None,
                       runtime_env: Path = RUNTIME_ENV) -> dict[str, str]:
    """Use the canonical ignored runtime.env, never the host's stale DB vars."""
    if not runtime_env.is_file():
        raise ValueError("NATIVE_CODEX_RUNTIME_ENV_MISSING")
    env = dict(os.environ if source is None else source)
    for key in RUNTIME_ENV_KEYS | set(PROXY_OVERRIDE_KEYS) | set(FORBIDDEN_MODE_KEYS):
        env.pop(key, None)
    env, _loaded = load_runtime_env_file(runtime_env, env)
    if any(not env.get(key) for key in DB_KEYS):
        raise ValueError("NATIVE_CODEX_RUNTIME_DB_IDENTITY_UNCONFIGURED")
    # Explicit scope-local mode, not a global config rewrite. On Windows a
    # foreground supervisor inherits this exact environment for all children.
    env["STORY_OS_PRODUCTION_MODE"] = "CODEX_MANAGED"
    env["STORY_OS_IMAGE_EXECUTOR"] = "CODEX"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def canonical_episode(raw: str) -> Path:
    ep = Path(raw)
    ep = (ep if ep.is_absolute() else ROOT / ep).resolve()
    if not ep.is_dir() or not ep.is_relative_to(EPISODES.resolve()):
        raise ValueError("NATIVE_CODEX_EPISODE_PATH_INVALID")
    return ep


def _probe(env: dict[str, str], script: str, args: list[str],
           *, timeout: int = 110) -> tuple[int, dict]:
    """Execute a read-only canonical check, returning sanitized structured data."""
    cmd = [sys.executable, str(ROOT / "scripts/storyos_production_env.py"),
           script, *args]
    try:
        proc = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True,
                              encoding="utf-8", errors="replace", text=True,
                              check=False, timeout=timeout)
        data = json.loads(proc.stdout)
        return proc.returncode, data if isinstance(data, dict) else {}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        # Never expose a DSN, raw subprocess output or credential.
        return 2, {}


def resident_restart_permitted(driver: dict) -> bool:
    """Only resume a clean/yielded or unexpectedly vanished Driver.

    All canonical Episode/Attempt authorities are revalidated by preflight.
    A nonzero recorded exit is an exhausted/hard stop, not a watchdog retry.
    """
    state = str(driver.get("driver_state") or "")
    if state == "NEVER_STARTED":
        return True
    code = str(driver.get("exit_code") or "").strip().split(" ", 1)[0]
    if state == "ABNORMAL_DISAPPEARANCE":
        # A killed carrier is recoverable only when the pid is proven gone.
        # Attempt and owner authority remain independent mandatory gates.
        return driver.get("liveness") == "DEAD" and not code
    return state == "EXITED" and code in {"", "0"}


def admission_summary(*,stage:dict,visual:dict,native_ready:dict,
                      blockers:list[str])->dict:
    """Split DAG startability from proven paid-image readiness.

    Neither a healthy CLI nor a clean MySQL Stage means an image may be
    dispatched. Only canonical Gateway/Attempt and pixel gates can authorize.
    """
    dag=(not blockers and stage.get("status")=="STAGE_ELIGIBLE")
    visual_status=visual.get("status") if isinstance(visual,dict) else None
    reason=visual.get("reason") if isinstance(visual,dict) else None
    return {"dag_startable":bool(dag),"image_ready":False,
            "image_blocking_reason":(
                reason if isinstance(reason,str) and reason else
                "IMAGE_TOOL_ENTITLEMENT_AND_PIXEL_PROOF_UNVERIFIED"),
            "visual_lock_status":visual_status,
            "real_image_tool_verified":False,
            "production_authorization":False}


def preflight(env: dict[str, str], *, episode: Path | None = None) -> dict:
    """Read-only gate. No owner acquisition, revision activation or model calls."""
    blockers: list[str] = []
    rc, caps = _probe(env, "episodes/_system/runtime_router.py", ["capabilities"])
    mode_ok = (rc == 0 and caps.get("effective_production_mode") == "CODEX_MANAGED"
               and caps.get("effective_runtime") == "CODEX"
               and caps.get("image_execution_runtime") == "CODEX"
               and caps.get("local_codex_spawn_allowed") is True
               and caps.get("local_codex_image_spawn_allowed") is True
               and caps.get("text_review_runtime") == "CODEX"
               and caps.get("vision_review_runtime") == "CODEX"
               and caps.get("governance_review_runtime") == "CODEX")
    if not mode_ok:
        blockers.append("NATIVE_CODEX_MODE_OR_EXECUTOR_UNAVAILABLE")
    rc, health = _probe(env, "episodes/_system/codex_user_runner.py", ["health", "--json"])
    native_ok = (rc == 0 and health.get("status") == "ok"
                 and health.get("codex_available") is True
                 and health.get("codex_auth_present") is True)
    if not native_ok:
        blockers.append("NATIVE_CODEX_AUTH_OR_USER_RUNNER_UNAVAILABLE")
    # The bridge presence check does not prove that the policy-bound -m model
    # can run on this CLI version. Check the CLI floor without any paid call.
    # This is necessary but not sufficient: account entitlement is still
    # unverified until a separate real native Codex model probe succeeds.
    model_args = (["--episode", episode.relative_to(ROOT).as_posix()]
                  if episode is not None else [])
    rc, model_readiness = _probe(
        env, "scripts/storyos_native_model_readiness.py", model_args
    )
    model_version_ok = (rc == 0
                        and model_readiness.get("status") == "CLIENT_VERSION_COMPATIBLE")
    if not model_version_ok:
        blockers.append("NATIVE_CODEX_MODEL_CLI_VERSION_OR_POLICY_UNVERIFIED")
    rc, schema = _probe(env, "scripts/storyos_revision_schema_readonly.py", [])
    if rc != 0 or schema.get("status") != "READY_FOR_FURTHER_ADMISSION":
        blockers.append("PRODUCTION_MYSQL_REVISION_SCHEMA_UNVERIFIED")
    attempts: dict = {}
    driver: dict = {}
    stage: dict = {}
    creative_recovery: dict = {}
    visual_lock_admission: dict = {"status": "NOT_APPLICABLE"}
    driver_recovery: dict = {"status": "NOT_APPLICABLE", "read_only": True}
    if episode is not None:
        rc, stage = _probe(env, "scripts/storyos_episode_stage_readonly.py",
                           ["--episode", episode.relative_to(ROOT).as_posix()])
        if rc != 0 or stage.get("status") != "STAGE_ELIGIBLE":
            blockers.append("EPISODE_STAGE_NOT_ELIGIBLE_FOR_PRODUCTION")
        rel = episode.relative_to(ROOT).as_posix()
        # An irreversible A9 new-Review ticket forbids DAG start while its
        # one-shot Codex result is timed out, unknown, or lacks canonical
        # MySQL PASS. Never interpret a healthy CLI as paid-review authority.
        if (episode/"meta/runtime/story-review-migrated-rubric-a9.json").is_file():
            a9_rc, a9_report = _probe(
                env, "scripts/storyos_a9_receipt_reconcile.py", ["--episode", rel])
            if (a9_rc != 0 or a9_report.get("status") not in {
                    "CANONICAL_A9_PASS_VERIFIED",
                    "CANONICAL_A10_PASS_VERIFIED",
                    "CANONICAL_A11_PASS_VERIFIED"}):
                blockers.append("STORY_REVIEW_A9_RECONCILIATION_REQUIRED")
        recovery_rc, creative_recovery = _probe(
            env, "scripts/storyos_creative_recovery_readonly.py", ["--episode", rel]
        )
        if recovery_rc != 0:
            creative_recovery = {"status": "CREATIVE_RECOVERY_AUTHORITY_UNVERIFIED"}
        rc, attempts = _probe(env, "scripts/storyos_attempt_readonly_preflight.py",
                              ["--episode", rel])
        if rc != 0 or attempts.get("status") != "ATTEMPT_HISTORY_READ_ONLY":
            # UNKNOWN is a terminal historical fact, NOT a retry permission.
            blockers.append("GENERATION_ATTEMPT_AUTHORITY_RECONCILIATION_REQUIRED")
        rc, driver = _probe(env, "episodes/_system/runtime_driver.py",
                            ["status", rel, "--json"])
        restartable = (rc == 0 and resident_restart_permitted(driver))
        if (not restartable and rc == 0
                and driver.get("driver_state") == "EXITED"
                and driver.get("exit_code") == "4"
                and driver.get("pid") == 0
                and driver.get("liveness") == "DEAD"
                and stage.get("status") == "STAGE_ELIGIBLE"
                and attempts.get("status") == "ATTEMPT_HISTORY_READ_ONLY"
                and not attempts.get("outcome_unknown_assets")
                and not attempts.get("active_attempt_assets")):
            # The previous quality-gate rc4 cannot be cleared or ignored. A
            # separate read-only authority proves the old event was superseded
            # by a newer, canonical A15 PASS for the exact locked source.
            recovery_rc, recovery = _probe(
                env, "scripts/storyos_post_review_rc4_readonly.py",
                ["--episode", rel]
            )
            if (recovery_rc == 0
                    and recovery.get("status") ==
                       "HISTORICAL_STORY_RC4_SUPERSEDED_BY_VERIFIED_A15_PASS"
                    and recovery.get("story_gate_verified") is True
                    and recovery.get("driver_record_sha256") ==
                        exit_remediation.canonical_sha(driver.get("record") or {})):
                restartable = True
                driver_recovery = {
                    "status": "HISTORICAL_STORY_RC4_SUPERSEDED_BY_VERIFIED_A15_PASS",
                    "driver_record_sha256": recovery["driver_record_sha256"],
                    "read_only": True, "production_authorization": False,
                }
            else:
                driver_recovery = {
                    "status": recovery.get("status") or "STORY_RC4_READ_AUTHORITY_ERROR",
                    "read_only": True, "production_authorization": False,
                }
            if not restartable:
                # A distinct post-PASS exit can be caused solely by the
                # Character Contract still referencing the PREVIOUS approved
                # Story bytes. This exception proves that exact newest rc4 and
                # the current official Story PASS without writing any state.
                # Never convert a quality/content/transport rc4 into a retry.
                newer_rc, newer = _probe(
                    env, "scripts/storyos_character_rc4_readonly.py",
                    ["--episode", rel]
                )
                if (newer_rc == 0
                        and newer.get("status") ==
                            "STORY_RC4_APPROVED_CHARACTER_BINDING_RECOVERABLE"
                        and newer.get("story_gate_verified") is True
                        and newer.get("driver_record_sha256") ==
                            exit_remediation.canonical_sha(driver.get("record") or {})):
                    restartable = True
                    driver_recovery = {
                        "status": "STORY_RC4_APPROVED_CHARACTER_BINDING_RECOVERABLE",
                        "driver_record_sha256": newer["driver_record_sha256"],
                        "binding_action": "CAS_APPEND_ONLY_WITHIN_EXPLICIT_DRIVER",
                        "read_only": True, "production_authorization": False,
                    }
                else:
                    driver_recovery = {
                        "status": newer.get("status") or "CHARACTER_RC4_PROOF_UNVERIFIED",
                        "read_only": True, "production_authorization": False,
                    }
            if not restartable:
                # Latest post-story rc4 may be a Host envelope-only rejection
                # of a separately proven PREIMAGE Candidate. No generic
                # "rc4 means retry" rule: exact Driver/trace/checkpoint,
                # successful native file_change, source snapshot and other
                # completed workers are all rechecked read-only.
                envelope_rc, envelope = _probe(
                    env, "scripts/storyos_preimage_host_envelope_rc4_readonly.py",
                    ["--episode", rel]
                )
                if (envelope_rc == 0
                        and envelope.get("status") ==
                            "PREIMAGE_RC4_HOST_ENVELOPE_RECOVERABLE"
                        and envelope.get("driver_record_sha256") ==
                            exit_remediation.canonical_sha(driver.get("record") or {})):
                    restartable = True
                    driver_recovery = {
                        "status": "PREIMAGE_RC4_HOST_ENVELOPE_RECOVERABLE",
                        "driver_record_sha256": envelope["driver_record_sha256"],
                        "candidate_sha256": envelope["candidate_sha256"],
                        "recovery_action": "HOST_SEAL_WITHOUT_NEW_MODEL",
                        "read_only": True,
                        "production_authorization": False,
                    }
                else:
                    driver_recovery = {
                        "status": envelope.get("status") or
                                  "PREIMAGE_RC4_ENVELOPE_UNVERIFIED",
                        "read_only": True, "production_authorization": False,
                    }
            if not restartable:
                # The old scoped VISUAL_LOCK text worker may have returned 0
                # without creating a plan, any image, or independent pixel
                # review. Permit only this exact newest rc4 with matching
                # checkpoint/trace/Driver proof; do not grant image entitlement.
                visual_rc4_rc, visual_rc4 = _probe(
                    env, "scripts/storyos_visual_lock_rc4_readonly.py",
                    ["--episode", rel]
                )
                if (visual_rc4_rc == 0
                        and visual_rc4.get("status") ==
                            "VISUAL_LOCK_RC4_MISSING_HOST_PLAN_RECOVERABLE"
                        and visual_rc4.get("driver_record_sha256") ==
                            exit_remediation.canonical_sha(driver.get("record") or {})):
                    restartable = True
                    driver_recovery = {
                        "status": "VISUAL_LOCK_RC4_MISSING_HOST_PLAN_RECOVERABLE",
                        "driver_record_sha256": visual_rc4["driver_record_sha256"],
                        "recovery_action": "HOST_FOUR_FRAME_PLAN_THEN_REAL_PIXELS",
                        "read_only": True,
                        "production_authorization": False,
                    }
                else:
                    driver_recovery = {
                        "status": visual_rc4.get("status") or
                                  "VISUAL_LOCK_RC4_UNVERIFIED",
                        "read_only": True,
                        "production_authorization": False,
                    }
            if not restartable:
                # Latest rc4 can be only a derived Frame Contract index stale
                # at deterministic PROMPT_AUTHORING. Read-only proof checks
                # exact Driver/last checkpoint/trace and every old->new SHA
                # before allowing explicit manual start. This is not a paid
                # image capability attestation or a generic rc4 retry.
                prompt_rc, prompt_proof = _probe(
                    env, "scripts/storyos_prompt_contract_rc4_readonly.py",
                    ["--episode", rel]
                )
                if (prompt_rc == 0
                        and prompt_proof.get("status") ==
                        "PROMPT_RC4_PREIMAGE_VISUAL_INDEX_REBIND_RECOVERABLE"
                        and prompt_proof.get("driver_record_sha256") ==
                        exit_remediation.canonical_sha(driver.get("record") or {})):
                    restartable = True
                    driver_recovery = {
                        "status": "PROMPT_RC4_PREIMAGE_VISUAL_INDEX_REBIND_RECOVERABLE",
                        "driver_record_sha256": prompt_proof["driver_record_sha256"],
                        "recovery_action": "REBUILD_EQUIVALENT_48_CONTRACTS_IN_EXPLICIT_DRIVER",
                        "read_only": True,
                        "production_authorization": False,
                    }
                else:
                    driver_recovery = {
                        "status": prompt_proof.get("status") or
                                  "PROMPT_CONTRACT_RC4_UNVERIFIED",
                        "read_only": True,
                        "production_authorization": False,
                    }
        if (not restartable and rc == 0
                and driver.get("driver_state") == "EXITED"
                and driver.get("exit_code") == "4"
                and driver.get("liveness") == "DEAD"
                and driver.get("pid") == 0
                and isinstance(driver.get("record"), dict)
                and driver["record"].get("log")
                and stage.get("status") == "STAGE_ELIGIBLE"
                and attempts.get("status") == "ATTEMPT_HISTORY_READ_ONLY"
                and not attempts.get("outcome_unknown_assets")
                and not attempts.get("active_attempt_assets")):
            # Exactly the latest Visual Lock F001 predispatch block after an
            # independently attested one-shot rearm. Never a general rc4 retry.
            baseline_rc, baseline_proof = _probe(
                env, "scripts/storyos_visual_lock_baseline_rearm_rc4_readonly.py",
                ["--episode", rel]
            )
            if (baseline_rc == 0 and baseline_proof.get("status") ==
                    "VISUAL_LOCK_RC4_VERIFIED_F001_PREDISPATCH_REARM_RECOVERABLE"
                    and baseline_proof.get("driver_record_sha256") ==
                    exit_remediation.canonical_sha(driver.get("record") or {})):
                restartable = True
                driver_recovery = {
                    "status": baseline_proof["status"],
                    "driver_record_sha256": baseline_proof["driver_record_sha256"],
                    "f001_queue_item_id": baseline_proof["f001_queue_item_id"],
                    "f001_reattest_proof_sha256": baseline_proof["f001_reattest_proof_sha256"],
                    "recovery_action": "CANONICAL_VISUAL_LOCK_F001_ONLY",
                    "read_only": True,
                    "production_authorization": False,
                }
        if (not restartable and rc == 0
                and driver.get("driver_state") == "EXITED"
                and driver.get("exit_code") == "24"
                and driver.get("pid") == 0
                and driver.get("liveness") == "DEAD"
                and stage.get("status") == "STAGE_ELIGIBLE"
                and attempts.get("status") == "ATTEMPT_HISTORY_READ_ONLY"
                and not attempts.get("outcome_unknown_assets")
                and not attempts.get("active_attempt_assets")):
            # An explicitly acknowledged *lost local provenance* disposition
            # may settle the old paid UNKNOWN as a local acceptance failure.
            # Never silently reclassify it; this exact one-shot MySQL ack,
            # matching archived bytes, four-frame queue and rc24 must re-prove.
            disp_rc, disp = _probe(
                env, "episodes/_system/f001_unknown_operator_disposition.py",
                ["--episode", rel, "--verify-rearmed"])
            if (disp_rc == 0 and disp.get("status") ==
                    "VISUAL_LOCK_RC24_OPERATOR_DISPOSITION_REARM_RECOVERABLE"
                    and disp.get("driver_record_sha256") ==
                        exit_remediation.canonical_sha(driver.get("record") or {})):
                restartable = True
                driver_recovery = {
                    "status": disp["status"],
                    "driver_record_sha256": disp["driver_record_sha256"],
                    "receipt_sha256": disp["receipt_sha256"],
                    "item_id": disp["item_id"],
                    "recovery_action": "CANONICAL_VISUAL_LOCK_ATTEMPT_2_ONLY",
                    "read_only": True,
                    "production_authorization": False,
                }
        if (not restartable and rc == 0
                and driver.get("driver_state") == "EXITED"
                and driver.get("exit_code") == "24"
                and driver.get("pid") == 0
                and driver.get("liveness") == "DEAD"
                and stage.get("status") == "STAGE_ELIGIBLE"
                and attempts.get("status") == "ATTEMPT_HISTORY_READ_ONLY"
                and not attempts.get("outcome_unknown_assets")
                and not attempts.get("active_attempt_assets")):
            proof_rc, proof = _probe(
                env, "episodes/_system/f001_attempt2_native_raw_reconcile.py",
                ["--episode", rel, "--verify-rearmed"])
            if (proof_rc == 0
                and proof.get("status") ==
                    "VISUAL_LOCK_RC24_F001_ATTEMPT2_RECONCILED_RECOVERABLE"
                and proof.get("driver_record_sha256") ==
                    exit_remediation.canonical_sha(driver.get("record") or {})):
                restartable = True
                driver_recovery = {
                    "status": proof["status"],
                    "driver_record_sha256": proof["driver_record_sha256"],
                    "receipt_sha256": proof["runner_receipt_sha256"],
                    "candidate_sha256": proof["candidate_sha256"],
                    "item_id": proof["item_id"],
                    "recovery_action": "RESUME_REVIEW_VERIFIED_F001_NO_NEW_GENERATION",
                    "read_only": True,
                    "production_authorization": False,
                }
        if (not restartable and rc == 0
                and driver.get("driver_state") == "EXITED"
                and driver.get("exit_code") == "22"
                and driver.get("pid") == 0
                and driver.get("liveness") == "DEAD"
                and stage.get("status") == "STAGE_ELIGIBLE"
                and attempts.get("status") == "ATTEMPT_HISTORY_READ_ONLY"
                and not attempts.get("outcome_unknown_assets")
                and not attempts.get("active_attempt_assets")):
            # Source-fenced F001 independent PASS, exact rc22 and old FAIL audit.
            proof_rc, proof = _probe(
                env, "episodes/_system/f001_independent_baseline_pass_cas.py",
                ["--episode", rel, "--verify-rearmed"])
            if (proof_rc == 0
                and proof.get("status") ==
                    "VISUAL_LOCK_RC22_F001_INDEPENDENT_PASS_RECOVERABLE"
                and proof.get("driver_record_sha256") ==
                    exit_remediation.canonical_sha(driver.get("record") or {})):
                restartable = True
                driver_recovery = {
                    "status": proof["status"],
                    "driver_record_sha256": proof["driver_record_sha256"],
                    "review_sha256": proof["review_sha256"],
                    "candidate_sha256": proof["candidate_sha256"],
                    "old_review_sha256": proof["old_review_sha256"],
                    "recovery_action": "RESUME_DEPENDENT_VISUAL_LOCK_3_NO_F001_GENERATION",
                    "read_only": True, "production_authorization": False,
                }
        if (not restartable and rc == 0
                and driver.get("driver_state") == "EXITED"
                and driver.get("exit_code") == "24"
                and driver.get("liveness") == "DEAD"
                and driver.get("pid") == 0
                and stage.get("status") == "STAGE_ELIGIBLE"
                and attempts.get("status") == "ATTEMPT_HISTORY_READ_ONLY"
                and not attempts.get("outcome_unknown_assets")
                and not attempts.get("active_attempt_assets")):
            # Strict F045 raw-source ratio correction following a single
            # existing paid image. The PNG/receipt/typed ledger and all 4
            # Visual Lock queue rows are verified; no new frame-45 Attempt.
            f045_rc, f045 = _probe(
                env, "episodes/_system/f045_raw_verified_rc24_rearm.py",
                ["--episode", rel, "--verify-rearmed"])
            if (f045_rc == 0
                and f045.get("status") ==
                    "VISUAL_LOCK_RC24_F045_RAW_RATIO_RECOVERED"
                and f045.get("driver_record_sha256") ==
                    exit_remediation.canonical_sha(driver.get("record") or {})):
                restartable = True
                driver_recovery = {
                    "status": f045["status"],
                    "driver_record_sha256": f045["driver_record_sha256"],
                    "f045_candidate_sha256": f045["f045_candidate_sha256"],
                    "f045_raw_sha256": f045["f045_raw_sha256"],
                    "f005_candidate_sha256": f045["f005_candidate_sha256"],
                    "f047_candidate_sha256": f045["f047_candidate_sha256"],
                    "recovery_action": "RESUME_REVIEW_EXISTING_VISUAL_LOCK_PIXELS",
                    "read_only": True,
                    "production_authorization": False,
                }
        if (not restartable and rc == 0
                and driver.get("driver_state") == "EXITED"
                and driver.get("exit_code") == "22"
                and driver.get("pid") == 0
                and driver.get("liveness") == "DEAD"
                and stage.get("status") == "STAGE_ELIGIBLE"
                and attempts.get("status") == "ATTEMPT_HISTORY_READ_ONLY"
                and not attempts.get("outcome_unknown_assets")
                and not attempts.get("active_attempt_assets")):
            # Existing *actual-pixel FAIL* authorizes exactly three previously
            # blocked content repairs. Never generate F001 or bypass the
            # subsequent native visibility / MySQL paid Attempt fences.
            proof_rc, proof = _probe(
                env,"episodes/_system/production_ep14_visual_repair.py",
                ["--episode",rel,"--verify-rearmed"])
            if (proof_rc == 0
                and proof.get("status") == "VISUAL_LOCK_RC22_EP14_REPAIR_REARMED"
                and proof.get("driver_record_sha256") ==
                    exit_remediation.canonical_sha(driver.get("record") or {})):
                restartable = True
                driver_recovery = {
                    "status":proof["status"],
                    "driver_record_sha256":proof["driver_record_sha256"],
                    "review_sha256":proof["review_sha256"],
                    "repair_queue_sha256":proof["repair_queue_sha256"],
                    "recovery_action":"RESUME_THREE_REVIEWED_REPAIRS_NO_F001_IMAGE",
                    "read_only":True,"production_authorization":False,
                }
        if (not restartable and rc == 0
                and driver.get("driver_state")=="EXITED"
                and str(driver.get("exit_code"))=="22"
                and driver.get("pid")==0
                and driver.get("liveness")=="DEAD"
                and stage.get("status")=="STAGE_ELIGIBLE"
                and attempts.get("status")=="ATTEMPT_HISTORY_READ_ONLY"
                and not attempts.get("outcome_unknown_assets")
                and not attempts.get("active_attempt_assets")):
            # Four real exhausted Visual Lock pixels have auditable WEAK_PASS
            # (independent Vision FAIL retained), with all extra predispatch
            # candidates superseded. This does not grant any third paid image.
            weak_rc,weak=_probe(
                env,"episodes/_system/production_ep14_exhausted_weakpass_reentry.py",
                ["--episode",rel,"--verify-rearmed"])
            if (weak_rc==0
                and weak.get("status")==
                    "VISUAL_LOCK_RC22_EP14_EXHAUSTED_WEAK_PASS_RECOVERABLE"
                and weak.get("driver_record_sha256")==
                    exit_remediation.canonical_sha(driver.get("record") or {})):
                restartable=True
                driver_recovery={
                    "status":weak["status"],
                    "driver_record_sha256":weak["driver_record_sha256"],
                    "queue_fingerprint":weak["queue_fingerprint"],
                    "candidate_sha256_by_frame":weak["candidate_sha256_by_frame"],
                    "recovery_action":"RESUME_AFTER_AUDITED_VISUAL_WEAK_PASS_NO_NEW_IMAGE",
                    "read_only":True,"production_authorization":False
                }
        if not restartable:
            blockers.append("EPISODE_DRIVER_OWNER_NOT_IDLE_OR_UNVERIFIED")
        if driver.get("driver_state") == "EXITED" and not restartable:
            blockers.append("EPISODE_DRIVER_EXIT_REQUIRES_REMEDIATION")
        if stage.get("stage") == "STORYBOARD_LOCKED":
            # A DAG may be safe to start without being eligible to finish.
            # This pure read-only advisory must NOT be promoted to image
            # entitlement, nor bypass the real image pixel/generation gates.
            visual_rc, visual_lock_admission = _probe(
                env, "scripts/storyos_visual_lock_readonly.py", ["--episode", rel]
            )
            if visual_rc != 0 or not isinstance(visual_lock_admission, dict):
                visual_lock_admission = {
                    "status": "BLOCKED",
                    "reason": "VISUAL_LOCK_READONLY_AUTHORITY_CHECK_FAILED",
                    "read_only": True,
                }
    # Test-only historical pixel evidence is useful diagnostics, not a
    # production Gateway permit or new-account entitlement attestation.
    try:
        import storyos_m00_native_evidence_readonly
        pixel_proof=storyos_m00_native_evidence_readonly.inspect(root=ROOT)
    except Exception:
        pixel_proof={"status":"IMAGE_TEST_PROOF_UNVERIFIED",
                     "production_authorization":False,
                     "can_dispatch_image":False}
    return {
        "production_admission":admission_summary(
            stage=stage,visual=visual_lock_admission,
            native_ready={"bridge_ok":native_ok,"mode_ok":mode_ok,
                          "model_client_version_ok":model_version_ok},
            blockers=blockers),
        "status": "READY_TO_START" if not blockers else "BLOCKED",
        "scope": "NATIVE_CODEX_FULL_AUTO",
        "production_mode": "CODEX_MANAGED",
        "image_executor": "CODEX",
        "orchestration": "CANONICAL_STORY_OS_DAG",
        "episode": episode.relative_to(ROOT).as_posix() if episode else None,
        "mysql": {
            "host": "127.0.0.1" if env.get("STORYOS_MYSQL_HOST") in
                    {"localhost", "127.0.0.1"} else "configured",
            "port": int(env["STORYOS_MYSQL_PORT"]),
            "schema_status": schema.get("status"),
            "schema_reason": schema.get("reason"),
        },
        "codex": {"bridge_ok": native_ok, "mode_ok": mode_ok,
                  "model_client_version_ok": model_version_ok,
                  "model_minimum_cli_version": model_readiness.get("minimum_cli_version"),
                  "model_policy_source": model_readiness.get("policy_source"),
                  "model_entitlement_verified": False,
                  "tool_generation_proven": False},
        "attempt": {"status": attempts.get("status"),
                    "outcome_unknown_assets": attempts.get("outcome_unknown_assets", []),
                    "active_attempt_assets": attempts.get("active_attempt_assets", [])},
        "driver_state": driver.get("driver_state") if episode else None,
        "driver_recovery": driver_recovery,
        # Read-only identity needed by the bounded autonomy watchdog. Never
        # promote a PID / heartbeat sample into a Writer fencing permit.
        "driver_evidence": {
            "driver_state": driver.get("driver_state"),
            "pid": driver.get("pid"),
            "liveness": driver.get("liveness"),
            "exit_code": driver.get("exit_code"),
        } if episode else {},
        "visual_lock_admission": visual_lock_admission,
        "test_only_native_pixel_evidence":pixel_proof,
        "creative_story_recovery": {
            "status": creative_recovery.get("status"),
            "contract_status": creative_recovery.get("contract_status"),
            "review_path_present": creative_recovery.get("review_path_present"),
            "model_success_receipt_count": creative_recovery.get("model_success_receipt_count"),
            "model_success_receipt_reuse_verified": False,
            "model_success_is_story_lock": False,
            "model_generation_required": None,
        } if episode else None,
        "episode_stage": {"status": stage.get("status"), "current_state": stage.get("stage"),
                          "source": stage.get("source")} if episode else None,
        "blockers": blockers,
        "read_only": True,
        "production_authorization": False,
        "model_calls": 0,
        "sql_writes": 0,
    }


def full_auto_command(args: argparse.Namespace, episode: Path | None) -> list[str]:
    """Reuse StoryOS, not a shadow scheduler or a freeform Codex subprocess."""
    cmd = [sys.executable, str(SYSTEM / "story_os.py")]
    if args.command == "run":
        cmd += ["run", str(episode), "--full-auto", "--resume"]
    elif args.command in {"start", "remediate-start"}:
        return [sys.executable, str(SYSTEM / "runtime_driver.py"), "start",
                str(episode), "--resume", "--json"]
    else:
        cmd += ["create", args.request_text, "--full-auto"]
        if args.title:
            cmd += ["--title", args.title]
        if args.visual_profile:
            cmd += ["--visual-profile", args.visual_profile]
    return cmd




def dispatch_remediated_start(
    env: dict[str, str], episode: Path, state: dict, expected: dict[str, str],
    *, kind: str = "source_binding",
) -> int:
    """Exceptional, explicit, single-use restart of one previously fixed 900 exit.

    The ordinary plan/start/watchdog still fail closed. The full independent
    canonical preflight must have exactly the two historical Driver blockers.
    """
    if (not exit_remediation.only_historical_exit_blockers(state.get("blockers") or [])
            or state.get("episode_stage", {}).get("status") != "STAGE_ELIGIBLE"
            or state.get("mysql", {}).get("schema_status") != "READY_FOR_FURTHER_ADMISSION"
            or state.get("attempt", {}).get("status") != "ATTEMPT_HISTORY_READ_ONLY"
            or state.get("attempt", {}).get("outcome_unknown_assets")
            or state.get("attempt", {}).get("active_attempt_assets")
            or not all(state.get("codex", {}).get(k) is True for k in
                       ("bridge_ok", "mode_ok", "model_client_version_ok"))):
        raise exit_remediation.RemediationDenied("INDEPENDENT_PRODUCTION_ADMISSION_BLOCKED")
    rel = episode.relative_to(ROOT).as_posix()
    source = ROOT / (
        "episodes/_system/next_action.py" if kind == "reviewed_repair_handoff"
        else "episodes/_system/vision_review_executor.py" if kind == "repair_wave_signature"
        else "episodes/_system/frame_semantic_review.py"
    )
    rc, driver = _probe(env, "episodes/_system/runtime_driver.py",
                        ["status", rel, "--json"])
    if rc != 0:
        raise exit_remediation.RemediationDenied("CANONICAL_DRIVER_READ_FAILED")
    summary = state.get("driver_evidence") or {}
    if any(driver.get(k) != summary.get(k) for k in
           ("driver_state", "pid", "liveness", "exit_code")):
        raise exit_remediation.RemediationDenied("PREFLIGHT_DRIVER_RECORD_DRIFT")
    if kind == "reviewed_repair_handoff":
        rc_action, action = _probe(env, "episodes/_system/next_action.py",
                                   ["show", rel])
        if (rc_action != 0 or not isinstance(action, dict)
                or action.get("action") != "MATERIALIZE_REPAIR_WAVE"
                or action.get("executor") != "CODEX_VISION"
                or action.get("hard_stop") is not False
                or action.get("auto_recoverable") is not True
                or int(action.get("attempt") or 0) != 1
                or not action.get("frames")):
            raise exit_remediation.RemediationDenied("FORMAL_REPAIR_HANDOFF_NOT_ADMISSIBLE")
    proof = exit_remediation.verify_exit(
        episode, driver, source=source, expected=expected, kind=kind)
    # Confirm exact identity once more immediately before O_EXCL reservation;
    # the native Driver owner lock remains the final double-start authority.
    rc, latest = _probe(env, "episodes/_system/runtime_driver.py",
                        ["status", rel, "--json"])
    if rc != 0:
        raise exit_remediation.RemediationDenied("DRIVER_REREAD_FAILED")
    again = exit_remediation.verify_exit(
        episode, latest, source=source, expected=expected, kind=kind)
    if again != proof:
        raise exit_remediation.RemediationDenied("DRIVER_REMEDIATION_RACE")
    if kind == "reviewed_repair_handoff":
        rc_action, latest_action = _probe(env, "episodes/_system/next_action.py",
                                         ["show", rel])
        if (rc_action != 0 or not isinstance(latest_action, dict)
                or latest_action.get("action") != "MATERIALIZE_REPAIR_WAVE"
                or latest_action.get("executor") != "CODEX_VISION"
                or latest_action.get("hard_stop") is not False
                or latest_action.get("auto_recoverable") is not True
                or int(latest_action.get("attempt") or 0) != 1
                or latest_action.get("frames") != action.get("frames")):
            raise exit_remediation.RemediationDenied("FORMAL_REPAIR_HANDOFF_DRIFT")
    ticket = exit_remediation.reserve_once(episode, proof)
    print(json.dumps({"remediation": "SINGLE_USE_RESERVED",
                      "receipt": ticket.relative_to(episode).as_posix(),
                      "exit_code": proof["exit_code"]}, ensure_ascii=False))
    return subprocess.call(
        full_auto_command(argparse.Namespace(command="remediate-start"), episode),
        cwd=ROOT, env=env)

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "run", "start"):
        option = sub.add_parser(name)
        option.add_argument("episode")
        if name in {"run", "start"}:
            option.add_argument("--ack-real-production", action="store_true")
    remedy = sub.add_parser("remediate-start")
    remedy.add_argument("episode")
    remedy.add_argument("--ack-real-production", action="store_true")
    remedy.add_argument("--remediation-kind", choices=("source_binding", "repair_wave_signature", "reviewed_repair_handoff"), default="source_binding")
    remedy.add_argument("--expected-driver-record-sha256", required=True)
    remedy.add_argument("--expected-crash-log-sha256", required=True)
    remedy.add_argument("--expected-fixed-source-sha256", required=True)
    create = sub.add_parser("create")
    create.add_argument("request_text")
    create.add_argument("--title")
    create.add_argument("--visual-profile")
    create.add_argument("--ack-real-production", action="store_true")
    args = parser.parse_args(argv)
    try:
        episode = canonical_episode(args.episode) if args.command != "create" else None
        env = native_environment()
        state = preflight(env, episode=episode)
        print(json.dumps(state, ensure_ascii=False, indent=2))
        if args.command == "plan":
            return 0 if state["status"] == "READY_TO_START" else 2
        if not args.ack_real_production:
            print("NATIVE_CODEX_REAL_PRODUCTION_ACK_REQUIRED", file=sys.stderr)
            return 2
        if args.command == "remediate-start":
            expected = {
                "driver_sha256": args.expected_driver_record_sha256,
                "log_sha256": args.expected_crash_log_sha256,
                "fix_sha256": args.expected_fixed_source_sha256,
            }
            try:
                return dispatch_remediated_start(env, episode, state, expected, kind=args.remediation_kind)
            except exit_remediation.RemediationDenied as error:
                print(str(error), file=sys.stderr)
                return 3
        if state["status"] != "READY_TO_START":
            print("NATIVE_CODEX_FULL_AUTO_BLOCKED_BY_AUTHORITY", file=sys.stderr)
            return 3
        valid_recoveries = {
            "HISTORICAL_STORY_RC4_SUPERSEDED_BY_VERIFIED_A15_PASS":
                "scripts/storyos_post_review_rc4_readonly.py",
            "STORY_RC4_APPROVED_CHARACTER_BINDING_RECOVERABLE":
                "scripts/storyos_character_rc4_readonly.py",
            "PREIMAGE_RC4_HOST_ENVELOPE_RECOVERABLE":
                "scripts/storyos_preimage_host_envelope_rc4_readonly.py",
            "VISUAL_LOCK_RC4_MISSING_HOST_PLAN_RECOVERABLE":
                "scripts/storyos_visual_lock_rc4_readonly.py",
            "PROMPT_RC4_PREIMAGE_VISUAL_INDEX_REBIND_RECOVERABLE":
                "scripts/storyos_prompt_contract_rc4_readonly.py",
            "VISUAL_LOCK_RC4_VERIFIED_F001_PREDISPATCH_REARM_RECOVERABLE":
                "scripts/storyos_visual_lock_baseline_rearm_rc4_readonly.py",
            "VISUAL_LOCK_RC24_OPERATOR_DISPOSITION_REARM_RECOVERABLE":
                "episodes/_system/f001_unknown_operator_disposition.py",
            "VISUAL_LOCK_RC24_F001_ATTEMPT2_RECONCILED_RECOVERABLE":
                "episodes/_system/f001_attempt2_native_raw_reconcile.py",
            "VISUAL_LOCK_RC22_F001_INDEPENDENT_PASS_RECOVERABLE":
                "episodes/_system/f001_independent_baseline_pass_cas.py",
            "VISUAL_LOCK_RC24_F045_RAW_RATIO_RECOVERED":
                "episodes/_system/f045_raw_verified_rc24_rearm.py",
            "VISUAL_LOCK_RC22_EP14_REPAIR_REARMED":
                "episodes/_system/production_ep14_visual_repair.py",
            "VISUAL_LOCK_RC22_EP14_EXHAUSTED_WEAK_PASS_RECOVERABLE":
                "episodes/_system/production_ep14_exhausted_weakpass_reentry.py",
        }
        recovery_status = (state.get("driver_recovery") or {}).get("status")
        if args.command in {"start", "run"} and recovery_status in valid_recoveries:
            # No separate reservation: the original explicit remediation
            # receipt already exists, and the actual Driver still owns its
            # double-start lock. Reconfirm this proof immediately before the
            # host performs its explicitly acknowledged dispatch.
            recovery_rc, latest = _probe(
                env, valid_recoveries[recovery_status],
                ["--episode", episode.relative_to(ROOT).as_posix()]
                + (["--verify-rearmed"] if recovery_status ==
                   "VISUAL_LOCK_RC24_OPERATOR_DISPOSITION_REARM_RECOVERABLE"
                   else ["--verify-rearmed"] if recovery_status ==
                   "VISUAL_LOCK_RC24_F001_ATTEMPT2_RECONCILED_RECOVERABLE"
                   else ["--verify-rearmed"] if recovery_status ==
                   "VISUAL_LOCK_RC22_F001_INDEPENDENT_PASS_RECOVERABLE"
                   else ["--verify-rearmed"] if recovery_status ==
                   "VISUAL_LOCK_RC24_F045_RAW_RATIO_RECOVERED"
                   else ["--verify-rearmed"] if recovery_status in {
                       "VISUAL_LOCK_RC22_EP14_REPAIR_REARMED",
                       "VISUAL_LOCK_RC22_EP14_EXHAUSTED_WEAK_PASS_RECOVERABLE"}
                   else [])
            )
            if (recovery_rc != 0 or latest.get("status") != recovery_status
                    or latest.get("driver_record_sha256") !=
                    state["driver_recovery"]["driver_record_sha256"]
                    or (recovery_status == "PREIMAGE_RC4_HOST_ENVELOPE_RECOVERABLE"
                        and latest.get("candidate_sha256") !=
                            state["driver_recovery"].get("candidate_sha256"))
                    or (recovery_status ==
                        "VISUAL_LOCK_RC24_F001_ATTEMPT2_RECONCILED_RECOVERABLE"
                        and (latest.get("runner_receipt_sha256") !=
                                 state["driver_recovery"].get("receipt_sha256")
                             or latest.get("candidate_sha256") !=
                                 state["driver_recovery"].get("candidate_sha256")
                             or latest.get("item_id") !=
                                 state["driver_recovery"].get("item_id")))
                    or (recovery_status ==
                        "VISUAL_LOCK_RC22_EP14_EXHAUSTED_WEAK_PASS_RECOVERABLE"
                        and (latest.get("queue_fingerprint") !=
                                state["driver_recovery"].get("queue_fingerprint")
                             or latest.get("candidate_sha256_by_frame") !=
                                state["driver_recovery"].get("candidate_sha256_by_frame")))
                    or (recovery_status ==
                        "VISUAL_LOCK_RC22_EP14_REPAIR_REARMED"
                        and (latest.get("review_sha256") !=
                                 state["driver_recovery"].get("review_sha256")
                             or latest.get("repair_queue_sha256") !=
                                 state["driver_recovery"].get("repair_queue_sha256")))
                    or (recovery_status ==
                        "VISUAL_LOCK_RC24_F045_RAW_RATIO_RECOVERED"
                        and any(latest.get(field) !=
                                state["driver_recovery"].get(field)
                                for field in ("f045_candidate_sha256",
                                              "f045_raw_sha256",
                                              "f005_candidate_sha256",
                                              "f047_candidate_sha256")))
                    or (recovery_status ==
                        "VISUAL_LOCK_RC22_F001_INDEPENDENT_PASS_RECOVERABLE"
                        and (latest.get("review_sha256") !=
                             state["driver_recovery"].get("review_sha256")
                             or latest.get("candidate_sha256") !=
                             state["driver_recovery"].get("candidate_sha256")
                             or latest.get("old_review_sha256") !=
                             state["driver_recovery"].get("old_review_sha256")))
                    or (recovery_status ==
                        "VISUAL_LOCK_RC24_OPERATOR_DISPOSITION_REARM_RECOVERABLE"
                        and (latest.get("receipt_sha256") !=
                                 state["driver_recovery"].get("receipt_sha256")
                             or latest.get("item_id") !=
                                 state["driver_recovery"].get("item_id")))
                    or (recovery_status ==
                        "VISUAL_LOCK_RC4_VERIFIED_F001_PREDISPATCH_REARM_RECOVERABLE"
                        and (latest.get("f001_queue_item_id") !=
                                 state["driver_recovery"].get("f001_queue_item_id")
                             or latest.get("f001_reattest_proof_sha256") !=
                                 state["driver_recovery"].get(
                                     "f001_reattest_proof_sha256")))):
                print("HISTORICAL_STORY_RC4_AUTHORITY_CHANGED_BEFORE_START",
                      file=sys.stderr)
                return 3
        return subprocess.call(full_auto_command(args, episode), cwd=ROOT, env=env)
    except (ValueError, OSError) as exc:
        # Print only fixed internal admission error codes, never credentials.
        code = str(exc)
        print(code if code.startswith("NATIVE_CODEX_") else "NATIVE_CODEX_PREFLIGHT_FAILED",
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
