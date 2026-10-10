"""Recent-5 projection never replaces the Story Critic or four-lock evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SYSTEM = ROOT / "episodes/_system"
if str(SYSTEM) not in sys.path:
    sys.path.insert(0, str(SYSTEM))
import release_preflight as release


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _example(tmp_path):
    ep = tmp_path / "episodes/00_独立篇/06_新篇"
    fp = ep / "meta/episode-fingerprint.json"
    _write(fp, {"episode_id": "00-06", "title": "新篇", "dimensions": {}})
    _write(ep / "meta/release-manifest.json", {"episode": {"id": "00-06"}})
    review = {
        "decision": "pass", "mechanism_veto": False, "comparison_count": 5,
        "episode_id": "00-06", "candidate_fingerprint_sha256": _sha(fp),
        "registry_sha256": "a" * 64, "semantic_review_sha256": "b" * 64,
    }
    _write(ep / "meta/recent5-review.json", review)
    _write(ep / "meta/story-gates.json", {
        "story": {
            "recent5_checked": False, "four_locks_diff_count": 0,
            "mechanism_skin_swap_veto": True, "task_closed": False,
        },
        "reviews": {"story": "pending"},
    })
    return ep, review


def test_only_sha_verified_recent5_is_projected(tmp_path, monkeypatch, capsys):
    ep, review = _example(tmp_path)
    # Production ep_path strictly rejects paths outside the repo. The test
    # fixture lives under pytest tmp_path; substitute only path resolution.
    # Do not loosen the actual CLI's repository-boundary admission.
    monkeypatch.setattr(release, "ep_path", lambda raw: Path(raw).resolve())
    monkeypatch.setattr(release, "verify_recent5_evidence", lambda ep: [])
    args = argparse.Namespace(episode_dir=str(ep))
    assert release.cmd_project_verified_recent5(args) == 0
    result = json.loads((ep / "meta/story-gates.json").read_text(encoding="utf-8"))
    assert result["story"]["recent5_checked"] is True
    assert result["story"]["mechanism_skin_swap_veto"] is False
    assert result["story"]["four_locks_diff_count"] == 0
    assert result["story"]["task_closed"] is False
    assert result["reviews"]["story"] == "pending"
    assert result["release_evidence_bindings"]["recent5"]["review_sha256"] == _sha(
        ep / "meta/recent5-review.json"
    )
    assert release.cmd_project_verified_recent5(args) == 0


@pytest.mark.parametrize("tamper", ["invalid_review", "not_pass", "wrong_fp", "wrong_episode"])
def test_refuses_incomplete_or_unbound_recent5(tmp_path, monkeypatch, tamper):
    ep, review = _example(tmp_path)
    # Production ep_path strictly rejects paths outside the repo. The test
    # fixture lives under pytest tmp_path; substitute only path resolution.
    # Do not loosen the actual CLI's repository-boundary admission.
    monkeypatch.setattr(release, "ep_path", lambda raw: Path(raw).resolve())
    monkeypatch.setattr(release, "verify_recent5_evidence",
                        lambda ep: ["unverified evidence"] if tamper == "invalid_review" else [])
    if tamper == "not_pass":
        review["decision"] = "block_or_redesign"
    if tamper == "wrong_fp":
        review["candidate_fingerprint_sha256"] = "f" * 64
    if tamper == "wrong_episode":
        review["episode_id"] = "00-05"
    _write(ep / "meta/recent5-review.json", review)
    with pytest.raises(ValueError):
        release.cmd_project_verified_recent5(argparse.Namespace(episode_dir=str(ep)))
    gate = json.loads((ep / "meta/story-gates.json").read_text(encoding="utf-8"))
    assert gate["story"]["recent5_checked"] is False
    assert gate["reviews"]["story"] == "pending"


def test_refuses_stale_existing_binding(tmp_path, monkeypatch):
    ep, review = _example(tmp_path)
    # Production ep_path strictly rejects paths outside the repo. The test
    # fixture lives under pytest tmp_path; substitute only path resolution.
    # Do not loosen the actual CLI's repository-boundary admission.
    monkeypatch.setattr(release, "ep_path", lambda raw: Path(raw).resolve())
    monkeypatch.setattr(release, "verify_recent5_evidence", lambda ep: [])
    args = argparse.Namespace(episode_dir=str(ep))
    assert release.cmd_project_verified_recent5(args) == 0
    gate_path = ep / "meta/story-gates.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    gate["release_evidence_bindings"]["recent5"]["review_sha256"] = "f" * 64
    _write(gate_path, gate)
    with pytest.raises(ValueError, match="BINDING_DRIFT"):
        release.cmd_project_verified_recent5(args)
