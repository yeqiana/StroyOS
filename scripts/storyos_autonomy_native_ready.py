#!/usr/bin/env python3
"""Pure/read-only native Codex CLI + interactive Runner auth readiness.

Never starts 'codex exec' / invokes paid model. Auth context visibility is
not a model entitlement or an authorization for production.
"""
from __future__ import annotations

import json
import shutil
import subprocess

import storyos_codex_cli_readiness as readiness


def summarize(cli: dict, bridge: dict) -> dict:
    cli_ok = isinstance(cli, dict) and cli.get("status") == "CLI_FLAGS_SUPPORTED"
    bridge_ok = isinstance(bridge, dict) and bridge.get("status") == "BRIDGE_AUTH_PRESENT"
    cli_digest = cli.get("executable_fingerprint") if isinstance(cli, dict) else None
    bridge_digest = bridge.get("executable_fingerprint") if isinstance(bridge, dict) else None
    cli_version = cli.get("version") if isinstance(cli, dict) else None
    bridge_version = bridge.get("codex_version") if isinstance(bridge, dict) else None
    # A CLI on PATH is not proof the interactive Runner will execute THAT CLI.
    both_available = bool(cli_digest and bridge_digest and cli_version and bridge_version)
    route_match = (both_available and cli_digest == bridge_digest
                   and cli_version == bridge_version)
    # Keep backwards-compatible auth-presence semantics with missing optional
    # identity evidence, but explicit contradiction blocks even read-only readiness.
    route_contradiction = (bool(cli_digest and bridge_digest and cli_digest != bridge_digest)
                           or bool(cli_version and bridge_version and cli_version != bridge_version))
    return {
        "status": ("NATIVE_AUTH_CONTEXT_READY" if cli_ok and bridge_ok
                   and not route_contradiction else "BLOCKED"),
        "cli_runner_same_binary_verified": bool(route_match),
        "native_cli_flags_verified": cli_ok,
        "interactive_codex_auth_context_present": bridge_ok,
        "model_entitlement_verified": False,
        "real_image_generation_verified": False,
        "may_start_paid_production": False,
        "model_calls": 0,
        "sql_writes": 0,
        "opencodex_used": False,
        "admission": "READ_ONLY_EVIDENCE_NOT_PAID_CANARY",
    }


def shell_cli_login_status(executable: str, *, runner=subprocess.run) -> str:
    """Observe only this process's Codex login; never infer Runner entitlement."""
    try:
        check = runner([executable, "login", "status"], capture_output=True,
                       text=True, check=False, timeout=12)
    except (OSError, subprocess.TimeoutExpired):
        return "UNVERIFIED"
    message = (str(check.stdout or "") + " " + str(check.stderr or "")).casefold()
    if "not logged in" in message:
        return "NOT_LOGGED_IN"
    if check.returncode == 0 and "logged in" in message:
        return "LOGGED_IN"
    return "UNVERIFIED"


def report() -> dict:
    # Windows PowerShell codex.ps1 is not a CreateProcess binary. Prefer cmd.
    executable = (shutil.which("codex.cmd") or shutil.which("codex.exe")
                  or shutil.which("codex"))
    if not executable:
        return summarize({}, {})
    try:
        cli = readiness.inspect_cli(executable)
        bridge = readiness.inspect_storyos_bridge()
    except Exception:
        return summarize({}, {})
    result = summarize(cli, bridge)
    result["cli_version"] = str(cli.get("version") or "UNVERIFIED")
    result["shell_cli_login_status"] = shell_cli_login_status(executable)
    result["shell_cli_login_verified"] = result["shell_cli_login_status"] == "LOGGED_IN"
    return result


def main() -> int:
    observed = report()
    print(json.dumps(observed, ensure_ascii=False, sort_keys=True))
    return 0 if observed["status"] == "NATIVE_AUTH_CONTEXT_READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
