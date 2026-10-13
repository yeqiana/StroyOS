"""StoryOS authorized Web draft writer — separate schema, NO canonical Episode admission.

A Project/Draft server identity here cannot be submitted as TB_EPISODE.EPISODE_ID.
No route executes production Drivers, Runtime Requests, Attempts, or Provider calls.
"""
from __future__ import annotations
import hashlib
import json
import re
import uuid
from pathlib import Path

import pymysql
from pymysql.cursors import DictCursor

from platform.repository.mysql.r17_isolated_draft_repo import validate_r16_backup

DATABASE = "STORYOS_WEB_DRAFTS"
WORKSPACE = re.compile(r"WDW_[0-9a-f-]{36}\Z")
REQUEST = re.compile(r"[A-Za-z0-9_-]{1,100}\Z")


class DraftWriteError(Exception):
    def __init__(self, code: str, status: int = 409):
        self.code, self.status = code, status
        super().__init__(code)


def fail(code: str, status: int = 409):
    raise DraftWriteError(code, status)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha(value):
    return hashlib.sha256(canonical(value).encode("utf8")).hexdigest()


class WebDraftRepository:
    def __init__(self, config: dict, *, test_only: bool):
        expected_port = 13306 if test_only else 3307
        expected_container = ("storyos-test-only-mysql-frame01-pr72-20261011" if test_only else "mysql8.0")
        if (not isinstance(config, dict)
            or config.get("database") != DATABASE
            or config.get("host") != "127.0.0.1"
            or config.get("port") != expected_port
            or config.get("container") != expected_container
            or not str(config.get("user", "")).startswith("webd_")
            or config.get("test_only") is not test_only):
            fail("DRAFT_DATABASE_IDENTITY_FORBIDDEN", 403)
        self.db = pymysql.connect(host="127.0.0.1", port=expected_port,
                                  user=config["user"], password=config["password"],
                                  database=DATABASE, charset="utf8mb4", autocommit=False,
                                  cursorclass=DictCursor, connect_timeout=5,
                                  read_timeout=10, write_timeout=10)
        with self.db.cursor() as cur:
            cur.execute("SELECT DATABASE() AS db")
            if cur.fetchone()["db"] != DATABASE:
                self.db.close()
                fail("DRAFT_DATABASE_MISMATCH", 403)

    def close(self):
        self.db.close()

    def _atomic(self, request_id: str, payload, mutator):
        if not isinstance(request_id, str) or not REQUEST.fullmatch(request_id):
            fail("INVALID_REQUEST_ID", 400)
        digest = sha(payload)
        try:
            self.db.begin()
            with self.db.cursor() as cur:
                try:
                    cur.execute("INSERT INTO WEB_DRAFT_REQUEST (REQUEST_ID,PAYLOAD_SHA,RESPONSE_JSON) VALUES (%s,%s,%s)",
                                (request_id, digest, '{"pending":true}'))
                except pymysql.err.IntegrityError as e:
                    self.db.rollback()
                    if e.args[0] != 1062:
                        raise
                    with self.db.cursor() as read:
                        read.execute("SELECT PAYLOAD_SHA,RESPONSE_JSON FROM WEB_DRAFT_REQUEST WHERE REQUEST_ID=%s", (request_id,))
                        stored=read.fetchone()
                    if not stored:
                        fail("REQUEST_RETRY", 409)
                    if stored["PAYLOAD_SHA"] != digest:
                        fail("IDEMPOTENCY_CONFLICT", 409)
                    val=stored["RESPONSE_JSON"]
                    return val if isinstance(val, dict) else json.loads(val)
                result=mutator(cur)
                cur.execute("UPDATE WEB_DRAFT_REQUEST SET RESPONSE_JSON=%s WHERE REQUEST_ID=%s",
                            (canonical(result),request_id))
            self.db.commit()
            return result
        except Exception:
            self.db.rollback()
            raise

    def save(self, request_id: str, backup: dict,
             workspace_id: str | None = None, expected_version: int | None = None):
        validate_r16_backup(backup)
        if workspace_id is not None and (
            not isinstance(workspace_id, str) or not WORKSPACE.fullmatch(workspace_id)):
            fail("INVALID_WORKSPACE_ID", 400)
        if workspace_id is None and expected_version is not None:
            fail("INVALID_VERSION", 422)
        if workspace_id is not None and (
            type(expected_version) is not int or expected_version < 1):
            fail("INVALID_VERSION", 422)

        def change(cur):
            if workspace_id:
                cur.execute("SELECT VERSION,IDENTITY_MAP_JSON FROM WEB_DRAFT_WORKSPACE WHERE WORKSPACE_ID=%s FOR UPDATE",
                            (workspace_id,))
                row=cur.fetchone()
                if not row or row["VERSION"] != expected_version:
                    fail("VERSION_CONFLICT", 409)
                raw=row["IDENTITY_MAP_JSON"]
                identity=raw if isinstance(raw,dict) else json.loads(raw)
                new_id=workspace_id
                version=expected_version+1
            else:
                new_id="WDW_"+str(uuid.uuid4())
                identity={"projects":{},"drafts":{}}
                version=1
            for project in backup["projects"]:
                identity["projects"].setdefault(project["id"],"WDP_"+str(uuid.uuid4()))
            for draft in backup["drafts"]:
                identity["drafts"].setdefault(draft["id"],"WDE_"+str(uuid.uuid4()))
            if workspace_id:
                cur.execute("UPDATE WEB_DRAFT_WORKSPACE SET BACKUP_JSON=%s,IDENTITY_MAP_JSON=%s,VERSION=%s "
                            "WHERE WORKSPACE_ID=%s AND VERSION=%s",
                            (canonical(backup),canonical(identity),version,new_id,expected_version))
                if cur.rowcount!=1:
                    fail("VERSION_CONFLICT",409)
            else:
                cur.execute("INSERT INTO WEB_DRAFT_WORKSPACE "
                            "(WORKSPACE_ID,VERSION,BACKUP_JSON,IDENTITY_MAP_JSON) VALUES (%s,%s,%s,%s)",
                            (new_id,version,canonical(backup),canonical(identity)))
            return {"workspace_id":new_id,"version":version,
                    "identity_map":identity,"draft_saved":True,
                    "canonical_episode_created":False,"production_started":False}
        return self._atomic(request_id,{"workspace_id":workspace_id,"expected_version":expected_version,
                                       "backup":backup,"action":"save"},change)

    def read(self, workspace_id: str):
        if not isinstance(workspace_id,str) or not WORKSPACE.fullmatch(workspace_id):
            fail("INVALID_WORKSPACE_ID",400)
        with self.db.cursor() as cur:
            cur.execute("SELECT WORKSPACE_ID,VERSION,BACKUP_JSON,IDENTITY_MAP_JSON FROM WEB_DRAFT_WORKSPACE WHERE WORKSPACE_ID=%s",
                        (workspace_id,))
            row=cur.fetchone()
        if not row:
            fail("NOT_FOUND",404)
        def unpack(value):
            return value if isinstance(value,dict) else json.loads(value)
        return {"workspace_id":row["WORKSPACE_ID"],"version":row["VERSION"],
                "backup":unpack(row["BACKUP_JSON"]), "identity_map":unpack(row["IDENTITY_MAP_JSON"]),
                "canonical_episode_created":False,"production_started":False}

    def list(self):
        with self.db.cursor() as cur:
            cur.execute("SELECT WORKSPACE_ID,VERSION,UPDATE_TIME FROM WEB_DRAFT_WORKSPACE "
                        "ORDER BY UPDATE_TIME DESC LIMIT 100")
            rows=cur.fetchall()
        return {"items":[{"workspace_id":r["WORKSPACE_ID"],"version":r["VERSION"],
                          "updated_at":r["UPDATE_TIME"].isoformat()} for r in rows],
                "canonical_episode_created":False,"production_started":False}
