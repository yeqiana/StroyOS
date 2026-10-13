#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Literal-only M00 storyboard evidence suggestions; NEVER Review Authority.

Deterministically surfaces exact source clauses and missing evidence. Even a
complete-looking candidate stays advisory: image meaning/continuity and source
event interpretation require the existing canonical Story/Frame Review.
"""
from __future__ import annotations

import hashlib
import json
import re

CUES = {
    "identity": ("人", "男子", "男生", "女生", "女性", "女孩", "老人", "孩子", "角色", "主角", "旅客", "人物", "person", "actor"),
    "wardrobe": ("衣", "外套", "裤", "鞋", "袖", "帽", "裙", "背包", "服饰", "衬衫", "jacket", "shirt", "dress", "shoes"),
    "props": ("车", "轮", "手机", "铅笔", "纸", "杯", "门把", "包", "桌", "椅", "屏", "票", "bicycle", "phone", "prop"),
    "geography": ("巷", "街", "墙", "门", "窗", "店", "楼", "树", "路", "海", "山", "房", "广场", "room", "street"),
    "photographer": ("摄影", "拍摄", "镜头", "机位", "视角", "手持", "左后", "右后", "相机", "camera", "viewpoint"),
    "lighting": ("光", "阴天", "黄昏", "夜晚", "傍晚", "晴", "日落", "台灯", "日光灯", "雨", "夜色", "light", "overcast"),
}
MOVEMENT = ("前进", "推进", "走", "迈", "推", "滚", "骑", "转", "跑", "驶", "移动", "跨", "抬", "起身", "打开", "合上", "伸手", "触碰", "驶入", "停下", "跳", "举", "靠近", "离开", "move", "walk", "roll", "step")
STILL = ("静止", "原地不动", "保持不动", "完全不动", "没有移动", "站着不动")
SUBJECT = {
    "bicycle": ("车", "轮", "自行车", "骑", "推车", "bicycle", "wheel"),
    "body": ("脚", "腿", "手", "身体", "人", "男", "女", "主角", "步", "person", "hand", "foot"),
    "object": ("门", "纸", "手机", "笔", "包", "椅", "屏", "窗", "door", "phone", "paper"),
}
MAX_CLAUSE = 220
MAX_CANDIDATES = 2


def _spans(source_text: str) -> list[str]:
    """Return bounded exact substrings; no rephrasing or external content."""
    text = str(source_text or "")
    raw = re.split(r"[，,。；;！？!?\n]+", text)
    found = []
    for fragment in raw:
        s = fragment.strip(" \t\r|")
        if 8 <= len(s) <= MAX_CLAUSE and s in text and s not in found:
            found.append(s)
    return found


def _hit(span: str, cues: tuple[str, ...]) -> bool:
    lowered = span.casefold()
    return any(token.casefold() in lowered for token in cues)


def _entry(*, text: str, source: str) -> dict:
    return {
        "source": source,
        "text": text,
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "permission": "SOURCE_QUOTE_NOT_VERIFIED_FACT",
    }


def analyze(*, story: str, previous: str, current: str, source: dict) -> dict:
    """Bounded source quotes, not an inferred physical-state story.

    Never derives authority from user-mode Codex login, generated pixels,
    arbitrary previous edits, or standalone draft annotations.
    """
    texts = {"previous": str(previous), "current": str(current), "story": str(story)}
    spans = {key: _spans(raw) for key, raw in texts.items()}
    locks, missing = {}, []
    for key, keywords in CUES.items():
        choices = [
            _entry(text=span, source=origin)
            for origin in ("previous", "current", "story")
            for span in spans[origin]
            if _hit(span, keywords)
        ]
        # Auto suggestions are raw quotes, not proven inter-frame invariants.
        locks[key] = choices[:2]
        if not choices:
            missing.append("locked:" + key)

    before = [s for s in spans["previous"] if _hit(s, MOVEMENT)]
    after = [s for s in spans["current"] if _hit(s, MOVEMENT)]
    paired = []
    used = set()
    for a in before:
        if len(paired) >= MAX_CANDIDATES:
            break
        for b in after:
            shared = [kind for kind, cues in SUBJECT.items()
                      if _hit(a, cues) and _hit(b, cues)]
            if a == b or not shared or (a, b) in used:
                continue
            used.add((a, b))
            paired.append({
                "id_hint": shared[0],
                "before": _entry(text=a, source="previous"),
                "after": _entry(text=b, source="current"),
                "pixel_evidence_hint": _entry(text=b, source="current"),
                "status": "CANDIDATE_NEEDS_CAUSAL_REVIEW",
            })
            break

    # Static mode may only be *suggested* where both beats explicitly say so.
    if any(_hit(s, STILL) for s in spans["previous"]) and any(
            _hit(s, STILL) for s in spans["current"]):
        mode_hint = "static"
    elif paired:
        mode_hint = "action"
    else:
        mode_hint = "UNKNOWN_NEEDS_REVIEW"
    if mode_hint == "action" and len(paired) < 2:
        missing.append("observable_changes:2_distinct_evidence_pairs")
    if mode_hint == "UNKNOWN_NEEDS_REVIEW":
        missing.append("mode:explicit_movement_or_stillness")
    return {
        "schema_version": 1,
        "status": "ADVISORY_SOURCE_QUOTES_ONLY",
        "story_sha256": source["story_sha256"],
        "storyboard_sha256": source["storyboard_sha256"],
        "previous_excerpt_sha256": source["previous_excerpt_sha256"],
        "current_excerpt_sha256": source["current_excerpt_sha256"],
        "locked_quote_candidates": locks,
        "observable_change_candidates": paired,
        "mode_hint": mode_hint,
        "missing_evidence": missing,
        "ready_for_source_attestation": False,
        "grants_review_authority": False,
        "generates_images": False,
    }
