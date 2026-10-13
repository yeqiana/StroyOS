"""Isolated R17 MySQL 8 draft-vault proof, never a canonical Production Writer.

Only accepts the dedicated TEST_ONLY database on the dedicated container port.
This module cannot create or edit a canonical Episode, Runtime Stage or Attempt.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Any

import pymysql
from pymysql.cursors import DictCursor

DB_NAME = "STORYOS_R17_DRAFT_TEST_20261013"
HOST_PORT = 13306
SOURCE_PROJECT = re.compile(r"proj-[a-zA-Z0-9_-]{1,70}\Z")
SOURCE_DRAFT = re.compile(r"ep-(?:home|proj)-[a-zA-Z0-9_-]{1,70}\Z")
REQUEST_ID = re.compile(r"[a-zA-Z0-9_-]{1,100}\Z")
DEFAULT_PROJECTS = frozenset(
    ("proj-aigc-dali", "proj-storyos", "proj-urban", "proj-relic")
)


class R17VaultError(Exception):
    def __init__(self, code: str, status: int = 409):
        super().__init__(code)
        self.code, self.status = code, status


def _fail(code: str, status: int = 409) -> None:
    raise R17VaultError(code, status)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def validate_r16_backup(backup: Any) -> None:
    if not isinstance(backup, dict):
        _fail("INVALID_BACKUP", 422)
    if (backup.get("format") != "storyos-local-draft-backup"
        or backup.get("version") != 1
        or backup.get("source") != "browser_local_only"):
        _fail("INVALID_BACKUP", 422)
    projects, drafts = backup.get("projects"), backup.get("drafts")
    if not isinstance(projects, list) or not isinstance(drafts, list) or len(projects) > 100 or len(drafts) > 100:
        _fail("INVALID_BACKUP", 422)
    if len(_canonical(backup)) > 2_000_000:
        _fail("BACKUP_TOO_LARGE", 413)
    project_ids: set[str] = set()
    for project in projects:
        if not isinstance(project, dict) or not isinstance(project.get("id"), str) or not SOURCE_PROJECT.fullmatch(project["id"]):
            _fail("INVALID_PROJECT", 422)
        title = project.get("name")
        if not isinstance(title, str) or not title.strip() or len(title) > 220 or project["id"] in project_ids:
            _fail("INVALID_PROJECT", 422)
        project_ids.add(project["id"])
    draft_ids: set[str] = set()
    for draft in drafts:
        if not isinstance(draft, dict) or not isinstance(draft.get("id"), str) or not SOURCE_DRAFT.fullmatch(draft["id"]):
            _fail("INVALID_DRAFT", 422)
        title = draft.get("title")
        if (not isinstance(title, str) or not title.strip() or len(title) > 220
            or not isinstance(draft.get("synopsis"), str)
            or not isinstance(draft.get("frameReviews"), list)
            or not isinstance(draft.get("preflightChecks"), list)
            or not isinstance(draft.get("runtimeRequest"), dict)
            or draft["id"] in draft_ids):
            _fail("INVALID_DRAFT", 422)
        project_id = draft.get("projectId")
        if project_id and project_id not in project_ids and project_id not in DEFAULT_PROJECTS:
            _fail("PROJECT_MISSING", 422)
        draft_ids.add(draft["id"])


class R17IsolatedMysqlStore:
    def __init__(self, config: dict, *, test_only: bool = False):
        if not test_only or config.get("test_only") is not True:
            _fail("TEST_ONLY_REQUIRED", 403)
        if (config.get("container") != "storyos-test-only-mysql-frame01-pr72-20261011"
            or config.get("database") != DB_NAME
            or config.get("host") != "127.0.0.1"
            or config.get("port") != HOST_PORT):
            _fail("UNSAFE_MYSQL_TARGET", 403)
        if not isinstance(config.get("user"), str) or not config["user"].startswith("r17_"):
            _fail("UNSAFE_MYSQL_USER", 403)
        self.conn = pymysql.connect(
            host=config["host"], port=HOST_PORT, database=DB_NAME,
            user=config["user"], password=config["password"],
            autocommit=False, charset="utf8mb4", cursorclass=DictCursor,
            connect_timeout=5, read_timeout=8, write_timeout=8,
        )
        with self.conn.cursor() as cur:
            cur.execute("SELECT DATABASE() AS db_name")
            if cur.fetchone()["db_name"] != DB_NAME:
                self.conn.close()
                _fail("MYSQL_IDENTITY_MISMATCH", 403)

    def close(self) -> None:
        self.conn.close()

    def install_schema(self, sql_path: Path) -> None:
        sql = sql_path.read_text(encoding="utf-8")
        # Only own schema, no canonical production tables, no DB switching.
        if not sql_path.name == "r17_test_only_draft_schema.sql":
            _fail("SCHEMA_NAME_UNSAFE", 403)
        statements = [s.strip() for s in sql.split(";") if s.strip()]
        with self.conn.cursor() as cur:
            for statement in statements:
                cleaned = "\n".join(
                    line for line in statement.splitlines()
                    if not line.lstrip().startswith("--")
                ).strip()
                if not cleaned:
                    continue
                if not re.match(r"CREATE TABLE IF NOT EXISTS (?:r17_draft_[a-z_]+|r17_saved_workspaces) \(", cleaned, re.I):
                    _fail("DDL_OUTSIDE_SANDBOX", 403)
                cur.execute(cleaned)
        self.conn.commit()

    def _replay(self, request_id: str, expected_sha: str) -> dict:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT payload_sha, result_json FROM r17_draft_requests WHERE request_id=%s",
                (request_id,),
            )
            row = cur.fetchone()
        if row is None:
            _fail("IDEMPOTENCY_RACE_RETRY_REQUIRED")
        if row["payload_sha"] != expected_sha:
            _fail("IDEMPOTENCY_CONFLICT")
        result = row["result_json"]
        return result if isinstance(result, dict) else json.loads(result)

    def _atomic(self, request_id: str, payload: dict, action) -> dict:
        if not isinstance(request_id, str) or not REQUEST_ID.fullmatch(request_id):
            _fail("INVALID_REQUEST_ID", 400)
        digest = _sha(payload)
        try:
            with self.conn.cursor() as cur:
                self.conn.begin()
                try:
                    # Reserve the idempotency key BEFORE any object writes.
                    # Concurrent INSERT blocks on InnoDB unique key until commit.
                    cur.execute(
                        "INSERT INTO r17_draft_requests(request_id,payload_sha,result_json) VALUES(%s,%s,%s)",
                        (request_id, digest, '{"pending":true}'),
                    )
                except pymysql.err.IntegrityError as exc:
                    self.conn.rollback()
                    if exc.args[0] != 1062:
                        raise
                    return self._replay(request_id, digest)
                result = action(cur)
                cur.execute(
                    "UPDATE r17_draft_requests SET result_json=%s WHERE request_id=%s",
                    (_canonical(result), request_id),
                )
                self.conn.commit()
                return result
        except R17VaultError:
            self.conn.rollback()
            raise
        except pymysql.err.IntegrityError as exc:
            self.conn.rollback()
            if exc.args[0] == 1062:
                _fail("SOURCE_ID_CONFLICT")
            raise
        except Exception:
            self.conn.rollback()
            raise

    def import_backup(self, request_id: str, backup: dict) -> dict:
        validate_r16_backup(backup)

        def mutation(cur) -> dict:
            bundle_id = "TEST_BUNDLE_" + str(uuid.uuid4())
            cur.execute(
                "INSERT INTO r17_draft_bundles(bundle_id,source_sha,backup_json) VALUES(%s,%s,%s)",
                (bundle_id, _sha(backup), _canonical(backup)),
            )
            for project in backup["projects"]:
                cur.execute(
                    "INSERT INTO r17_draft_projects(project_id,bundle_id,source_id,title) VALUES(%s,%s,%s,%s)",
                    ("TEST_PROJECT_" + str(uuid.uuid4()), bundle_id, project["id"], project["name"]),
                )
            for draft in backup["drafts"]:
                cur.execute(
                    "INSERT INTO r17_draft_episodes(draft_id,bundle_id,source_id,title) VALUES(%s,%s,%s,%s)",
                    ("TEST_DRAFT_" + str(uuid.uuid4()), bundle_id, draft["id"], draft["title"]),
                )
            cur.execute(
                "INSERT INTO r17_draft_audit(audit_id,action,subject_id,request_id) VALUES(%s,%s,%s,%s)",
                (str(uuid.uuid4()), "IMPORT_TEST_ONLY", bundle_id, request_id),
            )
            return {
                "bundle_id": bundle_id, "revision": 1,
                "projects": len(backup["projects"]), "drafts": len(backup["drafts"]),
                "test_only": True, "production_created": False,
            }

        return self._atomic(request_id, {"action": "import", "backup": backup}, mutation)

    def list_bundles(self) -> list[dict]:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT bundle_id,revision,created_at FROM r17_draft_bundles ORDER BY created_at DESC LIMIT 100"
            )
            return cur.fetchall()

    def read_bundle(self, bundle_id: str) -> dict:
        if not isinstance(bundle_id, str) or not re.fullmatch(r"TEST_BUNDLE_[a-f0-9-]{36}", bundle_id):
            _fail("INVALID_BUNDLE_ID", 400)
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT revision,backup_json FROM r17_draft_bundles WHERE bundle_id=%s", (bundle_id,)
            )
            row = cur.fetchone()
        if not row:
            _fail("NOT_FOUND", 404)
        value = row["backup_json"]
        backup = value if isinstance(value, dict) else json.loads(value)
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT source_id,title FROM r17_draft_episodes WHERE bundle_id=%s", (bundle_id,)
            )
            names = {x["source_id"]: x["title"] for x in cur.fetchall()}
        for draft in backup["drafts"]:
            draft["title"] = names.get(draft["id"], draft["title"])
        return {"bundle_id": bundle_id, "revision": row["revision"], "backup": backup,
                "test_only": True, "production_created": False}

    def rename_draft(self, draft_id: str, request_id: str, expected_version: int, title: str) -> dict:
        if not isinstance(draft_id, str) or not re.fullmatch(r"TEST_DRAFT_[a-f0-9-]{36}", draft_id):
            _fail("INVALID_DRAFT_ID", 400)
        if not isinstance(expected_version, int) or isinstance(expected_version, bool) or expected_version < 1:
            _fail("INVALID_VERSION", 422)
        if not isinstance(title, str) or not title.strip() or len(title) > 220:
            _fail("INVALID_TITLE", 422)

        def mutation(cur) -> dict:
            cur.execute(
                "UPDATE r17_draft_episodes SET title=%s,revision=revision+1 WHERE draft_id=%s AND revision=%s",
                (title, draft_id, expected_version),
            )
            if cur.rowcount != 1:
                _fail("VERSION_CONFLICT")
            cur.execute(
                "INSERT INTO r17_draft_audit(audit_id,action,subject_id,request_id) VALUES(%s,%s,%s,%s)",
                (str(uuid.uuid4()), "RENAME_TEST_ONLY", draft_id, request_id),
            )
            return {"draft_id": draft_id, "revision": expected_version + 1,
                    "title": title, "production_created": False}

        return self._atomic(
            request_id,
            {"action": "rename", "draft_id": draft_id, "expected_version": expected_version, "title": title},
            mutation,
        )

    def save_workspace(self, request_id: str, backup: dict, workspace_id: str | None = None,
                       expected_version: int | None = None) -> dict:
        """Atomic versioned snapshot of LOCAL drafts. Not a canonical Project/Episode."""
        validate_r16_backup(backup)
        if workspace_id is not None and not re.fullmatch(r"TEST_WORKSPACE_[a-f0-9-]{36}", workspace_id):
            _fail("INVALID_WORKSPACE_ID", 400)
        if workspace_id is None and expected_version is not None:
            _fail("INVALID_VERSION", 422)
        if workspace_id is not None and (type(expected_version) is not int or expected_version < 1):
            _fail("INVALID_VERSION", 422)

        def mutation(cur) -> dict:
            if workspace_id is None:
                new_id = "TEST_WORKSPACE_" + str(uuid.uuid4())
                cur.execute(
                    "INSERT INTO r17_saved_workspaces(workspace_id,version,backup_json) VALUES(%s,1,%s)",
                    (new_id, _canonical(backup)),
                )
                version = 1
                subject = new_id
            else:
                cur.execute(
                    "UPDATE r17_saved_workspaces SET backup_json=%s,version=version+1 "
                    "WHERE workspace_id=%s AND version=%s",
                    (_canonical(backup), workspace_id, expected_version),
                )
                if cur.rowcount != 1:
                    _fail("VERSION_CONFLICT")
                version = expected_version + 1
                subject = workspace_id
            cur.execute(
                "INSERT INTO r17_draft_audit(audit_id,action,subject_id,request_id) VALUES(%s,%s,%s,%s)",
                (str(uuid.uuid4()), "SAVE_WORKSPACE_TEST_ONLY", subject, request_id),
            )
            return {"workspace_id": subject, "version": version,
                    "test_only": True, "production_created": False}

        return self._atomic(request_id,
                            {"action":"save_workspace","id":workspace_id,
                             "expected_version":expected_version,"backup":backup},
                            mutation)

    def list_workspaces(self) -> list[dict]:
        with self.conn.cursor() as cur:
            cur.execute("SELECT workspace_id,version,updated_at FROM r17_saved_workspaces "
                        "ORDER BY updated_at DESC LIMIT 100")
            return cur.fetchall()

    def read_workspace(self, workspace_id: str) -> dict:
        if not isinstance(workspace_id, str) or not re.fullmatch(
            r"TEST_WORKSPACE_[a-f0-9-]{36}", workspace_id
        ):
            _fail("INVALID_WORKSPACE_ID", 400)
        with self.conn.cursor() as cur:
            cur.execute("SELECT workspace_id,version,backup_json FROM r17_saved_workspaces "
                        "WHERE workspace_id=%s", (workspace_id,))
            row = cur.fetchone()
        if not row:
            _fail("NOT_FOUND", 404)
        return {"workspace_id": row["workspace_id"],"version":row["version"],
                "backup": row["backup_json"] if isinstance(row["backup_json"],dict)
                else json.loads(row["backup_json"]),
                "test_only": True, "production_created": False}
