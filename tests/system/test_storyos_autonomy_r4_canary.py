"""R4 slot3: Frame01 evidence must survive a second native authority read."""
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
import storyos_autonomy_canary as c
from test_storyos_autonomy_r3_canary import healthy,baseline

def test_second_native_snapshot_drift_blocks_evidence(monkeypatch):
    from test_storyos_autonomy_watchdog_common import EP
    ep=c.native.ROOT/EP
    reports=[healthy(),healthy()]
    reports[1]["attempt"]["active_attempt_assets"]=["frame-01"]
    monkeypatch.setattr(c.native,"canonical_episode",lambda _:ep)
    monkeypatch.setattr(c.native,"native_environment",lambda:{})
    monkeypatch.setattr(c.native,"preflight",lambda *_a,**_k:reports.pop(0))
    monkeypatch.setattr(c.native,"_probe",lambda *_a,**_k:(0,baseline()))
    d=c.plan(EP)
    assert d["status"]=="BLOCKED"
    assert d["can_dispatch_image"] is False


def test_canary_does_not_accept_baseline_from_different_episode():
    native=healthy()
    baseline_evidence=baseline()
    baseline_evidence["episode"]="other-episode"
    assert c.decide(native,baseline_evidence,episode="episodes/00_独立篇/test")["status"]=="BLOCKED"
