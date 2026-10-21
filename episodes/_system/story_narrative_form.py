#!/usr/bin/env python3
"""One authoritative narrative-form projection and locked-source review dispatch fence.

Never derive a new approval, mutate an Episode, or consume a model attempt here.
The bound Runtime Request is the source; old requests without an explicit form
use only a clear episodic *title* ("第N集") as a backward-compatible signal.
"""
from __future__ import annotations

import re
from pathlib import Path

import runtime_request

STANDALONE = "STANDALONE"
SERIAL_EPISODE = "SERIAL_EPISODE"
FORMS = {STANDALONE, SERIAL_EPISODE}
_EPISODE_TITLE = re.compile(r"第(?:[0-9]{1,3}|[一二三四五六七八九十百]+)集")


def from_request(request: dict | None) -> str:
    if not isinstance(request, dict):
        return STANDALONE
    explicit = request.get("narrative_form")
    if isinstance(explicit, dict):
        explicit = explicit.get("kind", "")
    if explicit is not None:
        if not isinstance(explicit, str) or explicit not in FORMS:
            raise ValueError("INVALID_NARRATIVE_FORM: expected STANDALONE or SERIAL_EPISODE")
        return explicit
    title = str((request.get("topic") or {}).get("title") or "")
    raw = str((request.get("provenance") or {}).get("original_request") or "")
    declaration = re.search(r"(?i)\bnarrative_form\s*[:=]\s*(STANDALONE|SERIAL_EPISODE)\b", raw)
    if declaration:
        return declaration.group(1).upper()
    if re.search(r"单集完结|单篇完结|独立完结", raw):
        return STANDALONE
    if re.search(r"连续剧|系列剧|分集作品", raw):
        return SERIAL_EPISODE
    return SERIAL_EPISODE if _EPISODE_TITLE.search(title) else STANDALONE


def for_episode(episode: Path) -> str:
    return from_request(runtime_request.authority_for_episode(Path(episode).resolve()))


def is_locked(request: dict | None) -> bool:
    story = (request or {}).get("story_input") or {}
    return (story.get("mode") == "locked_story"
            and story.get("allow_structure_rewrite") is False)


def failed_locked_review_block(episode: Path) -> str | None:
    """Block an already FAILED official Critic before another creative model call.

    A new source revision / rubric epoch must use its own explicit review authority.
    Neither a changed prompt nor another Driver start silently authorizes rewriting
    user-locked material or replaying a failed paid review.
    """
    episode = Path(episode).resolve()
    request = runtime_request.authority_for_episode(episode)
    if not is_locked(request):
        return None
    import story_review
    review = story_review.load_review(episode)
    if review is None:
        return None
    if not isinstance(review, dict):
        return "LOCKED_STORY_REVIEW_AUTHORITY_UNVERIFIED"
    if (review.get("summary") or {}).get("passed") is not False:
        return None
    try:
        story, board = story_review.story_paths(episode)
        same_source = (
            review.get("story_sha256") == story_review.sha256_file(story)
            and review.get("storyboard_sha256") == story_review.sha256_file(board)
        )
        subsha = review.get("subtitle_source_sha256")
        if subsha:
            captions = episode / "docs/subtitles.yaml"
            same_source = (same_source and captions.is_file()
                           and subsha == story_review.sha256_file(captions))
    except (OSError, ValueError, KeyError):
        same_source = False
    return ("LOCKED_STORY_REVIEW_FAILED_SOURCE_UNCHANGED_NEEDS_USER_DECISION"
            if same_source else
            "LOCKED_STORY_FAILED_REVIEW_SOURCE_DRIFT_NEEDS_EXPLICIT_REVISION_AUTHORITY")


def approved_review_dispatch_block(episode: Path) -> str | None:
    """Independent hard fence: an existing PASS is never an authoring permit.

    Only the DAG's deterministic source-rebind/state-transition recovery can
    advance an already approved Story. A broken official PASS must stop too,
    not silently spawn a new creative-model call.
    """
    import story_review
    episode = Path(episode).resolve()
    review = story_review.load_review(episode)
    if not isinstance(review, dict) or (review.get("summary") or {}).get("passed") is not True:
        return None
    if (not story_review.review_required(episode)
            or story_review.verify(episode)
            or review.get("issue_codes") != []):
        return "OFFICIAL_STORY_PASS_AUTHORITY_UNVERIFIED_NO_MODEL_REPLAY"
    return "OFFICIAL_STORY_ALREADY_PASS_DETERMINISTIC_RESUME_ONLY"


def main() -> int:
    # Read-only native-MySQL verification through scripts/storyos_production_env.py.
    import argparse
    import json
    parser = argparse.ArgumentParser(description="Read-only narrative form and story dispatch fence")
    parser.add_argument("episode")
    args = parser.parse_args()
    episode = Path(args.episode).resolve()
    result = {"narrative_form": for_episode(episode),
              "creative_model_block_reason": failed_locked_review_block(episode),
              "read_only": True, "model_calls": 0}
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
