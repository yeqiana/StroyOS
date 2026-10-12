"""Lossless, single-writer rotation for Phase9 worker tick telemetry only.

Never touches incident alerts, MySQL, Episode, trace, or review evidence.
Rotated raw files are preserved on compression failure; archives are never deleted.
Do not use with multiple processes writing the same tick-log path.
"""
from __future__ import annotations

import gzip
import hashlib
import os
import shutil
import time
from pathlib import Path


def _sha256(path: Path, *, compressed: bool = False) -> str:
    digest = hashlib.sha256()
    opener = gzip.open if compressed else open
    with opener(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def maybe_rotate_tick_log(path: Path, *, max_bytes: int) -> Path | None:
    """Move full tick log into durable gzip archive on a size boundary.

    Fail-closed if path is symlink or an unexpected existing archive is present.
    Compression errors retain the renamed raw snapshot, never drop records.
    Caller is the sole writer and must invoke before the next append.
    """
    path = Path(path)
    if max_bytes <= 0 or not path.exists():
        return None
    if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
        raise ValueError("tick log must be a regular file, not a link")
    if not path.is_file() or path.stat().st_size < max_bytes:
        return None
    archive_dir = path.parent / "tick-archives"
    archive_dir.mkdir(parents=True, exist_ok=True)
    unique = f"{time.time_ns()}-{os.getpid()}"
    raw = archive_dir / f"{path.stem}.{unique}.jsonl"
    gz = archive_dir / (raw.name + ".gz")
    temp = archive_dir / (raw.name + ".gz.part")
    if any(item.exists() for item in (raw, gz, temp)):
        raise FileExistsError("tick archive path already exists")
    # A rename preserves every already appended record even on compressor failure.
    path.rename(raw)
    try:
        original_digest = _sha256(raw)
        with raw.open("rb") as source, temp.open("xb") as target:
            with gzip.GzipFile(fileobj=target, mode="wb", filename="", mtime=0) as encoded:
                shutil.copyfileobj(source, encoded, length=1024 * 1024)
            target.flush()
            os.fsync(target.fileno())
        if _sha256(temp, compressed=True) != original_digest:
            raise OSError("tick archive integrity verification failed")
        temp.replace(gz)
        raw.unlink()
        return gz
    except Exception:
        # Keep raw snapshot for audit/recovery. Never remove an unverified original.
        temp.unlink(missing_ok=True)
        return raw
