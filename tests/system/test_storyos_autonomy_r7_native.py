"""R7 slot3: CLI under PATH must be identical to interactive Runner's CLI."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
import storyos_autonomy_native_ready as r
import storyos_codex_cli_readiness as low

def cli_hash(raw):
    return low.executable_fingerprint(raw)

def test_same_native_binary_and_version_is_verified():
    cli={"status":"CLI_FLAGS_SUPPORTED","version":"codex-cli 0.162.1",
         "executable_fingerprint":cli_hash("C:/bin/codex.cmd")}
    bridge={"status":"BRIDGE_AUTH_PRESENT","codex_version":"codex-cli 0.162.1",
            "executable_fingerprint":cli_hash("C:/bin/codex.cmd")}
    report=r.summarize(cli,bridge)
    assert report["status"]=="NATIVE_AUTH_CONTEXT_READY"
    assert report["cli_runner_same_binary_verified"] is True

def test_different_cli_or_version_blocks():
    for cli_path,version in [("C:/alt/codex.cmd","codex-cli 0.162.1"),
                             ("C:/bin/codex.cmd","codex-cli 0.99.0")]:
        cli={"status":"CLI_FLAGS_SUPPORTED","version":version,
             "executable_fingerprint":cli_hash(cli_path)}
        bridge={"status":"BRIDGE_AUTH_PRESENT","codex_version":"codex-cli 0.162.1",
                "executable_fingerprint":cli_hash("C:/bin/codex.cmd")}
        result=r.summarize(cli,bridge)
        assert result["status"]=="BLOCKED"
        assert not result["may_start_paid_production"]

def test_bridge_absent_route_cannot_prove_same_binary():
    report=r.summarize({"status":"CLI_FLAGS_SUPPORTED","version":"codex-cli 0.162.1"},
                      {"status":"BRIDGE_AUTH_PRESENT"})
    assert report["cli_runner_same_binary_verified"] is False
    assert not report["may_start_paid_production"]

def test_bridge_fingerprint_never_exposes_path():
    report=low.inspect_storyos_bridge(health_provider=lambda:{
        "status":"ok","interactive_user":True,"codex_available":True,
        "codex_home_accessible":True,"codex_auth_present":True,
        "codex_executable":"C:/users/private/My Dir/codex.cmd",
        "codex_version":"codex-cli 0.162.1"})
    assert report["status"]=="BRIDGE_AUTH_PRESENT"
    assert report["executable_fingerprint"]==cli_hash("C:/users/private/My Dir/codex.cmd")
    assert "codex_executable" not in report
