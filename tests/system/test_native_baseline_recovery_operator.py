"""Guarded Frame01 operator: no production DB or model touched in tests."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "scripts", ROOT / "episodes" / "_system"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import native_baseline_recovery_operator as op
import storyos_native_frame01_recovery as cli


def ready():
    return {
        "status": "READ_ONLY_EVIDENCE_READY_TEST_DB_STILL_REQUIRED",
        "source_evidence_sha256": "a" * 64,
        "candidate_sha256": "b" * 64,
        "fencing_token": 5,
        "generation_attempt_status": "OUTCOME_UNKNOWN",
        "generation_attempts_consumed": 1,
        "authorized_to_mutate_production": False,
        "sql_writes": 0,
        "model_calls": 0,
    }


def test_plan_never_promotes_authority_or_attempt(tmp_path, monkeypatch):
    ep = tmp_path / "episodes/00_独立篇/06_五十亩山地之后_全新重制"
    ep.mkdir(parents=True)
    monkeypatch.setattr(op, "ROOT", tmp_path)
    monkeypatch.setattr(op.preflight, "inspect", lambda _: ready())
    result = op.plan(ep)
    assert result["status"] == "PLAN_ONLY_PRODUCTION_WRITE_NOT_AUTHORIZED"
    assert result["fencing_token"] == 5
    assert result["backup_required"] is True
    assert result["sql_writes"] == result["model_calls"] == 0
    assert result["authorized_to_mutate_production"] is False


@pytest.mark.parametrize("drift", [
    "review_ready", "attempt_used_twice", "fake_approval", "model_called",
    "image_produced", "stale_status",
])
def test_plan_denies_untrusted_readiness(tmp_path, monkeypatch, drift):
    ep = tmp_path / "episodes/00_独立篇/06_五十亩山地之后_全新重制"
    ep.mkdir(parents=True)
    monkeypatch.setattr(op, "ROOT", tmp_path)
    data = ready()
    if drift == "review_ready":
        data["status"] = "REVIEW_PASS"
    if drift == "attempt_used_twice":
        data["generation_attempts_consumed"] = 2
    if drift == "fake_approval":
        data["authorized_to_mutate_production"] = True
    if drift == "model_called":
        data["model_calls"] = 1
    if drift == "image_produced":
        data["sql_writes"] = 1
    if drift == "stale_status":
        data["generation_attempt_status"] = "SUCCEEDED"
    monkeypatch.setattr(op.preflight, "inspect", lambda _: data)
    with pytest.raises(op.NativeFrame01OperationDenied):
        op.plan(ep)


@pytest.fixture
def fake_archive(tmp_path, monkeypatch):
    ep = tmp_path / "episodes/00_独立篇/06_五十亩山地之后_全新重制"
    ep.mkdir(parents=True)
    archive = tmp_path / ".storyos" / "native-frame01-recovery-archives"
    monkeypatch.setattr(op, "ROOT", tmp_path)
    monkeypatch.setattr(op, "ARCHIVES", archive)
    data = ready()
    files = {"state.json": b'{"fake":"isolated-synthetic-authority"}\n'}
    files.update({"sources/" + key + ".bin": key.encode("utf-8")
                  for key in op.freeze.SOURCE_KEYS})
    monkeypatch.setattr(op, "capture", lambda _: (copy.deepcopy(data), copy.deepcopy(files)))
    result = op.backup(ep)
    assert result["status"] == "SEALED_READ_ONLY_BACKUP_NOT_PRODUCTION_AUTHORIZATION"
    assert result["authorized_to_mutate_production"] is False
    manifest = Path(result["archive"]) / "manifest.json"
    assert manifest.is_file()
    assert hashlib.sha256(manifest.read_bytes()).hexdigest() == result["manifest_sha256"]
    return ep, result, manifest


def test_backup_is_complete_with_sealed_hash_and_can_verify(fake_archive):
    ep, result, manifest = fake_archive
    op._verified_archive(ep, manifest, result["manifest_sha256"],
                         result["fencing_token"], result["evidence_sha256"])
    record = json.loads(manifest.read_text(encoding="utf-8"))
    assert len(record["files"]) == 7
    assert "state.json" in record["files"]
    assert set(record["files"]) == {"state.json"} | {
        "sources/" + key + ".bin" for key in op.freeze.SOURCE_KEYS
    }


@pytest.mark.parametrize("change", ["manifest", "content", "unexpected_file", "fencing"])
def test_backup_detects_tamper_or_fence_change(fake_archive, change):
    ep, result, manifest = fake_archive
    if change == "manifest":
        manifest.write_text('{"forged":true}', encoding="utf-8")
    elif change == "content":
        (manifest.parent / "sources/raw.bin").write_bytes(b"fake")
    elif change == "unexpected_file":
        record = json.loads(manifest.read_text(encoding="utf-8"))
        record["files"]["sources/fake.bin"] = "a" * 64
        manifest.write_text(json.dumps(record), encoding="utf-8")
    elif change == "fencing":
        result["fencing_token"] = 6
    with pytest.raises(op.NativeFrame01OperationDenied):
        op._verified_archive(ep, manifest, result["manifest_sha256"],
                             result["fencing_token"], result["evidence_sha256"])


def test_execute_denies_test_only_approval_without_production_consent(fake_archive, monkeypatch):
    ep, result, manifest = fake_archive
    calls = []
    monkeypatch.setattr(op.recovery, "reconcile_frame01_and_queue",
                        lambda *a, **kw: calls.append((a, kw)))
    with pytest.raises(op.NativeFrame01OperationDenied, match="PRODUCTION_APPROVAL"):
        op.execute(ep, fencing_token=5, evidence_sha256="a" * 64,
                   manifest=manifest, manifest_sha256=result["manifest_sha256"],
                   approval_ticket="FRAME01-20261012-APPROVAL",
                   production_approval="I_AUTHORIZE_ISOLATED_TEST_DB_WRITES")
    assert calls == []


def test_execute_calls_only_existing_attempt_cas_after_valid_seal(fake_archive, monkeypatch):
    ep, result, manifest = fake_archive
    called = []
    monkeypatch.setattr(op.recovery, "reconcile_frame01_and_queue",
                        lambda path, **args: (called.append((path, args)) or
                                            {"queue_reconciled": True}))
    response = op.execute(
        ep, fencing_token=5, evidence_sha256="a" * 64,
        manifest=manifest, manifest_sha256=result["manifest_sha256"],
        approval_ticket="FRAME01-20261012-APPROVED",
        production_approval=op.PRODUCTION_APPROVAL_VALUE,
    )
    assert called == [(ep.resolve(), {
        "expected_fencing_token": 5,
        "expected_evidence_sha256": "a" * 64,
    })]
    assert response["visual_review_pass"] is False
    assert response["new_generation_attempts"] == 0
    assert response["model_calls"] == 0




def test_capture_reads_five_exact_authority_rows_and_six_pixels_or_receipts(
        tmp_path, monkeypatch):
    ep = tmp_path / "episodes/00_独立篇/06_五十亩山地之后_全新重制"
    ep.mkdir(parents=True)
    monkeypatch.setattr(op, "ROOT", tmp_path)
    proof = {}
    for key in op.freeze.SOURCE_KEYS:
        file = tmp_path / "sources" / (key + ".bin")
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(key.encode("utf-8"))
        proof[key] = file.resolve()
    counts = {"opened": 0, "closed": 0, "queries": []}
    class FakeConnection:
        def query_one(self, sql, params):
            assert sql.startswith("SELECT * FROM ")
            assert "FOR UPDATE" not in sql
            counts["queries"].append((sql, params))
            return {"SQL": sql, "ARGS": list(params), "BIN": b"synthetic"}
        def close(self):
            counts["closed"] += 1
    monkeypatch.setattr(op.preflight, "inspect", lambda _: ready())
    monkeypatch.setattr(op.recovery, "verify_frame01_sources", lambda _: proof)
    monkeypatch.setattr(op.generation, "_connect",
                        lambda: (counts.__setitem__("opened", counts["opened"] + 1)
                                 or FakeConnection()))
    monkeypatch.setattr(op.generation, "frame_key", lambda *_: "synthetic-frame-01")
    monkeypatch.setattr(op.logical_asset_identity, "episode_id", lambda _: "test-logical-id")
    monkeypatch.setattr(op.episode_identity, "storage_episode_id", lambda _: "EPU_TEST_storage")
    monkeypatch.setattr(op.scheduler_core, "load_queue",
                        lambda _: {"items": [{"frame": 1, "status": "external_blocked"}]})
    state, files = op.capture(ep)
    assert state["authorized_to_mutate_production"] is False
    assert len(files) == 7
    assert "source" in files["state.json"].decode("utf-8")
    assert counts["opened"] == counts["closed"] == 2
    assert len(counts["queries"]) == 10
    assert "WHERE EPISODE_ID=%s AND FRAME_NO=1" in counts["queries"][3][0]
    decoded = json.loads(files["state.json"])
    assert len(decoded["authority_rows"]) == 5
    assert decoded["authority_rows"]["generation_attempt"]["BIN"] == {
        "binary_base64": "c3ludGhldGlj"
    }


def test_capture_refuses_authority_change_during_read_only_snapshot(tmp_path, monkeypatch):
    ep = tmp_path / "episodes/00_独立篇/06_五十亩山地之后_全新重制"
    ep.mkdir(parents=True)
    monkeypatch.setattr(op, "ROOT", tmp_path)
    proof = {}
    for key in op.freeze.SOURCE_KEYS:
        f = tmp_path / ("evidence-" + key)
        f.write_bytes(key.encode())
        proof[key] = f.resolve()
    responses = iter([ready(), {**ready(), "fencing_token": 6}])
    monkeypatch.setattr(op.preflight, "inspect", lambda _: next(responses))
    monkeypatch.setattr(op.recovery, "verify_frame01_sources", lambda _: proof)
    monkeypatch.setattr(op, "_authority", lambda _: {"state": 1})
    monkeypatch.setattr(op.scheduler_core, "load_queue",
                        lambda _: {"items": [{"frame": 1}]})
    with pytest.raises(op.NativeFrame01OperationDenied, match="AUTHORITY_MOVED"):
        op.capture(ep)



@pytest.fixture
def committed_resume(fake_archive, monkeypatch, tmp_path):
    """An interrupted SQL COMMIT + missing Queue save, with synthetic files."""
    import native_baseline_atomic_ledger as atomic
    import production_ledger_persistence as store
    ep, result, manifest = fake_archive
    def fake_old_preflight(_):
        raise op.preflight.NativeFrame01PreflightDenied(
            "NATIVE_PREFLIGHT_GENERATION_AUTHORITY_DRIFT"
        )
    monkeypatch.setattr(op, "capture", fake_old_preflight)
    files = {}
    for key in op.freeze.SOURCE_KEYS:
        source = tmp_path / "live_source" / (key + ".bin")
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes((manifest.parent / "sources" / (key + ".bin")).read_bytes())
        files[key] = source.resolve()
    candidate = files["candidate"]
    proof = {
        **files,
        "evidence_sha256": result["evidence_sha256"],
        "generation_key": "ga1-synthetic-single-attempt",
        "candidate": candidate,
    }
    state = {
        "attempts_consumed": 1,
        "active_attempt_index": None,
        "fencing_counter": 5,
    }
    generation_row = {
        "status": "SUCCEEDED",
        "generation_key": proof["generation_key"],
        "result_ref": str(candidate),
    }
    ledger_calls = []
    monkeypatch.setattr(op.recovery, "verify_frame01_sources",
                        lambda _ep, allow_generated=False: proof)
    monkeypatch.setattr(op.generation, "frame_key", lambda *_: "synthetic-frame-01")
    monkeypatch.setattr(op.generation, "load_asset_state", lambda *_: state)
    monkeypatch.setattr(op.generation, "load_attempt", lambda *_: generation_row)
    monkeypatch.setattr(store, "load_authority",
                        lambda *_: {"frames": {"01": {"status": "ORIGINAL_READY"}}})
    monkeypatch.setattr(atomic, "_check_existing",
                        lambda doc, source, *, completed: ledger_calls.append(completed))
    return ep, result, manifest, proof, state, generation_row, ledger_calls


def test_already_committed_original_attempt_resumes_missing_queue_only(
        committed_resume, monkeypatch):
    ep, result, manifest, _proof, _state, _row, ledger_calls = committed_resume
    invocations = []
    monkeypatch.setattr(op.recovery, "reconcile_frame01_and_queue",
                        lambda target, **args: (invocations.append((target, args)) or
                                                {"queue_reconciled": True}))
    output = op.execute(
        ep, fencing_token=5,
        evidence_sha256=result["evidence_sha256"],
        manifest=manifest,
        manifest_sha256=result["manifest_sha256"],
        approval_ticket="FRAME01-20261012-RESUME-APPROVED",
        production_approval=op.PRODUCTION_APPROVAL_VALUE,
    )
    assert output["visual_review_pass"] is False
    assert output["new_generation_attempts"] == 0
    assert ledger_calls == [True]
    assert invocations == [(ep.resolve(), {
        "expected_fencing_token": 5,
        "expected_evidence_sha256": result["evidence_sha256"],
    })]


@pytest.mark.parametrize("drift", [
    "source", "fencing", "spent_twice", "not_succeeded",
    "generation_key", "result_ref", "evidence_sha",
])
def test_committed_resume_rejects_provenance_or_attempt_drift(
        committed_resume, monkeypatch, drift):
    ep, result, manifest, proof, state, generation_row, ledger_calls = committed_resume
    invoked = []
    monkeypatch.setattr(op.recovery, "reconcile_frame01_and_queue",
                        lambda *a, **kw: invoked.append(1))
    if drift == "source":
        proof["raw"].write_bytes(b"after-cas-replaced")
    elif drift == "fencing":
        state["fencing_counter"] = 6
    elif drift == "spent_twice":
        state["attempts_consumed"] = 2
    elif drift == "not_succeeded":
        generation_row["status"] = "DISPATCH_COMMITTED"
    elif drift == "generation_key":
        generation_row["generation_key"] = "forged"
    elif drift == "result_ref":
        generation_row["result_ref"] = "forged.png"
    elif drift == "evidence_sha":
        proof["evidence_sha256"] = "0" * 64
    with pytest.raises(op.NativeFrame01OperationDenied):
        op.execute(
            ep, fencing_token=5,
            evidence_sha256=result["evidence_sha256"],
            manifest=manifest,
            manifest_sha256=result["manifest_sha256"],
            approval_ticket="FRAME01-20261012-RESUME-APPROVED",
            production_approval=op.PRODUCTION_APPROVAL_VALUE,
        )
    assert invoked == []
    assert ledger_calls == []

@pytest.fixture
def wrapper(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(
        cli.storyos_codex_managed, "canonical_episode",
        lambda name: Path("C:/synthetic-episode"),
    )
    monkeypatch.setattr(
        cli.storyos_codex_managed, "native_environment",
        lambda: {"STORYOS_MYSQL_PORT": "3307", "SYNTHETIC": "1"},
    )
    def fake_run(command, **kw):
        calls.append((command, kw))
        assert command[1] == "-c"
        assert kw["env"]["SYNTHETIC"] == "1"
        return SimpleNamespace(returncode=fake_run.returncode,
                               stdout=json.dumps(fake_run.result), stderr="SECRET")
    fake_run.returncode = 0
    fake_run.result = {
        "status": "PLAN_ONLY_PRODUCTION_WRITE_NOT_AUTHORIZED",
        "model_calls": 0, "sql_writes": 0,
        "authorized_to_mutate_production": False,
    }
    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    return fake_run, calls, capsys


def test_wrapper_plan_uses_canonical_runtime_and_never_authorizes(wrapper):
    fake, calls, capsys = wrapper
    assert cli.main(["plan", "episodes/synthetic"]) == 0
    response = json.loads(capsys.readouterr().out)
    assert response["status"] == "PLAN_ONLY_PRODUCTION_WRITE_NOT_AUTHORIZED"
    assert len(calls) == 1


def test_wrapper_denies_execute_before_any_child_process_without_new_approval(wrapper, monkeypatch):
    _fake, calls, capsys = wrapper
    monkeypatch.setenv("STORYOS_TEST_MYSQL_APPROVAL", "I_AUTHORIZE_ISOLATED_TEST_DB_WRITES")
    monkeypatch.delenv("STORYOS_NATIVE_FRAME01_PRODUCTION_APPROVAL", raising=False)
    assert cli.main(["execute", "episodes/synthetic",
                     "--ack-real-production",
                     "--fencing-token", "5",
                     "--evidence-sha256", "a" * 64,
                     "--backup-manifest", "never.json",
                     "--backup-sha256", "b" * 64,
                     "--approval-ticket", "FRAME01-20261012-APPROVED"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "BLOCKED"
    assert not calls


@pytest.mark.parametrize("forged", [
    "model_calls", "fake_status", "fake_auth", "fake_sql_write", "nonzero_exit",
])
def test_wrapper_rejects_child_claims_or_exec_error(wrapper, forged):
    fake, calls, capsys = wrapper
    if forged == "model_calls":
        fake.result["model_calls"] = 1
    elif forged == "fake_status":
        fake.result["status"] = "PUBLISH_READY"
    elif forged == "fake_auth":
        fake.result["authorized_to_mutate_production"] = True
    elif forged == "fake_sql_write":
        fake.result["sql_writes"] = 1
    elif forged == "nonzero_exit":
        fake.returncode = 2
    assert cli.main(["plan", "episodes/synthetic"]) == 2
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "BLOCKED"
    assert "SECRET" not in json.dumps(output)
    assert len(calls) == 1
