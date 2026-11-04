"""Only complete SHA-bound pixel reviews can survive a Codex transport timeout."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "episodes/_system"))
import production_batch_review as review


@pytest.fixture
def sample(monkeypatch, tmp_path):
    ep = tmp_path / "ep"
    ep.mkdir()
    source = tmp_path / "image.png"
    source.write_bytes(b"known-image-sha")
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    row = {"frame": 48, "output_path": str(source), "status": "generated",
           "batch_id": "SINGLE_48"}
    binding = {"candidate_sha256": source_sha, "frame_contract_sha256": "b" * 64}
    review.REVIEW_DIR.mkdir if False else None
    monkeypatch.setattr(review, "ROOT", tmp_path)
    monkeypatch.setattr(review, "batch_items", lambda ep, batch: [row])
    monkeypatch.setattr(review, "review_contracts", lambda ep, rows: [
        {"frame": "48", **binding, "prompt_contract": {}}])
    current = dict(binding)
    monkeypatch.setattr(review, "unit_binding", lambda ep, item: dict(current))
    monkeypatch.setattr(review.codex_user_runner, "workspace_path",
                        lambda prefix: (tmp_path / "staging"))
    (tmp_path / "staging").mkdir()
    monkeypatch.setattr(review.codex_critic_runner, "resolve_codex",
                        lambda x: Path("codex.cmd"))
    monkeypatch.setattr(review.runtime_router, "vision_review_model",
                        lambda: "gpt-6")
    monkeypatch.setattr(review.runtime_router, "vision_review_effort",
                        lambda kind: "high")
    observations = []
    def recover(ep, batch_id, *, rows, candidate, attempt,
                process_returncode, basis):
        bound = review._complete_bound_candidate(ep, batch_id, rows, candidate)
        if bound is None:
            return None
        observations.append(basis)
        return bound
    monkeypatch.setattr(review, "_recover_complete_candidate", recover)
    unit = {"frame": "48", **binding,
            "decision": "REPAIR_NOW", "checks": {"whole_image": "fail"},
            "unresolved": [], "issue_codes": ["STORY_BEAT_NOT_VISIBLE"],
            "reason": "visible evidence"}
    return ep, current, observations, unit


@pytest.mark.parametrize("case", ["valid_response", "valid_candidate", "incomplete", "stale_sha", "source_drift"])
def test_timeout_only_recovers_exact_complete_review(sample, monkeypatch, case):
    ep, current, observations, unit = sample
    if case == "stale_sha":
        unit["candidate_sha256"] = "0" * 64
    payload = {"batch_id": "SINGLE_48", "frames": [unit]}
    def timed_out(*args, **kwargs):
        if case == "valid_candidate":
            review.write_json(review.candidate_path(ep, "SINGLE_48"), payload)
        elif case in {"valid_response", "stale_sha", "source_drift"}:
            response = kwargs["output_path"]
            response.parent.mkdir(parents=True, exist_ok=True)
            response.write_text(json.dumps(payload), encoding="utf-8")
        if case == "source_drift":
            current["candidate_sha256"] = "f" * 64
        raise review.codex_user_runner.CodexUserRunnerTimeout(["codex"], 2)
    monkeypatch.setattr(review.codex_critic_runner, "launch", timed_out)
    if case in {"valid_response", "valid_candidate"}:
        result = review.run_codex_review(ep, "SINGLE_48", timeout=2)
        assert result == payload
        assert observations == ["persisted_complete_candidate_after_transport_timeout"]
    elif case == "source_drift":
        with pytest.raises(RuntimeError, match="bindings drifted"):
            review.run_codex_review(ep, "SINGLE_48", timeout=2)
        assert observations == []
    else:
        with pytest.raises(review.codex_user_runner.CodexUserRunnerTimeout):
            review.run_codex_review(ep, "SINGLE_48", timeout=2)
        assert observations == []
