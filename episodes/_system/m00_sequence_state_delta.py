#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M00 adjacent-frame physical-state delta (genre neutral, advisory-only).

No invented story beats: only an explicitly provided frozen transition may
supply states. A static beat is valid. Every action difference needs pixel proof.
"""
from __future__ import annotations

import hashlib
import json

_LOCK_KEYS = ("identity", "wardrobe", "props", "geography", "photographer", "lighting")
_FORBIDDEN = ("待补充", "待定义", "由故事定义", "some anomaly")


def canonical(contract: dict) -> dict:
    if not isinstance(contract, dict) or contract.get("schema_version") != 1:
        raise ValueError("M00_DELTA_SCHEMA_INVALID")
    locks = contract.get("locked")
    if not isinstance(locks, dict) or set(locks) != set(_LOCK_KEYS):
        raise ValueError("M00_DELTA_LOCKS_INCOMPLETE")
    for key, value in locks.items():
        if not isinstance(value, str) or len(value.strip()) < 8:
            raise ValueError("M00_DELTA_LOCK_INVALID:" + key)
    mode = contract.get("mode")
    changes = contract.get("observable_changes")
    if mode not in ("action", "static") or not isinstance(changes, list):
        raise ValueError("M00_DELTA_MODE_INVALID")
    if mode == "static" and changes:
        raise ValueError("M00_DELTA_STATIC_SHOULD_NOT_FORCE_ACTION")
    if mode == "action" and not 2 <= len(changes) <= 8:
        raise ValueError("M00_DELTA_OBSERVABLE_ACTION_REQUIRED")
    seen = set()
    for row in changes:
        if not isinstance(row, dict) or set(row) != {"id", "before", "after", "pixel_evidence"}:
            raise ValueError("M00_DELTA_CHANGE_FIELDS_INVALID")
        key = row["id"]
        if not isinstance(key, str) or not key or key in seen:
            raise ValueError("M00_DELTA_DUPLICATE_OR_EMPTY_CHANGE")
        seen.add(key)
        for field in ("before", "after", "pixel_evidence"):
            text = row[field]
            if not isinstance(text, str) or len(text.strip()) < 8 or any(f in text for f in _FORBIDDEN):
                raise ValueError("M00_DELTA_UNDEFINED_CHANGE")
        if row["before"].strip() == row["after"].strip():
            raise ValueError("M00_DELTA_NO_STATE_CHANGE")
    return {"schema_version": 1, "mode": mode, "locked": dict(locks),
            "observable_changes": [dict(row) for row in changes]}


def contract_sha256(contract: dict) -> str:
    return hashlib.sha256(json.dumps(canonical(contract), ensure_ascii=False,
                                     sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def prompt_suffix(contract: dict) -> str:
    data = canonical(contract)
    lines = ["[M00 LOCKED ADJACENT STATE TRANSITION]",
             "Previous photograph is an identity/scene reference, NOT a pose or frame template.",
             "Do not copy its pose, wheel location or exact composition when the next story beat changes.",
             "Never replace fixed building geometry, doors, shopfronts, background objects or the photographer's physical side.",
             "The camera may move only as far as the locked story/photographer permits.",
             "Treat one frame as one ordinary plausible exposure, not a movie storyboard collage."]
    lines += [f"LOCKED_{key.upper()}={value}" for key,value in data["locked"].items()]
    lines.append("BEAT_MODE=" + data["mode"])
    if data["mode"] == "static":
        lines.append("A static scene is intended: preserve stillness; do not invent movement, action, blur, shake or an anomaly.")
    else:
        lines.append("The next photograph MUST visibly differ by only the story-authorized physical state changes below:")
        lines += [f"CHANGE_{c['id']} BEFORE={c['before']} AFTER={c['after']} "
                  f"VERIFY_IN_PIXELS={c['pixel_evidence']}" for c in data["observable_changes"]]
        lines.append("Retaining the same actor/vehicle but duplicating their prior pose is NOT a successful action beat.")
    lines.append("Never add artificial film damage or motion blur unless shutter/subject motion causes it.")
    lines.append("[END M00 LOCKED ADJACENT STATE TRANSITION]")
    return "\n".join(lines)
