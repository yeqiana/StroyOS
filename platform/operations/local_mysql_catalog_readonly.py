"""Least-privilege canonical MySQL Episode catalog for local monitoring."""
from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import Any, Callable, Mapping

from platform.operations.local_mysql_monitor_readonly import (
    SCHEMA, CODE, EPISODE_NAMESPACE, grants_select_only, _time,
)

MAX_CATALOG = 500
SQL_CATALOG = (
    "SELECT e.BUSINESS_EPISODE_ID, e.EPISODE_NAMESPACE, e.TITLE, "
    "e.UPDATE_TIME, s.CURRENT_STATE, s.UPDATE_TIME AS STATE_UPDATE_TIME "
    "FROM TB_EPISODE e LEFT JOIN TB_EPISODE_STATE s ON s.EPISODE_ID=e.EPISODE_ID "
    "WHERE e.DISPOSITION='ACTIVE' AND e.EPISODE_NAMESPACE <> '' "
    "ORDER BY COALESCE(s.UPDATE_TIME,e.UPDATE_TIME) DESC LIMIT 501"
)


def observe_mysql_catalog(*, connect: Callable[..., Any] | None = None,
                          config: Mapping[str, str] | None = None) -> dict[str, Any]:
    """SELECT-only discovery of active Episodes, including Episodes without file state."""
    env = config if config is not None else os.environ
    empty = {"available": False, "reason": "READ_ONLY_MYSQL_NOT_ENABLED",
             "items": [], "observed_at": None, "truncated": False}
    if connect is None and env.get("STORYOS_LOCAL_MONITOR_MYSQL") != "1":
        return empty
    user = env.get("STORYOS_MONITOR_MYSQL_RO_USER", "")
    password = env.get("STORYOS_MONITOR_MYSQL_RO_PASSWORD", "")
    if (not isinstance(user, str) or not CODE.fullmatch(user) or
            user.lower() in ("root", "admin") or not password or
            env.get("STORYOS_MONITOR_MYSQL_RO_DB") != SCHEMA):
        return {**empty, "reason": "DEDICATED_SELECT_ONLY_ACCOUNT_NOT_CONFIGURED"}
    conn = None
    try:
        if connect is None:
            import pymysql
            connect = pymysql.connect
        conn = connect(host="127.0.0.1", port=int(env.get("STORYOS_MONITOR_MYSQL_RO_PORT", "3306")),
                       user=user, password=password, database=SCHEMA, connect_timeout=2,
                       read_timeout=2, write_timeout=2, autocommit=False,
                       cursorclass=__import__("pymysql").cursors.DictCursor)
        with conn.cursor() as cursor:
            cursor.execute("SHOW GRANTS")
            if not grants_select_only(list(cursor.fetchall())):
                return {**empty, "reason": "SELECT_ONLY_GRANTS_NOT_VERIFIED"}
            cursor.execute("START TRANSACTION READ ONLY")
            cursor.execute(SQL_CATALOG)
            rows = list(cursor.fetchall())
        items = []
        for row in rows[:MAX_CATALOG]:
            if not isinstance(row, Mapping):
                continue
            ns = row.get("EPISODE_NAMESPACE")
            if (not isinstance(ns, str) or not EPISODE_NAMESPACE.fullmatch(ns) or
                    len(ns.split("/")) != 2 or
                    any(part.startswith((".", "_")) for part in ns.split("/"))):
                continue
            title = row.get("TITLE")
            business_id = row.get("BUSINESS_EPISODE_ID")
            stage = row.get("CURRENT_STATE")
            if (not isinstance(title, str) or not title.strip() or len(title) > 256 or
                    not isinstance(business_id, str) or len(business_id) > 128):
                continue
            items.append({"namespace": ns, "title": title, "business_episode_id": business_id,
                          "production_stage": stage if isinstance(stage, str) and CODE.fullmatch(stage) else "NO_STATE",
                          "updated_at": _time(row.get("STATE_UPDATE_TIME") or row.get("UPDATE_TIME"))})
        return {"available": True, "reason": None, "items": items,
                "observed_at": datetime.now(timezone.utc).isoformat(),
                "truncated": len(rows) > MAX_CATALOG}
    except Exception:
        return {**empty, "reason": "READ_ONLY_MYSQL_UNAVAILABLE"}
    finally:
        if conn is not None:
            try: conn.rollback()
            except Exception: pass
            try: conn.close()
            except Exception: pass
