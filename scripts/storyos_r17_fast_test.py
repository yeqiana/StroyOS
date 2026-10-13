#!/usr/bin/env python3
"""R17 TEST_ONLY acceptance: never starts a production Driver or a paid image worker."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web-console"
AUTH = Path(os.environ.get("STORYOS_R17_MYSQL_TEST_AUTH", str(ROOT / ".storyos-tmp" / "r17-test-only" / "mysql-auth.json")))
NODE = Path("D:/soft/nvm-setup/nodejs/node.exe") if os.name == "nt" else Path("node")
TESTS = ROOT / "tests" / "platform"


def run(command: list[str], env: dict[str, str], cwd: Path = ROOT) -> None:
    printable = " ".join(Path(arg).name if "auth.json" in arg else arg for arg in command)
    print("R17_VERIFY_START", printable, flush=True)
    result = subprocess.run(command, cwd=cwd, env=env, check=False, timeout=120)
    if result.returncode:
        raise SystemExit(result.returncode)
    print("R17_VERIFY_PASS", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="R17 isolated contract fast/stress tests")
    parser.add_argument("--slot", choices=("mysql", "readonly", "browser-contract", "http", "all"), default="all")
    parser.add_argument("--stress", action="store_true", help="repeat isolated MySQL concurrency checks")
    args = parser.parse_args()
    env = dict(os.environ)
    if args.slot in ("mysql", "all"):
        if not AUTH.is_file():
            parser.error("TEST_ONLY MySQL credential file absent; do not fallback to production")
        env["STORYOS_R17_MYSQL_TEST_AUTH"] = str(AUTH)
        for _ in range(5 if args.stress else 1):
            run([sys.executable, "-m", "pytest", "-q",
                 str(TESTS / "test_r17_mysql_test_only_draft.py")], env)
    if args.slot in ("http", "all"):
        if not AUTH.is_file():
            parser.error("Dedicated TEST_ONLY MySQL credential file absent")
        env["STORYOS_R17_MYSQL_TEST_AUTH"] = str(AUTH)
        env["STORYOS_R17_PYTHON"] = sys.executable
        for _ in range(3 if args.stress else 1):
            run([str(NODE), str(WEB / "scripts" / "test-r17-real-mysql-api.mjs")], env, ROOT)
    if args.slot in ("readonly", "all"):
        run([sys.executable, "-m", "pytest", "-q",
             str(TESTS / "test_r16_readonly_persistence_boundary.py")], env)
    if args.slot in ("browser-contract", "all"):
        node = str(NODE)
        if not NODE.is_file() and os.name == "nt":
            parser.error("Node.js not found; cannot validate the browser contract")
        run([node, str(WEB / "scripts" / "test-r17-persistence-p0.mjs")], env, WEB)
        run([node, str(WEB / "scripts" / "test-r16-local-draft-backup-contract.mjs")], env, WEB)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
