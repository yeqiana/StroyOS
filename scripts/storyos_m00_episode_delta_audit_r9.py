#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only M00 Episode adjacent-state source/pixel check, never an Authority."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "episodes/_system"))

import frame_contract
import m00_episode_delta_review
import m00_episode_state_delta
import visual_profile


def inspect(*, episode: Path, frame: int, previous: Path | None = None,
            current: Path | None = None, review: dict | None = None) -> dict:
    ep = episode.resolve()
    if not ep.is_dir() or not ep.is_relative_to(ROOT):
        raise ValueError("M00_EPISODE_OUTSIDE_WORKSPACE")
    if frame <= 1:
        return {"status": "NO_ADJACENT_PREDECESSOR", "advisory_only": True}
    if (previous is None) != (current is None):
        raise ValueError("M00_EPISODE_PAIR_REQUIRES_TWO_IMAGES")
    profile = visual_profile.compile_prompt_contract(ep)["profile_id"]
    _story_path, storyboard = frame_contract.artifact_paths(ep)
    source = m00_episode_state_delta.source_transition(storyboard, frame, profile, episode=ep)
    if source is None:
        return {"status": "NOT_EXPLICITLY_OPTED_IN", "advisory_only": True}
    if previous is None:
        return {"status": "SOURCE_LOCKED_AWAITING_PIXELS", "frame": source["frame"],
                "delta_sha256": source["delta_sha256"],
                "source_frame_sha256": source["frame_excerpt_sha256"],
                "previous_frame_sha256": source["previous_frame_excerpt_sha256"],
                "advisory_only": True, "grants_visual_lock_pass": False}
    before = ep / previous if not previous.is_absolute() else previous
    after = ep / current if not current.is_absolute() else current
    return {"frame": source["frame"], **m00_episode_delta_review.inspect_pair(
        episode=ep, previous_image=before, current_image=after,
        locked_delta=source["delta"], review=review)}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("episode")
    p.add_argument("--frame", type=int, required=True)
    p.add_argument("--previous-image", type=Path)
    p.add_argument("--current-image", type=Path)
    p.add_argument("--review", type=Path)
    args = p.parse_args()
    review = json.loads(args.review.read_text(encoding="utf-8")) if args.review else None
    result = inspect(episode=Path(args.episode), frame=args.frame,
                     previous=args.previous_image, current=args.current_image, review=review)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
