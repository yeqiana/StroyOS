"""R6 slot3: native CLI plus interactive auth evidence must guard Frame01 plan."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
import storyos_autonomy_canary as canary
from test_storyos_autonomy_r3_canary import healthy,baseline
from test_storyos_autonomy_watchdog_common import EP

def setup(monkeypatch):
    ep=canary.native.ROOT/EP
    monkeypatch.setattr(canary.native,"canonical_episode",lambda _:ep)
    monkeypatch.setattr(canary.native,"native_environment",lambda:{})
    monkeypatch.setattr(canary.native,"preflight",lambda *a,**k:healthy())
    monkeypatch.setattr(canary.native,"_probe",lambda *a,**k:(0,baseline()))

def test_cli_bridge_unavailable_refuses_even_when_stage_valid(monkeypatch):
    setup(monkeypatch)
    monkeypatch.setattr(canary.native_cli,"report",
                        lambda:{"status":"BLOCKED","model_calls":0,"sql_writes":0})
    result=canary.plan(EP)
    assert result["status"]=="BLOCKED"
    assert result["reason"]=="NATIVE_CLI_OR_LOGIN_UNVERIFIED"
    assert result["can_dispatch_image"] is False

def test_cli_login_drift_between_canary_probes_refuses(monkeypatch):
    setup(monkeypatch)
    reports=iter([{"status":"NATIVE_AUTH_CONTEXT_READY","model_calls":0,"sql_writes":0,
                   "may_start_paid_production":False,"opencodex_used":False,
                   "cli_runner_same_binary_verified":True},
                  {"status":"BLOCKED","model_calls":0,"sql_writes":0,
                   "may_start_paid_production":False,"opencodex_used":False}])
    monkeypatch.setattr(canary.native_cli,"report",lambda:next(reports))
    result=canary.plan(EP)
    assert result["status"]=="BLOCKED"
    assert result["reason"]=="NATIVE_CLI_OR_LOGIN_CHANGED"
    assert result["model_calls"]==0

def test_healthy_cli_is_evidence_only_not_paid_admission(monkeypatch):
    setup(monkeypatch)
    monkeypatch.setattr(canary.native_cli,"report",
                        lambda:{"status":"NATIVE_AUTH_CONTEXT_READY",
                                "model_calls":0,"sql_writes":0,
                                "may_start_paid_production":False,
                                "opencodex_used":False,
                                "cli_runner_same_binary_verified":True})
    result=canary.plan(EP)
    assert result["status"]=="EVIDENCE_ONLY"
    assert result["can_dispatch_image"] is False
