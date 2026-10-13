"""R10 fourth slot: concrete safety gates and hermetic per-slot regression."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
sys.path.insert(0,str(ROOT/"episodes"/"_system"))
import storyos_autonomy_fast_test as fast
import storyos_autonomy_production_probe as probe
import story_review_attempt_admission as auth
import storyos_story_review_readonly as cli


def test_r10_four_fast_slots_registered_and_extreme_stress_retained():
    for name in ("story-critic-authority","driver-lifecycle","paid-attempt-proof","r10-integrated"):
        assert name in fast.SLOTS
        assert fast.test_commands(slot=name)
    cmd=fast.test_commands(slot="all",stress=True)
    assert any("test_multi_episode_global_image_capacity.py" in x for x in cmd[-1])
    assert any("test_storyos_autonomy_r10_runtime_admission.py" in x for a in cmd for x in a)


def test_lifecycle_conflict_cannot_unlock_image_on_healthy_driver():
    review=auth.decide(dag_attempt=162,official_review=None,
        request_rows={1:{"status":"AWAITING_PRODUCT_REVIEW"},
                      2:{"status":"FINALIZED"}},candidate_exists={1:False})
    live=probe.assess({"driver_state":"RUNNING","liveness":"ALIVE",
                       "heartbeat_status":"RETRY_WAIT"},
        {"status":"ATTEMPT_HISTORY_READ_ONLY","active_attempt_assets":[],
         "outcome_unknown_assets":[],"attempt_rows":0},
        {"status":"STAGE_ELIGIBLE","stage":"STORYBOARD_LOCKED","source":"mysql"})
    assert review["return_code"]==22 and review["may_dispatch"] is False
    assert live["image_generation_verified"] is False
    assert live["may_retry_paid_attempt"] is False


def test_readonly_auditor_blocks_unverified_mysql_without_model(monkeypatch):
    ep=ROOT/"episodes"/"00_独立篇"/"test"
    monkeypatch.setattr(cli.native,"canonical_episode",lambda _:ep)
    monkeypatch.setattr(cli.native,"native_environment",lambda:{})
    calls=[]
    monkeypatch.setattr(cli.native,"_probe",lambda *args:(calls.append(1),(
        2,{"status":"STAGE_UNVERIFIED","source":"file","stage":"STORYBOARD_LOCKED"}))[1])
    result=cli.inspect("episodes/00_独立篇/test")
    assert result["status"]=="MYSQL_STORYBOARD_STAGE_UNVERIFIED"
    assert result["read_only"] and result["model_calls"]==result["sql_writes"]==0
    assert len(calls)==1
