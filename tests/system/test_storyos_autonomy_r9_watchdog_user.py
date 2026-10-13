"""R9 Slot 2: installed carrier identity must use OS SID, not display spelling."""
import sys
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
import storyos_autonomy_carrier as c

EP=ROOT/"episodes"/"00_独立篇"/"test"

def record(plan):
    return {"principal":"normalized-local-user","executable":plan["executable"],
            "arguments":plan["arguments"],"working_directory":plan["working_directory"],
            "trigger":"AT_USER_LOGON","trigger_user":plan["principal"],
            "multiple_instances":"IgnoreNew","enabled":True}

def test_sid_equivalent_scheduler_user_passes(monkeypatch):
    p=c.build_plan(EP,identity="DESKTOP\\worker")
    r=record(p)
    monkeypatch.setattr(c,"_windows_sid_equal",lambda a,b: (a,b)==("normalized-local-user",p["principal"]))
    assert c._task_matches(p,r)

def test_different_sid_scheduler_user_remains_foreign(monkeypatch):
    p=c.build_plan(EP,identity="DESKTOP\\worker")
    monkeypatch.setattr(c,"_windows_sid_equal",lambda a,b:False)
    assert not c._task_matches(p,record(p))

def test_install_does_not_claim_registered_without_readback(monkeypatch):
    p=c.build_plan(EP,identity="DESKTOP\\worker")
    state=[None,{"principal":"foreign"}]
    monkeypatch.setattr(c,"registered_task",lambda name:state.pop(0))
    monkeypatch.setattr(c,"_primary_checkout",lambda:True)
    monkeypatch.setattr(c,"register_task",lambda plan:True)
    result=c.install(EP,acknowledged=True,identity="DESKTOP\\worker")
    assert result["status"]=="REGISTERED_BUT_UNVERIFIED"
    assert result["changed"] is True

def test_install_accepts_verified_sid_equivalent_readback(monkeypatch):
    plan=c.build_plan(EP,identity="DESKTOP\\worker")
    state=[None,{**record(plan),"principal":plan["principal"]}]
    monkeypatch.setattr(c,"registered_task",lambda _:state.pop(0))
    monkeypatch.setattr(c,"_primary_checkout",lambda:True)
    monkeypatch.setattr(c,"register_task",lambda _:True)
    result=c.install(EP,acknowledged=True,identity="DESKTOP\\worker")
    assert result["status"]=="REGISTERED"
