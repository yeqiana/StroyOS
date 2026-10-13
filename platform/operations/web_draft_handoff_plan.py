"""Read-only handoff preview for saved Web drafts, never Episode admission.

Only formats the existing canonical story_os.py create --dry-run entrypoint.
No subprocess, state mutation, Episode numbering, Driver, or paid Provider calls.
"""
from __future__ import annotations

import hashlib
import json
import re

DRAFT_UID = re.compile(r"WDE_[0-9a-f-]{36}")


def compile_handoff_plan(record: dict) -> dict:
    """Validate a persisted workspace receipt and present zero-execution candidates."""
    if not isinstance(record, dict):
        raise ValueError("WORKSPACE_RECEIPT_INVALID")
    version = record.get("version")
    backup = record.get("backup")
    identity_map = record.get("identity_map")
    workspace_id = record.get("workspace_id")
    if (not isinstance(workspace_id, str)
        or not re.fullmatch(r"WDW_[0-9a-f-]{36}", workspace_id)
        or type(version) is not int or version < 1
        or not isinstance(backup, dict) or not isinstance(identity_map, dict)
        or not isinstance(backup.get("drafts"), list)
        or not isinstance(identity_map.get("drafts"), dict)):
        raise ValueError("WORKSPACE_RECEIPT_INVALID")

    data = json.dumps(backup, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    fingerprint = hashlib.sha256(data.encode("utf-8")).hexdigest()
    mapped = identity_map["drafts"]
    items = []
    for draft in backup["drafts"]:
        if not isinstance(draft, dict):
            raise ValueError("DRAFT_RECEIPT_INVALID")
        source_id = draft.get("id")
        server_id = mapped.get(source_id)
        if (not isinstance(source_id, str)
            or not isinstance(server_id, str)
            or not DRAFT_UID.fullmatch(server_id)):
            raise ValueError("DRAFT_IDENTITY_NOT_BOUND")
        title = draft.get("title")
        synopsis = draft.get("synopsis")
        valid_title = isinstance(title, str) and 0 < len(title.strip()) <= 220
        valid_synopsis = isinstance(synopsis, str) and 0 < len(synopsis.strip()) <= 1600
        reason = None if valid_title and valid_synopsis else (
            "TITLE_REQUIRED" if not valid_title else "SYNOPSIS_REQUIRED"
        )
        item = {
            "server_draft_id": server_id,
            "source_draft_id": source_id,
            "title": title.strip() if valid_title else "",
            "preflight_available": reason is None,
            "reason": reason,
            "canonical_episode_created": False,
            "production_started": False,
        }
        if reason is None:
            item["preflight_argv"] = [
                "python", "episodes/_system/story_os.py", "create",
                synopsis.strip(), "--title", title.strip(), "--dry-run", "--json"
            ]
        items.append(item)

    return {
        "workspace_id": workspace_id,
        "workspace_version": version,
        "source_sha256": fingerprint,
        "authority": "READ_ONLY_HANDOFF_PLAN",
        "requires_human_approval": True,
        "admission_granted": False,
        "canonical_episode_created": False,
        "production_started": False,
        "model_calls": 0,
        "runtime_writes": 0,
        "items": items,
    }
