"""R4 slot2: distinguish authorized/watchable and misconfigured Windows task."""
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
import storyos_autonomy_carrier as carrier
import storyos_autonomy_watchdog as watchdog

EP=ROOT/"episodes"/"00_独立篇"/"unit"
def test_status_must_not_report_unverified_trigger_as_installed():
    plan=carrier.build_plan(EP,identity="interactive\\worker")
    record={"principal":plan["principal"],"executable":plan["executable"],
            "arguments":plan["arguments"],"trigger":"AT_BOOT",
            "multiple_instances":"Parallel","enabled":True}
    assert carrier._task_matches(plan,record) is False


def test_status_requires_interactive_logon_and_single_instance():
    plan=carrier.build_plan(EP,identity="interactive\\worker")
    record={"principal":plan["principal"],"executable":plan["executable"],
            "arguments":plan["arguments"],"working_directory":plan["working_directory"],
            "trigger":"AT_USER_LOGON","trigger_user":plan["principal"],
            "multiple_instances":"IgnoreNew","enabled":True}
    assert carrier._task_matches(plan,record) is True
    record["enabled"]=False
    assert carrier._task_matches(plan,record) is False

def test_watchdog_refuses_routing_evidence_drift(tmp_path,monkeypatch):
    from test_storyos_autonomy_watchdog_common import good,EP
    import storyos_autonomy_watchdog as watchdog
    from copy import deepcopy
    base=good()
    base["codex"]={"mode_ok":True,"model_client_version_ok":True}
    second=deepcopy(base)
    second["codex"]["model_client_version_ok"]=False
    reports=iter([base,second])
    launches=[]
    monkeypatch.setattr(watchdog.native,"canonical_episode",
                        lambda _:watchdog.ROOT/EP)
    monkeypatch.setattr(watchdog.native,"native_environment",lambda:{})
    monkeypatch.setattr(watchdog.native,"preflight",lambda *_a,**_k:next(reports))
    result=watchdog.tick(EP,acknowledged=True,data_root=tmp_path,
        dispatch=lambda *_a:launches.append(1),now_ts=1_800_000_000)
    assert result["status"]=="AUTHORITY_CHANGED"
    assert not launches
    assert not list(tmp_path.glob("*.json"))
