#!/usr/bin/env python3
"""Read-only native Codex CLI flag probe. Never runs `codex exec` against a model.

This checks syntax support, not user login, model access, attachments or
filesystem isolation. On Windows the current StoryOS runner can use full access.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

VERSION_RE = re.compile(r"^(?:codex|codex-cli) \d+\.\d+\.\d+(?:[-+][\w.-]+)?$")
REQUIRED_FLAGS = ("--ephemeral", "--skip-git-repo-check", "--json", "--sandbox")


def executable_fingerprint(executable: str | None) -> str | None:
    """Non-secret stable digest of the resolved local binary, never its path."""
    if not isinstance(executable, str) or not executable.strip():
        return None
    path = os.path.normcase(os.path.realpath(os.path.abspath(executable)))
    return hashlib.sha256(path.encode("utf-8", errors="replace")).hexdigest()


def inspect_cli(executable: str, *, platform_name: str | None = None) -> dict:
    name = platform_name or os.name
    values = []
    for argv in ((executable, "--version"), (executable, "exec", "--help")):
        result = subprocess.run(list(argv), capture_output=True, text=True,
                                check=False, timeout=15)
        if result.returncode != 0:
            return {"status": "CLI_PROBE_FAILED", "runtime_model_calls": 0,
                    "command_only": True, "native_credential_check": False,
                    "filesystem_isolation_verified": False}
        values.append(result.stdout)
    version = values[0].strip()
    help_text = values[1]
    flags = {f: f in help_text for f in REQUIRED_FLAGS}
    flags["-C"] = bool(re.search(r"\-C,\s*\-\-cd\b", help_text))
    return {
        "status": "CLI_FLAGS_SUPPORTED" if VERSION_RE.fullmatch(version)
                  and all(flags.values()) else "CLI_FLAGS_INCOMPLETE",
        "version": version if VERSION_RE.fullmatch(version) else "INVALID_VERSION",
        "executable_fingerprint": executable_fingerprint(executable),
        "flags": flags,
        "command_only": True,
        "runtime_model_calls": 0,
        "native_credential_check": False,
        "filesystem_isolation_verified": False,
        "episode_cwd_is_security_boundary": False,
        "windows_critic_default_sandbox_full_access": name == "nt",
        "note": "No model is started; -C only sets working directory. Windows default full-access Critic execution is not a filesystem sandbox.",
    }


def inspect_storyos_bridge(*, health_provider=None) -> dict:
    """Check interactive-user Runner presence without emitting identity or secrets.

    This is only a health/auth-presence probe; no model dispatch or log-in.
    """
    if health_provider is None:
        system = str(Path(__file__).resolve().parents[1] / "episodes" / "_system")
        if system not in sys.path:
            sys.path.insert(0, system)
        import codex_user_runner
        health_provider = codex_user_runner.runner_health
    try:
        health = health_provider()
    except Exception:
        return {"status": "BRIDGE_UNAVAILABLE", "interactive_user": False,
                "auth_context_present": False, "model_execution_verified": False}
    present = (health.get("status") == "ok"
               and health.get("interactive_user") is True
               and health.get("codex_available") is True
               and health.get("codex_home_accessible") is True
               and health.get("codex_auth_present") is True)
    return {
        "status": "BRIDGE_AUTH_PRESENT" if present else "BRIDGE_AUTH_UNVERIFIED",
        "interactive_user": health.get("interactive_user") is True,
        "codex_available": health.get("codex_available") is True,
        "codex_home_accessible": health.get("codex_home_accessible") is True,
        "auth_context_present": health.get("codex_auth_present") is True,
        "model_execution_verified": False,
        "credentials_disclosed": False,
        "codex_version": health.get("codex_version"),
        "executable_fingerprint": executable_fingerprint(health.get("codex_executable")),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex", help="Native Codex path; defaults to system PATH")
    parser.add_argument("--bridge", action="store_true", help="inspect local interactive-user bridge health without model calls")
    args = parser.parse_args()
    path = args.codex or shutil.which("codex") or shutil.which("codex.cmd")
    if not path:
        print(json.dumps({"status": "CODEX_NOT_FOUND", "runtime_model_calls": 0}))
        return 2
    try:
        report = inspect_cli(path)
        if args.bridge:
            report["storyos_user_bridge"] = inspect_storyos_bridge()
    except (OSError, subprocess.TimeoutExpired):
        report = {"status": "CLI_PROBE_FAILED", "runtime_model_calls": 0}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    # When explicitly requested, bridge readiness must fail closed too.
    # A healthy local CLI belonging to the SYSTEM account is not evidence
    # that the interactive-user Runner can consume the review task.
    cli_ok = report.get("status") == "CLI_FLAGS_SUPPORTED"
    bridge_ok = (not args.bridge or (report.get("storyos_user_bridge") or {}).get("status") == "BRIDGE_AUTH_PRESENT")
    return 0 if cli_ok and bridge_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
