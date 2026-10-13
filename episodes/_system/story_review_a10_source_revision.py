#!/usr/bin/env python3
"""Exactly one SHA-bound independent A10 review of revised Episode 15 source.

A9 timeout evidence, candidate, and consumed ticket remain immutable.
No review PASS or image permit is implied by plan/authorize.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

REVIEW_SCOPE = "EPISODE_SOURCE_REVISION_AFTER_A9_TIMEOUT"
EPOCH_REL = "meta/runtime/story-review-source-after-a9-timeout-a10.json"
CANDIDATE_REL = "meta/.story-semantic-review-a10.candidate.json"
EXPECTED_EPISODE = "episodes/15_天界生活日常/01_天界普通女生的一天"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def plan(ep: Path) -> dict:
    """Strict read-only; only the first material source revision is eligible."""
    import story_review as sr
    import story_review_rubric_migration as a9
    from text_audit import parse_simple_subtitles_yaml
    import sys
    scripts=str(sr.ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0,scripts)
    import storyos_a9_receipt_reconcile as receipt

    base={"status":"A10_AUTHORITY_UNVERIFIED","attempt":None,
          "read_only":True,"model_calls":0,"sql_writes":0,
          "can_dispatch_model":False,"can_dispatch_image":False}
    try:
        ep=Path(ep).resolve()
        if ep.relative_to(sr.ROOT.resolve()).as_posix()!=EXPECTED_EPISODE:
            return {**base,"status":"EPISODE_NOT_IN_A10_SCOPE"}
        if (ep/EPOCH_REL).exists():
            return {**base,"status":"A10_ALREADY_AUTHORIZED_NO_RETRY"}
        if sr.load_review(ep) is not None:
            return {**base,"status":"OFFICIAL_REVIEW_EXISTS_RECONCILE"}
        prior=sr.read_json(ep/a9.EPOCH_REL)
        if (prior.get("global_review_attempt")!=9
                or prior.get("review_scope")!=a9.REVIEW_SCOPE):
            return {**base,"status":"A9_TICKET_INVALID"}
        previous=receipt.inspect(ep,root=sr.ROOT)
        if (previous.get("status")!="PAID_CRITIC_TIMEOUT_NO_AUTORETRY"
                or previous.get("runner_receipt_count")!=1
                or previous.get("candidate_declared_pass") is not False):
            return {**base,"status":"A9_TIMEOUT_NOT_SHA_VERIFIED"}
        story,board=sr.story_paths(ep)
        captions=ep/"docs/subtitles.yaml"
        if (not captions.is_file() or not board.name.endswith("_V1.1.md")
                or "修订草稿" not in board.name
                or sr.sha256_file(story)!=prior.get("story_sha256")
                or sr.sha256_file(board)==prior.get("storyboard_sha256")):
            return {**base,"status":"MATERIAL_SOURCE_REVISION_UNVERIFIED"}
        frame_ids=sorted(parse_simple_subtitles_yaml(captions).get("frames") or {})
        if frame_ids!=list(range(1,21)):
            return {**base,"status":"CAPTION_FRAME_BINDING_INVALID"}
        candidate=ep/CANDIDATE_REL
        if candidate.exists():
            return {**base,"status":"A10_CANDIDATE_ALREADY_EXISTS_RECONCILE"}
        return {**base,"status":"ONE_SHOT_REVISED_SOURCE_READY",
                "attempt":10,"episode":EXPECTED_EPISODE,
                "story_sha256":sr.sha256_file(story),
                "previous_storyboard_sha256":prior["storyboard_sha256"],
                "storyboard_sha256":sr.sha256_file(board),
                "subtitle_source_sha256":sr.sha256_file(captions),
                "previous_a9_ticket_sha256":digest(ep/a9.EPOCH_REL),
                "previous_a9_candidate_sha256":digest(ep/sr.CANDIDATE_REL),
                "current_rubric_sha256":sr._review_rubric_digest(
                    Path(sr.__file__).read_text("utf-8-sig"))}
    except Exception:
        return {**base,"status":"A10_EVIDENCE_READ_ERROR"}


def authorize(ep: Path, *, attempt: int, current_rubric_sha256: str) -> dict:
    import story_review as sr
    if (not (sr.ROOT/".git").is_dir()
            or (sr.ROOT/".git").is_symlink()
            or not Path(ep).resolve().is_relative_to(sr.ROOT.resolve())):
        raise RuntimeError("A10 paid review requires primary checkout")
    if attempt!=10:
        raise RuntimeError("A10 only admits global attempt 10")
    evidence=plan(ep)
    if (evidence["status"]!="ONE_SHOT_REVISED_SOURCE_READY"
            or evidence["current_rubric_sha256"]!=current_rubric_sha256):
        raise RuntimeError("A10 source review denied: "+evidence["status"])
    result={
        "schema":"storyos.story_review_source_revision_after_a9_timeout.v1",
        "authorization":"direct_user_continuation",
        "review_scope":REVIEW_SCOPE,
        "global_review_attempt":10,"review_epoch":9,"epoch_attempt":1,
        "previous_review_attempt":9,
        "previous_a9_ticket_sha256":evidence["previous_a9_ticket_sha256"],
        "previous_a9_candidate_sha256":evidence["previous_a9_candidate_sha256"],
        "previous_storyboard_sha256":evidence["previous_storyboard_sha256"],
        "story_sha256":evidence["story_sha256"],
        "storyboard_sha256":evidence["storyboard_sha256"],
        "subtitle_source_sha256":evidence["subtitle_source_sha256"],
        "current_rubric_sha256":current_rubric_sha256,
        # The prior paid call timed out; this new source is independently
        # reviewed and does not borrow a prior PASS/FAIL as Review Authority.
        "reason":"New user-authorized source revision after SHA-proven A9 native timeout",
    }
    target=Path(ep)/EPOCH_REL
    target.parent.mkdir(parents=True,exist_ok=True)
    with target.open("x",encoding="utf-8") as f:
        f.write(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+"\n")
        f.flush()
        os.fsync(f.fileno())
    return result


def validate_epoch(ep: Path, provenance: dict) -> bool:
    import story_review as sr
    import story_review_rubric_migration as a9
    try:
        ep=Path(ep).resolve()
        stamp=sr.read_json(ep/EPOCH_REL)
        if not isinstance(provenance,dict):
            return False
        keys=("review_scope","review_epoch","epoch_attempt",
              "current_rubric_sha256",
              "previous_storyboard_sha256","previous_a9_ticket_sha256",
              "previous_a9_candidate_sha256","subtitle_source_sha256")
        if any(stamp.get(k)!=provenance.get(k) for k in keys):
            return False
        if (stamp.get("global_review_attempt")!=10
                or stamp.get("review_scope")!=REVIEW_SCOPE
                or stamp.get("review_epoch")!=9 or stamp.get("epoch_attempt")!=1
                or provenance.get("attempt")!=10):
            return False
        old=sr.read_json(ep/a9.EPOCH_REL)
        story,board=sr.story_paths(ep)
        captions=ep/"docs/subtitles.yaml"
        return bool(
            stamp["previous_a9_ticket_sha256"]==digest(ep/a9.EPOCH_REL)
            and old["storyboard_sha256"]==stamp["previous_storyboard_sha256"]
            and old["story_sha256"]==stamp["story_sha256"]
            and stamp["story_sha256"]==sr.sha256_file(story)
            and stamp["storyboard_sha256"]==sr.sha256_file(board)
            and stamp["subtitle_source_sha256"]==sr.sha256_file(captions)
            and stamp["previous_a9_candidate_sha256"]==digest(ep/sr.CANDIDATE_REL)
            and stamp["current_rubric_sha256"]==sr._review_rubric_digest(
                Path(sr.__file__).read_text("utf-8-sig")))
    except Exception:
        return False
