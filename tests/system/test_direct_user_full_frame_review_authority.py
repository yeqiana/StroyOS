"""User-accepted visual pixels have separate authority, not fabricated model PASS."""
from __future__ import annotations

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'episodes' / '_system'))

import final_acceptance
import verified_review_authority as authority


def _raise_missing(key):
    raise RuntimeError(f"missing accepted visual asset {key}")


def _fixture(monkeypatch):
    sha = {"01": "a" * 64, "02": "b" * 64, "03": "c" * 64}
    rows = {
        "01": {
            "status": "NEEDS_USER",
            "current_candidate": {"sha256": sha["01"]},
            "attempts": [{"result": "success", "candidate": {"sha256": sha["01"]}}],
        },
        "02": {
            "status": "LOCKED",
            "approved_asset": {"path": "media/approved/02.png", "sha256": sha["02"]},
            "attempts": [{"result": "success", "candidate": {"sha256": sha["02"]}}],
        },
        "03": {
            "status": "WEAK_PASS",
            "approved_asset": {"path": "media/approved/03.png", "sha256": sha["03"]},
            "attempts": [{"result": "success", "candidate": {"sha256": sha["03"]}}],
        },
    }
    payload = {
        "known_defect_frames": [1],
        "accepted_visual_assets": {
            key: {"path": f"media/publish/{key}.png", "sha256": value}
            for key, value in sha.items()
        },
        "accepted_scopes": ["frame_semantic", "production_gate"],
    }
    monkeypatch.setattr(final_acceptance, "valid", lambda ep: payload)
    monkeypatch.setattr(final_acceptance, "allows", lambda ep, scope, frame=None:
                        scope in payload["accepted_scopes"])
    monkeypatch.setattr(final_acceptance, "visual_asset_for_frame", lambda ep, frame:
                        (payload["accepted_visual_assets"].get(str(frame).zfill(2)) or _raise_missing(str(frame))))
    return rows, payload


def test_fully_sha_bound_direct_user_acceptance_is_not_machine_pass(monkeypatch, tmp_path):
    rows, _ = _fixture(monkeypatch)
    outcome = authority._sha_bound_direct_user_authority(tmp_path, rows)
    assert outcome["status"] == "USER_ACCEPTED", outcome
    assert outcome["machine_review_pass"] is False
    assert outcome["frames"] == ["01", "02", "03"]
    assert outcome["errors"] == []


def test_missing_unaccepted_semantic_defect_fails_closed(monkeypatch, tmp_path):
    rows, payload = _fixture(monkeypatch)
    payload["known_defect_frames"] = []
    outcome = authority._sha_bound_direct_user_authority(tmp_path, rows)
    assert outcome["status"] == "BLOCKED"
    assert "not directly accepted" in " ".join(outcome["errors"])


def test_sha_drift_fails_closed(monkeypatch, tmp_path):
    rows, payload = _fixture(monkeypatch)
    payload["accepted_visual_assets"]["01"]["sha256"] = "d" * 64
    outcome = authority._sha_bound_direct_user_authority(tmp_path, rows)
    assert outcome["status"] == "BLOCKED"
    assert "differ from current ledger asset" in " ".join(outcome["errors"])


def test_partial_accepted_asset_mapping_fails_closed(monkeypatch, tmp_path):
    rows, payload = _fixture(monkeypatch)
    del payload["accepted_visual_assets"]["03"]
    outcome = authority._sha_bound_direct_user_authority(tmp_path, rows)
    assert outcome["status"] == "BLOCKED"
    assert "must equal" in " ".join(outcome["errors"])


def test_no_explicit_final_assets_uses_original_model_authority(monkeypatch, tmp_path):
    rows, payload = _fixture(monkeypatch)
    payload["accepted_visual_assets"] = {}
    assert authority._sha_bound_direct_user_authority(tmp_path, rows) is None


def test_main_verifier_uses_exact_direct_user_authority_not_fake_model_review(
        monkeypatch, tmp_path):
    rows, _ = _fixture(monkeypatch)
    monkeypatch.setattr(authority.frame_semantic_review.phase4_contract, "required",
                        lambda ep: True)
    monkeypatch.setattr(authority.production_ledger, "load_authority",
                        lambda ep, default=None: {"frames": rows})
    monkeypatch.setattr(authority, "_is_phase5a_test_only", lambda ep: False)
    def _must_not_run_model_review(*args, **kwargs):
        pytest.fail("direct-user path must not synthesize or require a model PASS")
    monkeypatch.setattr(authority.frame_semantic_review, "verify_episode",
                        _must_not_run_model_review)
    outcome = authority.verify_episode_review_authority(tmp_path)
    assert outcome["status"] == "USER_ACCEPTED", outcome
    assert outcome["machine_review_pass"] is False


def test_user_acceptance_cannot_bypass_active_image_generation(monkeypatch, tmp_path):
    rows, _ = _fixture(monkeypatch)
    rows["01"]["status"] = "REPAIRING"
    outcome = authority._sha_bound_direct_user_authority(tmp_path, rows)
    assert outcome["status"] == "BLOCKED"
    assert "unresolved generation state" in " ".join(outcome["errors"])
