"""One-shot evidence-bound remediation of a nonzero resident Driver exit."""
import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import storyos_driver_exit_remediation as remedy


@pytest.fixture(autouse=True)
def _restore_trusted_fix_pin_after_test():
    original = remedy.APPROVED_FIXED_BLOB
    yield
    remedy.APPROVED_FIXED_BLOB = original

def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def evidence(tmp_path):
    ep = tmp_path / "episodes" / "reviewed"
    logs = ep / "meta" / "runtime" / "driver-logs"
    logs.mkdir(parents=True)
    log = logs / "driver_20261018_205227.log"
    log.write_text(
        "DRIVER TASK CARRIER pid=32924\n"
        "DRIVER CRASH RuntimeError('final semantic source bindings changed before commit')\n",
        encoding="utf-8",
    )
    source = tmp_path / "frame_semantic_review.py"
    source.write_text(
        'if review_scope == "FULL_FRAME_SET" and review_item is None:\n'
        '    provenance["review_source_bindings"] = review_source_bindings(ep, current)\n',
        encoding="utf-8",
    )
    driver = {
        "driver_state": "EXITED", "pid": 0, "liveness": "DEAD",
        "exit_code": "900", "log": str(log),
        "record": {"pid": 0, "rc": "900 2026-10-18T20:53:53+08:00",
                   "log": str(log), "episode": str(ep), "started_at": "2026-10-18T20:52:27+08:00"},
    }
    remedy.APPROVED_FIXED_BLOB = remedy.git_blob_sha(source.read_bytes())
    expected = {
        "driver_sha256": remedy.canonical_sha(driver["record"]),
        "log_sha256": _sha(log.read_bytes()),
        "fix_sha256": _sha(source.read_bytes()),
    }
    return ep, source, driver, expected


def test_verified_nonzero_exit_requires_three_exact_hashes(tmp_path):
    ep, source, driver, expected = evidence(tmp_path)
    proof = remedy.verify_exit(ep, driver, source=source, expected=expected)
    assert proof["exit_code"] == "900"
    assert proof["driver_sha256"] == expected["driver_sha256"]
    assert proof["log_sha256"] == expected["log_sha256"]
    assert proof["fix_sha256"] == expected["fix_sha256"]


@pytest.mark.parametrize("bad", ["driver_sha256", "log_sha256", "fix_sha256"])
def test_edited_or_unapproved_evidence_rejected_before_reservation(tmp_path, bad):
    ep, source, driver, expected = evidence(tmp_path)
    expected[bad] = "0" * 64
    with pytest.raises(remedy.RemediationDenied):
        remedy.verify_exit(ep, driver, source=source, expected=expected)
    assert not list((ep/"meta/runtime").glob("driver-remediation-*.json"))


@pytest.mark.parametrize("change", [
    {"pid": 12345}, {"liveness": "ALIVE"}, {"driver_state": "RUNNING"},
    {"exit_code": "0"}, {"exit_code": "20"},
])
def test_occupied_or_non_900_exit_never_permitted(tmp_path, change):
    ep, source, driver, expected = evidence(tmp_path)
    driver.update(change)
    with pytest.raises(remedy.RemediationDenied):
        remedy.verify_exit(ep, driver, source=source, expected=expected)


def test_wrong_crash_cause_and_source_marker_fail_closed(tmp_path):
    ep, source, driver, expected = evidence(tmp_path)
    log = Path(driver["log"])
    log.write_text("DRIVER CRASH RuntimeError('different unrelated failure')", encoding="utf-8")
    expected["log_sha256"] = _sha(log.read_bytes())
    with pytest.raises(remedy.RemediationDenied):
        remedy.verify_exit(ep, driver, source=source, expected=expected)
    log.write_text("DRIVER CRASH RuntimeError('final semantic source bindings changed before commit')",encoding="utf-8")
    expected["log_sha256"] = _sha(log.read_bytes())
    source.write_text("bypass source verification",encoding="utf-8")
    expected["fix_sha256"] = _sha(source.read_bytes())
    with pytest.raises(remedy.RemediationDenied):
        remedy.verify_exit(ep, driver, source=source, expected=expected)


def test_outside_episode_log_rejected(tmp_path):
    ep, source, driver, expected = evidence(tmp_path)
    other = tmp_path / "other.log"
    other.write_bytes(Path(driver["log"]).read_bytes())
    driver["log"] = str(other)
    driver["record"]["log"] = str(other)
    expected["driver_sha256"] = remedy.canonical_sha(driver["record"])
    with pytest.raises(remedy.RemediationDenied):
        remedy.verify_exit(ep, driver, source=source, expected=expected)


def test_one_shot_reservation_keeps_original_driver_exit(tmp_path):
    ep, source, driver, expected = evidence(tmp_path)
    before = json.dumps(driver, sort_keys=True)
    proof = remedy.verify_exit(ep, driver, source=source, expected=expected)
    ticket = remedy.reserve_once(ep, proof)
    assert ticket.is_file()
    row = json.loads(ticket.read_text(encoding="utf-8"))
    assert row["status"] == "REMEDIATION_DISPATCH_RESERVED"
    assert row["exit_code"] == "900"
    assert json.dumps(driver, sort_keys=True) == before
    with pytest.raises(remedy.RemediationDenied):
        remedy.reserve_once(ep, proof)


def test_preflight_may_only_contain_exact_prior_exit_blockers():
    assert remedy.only_historical_exit_blockers([
        "EPISODE_DRIVER_OWNER_NOT_IDLE_OR_UNVERIFIED",
        "EPISODE_DRIVER_EXIT_REQUIRES_REMEDIATION"])
    for extra in ["GENERATION_ATTEMPT_AUTHORITY_RECONCILIATION_REQUIRED",
                  "NATIVE_CODEX_AUTH_OR_USER_RUNNER_UNAVAILABLE"]:
        assert not remedy.only_historical_exit_blockers([
            "EPISODE_DRIVER_OWNER_NOT_IDLE_OR_UNVERIFIED",
            "EPISODE_DRIVER_EXIT_REQUIRES_REMEDIATION", extra])
    assert not remedy.only_historical_exit_blockers([])

def test_remediated_entrypoint_one_shot_dispatch_and_replay_fenced(tmp_path, monkeypatch):
    from unittest import mock
    import storyos_codex_managed as managed

    ep, source, driver, expected = evidence(tmp_path)
    fixed = tmp_path / "episodes/_system/frame_semantic_review.py"
    fixed.parent.mkdir(parents=True)
    fixed.write_bytes(source.read_bytes())
    state = {
        "blockers": sorted(remedy.HISTORICAL_EXIT_BLOCKERS),
        "episode_stage": {"status": "STAGE_ELIGIBLE", "source": "mysql"},
        "mysql": {"schema_status": "READY_FOR_FURTHER_ADMISSION"},
        "attempt": {"status": "ATTEMPT_HISTORY_READ_ONLY",
                    "active_attempt_assets": [], "outcome_unknown_assets": []},
        "codex": {"bridge_ok": True, "mode_ok": True, "model_client_version_ok": True},
        "driver_evidence": {k: driver[k] for k in (
            "driver_state", "pid", "liveness", "exit_code")},
    }
    monkeypatch.setattr(managed, "ROOT", tmp_path)
    monkeypatch.setattr(managed, "_probe", lambda *_a, **_k: (0, driver))
    with mock.patch.object(managed.subprocess, "call", return_value=0) as launched:
        assert managed.dispatch_remediated_start({}, ep, state, expected) == 0
        assert launched.call_count == 1
        with pytest.raises(remedy.RemediationDenied, match="ALREADY_REMEDIATION_RESERVED"):
            managed.dispatch_remediated_start({}, ep, state, expected)
        assert launched.call_count == 1


def test_remediation_never_overrides_mysql_attempt_or_model_blockers(tmp_path, monkeypatch):
    from unittest import mock
    import storyos_codex_managed as managed
    ep, source, driver, expected = evidence(tmp_path)
    monkeypatch.setattr(managed, "ROOT", tmp_path)
    with mock.patch.object(managed, "_probe") as probe, \
         mock.patch.object(managed.subprocess, "call") as launched:
        for blocked in (
            ["EPISODE_DRIVER_OWNER_NOT_IDLE_OR_UNVERIFIED",
             "EPISODE_DRIVER_EXIT_REQUIRES_REMEDIATION",
             "GENERATION_ATTEMPT_AUTHORITY_RECONCILIATION_REQUIRED"],
            ["EPISODE_DRIVER_OWNER_NOT_IDLE_OR_UNVERIFIED",
             "EPISODE_DRIVER_EXIT_REQUIRES_REMEDIATION",
             "NATIVE_CODEX_AUTH_OR_USER_RUNNER_UNAVAILABLE"],
        ):
            state = {"blockers": blocked}
            with pytest.raises(remedy.RemediationDenied):
                managed.dispatch_remediated_start({}, ep, state, expected)
        assert probe.call_count == 0
        assert launched.call_count == 0
        assert not list((ep / "meta/runtime").glob("driver-remediation-*.json"))


def test_explicit_ack_required_for_remediation(tmp_path, monkeypatch, capsys):
    import storyos_codex_managed as managed
    ep, _, _, expected = evidence(tmp_path)
    monkeypatch.setattr(managed, "canonical_episode", lambda *_: ep)
    monkeypatch.setattr(managed, "native_environment", lambda: {})
    monkeypatch.setattr(managed, "preflight", lambda *a, **k: {"status": "BLOCKED"})
    argv = [
        "remediate-start", str(ep),
        "--expected-driver-record-sha256", expected["driver_sha256"],
        "--expected-crash-log-sha256", expected["log_sha256"],
        "--expected-fixed-source-sha256", expected["fix_sha256"],
    ]
    assert managed.main(argv) == 2
    assert "NATIVE_CODEX_REAL_PRODUCTION_ACK_REQUIRED" in capsys.readouterr().err
    assert not list((ep / "meta/runtime").glob("driver-remediation-*.json"))

def test_repair_wave_crash_authorizes_only_exact_ci_pinned_fixed_source(tmp_path, monkeypatch):
    ep, _, driver, expected = evidence(tmp_path)
    log = Path(driver["log"])
    log.write_text(
        """DRIVER CRASH TypeError("materialize_wave() got an unexpected keyword argument 'evidence'")""",
        encoding="utf-8",
    )
    expected["log_sha256"] = _sha(log.read_bytes())
    source = tmp_path / "vision_review_executor.py"
    source.write_text(
        "wave = repair_aggregator.materialize_wave(ep,attempt=attempt,findings=evidence)\n",
        encoding="utf-8",
    )
    expected["fix_sha256"] = _sha(source.read_bytes())
    monkeypatch.setattr(remedy, "APPROVED_REPAIR_WAVE_BLOB", remedy.git_blob_sha(source.read_bytes()))
    proof = remedy.verify_exit(ep, driver, source=source, expected=expected,
                               kind="repair_wave_signature")
    assert proof["remediation_kind"] == "repair_wave_signature"
    assert proof["approved_git_blob"] == remedy.APPROVED_REPAIR_WAVE_BLOB
    assert remedy.reserve_once(ep, proof).is_file()
    with pytest.raises(remedy.RemediationDenied):
        remedy.reserve_once(ep, proof)
    with pytest.raises(remedy.RemediationDenied):
        remedy.verify_exit(ep, driver, source=source, expected=expected,
                           kind="source_binding")


def test_second_crash_never_authorizes_unknown_fix_or_wrong_source(tmp_path, monkeypatch):
    ep, _, driver, expected = evidence(tmp_path)
    source = tmp_path / "vision_review_executor.py"
    source.write_text("legacy_wrong_keyword=evidence", encoding="utf-8")
    log = Path(driver["log"])
    log.write_text(
        """DRIVER CRASH TypeError("materialize_wave() got an unexpected keyword argument 'evidence'")""",
        encoding="utf-8",
    )
    expected["log_sha256"] = _sha(log.read_bytes())
    expected["fix_sha256"] = _sha(source.read_bytes())
    monkeypatch.setattr(remedy, "APPROVED_REPAIR_WAVE_BLOB", remedy.git_blob_sha(source.read_bytes()))
    with pytest.raises(remedy.RemediationDenied):
        remedy.verify_exit(ep, driver, source=source, expected=expected,
                           kind="repair_wave_signature")
    with pytest.raises(remedy.RemediationDenied):
        remedy.verify_exit(ep, driver, source=source, expected=expected,
                           kind="unreviewed_new_failure")

def test_repair_wave_remediation_entrypoint_routes_verified_new_source(tmp_path, monkeypatch):
    from unittest import mock
    import storyos_codex_managed as managed
    ep, _, driver, expected = evidence(tmp_path)
    source = tmp_path / "episodes/_system/vision_review_executor.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "wave = repair_aggregator.materialize_wave(ep,attempt=attempt,findings=evidence)\n",
        encoding="utf-8",
    )
    log = Path(driver["log"])
    log.write_text(
        """DRIVER CRASH TypeError("materialize_wave() got an unexpected keyword argument 'evidence'")""",
        encoding="utf-8",
    )
    expected["log_sha256"] = _sha(log.read_bytes())
    expected["fix_sha256"] = _sha(source.read_bytes())
    monkeypatch.setattr(remedy, "APPROVED_REPAIR_WAVE_BLOB",
                        remedy.git_blob_sha(source.read_bytes()))
    monkeypatch.setattr(managed, "ROOT", tmp_path)
    monkeypatch.setattr(managed, "_probe", lambda *_a, **_k: (0, driver))
    state = {
        "blockers": sorted(remedy.HISTORICAL_EXIT_BLOCKERS),
        "episode_stage": {"status": "STAGE_ELIGIBLE"},
        "mysql": {"schema_status": "READY_FOR_FURTHER_ADMISSION"},
        "attempt": {"status": "ATTEMPT_HISTORY_READ_ONLY",
                    "active_attempt_assets": [], "outcome_unknown_assets": []},
        "codex": {"bridge_ok": True, "mode_ok": True, "model_client_version_ok": True},
        "driver_evidence": {k: driver[k] for k in
                            ("driver_state", "pid", "liveness", "exit_code")},
    }
    with mock.patch.object(managed.subprocess, "call", return_value=0) as launched:
        assert managed.dispatch_remediated_start(
            {}, ep, state, expected, kind="repair_wave_signature") == 0
        assert launched.call_count == 1
        with pytest.raises(remedy.RemediationDenied):
            managed.dispatch_remediated_start(
                {}, ep, state, expected, kind="repair_wave_signature")
        assert launched.call_count == 1


def test_wrong_remediation_kind_does_not_reserve(tmp_path):
    ep, source, driver, expected = evidence(tmp_path)
    with pytest.raises(remedy.RemediationDenied, match="UNKNOWN_REMEDIATION_KIND"):
        remedy.verify_exit(ep, driver, source=source, expected=expected,
                           kind="unreviewed_new_failure")
    assert not list((ep / "meta/runtime").glob("driver-remediation-*.json"))
