#!/usr/bin/env python3
"""Native Frame01 ZERO-WRITE evidence preflight using canonical runtime.env.

No production CAS, Queue mutation, model call, attempt allocation or image
review. The canonical runtime launcher owns the MySQL environment contract.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys

import storyos_codex_managed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("episode_dir")
    args = parser.parse_args(argv)
    failure = {
        "status": "BLOCKED",
        "reason": "NATIVE_FRAME01_PREFLIGHT_UNAVAILABLE",
        "authorized_to_mutate_production": False,
        "sql_writes": 0,
        "model_calls": 0,
    }
    try:
        ep = storyos_codex_managed.canonical_episode(args.episode_dir)
        runtime = storyos_codex_managed.native_environment()
        command = [
            sys.executable,
            str(storyos_codex_managed.SYSTEM / "native_baseline_readonly_preflight.py"),
            str(ep),
        ]
        result = subprocess.run(
            command, cwd=storyos_codex_managed.ROOT, env=runtime,
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=120, check=False,
        )
        observed = json.loads(result.stdout)
        if isinstance(observed, dict) and result.returncode in (0, 2):
            # Fail closed if the child response isn't an explicit evidence
            # assessment; a zero exit is not itself production authorization.
            if (observed.get("authorized_to_mutate_production") is False
                    and observed.get("sql_writes") == 0
                    and observed.get("model_calls") == 0
                    and observed.get("status") in {
                        "READ_ONLY_EVIDENCE_READY_TEST_DB_STILL_REQUIRED",
                        "BLOCKED",
                    }):
                print(json.dumps(observed, ensure_ascii=False, sort_keys=True))
                return 0 if result.returncode == 0 and observed["status"] != "BLOCKED" else 2
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    # Child stderr, external host configuration, DSN and stack traces remain
    # private: only a generic non-authorizing failure is shown.
    print(json.dumps(failure, ensure_ascii=False, sort_keys=True))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
