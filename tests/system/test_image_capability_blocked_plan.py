"""队列已有能力阻断时，计划视图必须如实报告剩余工作（离线无写入）。"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "episodes/_system"))
import image_scheduler as scheduler


def test_sixteen_native_image_capability_blocks_visible_without_paid_dispatch(monkeypatch):
    queue = {"items": [
        {"id": f"batch-{i}", "frame": i, "scope": "batch", "kind": "original",
         "status": "blocked",
         "technical_failure_code": "LOGIN_AUTH_IMAGE_TOOL_CAPABILITY_UNKNOWN",
         "last_error": "independent payload route unavailable"}
        for i in range(2, 18)
    ]}
    monkeypatch.setattr(scheduler, "ready_items", lambda ep, q: ([], []))
    monkeypatch.setattr(scheduler, "unresolved_generation_evidence_for_plan",
                        lambda ep, q: [])
    monkeypatch.setattr(scheduler.scheduler_core, "progress",
                        lambda ep, q: {"generated_frames": 4})
    result = scheduler.plan_snapshot(Path("unused"), queue)
    assert result["ready"] == []
    assert result["blocked"] == []  # dependency blocks keep their old meaning
    assert result["authority_blocked"] == []
    assert result["requires_capability_verification"] is True
    assert result["capability_blocked_count"] == 16
    assert [r["frame"] for r in result["capability_blocked"]] == list(range(2, 18))
    assert all(r["action"] == "VERIFY_NATIVE_CODEX_IMAGE_CAPABILITY"
               and r["retry_permitted"] is False for r in result["capability_blocked"])
    assert all(item["status"] == "blocked" for item in queue["items"])


def test_plan_reports_only_capability_blocked_rows_and_no_unearned_permission(monkeypatch):
    queue = {"items": [
        {"frame": 2, "scope": "batch", "status": "blocked",
         "technical_failure_code": "LOGIN_AUTH_IMAGE_TOOL_UNAVAILABLE_FOR_VISIBLE_MODELS"},
        {"frame": 3, "scope": "batch", "status": "blocked",
         "technical_failure_code": "OTHER_FAILURE"},
        {"frame": 4, "scope": "batch", "status": "generated",
         "technical_failure_code": "LOGIN_AUTH_IMAGE_TOOL_CAPABILITY_UNKNOWN"},
    ]}
    monkeypatch.setattr(scheduler, "ready_items", lambda *_: ([], []))
    monkeypatch.setattr(scheduler, "unresolved_generation_evidence_for_plan",
                        lambda *_: [])
    monkeypatch.setattr(scheduler.scheduler_core, "progress", lambda *_: {})
    result = scheduler.plan_snapshot(Path("unused"), queue)
    assert result["capability_blocked_count"] == 1
    assert [r["frame"] for r in result["capability_blocked"]] == [2]
    assert result["unresolved_status_blocked_count"] == 2
    assert result["requires_capability_verification"] is True
    assert result["requires_evidence_verification"] is False
