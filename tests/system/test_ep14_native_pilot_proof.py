"""EP14 only: live native capability, never global UNKNOWN-as-PASS."""
from __future__ import annotations

from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "episodes/_system"))
import production_ep14_native_pilot_proof as pilot


def valid_strict():
    return {
        "status": "BLOCKED",
        "failure_class": "LOGIN_AUTH_IMAGE_TOOL_CAPABILITY_UNKNOWN",
        "image_generation_called": False,
        "image_attempt_authority_called": False,
    }


def payload():
    return {"model": "gpt-image-2.5-flare", "quality": "high"}


def controller():
    return {"model": "gpt-6-luna", "reasoning_effort": "high"}


def runner_proof():
    return {
        "status": "READY_FOR_REAL_CAPABILITY_PROOF",
        "catalog_sha256": "d" * 64,
        "transport_model": "gpt-6-luna",
        "transport_effort": "high",
        "payload_model": "gpt-image-2.5-flare",
        "payload_quality": "high",
        "image_generation_visible_secondary": True,
        "image_generation_called": False,
        "image_attempt_authority_called": False,
    }


def test_exact_dual_source_never_claims_global_tool_entitlement(monkeypatch):
    monkeypatch.setattr(pilot, "_provider_capabilities_read", lambda: {
        "imageGeneration": True, "webSearch": True,
        "source": "NATIVE_CODEX_APP_SERVER_MODEL_PROVIDER_CAPABILITIES_READ",
    })
    monkeypatch.setattr(pilot.baseline, "attest_secondary",
                        lambda strict,p,c,codex: runner_proof())
    r = pilot.attest_one_frame(valid_strict(), payload(), controller())
    assert r["trial_scope"] == pilot.PILOT_STATUS
    assert r["trial_frame"] == 9
    assert r["tool_capability_state"] == "UNKNOWN"
    assert r["tool_registry_attestation"] == "UNAVAILABLE"
    assert r["status"] == "READY_FOR_REAL_CAPABILITY_PROOF"
    assert len(r["native_provider_capability_sha256"]) == 64
    assert r["image_attempt_authority_called"] is False
    assert r["image_generation_called"] is False


@pytest.mark.parametrize("bad",[
    "provider_no","session_tool_not_visible","account_auth_missing",
    "source_not_exact","model_wrong","quality_wrong","controller_wrong",
    "already_generated","attempt_reserved","original_provider_safety_denial",
])
def test_unverified_provider_or_attempt_fail_closed(monkeypatch,bad):
    evidence={"imageGeneration":True,"webSearch":True,
              "source":"NATIVE_CODEX_APP_SERVER_MODEL_PROVIDER_CAPABILITIES_READ"}
    mock_runner=[runner_proof()]
    monkeypatch.setattr(pilot,"_provider_capabilities_read",lambda:evidence)
    monkeypatch.setattr(pilot.baseline,"attest_secondary",
                        lambda strict,p,c,codex:mock_runner[0])
    strict=valid_strict()
    p=payload()
    c=controller()
    if bad=="provider_no":evidence["imageGeneration"]=False
    elif bad=="session_tool_not_visible":mock_runner[0]=None
    elif bad=="account_auth_missing":mock_runner[0]=None
    elif bad=="source_not_exact":strict["status"]="READY_FOR_REAL_CAPABILITY_PROOF"
    elif bad=="model_wrong":p["model"]="gpt-image-bogus"
    elif bad=="quality_wrong":p["quality"]="low"
    elif bad=="controller_wrong":c["model"]="bogus"
    elif bad=="already_generated":strict["image_generation_called"]=True
    elif bad=="attempt_reserved":strict["image_attempt_authority_called"]=True
    elif bad=="original_provider_safety_denial":
        strict["failure_class"]="IMAGE_PROVIDER_SAFETY_REJECTED"
    with pytest.raises(pilot.PilotDenied):
        pilot.attest_one_frame(strict,p,c)


@pytest.mark.parametrize("row",[
    {"frame":29,"kind":"repair","scope":"batch","status":"queued"},
    {"frame":9,"kind":"original","scope":"batch","status":"queued"},
    {"frame":9,"kind":"repair","scope":"batch","status":"external_blocked"},
    {"frame":9,"kind":"repair","scope":"batch","status":"pilot_hold"},
])
def test_nonpilot_or_old_refused_rows_never_eligible(row):
    assert pilot.eligible(Path("dummy"),row,payload(),controller()) is False
