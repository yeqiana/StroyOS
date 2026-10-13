"""Isolated no-real-MySQL tests for SELECT-only StoryOS monitor."""
import json
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock

from platform.operations.local_mysql_monitor_readonly import (
    observe_mysql_episode, SQL_ID, SQL_TASK, SQL_PRODUCTION_ATTEMPT, SQL_GENERATION_ATTEMPT,
)

ENV = {"STORYOS_LOCAL_MONITOR_MYSQL": "1", "STORYOS_MONITOR_MYSQL_RO_USER": "storyos_observer",
       "STORYOS_MONITOR_MYSQL_RO_PASSWORD": "test-only", "STORYOS_MONITOR_MYSQL_RO_DB": "STORY_OS_RUNTIME"}
NS = "09_旧物怪谈/05_婚礼前夜_记忆麻醉"
AT = datetime(2026, 10, 13, 3, 0, 0)


class FakeDB:
    def __init__(self, *, matched=True, grants=None, error=None):
        self.executed = []
        self.closed = False
        self.rolled_back = False
        self.matched = matched
        self.error = error
        self.grants = grants if grants is not None else [
            {"Grants": "GRANT USAGE ON *.* TO 'observer'@'localhost'"},
            {"Grants": "GRANT SELECT ON `STORY_OS_RUNTIME`.* TO 'observer'@'localhost'"},
        ]
        self.last = ""

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def execute(self, sql, params=None):
        self.last = sql
        self.executed.append((sql, params))
        if self.error and sql.startswith("SELECT TASK"):
            raise ValueError("MY_SECRET_CREDENTIAL=SHOULD_NOT_LEAK")

    def fetchall(self):
        if self.last == "SHOW GRANTS":
            return self.grants
        if self.last == SQL_ID:
            if not self.matched:
                return [{"EPISODE_ID": "DB_EP_1", "BUSINESS_EPISODE_ID": "UNRELATED",
                         "EPISODE_NAMESPACE": NS}]
            return [{"EPISODE_ID": "DB_EP_1", "BUSINESS_EPISODE_ID": "09-05",
                     "EPISODE_NAMESPACE": NS}]
        if self.last == SQL_TASK:
            return [{"TASK_TYPE": "IMAGE", "STATUS": "RUNNING", "FRAME_NO": 7,
                     "ATTEMPT_NO": 3, "UPDATE_TIME": AT, "OWNER_ID": "SECRET"}]
        if self.last == SQL_PRODUCTION_ATTEMPT:
            return [{"FRAME_NO": 7, "ATTEMPT_NO": 3, "ATTEMPT_KIND": "REPAIR",
                     "STATUS": "FAILED", "ERROR_CODE": "TECH_FAILED", "ELAPSED_MS": 18000,
                     "CREATE_TIME": AT, "PAYLOAD": "SECRET"}]
        if self.last == SQL_GENERATION_ATTEMPT:
            return [{"LOGICAL_ASSET_KEY": NS + "/frame-07", "ATTEMPT_INDEX": 2,
                     "STATUS": "OUTCOME_UNKNOWN", "FAILURE_CLASS": "TIMEOUT",
                     "DISPATCH_COMMITTED_AT": AT, "TERMINAL_AT": None,
                     "LEASE_TOKEN": "SECRET"}]
        raise AssertionError("Unexpected SQL:" + self.last)

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


class MySqlMonitorTests(unittest.TestCase):
    def test_explicit_select_only_connection_and_correct_three_id_domains(self):
        db = FakeDB()
        snap = observe_mysql_episode(NS, "09-05", connect=lambda **kwargs: db, config=ENV)
        self.assertTrue(snap["available"])
        self.assertTrue(snap["database_identity_verified"])
        self.assertTrue(snap["read_only_grants_verified"])
        self.assertFalse(snap["worker_execution_verified"])
        self.assertFalse(snap["writer_owner_verified"])
        self.assertEqual(len(snap["task_records"]), 1)
        self.assertEqual(snap["generation_attempt_records"][0]["frame"], 7)
        self.assertEqual(snap["generation_attempt_records"][0]["status"], "OUTCOME_UNKNOWN")
        self.assertEqual(snap["task_records"][0]["updated_at"], AT.replace(tzinfo=timezone.utc).isoformat())
        self.assertTrue(db.rolled_back)
        self.assertTrue(db.closed)
        statements = [s for s, _ in db.executed]
        self.assertEqual(statements[:2], ["SHOW GRANTS", "START TRANSACTION READ ONLY"])
        self.assertEqual(len(statements), 6)
        self.assertEqual(db.executed[2][1], (NS,))
        self.assertEqual(db.executed[3][1], ("DB_EP_1",))
        self.assertEqual(db.executed[4][1], ("DB_EP_1",))
        self.assertEqual(db.executed[5][1], (NS,))
        for forbidden in ("INSERT ", "UPDATE ", "DELETE ", "CREATE ", "ALTER ", "DROP ", "FOR UPDATE", "GET_LOCK"):
            self.assertFalse(any(forbidden in s.upper() for s in statements))
        response = json.dumps(snap)
        for secret in ("SECRET", "PAYLOAD", "LEASE_TOKEN", "OWNER_ID", "DB_EP_1", "test-only"):
            self.assertNotIn(secret, response)

    def test_no_authorized_readonly_account_does_not_connect(self):
        connector = Mock(side_effect=AssertionError("should not connect"))
        for changed in ({"STORYOS_MONITOR_MYSQL_RO_USER": "root"},
                        {"STORYOS_MONITOR_MYSQL_RO_PASSWORD": ""},
                        {"STORYOS_MONITOR_MYSQL_RO_DB": "another_db"}):
            e = dict(ENV, **changed)
            result = observe_mysql_episode(NS, "09-05", connect=connector, config=e)
            self.assertFalse(result["available"])
            connector.assert_not_called()

    def test_non_select_grant_denied_before_any_query(self):
        db = FakeDB(grants=[{"Grants": "GRANT ALL PRIVILEGES ON *.* TO 'root'@'localhost'"}])
        snap = observe_mysql_episode(NS, "09-05", connect=lambda **kw: db, config=ENV)
        self.assertFalse(snap["available"])
        self.assertEqual(snap["reason"], "SELECT_ONLY_GRANTS_NOT_VERIFIED")
        self.assertEqual([x[0] for x in db.executed], ["SHOW GRANTS"])
        self.assertTrue(db.closed)

    def test_grant_option_denied_even_with_select(self):
        db = FakeDB(grants=[{"Grants": "GRANT SELECT ON *.* TO 'observer'@'localhost' WITH GRANT OPTION"}])
        snap = observe_mysql_episode(NS, "09-05", connect=lambda **kw: db, config=ENV)
        self.assertFalse(snap["available"])
        self.assertEqual(snap["reason"], "SELECT_ONLY_GRANTS_NOT_VERIFIED")
        self.assertEqual(len(db.executed), 1)

    def test_identity_mismatch_denied_before_task_query(self):
        db = FakeDB(matched=False)
        snap = observe_mysql_episode(NS, "09-05", connect=lambda **kw: db, config=ENV)
        self.assertFalse(snap["available"])
        self.assertEqual(snap["reason"], "EPISODE_IDENTITY_MISMATCH")
        self.assertNotIn(SQL_TASK, [x[0] for x in db.executed])

    def test_malformed_namespace_never_contacts_database(self):
        connector = Mock(side_effect=AssertionError("connection should never be reached"))
        for namespace in ("../secrets", "/absolute", "a/../b", "", "a\\b"):
            snap = observe_mysql_episode(namespace, "09-05", connect=connector, config=ENV)
            self.assertEqual(snap["reason"], "EPISODE_IDENTITY_UNVERIFIED")
        connector.assert_not_called()

    def test_mysql_failure_never_leaks_password_or_error(self):
        db = FakeDB(error=True)
        snap = observe_mysql_episode(NS, "09-05", connect=lambda **kw: db, config=ENV)
        self.assertEqual(snap["reason"], "READ_ONLY_MYSQL_UNAVAILABLE")
        self.assertNotIn("SECRET", json.dumps(snap))
        self.assertTrue(db.closed)

    def test_real_default_has_no_db_access(self):
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {}, clear=True):
            result = observe_mysql_episode(NS, "09-05")
        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "READ_ONLY_MYSQL_NOT_ENABLED")


if __name__ == "__main__":
    unittest.main()
