#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Project *explicit*, storyboard-locked M00 adjacent-state evidence.

No additional creative authority or new story event is granted. Existing
Episode contract hashes stay identical when the storyboard does not opt in.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import m00_sequence_state_delta as delta

FIELD = "m00_adjacent_state_delta"
BEG = "[M00 LOCKED ADJACENT STATE TRANSITION]"
END = "[END M00 LOCKED ADJACENT STATE TRANSITION]"


def source_transition(storyboard: Path, frame: int, profile_id: str,
                      *, episode: Path | None = None) -> dict | None:
    """Read one authorized JSON storyboard frame; no unrelated/global fallback.

    Deliberately no Markdown parsing or LLM guessing: if not explicitly locked
    in a JSON frame, there is no opt-in and no imposed motion.
    """
    if str(profile_id) != "M00":
        return None
    # R10: the locked Markdown/JSON source is never rewritten. Source-attested
    # derivative only appears when an Episode opts in with exact source SHAs.
    if episode is not None:
        import m00_storyboard_delta_sources as source_rows
        ep = Path(episode).resolve()
        path = source_rows.candidate_path(ep, frame)
        if path.is_file():
            if storyboard.suffix.lower() == ".json":
                from frame_contract import _frame_from_json
                doc = json.loads(storyboard.read_text(encoding="utf-8-sig"))
                current = _frame_from_json(doc, frame)
                if isinstance(current, dict) and FIELD in current:
                    raise ValueError("M00_DELTA_AMBIGUOUS_DUAL_SOURCE")
            from frame_contract import artifact_paths
            story_path, official_board = artifact_paths(ep)
            if official_board.resolve() != storyboard.resolve():
                raise ValueError("M00_DELTA_STORYBOARD_NOT_MANIFEST_SOURCE")
            attested = source_rows.approve_source_bound(
                document=json.loads(path.read_text(encoding="utf-8-sig")),
                story=story_path, storyboard=storyboard, frame=frame)
            # This sidecar is *never* a replacement for the canonical Story
            # Review. Bind the editorial source decision to the live approved
            # Story Review authority; no ad-hoc/mock PASS in production.
            import story_review
            if not story_review.review_required(ep):
                raise ValueError("M00_DELTA_CANONICAL_STORY_REVIEW_REQUIRED")
            errors = story_review.verify(ep)
            if errors:
                raise ValueError("M00_DELTA_CANONICAL_STORY_REVIEW_INVALID: " + "; ".join(errors[:3]))
            review_sha = story_review.review_authority_sha256(ep)
            witness = json.loads(path.read_text(encoding="utf-8-sig")).get("editorial_attestation") or {}
            if (not review_sha or witness.get("story_review_authority_sha256") != review_sha):
                raise ValueError("M00_DELTA_STORY_REVIEW_AUTHORITY_SHA_MISMATCH")
            return {
                "frame": f"{frame:02d}", "previous_frame": f"{frame - 1:02d}",
                "delta": attested["delta"], "delta_sha256": attested["delta_sha256"],
                "frame_excerpt_sha256": attested["source"]["current_excerpt_sha256"],
                "previous_frame_excerpt_sha256": attested["source"]["previous_excerpt_sha256"],
                "source_format": attested["source_format"],
                "source_attestation_sha256": attested["attestation_sha256"],
                "source_document_sha256": source_rows.digest(path),
                "story_sha256": attested["source"]["story_sha256"],
                "storyboard_sha256": attested["source"]["storyboard_sha256"],
            }
    if storyboard.suffix.lower() != ".json":
        return None
    # A storyboard already bound by the release manifest is the only source.
    from frame_contract import _frame_from_json, extract_frame_excerpt

    source = json.loads(storyboard.read_text(encoding="utf-8-sig"))
    row = _frame_from_json(source, frame)
    if not isinstance(row, dict) or FIELD not in row:
        return None
    if frame <= 1:
        raise ValueError("M00_EPISODE_DELTA_REQUIRES_PREDECESSOR")
    if not isinstance(row[FIELD], dict):
        raise ValueError("M00_EPISODE_DELTA_MUST_BE_OBJECT")
    evidence = extract_frame_excerpt(storyboard, frame)
    previous = extract_frame_excerpt(storyboard, frame - 1)
    if evidence["mode"] != "json_frame" or previous["mode"] != "json_frame":
        raise ValueError("M00_EPISODE_DELTA_FRAME_SOURCE_NOT_LOCALIZED")
    normalized = delta.canonical(row[FIELD])
    sha = delta.contract_sha256(normalized)
    return {
        "frame": f"{frame:02d}",
        "previous_frame": f"{frame - 1:02d}",
        "delta": normalized, "delta_sha256": sha,
        "frame_excerpt_sha256": evidence["sha256"],
        "previous_frame_excerpt_sha256": previous["sha256"],
        "source_format": "locked_json_storyboard_frame",
    }


def project_final_prompt(*, scene_prompt: str, controller_input: dict,
                         is_m00: bool) -> str:
    """Put source-owned state transitions into the *final* Provider payload.

    Reject mismatched/forged statements even when a text-only Controller
    seemingly succeeded. This function never requests a model or pixels.
    """
    original = str(scene_prompt or "")
    contract = str(controller_input.get("frame_prompt_contract") or "")
    row = controller_input.get(FIELD)
    sha = controller_input.get("m00_adjacent_state_delta_sha256")
    contains_authorized = BEG in contract or END in contract
    if not is_m00:
        if row is not None or sha is not None:
            raise ValueError("M00_EPISODE_DELTA_WRONG_VISUAL_PROFILE")
        return original
    if row is None and sha is None:
        if contains_authorized:
            raise ValueError("M00_EPISODE_DELTA_AUTHORITY_PROJECTION_MISSING")
        if BEG in original or END in original:
            raise ValueError("M00_EPISODE_DELTA_UNAUTHORIZED_CONTROLLER_INSERTION")
        return original
    if not isinstance(row, dict) or not isinstance(sha, str) or sha != delta.contract_sha256(row):
        raise ValueError("M00_EPISODE_DELTA_SHA_MISMATCH")
    text = delta.prompt_suffix(row)
    if contract.count(text) != 1 or contract.count(BEG) != 1 or contract.count(END) != 1:
        raise ValueError("M00_EPISODE_DELTA_FRAME_CONTRACT_MISMATCH")
    if BEG in original or END in original:
        raise ValueError("M00_EPISODE_DELTA_CONTROLLER_INJECTION")
    return original.rstrip() + "\n\n" + text
