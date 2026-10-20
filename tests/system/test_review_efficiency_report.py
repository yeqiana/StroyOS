from __future__ import annotations
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SYSTEM = ROOT / "episodes" / "_system"
if str(SYSTEM) not in sys.path:
    sys.path.insert(0, str(SYSTEM))
import review_efficiency_report as report


def ts(seconds):
    return (dt.datetime(2026, 10, 20, tzinfo=dt.timezone.utc) + dt.timedelta(seconds=seconds)).isoformat()


def test_reuse_metrics_do_not_double_count_overlapping_wall_time():
    a = {"started_at": ts(0), "ended_at": ts(10), "status": "PASS", "metadata": {"target_frame_count": 5, "shard_count": 1}}
    b = {"started_at": ts(5), "ended_at": ts(15), "status": "PASS", "metadata": {"target_frame_count": 2, "shard_count": 1}}
    data = {"named_spans": {"REVIEW_FULL_1": {"runs": [a]}, "REVIEW_PATCH_2": {"runs": [b]}}}
    result = report.build_report({"action": "PATCH", "dirty_frames": ["03", "07"], "reused_frames": ["01", "02", "04"]}, data)
    assert result["reuse_ratio"] == 0.6
    assert result["review_span_wall_seconds"] == 15.0
    assert result["full_review_spans"] == 1
    assert result["patch_review_spans"] == 1
    assert result["actual_model_review_calls"] is None
    assert result["not_stage_gate"] is True


def test_missing_or_incomplete_telemetry_is_not_reported_as_zero_model_calls():
    result = report.build_report({}, {})
    assert result["status"] == "UNKNOWN"
    assert result["full_review_spans"] is None
    assert result["review_span_wall_seconds"] is None
    interrupted = report.build_report({"action": "PATCH"}, {
        "named_spans": {"REVIEW_PATCH_1": {"runs": [{"started_at": ts(0), "ended_at": None, "status": "RUNNING", "metadata": {}}]}}
    })
    assert interrupted["status"] == "INCOMPLETE"
    assert interrupted["review_span_wall_seconds"] is None
