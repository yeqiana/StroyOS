"""R12: never mistake saved Task / Frame / Generation Attempt for current work."""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

from platform.operations.local_production_progress_readonly import summarize_production_progress as summarise

NOW = datetime(2026, 10, 13, 6, 0, tzinfo=timezone.utc)
TS = (NOW - timedelta(hours=12)).isoformat()
MYSQL = {
    "available": True, "database_identity_verified": True, "read_only_grants_verified": True,
    "may_be_truncated": True,
    "task_records": [{"task_type": "RUNTIME_CHECKPOINT_STEP", "status": "HOST_WAIT",
                      "frame": None, "attempt_no": 2, "updated_at": TS}],
    "production_attempt_records": [
        {"frame": 7, "status": "technical_failure", "attempt_no": 3, "kind": "repair",
         "error_code": "TECH_FAILED", "elapsed_ms": 16000, "recorded_at": TS},
        {"frame": 6, "status": "success", "attempt_no": 2, "kind": "original",
         "elapsed_ms": 12000, "recorded_at": (NOW-timedelta(days=1)).isoformat()},
        {"frame": 7, "status": "success", "attempt_no": 1, "kind": "original",
         "elapsed_ms": 9000, "recorded_at": (NOW-timedelta(days=2)).isoformat()},
    ],
    "generation_attempt_records": [
        {"frame": 7, "status": "OUTCOME_UNKNOWN", "attempt_index": 2}
    ],
}
HELD = {"status": "FRESH_PRODUCER_LOCK_CLAIM", "producer_process_verified": True}


def test_recorded_frame_is_not_current_work_even_if_driver_heartbeat_fresh():
    result = summarise(MYSQL, HELD, now=NOW)
    assert result["available"]
    assert result["writer_producer_claim_fresh"] is True
    assert result["verified_current_frame"] is None
    assert result["verified_current_task"] is None
    assert result["provider_call_verified"] is False
    assert result["stalled_verified"] is False
    assert result["execution_in_progress_verified"] is False
    assert result["recent_task"]["recorded_status"] == "HOST_WAIT"
    assert result["recent_task"]["frame"] is None
    assert result["recent_task"]["age_seconds"] == 43200
    assert result["recent_frame"]["frame"] == 7
    assert result["recent_frame"]["last_attempt_no"] == 3
    assert result["recent_frame"]["last_recorded_status"] == "technical_failure"
    assert result["recent_frame"]["last_recorded_duration_ms"] == 16000
    assert result["recent_frame"]["age_seconds"] == 43200
    assert result["unresolved_generation_count"] == 1
    assert [row["frame"] for row in result["frame_attempts"]] == [6, 7]
    assert result["frame_attempts"][1]["last_attempt_no"] == 3


def test_outcome_unknown_never_authorizes_retry_or_inflight():
    db = copy.deepcopy(MYSQL)
    db["generation_attempt_records"] = [{"status": "OUTCOME_UNKNOWN"}]
    state = summarise(db, None, now=NOW)
    assert state["unresolved_generation_count"] == 1
    assert state["provider_call_verified"] is False
    assert state["verified_current_frame"] is None


def test_unavailable_or_unverified_db_is_fail_closed_and_hides_rows():
    for malformed in (None, {}, {"available": False}, {
        **MYSQL, "database_identity_verified": False}, {
        **MYSQL, "read_only_grants_verified": False}, {
        **MYSQL, "task_records": "unsafe"
    }):
        state = summarise(malformed, HELD, now=NOW)
        assert state["available"] is False
        assert state["recent_task"] is None
        assert state["recent_frame"] is None
        assert state["frame_attempts"] == []
        assert state["writer_producer_claim_fresh"] is False


def test_unsafe_frames_and_invalid_durations_rejected():
    db = copy.deepcopy(MYSQL)
    db["production_attempt_records"] = [
        {"frame": "20", "status": "success", "recorded_at": TS, "elapsed_ms": 100},
        {"frame": 21, "status": "success", "recorded_at": TS, "elapsed_ms": 100},
        {"frame": True, "status": "success", "recorded_at": TS, "elapsed_ms": 100},
        {"frame": 1, "status": "success", "recorded_at": TS, "elapsed_ms": -10},
    ]
    state = summarise(db, None, now=NOW)
    assert [x["frame"] for x in state["frame_attempts"]] == [1]
    assert state["recent_frame"]["frame"] == 1
    assert state["frame_attempts"][0]["last_recorded_duration_ms"] is None


def test_wall_age_not_execution_duration_and_naive_or_future_time_unknown():
    db = copy.deepcopy(MYSQL)
    db["task_records"][0]["updated_at"] = "2026-10-13T06:00:00"
    db["production_attempt_records"][0]["recorded_at"] = (NOW+timedelta(hours=10)).isoformat()
    state = summarise(db, None, now=NOW)
    assert state["recent_task"]["age_seconds"] is None
    assert state["recent_task"]["recorded_updated_at"] is None
    assert state["recent_frame"]["age_seconds"] is None
    assert state["recent_frame"]["recorded_at"] is None
    assert state["recent_frame"]["last_recorded_duration_ms"] == 16000
    assert state["execution_in_progress_verified"] is False


def test_60_rows_sampling_bound_and_truncation_warning():
    db = copy.deepcopy(MYSQL)
    db["production_attempt_records"] = [
        {"frame": 1, "status": "success", "recorded_at": TS, "elapsed_ms": 1}
        for _ in range(80)
    ]
    db["generation_attempt_records"] = [{"status": "OUTCOME_UNKNOWN"}] * 80
    state = summarise(db, HELD, now=NOW)
    assert len(state["frame_attempts"]) == 1
    assert state["unresolved_generation_count"] == 60
    assert state["may_be_truncated"] is True


def test_task_current_legacy_status_and_stale_writer_do_not_claim_running():
    db = copy.deepcopy(MYSQL)
    db["task_records"][0]["status"] = "CURRENT"
    state = summarise(db, {"status": "UNKNOWN", "producer_process_verified": False}, now=NOW)
    assert state["recent_task"]["recorded_status"] == "CURRENT"
    assert state["verified_current_task"] is None
    assert not state["writer_producer_claim_fresh"]
    assert state["stalled_verified"] is False
