"""Fail-closed hermetic proof for a historical creative-story rc4 superseded by A15 PASS."""
from __future__ import annotations

from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import types

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path: sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location(
    "storyos_post_review_rc4_readonly", SCRIPTS / "storyos_post_review_rc4_readonly.py")
post = importlib.util.module_from_spec(spec)
spec.loader.exec_module(post)
spec2 = importlib.util.spec_from_file_location(
    "storyos_codex_managed", SCRIPTS / "storyos_codex_managed.py")
native = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(native)


def fixture(tmp_path, monkeypatch):
    ep = tmp_path / "episodes" / "00_serial" / "14_first"
    original = ep / "docs" / "source" / "immutable.txt"
    original.parent.mkdir(parents=True)
    original.write_bytes(b"immutable user text")
    (ep / "meta/runtime/driver-logs").mkdir(parents=True)
    logfile = ep / "meta/runtime/driver-logs/driver_old.log"
    rawlog = b"DRIVER TASK CARRIER pid=100 task=history\nDRIVER EXIT rc=4 \n"
    logfile.write_bytes(rawlog)
    trace = ep / "meta/runtime/trace-events.jsonl"
    trace.write_text(json.dumps({
        "event_type": "STEP_FAILED",
        "step": "CREATIVE_STORY",
        "failure_class": "4",
        "timestamp": "2026-10-20T20:17:41+08:00",
    })+"\n", encoding="utf-8")
    old = {
        "pid": 0,
        "carrier_task": "history",
        "started_at": "2026-10-20T19:59:03+08:00",
        "rc": "4 2026-10-20T20:21:00+08:00",
        "episode": str(ep.resolve()),
        "log": str(logfile.resolve()),
        "exited_at": "2026-10-20T20:21:00+08:00",
    }
    sha = hashlib.sha256(json.dumps(
        old, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode()).hexdigest()
    rem = ep / "meta/runtime" / f"corrected-story-rc4-remediation-{sha}.json"
    rem.write_text(json.dumps({
        "status": "SINGLE_USE_RESERVED", "ack": "EXPLICIT_REAL_PRODUCTION",
        "historical_driver_sha256": sha,
        "historical_log_sha256": hashlib.sha256(rawlog).hexdigest(),
        "historical_failure_step": "CREATIVE_STORY",
        "historical_failure_class": "4", "frame_count": 48, "canvas": "4:5",
        "no_gate_pass_asserted": True, "runtime_request_id": "request-1",
        "source_sha256": hashlib.sha256(original.read_bytes()).hexdigest(),
    }), encoding="utf-8")
    driver = {"driver_state": "EXITED", "exit_code": "4", "pid": 0,
              "liveness": "DEAD", "record": old, "log": str(logfile.resolve())}
    review = {"summary": {"passed": True}, "issue_codes": [],
              "critic_provenance": {"attempt": 15, "review_epoch": 14,
                 "direct_user_continuation_review": True,
                 "review_scope": post.APPROVED_SCOPE,
                 "reviewed_at": "2026-10-20T23:28:59+08:00"}}
    gates = {"reviews": {"story": "passed"}, "story": {"task_closed": True}}
    binding = {"canvas": "4:5", "frame_count": 48,
               "source_sha256": hashlib.sha256(original.read_bytes()).hexdigest(),
               "source_archive": original.relative_to(tmp_path).as_posix()}
    request = {"request_id": "request-1", "narrative_form": "SERIAL_EPISODE",
               "story_input": {"mode": "locked_story", "allow_structure_rewrite": False},
               "user_intent": {"full_auto_authorized": True}}
    state = {"driver": driver, "review": review, "gates": gates, "binding": binding}
    monkeypatch.setattr(post, "ROOT", tmp_path)
    def stub(name, **items):
        obj = types.ModuleType(name)
        for key, value in items.items(): setattr(obj, key, value)
        monkeypatch.setitem(sys.modules, name, obj)
        return obj
    stub("runtime_driver", status=lambda _ep: state["driver"])
    stub("story_review", load_review=lambda _ep: state["review"],
         review_required=lambda _ep: True, verify=lambda _ep: [],
         read_json=lambda path: state["binding"] if "user-source-binding" in str(path)
                  else state["gates"])
    stub("runtime_request", authority_for_episode=lambda _ep: request)
    stub("story_narrative_form", is_locked=lambda _r: True,
         from_request=lambda _r: "SERIAL_EPISODE")
    stub("storyos_driver_exit_remediation", canonical_sha=lambda r: hashlib.sha256(
        json.dumps(r, sort_keys=True, ensure_ascii=False,
                   separators=(",", ":")).encode()).hexdigest())
    stub("story_source_revision_a15_review", validate_epoch=lambda _ep, _p: True)
    return ep, state, rem, logfile, original, sha


def test_old_receipt_byte_digest_drift_is_not_reused_as_production_permit(tmp_path, monkeypatch):
    ep, state, ticket, _, _, _ = fixture(tmp_path, monkeypatch)
    prior = json.loads(ticket.read_text("utf-8"))
    prior["historical_log_sha256"] = "f"*64
    ticket.write_text(json.dumps(prior), encoding="utf-8")
    report = post.inspect(ep)
    assert report["status"] == post.STATUS
    assert report["historical_receipt_log_byte_sha_same"] is False
    assert report["production_authorization"] is False


def test_readonly_proof_recovers_only_exact_superseded_rc4(tmp_path, monkeypatch):
    ep, state, *_ = fixture(tmp_path, monkeypatch)
    result = post.inspect(ep)
    assert result["status"] == post.STATUS, result
    assert result["story_gate_verified"] is True
    assert result["production_authorization"] is False
    assert result["image_entitlement_verified"] is False
    assert result["model_calls"] == result["sql_writes"] == 0


@pytest.mark.parametrize("fault", [
    "old_review", "failed_review", "gate_pending", "wrong_driver_rc",
    "driver_alive", "review_before_exit", "source_changed",
    "log_changed", "historical_ticket_missing",
])
def test_supersession_cannot_override_unverified_authority(tmp_path, monkeypatch, fault):
    ep, state, ticket, logfile, original, _ = fixture(tmp_path, monkeypatch)
    if fault == "old_review": state["review"]["critic_provenance"]["attempt"] = 14
    if fault == "failed_review": state["review"]["summary"]["passed"] = False
    if fault == "gate_pending": state["gates"]["reviews"]["story"] = "pending"
    if fault == "wrong_driver_rc": state["driver"]["exit_code"] = "22"
    if fault == "driver_alive": state["driver"]["liveness"] = "ALIVE"
    if fault == "review_before_exit":
        state["review"]["critic_provenance"]["reviewed_at"] = "2026-10-20T19:00:00+08:00"
    if fault == "source_changed": original.write_bytes(b"unauthorized new text")
    if fault == "log_changed": logfile.write_bytes(b"DRIVER EXIT rc=4 \nDRIVER CRASH unrelated")
    if fault == "historical_ticket_missing": ticket.unlink()
    result = post.inspect(ep)
    assert result["status"] != post.STATUS
    assert result["production_authorization"] is False


def test_preflight_surfaces_dag_ready_without_granting_images(monkeypatch):
    monkeypatch.setattr(native, "ROOT", ROOT)
    calls = []
    old_driver = {"driver_state": "EXITED", "exit_code": "4", "pid": 0,
        "liveness": "DEAD", "record": {"pid": 0, "rc": "4"}}
    import storyos_driver_exit_remediation as exit_proof
    token = exit_proof.canonical_sha(old_driver["record"])

    def fake(_env, script, args, **_kwargs):
        calls.append(script)
        if script.endswith("runtime_router.py"):
            return 0, {"effective_production_mode": "CODEX_MANAGED",
                "effective_runtime": "CODEX", "image_execution_runtime": "CODEX",
                "local_codex_spawn_allowed": True, "local_codex_image_spawn_allowed": True,
                "text_review_runtime": "CODEX", "vision_review_runtime": "CODEX",
                "governance_review_runtime": "CODEX"}
        if script.endswith("codex_user_runner.py"):
            return 0, {"status": "ok", "codex_available": True, "codex_auth_present": True}
        if script.endswith("storyos_native_model_readiness.py"):
            return 0, {"status": "CLIENT_VERSION_COMPATIBLE"}
        if script.endswith("storyos_revision_schema_readonly.py"):
            return 0, {"status": "READY_FOR_FURTHER_ADMISSION"}
        if script.endswith("storyos_episode_stage_readonly.py"):
            return 0, {"status": "STAGE_ELIGIBLE", "stage": "IDEA_LOCKED", "source": "mysql"}
        if script.endswith("storyos_creative_recovery_readonly.py"):
            return 0, {"status": "CONTRACT_ALREADY_LOCKED_VERIFY_STORY_GATES"}
        if script.endswith("storyos_attempt_readonly_preflight.py"):
            return 0, {"status": "ATTEMPT_HISTORY_READ_ONLY",
                       "outcome_unknown_assets": [], "active_attempt_assets": []}
        if script.endswith("runtime_driver.py"): return 0, old_driver
        if script.endswith("storyos_post_review_rc4_readonly.py"):
            return 0, {"status": post.STATUS, "story_gate_verified": True,
                       "driver_record_sha256": token}
        raise AssertionError(script)

    monkeypatch.setattr(native, "_probe", fake)
    result = native.preflight({"STORYOS_MYSQL_HOST": "127.0.0.1",
                              "STORYOS_MYSQL_PORT": "3307"},
                              episode=ROOT / "episodes")
    assert result["status"] == "READY_TO_START"
    assert not result["production_admission"]["image_ready"]
    assert not result["production_authorization"]
    assert result["driver_recovery"]["driver_record_sha256"] == token
    assert "scripts/storyos_post_review_rc4_readonly.py" in calls


def test_preflight_keeps_rc4_blocked_when_proof_is_not_valid(monkeypatch):
    original = native._probe
    def fail(_env, script, args, **_kw):
        if script.endswith("storyos_post_review_rc4_readonly.py"):
            return 2, {"status": "A15_EPOCH_SOURCE_SHA_DRIFT"}
        return original(_env, script, args)
    # Existing nonzero Driver gate still protects all unrelated cases.
    assert not native.resident_restart_permitted({
        "driver_state": "EXITED", "exit_code": "4", "pid": 0, "liveness": "DEAD"})
