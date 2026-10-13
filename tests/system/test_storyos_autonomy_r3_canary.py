"""R3 slot3: image Frame01 canary remains read-only, never creates Provider attempt."""
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import patch
import pytest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
import storyos_autonomy_canary as canary

def healthy():
    return {"status":"READY_TO_START","read_only":True,"production_authorization":False,
            "model_calls":0,"sql_writes":0,"image_executor":"CODEX",
            "production_mode":"CODEX_MANAGED","blockers":[],
            "episode_stage":{"source":"mysql","current_state":"STORYBOARD_LOCKED"},
            "attempt":{"status":"ATTEMPT_HISTORY_READ_ONLY","outcome_unknown_assets":[],
                       "active_attempt_assets":[]},
            "codex":{"mode_ok":True,"bridge_ok":True,"model_client_version_ok":True,
                     "tool_generation_proven":False},
            "visual_lock_admission":{"status":"BLOCKED"}}

def baseline():
    return {"status":"READ_ONLY_EVIDENCE_READY_TEST_DB_STILL_REQUIRED",
            "authorized_to_mutate_production":False,"model_calls":0,"sql_writes":0}

def test_canary_plan_is_not_entitlement_or_paid_launch():
    d=canary.decide(healthy(),baseline(),episode="episodes/00_独立篇/test")
    assert d["status"]=="EVIDENCE_ONLY"
    assert d["can_dispatch_image"] is False
    assert d["model_entitlement_verified"] is False
    assert d["frame"]==1

@pytest.mark.parametrize("broken",[
 lambda n,b:n["attempt"].update(outcome_unknown_assets=["01"]),
 lambda n,b:n.update(status="BLOCKED"),
 lambda n,b:n["episode_stage"].update(source="json"),
 lambda n,b:n["codex"].update(mode_ok=False),
 lambda n,b:b.update(model_calls=1),
 lambda n,b:b.update(authorized_to_mutate_production=True),
 lambda n,b:b.update(status="BLOCKED"),
])
def test_canary_unverified_authorities_fail_closed(broken):
    n,b=healthy(),baseline()
    broken(n,b)
    assert canary.decide(n,b,episode="episodes/00_独立篇/test")["status"]=="BLOCKED"

def test_only_frame_one_and_zero_calls_reported():
    result=canary.decide(healthy(),baseline(),episode="episodes/00_独立篇/test")
    assert result["frame"]==1 and result["model_calls"]==result["sql_writes"]==0
