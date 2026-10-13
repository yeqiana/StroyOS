"""R15 slot3: unknown paid image and stale review do not authorize Frame01."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
import storyos_autonomy_r12_critic_preflight as gate

D=dict(stage={"status":"STAGE_ELIGIBLE","stage":"STORYBOARD_LOCKED","source":"mysql"},
paid={"status":"ATTEMPT_HISTORY_READ_ONLY","active_attempt_assets":[],
 "outcome_unknown_assets":[],"unverified_status_assets":[]},
driver={"driver_state":"NEVER_STARTED","liveness":"DEAD"},
codex={"status":"NATIVE_AUTH_CONTEXT_READY","interactive_codex_auth_context_present":True,
 "cli_runner_same_binary_verified":True,"opencodex_used":False},
review={"status":"ONE_SHOT_NEW_CRITIC_EPOCH_READY","attempt":9})

def test_unknown_paid_image_must_not_retry():
    p={**D["paid"],"outcome_unknown_assets":["frame01"]}
    r=gate.decide(**{**D,"paid":p})
    assert r["status"]=="IMAGE_ATTEMPT_AUTHORITY_UNVERIFIED"
    assert r["can_dispatch_image"] is False
    assert r["may_start_new_text_review"] is False

def test_review_ready_still_not_pixel_or_image_permit():
    r=gate.decide(**D)
    assert r["may_start_new_text_review"] is True
    assert r["can_dispatch_image"] is False

def test_an_existing_one_shot_ticket_stops_a_second_run():
    r=gate.decide(**{**D,"review":{"status":"ALREADY_AUTHORIZED_NO_RETRY"}})
    assert r["status"]=="RUBRIC_REVIEW_AUTHORITY_UNVERIFIED"
    assert not r["may_start_new_text_review"]
