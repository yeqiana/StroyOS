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

def test_real_unknown_preflight_is_reported_without_losing_mysql_history():
    attempt={**ATTEMPT,"status":"OUTCOME_UNKNOWN_BLOCKED",
             "attempt_rows":26,"outcome_unknown_assets":["episode/frame-02"]}
    result=p.assess({"driver_state":"EXITED","liveness":"DEAD"},attempt,
                    {"status":"STAGE_ELIGIBLE","stage":"VISUAL_CALIBRATED","source":"mysql"})
    assert result["status"]=="PAID_ATTEMPT_RECONCILIATION_REQUIRED"
    assert result["historical_attempt_rows"]==26
    assert result["outcome_unknown_count"]==1
    assert result["active_attempt_count"]==0
    assert result["may_retry_paid_attempt"] is False
    assert result["model_calls"]==0 and result["sql_writes"]==0

def test_inspect_accepts_exit_2_only_as_blocked_authority_receipt(tmp_path,monkeypatch):
    episode=tmp_path/"episodes"/"ep"
    episode.mkdir(parents=True)
    monkeypatch.setattr(p.native,"ROOT",tmp_path)
    monkeypatch.setattr(p.native,"canonical_episode",lambda _:episode)
    monkeypatch.setattr(p.native,"native_environment",lambda:{})
    responses=[
        (0,{"driver_state":"EXITED","liveness":"DEAD","heartbeat_status":"HUMAN_REQUIRED"}),
        (2,{**ATTEMPT,"status":"OUTCOME_UNKNOWN_BLOCKED","attempt_rows":26,
            "outcome_unknown_assets":["ep/frame-02"]}),
        (0,{"status":"STAGE_ELIGIBLE","stage":"VISUAL_CALIBRATED","source":"mysql"}),
    ]
    monkeypatch.setattr(p.native,"_probe",lambda *_a:responses.pop(0))
    result=p.inspect("episodes/ep")
    assert result["status"]=="PAID_ATTEMPT_RECONCILIATION_REQUIRED"
    assert result["historical_attempt_rows"]==26

def test_exit2_corrupt_or_unproved_unknown_stays_unverified():
    stage={"status":"STAGE_ELIGIBLE","stage":"VISUAL_CALIBRATED","source":"mysql"}
    for attempt in [
        {**ATTEMPT,"status":"OUTCOME_UNKNOWN_BLOCKED","attempt_rows":26},
        {**ATTEMPT,"status":"ATTEMPT_HISTORY_INTEGRITY_BLOCKED","attempt_rows":26,
         "outcome_unknown_assets":["ep/frame-02"]},
        {**ATTEMPT,"status":"UNKNOWN","attempt_rows":26,
         "outcome_unknown_assets":["ep/frame-02"]},
    ]:
        result=p.assess(DRIVER,attempt,stage)
        assert result["status"]=="AUTHORITIES_UNVERIFIED"
        assert result["may_retry_paid_attempt"] is False

def test_active_preflight_maintains_hard_stop_with_correct_counts():
    result=p.assess(DRIVER,{**ATTEMPT,"status":"ACTIVE_ATTEMPT_BLOCKED",
        "attempt_rows":26,"active_attempt_assets":["ep/frame-03"]},
        {"status":"STAGE_ELIGIBLE","stage":"VISUAL_CALIBRATED","source":"mysql"})
    assert result["active_attempt_count"]==1
    assert result["status"]=="PAID_ATTEMPT_RECONCILIATION_REQUIRED"
    assert not result["may_retry_paid_attempt"]
