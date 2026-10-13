"""R12 slot 3: text Critic is never an image Permit or publish evidence."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
import storyos_autonomy_r12_critic_preflight as preflight
BASE={
"stage":{"status":"STAGE_ELIGIBLE","source":"mysql","stage":"STORYBOARD_LOCKED"},
"paid":{"status":"ATTEMPT_HISTORY_READ_ONLY","active_attempt_assets":[],
        "outcome_unknown_assets":[],"unverified_status_assets":[]},
"driver":{"driver_state":"STOPPED","liveness":"DEAD"},
"codex":{"status":"NATIVE_AUTH_CONTEXT_READY","opencodex_used":False,
         "interactive_codex_auth_context_present":True,
         "cli_runner_same_binary_verified":True},
"review":{"status":"ONE_SHOT_NEW_CRITIC_EPOCH_READY","attempt":9},
}
def run(**kw):
    x={**BASE,**kw}
    return preflight.decide(**x)

def test_new_text_critic_authorized_but_no_image_paid_permit():
    r=run()
    assert r["may_start_new_text_review"]
    assert r["can_dispatch_image"] is False
    assert r["model_calls"]==r["sql_writes"]==0

def test_unknown_paid_image_prevents_even_text_review():
    r=run(paid={**BASE["paid"],"outcome_unknown_assets":["frame01"]})
    assert r["status"]=="IMAGE_ATTEMPT_AUTHORITY_UNVERIFIED"
    assert not r["may_start_new_text_review"]

def test_native_codex_login_not_substituted_by_opencodex():
    r=run(codex={**BASE["codex"],"opencodex_used":True})
    assert r["status"]=="NATIVE_CODEX_AUTH_UNVERIFIED"

def test_driver_active_blocks_second_session():
    r=run(driver={"driver_state":"RUNNING","liveness":"ALIVE"})
    assert r["status"]=="DRIVER_SINGLETON_UNVERIFIED"

def test_review_already_frozen_disallows_duplicate_paid_critic():
    r=run(review={"status":"ALREADY_AUTHORIZED_NO_RETRY","attempt":9})
    assert not r["may_start_new_text_review"]
