"""Host binds PREIMAGE input SHA; the model owns semantic payload only."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

SYSTEM = Path(__file__).resolve().parents[2] / "episodes/_system"
if str(SYSTEM) not in sys.path:
    sys.path.insert(0, str(SYSTEM))

import preimage_task_contract as task_contract


def make_case(tmp_path, *, wrong_source=True, changed_snapshot=False):
    ep = tmp_path / "00_独立篇" / "06_真实故事"
    logdir = ep / "meta/scoped-workers"
    canddir = ep / "meta/runtime/preimage-candidates"
    logdir.mkdir(parents=True)
    canddir.mkdir(parents=True)
    task = {
        "task_type": "ENVIRONMENT_PREPARE",
        "task_id": "preimage-environment_prepare-real",
        "snapshot_id": "snapshot-A",
        "authority_scope": ["visual.environment_contract", "visual.frame_directives"],
        "input_contract": {"source_authority_sha256": {"owned_scopes": {"environment": "a" * 64}}},
    }
    candidate = {
        "schema_version": 1,
        "task_type": task["task_type"],
        "task_id": task["task_id"],
        "snapshot_id": "snapshot-B" if changed_snapshot else task["snapshot_id"],
        "source_authority_sha256": (
            {"owned_scopes": {"environment": "a" * 63}}
            if wrong_source else task["input_contract"]["source_authority_sha256"]
        ),
        "authority_scope": list(task["authority_scope"]),
        "status": "COMPLETED",
        "payload": {
            "visual.environment_contract": {"baseline": {"time_of_day": "afternoon"}},
            "visual.frame_directives": {"16": {"frame_mode": "normal_record", "impact_level": 1}},
        },
        "evidence": [],
    }
    p = canddir / "environment.json"
    p.write_text(json.dumps(candidate), encoding="utf-8")
    log = logdir / "preimage_environment.jsonl"
    log.write_text(
        '{"type":"thread.started"}\n{"type":"turn.completed","usage":{"input_tokens":5,"output_tokens":6}}\n',
        encoding="utf-8",
    )
    return ep, task, log, p, candidate


def test_native_host_seal_corrects_only_metadata_after_real_turn(tmp_path, monkeypatch):
    ep, task, log, p, original = make_case(tmp_path)
    raw = p.read_bytes()

    def official_fake(candidate, _task):
        if candidate.get("source_authority_sha256") != task["input_contract"]["source_authority_sha256"]:
            return ["candidate source authority SHA mismatch"]
        if candidate["payload"] != original["payload"]:
            return ["payload must remain unmodified"]
        return []

    monkeypatch.setattr(task_contract, "verify_candidate", official_fake)
    before = hashlib.sha256(raw).hexdigest()
    outcome = task_contract.seal_scoped_native_candidate(ep, task, log)
    assert outcome["status"] == "PASS"
    sealed = json.loads(p.read_text(encoding="utf-8"))
    assert sealed["source_authority_sha256"] == task["input_contract"]["source_authority_sha256"]
    assert sealed["payload"] == original["payload"]
    assert sealed["evidence"][0]["model_turn_completed"] is True
    assert sealed["evidence"][0]["original_candidate_sha256"] == before
    assert sealed["evidence"][0]["authoritative_payload_unchanged"] is True
    original_path = ep / sealed["evidence"][0]["original_candidate_path"]
    assert original_path.read_bytes() == raw
    assert "model_execution" not in sealed  # no fabricated telemetry


@pytest.mark.parametrize("invalid", ["old_turn_only", "drifted_snapshot", "missing_turn"])
def test_native_host_seal_rejects_stale_or_missing_proof(tmp_path, monkeypatch, invalid):
    ep, task, log, p, _original = make_case(
        tmp_path, changed_snapshot=(invalid == "drifted_snapshot")
    )
    raw = p.read_bytes()
    monkeypatch.setattr(task_contract, "verify_candidate", lambda c, t: [])
    if invalid == "old_turn_only":
        offset = log.stat().st_size
    elif invalid == "missing_turn":
        log.write_text('{"type":"thread.started"}\n', encoding="utf-8")
        offset = 0
    else:
        offset = 0
    result = task_contract.seal_scoped_native_candidate(
        ep, task, log, log_start_offset=offset
    )
    assert result["status"] == "REFUSED"
    assert p.read_bytes() == raw
    assert not (ep / "meta/runtime/native-host-envelope-archive").exists()


def test_native_host_seal_refuses_semantic_payload_failure(tmp_path, monkeypatch):
    ep, task, log, p, _ = make_case(tmp_path)
    before = p.read_bytes()
    monkeypatch.setattr(
        task_contract, "verify_candidate",
        lambda c, t: ["frame_directives.16 normal_record impact must be <=1"],
    )
    result = task_contract.seal_scoped_native_candidate(ep, task, log)
    assert result["status"] == "REFUSED"
    assert p.read_bytes() == before


def test_native_host_seal_rejects_log_outside_episode(tmp_path, monkeypatch):
    ep, task, log, p, _ = make_case(tmp_path)
    outsider = tmp_path / "elsewhere.jsonl"
    outsider.write_bytes(log.read_bytes())
    monkeypatch.setattr(task_contract, "verify_candidate", lambda c, t: [])
    assert task_contract.seal_scoped_native_candidate(ep, task, outsider)["status"] == "REFUSED"


def test_scoped_environment_prompt_constrains_normal_records():
    import scoped_codex_worker
    directive = scoped_codex_worker.STEP_DIRECTIVES["PREIMAGE_ENVIRONMENT"]
    assert "frame_mode=normal_record" in directive
    assert "impact_level 0 or 1" in directive
    assert "frame 16" in directive
