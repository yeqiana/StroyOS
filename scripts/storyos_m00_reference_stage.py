#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage exact original user captures into private local StoryOS reference storage.

No Episode mutation, production/Attempt reservation, Prompt mutation, DB calls,
or image provider calls. The manifest is created from real user-uploaded bytes
outside this repository, never from generation examples in Story contracts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET_REL = Path(".storyos/user-visual-references")
ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fp:
        for part in iter(lambda: fp.read(1 << 20), b""):
            h.update(part)
    return h.hexdigest()


def prepare(source_dir: Path, manifest: Path, root: Path = ROOT, *, apply: bool = False) -> dict:
    data = json.loads(manifest.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or data.get("schema_version") != 1 or not isinstance(data.get("uploads"), list) or not data["uploads"]:
        raise ValueError("M00_USER_REFERENCE_MANIFEST_INVALID")
    sources = source_dir.resolve()
    root = root.resolve()
    target_dir = (root / TARGET_REL).resolve()
    if not target_dir.is_relative_to(root):
        raise ValueError("M00_REFERENCE_OUTPUT_OUTSIDE_ROOT")
    seen_ids = set()
    entries = []
    for entry in data["uploads"]:
        if not isinstance(entry, dict):
            raise ValueError("M00_REFERENCE_ENTRY_INVALID")
        name, expected, sid = entry.get("filename"), entry.get("sha256"), entry.get("source_attachment_id")
        if (not isinstance(name, str) or not isinstance(expected, str)
                or not isinstance(sid, str) or not sid.startswith("file_")
                or len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected.lower())):
            raise ValueError("M00_REFERENCE_SOURCE_INVALID")
        if sid in seen_ids:
            raise ValueError("M00_REFERENCE_SOURCE_DUPLICATE")
        seen_ids.add(sid)
        rel = Path(name)
        if rel.name != name or name in {".", ".."} or rel.suffix.lower() not in ALLOWED_EXT:
            raise ValueError("M00_REFERENCE_SOURCE_PATH_UNSAFE")
        src = (sources / name).resolve()
        if not src.is_relative_to(sources) or not src.is_file():
            raise ValueError("M00_REFERENCE_SOURCE_MISSING")
        digest = sha256(src)
        if digest != expected.lower():
            raise ValueError("M00_REFERENCE_SOURCE_SHA_MISMATCH")
        from PIL import Image
        with Image.open(src) as im:
            im.verify()
        dst = target_dir / (digest[:16] + rel.suffix.lower())
        if dst.is_file() and sha256(dst) != digest:
            raise ValueError("M00_REFERENCE_TARGET_DRIFT")
        entries.append({
            "source_attachment_id": sid, "source": src, "target": dst,
            "path": dst.relative_to(root).as_posix(), "sha256": digest,
        })
    if apply:
        target_dir.mkdir(parents=True, exist_ok=True)
        for row in entries:
            if row["target"].exists():
                continue
            temporary = row["target"].with_suffix(row["target"].suffix + ".staging")
            try:
                with row["source"].open("rb") as reader, temporary.open("xb") as writer:
                    shutil.copyfileobj(reader, writer)
                if sha256(temporary) != row["sha256"]:
                    raise ValueError("M00_REFERENCE_COPY_SHA_MISMATCH")
                os.replace(temporary, row["target"])
            finally:
                temporary.unlink(missing_ok=True)
    return {
        "status": "STAGED" if apply else "PREFLIGHT_ONLY",
        "writes_episode": False, "uses_image_provider": False,
        "references_bound_to_episode": False,
        "reference_count": len(entries),
        "items": [{
            "path": row["path"], "sha256": row["sha256"],
            "source_attachment_id": row["source_attachment_id"],
            "kind": "capture_style", "origin": "direct_user_upload",
            "reference_use": "capture_appearance_only",
            "decision": "locked",
        } for row in entries],
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="SHA-locked private M00 capture-reference staging")
    p.add_argument("--source-dir", type=Path, required=True)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--apply", action="store_true", help="copy only into private .storyos storage")
    a = p.parse_args(argv)
    try:
        report = prepare(a.source_dir, a.manifest, apply=a.apply)
    except (OSError, ValueError, ImportError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
