#!/usr/bin/env python3
"""Reconcile ONE completed A10 native Codex FAIL without a new provider call.

Only a SHA-bound successful Runner receipt, completed JSONL, identical
candidate, and frozen source/epoch can authorize recording the real FAIL.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"episodes/_system"))
sys.path.insert(0, str(ROOT/"scripts"))

import codex_critic_runner as critic
import codex_user_runner as runner
import runtime_provenance
import story_review as review
import story_review_a10_source_revision as a10
import storyos_a9_receipt_reconcile as receipts


def inspect(ep: Path, *, root: Path = ROOT) -> tuple[dict, dict | None]:
    base = {"read_only":True,"model_calls":0,"sql_writes":0,
            "can_dispatch_image":False,"can_retry_attempt_10":False,
            "may_record_fail":False}
    try:
        ep = ep.resolve()
        root = root.resolve()
        if ep.relative_to(root).as_posix() != a10.EXPECTED_EPISODE:
            return {**base,"status":"EPISODE_OUT_OF_SCOPE"},None
        ticket_file = ep/a10.EPOCH_REL
        candidate_file = ep/a10.CANDIDATE_REL
        log_file = ep/"meta/story-critic-attempt-10.jsonl"
        if not all(x.is_file() for x in (ticket_file,candidate_file,log_file)):
            return {**base,"status":"A10_EVIDENCE_INCOMPLETE"},None
        stamp = json.loads(ticket_file.read_text("utf-8-sig"))
        if (stamp.get("global_review_attempt") != 10
                or stamp.get("review_scope") != a10.REVIEW_SCOPE):
            return {**base,"status":"A10_EPOCH_INVALID"},None
        if review.load_review(ep) is not None:
            return {**base,"status":"OFFICIAL_REVIEW_ALREADY_PRESENT"},None
        story,board = review.story_paths(ep)
        captions = ep/"docs/subtitles.yaml"
        if (not captions.is_file()
                or review.sha256_file(story)!=stamp.get("story_sha256")
                or review.sha256_file(board)!=stamp.get("storyboard_sha256")
                or review.sha256_file(captions)!=stamp.get("subtitle_source_sha256")
                or stamp.get("current_rubric_sha256") !=
                review._review_rubric_digest(Path(review.__file__).read_text("utf-8-sig"))):
            return {**base,"status":"SOURCE_OR_RUBRIC_CHANGED"},None
        prompt = review.critic_prompt(ep,story,board,candidate_file,10)
        prompt_sha=hashlib.sha256(
            (prompt+review.DIRECT_CODEX_EXECUTION_OVERRIDE).encode("utf-8")).hexdigest()
        folder = root/runner.RUNTIME_REL/runner.RESULT_DIR_NAME
        matching=[]
        for item in folder.glob("*.json"):
            if item.stat().st_mtime+30 < ticket_file.stat().st_mtime:
                continue
            row=json.loads(item.read_text("utf-8-sig"))
            proof=row.get("evidence") or {}
            if proof.get("stdin_sha256") == prompt_sha:
                matching.append(receipts.classify_receipt(
                    row,prompt_sha256=prompt_sha,root=root))
        if matching != ["RUNNER_SUCCEEDED_REQUIRES_CANONICAL_FINALIZATION"]:
            return {**base,"status":"RUNNER_RECEIPT_NOT_UNIQUELY_SUCCESSFUL",
                    "receipt_statuses":matching[:3]},None
        answer=critic.recover_completed_agent_json(log_file.read_text("utf-8-sig"))
        candidate=json.loads(candidate_file.read_text("utf-8-sig"))
        if not isinstance(answer,dict) or answer != candidate:
            return {**base,"status":"A10_CANDIDATE_NOT_COMPLETED_PROVIDER_OUTPUT"},None
        prov=runtime_provenance.build_critic_provenance(
            "CODEX",attempt=10,log=log_file.relative_to(root).as_posix(),
            allow_user_continuation_attempt=True)
        prov.update({k:v for k,v in stamp.items() if k in (
            "review_scope","review_epoch","epoch_attempt","current_rubric_sha256",
            "previous_storyboard_sha256","previous_a9_ticket_sha256",
            "previous_a9_candidate_sha256","subtitle_source_sha256")})
        if not a10.validate_epoch(ep,prov):
            return {**base,"status":"A10_PREDECESSOR_SHA_UNVERIFIED"},None
        payload=dict(candidate)
        payload.update({"schema_version":1,
                        "story_os_version":review.episode_contract_version(ep),
                        "story_sha256":review.sha256_file(story),
                        "storyboard_sha256":review.sha256_file(board),
                        "subtitle_source_sha256":prov["subtitle_source_sha256"],
                        "revision_count":9,"critic_provenance":prov})
        issues=review.validate_payload(payload,
            story_sha=review.sha256_file(story),
            storyboard_sha=review.sha256_file(board),
            version=review.episode_contract_version(ep))
        # A valid FAIL must have an actual failing hard check, and never
        # be promoted to PASS by an error-handling fallback.
        hard_failed=[k for k,v in (payload.get("hard_checks") or {}).items()
                     if v is False]
        if ((payload.get("summary") or {}).get("passed") is not False
                or not hard_failed or "DELETE_FRAME_TEST_FAIL" not in
                (payload.get("issue_codes") or [])):
            return {**base,"status":"A10_NOT_AUTHENTIC_KNOWN_FAIL"},None
        unexpected=[e for e in issues if not (
            e.startswith("hard_checks.") or
            "issue_codes" in e or "summary.passed" in e)]
        if unexpected:
            return {**base,"status":"A10_PAYLOAD_PROVENANCE_INVALID",
                    "validation_errors":unexpected[:8]},None
        return {**base,"status":"A10_PROVIDER_SUCCESS_REVIEW_FAIL",
                "review_attempt":10,"candidate_sha256":review.sha256_file(candidate_file),
                "issue_codes":payload.get("issue_codes"),
                "failed_hard_checks":hard_failed,"may_record_fail":True},payload
    except Exception as exc:
        return {**base,"status":"A10_EVIDENCE_UNAVAILABLE",
                "failure_kind":type(exc).__name__},None


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("episode")
    parser.add_argument("--record-verified-fail",action="store_true")
    opts=parser.parse_args(argv)
    ep=ROOT/opts.episode
    report,payload=inspect(ep)
    if opts.record_verified_fail:
        if not (ROOT/".git").is_dir() or not report["may_record_fail"]:
            print(json.dumps({**report,"status":"RECORD_FAIL_REFUSED"},ensure_ascii=False))
            return 2
        story,board=review.story_paths(ep)
        # Existing audited code persists FAIL to official MySQL; it must
        # not re-run Codex, delete the consumed ticket or declare PASS.
        rc=review._finalize_review(
            ep,payload,attempt=10,before_story=review.sha256_file(story),
            before_board=review.sha256_file(board),
            provenance=payload["critic_provenance"])
        print(json.dumps({**report,"status":"A10_OFFICIAL_FAIL_RECORDED",
                          "read_only":False,"sql_writes":"OFFICIAL_REVIEW_FAIL",
                          "review_rc":rc},ensure_ascii=False))
        return 0 if rc==2 else 2
    print(json.dumps(report,ensure_ascii=False,sort_keys=True))
    return 0 if report["status"]=="A10_PROVIDER_SUCCESS_REVIEW_FAIL" else 2


if __name__=="__main__":
    raise SystemExit(main())
