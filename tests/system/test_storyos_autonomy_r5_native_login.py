"""R5 slot3: logged-in CLI bridge is evidence, not permission to spend."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
import storyos_codex_cli_readiness as readiness

def test_bridge_health_without_model_call_is_only_auth_presence():
    report=readiness.inspect_storyos_bridge(health_provider=lambda:{
      "status":"ok","interactive_user":True,"codex_available":True,
      "codex_home_accessible":True,"codex_auth_present":True})
    assert report["status"]=="BRIDGE_AUTH_PRESENT"
    assert report["model_execution_verified"] is False

def test_cli_probe_must_not_claim_login_even_when_flags_supported(monkeypatch):
    from subprocess import CompletedProcess
    monkeypatch.setattr(readiness.subprocess,"run",lambda argv,**kw:CompletedProcess(
        argv,0,"codex-cli 0.162.1" if "--version" in argv else
        "--ephemeral --skip-git-repo-check --json --sandbox\n -C, --cd",""))
    report=readiness.inspect_cli("codex.cmd")
    assert report["status"]=="CLI_FLAGS_SUPPORTED"
    assert report["native_credential_check"] is False
    assert report["runtime_model_calls"]==0

def test_joined_readiness_flags_distinguish_logged_in_and_entitlement():
    from storyos_autonomy_native_ready import summarize
    cli={"status":"CLI_FLAGS_SUPPORTED","version":"codex-cli 0.162.1"}
    bridge={"status":"BRIDGE_AUTH_PRESENT"}
    r=summarize(cli,bridge)
    assert r["status"]=="NATIVE_AUTH_CONTEXT_READY"
    assert r["model_entitlement_verified"] is False
    assert r["may_start_paid_production"] is False
    assert r["model_calls"]==0

def test_unverified_model_probe_never_authorizes():
    from storyos_autonomy_native_ready import summarize
    r=summarize({"status":"CLI_PROBE_FAILED"},{"status":"BRIDGE_AUTH_PRESENT"})
    assert r["status"]=="BLOCKED"
    assert not r["may_start_paid_production"]
