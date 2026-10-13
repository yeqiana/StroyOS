"""Minimal R21 Web draft -> canonical Episode bootstrap; never invoke a Driver."""
from __future__ import annotations

import re
from pathlib import Path

from platform.operations.web_draft_execute_preflight import (
    PreflightBlocked, execute_saved_dry_run,
)
from platform.operations.web_draft_handoff_plan import compile_handoff_plan

DRAFT_ID = re.compile(r"WDE_[0-9a-f-]{36}\Z")


class BootstrapBlocked(Exception):
    def __init__(self, code: str, status: int = 409):
        self.code, self.status = code, status
        super().__init__(code)


def bootstrap_saved_episode(
    record: dict, request: dict, *, root: Path, admitted: bool = False,
    dry_run=None, creator=None, claim=None, finish=None,
) -> dict:
    """One explicitly confirmed, version-bound, bootstrap-only canonical creation.

    The authentic creator performs MySQL business-number claim and initializes
    the Episode. Deliberately NOT run_full_auto, workflow_runner or Driver.
    No retry after an interrupted bootstrap; an incomplete claim is retained.
    """
    if not admitted:
        raise BootstrapBlocked("EPISODE_BOOTSTRAP_DISABLED", 403)
    if not isinstance(request, dict) or set(request) != {
        "server_draft_id", "workspace_version", "source_sha256", "ack"
    } or request.get("ack") != "CREATE_EPISODE_WITHOUT_START":
        raise BootstrapBlocked("EPISODE_CREATE_ACK_REQUIRED", 403)
    plan = compile_handoff_plan(record)
    draft_id = request["server_draft_id"]
    if not isinstance(draft_id, str) or not DRAFT_ID.fullmatch(draft_id):
        raise BootstrapBlocked("EPISODE_DRAFT_INVALID", 400)
    if (type(request["workspace_version"]) is not int
        or request["workspace_version"] != plan["workspace_version"]
        or request["source_sha256"] != plan["source_sha256"]):
        raise BootstrapBlocked("EPISODE_DRAFT_STALE", 409)
    matching = [item for item in plan["items"] if item["server_draft_id"] == draft_id]
    if len(matching) != 1:
        raise BootstrapBlocked("EPISODE_DRAFT_NOT_FOUND", 404)
    item = matching[0]
    if not item["preflight_available"]:
        raise BootstrapBlocked(item["reason"] or "EPISODE_DRAFT_INCOMPLETE", 422)
    # An actual canonical dry-run is repeated on the same persisted snapshot.
    # Never trust a browser-supplied "passed" report.
    try:
        status = (dry_run or execute_saved_dry_run)(
            record, {k: request[k] for k in (
                "server_draft_id", "workspace_version", "source_sha256"
            )}, root=root
        )
    except PreflightBlocked as exc:
        raise BootstrapBlocked(exc.code, exc.status) from None
    if (status.get("authority") != "CANONICAL_DRY_RUN"
        or status.get("real_preflight_executed") is not True
        or status.get("status") != "PLANNED"
        or status.get("admission_granted") is not False
        or status.get("canonical_episode_created") is not False
        or status.get("production_started") is not False
        or status.get("workspace_id") != plan["workspace_id"]
        or status.get("workspace_version") != plan["workspace_version"]
        or status.get("source_sha256") != plan["source_sha256"]
        or status.get("server_draft_id") != draft_id):
        raise BootstrapBlocked("EPISODE_PREFLIGHT_NOT_APPROVED", 409)

    root = Path(root).resolve(strict=True)
    from sys import path as sys_path
    system = str((root / "episodes" / "_system").resolve(strict=True))
    if system not in sys_path:
        sys_path.insert(0, system)
    import story_creator

    # Fail closed on any existing title, including a removed local directory
    # whose namespace persists in canonical MySQL. Never resume unrelated work.
    title = item["title"]
    slug = story_creator.slugify(title)
    if len(slug) > 90 or not slug:
        raise BootstrapBlocked("EPISODE_TITLE_INVALID", 422)
    series = story_creator.DEFAULT_STANDALONE_SERIES
    suffix = "_" + slug
    series_root = root / "episodes" / series
    if series_root.is_dir() and any(
        entry.is_dir() and entry.name.endswith(suffix) for entry in series_root.iterdir()
    ):
        raise BootstrapBlocked("EPISODE_TITLE_ALREADY_EXISTS", 409)
    import episode_state_persistence
    if episode_state_persistence.authority_mode() != "mysql":
        raise BootstrapBlocked("EPISODE_MYSQL_AUTHORITY_REQUIRED", 403)
    namespaces = episode_state_persistence.list_episode_namespaces()
    if any(
        str(ns).replace("\\", "/").startswith(series + "/")
        and str(ns).replace("\\", "/").split("/")[-1].endswith(suffix)
        for ns in namespaces
    ):
        raise BootstrapBlocked("EPISODE_TITLE_ALREADY_CLAIMED", 409)

    synopsis = item["preflight_argv"][3]
    # Normal path is the pre-existing canonical bootstrap. Tests inject only
    # the creator to exercise authorization without touching formal data.
    if creator is None:
        if claim is None or finish is None:
            raise BootstrapBlocked('EPISODE_DURABLE_IDENTITY_REQUIRED',503)
        import story_intent_parser
        intent = story_intent_parser.parse(synopsis, story_root=root)
        selector = story_intent_parser.selector_input(intent)
        def creator(base, name, source):
            return story_creator.create_episode(
                base, name, selector_input=selector, runtime_request_text=source
            )

    if claim is not None:
        claim(plan['workspace_id'],plan['workspace_version'],draft_id,title)
    episode = Path(creator(root, title, synopsis)).resolve()
    canonical_root = (root / "episodes" / series).resolve()
    if episode.parent != canonical_root or not episode.is_dir():
        raise BootstrapBlocked("EPISODE_BOOTSTRAP_INVALID_RESULT", 503)
    namespace = episode.relative_to(root / 'episodes').as_posix()
    if finish is not None:
        finish(plan['workspace_id'],draft_id,namespace)
    return {
        "authority": "CANONICAL_EPISODE_BOOTSTRAP",
        "workspace_id": plan["workspace_id"],
        "workspace_version": plan["workspace_version"],
        "source_sha256": plan["source_sha256"],
        "server_draft_id": draft_id,
        "episode_namespace": namespace,
        "canonical_episode_created": True,
        "production_started": False,
        "driver_started": False,
        "model_calls": 0,
        "requires_production_gate": True,
    }
