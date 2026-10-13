"""Test-only JSON-line bridge to the dedicated R17 MySQL schema.

Never accepts connection details, SQL text, paths or canonical production IDs from HTTP.
A new process reads one bounded stdin command and exits.
"""
from __future__ import annotations
import json
import os
import re
import sys
from pathlib import Path

from platform.repository.mysql.r17_isolated_draft_repo import R17IsolatedMysqlStore, R17VaultError

MAX_BYTES = 2_100_000
WORKSPACE_ROUTE = re.compile(r"^/api/v1/draft-vault/workspaces/(TEST_WORKSPACE_[a-f0-9-]{36})$")
BASE = "/api/v1/draft-vault"
BUNDLE_ROUTE = re.compile(r"^/api/v1/draft-vault/(TEST_BUNDLE_[a-f0-9-]{36})$")
RENAME_ROUTE = re.compile(r"^/api/v1/draft-vault/drafts/(TEST_DRAFT_[a-f0-9-]{36})$")


def check_auth_file() -> dict:
    if os.environ.get("STORYOS_R17_TEST_ONLY") != "1":
        raise R17VaultError("TEST_ONLY_REQUIRED", 403)
    raw = os.environ.get("STORYOS_R17_MYSQL_TEST_AUTH", "")
    if not raw or not Path(raw).is_absolute() or Path(raw).name != "mysql-auth.json":
        raise R17VaultError("ISOLATED_AUTH_FILE_REQUIRED", 403)
    path = Path(raw).resolve(strict=True)
    if path.parent.name != "r17-test-only" or path.parent.parent.name != ".storyos-tmp":
        raise R17VaultError("UNSAFE_AUTH_FILE_LOCATION", 403)
    if path.stat().st_size > 2048:
        raise R17VaultError("INVALID_AUTH_FILE", 403)
    return json.loads(path.read_text(encoding="utf-8"))


def handle(command: dict) -> dict:
    if not isinstance(command, dict) or set(command) != {"method", "path", "body"}:
        raise R17VaultError("INVALID_COMMAND", 400)
    method, path, body = command["method"], command["path"], command["body"]
    if not isinstance(path, str) or "?" in path or not isinstance(body, dict):
        raise R17VaultError("INVALID_ROUTE", 400)
    cfg = check_auth_file()
    store = R17IsolatedMysqlStore(cfg, test_only=True)
    try:
        if path == BASE + "/workspaces" and method == "GET":
            rows = store.list_workspaces()
            return {"status":200,"data":{"items":[
                {"workspace_id":v["workspace_id"],"version":v["version"],
                 "updated_at":v["updated_at"].isoformat()} for v in rows],
                "test_only":True,"production_created":False}}
        if path == BASE + "/workspaces" and method == "POST":
            return {"status":201,"data":store.save_workspace(
                body.get("request_id"),body.get("backup"))}
        workspace_match = WORKSPACE_ROUTE.fullmatch(path)
        if workspace_match and method == "GET":
            return {"status":200,"data":store.read_workspace(workspace_match.group(1))}
        if workspace_match and method == "PUT":
            return {"status":200,"data":store.save_workspace(
                body.get("request_id"),body.get("backup"),
                workspace_match.group(1),body.get("expected_version"))}
        if method == "GET" and path == BASE:
            rows = store.list_bundles()
            return {"status": 200, "data": {"items": [
                {"bundle_id": row["bundle_id"], "version": row["revision"],
                 "created_at": row["created_at"].isoformat()}
                for row in rows], "test_only": True, "production_created": False, "backend": "mysql8_test_only"}}
        match = BUNDLE_ROUTE.fullmatch(path)
        if method == "GET" and match:
            record = store.read_bundle(match.group(1))
            record["version"] = record.pop("revision")
            return {"status": 200, "data": record}
        if method == "POST" and path == BASE:
            record = store.import_backup(body.get("request_id"), body.get("backup"))
            record["version"] = record.pop("revision")
            return {"status": 201, "data": record}
        match = RENAME_ROUTE.fullmatch(path)
        if method == "PATCH" and match:
            result = store.rename_draft(match.group(1),body.get("request_id"),
                                        body.get("expected_version"),body.get("title"))
            result["version"] = result.pop("revision")
            return {"status": 200, "data": result}
        raise R17VaultError("ROUTE_NOT_FOUND", 404)
    finally:
        store.close()


def main():
    try:
        raw = sys.stdin.buffer.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise R17VaultError("REQUEST_TOO_LARGE", 413)
        if not raw:
            raise R17VaultError("EMPTY_REQUEST", 400)
        command = json.loads(raw)
        result = handle(command)
    except R17VaultError as error:
        result = {"status": error.status, "code": error.code, "message": error.code}
    except (ValueError, TypeError, json.JSONDecodeError):
        result = {"status": 400, "code": "INVALID_JSON", "message": "INVALID_JSON"}
    except Exception:
        # Do not print database paths, usernames or SQL to the browser.
        result = {"status": 503, "code": "TEST_MYSQL_UNAVAILABLE", "message": "隔离测试数据库不可用"}
    sys.stdout.write(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main()
