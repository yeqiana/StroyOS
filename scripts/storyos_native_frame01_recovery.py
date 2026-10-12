#!/usr/bin/env python3
"""Native Frame01 operator CLI: plan, full snapshot backup, gated recovery.

The authenticated TEST_ONLY MySQL authorization does not permit execute.
Execute requires a distinct real-production approval, sealed backup and fence.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

import storyos_codex_managed

VALID_ACTIONS = ("plan", "backup", "execute")


def _child_code() -> str:
    return (
        "import sys,json;"
        "from pathlib import Path;"
        "sys.path.insert(0,str(Path.cwd()/'episodes'/'_system'));"
        "import native_baseline_recovery_operator as op;"
        "a=json.loads(sys.stdin.read());"
        "ep=Path(a['episode']);"
        "v=(op.plan(ep) if a['action']=='plan' else "
        "op.backup(ep) if a['action']=='backup' else "
        "op.execute(ep,fencing_token=a['fencing_token'],"
        "evidence_sha256=a['evidence_sha256'],"
        "manifest=Path(a['backup_manifest']),"
        "manifest_sha256=a['backup_sha256'],"
        "approval_ticket=a['approval_ticket'],"
        "production_approval=__import__('os').environ.get(op.PRODUCTION_APPROVAL_ENV)));"
        "print(json.dumps(v,ensure_ascii=False))"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=VALID_ACTIONS)
    parser.add_argument("episode")
    parser.add_argument("--ack-real-production", action="store_true")
    parser.add_argument("--fencing-token", type=int)
    parser.add_argument("--evidence-sha256")
    parser.add_argument("--backup-manifest")
    parser.add_argument("--backup-sha256")
    parser.add_argument("--approval-ticket")
    args = parser.parse_args(argv)
    denial = {
        "status": "BLOCKED",
        "reason": "NATIVE_FRAME01_OPERATOR_ADMISSION_DENIED",
        "model_calls": 0,
    }
    if args.action == "execute":
        if (not args.ack_real_production
                or not all((args.fencing_token, args.evidence_sha256,
                            args.backup_manifest, args.backup_sha256,
                            args.approval_ticket))
                or os.environ.get("STORYOS_NATIVE_FRAME01_PRODUCTION_APPROVAL")
                    != "I_AUTHORIZE_OFFICIAL_FRAME01_ATTEMPT1_RECOVERY"):
            print(json.dumps(denial))
            return 2
    else:
        if args.ack_real_production:
            print(json.dumps(denial))
            return 2
    try:
        ep = storyos_codex_managed.canonical_episode(args.episode)
        env = storyos_codex_managed.native_environment()
        params = {
            "action": args.action,
            "episode": str(ep),
            "fencing_token": args.fencing_token,
            "evidence_sha256": args.evidence_sha256,
            "backup_manifest": args.backup_manifest,
            "backup_sha256": args.backup_sha256,
            "approval_ticket": args.approval_ticket,
        }
        result = subprocess.run(
            [sys.executable, "-c", _child_code()],
            input=json.dumps(params), cwd=storyos_codex_managed.ROOT,
            env=env, capture_output=True, encoding="utf-8", errors="replace",
            text=True, check=False, timeout=180,
        )
        observed = json.loads(result.stdout)
        allowed = {
            "plan": "PLAN_ONLY_PRODUCTION_WRITE_NOT_AUTHORIZED",
            "backup": "SEALED_READ_ONLY_BACKUP_NOT_PRODUCTION_AUTHORIZATION",
            "execute": "FRAME01_RECONCILED_PENDING_INDEPENDENT_VISUAL_REVIEW",
        }
        if (result.returncode != 0 or not isinstance(observed, dict)
                or observed.get("status") != allowed[args.action]
                or observed.get("model_calls") != 0):
            raise ValueError("NATIVE_FRAME01_OPERATOR_CHILD_REJECTED")
        if args.action != "execute" and (
            observed.get("sql_writes") != 0
            or observed.get("authorized_to_mutate_production") is not False
        ):
            raise ValueError("NATIVE_FRAME01_OPERATOR_UNSAFE_CHILD_RESPONSE")
        if args.action == "execute" and (
            observed.get("visual_review_pass") is not False
            or observed.get("new_generation_attempts") != 0
            or observed.get("queue_reconciled") is not True
        ):
            raise ValueError("NATIVE_FRAME01_OPERATOR_UNSAFE_EXECUTE_RESPONSE")
        print(json.dumps(observed, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, ValueError, subprocess.TimeoutExpired):
        # Do not print passwords, raw SQL, Runner logs or child tracebacks.
        print(json.dumps(denial))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
