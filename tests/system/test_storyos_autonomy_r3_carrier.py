"""R3 slot1: offline Windows watchdog carrier contract, no Task Scheduler changes."""
from __future__ import annotations
from pathlib import Path
import sys
from unittest.mock import patch
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
import storyos_autonomy_carrier as c

EP=ROOT/"episodes"/"00_独立篇"/"test"
def test_carrier_plan_is_deterministic_and_escapes_quotes():
    p=c.build_plan(EP, identity="RENRP\\user")
    assert p["status"]=="PLAN_ONLY"
    assert p["task_name"].startswith("StoryOSAutonomy-")
    assert p["task_name"]==c.build_plan(EP,identity="RENRP\\user")["task_name"]
    assert "--ack-real-production" in p["arguments"]
    assert "--interval-seconds" in p["arguments"]
    assert p["principal"]=="RENRP\\user"
    assert p["model_calls"]==p["sql_writes"]==0

@pytest.mark.parametrize("identity", ["", "NT AUTHORITY\\SYSTEM", "SYSTEM", "LocalSystem"])
def test_carrier_never_installs_under_system(identity):
    with pytest.raises(ValueError,match="INTERACTIVE_USER"):
        c.build_plan(EP,identity=identity)

def test_carrier_plan_never_calls_registration(monkeypatch):
    with patch.object(c.subprocess,"run",side_effect=AssertionError("no OS call")):
        p=c.build_plan(EP, identity="interactive\\owner")
    assert p["status"]=="PLAN_ONLY"

def test_install_refuses_without_explicit_ack(monkeypatch):
    with patch.object(c,"register_task",side_effect=AssertionError("must not register")):
        assert c.install(EP,acknowledged=False,identity="interactive\\owner")["status"]=="ACK_REQUIRED"

def test_install_checks_existing_task_and_never_overwrites_foreign(monkeypatch):
    with patch.object(c,"registered_task",return_value={"principal":"elsewhere\\user"}), \
         patch.object(c,"register_task",side_effect=AssertionError("forbidden")):
        assert c.install(EP,acknowledged=True,identity="interactive\\owner")["status"]=="TASK_ALREADY_EXISTS"

def test_carrier_refuses_disposable_worktree_install(monkeypatch):
    with patch.object(c,"registered_task",return_value=None), \
         patch.object(c,"_primary_checkout",return_value=False), \
         patch.object(c,"register_task",side_effect=AssertionError("no registration")):
        assert c.install(EP,acknowledged=True,identity="interactive\\owner")["status"]=="PRIMARY_CHECKOUT_REQUIRED"

def test_uninstall_never_removes_unrecognized_task(monkeypatch):
    with patch.object(c,"registered_task",return_value={
        "principal":"elsewhere\\user","executable":"different.exe","arguments":"bad"
    }),patch.object(c,"_powershell",side_effect=AssertionError("no destructive action")):
        assert c.uninstall(EP,acknowledged=True,identity="interactive\\owner")["status"]=="FOREIGN_TASK_REFUSED"

def test_uninstall_needs_separate_explicit_ack():
    assert c.uninstall(EP,acknowledged=False,identity="interactive\\owner")["status"]=="ACK_REQUIRED"


def test_task_args_use_canonical_main_worktree(monkeypatch):
    p=c.build_plan(EP,identity="interactive\\owner")
    assert p["executable"]==sys.executable
    assert str(c.ROOT/"scripts/storyos_autonomy_watchdog.py") in p["arguments"]
    assert str(EP) in p["arguments"]
