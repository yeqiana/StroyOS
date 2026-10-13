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
    commands = [[sys.executable, "-m", "pytest", "-q", *files, "--tb=short"]
                for files in selected.values()]
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
