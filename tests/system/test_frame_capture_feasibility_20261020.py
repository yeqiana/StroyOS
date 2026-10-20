"""Conservative POV/camera feasibility: block only explicit contradictory facts."""
from __future__ import annotations
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"episodes/_system"))
import frame_capture_feasibility as gate


def shot(**kwargs):
    return {"hash_material":{
        "shot_progression":{"pov_mode":"first_person_handheld",
                           "human_action_stage":"act",**kwargs},
        "capture_event":{"photographer_id":"P01"}
    }}


def test_two_simultaneously_busy_hands_and_handheld_camera_are_impossible():
    report=gate.inspect(shot(simultaneous_operator_hands_required=2))
    assert report["status"]=="BLOCKED"
    with pytest.raises(ValueError,match="FRAME_CAMERA_OPERATOR_HAND_CAPACITY_CONFLICT"):
        gate.require_feasible(shot(simultaneous_operator_hands_required=2))


def test_conflicting_authoritative_photographer_identity_is_blocked():
    report=gate.inspect(shot(required_camera_operator_id="P02"))
    assert "FRAME_CAMERA_OPERATOR_IDENTITY_CONFLICT" in report["blockers"]


def test_legitimate_one_hand_signing_is_not_silently_rewritten_or_blocked():
    report=gate.inspect(shot(action="P01签四张单据",simultaneous_operator_hands_required=1))
    assert not report["blockers"]
    assert report["status"]=="ADVISORY"
    gate.require_feasible(shot(action="P01签四张单据"))


def test_missing_or_unstructured_fields_do_not_falsely_block():
    assert gate.inspect({})["status"]=="PASS"
    assert gate.inspect({"hash_material":{"shot_progression":{},
                "capture_event":{}}})["blockers"]==[]
