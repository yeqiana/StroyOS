from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SYSTEM = ROOT / "episodes" / "_system"
if str(SYSTEM) not in sys.path:
    sys.path.insert(0, str(SYSTEM))

import story_narrative_form
import story_review
import story_serial_recheck as serial
import runtime_request
import runtime_driver
import codex_critic_runner
import runtime_provenance
from story_os_contract import story_os_version


def _fixture(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    standard = tmp_path / "standards" / "\u5236\u4f5c\u89c4\u8303_\u6b63\u5f0f\u7248.md"
    standard.parent.mkdir()
    standard.write_text("single series serialized review", encoding="utf-8")
    episode = tmp_path / "episodes" / "01_serial"
    docs = episode / "docs"
    docs.mkdir(parents=True)
    story = docs / "story.md"
    board = docs / "storyboard.md"
    captions = docs / "subtitles.yaml"
    for path in (story, board, captions):
        path.write_text(path.name, encoding="utf-8")
    sources = {key: serial.digest(path) for key, path in
               (("story_sha256", story), ("storyboard_sha256", board),
                ("subtitle_source_sha256", captions))}
    fail = {"summary": {"passed": False},
            "critic_provenance": {"attempt": 1, "review_scope": "STANDARD"},
            **sources,
            "issue_codes": ["ENDING_PAYOFF_TOO_WEAK"]}
    request = {"topic": {"title": "Episode \u7b2c\u4e00\u96c6"},
               "narrative_form": "SERIAL_EPISODE",
               "story_input": {"mode": "locked_story", "allow_structure_rewrite": False}}
    monkeypatch.setattr(story_review, "ROOT", tmp_path)
    monkeypatch.setattr(story_review, "story_paths", lambda _ep: (story, board))
    monkeypatch.setattr(story_review, "load_review", lambda _ep: fail)
    monkeypatch.setattr(runtime_request, "authority_for_episode", lambda _ep: request)
    monkeypatch.setattr(serial, "_previous_exists", lambda _ep, _sha: True)
    monkeypatch.setattr(runtime_driver, "status", lambda _ep: {"driver_state": "EXITED"})
    return episode, sources, fail


def test_recheck_requires_persisted_failed_authority_and_unchanged_locked_source(tmp_path, monkeypatch):
    ep, sources, old = _fixture(tmp_path, monkeypatch)
    info = serial.plan(ep)
    assert info["status"] == "ONE_SHOT_SERIAL_REVIEW_READY"
    assert info["can_dispatch_model"] is True
    assert info["model_calls"] == info["sql_writes"] == 0
    assert info["previous_review_sha256"] == serial._prior_digest(old)
    (ep / "docs/storyboard.md").write_text("new unauthorized storyboard", encoding="utf-8")
    assert serial.plan(ep)["status"] == "PREVIOUS_REVIEW_SOURCE_SHA_DRIFT"


def test_review_reservation_is_atomic_and_nonreplayable(tmp_path, monkeypatch):
    ep, sources, old = _fixture(tmp_path, monkeypatch)
    plan = serial.plan(ep)
    with pytest.raises(RuntimeError, match="PREVIOUS_FAIL_SHA_MISMATCH"):
        serial.authorize(ep, previous_sha="f" * 64)
    assert not (ep / serial.EPOCH_REL).exists()
    reservation = serial.authorize(ep, previous_sha=plan["previous_review_sha256"])
    assert reservation["story_sha256"] == sources["story_sha256"]
    assert reservation["review_scope"] == serial.REVIEW_SCOPE
    assert serial.validate_epoch(ep, {
        "attempt": 12, "review_scope": serial.REVIEW_SCOPE,
        "direct_user_continuation_review": True,
        "review_epoch": 11, "epoch_attempt": 1,
        "previous_review_sha256": reservation["previous_review_sha256"],
        "current_rubric_sha256": reservation["current_rubric_sha256"],
        "subtitle_source_sha256": reservation["subtitle_source_sha256"],
    })
    assert serial.plan(ep)["status"] == "SERIAL_RECHECK_ALREADY_RESERVED_NO_RETRY"
    with pytest.raises(RuntimeError, match="ALREADY_RESERVED_NO_RETRY"):
        serial.authorize(ep, previous_sha=plan["previous_review_sha256"])
    assert story_review.load_review(ep) is old


def test_serial_recheck_cannot_dispatch_again_after_unknown(tmp_path, monkeypatch):
    ep, _, old = _fixture(tmp_path, monkeypatch)
    check = serial.plan(ep)
    launched = []
    monkeypatch.setattr(story_review, "resolve_codex", lambda _raw: Path("fake-codex"))
    monkeypatch.setattr(story_review, "critic_prompt",
                        lambda *_args: "SERIAL EPISODE HARD RULES (STORY_OS_SERIAL_EPISODE)")
    def fail_model(*_args, **_kwargs):
        launched.append(True)
        return SimpleNamespace(returncode=124)
    monkeypatch.setattr(codex_critic_runner, "launch", fail_model)
    with pytest.raises(RuntimeError, match="RESULT_UNKNOWN_NO_RETRY"):
        serial.run(ep, previous_sha=check["previous_review_sha256"], codex_raw=None)
    assert len(launched) == 1
    assert (ep / serial.EPOCH_REL).exists()
    with pytest.raises(RuntimeError, match="ALREADY_RESERVED_NO_RETRY"):
        serial.run(ep, previous_sha=check["previous_review_sha256"], codex_raw=None)
    assert len(launched) == 1
    assert (old["summary"]["passed"]) is False


def test_serial_a12_payload_still_requires_every_hard_check():
    sha = "a" * 64
    provenance = runtime_provenance.build_critic_provenance(
        "CODEX", attempt=12, allow_user_continuation_attempt=True)
    provenance.update({
        "review_scope": serial.REVIEW_SCOPE,
        "review_epoch": 11,
        "epoch_attempt": 1,
        "previous_review_sha256": "b" * 64,
        "current_rubric_sha256": "c" * 64,
        "subtitle_source_sha256": "d" * 64,
    })
    payload = {
        "schema_version": 1,
        "story_os_version": story_os_version(),
        "story_sha256": sha, "storyboard_sha256": sha,
        "subtitle_source_sha256": "d" * 64,
        "revision_count": 11, "critic_provenance": provenance,
        "contract": {key: "evidence" for key in story_review.CONTRACT_FIELDS},
        "blind_retell": {key: "actual arc" for key in story_review.BLIND_FIELDS},
        "hard_checks": {key: True for key in story_review.HARD_CHECKS},
        "summary": {"passed": True}, "issue_codes": [],
    }
    payload["contract"]["ending_recontextualization"] = ["first fact", "second fact", "third fact"]
    assert story_review.validate_payload(
        payload, story_sha=sha, storyboard_sha=sha, version=story_os_version()) == []
    payload["hard_checks"]["mechanism_consistency"] = False
    assert any("mechanism_consistency" in item for item in
               story_review.validate_payload(
                   payload, story_sha=sha, storyboard_sha=sha,
                   version=story_os_version()))


def test_recheck_disallowed_for_standalone_or_unlocked(tmp_path, monkeypatch):
    ep, _, old = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(story_narrative_form, "from_request", lambda _req: "STANDALONE")
    assert serial.plan(ep)["status"] == "NOT_A_SERIAL_EPISODE"
