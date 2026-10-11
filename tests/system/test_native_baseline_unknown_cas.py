"""Hermetic fail-closed coverage for the one-off native Frame01 UNKNOWN CAS.

No production MySQL, native Codex, real image tool or project runtime env is used.
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from io import BytesIO
from PIL import Image
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import pytest

SYSTEM = Path(__file__).resolve().parents[2] / "episodes" / "_system"
if str(SYSTEM) not in sys.path:
    sys.path.insert(0, str(SYSTEM))

import native_baseline_unknown_cas as reconcile


REQUEST = "66c88e2746514f49ae14460fa98bbd7f"
THREAD = "01a12adb-b801-7bf0-ac83-fe74828b75f1"
FILE = "exec-6f5a7c1e-1aed-4058-a77b-3a2014f2b896.png"
QUEUE_ID = "65db61f1e871"
def tiny_png(rgb):
    stream = BytesIO()
    Image.new("RGB", (1, 1), rgb).save(stream, format="PNG")
    return stream.getvalue()


RAW = tiny_png((10, 20, 30))
CANDIDATE = tiny_png((20, 30, 40))


class FakeMySql:
    def __init__(self, state: dict, row: dict):
        self.state = state
        self.row = row
        self.mutations = 0
        self.ledger_status = "TECH_FAILED"
        self.closed = False
        self.force_cas_loss = False

    @contextmanager
    def transaction(self):
        before = copy.deepcopy((self.state, self.row, self.mutations, self.ledger_status))
        try:
            yield
        except BaseException:
            self.state, self.row, self.mutations, self.ledger_status = before
            raise

    def query_one(self, sql, args):
        assert "TB_GENERATION_ATTEMPT" in sql and "FOR UPDATE" in sql
        assert "ATTEMPT_INDEX=1" in sql and len(args) == 2
        return copy.deepcopy(self.row)

    def execute(self, sql, args):
        assert "STATUS='SUCCEEDED'" in sql
        assert "AND STATUS='OUTCOME_UNKNOWN'" in sql
        assert "AND FENCING_TOKEN=%s" in sql
        assert "TERMINAL_AT=%s" in sql
        assert "AND GENERATION_KEY=%s" in sql
        if self.force_cas_loss:
            return 0
        assert self.row["STATUS"] == "OUTCOME_UNKNOWN"
        assert self.row["GENERATION_KEY"] == args[5]
        self.row["STATUS"] = "SUCCEEDED"
        self.row["TERMINAL_AT"] = args[1]
        self.row["RESULT_REF"] = args[2]
        self.mutations += 1
        return 1

    def close(self):
        self.closed = True


def sha(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture()
def example(tmp_path, monkeypatch):
    ep = tmp_path / "episodes" / "00_独立篇" / "06_五十亩山地之后_全新重制"
    ep.mkdir(parents=True)
    monkeypatch.setattr(reconcile, "ROOT", tmp_path)
    raw = ep / "media/raw/01-1791720392.png"
    candidate = ep / f"media/candidates/scheduled/01-{QUEUE_ID}-a1.png"
    log = ep / f"meta/image-workers/01-{QUEUE_ID}-a1.jsonl"
    for p, value in ((raw, RAW), (candidate, CANDIDATE), (log, b"real Codex JSONL")):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(value)
    key = reconcile.authority.frame_key(ep, 1)
    generation_key = reconcile.authority.stable_generation_key(
        reconcile.logical_asset_identity.episode_id(ep), key, 1)
    evidence = {
        "schema_version": 1, "episode_id": "00-06", "frame": 1,
        "attempt_index": 1, "kind": reconcile.EXPECTED_EVIDENCE_KIND,
        "status": reconcile.EXPECTED_EVIDENCE_STATUS,
        "transport": "native_codex", "model_execution_kind": "image",
        "codex_turn_completed": True, "codex_jsonl_image_generation_call_count": 0,
        "provider_model_attested": False, "review_pass": False,
        "attempt_authority_mutated": False,
        "source_generated_png_sha256": sha(RAW),
        "source_generated_png_bytes": len(RAW),
        "episode_raw_png_sha256": sha(RAW),
        "normalized_png_sha256": sha(CANDIDATE),
        "codex_log_sha256": sha(log.read_bytes()),
        "frame_contract_sha256": "a" * 64, "prompt_package_sha256": "b" * 64,
        "native_runner_request_id": REQUEST, "queue_item_id": QUEUE_ID,
        "thread_id": THREAD, "generated_artifact_relative_path": f"{THREAD}/{FILE}",
        "episode_raw_png_relative_path": raw.relative_to(ep).as_posix(),
        "normalized_png_relative_path": candidate.relative_to(ep).as_posix(),
        "generation_key": generation_key,
    }
    evidence_path = ep / reconcile.EVIDENCE_REL
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(evidence, ensure_ascii=False), encoding="utf-8")
    queue = {"items": [
        {"frame": 1, "id": QUEUE_ID, "status": "external_blocked",
         "scope": "visual_lock", "kind": "original",
         "execution": {"transaction_id": "9" * 32},
         "prompt_package": {"frame_contract_sha256": "a" * 64, "package_sha256": "b" * 64,
                            "scene_prompt_sha256": "c" * 64}},
        *({"frame": frame, "status": "queued", "depends_on": [1]}
          for frame in (16, 8, 17)),
    ]}
    monkeypatch.setattr(reconcile.scheduler_core, "load_queue", lambda _: queue)
    monkeypatch.setattr(reconcile.scheduler_core._QUEUE_LOCK_LOCAL, "depths",
                        {ep.resolve().as_posix(): 1}, raising=False)
    monkeypatch.setattr(reconcile.canvas_normalize, "read_canvas",
                        lambda _: (1, 1, "1:1"))
    monkeypatch.setattr(reconcile.episode_state_persistence, "load", lambda _: {"current_state": "STORYBOARD_LOCKED"})
    monkeypatch.setattr(reconcile.codex_user_runner, "read_task_result",
                        lambda _: {"request_id": REQUEST})
    monkeypatch.setattr(reconcile.codex_user_runner, "codex_home",
                        lambda: (tmp_path / ".codex", {}))
    def fake_proof(**kwargs):
        return {
            "proof_kind": "TRUSTED_NATIVE_RUNNER_THREAD_SCOPED_IMAGE_SHA",
            "runner_request_id": REQUEST, "native_codex_thread_id": THREAD,
            "exported_artifact_relative_path": f"{THREAD}/{FILE}",
            "raw_png_sha256": sha(RAW), "source_png_sha256": sha(RAW),
            "native_codex_log_sha256": sha(log.read_bytes()),
            "native_image_generation_jsonl_events": 0,
            "provider_model_attested": False, "review_pass": False,
        }
    monkeypatch.setattr(reconcile.production_native_baseline_proof,
                        "verify_runner_scoped_generated_image", fake_proof)
    context = {
        "scope": "visual_lock", "queue_item_id": QUEUE_ID,
        "visual_lock_frame": 1,
        "tool_capability_claim": "UNKNOWN_NOT_YET_PROVEN",
        "controller_effort": "high",
        "model_policy_sha256": "e" * 64,
        "image_capability_proof_purpose": reconcile.production_native_baseline_proof.REASON,
        "frame_contract_sha256": "a" * 64,
        "prompt_package_sha256": "b" * 64,
    }
    row = {
        "STATUS": "OUTCOME_UNKNOWN",
        "FENCING_TOKEN": 5, "GENERATION_KEY": generation_key,
        "FAILURE_CLASS": reconcile.EXPECTED_REASON,
        "RESULT_REF": None, "CONTEXT": json.dumps(context),
        "DISPATCH_COMMITTED_AT": datetime(2026, 10, 11, 12, 7),
        "MODEL_POLICY_SHA256": "e" * 64,
        "CONTROLLER_MODEL": "gpt-6-luna",
        "PAYLOAD_MODEL": "gpt-image-2.5-flare",
        "PAYLOAD_QUALITY": "high", "PROVIDER": "codex_subscription",
    }
    state = {"ATTEMPTS_CONSUMED": 1, "ACTIVE_ATTEMPT_INDEX": None,
             "FENCING_COUNTER": 5}
    db = FakeMySql(state, row)
    monkeypatch.setattr(reconcile.authority, "_connect", lambda: db)
    monkeypatch.setattr(reconcile.authority, "_row",
                        lambda _, eid, asset: copy.deepcopy(db.state))
    monkeypatch.setattr(reconcile.authority, "_utcnow",
                        lambda: datetime(2026, 10, 11, 12, 30))
    monkeypatch.setattr(reconcile.atomic_ledger, "locked_ledger_update",
                        lambda conn, episode, source, already_succeeded=False: not already_succeeded)
    return ep, raw, candidate, log, evidence_path, evidence, queue, db


def commit(ep, evidence_path, fence=5, evidence_sha=None):
    return reconcile.reconcile_frame01_unknown(
        ep, expected_fencing_token=fence,
        expected_evidence_sha256=evidence_sha or (
            sha(evidence_path.read_bytes()) if evidence_path.is_file() else "0" * 64
        ),
    )


def test_successful_cas_is_single_update_and_idempotent(example):
    ep, raw, candidate, log, evidence_path, evidence, queue, db = example
    before = {p: p.read_bytes() for p in (raw, candidate, log, evidence_path)}
    result = commit(ep, evidence_path)
    assert result["status"] == "SUCCEEDED"
    assert result["attempt_index"] == 1 and result["ledger_reconciled"] is True
    assert result["visual_review_pass"] is False and result["review_pass"] is False
    assert db.mutations == 1 and db.state["ATTEMPTS_CONSUMED"] == 1
    assert db.state["ACTIVE_ATTEMPT_INDEX"] is None
    assert db.row["FAILURE_CLASS"] == reconcile.EXPECTED_REASON
    assert db.row["TERMINAL_AT"] == datetime(2026, 10, 11, 12, 30)
    assert all(p.read_bytes() == value for p, value in before.items())
    assert queue["items"][0]["status"] == "external_blocked"
    repeated = commit(ep, evidence_path)
    assert repeated["idempotent"] is True
    assert db.mutations == 1 and db.closed


@pytest.mark.parametrize("mutation", [
    "raw_sha", "candidate_sha", "codex_log_sha", "runner_provenance",
    "source_id", "wrong_status", "wrong_evidence_kind", "missing_evidence",
    "queue_frame_started", "queue_binding_drift", "stage_changed",
    "canvas_mismatch", "candidate_path_swap", "model_policy_drift",
    "raw_path_swap", "raw_size_drift",
    "wrong_fence", "wrong_evidence_digest", "wrong_attempt_status",
    "wrong_fail_class", "stale_consumption", "active_attempt",
    "wrong_context", "wrong_generation_key", "cas_race",
])
def test_all_mismatches_fail_closed_without_mysql_update(example, monkeypatch, mutation):
    ep, raw, candidate, log, evidence_path, evidence, queue, db = example
    evidence = copy.deepcopy(evidence)
    if mutation == "raw_sha":
        raw.write_bytes(RAW + b"tampered")
    elif mutation == "candidate_sha":
        candidate.write_bytes(CANDIDATE + b"tampered")
    elif mutation == "codex_log_sha":
        log.write_bytes(b"tampered")
    elif mutation == "runner_provenance":
        monkeypatch.setattr(reconcile.production_native_baseline_proof,
                            "verify_runner_scoped_generated_image", lambda **_: None)
    elif mutation == "source_id":
        evidence["native_runner_request_id"] = "invalid"
    elif mutation == "wrong_status":
        evidence["status"] = "PASS"
    elif mutation == "wrong_evidence_kind":
        evidence["kind"] = "UNTRUSTED"
    elif mutation == "missing_evidence":
        evidence_path.unlink()
    elif mutation == "queue_frame_started":
        queue["items"][2]["status"] = "running"
    elif mutation == "queue_binding_drift":
        queue["items"][0]["prompt_package"]["package_sha256"] = "c" * 64
    elif mutation == "canvas_mismatch":
        monkeypatch.setattr(reconcile.canvas_normalize, "read_canvas",
                            lambda _: (1080, 1350, "4:5"))
    elif mutation == "raw_path_swap":
        evidence["episode_raw_png_relative_path"] = "media/other.png"
        (ep / "media/other.png").write_bytes(RAW)
    elif mutation == "raw_size_drift":
        evidence["source_generated_png_bytes"] += 1
    elif mutation == "candidate_path_swap":
        evidence["normalized_png_relative_path"] = "media/candidates/scheduled/other.png"
        (ep / "media/candidates/scheduled/other.png").write_bytes(CANDIDATE)
    elif mutation == "model_policy_drift":
        db.row["MODEL_POLICY_SHA256"] = "f" * 64
    elif mutation == "stage_changed":
        monkeypatch.setattr(reconcile.episode_state_persistence, "load",
                            lambda _: {"current_state": "VISUAL_CALIBRATED"})
    elif mutation == "wrong_fence":
        db.state["FENCING_COUNTER"] = 6
    elif mutation == "wrong_evidence_digest":
        pass
    elif mutation == "wrong_attempt_status":
        db.row["STATUS"] = "DISPATCH_COMMITTED"
    elif mutation == "wrong_fail_class":
        db.row["FAILURE_CLASS"] = "OTHER"
    elif mutation == "stale_consumption":
        db.state["ATTEMPTS_CONSUMED"] = 2
    elif mutation == "active_attempt":
        db.state["ACTIVE_ATTEMPT_INDEX"] = 1
    elif mutation == "wrong_context":
        context = json.loads(db.row["CONTEXT"])
        context["prompt_package_sha256"] = "c" * 64
        db.row["CONTEXT"] = json.dumps(context)
    elif mutation == "wrong_generation_key":
        db.row["GENERATION_KEY"] = "wrong"
    elif mutation == "cas_race":
        db.force_cas_loss = True
    if mutation in {"source_id", "wrong_status", "wrong_evidence_kind", "candidate_path_swap", "raw_path_swap", "raw_size_drift"}:
        evidence_path.write_text(json.dumps(evidence, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(reconcile.NativeReconciliationDenied):
        commit(ep, evidence_path,
               evidence_sha="0" * 64 if mutation == "wrong_evidence_digest" else None)
    assert db.mutations == 0
    assert db.row["STATUS"] != "SUCCEEDED"


def test_out_of_scope_episode_rejected_before_runner_or_database(example, tmp_path):
    ep, *rest = example
    other = tmp_path / "episodes" / "elsewhere"
    other.mkdir(parents=True)
    with pytest.raises(reconcile.NativeReconciliationDenied, match="EPISODE_SCOPE"):
        reconcile.verify_frame01_sources(other)


def test_direct_cas_requires_canonical_queue_writer_lock(example, monkeypatch):
    ep, _raw, _candidate, _log, evidence_path, _evidence, _queue, db = example
    monkeypatch.setattr(reconcile.scheduler_core._QUEUE_LOCK_LOCAL, "depths", {})
    with pytest.raises(reconcile.NativeReconciliationDenied, match="QUEUE_OWNER_LOCK_REQUIRED"):
        commit(ep, evidence_path)
    assert db.mutations == 0
    assert db.row["STATUS"] == "OUTCOME_UNKNOWN"


def test_mysql_atomic_rollback_if_late_cas_fails(example, monkeypatch):
    ep, _raw, _candidate, _log, evidence_path, _evidence, _queue, db = example
    def update_ledger(connection, episode, source, *, already_succeeded):
        assert connection is db
        assert not already_succeeded
        connection.ledger_status = "ORIGINAL_READY"
        return True
    monkeypatch.setattr(reconcile.atomic_ledger, "locked_ledger_update", update_ledger)
    db.force_cas_loss = True
    with pytest.raises(reconcile.NativeReconciliationDenied, match="CAS_LOST"):
        commit(ep, evidence_path)
    assert db.row["STATUS"] == "OUTCOME_UNKNOWN"
    assert db.ledger_status == "TECH_FAILED"
    assert db.mutations == 0


def test_mysql_atomic_rollback_if_ledger_write_raises(example, monkeypatch):
    ep, _raw, _candidate, _log, evidence_path, _evidence, _queue, db = example
    def update_ledger(connection, episode, source, *, already_succeeded):
        connection.ledger_status = "ORIGINAL_READY"
        raise RuntimeError("injected typed projection failure")
    monkeypatch.setattr(reconcile.atomic_ledger, "locked_ledger_update", update_ledger)
    with pytest.raises(RuntimeError, match="typed projection failure"):
        commit(ep, evidence_path)
    assert db.row["STATUS"] == "OUTCOME_UNKNOWN"
    assert db.ledger_status == "TECH_FAILED"
    assert db.mutations == 0


def test_queue_crash_after_mysql_commit_only_resumes_original_item(example, monkeypatch):
    from contextlib import contextmanager
    ep, raw, candidate, log, evidence_path, evidence, original_queue, db = example
    persisted = {"queue": copy.deepcopy(original_queue), "saved": 0, "journal": 0}
    @contextmanager
    def locked(_ep):
        yield
    def read_queue(_ep):
        return copy.deepcopy(persisted["queue"])
    def save_queue(_ep, value):
        persisted["saved"] += 1
        if persisted["saved"] == 1:
            raise OSError("simulated interruption after SQL commit")
        persisted["queue"] = copy.deepcopy(value)
    monkeypatch.setattr(reconcile.scheduler_core, "queue_transaction", locked)
    monkeypatch.setattr(reconcile.scheduler_core, "load_queue", read_queue)
    monkeypatch.setattr(reconcile.scheduler_core, "save_queue", save_queue)
    monkeypatch.setattr(reconcile.ledger_store, "load_authority",
                        lambda _ep: {"frames": {"01": {"status": "ORIGINAL_READY"}}})
    monkeypatch.setattr(reconcile.atomic_ledger, "_check_existing",
                        lambda doc, source, completed: {})
    monkeypatch.setattr(reconcile.authority, "load_attempt",
                        lambda *_: {"status": db.row["STATUS"],
                                    "generation_key": db.row["GENERATION_KEY"],
                                    "result_ref": db.row["RESULT_REF"]})
    import production_recovery
    def fake_mark_terminal(_ep, item, phase, **kwargs):
        assert phase == "COMMITTED"
        persisted["journal"] += 1
        item["execution"]["phase"] = phase
    monkeypatch.setattr(production_recovery, "mark_terminal", fake_mark_terminal)
    with pytest.raises(OSError, match="interruption"):
        reconcile.reconcile_frame01_and_queue(
            ep, expected_fencing_token=5,
            expected_evidence_sha256=sha(evidence_path.read_bytes()),
        )
    # At least once: the entire MySQL TX committed, but external Queue did not.
    assert db.mutations == 1
    assert db.row["STATUS"] == "SUCCEEDED"
    assert persisted["queue"]["items"][0]["status"] == "external_blocked"
    result = reconcile.reconcile_frame01_and_queue(
        ep, expected_fencing_token=5,
        expected_evidence_sha256=sha(evidence_path.read_bytes()),
    )
    assert result["idempotent"] is True
    assert result["queue_reconciled"] is True
    assert result["queue_idempotent"] is False
    assert result["visual_review_pass"] is False
    assert db.mutations == 1
    frame = persisted["queue"]["items"][0]
    assert frame["status"] == "generated"
    assert frame["output_path"] == candidate.relative_to(reconcile.ROOT).as_posix()
    assert frame["generation_key"] == evidence["generation_key"]
    assert frame["frame_contract_sha256"] == evidence["frame_contract_sha256"]
    assert frame["prompt_package_sha256"] == evidence["prompt_package_sha256"]
    assert frame["attempt_index"] == 1
    assert frame["unknown_reconciliation"]["pixel_review_pass"] is False
    import review_queue
    review_result = review_queue.enqueue(
        persisted["queue"], episode=ep, source_item=frame,
        artifact_path=frame["output_path"],
        artifact_sha256=evidence["normalized_png_sha256"],
        policy={"role": "vision.fast", "model_policy_sha256": "d" * 64,
                "model": "gpt-6-luna"},
    )
    assert review_result["status"] == "ENQUEUED"
    assert review_result["item"]["frame_contract_sha256"] == evidence["frame_contract_sha256"]
    assert review_result["item"]["prompt_package_sha256"] == evidence["prompt_package_sha256"]
    assert review_result["item"]["status"] == "queued"
    assert review_result["item"]["receipt"] is None
    assert review_result["item"]["generation_key"] == evidence["generation_key"]
    assert frame["execution"]["transaction_id"] == "9" * 32
    assert frame["execution"]["phase"] == "COMMITTED"
    assert all(x["status"] == "queued" for x in persisted["queue"]["items"][1:])
    final = reconcile.reconcile_frame01_and_queue(
        ep, expected_fencing_token=5,
        expected_evidence_sha256=sha(evidence_path.read_bytes()),
    )
    assert final["queue_idempotent"] is True
    assert db.mutations == 1
