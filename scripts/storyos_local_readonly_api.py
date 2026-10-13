"""本地 StoryOS 作品状态文件的只读 HTTP 投影。

输入只来自显式指定的 workspace/episodes/**/meta/episode-state.json。
不连接 MySQL/Redis、不修改文件、不推断 Worker 心跳、分账/发布或运行态。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit
import sys

# 直接通过 Python 路径启动脚本时，让项目内 platform.api 优先于同名 stdlib module。
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from platform.api.controllers import RuntimeStatusApiController, RuntimeAuthorityApiController
from platform.operations.runtime_authority_evidence import RuntimeAuthorityEvidenceService
from platform.api.http_server import PlatformApiDispatcher, PlatformApiRequestHandler, build_http_server
from platform.operations.local_episode_monitoring import read_recorded_production
from platform.operations.local_mysql_monitor_readonly import observe_mysql_episode, empty as empty_mysql_monitor
from platform.operations.local_worker_heartbeat_readonly import observe_local_redis_heartbeats

SOURCE = "local_workspace_episode_state_file"


class LocalEpisodeFileStatuses:
    def __init__(self, workspace: str | Path) -> None:
        self.root = Path(workspace).expanduser().resolve(strict=True)
        self.episodes = (self.root / "episodes").resolve(strict=True)
        if not self.episodes.is_dir() or not self.episodes.is_relative_to(self.root):
            raise ValueError("workspace must have episodes directory")

    def _production_state_files(self):
        """Only canonical production Episode states, not tests or archives."""
        for state_file in sorted(self.episodes.glob("*/**/meta/episode-state.json")):
            try:
                parts = state_file.relative_to(self.episodes).parts
                if len(parts) != 4 or any(part.startswith(("_", ".")) for part in parts):
                    continue
                if state_file.is_symlink() or not state_file.is_file():
                    continue
                if any(parent.is_symlink() for parent in (
                    state_file.parent, state_file.parent.parent, state_file.parent.parent.parent
                )):
                    continue
                resolved = state_file.resolve(strict=True)
                if resolved.is_relative_to(self.episodes):
                    yield resolved
            except OSError:
                continue

    def _load(self) -> tuple[list[dict], list[str]]:
        rows: list[dict] = []
        errors: list[str] = []
        for state_file in self._production_state_files():
            resolved = state_file
            relative = resolved.relative_to(self.episodes).as_posix()
            try:
                state = json.loads(resolved.read_text(encoding="utf-8"))
                if not isinstance(state, dict):
                    raise ValueError("state must be object")
                stage = state.get("current_state")
                if not isinstance(stage, str) or not stage.strip():
                    raise ValueError("no recorded current_state")
                identity = "LOCAL_" + hashlib.sha256(relative.encode("utf-8")).hexdigest()[:24]
                rows.append({
                    "schema_version": 1,
                    "projection_level": "summary",
                    "episode_id": identity,
                    "episode_ref": identity,
                    "business_episode_id": str(state.get("episode_id") or ""),
                    "series": str(state.get("series") or ""),
                    "title": str(state.get("title") or state_file.parent.parent.name),
                    "production_stage": stage,
                    "state_source": SOURCE,
                    "updated_at": state.get("updated_at"),
                })
            except (OSError, ValueError, UnicodeError, json.JSONDecodeError):
                errors.append("unreadable episode-state record")
        return rows, errors

    @staticmethod
    def _pagination(limit: str, offset: str) -> tuple[int, int]:
        try:
            take, skip = int(limit), int(offset)
        except (ValueError, TypeError) as exc:
            raise ValueError("limit and offset must be integers") from exc
        if take < 1 or take > 100 or skip < 0:
            raise ValueError("limit must be 1..100 and offset >= 0")
        return take, skip

    def list_episode_statuses(self, limit: str = "50", offset: str = "0") -> dict:
        take, skip = self._pagination(limit, offset)
        rows, errors = self._load()
        counts: dict[str, int] = {}
        for row in rows:
            stage = row["production_stage"]
            counts[stage] = counts.get(stage, 0) + 1
        return {
            "items": rows[skip:skip + take],
            "count": len(rows[skip:skip + take]),
            "total": len(rows),
            "limit": take,
            "offset": skip,
            "has_more": skip + take < len(rows),
            "stage_counts": counts,
            "errors": errors,
        }

    def get_episode_status(self, episode: str) -> dict | None:
        rows, _ = self._load()
        item = next((record for record in rows if record["episode_ref"] == episode), None)
        if item is None:
            return None
        recorded = {}
        mysql_snapshot = empty_mysql_monitor("EPISODE_IDENTITY_UNVERIFIED")
        for state_file in self._production_state_files():
            try:
                resolved = state_file
                relative = resolved.relative_to(self.episodes).as_posix()
                candidate_ref = "LOCAL_" + hashlib.sha256(relative.encode("utf-8")).hexdigest()[:24]
                if candidate_ref == episode:
                    recorded = read_recorded_production(resolved.parent)
                    mysql_snapshot = observe_mysql_episode(
                        resolved.parent.parent.relative_to(self.episodes).as_posix(),
                        str(item.get("business_episode_id") or ""),
                    )
                    break
            except OSError:
                continue
        return {
            **item,
            "projection_level": "detail",
            # Even a recently modified file cannot prove a live Writer or Worker.
            "execution_status": "UNKNOWN",
            "current_action": None,
            "next_step": None,
            "blocking_reason": None,
            "needs_user": None,
            "auto_recoverable": None,
            "heartbeat": {"health": "unknown"},
            "mysql_monitor": mysql_snapshot,
            "writer_owner_observation": {
                "status": "UNVERIFIED",
                "reason": "OS_LOCK_HOLDER_UNAVAILABLE_WITHOUT_AUTHORITY_OPERATION",
                "read_only": True,
            },
            **recorded,
        }

# R16: only approved images from canonical episode directories; no arbitrary path API.
MEDIA_NAME = re.compile(r"^(0[1-9]|1[0-9]|20)\.(png|jpg|jpeg|webp)$", re.IGNORECASE)
MEDIA_TOKEN = re.compile(r"^[0-9a-f]{32}$")
MEDIA_PREFIX = "/api/v1/local-media/images/"
MEDIA_MAX_BYTES = 12 * 1024 * 1024
MEDIA_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


class LocalApprovedMedia:
    """Path-free read-only media projection for non-archived episodes with state files."""

    def __init__(self, service: LocalEpisodeFileStatuses) -> None:
        self.service = service

    def scan(self) -> tuple[list[dict], dict[str, Path]]:
        records: list[dict] = []
        by_token: dict[str, Path] = {}
        for state in sorted(self.service.episodes.glob("*/**/meta/episode-state.json")):
            try:
                if not state.is_file() or state.is_symlink():
                    continue
                parts = state.relative_to(self.service.episodes).parts
                if any(part.startswith(("_", ".")) for part in parts):
                    continue
                state_real = state.resolve(strict=True)
                if not state_real.is_relative_to(self.service.episodes):
                    continue
                evidence = json.loads(state_real.read_text(encoding="utf-8"))
                title = evidence.get("title")
                code = evidence.get("episode_id")
                if not isinstance(title, str) or not title.strip() or not isinstance(code, str) or not code.strip():
                    continue
                approved = state.parent.parent / "media" / "approved"
                if not approved.is_dir() or approved.is_symlink():
                    continue
                if not approved.resolve(strict=True).is_relative_to(self.service.episodes):
                    continue
                frames: list[dict] = []
                for file in sorted(approved.iterdir()):
                    match = MEDIA_NAME.fullmatch(file.name)
                    if not match or file.is_symlink() or not file.is_file():
                        continue
                    resolved = file.resolve(strict=True)
                    if not resolved.is_relative_to(approved.resolve(strict=True)):
                        continue
                    size = file.stat().st_size
                    if not 0 < size <= MEDIA_MAX_BYTES:
                        continue
                    # Do not advertise files whose header is not a real image of the expected type.
                    with file.open("rb") as image_file:
                        header = image_file.read(12)
                    extension = file.suffix.lower()
                    valid_header = (header.startswith(b"\x89PNG\r\n\x1a\n") if extension == ".png"
                                    else header.startswith(b"\xff\xd8\xff") if extension in (".jpg", ".jpeg")
                                    else header[:4] == b"RIFF" and header[8:12] == b"WEBP")
                    if not valid_header:
                        continue
                    frame = int(match.group(1))
                    relative = file.relative_to(self.service.episodes).as_posix()
                    token = hashlib.sha256(relative.encode("utf-8")).hexdigest()[:32]
                    frames.append({"frame": frame, "url": MEDIA_PREFIX + token})
                    by_token[token] = resolved
                if frames:
                    frames.sort(key=lambda x: x["frame"])
                    # The local status API uses the same opaque episode identity.
                    relative_state = state_real.relative_to(self.service.episodes).as_posix()
                    episode_ref = "LOCAL_" + hashlib.sha256(relative_state.encode("utf-8")).hexdigest()[:24]
                    records.append({
                        "title": title, "business_episode_id": code, "episode_ref": episode_ref,
                        "source": "local_workspace_approved_only", "frames": frames,
                    })
            except (OSError, ValueError, TypeError, json.JSONDecodeError, UnicodeError):
                continue
        return records, by_token

    def image(self, token: str) -> tuple[bytes, str] | None:
        if not MEDIA_TOKEN.fullmatch(token):
            return None
        _items, index = self.scan()  # recheck rights and paths on every request
        path = index.get(token)
        if path is None:
            return None
        try:
            with path.open("rb") as reader:
                data = reader.read(MEDIA_MAX_BYTES + 1)
            if not data or len(data) > MEDIA_MAX_BYTES:
                return None
            extension = path.suffix.lower()
            valid = (data.startswith(b"\x89PNG\r\n\x1a\n") if extension == ".png"
                     else data.startswith(b"\xff\xd8\xff") if extension in (".jpg", ".jpeg")
                     else data[:4] == b"RIFF" and data[8:12] == b"WEBP")
            if not valid:
                return None
            return data, MEDIA_TYPES[extension]
        except OSError:
            return None


class ReadOnlyLocalDispatcher(PlatformApiDispatcher):
    def dispatch(self, method: str, path: str, body=None):
        clean = urlsplit(path).path
        if method.upper() != "GET" or clean not in {
            "/healthz", "/api/v1/runtime/statuses", "/api/v1/runtime/status",
            "/api/v1/runtime/authority",
        }:
            return 403, {"code": "READ_ONLY_LOCAL_EVIDENCE", "message": "local evidence API supports only registered read-only GET endpoints", "data": None}
        return super().dispatch(method, path, body)


class LocalReadOnlyHandler(PlatformApiRequestHandler):
    # 浏览器与服务使用 Vite 同源代理，不允许外部网页跨域读取本机资料。
    def _cors_headers(self) -> None:
        return

    def do_GET(self) -> None:
        route = urlsplit(self.path)
        if route.path == "/api/v1/local-monitor/workers":
            host = self.headers.get("Host", "")
            origin = self.headers.get("Origin", "")
            site = self.headers.get("Sec-Fetch-Site", "")
            if (route.query or route.fragment or origin or
                    (site and site not in ("same-origin", "none")) or
                    host not in (f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}")):
                self._send(403, {"code": "READ_ONLY_LOCAL_EVIDENCE", "data": None})
                return
            self._send(200, {"code": "OK", "data": observe_local_redis_heartbeats()})
            return
        media = getattr(self.server, "approved_media", None)
        if media is not None and (route.path == "/api/v1/local-media/catalog" or route.path.startswith(MEDIA_PREFIX)):
            # Additional guard for browser cross-site reads; the Vite proxy sends Host 127.0.0.1.
            site = self.headers.get("Sec-Fetch-Site", "")
            origin = self.headers.get("Origin", "")
            host = self.headers.get("Host", "")
            if (site and site not in ("same-origin", "none")) or origin or host not in (
                f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"
            ):
                self._send(403, {"code": "MEDIA_FORBIDDEN", "data": None})
                return
            if route.query or route.fragment:
                self._send(400, {"code": "INVALID_REQUEST", "data": None})
                return
            if route.path == "/api/v1/local-media/catalog":
                catalog, _ = media.scan()
                self._send(200, {"code": "OK", "data": {"items": catalog, "source": "local_workspace_approved_only"}})
                return
            result = media.image(route.path[len(MEDIA_PREFIX):])
            if result is None:
                self._send(404, {"code": "MEDIA_NOT_FOUND", "data": None})
                return
            data, content_type = result
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", "default-src 'none'")
            self.end_headers()
            self.wfile.write(data)
            return
        super().do_GET()

    def do_OPTIONS(self) -> None:
        self.send_response(405)
        self.send_header("Content-Length", "0")
        self.end_headers()


def main() -> None:
    parser = argparse.ArgumentParser(description="StoryOS 本机状态文件只读 API，绝不启动 Runtime 或连接数据库")
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--port", type=int, default=19117)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("port must be in 1024..65535")
    service = LocalEpisodeFileStatuses(args.workspace_root)
    # Only local-stage evidence. All five Runtime authorities explicitly
    # remain unavailable; no MySQL/Redis/Worker readers are connected.
    controllers = {
        "RuntimeStatusApiController": RuntimeStatusApiController(service),
        "RuntimeAuthorityApiController": RuntimeAuthorityApiController(
            RuntimeAuthorityEvidenceService(service)),
    }
    server = build_http_server(controllers, host="127.0.0.1", port=args.port)
    server.approved_media = LocalApprovedMedia(service)
    server.dispatcher = ReadOnlyLocalDispatcher(controllers)
    server.RequestHandlerClass = LocalReadOnlyHandler
    print("READY LOCAL_WORKSPACE_READONLY", server.server_address[1], flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
