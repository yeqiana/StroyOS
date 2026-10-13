"""R10 slot2/3: no fictitious first start and no paid-attempt omission."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
import storyos_autonomy_production_probe as p

DRIVER={"driver_state":"RUNNING","liveness":"ALIVE","heartbeat_status":"RUNNING"}
STAGE={"status":"STAGE_ELIGIBLE","stage":"STORYBOARD_LOCKED","source":"mysql"}
ATTEMPT={"status":"ATTEMPT_HISTORY_READ_ONLY","active_attempt_assets":[],
         "outcome_unknown_assets":[],"unverified_status_assets":[],
         "attempt_rows":0}

def test_no_driver_record_is_not_proof_user_never_started():
    r=p.assess({"driver_state":"NEVER_STARTED","liveness":"DEAD"},ATTEMPT,STAGE)
    assert r["status"]=="DRIVER_HISTORY_UNVERIFIED"
    assert r["previous_driver_start_verified"] is False
    assert not r["may_retry_paid_attempt"]

def test_unverified_status_assets_never_certify_zero_paid():
    r=p.assess(DRIVER,{**ATTEMPT,"unverified_status_assets":["01"]},STAGE)
    assert r["status"]=="PAID_ATTEMPT_RECONCILIATION_REQUIRED"
    assert not r["image_generation_verified"]

def test_historical_attempt_must_not_be_described_as_no_paid_attempt():
    r=p.assess(DRIVER,{**ATTEMPT,"attempt_rows":3},STAGE)
    assert r["status"]=="RUNNING_WITH_HISTORICAL_ATTEMPTS"
    assert r["active_attempt_count"]==0

def test_invalid_mysql_attempt_rows_fail_closed():
    r=p.assess(DRIVER,{**ATTEMPT,"attempt_rows":-1},STAGE)
    assert r["status"]=="AUTHORITIES_UNVERIFIED"

def test_mysql_publish_ready_while_unknown_paid_request_needs_reconciliation():
    r=p.assess(DRIVER,{**ATTEMPT,"outcome_unknown_assets":["01"]},
               {"status":"ALREADY_PUBLISH_READY","stage":"PUBLISH_READY","source":"mysql"})
    assert r["status"]=="PAID_ATTEMPT_RECONCILIATION_REQUIRED"
    assert r["publish_ready_verified"] is False
