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
    total = frame_contract.frame_count(ep)
    pending, prepared, created, existed = [], [], 0, 0
    # Preflight the entire source before touching any episode-owned draft.
    for n in range(2, total + 1):
        # Do not shadow already-locked JSON Frame Contract deltas.
        if board.suffix.lower() == ".json":
            if m00_episode_state_delta.source_transition(board, n, "M00") is not None:
                continue
        proposal = source.proposal(story=story, storyboard=board, frame=n)
        path = source.candidate_path(ep, n)
        if path.exists():
            existed += 1
            continue
        pending.append({"frame": f"{n:02d}", "path": path.relative_to(ep).as_posix(),
                        "previous_excerpt_sha256": proposal["source"]["previous_excerpt_sha256"],
                        "current_excerpt_sha256": proposal["source"]["current_excerpt_sha256"]})
        prepared.append((path, proposal))
    if apply:
        for path, proposal in prepared:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("x", encoding="utf-8", newline="\n") as handle:
                json.dump(proposal, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            created += 1
    return {"status": "DRAFTS_CREATED_NO_AUTHORITY" if apply else "DRY_RUN",
            "created": created, "existing_untouched": existed, "pending": pending,
            "formal_generation_calls": 0, "formal_authority_granted": False}


def main() -> int:
    arg = argparse.ArgumentParser()
    arg.add_argument("episode")
    arg.add_argument("--apply", action="store_true")
    opts = arg.parse_args()
    print(json.dumps(prepare(Path(opts.episode), apply=opts.apply), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
