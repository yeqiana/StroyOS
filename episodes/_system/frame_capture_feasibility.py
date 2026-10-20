"""Conservative, deterministic single-frame capture feasibility gate.

Only explicit structured contradictions are blocking. Free-form Story/Storyboard
prose is not parsed into invented camera facts; no LLM/Review is invoked.
"""
from __future__ import annotations


def inspect(contract: dict) -> dict:
    body = contract.get("hash_material") if isinstance(contract, dict) else None
    data = body if isinstance(body, dict) else contract
    if not isinstance(data, dict):
        return {"status": "UNVERIFIED", "blockers": [], "advisories": []}
    shot = data.get("shot_progression") or {}
    capture = data.get("capture_event") or {}
    if not isinstance(shot, dict) or not isinstance(capture, dict):
        return {"status": "UNVERIFIED", "blockers": [], "advisories": []}
    blockers = []
    advisories = []
    pov_mode = str(shot.get("pov_mode") or "")
    owner = str(capture.get("photographer_id") or "").strip()
    # Explicit contract fields are optional. Missing structured facts must not
    # convert a valid legacy shot into a false-positive hard stop.
    declared = str(shot.get("required_camera_operator_id") or "").strip()
    if declared and owner and declared != owner and pov_mode.startswith("first_person"):
        blockers.append("FRAME_CAMERA_OPERATOR_IDENTITY_CONFLICT")
    hand_count = shot.get("simultaneous_operator_hands_required")
    if (pov_mode == "first_person_handheld"
            and type(hand_count) is int and 0 <= hand_count <= 2
            and hand_count > 1):
        blockers.append("FRAME_CAMERA_OPERATOR_HAND_CAPACITY_CONFLICT")
    if (pov_mode == "first_person_handheld"
            and capture.get("camera_mount") in {"fixed_tripod", "unattended_remote"}):
        blockers.append("FRAME_CAPTURE_SUPPORT_CONFLICT")
    if pov_mode == "first_person_handheld" and owner and not blockers:
        # Operator action can be physically plausible (one hand signs while
        # the other records); never fail solely for a Chinese action keyword.
        if shot.get("human_action_stage") == "act":
            advisories.append("FRAME_OPERATOR_ACTION_VISIBILITY_CHECK_RECOMMENDED")
    return {
        "status": "BLOCKED" if blockers else ("ADVISORY" if advisories else "PASS"),
        "blockers": blockers,
        "advisories": advisories,
    }


def require_feasible(contract: dict) -> None:
    report = inspect(contract)
    if report["blockers"]:
        raise ValueError("FRAME_CAPTURE_INFEASIBLE:" + ",".join(report["blockers"]))
