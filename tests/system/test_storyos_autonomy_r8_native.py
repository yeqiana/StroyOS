"""R8 native DAG start must not misrepresent real image readiness."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
import storyos_codex_managed as native

def test_dag_startable_without_visual_lock_does_not_claim_image_ready():
    report=native.admission_summary(stage={"status":"STAGE_ELIGIBLE","stage":"STORYBOARD_LOCKED"},
                                    visual={"status":"BLOCKED","reason":"FOUR_FRAME_MISSING"},
                                    native_ready={"bridge_ok":True,"mode_ok":True,
                                                  "model_client_version_ok":True},
                                    blockers=[])
    assert report["dag_startable"] is True
    assert report["image_ready"] is False
    assert report["image_blocking_reason"]=="FOUR_FRAME_MISSING"

def test_finished_episode_will_not_resume():
    report=native.admission_summary(stage={"status":"ALREADY_PUBLISH_READY","stage":"PUBLISH_READY"},
                                    visual={"status":"NOT_APPLICABLE"},native_ready={},blockers=["EPISODE_STAGE_NOT_ELIGIBLE_FOR_PRODUCTION"])
    assert report["dag_startable"] is False
    assert report["image_ready"] is False

def test_no_readonly_visual_proof_never_entitles_paid_image():
    report=native.admission_summary(stage={"status":"STAGE_ELIGIBLE","stage":"STORYBOARD_LOCKED"},
                                    visual={"status":"REVIEW_PASS_REQUIRES_INDEPENDENT_PROVENANCE"},
                                    native_ready={"bridge_ok":True,"mode_ok":True,"model_client_version_ok":True},
                                    blockers=[])
    assert report["image_ready"] is False
