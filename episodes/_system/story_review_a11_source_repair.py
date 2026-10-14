#!/usr/bin/env python3
"""Exactly one new A11 native Story Review after the actual MySQL A10 FAIL.

The database's row attempt_no is NOT the global Critic attempt. Preserve
original A10 provenance, ticket, model candidate and old source bytes.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import story_review_a10_source_revision as a10

REVIEW_SCOPE = "EPISODE_SOURCE_REPAIR_AFTER_A10_DELETE_FRAME_FAIL"
EPOCH_REL = "meta/runtime/story-review-a11-after-a10-delete-frame-fail.json"
CANDIDATE_REL = "meta/.story-semantic-review-a11.candidate.json"
EXPECTED_EPISODE = a10.EXPECTED_EPISODE


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _previous_mysql_a10(ep: Path):
    """Locate global Critic #10 by provenance, never by database row number."""
    import story_review as sr
    import review_record_persistence as store
    import episode_identity
    conn,repo=store._repository()
    try:
        rows=repo.list_attempts(episode_identity.storage_episode_id(ep),sr.REVIEW_TYPE)
        match=[r for r in rows if (r.get("payload") or {}).get("critic_provenance",{}).get("attempt")==10
               and r.get("decision")=="FAIL"]
        if len(match)!=1 or len(rows)>32:
            return None
        number=int(match[0]["attempt_no"])
    finally:
        conn.close()
    payload=store.load_attempt(ep,sr.REVIEW_TYPE,number,legacy_path=ep/sr.REVIEW_REL)
    if (not isinstance(payload,dict)
            or (payload.get("critic_provenance") or {}).get("attempt")!=10
            or (payload.get("summary") or {}).get("passed") is not False
            or "DELETE_FRAME_TEST_FAIL" not in (payload.get("issue_codes") or [])):
        return None
    return number,payload,store._payload_content_sha(payload)


def plan(ep: Path) -> dict:
    import story_review as sr
    from text_audit import parse_simple_subtitles_yaml
    base={"status":"A11_AUTHORITY_UNVERIFIED","attempt":None,
          "read_only":True,"model_calls":0,"sql_writes":0,
          "can_dispatch_model":False,"can_dispatch_image":False}
    try:
        ep=Path(ep).resolve()
        if ep.relative_to(sr.ROOT.resolve()).as_posix()!=EXPECTED_EPISODE:
            return {**base,"status":"A11_OUT_OF_SCOPE"}
        if (ep/EPOCH_REL).exists() or (ep/CANDIDATE_REL).exists():
            return {**base,"status":"A11_ALREADY_CONSUMED_NO_RETRY"}
        previous=_previous_mysql_a10(ep)
        if previous is None:
            return {**base,"status":"OFFICIAL_A10_FAIL_NOT_MYSQL_VERIFIED"}
        db_row,old_review,review_sha=previous
        latest=sr.load_review(ep)
        import review_record_persistence as store
        if (not isinstance(latest,dict) or
                (latest.get("critic_provenance") or {}).get("attempt")!=10 or
                (latest.get("summary") or {}).get("passed") is not False
                or store._payload_content_sha(latest)!=review_sha):
            return {**base,"status":"A10_NOT_LATEST_AUTHORITY"}
        old_ticket=sr.read_json(ep/a10.EPOCH_REL)
        old_board=ep/"docs/03_天界普通女生的一天_20张分镜修订草稿_V1.1.md"
        old_captions=ep/"docs/subtitles_V1.1.yaml"
        old_candidate=ep/a10.CANDIDATE_REL
        story,board=sr.story_paths(ep)
        subtitles=ep/"docs/subtitles.yaml"
        if (old_ticket.get("global_review_attempt")!=10
            or old_review.get("story_sha256")!=old_ticket.get("story_sha256")
            or old_review.get("storyboard_sha256")!=old_ticket.get("storyboard_sha256")
            or old_review.get("subtitle_source_sha256")!=old_ticket.get("subtitle_source_sha256")
            or old_board.is_symlink() or old_captions.is_symlink()
            or any(not f.is_file() for f in (old_board,old_captions,old_candidate,subtitles))
            or sha(old_board)!=old_ticket["storyboard_sha256"]
            or sha(old_captions)!=old_ticket["subtitle_source_sha256"]
            or sha(story)!=old_ticket["story_sha256"]
            or sha(board)==sha(old_board)
            or sha(subtitles)==sha(old_captions)
            or not board.name.endswith("V1.2.md")):
            return {**base,"status":"A11_MATERIAL_SOURCE_OR_PREDECESSOR_UNVERIFIED"}
        frames=parse_simple_subtitles_yaml(subtitles)["frames"]
        if sorted(frames)!=list(range(1,21)):
            return {**base,"status":"A11_CAPTIONS_NOT_BIJECTIVE"}
        body=board.read_text("utf-8-sig")
        if not all(token in body for token in ("3. **专门留早餐**","4. **P04 看见为自己留的早餐**",
            "8. **抢窗边位置的小习惯**","9. **又想抢最后一块点心**",
            "18. **这回先给朋友**")):
            return {**base,"status":"A11_DELETE_FRAME_REPAIR_NOT_PRESENT"}
        return {**base,"status":"ONE_SHOT_A11_SOURCE_REPAIR_READY","attempt":11,
                "story_sha256":sha(story),"storyboard_sha256":sha(board),
                "subtitle_source_sha256":sha(subtitles),
                "previous_review_sha256":review_sha,
                "previous_a10_mysql_attempt_no":db_row,
                "previous_a10_ticket_sha256":sha(ep/a10.EPOCH_REL),
                "previous_a10_candidate_sha256":sha(old_candidate),
                "previous_storyboard_sha256":sha(old_board),
                "previous_subtitle_sha256":sha(old_captions),
                "current_rubric_sha256":sr._review_rubric_digest(
                    Path(sr.__file__).read_text("utf-8-sig"))}
    except Exception:
        return {**base,"status":"A11_READONLY_SOURCE_UNVERIFIED"}


def authorize(ep: Path, *, attempt: int, current_rubric_sha256: str) -> dict:
    import story_review as sr
    ep=Path(ep).resolve()
    if ((sr.ROOT/".git").is_symlink() or not (sr.ROOT/".git").is_dir()
            or attempt!=11 or not ep.is_relative_to(sr.ROOT.resolve())):
        raise RuntimeError("A11 requires the canonical primary checkout and attempt 11")
    source=plan(ep)
    if (source["status"]!="ONE_SHOT_A11_SOURCE_REPAIR_READY"
            or source["current_rubric_sha256"]!=current_rubric_sha256):
        raise RuntimeError("A11 irreversible review denied: "+source["status"])
    proof={
        "schema":"storyos.story_critic_after_a10_failed_delete_frame.v1",
        "authorization":"direct_user_continuation","review_scope":REVIEW_SCOPE,
        "global_review_attempt":11,"review_epoch":10,"epoch_attempt":1,
        "previous_review_attempt":10,
        **{k:source[k] for k in (
            "previous_review_sha256","previous_a10_mysql_attempt_no",
            "previous_a10_ticket_sha256","previous_a10_candidate_sha256",
            "previous_storyboard_sha256","previous_subtitle_sha256",
            "story_sha256","storyboard_sha256","subtitle_source_sha256",
            "current_rubric_sha256")}
    }
    target=ep/EPOCH_REL
    target.parent.mkdir(parents=True,exist_ok=True)
    with target.open("x",encoding="utf-8") as f:
        json.dump(proof,f,ensure_ascii=False,sort_keys=True,indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    return proof


def validate_epoch(ep: Path, provenance: dict) -> bool:
    import story_review as sr
    import review_record_persistence as store
    try:
        ep=Path(ep).resolve()
        stamp=sr.read_json(ep/EPOCH_REL)
        keys=("review_scope","review_epoch","epoch_attempt",
              "previous_review_sha256","previous_a10_ticket_sha256",
              "previous_a10_candidate_sha256","previous_storyboard_sha256",
              "previous_subtitle_sha256","subtitle_source_sha256",
              "current_rubric_sha256")
        if (not isinstance(provenance,dict)
            or provenance.get("attempt")!=11
            or stamp.get("global_review_attempt")!=11
            or stamp.get("review_scope")!=REVIEW_SCOPE
            or stamp.get("review_epoch")!=10
            or stamp.get("epoch_attempt")!=1
            or any(provenance.get(k)!=stamp.get(k) for k in keys)):
            return False
        previous=store.load_attempt(ep,sr.REVIEW_TYPE,
            int(stamp["previous_a10_mysql_attempt_no"]),
            legacy_path=ep/sr.REVIEW_REL)
        old_ticket=sr.read_json(ep/a10.EPOCH_REL)
        story,board=sr.story_paths(ep)
        return bool(
            isinstance(previous,dict)
            and (previous.get("critic_provenance") or {}).get("attempt")==10
            and (previous.get("summary") or {}).get("passed") is False
            and store._payload_content_sha(previous)==stamp["previous_review_sha256"]
            and old_ticket["storyboard_sha256"]==stamp["previous_storyboard_sha256"]
            and old_ticket["subtitle_source_sha256"]==stamp["previous_subtitle_sha256"]
            and sha(ep/a10.EPOCH_REL)==stamp["previous_a10_ticket_sha256"]
            and sha(ep/a10.CANDIDATE_REL)==stamp["previous_a10_candidate_sha256"]
            and sha(ep/"docs/03_天界普通女生的一天_20张分镜修订草稿_V1.1.md")
               ==stamp["previous_storyboard_sha256"]
            and sha(ep/"docs/subtitles_V1.1.yaml")==stamp["previous_subtitle_sha256"]
            and sha(story)==stamp["story_sha256"]
            and sha(board)==stamp["storyboard_sha256"]
            and sha(ep/"docs/subtitles.yaml")==stamp["subtitle_source_sha256"]
            and sr._review_rubric_digest(Path(sr.__file__).read_text("utf-8-sig"))
               ==stamp["current_rubric_sha256"])
    except Exception:
        return False
