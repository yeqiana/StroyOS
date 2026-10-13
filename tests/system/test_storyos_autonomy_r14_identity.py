"""R14 slot2: native Codex executable proof must match interactive runner."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
import storyos_autonomy_r12_critic_preflight as p

READY=dict(
 stage={"status":"STAGE_ELIGIBLE","source":"mysql","stage":"STORYBOARD_LOCKED"},
 paid={"status":"ATTEMPT_HISTORY_READ_ONLY","active_attempt_assets":[],
       "outcome_unknown_assets":[],"unverified_status_assets":[]},
 driver={"driver_state":"NEVER_STARTED","liveness":"DEAD"},
 codex={"status":"NATIVE_AUTH_CONTEXT_READY","opencodex_used":False,
        "interactive_codex_auth_context_present":True,
        "cli_runner_same_binary_verified":True},
 review={"status":"ONE_SHOT_NEW_CRITIC_EPOCH_READY","attempt":9},
)
def classify(**kw):
    return p.decide(**{**READY,**kw})

def test_same_binary_interactive_login_is_readonly_text_critic_eligibility():
    r=classify()
    assert r["status"]=="READY_FOR_ONE_SHOT_NATIVE_TEXT_REVIEW"
    assert r["may_start_new_text_review"] is True
    assert r["can_dispatch_image"] is False
    assert r["model_calls"]==r["sql_writes"]==0

def test_ambiguous_binary_identity_denies_even_authenticated_codex():
    for fingerprint in (False,None):
        r=classify(codex={**READY["codex"],
            "cli_runner_same_binary_verified":fingerprint})
        assert r["status"]=="NATIVE_CODEX_AUTH_UNVERIFIED"
        assert r["may_start_new_text_review"] is False

def test_other_provider_environment_is_never_accepted():
    r=classify(codex={**READY["codex"],"opencodex_used":True})
    assert r["status"]=="NATIVE_CODEX_AUTH_UNVERIFIED"

def test_active_driver_and_ambiguous_paid_image_both_block():
    assert classify(driver={"driver_state":"RUNNING","liveness":"ALIVE"})[
        "may_start_new_text_review"] is False
    r=classify(paid={**READY["paid"],"outcome_unknown_assets":["frame01"]})
    assert r["status"]=="IMAGE_ATTEMPT_AUTHORITY_UNVERIFIED"
