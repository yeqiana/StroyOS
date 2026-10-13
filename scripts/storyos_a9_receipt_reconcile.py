#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R16: read-only, SHA-bound A9 paid-Codex receipt reconciliation.

No model dispatch, SQL mutation, candidate promotion, retry or ticket removal.
One A9 ticket is immutable, including on timeout, process kill and restart.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "episodes/_system"
if str(SYSTEM) not in sys.path:
    sys.path.insert(0, str(SYSTEM))
import story_review as review
import story_review_rubric_migration as migration
import codex_user_runner as runner

ALLOWED_RECEIPTS = 32


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def expected_prompt_sha(ep: Path) -> str:
    story, board = review.story_paths(ep)
    prompt = review.critic_prompt(ep, story, board, ep / review.CANDIDATE_REL, 9)
    return sha256((prompt + review.DIRECT_CODEX_EXECUTION_OVERRIDE).encode("utf-8"))


def classify_receipt(receipt: dict, *, prompt_sha256: str, root: Path) -> str:
    """Never treat an unbound or timed-out runner result as a model PASS."""
    if not isinstance(receipt, dict):
        return "RUNNER_RECEIPT_MALFORMED"
    proof = receipt.get("evidence")
    if not isinstance(proof, dict):
        return "RUNNER_RECEIPT_MALFORMED"
    rid = str(receipt.get("request_id") or "")
    if (not rid or proof.get("request_id") != rid
            or proof.get("task_type") != "critic"
            or proof.get("stdin_sha256") != prompt_sha256
            or proof.get("transport_route") != "native_codex"
            or Path(str(proof.get("working_directory") or "")).resolve() != root.resolve()):
        return "RUNNER_RECEIPT_NOT_SHA_BOUND"
    if (receipt.get("returncode") != proof.get("returncode")
            or type(receipt.get("returncode")) is not int
            or type(proof.get("timed_out")) is not bool):
        return "RUNNER_RECEIPT_CONTRADICTORY"
    try:
        output = base64.b64decode(str(receipt.get("output_base64") or ""), validate=True)
        if (sha256(output) != receipt.get("output_sha256")
                or len(output) != receipt.get("output_bytes")):
            return "RUNNER_OUTPUT_INTEGRITY_INVALID"
    except (ValueError, TypeError):
        return "RUNNER_OUTPUT_INTEGRITY_INVALID"
    if proof["timed_out"] is True or receipt["returncode"] == 124:
        return "PAID_CRITIC_TIMEOUT_NO_AUTORETRY"
    if receipt["returncode"] != 0:
        return "PAID_CRITIC_FAILED_NO_AUTORETRY"
    return "RUNNER_SUCCEEDED_REQUIRES_CANONICAL_FINALIZATION"


def decide(*, epoch_present: bool, candidate: dict | None,
           candidate_exists: bool, evidence_status: str,
           official_review_present: bool) -> dict:
    base = {
        "read_only": True, "model_calls": 0, "sql_writes": 0,
        "can_dispatch_model": False, "may_retry_attempt_9": False,
        "can_dispatch_image": False, "may_start_driver": False,
        "can_mark_review_pass": False, "can_publish": False,
        "review_attempt": 9,
    }
    if official_review_present:
        # The official review must be verified by the canonical MySQL lane;
        # seeing a local review file is never a proof of a new PASS.
        return {**base, "status": "OFFICIAL_REVIEW_NEEDS_CANONICAL_VALIDATION"}
    if not epoch_present:
        return {**base, "status": "A9_TICKET_ABSENT"}
    if evidence_status in {"PAID_CRITIC_TIMEOUT_NO_AUTORETRY",
                           "PAID_CRITIC_FAILED_NO_AUTORETRY"}:
        return {**base, "status": evidence_status,
                "candidate_present": candidate_exists,
                "candidate_declared_pass": ((candidate.get("summary") or {}).get("passed")
                                            if isinstance(candidate, dict) else None),
                "next_step": "RECONCILE_ONE_SHOT_ATTEMPT_9_NO_MODEL_RETRY"}
    if evidence_status == "RUNNER_SUCCEEDED_REQUIRES_CANONICAL_FINALIZATION":
        return {**base, "status": evidence_status,
                "candidate_present": candidate_exists,
                "next_step": "VALIDATE_RUNNER_OUTPUT_AND_CANDIDATE_BEFORE_FINALIZATION"}
    if not candidate_exists:
        return {**base, "status": "A9_OUTCOME_UNKNOWN_NO_CANDIDATE"}
    if not isinstance(candidate, dict):
        return {**base, "status": "A9_CANDIDATE_INVALID_RECONCILE"}
    if (candidate.get("summary") or {}).get("passed") is False:
        return {**base, "status": "A9_FAIL_CANDIDATE_UNATTESTED"}
    return {**base, "status": "A9_UNVERIFIED_CANDIDATE_RECONCILE"}


def canonical_a9_review_verified(ep: Path) -> bool:
    """Only independent, SHA-bound MySQL Story Review PASS unlocks the DAG."""
    try:
        report = review.load_review(ep)
        prov = report.get("critic_provenance") if isinstance(report, dict) else {}
        if (not isinstance(prov, dict)
                or prov.get("attempt") != 9
                or prov.get("review_scope") != migration.REVIEW_SCOPE
                or (report.get("summary") or {}).get("passed") is not True):
            return False
        return migration.validate_epoch(ep, prov) and not review.verify(ep)
    except Exception:
        return False


def inspect(episode: Path, *, root: Path = ROOT) -> dict:
    base = decide(epoch_present=True,candidate=None,candidate_exists=False,
                  evidence_status="UNKNOWN",official_review_present=False)
    try:
        root = root.resolve()
        ep = episode.resolve()
        if (not ep.is_relative_to(root / "episodes")
                or ep.is_symlink() or not ep.is_dir()):
            return {**base, "status": "EPISODE_PATH_UNVERIFIED"}
        ticket = ep / migration.EPOCH_REL
        if not ticket.is_file():
            return {**base,"status":"A9_TICKET_ABSENT"}
        stamp = json.loads(ticket.read_text(encoding="utf-8-sig"))
        if (stamp.get("schema") != "storyos.story_review_migrated_rubric_epoch.v1"
                or stamp.get("global_review_attempt") != 9
                or stamp.get("review_scope") != migration.REVIEW_SCOPE):
            return {**base,"status":"A9_TICKET_INVALID"}
        if canonical_a9_review_verified(ep):
            return {**base,"status":"CANONICAL_A9_PASS_VERIFIED",
                    "episode":ep.relative_to(root).as_posix(),
                    "may_start_driver":True}
        prompt_sha = expected_prompt_sha(ep)
        results_dir = root / runner.RUNTIME_REL / runner.RESULT_DIR_NAME
        possible = []
        if results_dir.is_dir():
            # Only results newer than the immutable A9 ticket can match.
            for path in results_dir.glob("*.json"):
                if path.stat().st_mtime + 30 >= ticket.stat().st_mtime:
                    possible.append(path)
        if len(possible) > ALLOWED_RECEIPTS:
            return {**base,"status":"RUNNER_RECEIPT_DISCOVERY_AMBIGUOUS"}
        matches = []
        for path in possible:
            try:
                row = json.loads(path.read_text(encoding="utf-8-sig"))
                status = classify_receipt(row,prompt_sha256=prompt_sha,root=root)
                if status != "RUNNER_RECEIPT_NOT_SHA_BOUND":
                    # Do not silently dismiss corrupt evidence claiming an A9
                    # input hash; demand manual reconciliation.
                    if status != "RUNNER_RECEIPT_MALFORMED":
                        matches.append((path.name,status))
            except (OSError, ValueError, TypeError):
                continue
        if len(matches) > 1:
            return {**base, "status":"MULTIPLE_A9_RECEIPTS_REQUIRE_RECONCILIATION"}
        evidence_status = matches[0][1] if matches else "RUNNER_RECEIPT_MISSING"
        candidate_path = ep / review.CANDIDATE_REL
        candidate_exists = candidate_path.is_file()
        try:
            candidate = (json.loads(candidate_path.read_text(encoding="utf-8-sig"))
                         if candidate_exists else None)
        except (OSError, ValueError):
            candidate = None
        # The real official Review authority is in MySQL, and is intentionally
        # not synthesized from historical disk JSON or a candidate.
        result = decide(epoch_present=True,candidate=candidate,
                        candidate_exists=candidate_exists,
                        evidence_status=evidence_status,
                        official_review_present=False)
        return {**result,"episode":ep.relative_to(root).as_posix(),
                "runner_evidence_status":evidence_status,
                "runner_receipt_count":len(matches),
                "candidate_valid_json":isinstance(candidate,dict),
                "log_nonempty":(ep/"meta/story-critic-attempt-9.jsonl").stat().st_size>0
                    if (ep/"meta/story-critic-attempt-9.jsonl").is_file() else False}
    except Exception as exc:
        return {**base, "status":"A9_READ_ONLY_EVIDENCE_UNAVAILABLE",
                "failure_kind":type(exc).__name__}


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episode",required=True)
    args=parser.parse_args(argv)
    episode=(ROOT/args.episode).resolve()
    report=inspect(episode)
    print(json.dumps(report,ensure_ascii=False,sort_keys=True))
    return 0 if report["status"] in {
        "PAID_CRITIC_TIMEOUT_NO_AUTORETRY","PAID_CRITIC_FAILED_NO_AUTORETRY",
        "RUNNER_SUCCEEDED_REQUIRES_CANONICAL_FINALIZATION"} else 2


if __name__=="__main__":
    raise SystemExit(main())
