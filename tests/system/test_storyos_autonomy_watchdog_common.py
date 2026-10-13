"""Offline native Codex watchdog tests: no model, image or production DB calls."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
import storyos_autonomy_watchdog as wd

EP="episodes/00_独立篇/test"
def good(state="ABNORMAL_DISAPPEARANCE", *, liveness="DEAD", code=""):
    return {"status":"READY_TO_START","episode":EP,
            "scope":"NATIVE_CODEX_FULL_AUTO","production_mode":"CODEX_MANAGED",
            "image_executor":"CODEX","read_only":True,"production_authorization":False,
            "model_calls":0,"sql_writes":0,"blockers":[],
            "attempt":{"status":"ATTEMPT_HISTORY_READ_ONLY",
                        "outcome_unknown_assets":[],"active_attempt_assets":[]},
            "episode_stage":{"status":"STAGE_ELIGIBLE","current_state":"IDEA_LOCKED","source":"mysql"},
            "mysql":{"schema_status":"READY_FOR_FURTHER_ADMISSION"},
            "driver_state":state,
            "driver_evidence":{"driver_state":state,"liveness":liveness,
                               "exit_code":code,"pid":123 if state=="ABNORMAL_DISAPPEARANCE" else 0}}
