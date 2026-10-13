"""R13 slot3: independent text Critic never implies Frame01 pixels."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
import storyos_autonomy_r12_critic_preflight as admission
import storyos_autonomy_production_probe as production

def test_native_text_review_ready_never_mints_paid_image_permit():
    result=admission.decide(
       stage={"status":"STAGE_ELIGIBLE","stage":"STORYBOARD_LOCKED","source":"mysql"},
       paid={"status":"ATTEMPT_HISTORY_READ_ONLY","active_attempt_assets":[],
             "outcome_unknown_assets":[],"unverified_status_assets":[]},
       driver={"driver_state":"STOPPED","liveness":"DEAD"},
       codex={"status":"NATIVE_AUTH_CONTEXT_READY","opencodex_used":False,
              "interactive_codex_auth_context_present":True},
       review={"status":"ONE_SHOT_NEW_CRITIC_EPOCH_READY","attempt":9})
    assert result["may_start_new_text_review"] is True
    assert result["can_dispatch_image"] is False

def test_unknown_paid_generation_prevails_over_passing_review():
    result=production.assess(
       {"driver_state":"RUNNING","liveness":"ALIVE",
        "heartbeat_status":"RUNNING"},
       {"status":"ATTEMPT_HISTORY_READ_ONLY","active_attempt_assets":[],
        "outcome_unknown_assets":["01"],"attempt_rows":1},
       {"status":"STAGE_ELIGIBLE","stage":"STORYBOARD_LOCKED","source":"mysql"})
    assert result["status"]=="PAID_ATTEMPT_RECONCILIATION_REQUIRED"
    assert not result["may_retry_paid_attempt"]
