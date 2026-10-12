"""A stale/cancelled review must not become an apparent approval.

Temporary Episode lives under the repository's ignored _tests directory,
following the existing review lifecycle fixtures. No image Provider or publish.
"""
import json
import tempfile
from pathlib import Path
import sys
import pytest

ROOT=Path(__file__).resolve().parents[2]
SYSTEM=ROOT/"episodes"/"_system"
if str(SYSTEM) not in sys.path:sys.path.insert(0,str(SYSTEM))
import product_review_adapter as adapter


@pytest.fixture
def review_episode():
    parent=ROOT/"episodes"/"_tests"
    parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="single-node-review-",dir=parent) as temp:
        ep=Path(temp)
        (ep/"meta/runtime/reviews").mkdir(parents=True)
        (ep/"meta/episode-state.json").write_text(
            json.dumps({"current_state":"STORYBOARD_LOCKED"}),encoding="utf-8")
        source=ep/"story.md"
        source.write_text("story original",encoding="utf-8")
        yield ep,source


def _prepare(ep,source):
    return adapter.prepare(
        ep,kind="story-semantic",runtime="WORK",attempt=1,
        prompt="review the frozen story",source_paths=[source],
        candidate_path=ep/"meta/.story-semantic.a1.candidate.json",
    )


def test_cancelled_story_review_cannot_finalize_after_restart_style_reload(review_episode):
    ep,source=review_episode
    request=_prepare(ep,source)
    adapter.cancel_request(ep,"story-semantic",attempt=1,
                           actor="operator",reason="source rejected")
    candidate=ep/"meta/.story-semantic.a1.candidate.json"
    candidate.write_text(json.dumps({"summary":{"passed":True}}),encoding="utf-8")
    with pytest.raises(adapter.ProductReviewError,match="cannot be finalized"):
        adapter.finalize_candidate(ep,kind="story-semantic",runtime="WORK",
                                   attempt=1,candidate_path=candidate)
    with pytest.raises(adapter.ProductReviewError,match="cannot complete"):
        adapter.mark_complete(ep,"story-semantic",final_path=candidate,attempt=1)
    stored=json.loads(adapter.request_path(ep,"story-semantic",attempt=1).read_text("utf-8"))
    assert stored["status"]=="CANCELLED"
    assert "final_path" not in stored


def test_drifted_story_review_cannot_be_reused_after_source_change(review_episode):
    ep,source=review_episode
    request=_prepare(ep,source)
    source.write_text("a different story",encoding="utf-8")
    reconciled,event=adapter.reconcile_request(ep,request)
    assert reconciled["status"]=="SUPERSEDED"
    assert event["status"]=="SUPERSEDED"
    candidate=ep/"meta/.story-semantic.a1.candidate.json"
    candidate.write_text(json.dumps({"summary":{"passed":True}}),encoding="utf-8")
    with pytest.raises(adapter.ProductReviewError,match="cannot be finalized"):
        adapter.finalize_candidate(ep,kind="story-semantic",runtime="WORK",
                                   attempt=1,candidate_path=candidate)
    stored=json.loads(adapter.request_path(ep,"story-semantic",attempt=1).read_text("utf-8"))
    assert stored["status"]=="SUPERSEDED"
    assert "final_path" not in stored
