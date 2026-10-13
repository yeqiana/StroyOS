"""Native Codex production must not be blocked by optional old host probes."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"episodes"/"_system"))
import next_action as actions

def test_optional_prior_shadow_does_not_block_native(monkeypatch):
    ep=ROOT/"episodes"/"00_独立篇"/"test"
    row={"path":ep/"meta/runtime/reviews/old-request.json",
         "payload":{"status":"AWAITING_PRODUCT_REVIEW",
                    "review_kind":"story-semantic-critic-shadow"}}
    monkeypatch.setattr(actions.runtime_router,"text_review_runtime",lambda:("CODEX","test"))
    monkeypatch.setattr(actions.runtime_review_persistence,"list_current",lambda ep:[row])
    assert actions.pending_product_review(ep,current_state="STORYBOARD_LOCKED") is None

def test_mandatory_story_critic_still_blocks_native(monkeypatch):
    ep=ROOT/"episodes"/"00_独立篇"/"test"
    row={"path":ep/"meta/runtime/reviews/current-request.json",
         "payload":{"status":"AWAITING_PRODUCT_REVIEW",
                    "review_kind":"story-semantic","attempt":1,
                    "created_at":"2026-10-13T02:00:00+08:00"}}
    monkeypatch.setattr(actions.runtime_router,"text_review_runtime",lambda:("CODEX","test"))
    monkeypatch.setattr(actions.runtime_review_persistence,"list_current",lambda ep:[row])
    monkeypatch.setattr(actions.product_review_adapter,"answered_request",lambda ep,req:None)
    monkeypatch.setattr(actions.product_review_adapter,"reconcile_request",lambda ep,req:(req,None))
    result=actions.pending_product_review(ep,current_state="STORYBOARD_LOCKED")
    assert result["review_kind"]=="story-semantic"


def test_collaborative_work_still_requires_shadow_host(monkeypatch):
    ep=ROOT/"episodes"/"00_独立篇"/"test"
    row={"path":ep/"meta/runtime/reviews/old-request.json",
         "payload":{"status":"AWAITING_PRODUCT_REVIEW",
                    "review_kind":"story-semantic-critic-shadow",
                    "attempt":1,"created_at":"2026-10-13T02:00:00+08:00"}}
    monkeypatch.setattr(actions.runtime_router,"text_review_runtime",lambda:("WORK","test"))
    monkeypatch.setattr(actions.runtime_review_persistence,"list_current",lambda ep:[row])
    monkeypatch.setattr(actions.product_review_adapter,"answered_request",lambda ep,req:None)
    monkeypatch.setattr(actions.product_review_adapter,"reconcile_request",lambda ep,req:(req,None))
    result=actions.pending_product_review(ep,current_state="STORYBOARD_LOCKED")
    assert result["review_kind"]=="story-semantic-critic-shadow"
