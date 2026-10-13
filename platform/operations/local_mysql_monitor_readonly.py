"""Strictly opt-in local MySQL production observations, never a write adapter.

A dedicated SELECT-only MySQL account and a READ ONLY transaction are BOTH
required. No connection is attempted with normal StoryOS production credentials.
Episode namespace and business ID must resolve to one TB_EPISODE row.
"""
from __future__ import annotations

from datetime import datetime, timezone
import os
import re
from typing import Any, Callable, Mapping

SCHEMA = "STORY_OS_RUNTIME"
MAX_ROWS = 60
CODE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
EPISODE_NAMESPACE = re.compile(r"^(?!/)(?!.*(?:^|/)\.\.?(/|$))[^\x00-\x1f\\]{1,256}$")
_GRANT = re.compile(r"^GRANT ((?:SELECT|SHOW VIEW|USAGE)(?:,\s*(?:SELECT|SHOW VIEW|USAGE))*) ON ", re.IGNORECASE)

SQL_ID = ("SELECT EPISODE_ID, BUSINESS_EPISODE_ID, EPISODE_NAMESPACE, DISPOSITION "
          "FROM TB_EPISODE WHERE EPISODE_NAMESPACE=%s LIMIT 2")
SQL_TASK = ("SELECT TASK_TYPE, FRAME_NO, STATUS, ATTEMPT_NO, UPDATE_TIME "
            "FROM TB_TASK WHERE EPISODE_ID=%s ORDER BY UPDATE_TIME DESC LIMIT 60")
SQL_PRODUCTION_ATTEMPT = (
    "SELECT FRAME_NO, ATTEMPT_NO, ATTEMPT_KIND, STATUS, ERROR_CODE, ELAPSED_MS, CREATE_TIME "
    "FROM TB_PRODUCTION_ATTEMPT WHERE EPISODE_ID=%s ORDER BY CREATE_TIME DESC LIMIT 60")
SQL_GENERATION_ATTEMPT = (
    "SELECT LOGICAL_ASSET_KEY, ATTEMPT_INDEX, STATUS, FAILURE_CLASS, "
    "DISPATCH_COMMITTED_AT, TERMINAL_AT FROM TB_GENERATION_ATTEMPT "
    "WHERE EPISODE_ID=%s ORDER BY REQUESTED_AT DESC LIMIT 60")


def empty(reason: str) -> dict[str, Any]:
    return {
        "scope": "MYSQL_EPISODE_READ_ONLY",
        "read_only": True,
        "available": False,
        "reason": reason,
        "observed_at": None,
        "database_identity_verified": False,
        "read_only_grants_verified": False,
        "task_records": [],
        "production_attempt_records": [],
        "generation_attempt_records": [],
        "records_limit_per_table": MAX_ROWS,
        "may_be_truncated": True,
        "writer_owner_verified": False,
        "worker_execution_verified": False,
        "production_authorization": False,
    }


def _code(value: object) -> str | None:
    return value if isinstance(value, str) and CODE.fullmatch(value) else None


def _integer(value: object, upper: int = 100000000) -> int | None:
    return value if type(value) is int and 0 <= value <= upper else None


def _time(value: object) -> str | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    return None


def _frame_from_key(key: object, namespace: str) -> int | None:
    if not isinstance(key, str) or not key.startswith(namespace + "/frame-"):
        return None
    end = key.removeprefix(namespace + "/frame-")
    return int(end) if re.fullmatch(r"\d{1,2}", end) and 1 <= int(end) <= 20 else None


def grants_select_only(rows: list[Mapping[str, Any]]) -> bool:
    if not rows:
        return False
    for row in rows:
        if not isinstance(row, Mapping) or len(row) != 1:
            return False
        grant = next(iter(row.values()))
        if (not isinstance(grant, str) or _GRANT.match(grant) is None or
                "WITH GRANT OPTION" in grant.upper() or "WITH ADMIN OPTION" in grant.upper()):
            return False
    return True


def observe_mysql_episode(
    namespace: str, business_id: str, *,
    connect: Callable[..., Any] | None = None,
    config: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = config if config is not None else os.environ
    if connect is None and env.get("STORYOS_LOCAL_MONITOR_MYSQL") != "1":
        return empty("READ_ONLY_MYSQL_NOT_ENABLED")
    user, password = env.get("STORYOS_MONITOR_MYSQL_RO_USER", ""), env.get("STORYOS_MONITOR_MYSQL_RO_PASSWORD", "")
    database = env.get("STORYOS_MONITOR_MYSQL_RO_DB", "")
    if not user or not password or database != SCHEMA or user.lower() in ("root", "admin") or not CODE.fullmatch(user):
        return empty("DEDICATED_SELECT_ONLY_ACCOUNT_NOT_CONFIGURED")
    if (not isinstance(namespace, str) or EPISODE_NAMESPACE.fullmatch(namespace) is None or
            not isinstance(business_id, str) or not business_id or len(business_id) > 128):
        return empty("EPISODE_IDENTITY_UNVERIFIED")
    conn = None
    try:
        if connect is None:
            import pymysql
            connect = pymysql.connect
        conn = connect(
            host="127.0.0.1",
            port=int(env.get("STORYOS_MONITOR_MYSQL_RO_PORT", "3306")),
            user=user, password=password, database=SCHEMA,
            connect_timeout=2, read_timeout=2, write_timeout=2,
            autocommit=False, cursorclass=__import__("pymysql").cursors.DictCursor,
        )
        with conn.cursor() as cursor:
            cursor.execute("SHOW GRANTS")
            grants = cursor.fetchall()
            if not grants_select_only(list(grants)):
                return empty("SELECT_ONLY_GRANTS_NOT_VERIFIED")
            cursor.execute("START TRANSACTION READ ONLY")
            cursor.execute(SQL_ID, (namespace,))
            matches = list(cursor.fetchall())
            if (len(matches) != 1 or str(matches[0].get("BUSINESS_EPISODE_ID")) != business_id or
                    str(matches[0].get("EPISODE_NAMESPACE")) != namespace or
                    not matches[0].get("EPISODE_ID")):
                return empty("EPISODE_IDENTITY_MISMATCH")
            mysql_id = str(matches[0]["EPISODE_ID"])
            if len(mysql_id) > 64:
                return empty("EPISODE_IDENTITY_MISMATCH")

            cursor.execute(SQL_TASK, (mysql_id,))
            task_rows = list(cursor.fetchall())
            cursor.execute(SQL_PRODUCTION_ATTEMPT, (mysql_id,))
            attempt_rows = list(cursor.fetchall())
            # Generation Attempt authority uses canonical repository namespace,
            # NOT the TB_EPISODE primary key; never mix these IDs.
            cursor.execute(SQL_GENERATION_ATTEMPT, (namespace,))
            generation_rows = list(cursor.fetchall())

            tasks = [{
                "task_type": _code(row.get("TASK_TYPE")), "status": _code(row.get("STATUS")),
                "frame": _integer(row.get("FRAME_NO"), 20),
                "attempt_no": _integer(row.get("ATTEMPT_NO"), 1000),
                "updated_at": _time(row.get("UPDATE_TIME")),
            } for row in task_rows if isinstance(row, dict)]
            production = [{
                "frame": _integer(row.get("FRAME_NO"), 20),
                "attempt_no": _integer(row.get("ATTEMPT_NO"), 1000),
                "kind": _code(row.get("ATTEMPT_KIND")),
                "status": _code(row.get("STATUS")),
                "error_code": _code(row.get("ERROR_CODE")),
                "elapsed_ms": _integer(row.get("ELAPSED_MS")),
                "recorded_at": _time(row.get("CREATE_TIME")),
            } for row in attempt_rows if isinstance(row, dict)]
            generation = [{
                "frame": _frame_from_key(row.get("LOGICAL_ASSET_KEY"), namespace),
                "attempt_index": _integer(row.get("ATTEMPT_INDEX"), 2),
                "status": _code(row.get("STATUS")),
                "failure_class": _code(row.get("FAILURE_CLASS")),
                "dispatch_recorded_at": _time(row.get("DISPATCH_COMMITTED_AT")),
                "terminal_recorded_at": _time(row.get("TERMINAL_AT")),
            } for row in generation_rows if isinstance(row, dict)]
        return {
            **empty(None),
            "available": True,
            "database_identity_verified": True,
            "read_only_grants_verified": True,
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "task_records": tasks,
            "production_attempt_records": production,
            "generation_attempt_records": generation,
        }
    except Exception:
        return empty("READ_ONLY_MYSQL_UNAVAILABLE")
    finally:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass
