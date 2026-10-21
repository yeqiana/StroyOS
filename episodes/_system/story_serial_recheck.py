#!/usr/bin/env python3
"""One explicitly authorized, non-replayable serial-episode re-review.

The first official failed Story Critic remains immutable. This entry never
rewrites locked source, restarts the Driver, or authorizes any image generation.
The one-shot record is exclusively created *before* the paid independent Codex
critic; failures, timeout, UNKNOWN and transport errors consume this epoch.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

import story_narrative_form

REVIEW_SCOPE = "SERIAL_EPISODE_SAME_SOURCE_REVALIDATION"
EPOCH_REL = "meta/runtime/story-review-serial-episode-a12.json"
CANDIDATE_REL = "meta/.story-semantic-review-a12.candidate.json"
ATTEMPT = 12


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _prior_digest(review: dict) -> str:
    import review_record_persistence as store
    return store._payload_content_sha(review)


def _source_digest(ep: Path) -> dict:
    import story_review as sr
    story, board = sr.story_paths(ep)
    captions = ep / "docs/subtitles.yaml"
    if any(not p.is_file() or p.is_symlink() for p in (story, board, captions)):
        raise ValueError("SERIAL_RECHECK_SOURCE_MISSING_OR_SYMLINK")
    return {"story_sha256": sr.sha256_file(story),
            "storyboard_sha256": sr.sha256_file(board),
            "subtitle_source_sha256": sr.sha256_file(captions)}


def _rubric() -> str:
    import story_review as sr
    return sr._review_rubric_digest(Path(sr.__file__).read_text(encoding="utf-8-sig"))


def _previous_exists(ep: Path, sha: str) -> bool:
    import review_record_persistence as store
    import story_review as sr
    import episode_identity
    connection, repository = store._repository()
    try:
        rows = repository.list_attempts(
            episode_identity.storage_episode_id(ep), sr.REVIEW_TYPE)
        if len(rows) > 48:
            return False
        ids = [int(row.get("attempt_no") or 0) for row in rows]
    finally:
        connection.close()
    for number in ids:
        if number < 1:
            continue
        payload = store.load_attempt(ep, sr.REVIEW_TYPE, number,
                                     legacy_path=ep / sr.REVIEW_REL)
        if isinstance(payload, dict) and _prior_digest(payload) == sha:
            return (payload.get("summary") or {}).get("passed") is False
    return False


def plan(ep: Path) -> dict:
    import story_review as sr
    import runtime_request
    ep = Path(ep).resolve()
    base = {"status": "SERIAL_RECHECK_UNVERIFIED", "can_dispatch_model": False,
            "can_dispatch_image": False, "read_only": True,
            "model_calls": 0, "sql_writes": 0}
    try:
        if not ep.is_relative_to(sr.ROOT.resolve()):
            return {**base, "status": "EPISODE_OUTSIDE_REPOSITORY"}
        request = runtime_request.authority_for_episode(ep)
        if story_narrative_form.from_request(request) != story_narrative_form.SERIAL_EPISODE:
            return {**base, "status": "NOT_A_SERIAL_EPISODE"}
        if not story_narrative_form.is_locked(request):
            return {**base, "status": "NOT_USER_LOCKED_STORY"}
        if (ep / EPOCH_REL).exists() or (ep / CANDIDATE_REL).exists():
            return {**base, "status": "SERIAL_RECHECK_ALREADY_RESERVED_NO_RETRY"}
        previous = sr.load_review(ep)
        if not isinstance(previous, dict) or (previous.get("summary") or {}).get("passed") is not False:
            return {**base, "status": "OFFICIAL_FAILED_REVIEW_REQUIRED"}
        provenance = previous.get("critic_provenance") or {}
        if provenance.get("attempt") not in {1, 2}:
            return {**base, "status": "UNEXPECTED_PREVIOUS_REVIEW_EPOCH"}
        source = _source_digest(ep)
        if any(previous.get(k) != source[k] for k in source):
            return {**base, "status": "PREVIOUS_REVIEW_SOURCE_SHA_DRIFT"}
        previous_sha = _prior_digest(previous)
        if not _previous_exists(ep, previous_sha):
            return {**base, "status": "PREVIOUS_FAILED_REVIEW_NOT_PERSISTED"}
        rubric = _rubric()
        actual_standard_sha = digest(sr.ROOT / "standards" / "制作规范_正式版.md")
        # This check binds code to the serial-specific critic rubric, not a
        # fallback that could silently apply standalone completion criteria.
        text = Path(sr.__file__).read_text(encoding="utf-8-sig")
        if "SERIAL EPISODE HARD RULES (STORY_OS_SERIAL_EPISODE)" not in text:
            return {**base, "status": "SERIAL_CRITIC_RUBRIC_MISSING"}
        import runtime_driver
        driver = runtime_driver.status(ep)
        if driver.get("driver_state") in {"RUNNING", "ALIVE_NOT_BEATING", "UNKNOWN"}:
            return {**base, "status": "DRIVER_OWNER_UNVERIFIED"}
        return {**base, **source, "status": "ONE_SHOT_SERIAL_REVIEW_READY",
                "attempt": ATTEMPT, "can_dispatch_model": True,
                "previous_review_sha256": previous_sha,
                "current_rubric_sha256": rubric,
                "current_standard_sha256": actual_standard_sha,
                "episode": ep.relative_to(sr.ROOT).as_posix()}
    except Exception:
        return {**base, "status": "SERIAL_RECHECK_READ_EVIDENCE_ERROR"}


def authorize(ep: Path, *, previous_sha: str) -> dict:
    """Reserve exactly once, crash-safe, without clobbering any previous token."""
    import story_review as sr
    ep = Path(ep).resolve()
    if not (sr.ROOT / ".git").is_dir() or (sr.ROOT / ".git").is_symlink():
        raise RuntimeError("SERIAL_RECHECK_CANONICAL_PRIMARY_CHECKOUT_REQUIRED")
    check = plan(ep)
    if check["status"] != "ONE_SHOT_SERIAL_REVIEW_READY":
        raise RuntimeError("SERIAL_RECHECK_DENIED:" + check["status"])
    if not previous_sha or previous_sha != check["previous_review_sha256"]:
        raise RuntimeError("SERIAL_RECHECK_PREVIOUS_FAIL_SHA_MISMATCH")
    keys = ("episode", "story_sha256", "storyboard_sha256", "subtitle_source_sha256",
            "previous_review_sha256", "current_rubric_sha256", "current_standard_sha256")
    token = {"schema": "storyos.serial_episode_review_a12.v1",
             "authorization": "explicit_user_one_shot_serial_review",
             "review_scope": REVIEW_SCOPE, "global_review_attempt": ATTEMPT,
             "review_epoch": 11, "epoch_attempt": 1,
             **{key: check[key] for key in keys}}
    ticket = ep / EPOCH_REL
    ticket.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(token, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    with ticket.open("x", encoding="utf-8") as out:
        out.write(raw)
        out.flush()
        os.fsync(out.fileno())
    return token


def validate_epoch(ep: Path, provenance: dict) -> bool:
    """The new review can pass only while its old failed row still exists."""
    import story_review as sr
    try:
        ep = Path(ep).resolve()
        ticket = sr.read_json(ep / EPOCH_REL)
        if ticket.get("authorization") != "explicit_user_one_shot_serial_review":
            return False
        if (ticket.get("review_scope") != REVIEW_SCOPE
                or ticket.get("global_review_attempt") != ATTEMPT
                or ticket.get("review_epoch") != 11
                or ticket.get("epoch_attempt") != 1
                or provenance.get("attempt") != ATTEMPT
                or provenance.get("review_scope") != REVIEW_SCOPE
                or provenance.get("direct_user_continuation_review") is not True):
            return False
        for key in ("review_epoch", "epoch_attempt", "previous_review_sha256",
                    "current_rubric_sha256", "subtitle_source_sha256"):
            if ticket.get(key) != provenance.get(key):
                return False
        source = _source_digest(ep)
        if any(ticket.get(k) != source[k] for k in source):
            return False
        if ticket["current_rubric_sha256"] != _rubric():
            return False
        if ticket["current_standard_sha256"] != digest(sr.ROOT / "standards" / "制作规范_正式版.md"):
            return False
        return _previous_exists(ep, ticket["previous_review_sha256"])
    except Exception:
        return False


def run(ep: Path, *, previous_sha: str, codex_raw: str | None, timeout: int | None = None) -> int:
    import story_review as sr
    import codex_critic_runner
    import runtime_provenance
    import runtime_timeout_policy
    ep = Path(ep).resolve()
    # Free route/source verification must precede the irreversible reservation.
    codex = sr.resolve_codex(codex_raw)
    check = plan(ep)
    if check["status"] != "ONE_SHOT_SERIAL_REVIEW_READY":
        raise RuntimeError("SERIAL_RECHECK_DENIED:" + check["status"])
    story, board = sr.story_paths(ep)
    candidate = ep / CANDIDATE_REL
    prompt = sr.critic_prompt(ep, story, board, candidate, ATTEMPT)
    if "SERIAL EPISODE HARD RULES" not in prompt:
        raise RuntimeError("SERIAL_RECHECK_WRONG_RUBRIC")
    if digest(story) != check["story_sha256"] or digest(board) != check["storyboard_sha256"]:
        raise RuntimeError("SERIAL_RECHECK_INPUT_CHANGED_BEFORE_RESERVATION")
    resolved_timeout = runtime_timeout_policy.resolve("serial_episode_review", timeout)
    token = authorize(ep, previous_sha=previous_sha)
    log = ep / "meta" / "story-critic-attempt-12.jsonl"
    # Nothing after this line may call the model twice or delete the token.
    completed = codex_critic_runner.launch(
        prompt + sr.DIRECT_CODEX_EXECUTION_OVERRIDE, codex=codex,
        root=sr.ROOT, timeout=resolved_timeout, output_path=candidate,
        reasoning_effort="high", sandbox="read-only",
        log_path=log, codex_home_mode="isolated")
    if completed.returncode != 0:
        raise RuntimeError("SERIAL_RECHECK_RESULT_UNKNOWN_NO_RETRY")
    if (not candidate.is_file()
            or not all(getattr(__import__("story_review"), "sha256_file")
                       (path) == token[key] for path, key in (
                       (story, "story_sha256"), (board, "storyboard_sha256"),
                       (ep / "docs/subtitles.yaml", "subtitle_source_sha256")))):
        raise RuntimeError("SERIAL_RECHECK_SOURCE_OR_OUTPUT_DRIFT_NO_RETRY")
    data = sr.read_json(candidate)
    prov = runtime_provenance.build_critic_provenance(
        "CODEX", attempt=ATTEMPT, log=log.relative_to(sr.ROOT).as_posix(),
        allow_user_continuation_attempt=True)
    prov.update({"review_scope": REVIEW_SCOPE, "review_epoch": 11,
                 "epoch_attempt": 1,
                 "previous_review_sha256": token["previous_review_sha256"],
                 "current_rubric_sha256": token["current_rubric_sha256"],
                 "subtitle_source_sha256": token["subtitle_source_sha256"]})
    rc = sr._finalize_review(
        ep, data, attempt=ATTEMPT, before_story=token["story_sha256"],
        before_board=token["storyboard_sha256"], provenance=prov)
    if rc != 0:
        return rc
    if sr.verify(ep):
        return 2
    sr.project_verified_story_gate(ep)
    # The independent PASS certifies one *episode-level* state-change closure,
    # not that the whole series' mystery has been resolved.
    gates = ep / "meta/story-gates.json"
    current = sr.read_json(gates)
    if ((current.get("reviews") or {}).get("story") == "passed"
            and validate_epoch(ep, prov)):
        current.setdefault("story", {})["task_closed"] = True
        sr.write_json(gates, current)
        return 0
    return 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    check = sub.add_parser("plan")
    check.add_argument("episode")
    launch = sub.add_parser("run")
    launch.add_argument("episode")
    launch.add_argument("--ack-one-shot-serial-review", action="store_true", required=True)
    launch.add_argument("--expected-previous-review-sha", required=True)
    launch.add_argument("--codex")
    launch.add_argument("--timeout", type=int, default=None)
    args = parser.parse_args()
    ep = Path(args.episode).resolve()
    if args.cmd == "plan":
        print(json.dumps(plan(ep), ensure_ascii=False))
        return 0
    try:
        if not args.ack_one_shot_serial_review:
            raise RuntimeError("EXPLICIT_ONE_SHOT_AUTHORIZATION_REQUIRED")
        return run(ep, previous_sha=args.expected_previous_review_sha,
                   codex_raw=args.codex, timeout=args.timeout)
    except (OSError, RuntimeError, ValueError) as exc:
        print("SERIAL_RECHECK_STOP:", type(exc).__name__, str(exc))
        return 22


if __name__ == "__main__":
    raise SystemExit(main())
