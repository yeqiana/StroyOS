#!/usr/bin/env python3
"""Production ledger CLI facade (Story OS B4 split).

Domain implementations moved to production_ledger_core (shared library),
production_ledger_run (runtime commands) and production_ledger_manage
(management commands). This facade keeps parser/main and re-exports the full
public surface so existing importers and CLI callers are unaffected.
"""
from __future__ import annotations

from production_ledger_core import *  # noqa: F401,F403  (full public library)
from production_ledger_run import (cmd_authorize_repair, cmd_begin,
    cmd_recover_success, cmd_restore_evidence_gap_review, cmd_review, cmd_success, cmd_tech_fail)
from production_ledger_manage import (cmd_accept_user_exception_candidate,
    cmd_accept_after_retry_exhaustion,
    force_pass_content_exhaustion,
    cmd_accept_user_contract_exception,
    cmd_audit, cmd_authorize_authority_refresh, cmd_authorize_user_continuation_repair, cmd_authorize_user_exception_repair,
    cmd_authorize_user_locked_repair, cmd_authorize_user_passed_repair,
    cmd_batch_begin, cmd_batch_end, cmd_init, cmd_lock, cmd_promote, cmd_show,
    mark_review_needs_user)

# ``frame_contract -> identity_continuity -> production_ledger`` creates a
# short bootstrap cycle.  During that cycle the implementation modules can
# receive a partial ``from production_ledger_core import *`` snapshot.  The
# core is complete by the time the facade reaches this point, so backfill any
# public core helpers that were not visible during the early import.  This is
# limited to missing names and does not alter the command API.
import production_ledger_core as _ledger_core
import production_ledger_run as _ledger_run
import production_ledger_manage as _ledger_manage
for _module in (_ledger_run, _ledger_manage):
    for _name, _value in vars(_ledger_core).items():
        if not _name.startswith("_") and _name not in _module.__dict__:
            setattr(_module, _name, _value)

# The facade itself can also be imported partially during the same bootstrap cycle
# (notably when this file is executed as the CLI script). Backfill its public core
# helpers after production_ledger_core is complete so downstream imports such as
# visual_lock_candidate_pool always see the canonical authority API.
for _name, _value in vars(_ledger_core).items():
    if not _name.startswith("_") and _name not in globals():
        globals()[_name] = _value
del _module, _name, _value, _ledger_core, _ledger_run, _ledger_manage


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Story OS V1.2 Production Engine ledger")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("init", help="initialize per-frame ledger; default canvas is 4:5 / 1080x1350")
    s.add_argument("episode_dir")
    s.add_argument("--frame-count", type=int)
    s.add_argument("--aspect-ratio", help="4:5 or 9:16; omitted => manifest, then default 4:5")
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("begin", help="record generation preflight and request fingerprint")
    s.add_argument("episode_dir")
    s.add_argument("--frame", required=True)
    s.add_argument("--kind", choices=["original", "repair", "baseline_candidate"], default="original")
    s.add_argument("--prompt")
    s.add_argument("--prompt-file")
    s.add_argument("--capture-id", required=True)
    s.add_argument("--model", default="default")
    s.add_argument("--quality", choices=["high"], default=DEFAULT_IMAGE_QUALITY)
    s.add_argument("--reference", action="append", help="PATH::ROLE::KIND, KIND=identity|prop|location|capture_style")
    s.add_argument("--notes", default="")
    s.add_argument("--batch-id", help="V2.4 Batch Runtime derived execution id")
    s.add_argument("--runtime-transaction-id", help="queue/ledger crash-recovery correlation id")
    s.add_argument("--production-revision-id", help="formal Episode production revision binding")
    s.add_argument("--allow-long-prompt", action="store_true")
    s.set_defaults(func=cmd_begin)

    s = sub.add_parser("success", help="record a generated candidate; dimensions must exactly match canvas")
    s.add_argument("episode_dir")
    s.add_argument("--frame", required=True)
    s.add_argument("--path", required=True)
    s.add_argument("--provider-receipt", help="provider RAW dimension receipt JSON")
    s.add_argument("--generation-key", help="immutable Generation Attempt key")
    s.add_argument("--generation-attempt-index", type=int, choices=[1, 2, 3])
    s.add_argument("--production-revision-id", help="formal Episode production revision binding")
    s.set_defaults(func=cmd_success)

    s = sub.add_parser("recover-success", help="correct an exact technical-failure transaction after durable runner success is recovered")
    s.add_argument("episode_dir")
    s.add_argument("--frame", required=True)
    s.add_argument("--path", required=True)
    s.add_argument("--provider-receipt")
    s.add_argument("--transaction-id", required=True)
    s.add_argument("--runner-request-id")
    s.add_argument("--recovery-reason", help="auditable correction reason; defaults to late durable user-runner success")
    s.set_defaults(func=cmd_recover_success)

    s = sub.add_parser("tech-fail", help="record network/timeout/no-candidate failure without consuming content repair")
    s.add_argument("episode_dir")
    s.add_argument("--frame", required=True)
    s.add_argument("--code", required=True)
    s.add_argument("--message", required=True)
    s.set_defaults(func=cmd_tech_fail)

    s = sub.add_parser("review", help="content review for ready candidate")
    s.add_argument("episode_dir")
    s.add_argument("--frame", required=True)
    s.add_argument("--decision", choices=["pass", "repair", "needs_user"], required=True)
    s.add_argument("--notes", default="")
    s.set_defaults(func=cmd_review)

    s = sub.add_parser("authorize-repair", help="explicitly authorize the single content repair round")
    s.add_argument("episode_dir")
    s.add_argument("--frame", required=True)
    s.add_argument("--note", required=True)
    s.add_argument("--delegated-auto", action="store_true", help="continuous-execution agent approval; does not claim direct user review")
    s.set_defaults(func=cmd_authorize_repair)

    s = sub.add_parser("authorize-user-locked-repair", help="reopen a locked frame for its first ordinary repair with direct user scope approval")
    s.add_argument("episode_dir")
    s.add_argument("--frame", required=True)
    s.add_argument("--approval-text", required=True)
    s.add_argument("--reason", required=True)
    s.set_defaults(func=cmd_authorize_user_locked_repair)

    s = sub.add_parser("authorize-user-passed-repair", help="reopen a PASSED pre-lock frame after a direct-user authority change")
    s.add_argument("episode_dir")
    s.add_argument("--frame", required=True)
    s.add_argument("--approval-text", required=True)
    s.add_argument("--reason", required=True)
    s.set_defaults(func=cmd_authorize_user_passed_repair)

    s = sub.add_parser("authorize-authority-refresh", help="reopen a ready/passed frame after direct-user authority or Frame Contract drift without consuming content repair budget")
    s.add_argument("episode_dir")
    s.add_argument("--frame", required=True)
    s.add_argument("--approval-text", required=True)
    s.add_argument("--reason", required=True)
    s.set_defaults(func=cmd_authorize_authority_refresh)

    s = sub.add_parser("authorize-user-exception-repair", help="record one direct-user exception after the ordinary repair hard-fails")
    s.add_argument("episode_dir")
    s.add_argument("--frame", required=True)
    s.add_argument("--approval-text", required=True)
    s.add_argument("--reason", required=True)
    s.set_defaults(func=cmd_authorize_user_exception_repair)

    s = sub.add_parser("authorize-user-continuation-repair", help="authorize exactly one additional candidate after an explicit user continue decision")
    s.add_argument("episode_dir")
    s.add_argument("--frame", required=True)
    s.add_argument("--approval-text", required=True)
    s.add_argument("--reason", required=True)
    s.set_defaults(func=cmd_authorize_user_continuation_repair)

    s = sub.add_parser("accept-user-exception-candidate", help="accept an existing NEEDS_USER visual candidate with direct user approval after a user-exception repair or exhausted bounded Visual Lock pool")
    s.add_argument("episode_dir")
    s.add_argument("--frame", required=True)
    s.add_argument("--approval-text", required=True)
    s.add_argument("--reason", required=True)
    s.set_defaults(func=cmd_accept_user_exception_candidate)

    s = sub.add_parser("accept-after-retry-exhaustion", help="record an explicit continuity acceptance after all bounded repair image attempts fail technically")
    s.add_argument("episode_dir")
    s.add_argument("--frame", required=True)
    s.add_argument("--reason", required=True)
    s.set_defaults(func=cmd_accept_after_retry_exhaustion)

    s = sub.add_parser("accept-user-contract-exception", help="accept an existing candidate under a direct-user-selected original Frame Contract")
    s.add_argument("episode_dir")
    s.add_argument("--frame", required=True)
    s.add_argument("--approval-text", required=True)
    s.add_argument("--reason", required=True)
    s.set_defaults(func=cmd_accept_user_contract_exception)

    s = sub.add_parser("restore-evidence-gap-review", help="restore a candidate incorrectly failed solely by an unavailable-input review")
    s.add_argument("episode_dir")
    s.add_argument("--frame", required=True)
    s.add_argument("--reason", required=True)
    s.set_defaults(func=cmd_restore_evidence_gap_review)

    s = sub.add_parser("promote", help="copy current passed candidate into production/approved without overwriting source")
    s.add_argument("episode_dir")
    s.add_argument("--frame", required=True)
    s.set_defaults(func=cmd_promote)

    s = sub.add_parser("lock", help="lock approved asset by SHA-256")
    s.add_argument("episode_dir")
    s.add_argument("--frame", required=True)
    s.add_argument("--reason", required=True)
    s.set_defaults(func=cmd_lock)

    s = sub.add_parser("batch-begin", help="open an auditable generation batch")
    s.add_argument("episode_dir")
    s.add_argument("--frames", action="append", required=True, help="e.g. 01-03 or 01,03,05")
    s.add_argument("--max-successes", type=int, default=3)
    s.add_argument("--note", default="")
    s.set_defaults(func=cmd_batch_begin)

    s = sub.add_parser("batch-end", help="close a generation batch")
    s.add_argument("episode_dir")
    s.add_argument("--batch-id", required=True)
    s.add_argument("--summary", default="")
    s.set_defaults(func=cmd_batch_end)

    s = sub.add_parser("audit", help="audit ledger invariants and asset hashes")
    s.add_argument("episode_dir")
    s.add_argument("--require-passed", action="store_true")
    s.set_defaults(func=cmd_audit)

    s = sub.add_parser("show")
    s.add_argument("episode_dir")
    s.add_argument("--frame")
    s.set_defaults(func=cmd_show)
    return p


def main() -> None:
    args = parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
