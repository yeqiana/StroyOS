"""Hermetic ledger+Generation Attempt atomic recovery tests.

All connections/repositories below are memory fakes; the real Episode MySQL
and native image tool are never touched.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime, timezone
import sys

import pytest

SYSTEM = Path(__file__).resolve().parents[2] / "episodes" / "_system"
if str(SYSTEM) not in sys.path:
    sys.path.insert(0, str(SYSTEM))

import native_baseline_atomic_ledger as atomic
import native_baseline_unknown_cas as reconcile


@pytest.fixture
def sample(tmp_path, monkeypatch):
    ep = tmp_path / "ep"
    ep.mkdir()
    monkeypatch.setattr(atomic, "_core", lambda: SimpleNamespace(
        verify_attempt_visual_provenance=lambda *_: None,
        verify_attempt_frame_contract_provenance=lambda *_: None,
        now_iso=lambda: "2026-10-11T21:00:00+08:00",
    ))
    source = {
        "episode": ep,
        "runtime_transaction_id": "9" * 32,
        "generation_key": "ga1-" + "d" * 48 + "-a1",
        "frame_contract_sha256": "a" * 64,
        "scene_prompt_sha256": "c" * 64,
        "candidate_sha256": "b" * 64,
        "candidate_repo_rel": "episodes/00_独立篇/06_五十亩山地之后_全新重制/media/candidates/scheduled/01-65db61f1e871-a1.png",
        "canvas_width": 1080,
        "canvas_height": 1350,
        "evidence_sha256": "e" * 64,
        "runner_request_id": "f" * 32,
        "raw_sha256": "1" * 64,
    }
    attempt = {
        "attempt_id": "ca8ec994fbf7", "kind": "original",
        "result": "technical_failure",
        "runtime_transaction_id": source["runtime_transaction_id"],
        "request": {"frame": "01", "frame_contract_sha256": source["frame_contract_sha256"],
                    "prompt_sha256": source["scene_prompt_sha256"],
                    "model": "gpt-image-2.5-flare", "quality": "high"},
        "error": {"code": "IMAGE_BACKEND_ERROR",
                  "message": "NATIVE_BASELINE_PIXEL_TOOL_PROOF_UNVERIFIED: RuntimeError"},
        "provider_attempt": {"status": "NOT_INVOKED", "failure_code": "IMAGE_BACKEND_ERROR"},
    }
    ledger = {
        "schema_version": 1, "engine_version": "test",
        "canvas": {"width": 1080, "height": 1350},
        "frames": {"01": {
            "number": 1, "status": "TECH_FAILED", "current_candidate": None,
            "attempts": [attempt], "content_repairs_used": 0,
            "technical_failures": [{"attempt_id": attempt["attempt_id"],
                                    "code": "IMAGE_BACKEND_ERROR"}]},
            "02": {"number": 2, "status": "PENDING", "attempts": [],
                   "content_repairs_used": 0}},
    }
    return source, ledger


def test_correction_retains_failure_and_does_not_pass_visual(sample):
    source, ledger = sample
    baseline = deepcopy(ledger)
    fixed = atomic.corrected_ledger_document(ledger, source)
    assert ledger == baseline
    frame = fixed["frames"]["01"]
    attempt = frame["attempts"][0]
    assert frame["status"] == "ORIGINAL_READY"
    assert attempt["result"] == "success"
    assert attempt["generation_key"] == source["generation_key"]
    assert attempt["generation_attempt_index"] == 1
    assert frame["current_candidate"]["sha256"] == source["candidate_sha256"]
    assert attempt["recovery_correction"]["previous_result"] == "technical_failure"
    assert attempt["recovery_correction"]["previous_error"] == baseline["frames"]["01"]["attempts"][0]["error"]
    assert attempt["recovery_correction"]["previous_provider_attempt"]["status"] == "NOT_INVOKED"
    assert attempt["recovery_correction"]["review_pass"] is False
    assert attempt["recovery_correction"]["provider_model_attested"] is False
    assert attempt["provider_attempt"]["native_image_generation_jsonl_events"] == 0
    assert "error" not in attempt
    assert frame["technical_failures"][0]["code"] == "IMAGE_BACKEND_ERROR"
    assert frame["technical_failures"][0]["recovered_at"]
    assert fixed["frames"]["02"] == baseline["frames"]["02"]
    assert frame["content_repairs_used"] == 0
    atomic._check_existing(fixed, source, completed=True)


@pytest.mark.parametrize("mutate", [
    "attempt_count", "status", "transaction", "frame_contract", "prompt",
    "model", "quality", "canvas", "failure_code", "failure_message",
    "provider_status", "technical_failure_id", "already_recovered",
    "current_candidate", "attempt_kind",
])
def test_ledger_drift_never_generates_candidate(sample, mutate):
    source, ledger = sample
    item = ledger["frames"]["01"]
    att = item["attempts"][0]
    if mutate == "attempt_count":
        item["attempts"].append(deepcopy(att))
    elif mutate == "status":
        item["status"] = "PASSED"
    elif mutate == "transaction":
        att["runtime_transaction_id"] = "wrong"
    elif mutate == "frame_contract":
        att["request"]["frame_contract_sha256"] = "0" * 64
    elif mutate == "prompt":
        att["request"]["prompt_sha256"] = "0" * 64
    elif mutate == "model":
        att["request"]["model"] = "other"
    elif mutate == "quality":
        att["request"]["quality"] = "low"
    elif mutate == "canvas":
        ledger["canvas"]["width"] = 1081
    elif mutate == "failure_code":
        att["error"]["code"] = "OTHER"
    elif mutate == "failure_message":
        att["error"]["message"] = "other"
    elif mutate == "provider_status":
        att["provider_attempt"]["status"] = "COMPLETED"
    elif mutate == "technical_failure_id":
        item["technical_failures"][0]["attempt_id"] = "other"
    elif mutate == "already_recovered":
        item["technical_failures"][0]["recovered_at"] = "yesterday"
    elif mutate == "current_candidate":
        item["current_candidate"] = {"path": "other.png"}
    elif mutate == "attempt_kind":
        att["kind"] = "repair"
    before = deepcopy(ledger)
    with pytest.raises(atomic.LedgerRecoveryDenied):
        atomic.corrected_ledger_document(ledger, source)
    assert ledger == before


def test_idempotent_correction_checks_proof_identity(sample):
    source, ledger = sample
    fixed = atomic.corrected_ledger_document(ledger, source)
    for key, value in (
        ("evidence_sha256", "0" * 64),
        ("generation_key", "wrong"),
        ("candidate_sha256", "wrong"),
        ("runner_request_id", "wrong"),
        ("runtime_transaction_id", "wrong"),
    ):
        changed = dict(source, **{key: value})
        with pytest.raises(atomic.LedgerRecoveryDenied):
            atomic._check_existing(fixed, changed, completed=True)




@pytest.mark.parametrize("tamper", [
    "frame_candidate_attempt_id", "frame_candidate_kind", "frame_candidate_width",
    "frame_candidate_height", "attempt_candidate", "attempt_generation_key",
    "attempt_generation_index", "attempt_error",
    "correction_review_pass", "correction_model_attested", "correction_raw_sha",
    "correction_candidate_sha", "correction_generation_key", "correction_generation_index",
    "correction_previous_provider", "correction_previous_error",
    "provider_status", "provider_proof_kind", "provider_runner_id",
    "provider_payload_model_attested", "provider_jsonl_image_events",
    "failure_recovered_at", "failure_runner_id",
])
def test_idempotent_replay_refuses_forged_provenance_or_review(sample, tamper):
    source, original = sample
    fixed = atomic.corrected_ledger_document(original, source)
    frame = fixed["frames"]["01"]
    attempt = frame["attempts"][0]
    correction = attempt["recovery_correction"]
    provider = attempt["provider_attempt"]
    candidate = frame["current_candidate"]
    if tamper == "frame_candidate_attempt_id":
        candidate["attempt_id"] = "fabricated"
    elif tamper == "frame_candidate_kind":
        candidate["kind"] = "repair"
    elif tamper == "frame_candidate_width":
        candidate["width"] += 1
    elif tamper == "frame_candidate_height":
        candidate["height"] += 1
    elif tamper == "attempt_candidate":
        attempt["candidate"]["sha256"] = "0" * 64
    elif tamper == "attempt_generation_key":
        attempt["generation_key"] = "fabricated"
    elif tamper == "attempt_generation_index":
        attempt["generation_attempt_index"] = 2
    elif tamper == "attempt_error":
        attempt["error"] = {"code": "forged"}
    elif tamper == "correction_review_pass":
        correction["review_pass"] = True
    elif tamper == "correction_model_attested":
        correction["provider_model_attested"] = True
    elif tamper == "correction_raw_sha":
        correction["raw_png_sha256"] = "0" * 64
    elif tamper == "correction_candidate_sha":
        correction["normalized_png_sha256"] = "0" * 64
    elif tamper == "correction_generation_key":
        correction["generation_key"] = "fabricated"
    elif tamper == "correction_generation_index":
        correction["attempt_index"] = 2
    elif tamper == "correction_previous_provider":
        correction["previous_provider_attempt"]["status"] = "COMPLETED"
    elif tamper == "correction_previous_error":
        correction["previous_error"] = None
    elif tamper == "provider_status":
        provider["status"] = "NOT_INVOKED"
    elif tamper == "provider_proof_kind":
        provider["proof_kind"] = "FAKE_IMAGE_TOOL_EVENT"
    elif tamper == "provider_runner_id":
        provider["runner_request_id"] = "0" * 32
    elif tamper == "provider_payload_model_attested":
        provider["payload_model_attested"] = True
    elif tamper == "provider_jsonl_image_events":
        provider["native_image_generation_jsonl_events"] = 1
    elif tamper == "failure_recovered_at":
        frame["technical_failures"][-1]["recovered_at"] = "fabricated"
    elif tamper == "failure_runner_id":
        frame["technical_failures"][-1]["recovered_runner_request_id"] = "fabricated"
    with pytest.raises(atomic.LedgerRecoveryDenied, match="IDEMPOTENCY_DRIFT"):
        atomic._check_existing(fixed, source, completed=True)

def test_typed_authority_and_projection_share_given_connection(sample, monkeypatch):
    source, document = sample
    class MemoryConn:
        def __init__(self):
            self.current = deepcopy(document)
            self.writes = []
            self.sha = "8" * 64
        def query_one(self, sql, args):
            assert "FOR UPDATE" in sql and "TB_PRODUCTION_LEDGER_AUTHORITY" in sql
            return {"SHA256": self.sha}
    db = MemoryConn()
    class Repo:
        def __init__(self, conn):
            assert conn is db
        def get(self, sid):
            return {"sha256": db.sha, "document": deepcopy(db.current)}
        def upsert(self, sid, data):
            db.writes.append(("authority", sid, deepcopy(data)))
            db.current = deepcopy(data)
    class Frames:
        def __init__(self, conn): assert conn is db
        def upsert(self, data): db.writes.append(("frame", data["frame_no"]))
    class Attempts:
        def __init__(self, conn): assert conn is db
        def upsert(self, data): db.writes.append(("attempt", data["attempt_no"]))
    monkeypatch.setattr(atomic, "MySqlProductionLedgerAuthorityRepository", Repo)
    monkeypatch.setattr(atomic, "MySqlProductionFrameRepository", Frames)
    monkeypatch.setattr(atomic, "MySqlProductionAttemptRepository", Attempts)
    monkeypatch.setattr(atomic.episode_identity, "storage_episode_id", lambda _: "00-06")
    monkeypatch.setattr(atomic.ledger_store, "mode", lambda: "mysql")
    # The isolated fake repositories assert same-connection upserts; separate
    # tests below exercise actual SELECT ... FOR UPDATE typed consistency.
    monkeypatch.setattr(atomic, "_verify_typed_frame01", lambda *_: None)
    assert atomic.locked_ledger_update(db, source["episode"], source, already_succeeded=False) is True
    assert [row[0] for row in db.writes] == ["authority", "attempt", "frame"]
    assert db.current["frames"]["01"]["status"] == "ORIGINAL_READY"
    assert atomic.locked_ledger_update(db, source["episode"], source, already_succeeded=True) is False
    assert len(db.writes) == 3





def _typed_test_db(source, document):
    """Tiny read-only SQL projection stub with real repository column names."""
    class Db:
        def __init__(self):
            self.attempt = document["frames"]["01"]["attempts"][0]
            self.frame = document["frames"]["01"]
            self.rows = {
                "attempt": {
                    "EPISODE_ID": "00-06", "FRAME_NO": 1, "ATTEMPT_NO": 1,
                    "ATTEMPT_ID": self.attempt["attempt_id"],
                    "ATTEMPT_KIND": self.attempt["kind"],
                    "STATUS": self.attempt["result"],
                    "PAYLOAD": deepcopy(self.attempt),
                },
                "frame": {
                    "EPISODE_ID": "00-06", "FRAME_NO": 1,
                    "STATUS": self.frame["status"],
                    "CURRENT_ATTEMPT_ID": self.attempt["attempt_id"],
                    "CONTRACT_SHA256": source["frame_contract_sha256"],
                    "APPROVED_ARTIFACT_ID": None,
                },
            }
            self.queries = []
        def query_one(self, sql, args):
            assert "FOR UPDATE" in sql
            assert args == ("00-06",)
            self.queries.append(sql)
            return (self.rows["attempt"] if "TB_PRODUCTION_ATTEMPT" in sql
                    else self.rows["frame"] if "TB_PRODUCTION_FRAME" in sql
                    else None)
    return Db()


def test_exact_typed_projection_is_locked_and_payload_verified(sample):
    source, ledger = sample
    db = _typed_test_db(source, ledger)
    atomic._verify_typed_frame01(db, "00-06", ledger)
    assert len(db.queries) == 2
    assert "TB_PRODUCTION_ATTEMPT" in db.queries[0]
    assert "TB_PRODUCTION_FRAME" in db.queries[1]


@pytest.mark.parametrize("drift", [
    "attempt_missing", "frame_missing", "attempt_status", "frame_status",
    "attempt_id", "attempt_index", "attempt_kind", "attempt_episode",
    "attempt_payload", "attempt_payload_invalid", "frame_episode",
    "frame_no", "current_attempt_id", "contract", "approved_artifact",
])
def test_typed_projection_drift_fails_closed_before_success(sample, drift):
    source, ledger = sample
    db = _typed_test_db(source, ledger)
    a, f = db.rows["attempt"], db.rows["frame"]
    if drift == "attempt_missing":
        db.rows["attempt"] = None
    elif drift == "frame_missing":
        db.rows["frame"] = None
    elif drift == "attempt_status":
        a["STATUS"] = "success"
    elif drift == "frame_status":
        f["STATUS"] = "ORIGINAL_READY"
    elif drift == "attempt_id":
        a["ATTEMPT_ID"] = "wrong"
    elif drift == "attempt_index":
        a["ATTEMPT_NO"] = 2
    elif drift == "attempt_kind":
        a["ATTEMPT_KIND"] = "repair"
    elif drift == "attempt_episode":
        a["EPISODE_ID"] = "wrong"
    elif drift == "attempt_payload":
        a["PAYLOAD"]["result"] = "success"
    elif drift == "attempt_payload_invalid":
        a["PAYLOAD"] = "{bad json"
    elif drift == "frame_episode":
        f["EPISODE_ID"] = "wrong"
    elif drift == "frame_no":
        f["FRAME_NO"] = 2
    elif drift == "current_attempt_id":
        f["CURRENT_ATTEMPT_ID"] = "wrong"
    elif drift == "contract":
        f["CONTRACT_SHA256"] = "0" * 64
    elif drift == "approved_artifact":
        f["APPROVED_ARTIFACT_ID"] = "fabricated-approval"
    with pytest.raises(atomic.LedgerRecoveryDenied, match="TYPED_"):
        atomic._verify_typed_frame01(db, "00-06", ledger)




class _FullRepositorySqlFake:
    """Imitate only the exact SQL emitted by the *real* three repositories."""

    def __init__(self, source: dict, document: dict):
        import hashlib
        from platform.repository.mysql.mysql_production_ledger_authority_repository import canonical_bytes

        self.storage_id = "00-06"
        self.blob = canonical_bytes(document)
        self.sha = hashlib.sha256(self.blob).hexdigest()
        self.initial_sha = self.sha
        self.schema_version = 1
        self.engine_version = "test"
        self.typed_attempt = _typed_test_db(source, document).rows["attempt"]
        self.typed_frame = _typed_test_db(source, document).rows["frame"]
        self.writes = []
        self.fail_frame_write = False

    def query_one(self, sql, args):
        assert args == (self.storage_id,)
        if "TB_PRODUCTION_LEDGER_AUTHORITY" in sql:
            if "FOR UPDATE" in sql:
                return {"SHA256": self.sha}
            return {
                "EPISODE_ID": self.storage_id, "DOCUMENT_BLOB": self.blob,
                "SHA256": self.sha, "BYTE_SIZE": len(self.blob),
                "SCHEMA_VERSION": self.schema_version,
                "ENGINE_VERSION": self.engine_version,
            }
        if "TB_PRODUCTION_ATTEMPT" in sql:
            assert "FOR UPDATE" in sql
            return deepcopy(self.typed_attempt)
        if "TB_PRODUCTION_FRAME" in sql:
            assert "FOR UPDATE" in sql
            return deepcopy(self.typed_frame)
        raise AssertionError("unrecognized SELECT: " + sql)

    def execute(self, sql, args):
        import hashlib
        assert sql.startswith("INSERT INTO ")
        if "TB_PRODUCTION_LEDGER_AUTHORITY" in sql:
            assert len(args) == 6 and args[0] == self.storage_id
            self.blob = args[3]
            self.sha = hashlib.sha256(self.blob).hexdigest()
            assert self.sha == args[4] and args[5] == len(self.blob)
            self.writes.append("authority")
        elif "TB_PRODUCTION_ATTEMPT" in sql:
            assert len(args) == 14 and args[0]
            self.typed_attempt = {
                "ATTEMPT_ID": args[0], "EPISODE_ID": args[1],
                "FRAME_NO": args[2], "ATTEMPT_NO": args[3],
                "ATTEMPT_KIND": args[4], "STATUS": args[5], "PAYLOAD": args[13],
            }
            self.writes.append("attempt")
        elif "TB_PRODUCTION_FRAME" in sql:
            if self.fail_frame_write:
                raise RuntimeError("injected projection write failure")
            assert len(args) == 6
            self.typed_frame = {
                "EPISODE_ID": args[0], "FRAME_NO": args[1], "STATUS": args[2],
                "APPROVED_ARTIFACT_ID": args[3],
                "CURRENT_ATTEMPT_ID": args[4], "CONTRACT_SHA256": args[5],
            }
            self.writes.append("frame")
        else:
            raise AssertionError("unrecognized upsert: " + sql)
        return 1

    @property
    def state(self):
        return (self.blob, self.sha, deepcopy(self.typed_frame),
                deepcopy(self.typed_attempt), list(self.writes))

    def transaction(self):
        from contextlib import contextmanager

        @contextmanager
        def scope():
            before = self.state
            try:
                yield
            except BaseException:
                self.blob, self.sha, self.typed_frame, self.typed_attempt, self.writes = before
                raise

        return scope()


def test_real_mysql_repo_statements_share_atomic_transaction(sample, monkeypatch):
    source, document = sample
    db = _FullRepositorySqlFake(source, document)
    monkeypatch.setattr(atomic.episode_identity, "storage_episode_id", lambda _: "00-06")
    monkeypatch.setattr(atomic.ledger_store, "mode", lambda: "mysql")
    with db.transaction():
        assert atomic.locked_ledger_update(
            db, source["episode"], source, already_succeeded=False,
        ) is True
    assert db.writes == ["authority", "attempt", "frame"]
    # Exact repository-produced SHA, JSON payload, projections and identity.
    from platform.repository.mysql.mysql_production_ledger_authority_repository import (
        MySqlProductionLedgerAuthorityRepository,
    )
    persisted = MySqlProductionLedgerAuthorityRepository(db).get("00-06")["document"]
    assert persisted["frames"]["01"]["status"] == "ORIGINAL_READY"
    assert db.typed_attempt["STATUS"] == "success"
    assert db.typed_frame["STATUS"] == "ORIGINAL_READY"
    with db.transaction():
        assert atomic.locked_ledger_update(
            db, source["episode"], source, already_succeeded=True,
        ) is False
    assert db.writes == ["authority", "attempt", "frame"]


def test_real_repository_projection_failure_rolls_back_all_three(sample, monkeypatch):
    source, document = sample
    db = _FullRepositorySqlFake(source, document)
    db.fail_frame_write = True
    before = db.state
    monkeypatch.setattr(atomic.episode_identity, "storage_episode_id", lambda _: "00-06")
    monkeypatch.setattr(atomic.ledger_store, "mode", lambda: "mysql")
    with pytest.raises(RuntimeError, match="injected projection write failure"):
        with db.transaction():
            atomic.locked_ledger_update(
                db, source["episode"], source, already_succeeded=False,
            )
    assert db.state == before
    assert db.typed_frame["STATUS"] == "TECH_FAILED"
    assert db.typed_attempt["STATUS"] == "technical_failure"


def test_real_repository_idempotent_replay_refuses_typed_drift(sample, monkeypatch):
    source, document = sample
    db = _FullRepositorySqlFake(source, document)
    monkeypatch.setattr(atomic.episode_identity, "storage_episode_id", lambda _: "00-06")
    monkeypatch.setattr(atomic.ledger_store, "mode", lambda: "mysql")
    with db.transaction():
        assert atomic.locked_ledger_update(db, source["episode"], source,
                                           already_succeeded=False)
    db.typed_attempt["PAYLOAD"] = '{"fabricated": true}'
    before = db.state
    with pytest.raises(atomic.LedgerRecoveryDenied, match="TYPED_ATTEMPT_DRIFT"):
        with db.transaction():
            atomic.locked_ledger_update(db, source["episode"], source,
                                        already_succeeded=True)
    assert db.state == before




def _read_only_preview_env(sample, monkeypatch):
    import native_baseline_readonly_preflight as preflight

    source, ledger = sample
    source["queue_item_id"] = "synthetic-queue-01"
    source["prompt_package_sha256"] = "b" * 64
    original = ledger["frames"]["01"]["attempts"][0]
    captured = {"queries": 0, "sql_writes": 0}
    row_frame = {
        "episode_id": "test-storage-00-06",
        "frame_no": 1,
        "status": "TECH_FAILED",
        "current_attempt_id": original["attempt_id"],
        "contract_sha256": source["frame_contract_sha256"],
        "approved_artifact_id": None,
    }
    row_attempt = {
        "episode_id": "test-storage-00-06",
        "frame_no": 1,
        "attempt_no": 1,
        "attempt_id": original["attempt_id"],
        "attempt_kind": "original",
        "status": "technical_failure",
        "payload": deepcopy(original),
    }
    state = {"episode_id": "synthetic-logical-00-06",
             "attempts_consumed": 1, "active_attempt_index": None, "fencing_counter": 5}
    generation_raw = {
        "FENCING_TOKEN": 5, "GENERATION_KEY": source["generation_key"],
        "STATUS": "OUTCOME_UNKNOWN",
        "FAILURE_CLASS": reconcile.EXPECTED_REASON,
        "RESULT_REF": None,
        "DISPATCH_COMMITTED_AT": datetime(2026, 10, 11, 12, 7),
        "CONTROLLER_MODEL": "gpt-6-luna",
        "PAYLOAD_MODEL": "gpt-image-2.5-flare",
        "PAYLOAD_QUALITY": "high",
        "PROVIDER": "codex_subscription",
        "MODEL_POLICY_SHA256": "a" * 64,
        "CONTEXT": {
            "scope": "visual_lock",
            "visual_lock_frame": 1,
            "queue_item_id": source["queue_item_id"],
            "tool_capability_claim": "UNKNOWN_NOT_YET_PROVEN",
            "frame_contract_sha256": source["frame_contract_sha256"],
            "prompt_package_sha256": source["prompt_package_sha256"],
            "controller_effort": "high",
            "model_policy_sha256": "a" * 64,
        },
    }
    captured["generation_raw"] = generation_raw
    attempt = {
        "status": "OUTCOME_UNKNOWN",
        "generation_key": source["generation_key"],
        "failure_class": reconcile.EXPECTED_REASON,
        "result_ref": None,
        "dispatch_committed_at": datetime(2026, 10, 11, 12, 7),
    }

    class ReadOnlySqlConnection:
        def close(self): pass
        def query_one(self, statement, _args):
            assert statement.lstrip().startswith("SELECT")
            assert "FOR UPDATE" not in statement
            captured["queries"] += 1
            if "TB_GENERATION_ATTEMPT" in statement:
                return deepcopy(generation_raw)
            if "TB_PRODUCTION_FRAME" in statement:
                return {
                    "EPISODE_ID": row_frame["episode_id"],
                    "FRAME_NO": row_frame["frame_no"],
                    "STATUS": row_frame["status"],
                    "CURRENT_ATTEMPT_ID": row_frame["current_attempt_id"],
                    "CONTRACT_SHA256": row_frame["contract_sha256"],
                    "APPROVED_ARTIFACT_ID": row_frame["approved_artifact_id"],
                }
            raise AssertionError("unrecognized read-only SELECT")
        def query_all(self, statement, _args):
            assert statement.lstrip().startswith("SELECT")
            assert "FOR UPDATE" not in statement
            captured["queries"] += 1
            if "TB_PRODUCTION_ATTEMPT" in statement:
                return [{
                    "EPISODE_ID": row_attempt["episode_id"],
                    "FRAME_NO": row_attempt["frame_no"],
                    "ATTEMPT_NO": row_attempt["attempt_no"],
                    "ATTEMPT_ID": row_attempt["attempt_id"],
                    "ATTEMPT_KIND": row_attempt["attempt_kind"],
                    "STATUS": row_attempt["status"],
                    "PAYLOAD": deepcopy(row_attempt["payload"]),
                }]
            raise AssertionError("unrecognized read-only SELECT")

    monkeypatch.setattr(preflight.cas, "verify_frame01_sources", lambda _ep: source)
    monkeypatch.setattr(preflight.ledger_store, "load_authority", lambda _ep: ledger)
    monkeypatch.setattr(preflight.attempt_authority, "frame_key", lambda *_: "frame-01")
    monkeypatch.setattr(preflight.attempt_authority, "load_asset_state", lambda *_: state)
    monkeypatch.setattr(preflight.attempt_authority, "load_attempt", lambda *_: attempt)
    monkeypatch.setattr(preflight.attempt_authority, "_connect", ReadOnlySqlConnection)
    monkeypatch.setattr(preflight, "storage_episode_id", lambda _ep: "test-storage-00-06")
    return preflight, source, ledger, row_frame, row_attempt, state, attempt, captured


def test_readonly_preflight_is_evidence_only_and_never_authorizes_mutation(sample, monkeypatch):
    preflight, source, _ledger, _frame, _attempt, _state, _generation, captured = (
        _read_only_preview_env(sample, monkeypatch)
    )
    result = preflight.inspect(source["episode"])
    assert result["status"] == "READ_ONLY_EVIDENCE_READY_TEST_DB_STILL_REQUIRED"
    assert result["source_evidence_sha256"] == source["evidence_sha256"]
    assert result["candidate_sha256"] == source["candidate_sha256"]
    assert result["ledger_frame_status"] == "TECH_FAILED"
    assert result["source_model_attested"] is False
    assert result["pixel_review_pass"] is False
    assert result["authorized_to_mutate_production"] is False
    assert result["real_mysql_integration_tests_passed"] is False
    assert result["sql_writes"] == result["model_calls"] == captured["sql_writes"] == 0
    assert captured["queries"] == 3


@pytest.mark.parametrize("drift", [
    "attempt_consumed", "attempt_active", "fencing", "generation_status",
    "generation_key", "failure_class", "result_ref", "missing_dispatch",
    "typed_frame_status", "typed_frame_contract", "typed_frame_id",
    "typed_attempt_status", "typed_attempt_payload", "typed_attempt_namespace",
    "raw_fencing", "raw_payload_model", "raw_context_contract", "raw_context_policy",
])
def test_readonly_preflight_denies_cross_authority_drift(sample, monkeypatch, drift):
    preflight, source, _ledger, frame, typed, state, generation_row, captured = (
        _read_only_preview_env(sample, monkeypatch)
    )
    if drift == "attempt_consumed":
        state["attempts_consumed"] = 2
    elif drift == "attempt_active":
        state["active_attempt_index"] = 1
    elif drift == "fencing":
        state["fencing_counter"] = 0
    elif drift == "generation_status":
        generation_row["status"] = "SUCCEEDED"
    elif drift == "generation_key":
        generation_row["generation_key"] = "fake"
    elif drift == "failure_class":
        generation_row["failure_class"] = "fake"
    elif drift == "result_ref":
        generation_row["result_ref"] = "fake"
    elif drift == "missing_dispatch":
        generation_row["dispatch_committed_at"] = None
    elif drift == "typed_frame_status":
        frame["status"] = "ORIGINAL_READY"
    elif drift == "typed_frame_contract":
        frame["contract_sha256"] = "0" * 64
    elif drift == "typed_frame_id":
        frame["current_attempt_id"] = "fake"
    elif drift == "typed_attempt_status":
        typed["status"] = "success"
    elif drift == "typed_attempt_payload":
        typed["payload"]["result"] = "success"
    elif drift == "typed_attempt_namespace":
        typed["episode_id"] = "fake"
    elif drift == "raw_fencing":
        captured["generation_raw"]["FENCING_TOKEN"] = 4
    elif drift == "raw_payload_model":
        captured["generation_raw"]["PAYLOAD_MODEL"] = "fake"
    elif drift == "raw_context_contract":
        captured["generation_raw"]["CONTEXT"]["frame_contract_sha256"] = "0" * 64
    elif drift == "raw_context_policy":
        captured["generation_raw"]["CONTEXT"]["model_policy_sha256"] = "0" * 64
    with pytest.raises(preflight.NativeFrame01PreflightDenied):
        preflight.inspect(source["episode"])
    assert captured["sql_writes"] == 0

def test_atomic_ledger_refuses_non_mysql_mode(sample, monkeypatch):
    source, document = sample
    monkeypatch.setattr(atomic.ledger_store, "mode", lambda: "json")
    with pytest.raises(atomic.LedgerRecoveryDenied, match="MYSQL_LEDGER_REQUIRED"):
        atomic.locked_ledger_update(object(), source["episode"], source,
                                    already_succeeded=False)
