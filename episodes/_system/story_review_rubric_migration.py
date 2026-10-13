#!/usr/bin/env python3
"""One-shot source-SHA-bound NEW native Codex Story Critic epoch.

Historical WORK/DevSpace PASS never becomes current MySQL authority. An
immutable prior review proves only historical input; a new independent reviewer
must actually assess the changed current production rubric.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
import sys

REVIEW_SCOPE = "MIGRATED_EPISODE_RUBRIC_REVALIDATION"
EPOCH_REL = "meta/runtime/story-review-migrated-rubric-a9.json"
FORMAL_STANDARD = "standards/制作规范_正式版.md"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_legacy_review(ep: Path) -> dict:
    import story_review
    return story_review.read_json(Path(ep) / story_review.REVIEW_REL)


def plan(ep: Path) -> dict:
    import story_review as sr
    import product_review_adapter as pra
    ep = Path(ep).resolve()
    base = {"status":"EVIDENCE_UNVERIFIED","attempt":None,
            "may_reuse_old_pass":False,"provider_calls":0,
            "sql_writes":0,"old_review_still_readonly":True}
    try:
        root = sr.ROOT.resolve()
        ep.relative_to(root)
        if (ep/EPOCH_REL).exists():
            return {**base,"status":"ALREADY_AUTHORIZED_NO_RETRY"}
        if sr.load_review(ep) is not None:
            return {**base,"status":"OFFICIAL_REVIEW_ALREADY_EXISTS"}
        scoped = pra.request_path(ep,"story-semantic",attempt=2)
        if not pra._request_exists(scoped):
            return {**base,"status":"HISTORICAL_REQUEST_MISSING"}
        prior = pra._read_json(scoped)
        if (prior.get("status")!="FINALIZED" or prior.get("attempt")!=2
            or prior.get("review_kind")!="story-semantic"):
            return {**base,"status":"HISTORICAL_REQUEST_UNVERIFIED"}
        prior_path = ep/sr.REVIEW_REL
        if not prior_path.is_file():
            return {**base,"status":"HISTORICAL_PAYLOAD_MISSING"}
        historic = sr.read_json(prior_path)
        story,board = sr.story_paths(ep)
        story_sha=sr.sha256_file(story)
        board_sha=sr.sha256_file(board)
        if (historic.get("summary") or {}).get("passed") is not True:
            return {**base,"status":"PRIOR_REVIEW_NOT_PASS"}
        if (historic.get("critic_provenance") or {}).get("attempt")!=2 or (
            historic.get("critic_provenance") or {}).get("request_id")!=prior.get("request_id"):
            return {**base,"status":"REVIEW_REQUEST_BINDING_MISMATCH"}
        if sr.validate_payload(historic, story_sha=story_sha,
                               storyboard_sha=board_sha,
                               version=sr.episode_contract_version(ep)):
            return {**base,"status":"HISTORICAL_PAYLOAD_INVALID"}
        frozen=prior.get("source_files")
        if not isinstance(frozen,list) or len(frozen)<4:
            return {**base,"status":"FROZEN_SOURCES_MISSING"}
        bypath={str(x.get("path") or ""):str(x.get("sha256") or "").lower()
                for x in frozen if isinstance(x,dict)}
        if len(bypath)!=len(frozen) or FORMAL_STANDARD not in bypath:
            return {**base,"status":"FROZEN_SOURCE_BINDINGS_INVALID"}
        original_sha=bypath[FORMAL_STANDARD]
        if any(not re.fullmatch(r"[a-f0-9]{64}", v) for v in bypath.values()):
            return {**base,"status":"FROZEN_SOURCE_SHA_MALFORMED"}
        if not str(prior.get("request_id") or "").strip():
            return {**base,"status":"HISTORICAL_REQUEST_ID_MISSING"}
        formal = root/FORMAL_STANDARD
        current_sha=digest(formal)
        if not original_sha or original_sha==current_sha:
            return {**base,"status":"FORMAL_STANDARD_NOT_CHANGED"}
        moved={"story":story_sha,"storyboard":board_sha}
        hit={"story":False,"storyboard":False}
        for raw,previous_sha in bypath.items():
            source=(root/raw).resolve()
            if not source.is_relative_to(root) or len(previous_sha)!=64:
                return {**base,"status":"FROZEN_SOURCE_UNSAFE"}
            if raw==FORMAL_STANDARD:
                continue
            if source.is_file():
                if digest(source)!=previous_sha:
                    return {**base,"status":"OTHER_FROZEN_SOURCE_DRIFT"}
            elif Path(raw).name==story.name:
                if previous_sha!=moved["story"]:
                    return {**base,"status":"STORY_SOURCE_DRIFT"}
                hit["story"]=True
            elif Path(raw).name==board.name:
                if previous_sha!=moved["storyboard"]:
                    return {**base,"status":"STORYBOARD_SOURCE_DRIFT"}
                hit["storyboard"]=True
            else:
                return {**base,"status":"OTHER_FROZEN_SOURCE_MISSING"}
        if not all(hit.values()):
            # In an already relocated Episode request paths must still be
            # the immutable old paths, not a mix of unreviewed current aliases.
            return {**base,"status":"FROZEN_STORY_BINDING_UNVERIFIED"}
        return {**base,"status":"ONE_SHOT_NEW_CRITIC_EPOCH_READY",
                "attempt":9,"episode":ep.relative_to(root).as_posix(),
                "legacy_review_sha256":digest(prior_path),
                "prior_review_request_sha256":digest(scoped),
                "prior_review_request_id":prior["request_id"],
                "prior_standard_sha256":original_sha,
                "current_standard_sha256":current_sha,
                "prior_story_sha256":historic["story_sha256"],
                "current_story_sha256":story_sha,
                "storyboard_sha256":board_sha}
    except Exception:
        return {**base,"status":"EVIDENCE_READ_ERROR"}


def authorize(ep: Path, *, attempt: int, current_rubric_sha256: str) -> dict:
    """Reserve the SINGLE paid text-Critic call BEFORE dispatch. Never retry."""
    import story_review as sr
    if (not (sr.ROOT/".git").is_dir()
            or (sr.ROOT/".git").is_symlink()
            or not Path(ep).resolve().is_relative_to(sr.ROOT.resolve())):
        raise RuntimeError("migrated rubric paid Critic requires canonical primary checkout")
    if attempt!=9:
        raise RuntimeError("migrated rubric revalidation only admits attempt 9")
    ep=Path(ep).resolve()
    selection=plan(ep)
    if selection["status"]!="ONE_SHOT_NEW_CRITIC_EPOCH_READY":
        raise RuntimeError("migrated rubric critic denied: "+selection["status"])
    if not current_rubric_sha256 or len(current_rubric_sha256)!=64:
        raise RuntimeError("current rubric identity missing")
    prior={
        "schema":"storyos.story_review_migrated_rubric_epoch.v1",
        "authorization":"direct_user_continuation",
        "review_scope":REVIEW_SCOPE,
        "global_review_attempt":9,"review_epoch":8,"epoch_attempt":1,
        "previous_review_sha256":selection["legacy_review_sha256"],
        "previous_review_request_sha256":selection["prior_review_request_sha256"],
        "previous_review_request_id":selection["prior_review_request_id"],
        "previous_standard_sha256":selection["prior_standard_sha256"],
        "current_standard_sha256":selection["current_standard_sha256"],
        "current_rubric_sha256":current_rubric_sha256,
        "story_sha256":selection["current_story_sha256"],
        "storyboard_sha256":selection["storyboard_sha256"],
        "reason":"Fresh independent Critic required after Git byte-identical Episode relocation and changed formal production standard; cannot replay legacy WORK PASS",
    }
    target=ep/EPOCH_REL
    target.parent.mkdir(parents=True,exist_ok=True)
    payload=json.dumps(prior,ensure_ascii=False,sort_keys=True,indent=2)+"\n"
    # Exclusive create reserves attempt 9: a killed/timeout Codex call may
    # have been paid. No 'resume by retry' in any circumstance.
    with target.open("x",encoding="utf-8") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    return prior


def validate_epoch(ep: Path, data: dict) -> bool:
    import story_review as sr
    import product_review_adapter as pra
    ep=Path(ep).resolve()
    try:
        if not isinstance(data,dict) or data.get("review_scope")!=REVIEW_SCOPE:
            return False
        stamp=sr.read_json(ep/EPOCH_REL)
        if any(data.get(k)!=stamp.get(k) for k in (
            "review_scope","review_epoch","epoch_attempt","previous_review_sha256",
            "previous_review_request_sha256","previous_review_request_id",
            "previous_standard_sha256","current_standard_sha256","current_rubric_sha256")):
            return False
        if (stamp.get("global_review_attempt")!=9
            or stamp.get("review_epoch")!=8
            or stamp.get("epoch_attempt")!=1):
            return False
        scoped=pra.request_path(ep,"story-semantic",attempt=2)
        req=pra._read_json(scoped)
        prior=sr.read_json(ep/sr.REVIEW_REL)
        story,board=sr.story_paths(ep)
        return bool(
            digest(ep/sr.REVIEW_REL)==stamp["previous_review_sha256"]
            and digest(scoped)==stamp["previous_review_request_sha256"]
            and req["request_id"]==stamp["previous_review_request_id"]
            and prior["critic_provenance"]["request_id"]==req["request_id"]
            and stamp["story_sha256"]==sr.sha256_file(story)
            and stamp["storyboard_sha256"]==sr.sha256_file(board)
            and stamp["current_standard_sha256"]==digest(sr.ROOT/FORMAL_STANDARD)
            and stamp["previous_standard_sha256"]!=stamp["current_standard_sha256"]
            and stamp["current_rubric_sha256"]==sr._review_rubric_digest(
                Path(sr.__file__).read_text("utf-8-sig")))
    except Exception:
        return False
