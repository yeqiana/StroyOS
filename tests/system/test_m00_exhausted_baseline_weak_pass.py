"""Exhaustion permits only SHA-bound, independently checked soft-quality debt."""
from pathlib import Path
import sys
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"episodes/_system"))
import visual_lock_baseline_gate as baseline
import visual_lock_candidate_pool as pool

EP=ROOT/"episodes/00_独立篇/13_失物归还的那扇门"
SHA="a"*64


def test_budget_exhaustion_soft_checks_allowed_only_for_current_sha(monkeypatch):
    monkeypatch.setattr(pool,"baseline_frame",lambda _ep:1)
    monkeypatch.setattr(pool,"weak_pass_allowed",lambda _ep:True)
    monkeypatch.setattr(baseline,"eligible_exhausted_baseline",lambda _ep:True)
    monkeypatch.setattr(pool,"_ledger_frame",lambda _ep,_frame:{
        "status":"REPAIR_READY","attempts":[{"result":"success"}]*2,
        "current_candidate":{"sha256":SHA}})
    row={"id":"V-B","frame":1,"sha256":SHA,
         "checks":{"not_cinematic":False,"identity_usable":True},
         "issues":["cinematic_visual_polish"]}
    monkeypatch.setattr(pool,"_row_for_frame",lambda _ep,_frame:row)
    status=pool.weak_pass_eligibility(EP,1)
    assert status["eligible"] and status["eligible_by_budget_exhaustion"]
    assert status["content_attempts"]==2
    row["checks"]["character_appearance_anchor_fidelity"]=False
    assert not pool.weak_pass_eligibility(EP,1)["eligible"]
    row["checks"].pop("character_appearance_anchor_fidelity")
    row["sha256"]="b"*64
    assert not pool.weak_pass_eligibility(EP,1)["eligible"]


def test_soft_baseline_proof_never_substitutes_for_real_review(monkeypatch):
    monkeypatch.setattr(baseline,"validate_review",lambda ep:["unposed capture FAIL"])
    monkeypatch.setattr(baseline,"eligible_exhausted_baseline",lambda ep:False)
    assert not baseline.ready_for_joint_critic(EP)
    monkeypatch.setattr(baseline,"eligible_exhausted_baseline",lambda ep:True)
    assert baseline.ready_for_joint_critic(EP)
