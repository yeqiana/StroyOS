"""Trace activity is historical evidence, not current Driver/Worker authority."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "platform/operations/local_runtime_trace_readonly.py"
spec = importlib.util.spec_from_file_location("storyos_local_trace_under_test", MODULE)
assert spec is not None and spec.loader is not None
trace_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trace_module)
latest_node = trace_module.latest_node


def _trace(ep: Path, rows: list[dict]) -> None:
    path = ep / "meta/runtime/trace-events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_old_creative_story_step_failed_cannot_claim_current_block(tmp_path: Path):
    _trace(tmp_path, [{
        "event_type": "STEP_FAILED",
        "step": "CREATIVE_STORY",
        "failure_class": "4",
        "timestamp": "2026-10-20T20:21:00+08:00",
    }])
    row = latest_node(tmp_path)
    assert row["execution_status"] == "FAILURE_RECORDED"
    assert row["historical_failure_reason"] == "STEP_FAILED"
    assert row["blocking_reason"] is None
    assert row["current_action"] == "CREATIVE_STORY"


def test_later_step_result_overrides_old_failed_trace(tmp_path: Path):
    _trace(tmp_path, [
        {"event_type": "STEP_FAILED", "step": "CREATIVE_STORY",
         "failure_class": "4", "timestamp": "2026-10-20T20:21:00+08:00"},
        {"event_type": "STEP_FINISHED", "step": "CREATIVE_STORY",
         "timestamp": "2026-10-21T00:40:00+08:00"},
    ])
    row = latest_node(tmp_path)
    assert row["execution_status"] == "RESULT_RECORDED"
    assert row["blocking_reason"] is None
    assert row["historical_failure_reason"] is None


def test_unreadable_trace_never_claims_current_block(tmp_path: Path):
    row = latest_node(tmp_path)
    assert row["execution_status"] == "UNKNOWN"
    assert row["blocking_reason"] is None
