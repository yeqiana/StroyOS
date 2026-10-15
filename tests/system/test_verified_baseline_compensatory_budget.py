"""Compensatory image budget is not a reusable or global third dispatch."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "episodes/_system"))
import generation_attempt_authority as attempts


class FakeConnection:
    def __init__(self):
        self.records = [
            {"ATTEMPT_INDEX": 1, "STATUS": "FAILED_AFTER_DISPATCH",
             "FAILURE_CLASS": "IMAGE_TOOL_NETWORK_ERROR_DURABLE_RECEIPT",
             "RESULT_REF": None, "PROVIDER": "codex_subscription"},
            {"ATTEMPT_INDEX": 2, "STATUS": "SUCCEEDED",
             "FAILURE_CLASS": None, "RESULT_REF": "candidate.png",
             "PROVIDER": "codex_subscription"},
        ]

    def query_all(self, query, args):
        assert "FOR UPDATE" in query
        return self.records


EP = "00_独立篇/13_失物归还的那扇门"
CONTEXT = {
    "scope": "repair",
    "generation_attempt_reason": "VISUAL_LOCK_CONTENT_REPAIR",
    "image_capability_proof_purpose": attempts.BASELINE_REPAIR_PROOF_REASON,
    "visual_lock_frame": 1,
    "provider": "codex_subscription",
    "payload_model": "gpt-image-2.5-flare",
    "payload_quality": "high",
    "capture_id": "visual-lock-candidate-v2-semantic-anchor-01-01",
    "queue_item_id": "frame01-candidate",
}


def test_exact_network_failure_allows_one_compensated_slot():
    c = FakeConnection()
    assert attempts._verified_compensatory_baseline(c, EP, EP+"/frame-01", CONTEXT, 2)
    assert not attempts._verified_compensatory_baseline(c, EP, EP+"/frame-01", CONTEXT, 3)
    assert not attempts._verified_compensatory_baseline(c, EP, EP+"/frame-02", CONTEXT, 2)
    assert not attempts._verified_compensatory_baseline(c, "unrelated/episode",
                                                       "unrelated/episode/frame-01", CONTEXT, 2)


def test_unknown_and_unverified_errors_do_not_grant_paid_retries():
    c = FakeConnection()
    for status in ("OUTCOME_UNKNOWN", "DISPATCH_COMMITTED", "RESERVED", "SUCCEEDED"):
        c.records[0]["STATUS"] = status
        assert not attempts._verified_compensatory_baseline(c, EP, EP+"/frame-01", CONTEXT, 2)
    c.records[0]["STATUS"] = "FAILED_AFTER_DISPATCH"
    c.records[0]["FAILURE_CLASS"] = "unverified_network_error"
    assert not attempts._verified_compensatory_baseline(c, EP, EP+"/frame-01", CONTEXT, 2)


def test_cannot_bypass_with_false_context_or_second_success_missing():
    c = FakeConnection()
    for key, value in (
        ("scope", "visual_lock"), ("capture_id", "manual"),
        ("generation_attempt_reason", "PRIMARY_GENERATION"),
        ("image_capability_proof_purpose", "arbitrary"),
        ("visual_lock_frame", 18), ("provider", "opencodex"),
    ):
        edited = {**CONTEXT, key: value}
        assert not attempts._verified_compensatory_baseline(
            c, EP, EP+"/frame-01", edited, 2)
    c.records[1]["STATUS"] = "OUTCOME_UNKNOWN"
    assert not attempts._verified_compensatory_baseline(c, EP, EP+"/frame-01", CONTEXT, 2)
