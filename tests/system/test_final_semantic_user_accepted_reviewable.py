"""User-accepted NEEDS_USER pixels remain reviewable, not automatically PASS."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

SYSTEM = Path(__file__).resolve().parents[2] / "episodes/_system"
if str(SYSTEM) not in sys.path:
    sys.path.insert(0, str(SYSTEM))
import frame_semantic_review as semantic


@pytest.fixture
def episode(monkeypatch, tmp_path):
    ep = tmp_path / "episode"
    ep.mkdir()
    asset = tmp_path / "candidate.png"
    asset.write_bytes(b"exact reviewed image")
    sha = hashlib.sha256(asset.read_bytes()).hexdigest()
    ledger = {"frames": {
        "09": {"status": "NEEDS_USER",
               "current_candidate": {"path": str(asset), "sha256": sha}},
        "48": {"status": "NEEDS_USER",
               "current_candidate": {"path": str(asset), "sha256": sha}},
    }}
    accepted = {"09", "48"}
    monkeypatch.setattr(semantic.production_ledger, "load_authority",
                        lambda _ep, **kwargs: ledger)
    monkeypatch.setattr(semantic.final_acceptance, "allows",
                        lambda _ep, scope, frame=None:
                        scope == "frame_semantic" and str(frame).zfill(2) in accepted)
    monkeypatch.setattr(semantic, "repo_path",
                        lambda raw, label, require_file=False: Path(raw))
    monkeypatch.setattr(semantic, "repo_rel", lambda path: str(path))
    monkeypatch.setattr(semantic, "current_generation_binding", lambda *args: {})
    return ep, asset, ledger, accepted


def test_explicit_acceptance_reviews_current_pixels_without_promoting(episode):
    ep, asset, ledger, accepted = episode
    rows = semantic.reviewable_frame_records(ep, require_files=True)
    assert [row["frame"] for row in rows] == ["09", "48"]
    assert all(row["source_kind"] == "user_accepted_candidate" for row in rows)
    assert all(row["sha256"] == hashlib.sha256(asset.read_bytes()).hexdigest()
               for row in rows)
    assert [ledger["frames"][key]["status"] for key in ("09", "48")] == [
        "NEEDS_USER", "NEEDS_USER"
    ]
    assert all("approved_asset" not in ledger["frames"][key] for key in ("09", "48"))


@pytest.mark.parametrize("case", ["not_accepted", "asset_missing", "sha_mismatch", "no_candidate", "wrong_status"])
def test_unapproved_or_drifted_pixels_are_not_reviewable(episode, case):
    ep, asset, ledger, accepted = episode
    if case == "not_accepted":
        accepted.remove("48")
    elif case == "asset_missing":
        asset.unlink()
    elif case == "sha_mismatch":
        ledger["frames"]["48"]["current_candidate"]["sha256"] = "f" * 64
    elif case == "no_candidate":
        ledger["frames"]["48"].pop("current_candidate")
    elif case == "wrong_status":
        ledger["frames"]["48"]["status"] = "TECH_FAILED"
    with pytest.raises((ValueError, FileNotFoundError)):
        semantic.reviewable_frame_records(ep, require_files=True)


def test_acceptance_does_not_convert_real_final_critic_fail_into_pass(episode, monkeypatch):
    ep, asset, ledger, accepted = episode
    reviewed = semantic.reviewable_frame_records(ep, require_files=True)
    data = {"frames": [
        {"frame": "09", "decision": "fail", "checks": {"story": False},
         "issue_codes": ["FRAME_SCENE_MISMATCH"], "notes": "visible defect"},
        {"frame": "48", "decision": "fail", "checks": {"story": False},
         "issue_codes": ["FRAME_SCENE_MISMATCH"], "notes": "visible defect"},
    ], "issue_codes": ["FRAME_SCENE_MISMATCH"], "summary": {"passed": False}}
    monkeypatch.setattr(semantic, "episode_contract_version", lambda _ep: "V1")
    monkeypatch.setattr(semantic, "directing_v3_required", lambda _ep: False)
    monkeypatch.setattr(semantic, "validate_candidate_gate_rows", lambda *args: [])
    monkeypatch.setattr(semantic.runtime_provenance, "validate_critic_provenance", lambda *args: [])
    monkeypatch.setattr(semantic, "review_source_bindings", lambda *args: {"frames": {}})
    monkeypatch.setattr(semantic, "phase4_contract", type("Stub", (), {"required": staticmethod(lambda ep: False)})())
    monkeypatch.setattr(semantic, "write_json", lambda *args: None)
    monkeypatch.setattr(semantic.production_ledger, "mark_review_needs_user", lambda *args, **kw: None)
    result = semantic._apply_candidate_gate(
        ep, data=data, reviewed=reviewed, contexts={},
        provenance={"review_source_bindings": {"frames": {}}},
        attempt=1)
    assert result == 2
    assert ledger["frames"]["09"]["status"] == "NEEDS_USER"
    assert ledger["frames"]["48"]["status"] == "NEEDS_USER"
