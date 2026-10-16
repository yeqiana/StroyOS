from __future__ import annotations
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
SYSTEM=ROOT/"episodes"/"_system"
if str(SYSTEM) not in sys.path:sys.path.insert(0,str(SYSTEM))
import image_scheduler as scheduler


def test_unknown_login_image_tool_capability_blocks_before_real_attempt():
    error="LOGIN_AUTH_IMAGE_TOOL_CAPABILITY_UNKNOWN: independent payload route unavailable; provider=codex_subscription"
    code=scheduler.classify_error(error)
    assert code=="LOGIN_AUTH_IMAGE_TOOL_CAPABILITY_UNKNOWN"
    assert code in scheduler.NON_REGENERATING_FAILURE_CODES
    assert code not in scheduler.RETRYABLE_TECH_CODES
    assert scheduler._terminal_technical_status(Path("."),{"frame":1},code)=="blocked"


def test_unavailable_visible_models_produces_distinct_not_retryable_capability_code():
    code=scheduler.classify_error("LOGIN_AUTH_IMAGE_TOOL_UNAVAILABLE_FOR_VISIBLE_MODELS: local")
    assert code=="LOGIN_AUTH_IMAGE_TOOL_UNAVAILABLE_FOR_VISIBLE_MODELS"
    assert code in scheduler.NON_REGENERATING_FAILURE_CODES


def test_native_user_runner_unavailable_is_a_pre_dispatch_block_not_a_paid_image_failure():
    error = ("LOGIN_AUTH_RUNNER_UNAVAILABLE: independent payload route unavailable; "
             "provider=codex_subscription")
    code = scheduler.classify_error(error)
    assert code == "LOGIN_AUTH_RUNNER_UNAVAILABLE"
    assert code in scheduler.PRE_DISPATCH_CAPABILITY_BLOCK_CODES
    assert code in scheduler.NON_REGENERATING_FAILURE_CODES
    assert code not in scheduler.RETRYABLE_TECH_CODES
    assert scheduler._terminal_technical_status(Path("."), {"frame": 2}, code) == "blocked"


def test_live_generation_failures_keep_original_retry_taxonomy():
    assert scheduler.classify_error("Selected model is at capacity. Please try a different model.")=="PROVIDER_CAPACITY"
    assert scheduler.classify_error("error_is_timeout=true and response absent")=="TIMEOUT"
    assert scheduler.classify_error("failed to save generated image: os error 183")=="PROVIDER_ARTIFACT_SAVE_COLLISION"
