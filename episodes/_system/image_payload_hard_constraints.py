"""Deterministically preserve frozen Frame Contract obligations in final image payload.

No model, Provider, state writes, or additional review. The source is the
already-compiled, SHA-bound frame_prompt_contract given to Image Controller.
"""
from __future__ import annotations
import hashlib
import re

BEGIN = "[STORYOS FROZEN FRAME OBLIGATIONS]"
END = "[END STORYOS FROZEN FRAME OBLIGATIONS]"
MAX_BYTES = 32_000
SECTIONS = (
    "STORYBOARD FRAME",
    "CHARACTER / POV CONTRACT",
    "CHARACTER VISUAL / ORIGINAL IDENTITY",
    "CHARACTER APPEARANCE ANCHOR V2.2.1",
    "WORLD IDENTITY V2.2.1",
    "CAPTURE EVENT",
    "SHOT PROGRESSION / ACTION / ANOMALY LOGIC",
    "TEMPORAL CONTINUITY",
    "SCENE-AWARE WARDROBE",
    "FRAME DIRECTIVE",
)
SECTION_PATTERN = re.compile(r"^\[([A-Z][A-Z0-9 /._-]+)\]\s*$", re.M)


def frozen_projection(frame_contract: str) -> str:
    """Extract existing exact source blocks, never ask Controller to rewrite them."""
    source = str(frame_contract or "").strip()
    if not source:
        raise ValueError("IMAGE_FROZEN_FRAME_CONTRACT_MISSING")
    matches = list(SECTION_PATTERN.finditer(source))
    parts = []
    for index, match in enumerate(matches):
        if match.group(1) not in SECTIONS:
            continue
        stop = matches[index + 1].start() if index + 1 < len(matches) else len(source)
        value = source[match.end():stop].strip()
        if value and value not in {"{}", "null", "[]"}:
            parts.append(f"[{match.group(1)}]\n{value}")
    if not parts:
        # Compatibility for test-era minimal contracts; still preserve the
        # exact source instead of silently discarding obligations.
        parts = [source]
    body = "\n\n".join(parts)
    if len(body.encode("utf-8")) > MAX_BYTES:
        raise ValueError("IMAGE_FROZEN_FRAME_CONTEXT_TOO_LARGE")
    return body


def inject(scene_prompt: str, frame_contract: str, *,
           original_scene: str = "", m00: bool = False) -> str:
    scene = str(scene_prompt or "").strip()
    if not scene:
        raise ValueError("IMAGE_FINAL_SCENE_PROMPT_MISSING")
    if BEGIN in scene or END in scene:
        raise ValueError("IMAGE_FROZEN_FRAME_BLOCK_INJECTION")
    source = str(frame_contract or "").strip()
    body = frozen_projection(source)
    if not m00:
        original = str(original_scene or "").strip()
        if original:
            body = "[ORIGINAL SCENE FACTS]\n" + original + "\n\n" + body
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    return (scene + "\n\n" + BEGIN + "\n" +
            "The following are immutable scene/identity/camera facts, not "
            "optional aesthetic preferences. Do not change them.\n" +
            "source_frame_contract_sha256=" + digest + "\n" +
            body + "\n" + END)
