"""Concept Ambition's independent native critic must not inherit Windows arg0 ACLs."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SYSTEM = ROOT / "episodes/_system"
if str(SYSTEM) not in sys.path:
    sys.path.insert(0, str(SYSTEM))

import concept_ambition as concept


def test_concept_critic_uses_isolated_user_home_without_bypassing_review(tmp_path, monkeypatch):
    episode = tmp_path / "episodes" / "00_独立篇" / "06_新篇"
    meta = episode / "meta"
    meta.mkdir(parents=True)
    candidates = meta / "concept-candidates.json"
    candidates.write_text('{"candidates":[]}', encoding="utf-8")
    command = ["codex", "exec", "--json", "-"]
    dispatched = []

    monkeypatch.setattr(concept, "ROOT", tmp_path)
    monkeypatch.setattr(concept, "required", lambda _ep: True)
    monkeypatch.setattr(concept, "validate_candidates", lambda _data: [])
    monkeypatch.setattr(concept, "sha256_file", lambda _path: "a" * 64)
    monkeypatch.setattr(concept.runtime_router, "detect", lambda: ("CODEX", "test"))
    monkeypatch.setattr(concept, "resolve_codex", lambda _path: Path("codex"))
    monkeypatch.setattr(concept, "prefix", lambda _path: ["codex"])
    monkeypatch.setattr(concept, "critic_prompt", lambda *_args: "real review prompt")
    monkeypatch.setattr(
        concept.runtime_provenance, "build_critic_provenance",
        lambda mode, *, attempt, log: {"mode": mode, "attempt": attempt, "log": log},
    )

    def fake_runner(argv, **kwargs):
        dispatched.append((argv, kwargs))
        # A successful transport is not itself a Review PASS. The evidence
        # must still flow through the canonical review finalizer.
        (meta / ".concept-ambition-review.candidate.json").write_text(
            json.dumps({"summary": {"passed": True}}, ensure_ascii=False),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0)

    finalized = []

    def finalize(ep, review, before, provenance):
        finalized.append((ep, review, before, provenance))
        return 0

    monkeypatch.setattr(concept.codex_user_runner, "run_model_codex", fake_runner)
    monkeypatch.setattr(concept, "_finalize_review", finalize)
    assert concept.run_critic(episode, 1, codex_raw="codex") == 0
    assert len(dispatched) == 1
    actual_command, options = dispatched[0]
    assert actual_command[0] == command[0]
    assert options["codex_home_mode"] == "isolated"
    assert options["task_type"] == "critic"
    assert options["input"] == "real review prompt"
    assert len(finalized) == 1
    assert finalized[0][2] == "a" * 64
    assert finalized[0][3]["mode"] == "CODEX"


def test_concept_critic_cli_failure_keeps_review_unlocked(tmp_path, monkeypatch):
    episode = tmp_path / "episodes" / "00_独立篇" / "06_新篇"
    (episode / "meta").mkdir(parents=True)
    (episode / "meta/concept-candidates.json").write_text(
        '{"candidates":[]}', encoding="utf-8"
    )
    monkeypatch.setattr(concept, "required", lambda _ep: True)
    monkeypatch.setattr(concept, "validate_candidates", lambda _data: [])
    monkeypatch.setattr(concept, "sha256_file", lambda _path: "a" * 64)
    monkeypatch.setattr(concept.runtime_router, "detect", lambda: ("CODEX", "test"))
    monkeypatch.setattr(concept, "resolve_codex", lambda _path: Path("codex"))
    monkeypatch.setattr(concept, "prefix", lambda _path: ["codex"])
    monkeypatch.setattr(concept, "critic_prompt", lambda *_args: "review")
    seen = []
    def fail_runner(_argv, **kwargs):
        seen.append(kwargs["codex_home_mode"])
        return SimpleNamespace(returncode=1)
    monkeypatch.setattr(concept.codex_user_runner, "run_model_codex", fail_runner)
    with pytest.raises(RuntimeError, match="concept critic failed rc=1"):
        concept.run_critic(episode, 1, codex_raw="codex")
    assert seen == ["isolated"]
    assert not (episode / "meta/concept-ambition-review.json").exists()


def test_windows_isolated_codex_home_must_use_user_runner_even_for_interactive_worker(monkeypatch):
    """Nested native Codex inside a scoped Worker must not reuse inaccessible arg0."""
    import os
    import subprocess
    import codex_user_runner as runner

    if os.name != "nt":
        pytest.skip("Windows nested Codex arg0 ACL regression")

    sent = []
    monkeypatch.setattr(runner, "bridge_required", lambda: False)
    monkeypatch.setattr(runner, "pin_windows_sandbox", lambda cmd: cmd)
    monkeypatch.setattr(runner, "resolve_provider_transport", lambda *args, **kw: None)
    monkeypatch.setattr(runner, "execute_codex", lambda task: sent.append(task) or runner.ExecResult(0, b"{}"))

    def forbid_direct(*args, **kwargs):
        raise AssertionError("isolated home must not spawn direct Codex")
    monkeypatch.setattr(subprocess, "run", forbid_direct)

    result = runner.run_codex(
        ["codex", "exec", "--json", "-"], input="review prompt", text=True,
        stdout=subprocess.PIPE, task_type="critic", codex_home_mode="isolated"
    )
    assert result.returncode == 0
    assert result.stdout == "{}"
    assert len(sent) == 1
    assert sent[0].codex_home_mode == "isolated"
