"""Slimdown must not broaden image/provider or critic-dispatch authority."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SYSTEM=Path(__file__).resolve().parents[2]/"episodes"/"_system"
sys.path.insert(0,str(SYSTEM))
import runtime_router
import runtime_scheduler
import storyos_config


def test_default_image_and_vision_routes_remain_native_codex(monkeypatch):
    for key in ("STORY_OS_IMAGE_EXECUTOR","STORY_OS_IMAGE_RUNTIME",
                "STORY_OS_VISION_EXECUTOR","STORY_OS_VISION_RUNTIME"):
        monkeypatch.delenv(key, raising=False)
    image, image_source=runtime_router.image_execution_runtime()
    vision, vision_source=runtime_router.vision_review_runtime()
    assert image=="CODEX", image_source
    assert vision=="CODEX", vision_source


def test_unsupported_executor_is_rejected_not_silently_proxied(monkeypatch):
    monkeypatch.setenv("STORY_OS_IMAGE_EXECUTOR","OPENCODEX")
    with pytest.raises(ValueError,match="invalid STORY_OS_IMAGE_EXECUTOR"):
        runtime_router.image_execution_runtime()
    monkeypatch.delenv("STORY_OS_IMAGE_EXECUTOR")
    monkeypatch.setenv("STORY_OS_VISION_EXECUTOR","OPENCODEX")
    with pytest.raises(ValueError,match="invalid STORY_OS_VISION_EXECUTOR"):
        runtime_router.vision_review_runtime()


def test_no_route_has_no_critic_execution_target():
    decision=runtime_scheduler.authorize_critic_dispatch(
        task_type="story_semantic_critic",
        legacy_target={"provider":"codex_user_runner","runtime":"CODEX","model":"model"},
        route_decision={"effective_action":"NO_ROUTE"},
        production_enabled=True)
    assert decision["action"]=="NO_ROUTE"
    assert decision["execution_target"] is None
    assert decision["scheduler_authorized"] is False


def test_shadow_review_adapters_cannot_create_authority():
    cfg=storyos_config.load_config()
    adapters=storyos_config.get_path(cfg,"agent_runtime.adapters")
    for name in ("story_semantic_critic","preimage_semantic_critic","final_semantic_critic"):
        assert adapters[name]["shadow_enabled"] is False
        assert adapters[name]["production_enabled"] is False
