"""Finalizer re-entry must use final weak-pass authority, not initial PASS only."""
from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"episodes/_system"))
import machine_action_executor as machine


def prepare(monkeypatch, errors):
    state=["STORYBOARD_LOCKED"]
    monkeypatch.setattr(machine,"_state",lambda ep:state[0])
    monkeypatch.setattr(machine,"_materialize_visual_machine_contract",lambda ep:{})
    monkeypatch.setattr(machine.frame_contract,"record_projection_migrations",lambda ep:{})
    monkeypatch.setattr(machine.visual_lock_baseline_gate,"validate_review",
                        lambda ep:["unposed_capture and not_cinematic original FAIL"])
    monkeypatch.setattr(machine.visual_lock_baseline_gate,"validate_final_requirement",
                        lambda ep:errors)
    monkeypatch.setattr(machine.visual_lock_v21,"verify",lambda *a,**k:[])
    monkeypatch.setattr(machine.visual_lock_finalizer,"build",lambda ep:{"decision":"WEAK_PASS"})
    monkeypatch.setattr(machine.visual_lock_finalizer,"verify",lambda ep:[])
    monkeypatch.setattr(machine.delegated_approval,"verify",lambda *a:[])
    monkeypatch.setattr(machine.episode_state,"transition_cmd",
                        lambda args:state.__setitem__(0,args.target))
    return state


def test_budget_exhausted_soft_baseline_can_finalize(monkeypatch):
    state=prepare(monkeypatch,[])
    result=machine._finalize_visual_lock(ROOT)
    assert result["status"]=="PASS"
    assert state[0]=="VISUAL_CALIBRATED"


def test_hard_baseline_failure_still_blocks(monkeypatch):
    state=prepare(monkeypatch,["character identity anchor mismatch"])
    with pytest.raises(machine.MachineActionError,match="character identity"):
        machine._finalize_visual_lock(ROOT)
    assert state[0]=="STORYBOARD_LOCKED"
