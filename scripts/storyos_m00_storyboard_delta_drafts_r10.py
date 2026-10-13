#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prepare source-quoted M00 adjacent-frame delta drafts without creative writes.

Dry-run by default. --apply creates only missing DRAFT_ONLY sidecars. Never
changes the storyboard/story or turns them into a formal PASS.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "episodes/_system"))
import frame_contract
import m00_storyboard_delta_sources as source
import m00_episode_state_delta
import visual_profile


def prepare(ep: Path, *, apply: bool = False) -> dict:
    ep = ep.resolve()
    if not ep.is_relative_to(ROOT.resolve()) or not ep.is_dir():
        raise ValueError("M00_DELTA_EPISODE_OUTSIDE_REPO")
    story, board = frame_contract.artifact_paths(ep)
    if visual_profile.compile_prompt_contract(ep)["profile_id"] != "M00":
        return {"status": "NOT_M00", "created": 0, "pending": []}
    return source.prepare_drafts(episode=ep, story=story, storyboard=board,
                                 count=frame_contract.frame_count(ep), apply=apply)


def main() -> int:
    arg = argparse.ArgumentParser()
    arg.add_argument("episode")
    arg.add_argument("--apply", action="store_true")
    opts = arg.parse_args()
    print(json.dumps(prepare(Path(opts.episode), apply=opts.apply), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
