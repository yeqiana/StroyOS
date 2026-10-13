#!/usr/bin/env python3
"""Pure/read-only native Codex CLI + interactive Runner auth readiness.

Never starts 'codex exec' / invokes paid model. Auth context visibility is
not a model entitlement or an authorization for production.
"""
from __future__ import annotations

import json
import shutil

import storyos_codex_cli_readiness as readiness


def summarize(cli: dict, bridge: dict) -> dict:
    cli_ok = isinstance(cli, dict) and cli.get("status") == "CLI_FLAGS_SUPPORTED"
    bridge_ok = isinstance(bridge, dict) and bridge.get("status") == "BRIDGE_AUTH_PRESENT"
    return {
        "status": "NATIVE_AUTH_CONTEXT_READY" if cli_ok and bridge_ok else "BLOCKED",
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
    return result


def main() -> int:
    observed = report()
    print(json.dumps(observed, ensure_ascii=False, sort_keys=True))
    return 0 if observed["status"] == "NATIVE_AUTH_CONTEXT_READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
