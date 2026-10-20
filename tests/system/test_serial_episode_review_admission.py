from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SYSTEM = ROOT / "episodes" / "_system"
if str(SYSTEM) not in sys.path:
    sys.path.insert(0, str(SYSTEM))

import story_narrative_form as narrative
import runtime_request
import story_review
import runtime_dag
import scoped_codex_worker
import runtime_failure_classifier
import validate_episode


def _request(title: str = "新故事", *, locked=True):
    return {
        "topic": {"title": title},
        "story_input": {
            "mode": "locked_story" if locked else "auto_create",
            "allow_structure_rewrite": not locked,
        },
    }


def test_default_and_explicit_narrative_forms():
    assert narrative.from_request(_request("独立故事")) == narrative.STANDALONE
    assert narrative.from_request(_request("疗愈所_第一集")) == narrative.SERIAL_EPISODE
    assert narrative.from_request(_request("疗愈所_第12集")) == narrative.SERIAL_EPISODE
    assert narrative.from_request(_request("疗愈所_第二集")) == narrative.SERIAL_EPISODE
    standalone = {**_request("疗愈所_第一集"), "narrative_form": narrative.STANDALONE}
    assert narrative.from_request(standalone) == narrative.STANDALONE
    serial = {**_request("独立故事"), "narrative_form": {"kind": narrative.SERIAL_EPISODE}}
    assert narrative.from_request(serial) == narrative.SERIAL_EPISODE
    for invalid in ("OTHER", {}, []):
        with pytest.raises(ValueError, match="INVALID_NARRATIVE_FORM"):
            narrative.from_request({**_request(), "narrative_form": invalid})


def test_new_runtime_requests_freeze_narrative_form():
    serial = runtime_request.compile_request("全自动做一篇「深渊疗愈所_第一集」。")
    assert serial["narrative_form"] == narrative.SERIAL_EPISODE
    standalone = runtime_request.compile_request("全自动做一篇「独立恐怖故事」。")
    assert standalone["narrative_form"] == narrative.STANDALONE
    explicit_serial = runtime_request.compile_request("全自动做一篇「神秘事件」，这是连续剧的分集作品。")
    assert explicit_serial["narrative_form"] == narrative.SERIAL_EPISODE
    standalone_override = runtime_request.compile_request("全自动做一篇「奇谈_第一集」，这次单篇完结。")
    assert standalone_override["narrative_form"] == narrative.STANDALONE
    assert not runtime_request.validate_request(serial)
    assert not runtime_request.validate_request(standalone)
    assert "invalid narrative_form" in runtime_request.validate_request({
        **serial, "narrative_form": "UNSUPPORTED",
    })


def test_serial_critic_uses_episode_payoff_not_full_series_resolution(monkeypatch):
    ep = ROOT / "episodes" / "synthetic_serial_critic"
    monkeypatch.setattr(narrative, "for_episode", lambda _ep: narrative.SERIAL_EPISODE)
    monkeypatch.setattr(story_review, "_locked_documentary_rubric", lambda _ep: False)
    monkeypatch.setattr(story_review.propagation_core_gate, "anomaly_applicable", lambda _ep: True)
    prompt = story_review.critic_prompt(
        ep, ep / "docs/story.md", ep / "docs/storyboard.md",
        ep / "meta/.story-semantic-review.candidate.json", 1,
    )
    assert "SERIAL EPISODE HARD RULES" in prompt
    assert "Do not demand full escape" in prompt
    assert "All unchanged hard_checks remain mandatory" in prompt
    assert '"hard_checks": {' in prompt
    assert "Do NOT demand rewriting the source merely to fit standalone" in prompt
    assert "The climax needs choice, cost" not in prompt


def test_standalone_critic_remains_strict(monkeypatch):
    ep = ROOT / "episodes" / "synthetic_standalone_critic"
    monkeypatch.setattr(narrative, "for_episode", lambda _ep: narrative.STANDALONE)
    monkeypatch.setattr(story_review, "_locked_documentary_rubric", lambda _ep: False)
    monkeypatch.setattr(story_review.propagation_core_gate, "anomaly_applicable", lambda _ep: True)
    prompt = story_review.critic_prompt(
        ep, ep / "docs/story.md", ep / "docs/storyboard.md",
        ep / "meta/.story-semantic-review.candidate.json", 1,
    )
    assert "SERIAL EPISODE HARD RULES" not in prompt
    assert '"hard_checks": {' in prompt
    assert "The climax needs choice, cost" in prompt


def test_serial_story_gate_still_requires_closure_and_real_review():
    gates = {
        "story": {
            "task_closed": False,
            "hook_frames": [1],
            "climax_frame": 2,
            "payoff_frame": 3,
        },
        "reviews": {"story": "pending"},
    }
    findings = []
    validate_episode.check_story_gate(
        gates, 3, findings, creative_gates_required=False,
        narrative_form=narrative.SERIAL_EPISODE,
    )
    reasons = {f.code: f.message for f in findings if f.level == "FAIL"}
    assert "task_not_closed" in reasons
    assert "本集" in reasons["task_not_closed"]
    assert "review_not_passed" in reasons
    gates["story"]["task_closed"] = True
    gates["reviews"]["story"] = "passed"
    findings = []
    validate_episode.check_story_gate(
        gates, 3, findings, creative_gates_required=False,
        narrative_form=narrative.SERIAL_EPISODE,
    )
    assert not [f for f in findings if f.level == "FAIL"]


def _build_source(tmp_path):
    episode = tmp_path / "episode"
    docs = episode / "docs"
    docs.mkdir(parents=True)
    contents = {
        "story.md": "original story",
        "storyboard.md": "original storyboard",
        "subtitles.yaml": "01: source",
    }
    for name, content in contents.items():
        (docs / name).write_text(content, encoding="utf-8")
    hashes = {name: hashlib.sha256((docs / name).read_bytes()).hexdigest()
              for name in contents}
    return episode, hashes


def _review(hashes, *, passed=False):
    return {
        "summary": {"passed": passed},
        "story_sha256": hashes["story.md"],
        "storyboard_sha256": hashes["storyboard.md"],
        "subtitle_source_sha256": hashes["subtitles.yaml"],
        "issue_codes": ["ENDING_PAYOFF_TOO_WEAK"] if not passed else [],
    }


def test_locked_failed_review_is_blocked_without_dispatch(tmp_path, monkeypatch):
    ep, hashes = _build_source(tmp_path)
    monkeypatch.setattr(narrative.runtime_request, "authority_for_episode", lambda _ep: _request("第一集"))
    monkeypatch.setattr(story_review, "load_review", lambda _ep: _review(hashes))
    monkeypatch.setattr(story_review, "story_paths", lambda _ep:
                        (ep / "docs/story.md", ep / "docs/storyboard.md"))
    block = narrative.failed_locked_review_block(ep)
    assert block == "LOCKED_STORY_REVIEW_FAILED_SOURCE_UNCHANGED_NEEDS_USER_DECISION"
    assert runtime_failure_classifier.classify(22, block).category == "HUMAN_REQUIRED"
    monkeypatch.setattr(narrative, "failed_locked_review_block", lambda _ep: block)
    # Targeted recovery must refuse before calling any scoped request or model.
    import product_review_adapter
    monkeypatch.setattr(product_review_adapter, "request_path",
                        lambda *_args, **_kwargs: pytest.fail("paid review reached"))
    rc, note = runtime_dag._run_targeted_review(
        ep, kind="story-semantic", attempt=7, codex=None,
        timeout=3, run_id=None, trace_id=None,
    )
    assert rc == 22 and note == block


def test_direct_scoped_worker_fence_prevents_model_dispatch(tmp_path, monkeypatch):
    ep, _hashes = _build_source(tmp_path)
    monkeypatch.setattr(narrative, "failed_locked_review_block",
                        lambda _ep: "LOCKED_STORY_REVIEW_FAILED_SOURCE_UNCHANGED_NEEDS_USER_DECISION")
    monkeypatch.setattr(scoped_codex_worker, "resolved_model",
                        lambda *_args: pytest.fail("direct model admission reached"))
    rc, reason = scoped_codex_worker.run_step(ep, "CREATIVE_STORY")
    assert rc == 22
    assert "NEEDS_USER_DECISION" in reason


def test_locked_failed_review_after_source_drift_needs_explicit_revision(tmp_path, monkeypatch):
    ep, hashes = _build_source(tmp_path)
    monkeypatch.setattr(narrative.runtime_request, "authority_for_episode", lambda _ep: _request("第一集"))
    monkeypatch.setattr(story_review, "load_review", lambda _ep: _review(hashes))
    monkeypatch.setattr(story_review, "story_paths", lambda _ep:
                        (ep / "docs/story.md", ep / "docs/storyboard.md"))
    (ep / "docs/story.md").write_text("changed without revision authority", encoding="utf-8")
    assert narrative.failed_locked_review_block(ep) == (
        "LOCKED_STORY_FAILED_REVIEW_SOURCE_DRIFT_NEEDS_EXPLICIT_REVISION_AUTHORITY"
    )


def test_success_or_unlocked_stories_are_not_blocked(tmp_path, monkeypatch):
    ep, hashes = _build_source(tmp_path)
    monkeypatch.setattr(story_review, "load_review", lambda _ep: _review(hashes))
    monkeypatch.setattr(narrative.runtime_request, "authority_for_episode",
                        lambda _ep: _request("独立篇", locked=False))
    assert narrative.failed_locked_review_block(ep) is None
    monkeypatch.setattr(narrative.runtime_request, "authority_for_episode",
                        lambda _ep: _request("第一集"))
    monkeypatch.setattr(story_review, "load_review", lambda _ep: _review(hashes, passed=True))
    assert narrative.failed_locked_review_block(ep) is None
