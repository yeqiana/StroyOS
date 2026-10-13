"""R16 slot3: resident watchdog must stop at actual A9 timeout."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
import storyos_codex_managed as n

def test_live_a9_ticket_fences_auto_driver_restart(tmp_path,monkeypatch):
    ep=tmp_path/"episodes"/"fixture"
    ticket=ep/"meta/runtime/story-review-migrated-rubric-a9.json"
    ticket.parent.mkdir(parents=True)
    ticket.write_text("{}")
    monkeypatch.setattr(n,"ROOT",tmp_path)
    def probe(env,script,args,**kwargs):
        if script.endswith("runtime_router.py"):
            return 0,{"effective_production_mode":"CODEX_MANAGED","effective_runtime":"CODEX",
                "image_execution_runtime":"CODEX","local_codex_spawn_allowed":True,
                "local_codex_image_spawn_allowed":True,"text_review_runtime":"CODEX",
                "vision_review_runtime":"CODEX","governance_review_runtime":"CODEX"}
        if script.endswith("codex_user_runner.py"):return 0,{"status":"ok","codex_available":True,"codex_auth_present":True}
        if script.endswith("storyos_native_model_readiness.py"):return 0,{"status":"CLIENT_VERSION_COMPATIBLE"}
        if script.endswith("storyos_revision_schema_readonly.py"):return 0,{"status":"READY_FOR_FURTHER_ADMISSION"}
        if script.endswith("storyos_episode_stage_readonly.py"):return 0,{"status":"STAGE_ELIGIBLE","stage":"STORYBOARD_LOCKED","source":"mysql"}
        if script.endswith("storyos_creative_recovery_readonly.py"):return 0,{"status":"BLOCKED"}
        if script.endswith("storyos_attempt_readonly_preflight.py"):return 0,{"status":"ATTEMPT_HISTORY_READ_ONLY"}
        if script.endswith("runtime_driver.py"):return 0,{"driver_state":"NEVER_STARTED","liveness":"DEAD"}
        if script.endswith("storyos_visual_lock_readonly.py"):return 0,{"status":"BLOCKED","reason":"REAL_PIXEL_PENDING"}
        if script.endswith("storyos_a9_receipt_reconcile.py"):return 0,{"status":"PAID_CRITIC_TIMEOUT_NO_AUTORETRY"}
        return 2,{}
    monkeypatch.setattr(n,"_probe",probe)
    report=n.preflight({"STORYOS_MYSQL_HOST":"127.0.0.1",
                        "STORYOS_MYSQL_PORT":"3306"},episode=ep)
    assert "STORY_REVIEW_A9_RECONCILIATION_REQUIRED" in report["blockers"]
    assert report["status"]=="BLOCKED"
    assert report["production_admission"]["image_ready"] is False
    assert report["production_admission"]["dag_startable"] is False
    assert report["model_calls"]==report["sql_writes"]==0
