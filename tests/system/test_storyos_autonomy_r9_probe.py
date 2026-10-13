"""R9 Slot 1/3: live production proof never infers paid image from heartbeat."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
import storyos_autonomy_production_probe as p

STAGE={"status":"STAGE_ELIGIBLE","stage":"STORYBOARD_LOCKED","source":"mysql"}
ATTEMPT={"status":"ATTEMPT_HISTORY_READ_ONLY","active_attempt_assets":[],
         "outcome_unknown_assets":[],"attempt_rows":0}
DRIVER={"driver_state":"RUNNING","liveness":"ALIVE","heartbeat_status":"RETRY_WAIT"}

def test_live_retry_wait_not_image_success():
    result=p.assess(DRIVER,ATTEMPT,STAGE)
    assert result["status"]=="RUNNING_RETRY_WAIT"
    assert result["image_generation_verified"] is False
    assert result["may_retry_paid_attempt"] is False
    assert result["active_attempt_count"]==0

def test_unknown_attempt_fail_closed_even_if_driver_alive():
    result=p.assess(DRIVER,{**ATTEMPT,"outcome_unknown_assets":["01"]},STAGE)
    assert result["status"]=="PAID_ATTEMPT_RECONCILIATION_REQUIRED"
    assert result["may_retry_paid_attempt"] is False

def test_mysql_stage_missing_cannot_claim_completed():
    result=p.assess(DRIVER,ATTEMPT,{"status":"ALREADY_PUBLISH_READY","stage":"PUBLISH_READY","source":"json"})
    assert result["status"]=="AUTHORITIES_UNVERIFIED"
    assert result["publish_ready_verified"] is False

def test_mysql_publish_ready_is_stage_proof_not_pixel_proof():
    result=p.assess({"driver_state":"EXITED","liveness":"DEAD"},ATTEMPT,
                    {"status":"ALREADY_PUBLISH_READY","stage":"PUBLISH_READY","source":"mysql"})
    assert result["status"]=="MYSQL_PUBLISH_READY"
    assert result["publish_ready_verified"] is True
    assert result["image_generation_verified"] is False

def test_driver_alive_without_attempt_does_not_prove_provider_call():
    result=p.assess({"driver_state":"RUNNING","liveness":"ALIVE","heartbeat_status":"RUNNING"},
                    ATTEMPT,STAGE)
    assert result["status"]=="RUNNING_NO_PAID_ATTEMPT"
    assert not result["image_generation_verified"]
