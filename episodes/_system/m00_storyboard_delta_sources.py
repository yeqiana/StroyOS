#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Non-generating storyboard delta drafts and SOURCE-ATTESTED admissions.

Markdown table and JSON storyboards stay immutable. Drafts are incomplete by
design: do not invent events absent from the reviewed story and storyboard.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import m00_sequence_state_delta as delta

REL = Path("meta/runtime/m00-adjacent-state-deltas")
TABLE = re.compile(r"^\|\s*(\d{1,3})\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*$")
SOURCE_KEYS = ("identity", "wardrobe", "props", "geography", "photographer", "lighting")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def excerpts(storyboard: Path, frame: int) -> tuple[str, str, str]:
    from frame_contract import _frame_from_json, extract_frame_excerpt
    if frame <= 1:
        raise ValueError("M00_DELTA_PREVIOUS_FRAME_REQUIRED")
    if storyboard.suffix.lower() == ".json":
        doc = json.loads(storyboard.read_text(encoding="utf-8-sig"))
        one = _frame_from_json(doc, frame - 1)
        two = _frame_from_json(doc, frame)
        if not isinstance(one, dict) or not isinstance(two, dict):
            raise ValueError("M00_DELTA_FRAME_NOT_FOUND")
        # Exact source text: encode JSON as it exists, no invented subject.
        p, c = (json.dumps(row, ensure_ascii=False, sort_keys=True) for row in (one, two))
        return p, c, "json_frame"
    if storyboard.suffix.lower() != ".md":
        raise ValueError("M00_DELTA_STORYBOARD_FORMAT_UNSUPPORTED")
    rows: dict[int, str] = {}
    for line in storyboard.read_text(encoding="utf-8-sig").splitlines():
        found = TABLE.fullmatch(line.strip())
        if not found:
            continue
        number = int(found.group(1))
        if number in rows:
            raise ValueError("M00_DELTA_DUPLICATE_STORYBOARD_FRAME")
        # Preserve both narrative meaning and photography instructions verbatim.
        rows[number] = found.group(2).strip() + " | " + found.group(3).strip()
    if frame - 1 not in rows or frame not in rows:
        raise ValueError("M00_DELTA_FRAME_NOT_FOUND")
    if not rows[frame - 1].strip(" |") or not rows[frame].strip(" |"):
        raise ValueError("M00_DELTA_EMPTY_BEAT")
    return rows[frame - 1], rows[frame], "markdown_table"


def proposal(*, story: Path, storyboard: Path, frame: int) -> dict:
    prev, curr, fmt = excerpts(storyboard, frame)
    if not story.is_file() or not story.read_text(encoding="utf-8-sig").strip():
        raise ValueError("M00_DELTA_STORY_MISSING")
    return {
        "schema_version": 1, "status": "DRAFT_ONLY", "frame": f"{frame:02d}",
        "authority": "SOURCE_QUOTATIONS_ONLY_NOT_A_REVIEW_PASS",
        "source": {
            "story_sha256": digest(story), "storyboard_sha256": digest(storyboard),
            "previous_excerpt_sha256": hashlib.sha256(prev.encode("utf-8")).hexdigest(),
            "current_excerpt_sha256": hashlib.sha256(curr.encode("utf-8")).hexdigest(),
            "format": fmt,
        },
        "evidence": {"previous": prev, "current": curr},
        "delta": {"schema_version": 1, "mode": "action",
                  "locked": {k: "" for k in SOURCE_KEYS},
                  "observable_changes": []},
        "editorial_attestation": None,
    }


def approve_source_bound(*, document: dict, story: Path, storyboard: Path,
                         frame: int) -> dict:
    """Prove every narrative assertion already exists in an exact source.

    Editorial judgment/attestation cannot replace Story Review Authority. Any
    missing source, prior/current mismatch, novel object, or stale hash blocks.
    """
    snapshot = proposal(story=story, storyboard=storyboard, frame=frame)
    if (not isinstance(document, dict)
            or document.get("schema_version") != 1
            or document.get("status") != "SOURCE_ATTESTED"
            or document.get("frame") != snapshot["frame"]
            or document.get("source") != snapshot["source"]
            or document.get("evidence") != snapshot["evidence"]):
        raise ValueError("M00_DELTA_SOURCE_SHA_OR_EXCERPT_DRIFT")
    witness = document.get("editorial_attestation")
    if (not isinstance(witness, dict) or witness.get("decision") != "ACCEPT"
            or not str(witness.get("reviewer") or "").strip()
            or not str(witness.get("reason") or "").strip()
            or witness.get("source_storyboard_sha256") != snapshot["source"]["storyboard_sha256"]):
        raise ValueError("M00_DELTA_EDITORIAL_ATTESTATION_REQUIRED")
    material = delta.canonical(document.get("delta"))
    prior, current = snapshot["evidence"]["previous"], snapshot["evidence"]["current"]
    full_story = story.read_text(encoding="utf-8-sig")
    # Exact source spans, no self-authored paraphrase pretending to be source.
    for key, value in material["locked"].items():
        if value not in prior and value not in current and value not in full_story:
            raise ValueError("M00_DELTA_UNSUPPORTED_LOCK:" + key)
    for change in material["observable_changes"]:
        # Causal state cannot be borrowed from some other moment in the
        # story: before belongs to the previous beat; after/evidence belong
        # to this exact beat. Story-wide context is reserved for stable locks.
        for key, allowed in (("before", prior),
                             ("after", current),
                             ("pixel_evidence", current)):
            if change[key] not in allowed:
                raise ValueError("M00_DELTA_UNSUPPORTED_ACTION:" + change["id"] + ":" + key)
    return {
        "delta": material, "delta_sha256": delta.contract_sha256(material),
        "source": snapshot["source"],
        "source_format": "source_attested_" + snapshot["source"]["format"],
        "attestation_sha256": hashlib.sha256(json.dumps(
            witness, ensure_ascii=False, sort_keys=True,
            separators=(",", ":")).encode("utf-8")).hexdigest(),
    }


def candidate_path(episode: Path, frame: int) -> Path:
    return episode / REL / f"{frame:02d}.json"
