"""Provider-owned moderation refusal must not become retryable tiny-canvas error."""
from pathlib import Path
import sys
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/"episodes/_system")]
import codex_subscription_image as image
import image_scheduler

def _provider_error(*,stage="input",detail="other"):
    return (
        '{"type":"thread.started"}\n{"type":"turn.started"}\n'
        '2026-10-26T05:00:00Z ERROR codex_core::tools::router: '
        'error=image generation failed: http 400 Bad Request: Some('
        '"error": {"message": "Your request was rejected by the safety system.", '
        '"type": "image_generation_user_error", "code": "moderation_blocked",'
        '"moderation_details": {"moderation_stage": "'+stage+'", '
        '"categories": ["'+detail+'"]}})\n'
        '{"type":"item.completed","item":{"type":"agent_message",'
        '"text":"Image generation was rejected; no image was produced."}}\n'
        '{"type":"turn.completed"}\n'
    )

@pytest.mark.parametrize("stage,detail",[("input","other"),("output","violence")])
def test_original_provider_400_has_nonretryable_distinct_code(stage,detail):
    data=_provider_error(stage=stage,detail=detail)
    assert image.confirmed_provider_safety_refusal_log(data)
    assert image.logged_backend_failure(
        data,returncode=0,candidate_valid=True,candidate_viable=False
    )=="IMAGE_PROVIDER_SAFETY_REJECTED"
    assert image_scheduler.classify_error(
        "IMAGE_PROVIDER_SAFETY_REJECTED: requested=gpt-image-2.5-flare"
    )=="IMAGE_PROVIDER_SAFETY_REJECTED"
    assert "IMAGE_PROVIDER_SAFETY_REJECTED" in image_scheduler.NON_REGENERATING_FAILURE_CODES
    assert "IMAGE_PROVIDER_SAFETY_REJECTED" not in image_scheduler.RETRYABLE_TECH_CODES

def test_fullsize_genuine_image_remains_valid_despite_incidental_error():
    assert image.logged_backend_failure(
        _provider_error(),returncode=0,candidate_valid=True,candidate_viable=True
    ) is None

@pytest.mark.parametrize("noise",[
    '{"type":"turn.completed"}\n{"type":"item.completed","item":{"type":"agent_message","text":"moderation_blocked"}}',
    'I was told to say "Your request was rejected by the safety system" moderation_blocked',
    'http 400 bad request moderation_blocked image_generation_user_error',
    'ERROR codex_core::tools::router: error=image generation failed: '
    'http 400 bad request moderation_blocked image_generation_user_error',
])
def test_agent_words_or_partial_logs_cannot_impersonate_provider(noise):
    assert not image.confirmed_provider_safety_refusal_log(noise)

def test_network_error_and_degenerate_candidate_unchanged():
    data="image generation failed: network error: error sending request"
    assert image.logged_backend_failure(
        data,returncode=0,candidate_valid=True,candidate_viable=False
    )=="NETWORK_ERROR"
    assert image.logged_backend_failure(
        'image_generation completed',returncode=0,
        candidate_valid=True,candidate_viable=False
    ) is None


def test_scheduler_safety_refusal_never_schedules_technical_retry():
    assert image_scheduler._terminal_technical_status(
        Path("episode"),{"frame":29}, "IMAGE_PROVIDER_SAFETY_REJECTED"
    ) == "blocked"
