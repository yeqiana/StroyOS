"""Opaque, local-only previews of UNREVIEWED image candidates (never publish authority)."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re

SOURCE = "local_workspace_unreviewed_candidates"
CATALOG_PATH = "/api/v1/local-media/candidates"
IMAGE_PREFIX = "/api/v1/local-media/candidate-images/"
NAME = re.compile(r"^([0-9]{2})-(?:[0-9]{8,12}|[a-f0-9]{8,64}-a[0-9]+)\.(png|jpg|jpeg|webp)$", re.I)
TOKEN = re.compile(r"^[0-9a-f]{32}$")
MAX_BYTES = 12 * 1024 * 1024
TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


def valid_header(header: bytes, suffix: str) -> bool:
    if suffix == ".png":
        return header.startswith(b"\x89PNG\r\n\x1a\n")
    if suffix in (".jpg", ".jpeg"):
        return header.startswith(b"\xff\xd8\xff")
    return suffix == ".webp" and header[:4] == b"RIFF" and header[8:12] == b"WEBP"


class LocalCandidateMedia:
    """Read-only, scoped to canonical Episode directories and unreviewed sources."""

    def __init__(self, service) -> None:
        self.service = service

    def scan(self) -> tuple[list[dict], dict[str, Path]]:
        rows, _errors = self.service._load()
        catalog: list[dict] = []
        tokens: dict[str, Path] = {}
        for row in rows:
            directory = self.service._episode_dir(row["_namespace"])
            if directory is None:
                continue
            latest: tuple[float, int, str] | None = None
            count = 0
            for relative_folder in ("media/raw", "media/candidates/scheduled"):
                folder = directory / relative_folder
                try:
                    if (not folder.is_dir() or folder.is_symlink()
                            or not folder.resolve(strict=True).is_relative_to(directory)):
                        continue
                    folder_real = folder.resolve(strict=True)
                    for file in folder.iterdir():
                        match = NAME.fullmatch(file.name)
                        if not match or file.is_symlink() or not file.is_file():
                            continue
                        resolved = file.resolve(strict=True)
                        if not resolved.is_relative_to(folder_real):
                            continue
                        stat = resolved.stat()
                        if not 0 < stat.st_size <= MAX_BYTES:
                            continue
                        with resolved.open("rb") as reader:
                            header = reader.read(12)
                        if not valid_header(header, resolved.suffix.lower()):
                            continue
                        relative = resolved.relative_to(self.service.episodes).as_posix()
                        token = hashlib.sha256(("candidate:" + relative).encode()).hexdigest()[:32]
                        tokens[token] = resolved
                        count += 1
                        if latest is None or stat.st_mtime > latest[0]:
                            latest = (stat.st_mtime, int(match.group(1)), token)
                except OSError:
                    continue
            if latest is not None:
                catalog.append({
                    "episode_ref": row["episode_ref"],
                    "title": row["title"],
                    "business_episode_id": row["business_episode_id"],
                    "source": SOURCE,
                    "candidate_count": count,
                    "preview": {
                        "frame": latest[1],
                        "url": IMAGE_PREFIX + latest[2],
                        "updated_at": datetime.fromtimestamp(latest[0], timezone.utc).isoformat(),
                    },
                })
        return catalog, tokens

    def image(self, token: str) -> tuple[bytes, str] | None:
        if not TOKEN.fullmatch(token):
            return None
        _, index = self.scan()  # revalidate identity/path/magic on every request
        path = index.get(token)
        if path is None:
            return None
        try:
            if not 0 < path.stat().st_size <= MAX_BYTES:
                return None
            data = path.read_bytes()
            if not 0 < len(data) <= MAX_BYTES or not valid_header(data[:12], path.suffix.lower()):
                return None
            return data, TYPES[path.suffix.lower()]
        except OSError:
            return None
