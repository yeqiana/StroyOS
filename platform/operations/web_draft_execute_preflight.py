"""Execute existing canonical create --dry-run for one saved Web draft.

No Episode creation, paid calls or Runtime Writer access. The subprocess receives
a dedicated SELECT-only MySQL identity and never sees the draft writer password.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from platform.operations.web_draft_handoff_plan import compile_handoff_plan

DRAFT_ID = re.compile(r"WDE_[a-f0-9-]{36}")
MAX_OUTPUT = 350_000


class PreflightBlocked(Exception):
    def __init__(self, code: str, status: int = 409):
        super().__init__(code)
        self.code, self.status = code, status


def execute_saved_dry_run(
    record: dict, request: dict, *, root: Path, python_exe: str | None = None,
    runner=None,
) -> dict:
    """Use exactly the saved version, digest, identity and canonical CLI."""
    plan = compile_handoff_plan(record)
    if not isinstance(request, dict) or set(request) != {
        "server_draft_id", "workspace_version", "source_sha256"
    }:
        raise PreflightBlocked("PREFLIGHT_REQUEST_INVALID", 400)
    draft_id = request["server_draft_id"]
    if not isinstance(draft_id, str) or not DRAFT_ID.fullmatch(draft_id):
        raise PreflightBlocked("PREFLIGHT_DRAFT_INVALID", 400)
    if (type(request["workspace_version"]) is not int
        or request["workspace_version"] != plan["workspace_version"]
        or request["source_sha256"] != plan["source_sha256"]):
        raise PreflightBlocked("PREFLIGHT_STALE_WORKSPACE", 409)
    matched = [item for item in plan["items"] if item["server_draft_id"] == draft_id]
    if len(matched) != 1:
        raise PreflightBlocked("PREFLIGHT_DRAFT_NOT_FOUND", 404)
    item = matched[0]
    if not item["preflight_available"]:
        raise PreflightBlocked(item["reason"] or "PREFLIGHT_DRAFT_INCOMPLETE", 422)

    root = Path(root).resolve(strict=True)
    story_os = (root / "episodes" / "_system" / "story_os.py").resolve(strict=True)
    if not story_os.is_relative_to(root):
        raise PreflightBlocked("PREFLIGHT_ENTRY_FORBIDDEN", 403)

    # Refuse a real run until the caller configured SELECT-only canonical MySQL.
    config_path = os.environ.get("STORYOS_WEB_DRAFTS_PREFLIGHT_AUTH", "")
    if runner is None:
        if not config_path or not Path(config_path).is_absolute():
            raise PreflightBlocked("PREFLIGHT_READONLY_DB_NOT_CONFIGURED", 503)
        config_file = Path(config_path).resolve(strict=True)
        if (config_file.name != "preflight-mysql-readonly.json"
            or config_file.parent.name != "web-drafts"
            or config_file.parent.parent.name != ".storyos-tmp"
            or config_file.stat().st_size > 2048):
            raise PreflightBlocked("PREFLIGHT_AUTH_PATH_FORBIDDEN", 403)
        config = json.loads(config_file.read_text(encoding="utf-8"))
        if (config.get("host") != "127.0.0.1"
            or config.get("port") != 3307
            or config.get("database") != "STORY_OS_RUNTIME"
            or not str(config.get("user", "")).startswith("webp_")
            or not isinstance(config.get("password"), str)
            or len(config["password"]) < 32):
            raise PreflightBlocked("PREFLIGHT_READONLY_DB_FORBIDDEN", 403)
        env = {
            **os.environ,
            "STORYOS_MYSQL_HOST": "127.0.0.1",
            "STORYOS_MYSQL_PORT": "3307",
            "STORYOS_MYSQL_DB": "STORY_OS_RUNTIME",
            "STORYOS_MYSQL_USER": config["user"],
            "STORYOS_MYSQL_PWD": config["password"],
        }
    else:
        env = {"STORYOS_MYSQL_HOST": "127.0.0.1", "STORYOS_MYSQL_PORT": "3307"}
    argv = [
        python_exe or sys.executable, str(story_os), "create",
        item["preflight_argv"][3], "--title", item["title"], "--dry-run", "--json",
    ]
    if runner is None:
        def runner(command, **kwargs):
            return subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  text=True, encoding="utf-8", errors="replace",
                                  timeout=24, check=False, **kwargs)
    try:
        proc = runner(argv, cwd=root, env=env)
    except subprocess.TimeoutExpired:
        raise PreflightBlocked("PREFLIGHT_TIMEOUT", 503) from None
    except OSError:
        raise PreflightBlocked("PREFLIGHT_PROCESS_UNAVAILABLE", 503) from None
    if len(proc.stdout or "") > MAX_OUTPUT:
        raise PreflightBlocked("PREFLIGHT_OUTPUT_TOO_LARGE", 503)
    try:
        data = json.loads(proc.stdout)
    except (TypeError, ValueError):
        raise PreflightBlocked("PREFLIGHT_CANONICAL_UNAVAILABLE", 503) from None
    if (not isinstance(data, dict) or data.get("dry_run") is not True
        or data.get("written") is not False or data.get("created") is not False
        or (data.get("workflow") or {}).get("invoked") is not False
        or data.get("production") != "not_started"
        or proc.returncode not in (2, 3)):
        raise PreflightBlocked("PREFLIGHT_UNSAFE_RECEIPT", 503)
    status = data.get("status")
    if status not in ("PLANNED", "HUMAN_GATE_REQUIRED"):
        raise PreflightBlocked("PREFLIGHT_UNEXPECTED_STATUS", 503)
    return {
        "authority": "CANONICAL_DRY_RUN",
        "workspace_id": plan["workspace_id"],
        "workspace_version": plan["workspace_version"],
        "source_sha256": plan["source_sha256"],
        "server_draft_id": draft_id,
        "status": status,
        "profile_id": (data.get("visual_profile_selection") or {}).get("profile_id"),
        "visual_lock": data.get("visual_lock"),
        "real_preflight_executed": True,
        "canonical_episode_created": False,
        "admission_granted": False,
        "production_started": False,
        "model_calls": 0,
    }
