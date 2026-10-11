"""Actual MySQL transaction canary for native Frame01 Ledger recovery.

Only runs with --storyos-isolated-mysql and _isolated_mysql_authority approval.
Creates synthetic Episode IDs in a dedicated labeled TEST_ONLY MySQL Docker DB.
Never reads or writes the official production Episode, DB 3306/3307, or pixels.
"""
from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SYSTEM = ROOT / "episodes" / "_system"
for folder in (ROOT, SYSTEM):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import native_baseline_atomic_ledger as atomic
import native_baseline_unknown_cas as reconciliation
import generation_attempt_authority as generation
import production_native_baseline_proof
from platform.repository.mysql.mysql_production_ledger_authority_repository import MySqlProductionLedgerAuthorityRepository
from platform.repository.mysql.mysql_production_attempt_repository import MySqlProductionAttemptRepository
from platform.repository.mysql.mysql_production_frame_repository import MySqlProductionFrameRepository


@pytest.fixture
def admitted_db(request, monkeypatch, tmp_path):
    if not request.config.getoption("--storyos-isolated-mysql"):
        pytest.skip("TEST_ONLY MySQL requires --storyos-isolated-mysql and explicit admission")
    # Admission verifies named, labeled dedicated Docker container, dedicated
    # non-root user, loopback non-3306/3307 port and explicit permission.
    from _isolated_mysql_authority import connection_factory
    from platform.repository.mysql.schema_v2 import DDL_STEPS

    database = connection_factory()()
    storage_id = "EPU_TEST_" + uuid.uuid4().hex[:18]
    schema_steps = {
        "create_production_frame",
        "create_production_attempt",
        "create_production_ledger_authority",
        "create_generation_asset_state",
        "create_generation_attempt",
    }
    try:
        assert database.health_check().get("alive") is True
        for name, sql in DDL_STEPS:
            if name in schema_steps:
                database.execute(sql)
        monkeypatch.setattr(atomic.ledger_store, "mode", lambda: "mysql")
        monkeypatch.setattr(atomic.episode_identity, "storage_episode_id", lambda _: storage_id)
        monkeypatch.setattr(atomic, "_core", lambda: SimpleNamespace(
            verify_attempt_visual_provenance=lambda *_: None,
            verify_attempt_frame_contract_provenance=lambda *_: None,
            now_iso=lambda: "2026-10-11T21:00:00+08:00",
        ))
        ep = tmp_path / "isolated-synthetic-episode"
        ep.mkdir()
        attempt_id = "TEST_" + uuid.uuid4().hex[:16]
        source = {
            "episode": ep,
            "runtime_transaction_id": "9" * 32,
            "generation_key": "ga1-" + "d" * 48 + "-a1",
            "frame_contract_sha256": "a" * 64,
            "scene_prompt_sha256": "c" * 64,
            "candidate_sha256": "b" * 64,
            "candidate_repo_rel": "synthetic/isolation-only/frame01.png",
            "canvas_width": 1080,
            "canvas_height": 1350,
            "evidence_sha256": "e" * 64,
            "runner_request_id": "f" * 32,
            "raw_sha256": "1" * 64,
        }
        asset_key = "synthetic-frame-01"
        source["queue_item_id"] = "synthetic-queue-01"
        source["prompt_package_sha256"] = "b" * 64
        source["generation_key"] = generation.stable_generation_key(storage_id, asset_key, 1)
        source["candidate"] = ep / "synthetic-image-isolation-only.png"
        monkeypatch.setattr(reconciliation.logical_asset_identity, "episode_id", lambda _: storage_id)
        monkeypatch.setattr(generation, "frame_key", lambda _ep, _frame: asset_key)
        monkeypatch.setattr(reconciliation, "verify_frame01_sources",
                            lambda _ep, allow_generated=False: dict(source))
        monkeypatch.setattr(generation, "_connect", connection_factory())
        monkeypatch.setattr(reconciliation.scheduler_core._QUEUE_LOCK_LOCAL,
                            "depths", {ep.as_posix(): 1}, raising=False)
        attempt = {
            "attempt_id": attempt_id, "kind": "original",
            "result": "technical_failure",
            "runtime_transaction_id": source["runtime_transaction_id"],
            "request": {
                "frame": "01", "frame_contract_sha256": source["frame_contract_sha256"],
                "prompt_sha256": source["scene_prompt_sha256"],
                "model": "gpt-image-2.5-flare", "quality": "high",
            },
            "error": {
                "code": "IMAGE_BACKEND_ERROR",
                "message": "NATIVE_BASELINE_PIXEL_TOOL_PROOF_UNVERIFIED: synthetic test",
            },
            "provider_attempt": {"status": "NOT_INVOKED"},
        }
        doc = {
            "schema_version": 1, "engine_version": "synthetic-test",
            "canvas": {"width": 1080, "height": 1350},
            "frames": {"01": {
                "number": 1, "status": "TECH_FAILED", "current_candidate": None,
                "attempts": [attempt], "content_repairs_used": 0,
                "technical_failures": [{
                    "attempt_id": attempt_id, "code": "IMAGE_BACKEND_ERROR",
                }],
            }},
        }
        with database.transaction():
            MySqlProductionLedgerAuthorityRepository(database).upsert(storage_id, doc)
            now = datetime(2026, 10, 11, 13, 0, 0)
            model_sha = "c" * 64
            context = {
                "scope": "visual_lock", "queue_item_id": source["queue_item_id"],
                "visual_lock_frame": 1,
                "tool_capability_claim": "UNKNOWN_NOT_YET_PROVEN",
                "image_capability_proof_purpose": production_native_baseline_proof.REASON,
                "frame_contract_sha256": source["frame_contract_sha256"],
                "prompt_package_sha256": source["prompt_package_sha256"],
                "controller_effort": "high", "model_policy_sha256": model_sha,
            }
            database.execute(
                "INSERT INTO TB_GENERATION_ASSET_STATE "
                "(EPISODE_ID,LOGICAL_ASSET_KEY,ATTEMPTS_CONSUMED,ACTIVE_ATTEMPT_INDEX,FENCING_COUNTER) "
                "VALUES (%s,%s,1,NULL,1)", (storage_id, asset_key),
            )
            database.execute(
                "INSERT INTO TB_GENERATION_ATTEMPT "
                "(EPISODE_ID,LOGICAL_ASSET_KEY,ATTEMPT_INDEX,GENERATION_KEY,LEASE_TOKEN,"
                "FENCING_TOKEN,STATUS,REQUESTED_AT,RESERVED_AT,LEASE_EXPIRES_AT,"
                "DISPATCH_COMMITTED_AT,MODEL_ROLE,MODEL_POLICY_SHA256,CONTROLLER_MODEL,"
                "PAYLOAD_MODEL,PAYLOAD_QUALITY,PROVIDER,FAILURE_CLASS,CONTEXT) "
                "VALUES (%s,%s,1,%s,%s,1,'OUTCOME_UNKNOWN',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (storage_id, asset_key, source["generation_key"], "f" * 64,
                 now, now, now, now, "image.payload", model_sha, "gpt-6-luna",
                 "gpt-image-2.5-flare", "high", "codex_subscription",
                 reconciliation.EXPECTED_REASON, json.dumps(context)),
            )
            atomic.ledger_store._persist_projection(
                storage_id, doc, MySqlProductionFrameRepository(database),
                MySqlProductionAttemptRepository(database), frame_keys={"01"},
            )
        yield database, storage_id, ep, source
    finally:
        # A synthetic namespace, in an admitted disposable database only.
        # Real production IDs are never used as delete predicates.
        for table in ("TB_GENERATION_ATTEMPT", "TB_GENERATION_ASSET_STATE",
                      "TB_PRODUCTION_ATTEMPT", "TB_PRODUCTION_FRAME",
                      "TB_PRODUCTION_LEDGER_AUTHORITY"):
            database.execute(f"DELETE FROM {table} WHERE EPISODE_ID=%s", (storage_id,))
        database.close()


def _read(db, storage_id):
    ledger = MySqlProductionLedgerAuthorityRepository(db).get(storage_id)["document"]
    frame = MySqlProductionFrameRepository(db).get(storage_id, 1)
    attempt = MySqlProductionAttemptRepository(db).list_frame(storage_id, 1)[0]
    return ledger, frame, attempt


def test_real_isolated_mysql_atomic_commit_and_replay(admitted_db):
    db, storage_id, ep, source = admitted_db
    with db.transaction():
        assert atomic.locked_ledger_update(db, ep, source, already_succeeded=False)
    ledger, frame, attempt = _read(db, storage_id)
    assert ledger["frames"]["01"]["status"] == "ORIGINAL_READY"
    assert frame["status"] == "ORIGINAL_READY"
    assert attempt["status"] == "success"
    assert attempt["payload"] == ledger["frames"]["01"]["attempts"][0]
    assert ledger["frames"]["01"]["attempts"][0]["recovery_correction"]["review_pass"] is False
    with db.transaction():
        assert atomic.locked_ledger_update(db, ep, source, already_succeeded=True) is False
    # Corrupt typed projection in synthetic TEST_ONLY namespace only.
    db.execute(
        "UPDATE TB_PRODUCTION_ATTEMPT SET STATUS='fabricated' "
        "WHERE EPISODE_ID=%s AND FRAME_NO=1 AND ATTEMPT_NO=1", (storage_id,),
    )
    with pytest.raises(atomic.LedgerRecoveryDenied, match="TYPED_ATTEMPT_DRIFT"):
        with db.transaction():
            atomic.locked_ledger_update(db, ep, source, already_succeeded=True)


def test_real_isolated_mysql_projection_failure_rolls_back_everything(admitted_db):
    db, storage_id, ep, source = admitted_db
    before = _read(db, storage_id)

    class FailingFrameUpsert:
        def query_one(self, sql, params=None):
            return db.query_one(sql, params)
        def execute(self, sql, params=None):
            if sql.startswith("INSERT INTO TB_PRODUCTION_FRAME"):
                raise RuntimeError("injected typed Frame write failure")
            return db.execute(sql, params)

    with pytest.raises(RuntimeError, match="injected typed Frame write failure"):
        with db.transaction():
            atomic.locked_ledger_update(
                FailingFrameUpsert(), ep, source, already_succeeded=False,
            )
    assert _read(db, storage_id) == before


def test_real_isolated_mysql_generation_attempt_and_ledger_one_transaction(admitted_db):
    db, storage_id, ep, source = admitted_db
    result = reconciliation.reconcile_frame01_unknown(
        ep, expected_fencing_token=1,
        expected_evidence_sha256=source["evidence_sha256"],
    )
    assert result["status"] == "SUCCEEDED"
    assert result["ledger_reconciled"] is True
    frame = MySqlProductionFrameRepository(db).get(storage_id, 1)
    attempt = MySqlProductionAttemptRepository(db).list_frame(storage_id, 1)[0]
    authority_row = db.query_one(
        "SELECT STATUS,RESULT_REF,FAILURE_CLASS,TERMINAL_AT FROM TB_GENERATION_ATTEMPT "
        "WHERE EPISODE_ID=%s AND LOGICAL_ASSET_KEY=%s AND ATTEMPT_INDEX=1",
        (storage_id, "synthetic-frame-01"),
    )
    assert authority_row["STATUS"] == "SUCCEEDED"
    assert authority_row["RESULT_REF"] == str(source["candidate"])
    assert authority_row["FAILURE_CLASS"] == reconciliation.EXPECTED_REASON
    assert authority_row["TERMINAL_AT"] is not None
    assert frame["status"] == "ORIGINAL_READY"
    assert attempt["status"] == "success"
    again = reconciliation.reconcile_frame01_unknown(
        ep, expected_fencing_token=1,
        expected_evidence_sha256=source["evidence_sha256"],
    )
    assert again["idempotent"] is True





def test_real_isolated_mysql_competing_attempt_cas_single_winner(admitted_db):
    """Stress the InnoDB row lock and CAS without invoking a real Queue writer.

    Both threads use synthetic proof data and indicate an already-owned Queue
    lock ONLY in this isolated TEST_ONLY test; the ordinary production entry
    point still requires its canonical OS queue writer lock.
    """
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    db, storage_id, ep, source = admitted_db
    barrier = Barrier(2)

    def contender():
        reconciliation.scheduler_core._QUEUE_LOCK_LOCAL.depths = {
            ep.as_posix(): 1,
        }
        barrier.wait(timeout=10)
        return reconciliation.reconcile_frame01_unknown(
            ep, expected_fencing_token=1,
            expected_evidence_sha256=source["evidence_sha256"],
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        a = executor.submit(contender)
        b = executor.submit(contender)
        results = [a.result(timeout=45), b.result(timeout=45)]
    assert [row["idempotent"] for row in results].count(False) == 1
    assert [row["idempotent"] for row in results].count(True) == 1
    assert all(row["ledger_reconciled"] for row in results)
    assert MySqlProductionAttemptRepository(db).list_frame(storage_id, 1)[0]["status"] == "success"
    asset_state = db.query_one(
        "SELECT ATTEMPTS_CONSUMED,ACTIVE_ATTEMPT_INDEX,FENCING_COUNTER "
        "FROM TB_GENERATION_ASSET_STATE WHERE EPISODE_ID=%s AND LOGICAL_ASSET_KEY=%s",
        (storage_id, "synthetic-frame-01"),
    )
    assert asset_state["ATTEMPTS_CONSUMED"] == 1
    assert asset_state["ACTIVE_ATTEMPT_INDEX"] is None
    assert asset_state["FENCING_COUNTER"] == 1

def test_real_isolated_mysql_final_cas_conflict_rolls_back_ledger(admitted_db, monkeypatch):
    db, storage_id, ep, source = admitted_db
    from _isolated_mysql_authority import connection_factory
    factory = connection_factory()
    before = _read(db, storage_id)

    class FinalCasConflict:
        def __init__(self):
            self.connection = factory()
        def transaction(self):
            return self.connection.transaction()
        def query_one(self, sql, args):
            return self.connection.query_one(sql, args)
        def execute(self, sql, args):
            if sql.startswith("UPDATE TB_GENERATION_ATTEMPT"):
                return 0
            return self.connection.execute(sql, args)
        def close(self):
            self.connection.close()

    monkeypatch.setattr(generation, "_connect", FinalCasConflict)
    with pytest.raises(reconciliation.NativeReconciliationDenied, match="CAS_LOST"):
        reconciliation.reconcile_frame01_unknown(
            ep, expected_fencing_token=1,
            expected_evidence_sha256=source["evidence_sha256"],
        )
    assert _read(db, storage_id) == before
    row = db.query_one(
        "SELECT STATUS FROM TB_GENERATION_ATTEMPT WHERE EPISODE_ID=%s "
        "AND LOGICAL_ASSET_KEY=%s AND ATTEMPT_INDEX=1",
        (storage_id, "synthetic-frame-01"),
    )
    assert row["STATUS"] == "OUTCOME_UNKNOWN"
