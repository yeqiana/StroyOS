"""Regression for immutable PREIMAGE continuity anchors at Visual Lock finalization."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "episodes/_system"))
import machine_action_executor as machine
import frame_contract_persistence as history


@pytest.fixture
def source(tmp_path, monkeypatch):
    root = tmp_path / "storyOS"
    ep = root / "episodes" / "00_独立篇" / "14_深渊疗愈所_第一集_净土生命还原"
    ep.mkdir(parents=True)
    monkeypatch.setattr(machine, "__file__",
                        str(root / "episodes/_system/machine_action_executor.py"))
    sha = {f: f"{f:064x}" for f in (1,5,45,47)}
    ids = {1:"V-B",5:"V-A",45:"V-W",47:"V-H"}
    registry = {"items": {rid: {"status":"WEAK_PASS", "frame_contract_sha256":sha[f]}
                          for f,rid in ids.items()}}
    monkeypatch.setattr(machine.visual_lock_candidate_pool,
                        "ep14_remaining_exhausted_weak_passes", lambda *_: [])
    monkeypatch.setattr(machine.visual_lock_candidate_pool.visual_lock_admission_state,
                        "load", lambda *_: registry)
    old = {"location":"mountain_road",
           "weather_time":"night; cold rainy night on an exposed karst mountain road"}
    monkeypatch.setattr(history, "load_sha_bound_version",
                        lambda _ep, f, _sha: {"contract_sha256": sha[f],
                            "hash_material":{"continuity":{"anchors":dict(old)}}})
    bad = {"location":"{'architecture_context': 'invalid stringified location'}",
           "weather_time":"locked temporal continuity"}
    return ep, old, bad, registry


def test_four_weak_pass_source_restores_only_two_corrupted_fields(source):
    ep, old, bad, _ = source
    anchors = {"protagonist":"P01", **bad}
    result = machine._restore_ep14_overwritten_machine_anchors(ep, anchors, bad)
    assert result["status"] == "RESTORED"
    assert result["fields"] == ["location", "weather_time"]
    assert result["paid_image_attempts"] == 0
    assert anchors == {"protagonist":"P01", **old}


def test_unchanged_and_unrelated_sources_are_not_rewritten(source,tmp_path):
    ep, old, bad, _ = source
    anchors = dict(old)
    assert machine._restore_ep14_overwritten_machine_anchors(
        ep, anchors, bad)["status"] == "UNCHANGED"
    assert anchors == old
    unrelated = tmp_path / "other"
    assert machine._restore_ep14_overwritten_machine_anchors(
        unrelated, dict(bad), bad)["status"] == "NOT_APPLICABLE"


@pytest.mark.parametrize("corruption", ["missing_weak_proof", "stale_history", "unexpected_current"])
def test_corrupted_source_fails_without_changing_locked_gate(source,monkeypatch,corruption):
    ep,old,bad,registry=source
    anchors = dict(bad)
    if corruption == "missing_weak_proof":
        monkeypatch.setattr(machine.visual_lock_candidate_pool,
                            "ep14_remaining_exhausted_weak_passes",lambda *_: None)
    elif corruption == "stale_history":
        registry["items"]["V-B"]["frame_contract_sha256"] = "0" * 64
    else:
        anchors["weather_time"] = "a new user authored weather contract"
    before=dict(anchors)
    with pytest.raises(machine.MachineActionError):
        machine._restore_ep14_overwritten_machine_anchors(ep, anchors, bad)
    assert anchors == before


def test_machine_action_restores_only_two_fields_with_exact_cas(source, monkeypatch):
    import hashlib
    ep, old, bad, _ = source
    gates = {"visual": {"continuity": {"anchors": {"protagonist": "P01", **bad}}}}
    gate_path = ep / "meta/story-gates.json"
    gate_path.parent.mkdir(parents=True, exist_ok=True)
    gate_path.write_text("original-gates", encoding="utf-8")
    before = hashlib.sha256(gate_path.read_bytes()).hexdigest()
    writes = []
    monkeypatch.setattr(machine, "_state", lambda *_: "STORYBOARD_LOCKED")
    monkeypatch.setattr(machine, "_read",
                        lambda _ep, rel: gates if rel == "meta/story-gates.json"
                        else ({"initial_location": {"x":1}} if rel == "meta/world-state.json" else {}))
    monkeypatch.setattr(machine.story_json, "write_json",
                        lambda _path, value: writes.append(value.copy()))
    monkeypatch.setattr(machine.frame_contract, "record_projection_migrations",
                        lambda *_: {"status":"PASS","count":4})
    monkeypatch.setattr(machine, "ep14_visual_anchor_restore_plan", lambda *_:{
        "status":"READY", "source_gate_sha256":before,
        "fields":["location","weather_time"], "restored":old,
    })
    action={"action":"RESTORE_EP14_VISUAL_PROJECTION_ANCHORS",
            "executor":"MACHINE", "source_gate_sha256":before}
    report=machine.execute(ep,action)
    assert report["status"]=="PASS" and report["new_paid_attempts"]==0
    assert report["projection_migrations"]["count"]==4
    assert gates["visual"]["continuity"]["anchors"]=={"protagonist":"P01",**old}
    assert len(writes)==1
    with pytest.raises(machine.MachineActionError,match="CAS_DRIFT"):
        machine.restore_ep14_visual_projection_anchors(ep,expected_gate_sha="0"*64)


def test_machine_restore_action_refuses_non_machine_dispatch(source):
    ep,_,_,_=source
    assert machine.local_machine_action({
        "action":"RESTORE_EP14_VISUAL_PROJECTION_ANCHORS",
        "executor":"CODEX_IMAGE"}) is None


def test_rc900_proof_never_accepts_unrelated_crash(source,monkeypatch):
    import production_ep14_machine_anchor_rc900 as reentry
    ep,_,_,_=source
    log=ep/"meta/runtime/driver-logs"/"driver_fake.log"
    log.parent.mkdir(parents=True)
    log.write_text("DRIVER CRASH ValueError('unrelated exception')",encoding="utf-8")
    monkeypatch.setattr(reentry,"EPISODE",ep)
    monkeypatch.setattr(reentry.runtime_driver,"status",lambda *_:{
        "driver_state":"EXITED", "liveness":"DEAD", "pid":0,
        "exit_code":"900", "log":str(log), "record":{
            "rc":"900 2026-10-25", "episode":str(ep),"log":str(log),
        }})
    with pytest.raises(reentry.SourceUnverified,match="UNRELATED_RC900_CRASH"):
        reentry.inspect(ep)
