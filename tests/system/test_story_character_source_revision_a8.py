"""Fail-closed Character Story source revision and independent #8 reviewer epoch."""
from __future__ import annotations

import json
import hashlib
import sys
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SYSTEM = ROOT / "episodes/_system"
if str(SYSTEM) not in sys.path:
    sys.path.insert(0, str(SYSTEM))

import character_contract
import story_review
import runtime_provenance
from story_os_contract import story_os_version


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _setup(tmp_path):
    ep = tmp_path / "episode"
    (ep / "docs").mkdir(parents=True)
    (ep / "meta").mkdir()
    story = ep / "docs/story.md"
    board = ep / "docs/storyboard.md"
    captions = ep / "docs/subtitles.yaml"
    story.write_text("李程与五名普通同学在民宿聚会，走入果园，沿水沟搀扶伤者，最后选择留下相机。", encoding="utf-8")
    board.write_text("1. 李程决定留下相机，加入搀扶伤员，其他朋友沿水沟走。", encoding="utf-8")
    captions.write_text("voice_card:\n  tone: 口语\nframes:\n" +
                        "".join(f"  {i}: \"沿水沟离开 {i}\"\n" for i in range(1, 21)) +
                        "silent_frames: []\n", encoding="utf-8")
    (ep / "meta/release-manifest.json").write_text(
        json.dumps({"release": {"body_frame_count": 20}}), encoding="utf-8")
    old_story, old_board, old_contract, prior_review_sha = ("a" * 64, "b" * 64,
                                                              "c" * 64, "d" * 64)
    prior = {"summary": {"passed": False},
             "issue_codes": ["STORY_COMPREHENSION_FAIL", "CAUSAL_CHAIN_BROKEN", "CLIMAX_PAYOFF_WEAK"],
             "critic_provenance": {"attempt": 7},
             "story_sha256": old_story, "storyboard_sha256": old_board}
    contract = {"status": "LOCKED",
                "cast": {"members": [{"name": "李程"}]},
                "final_story_review": {"story_sha256": old_story}}
    evidence = {"schema_version": 1, "previous_contract_authority_sha256": old_contract,
                "previous_review_authority_sha256": prior_review_sha,
                "previous_story_sha256": old_story,
                "story_sha256": _sha(story), "storyboard_sha256": _sha(board),
                "subtitle_sha256": _sha(captions),
                "no_anomaly_test": {"pass": True, "story_sha256": _sha(story),
                    "ordinary_day_plan": "朋友们在普通民宿聚会吃饭拍合影然后正常返校。",
                    "review_reason": "即使完全没有怪事，他们依旧会聚会拍照、散步、照顾受伤朋友并下山。"}}
    attestation = ep / "meta/character-source-revision-attestation-a8.json"
    attestation.write_text(json.dumps(evidence, ensure_ascii=False), encoding="utf-8")
    return ep, prior, contract, evidence, attestation, (old_contract, prior_review_sha)


def _mock_dependencies(monkeypatch, prior, current, authorities):
    state = {"contract": deepcopy(current), "sha": authorities[0], "calls": 0}
    import episode_state_persistence
    monkeypatch.setattr(episode_state_persistence, "load", lambda ep: {"current_state": "IDEA_LOCKED"})
    monkeypatch.setattr(story_review, "load_review", lambda ep: prior)
    monkeypatch.setattr(story_review, "review_authority_sha256", lambda ep: authorities[1])
    monkeypatch.setattr(character_contract, "load", lambda ep: state["contract"])
    monkeypatch.setattr(character_contract, "authority_sha256", lambda ep: state["sha"])
    monkeypatch.setattr(character_contract, "validate", lambda ep, **kw: [])
    def fake_save(ep, data, *, expected_sha256=None):
        assert expected_sha256 == authorities[0]
        state["calls"] += 1
        state["contract"] = deepcopy(data)
        state["sha"] = "f" * 64
    monkeypatch.setattr(character_contract, "save", fake_save)
    return state


def test_relock_repaired_story_is_sha_bound_cas_and_one_time(tmp_path, monkeypatch):
    ep, prior, current, evidence, attestation, auth = _setup(tmp_path)
    state = _mock_dependencies(monkeypatch, prior, current, auth)
    result = character_contract.source_revision_lock(ep, "meta/" + attestation.name)
    assert result["status"] == "LOCKED_REVISED"
    assert state["calls"] == 1
    assert state["contract"]["final_story_review"]["story_sha256"] == evidence["story_sha256"]
    assert state["contract"]["source_revision"]["previous_review_authority_sha256"] == auth[1]
    assert (ep / "meta/runtime/character-story-source-revision-a8.json").is_file()
    with pytest.raises(ValueError, match="ALREADY_USED"):
        character_contract.source_revision_lock(ep, "meta/" + attestation.name)
    assert state["calls"] == 1


@pytest.mark.parametrize("defect", ["unchanged_source", "prior_passed", "contract_sha", "attestation_sha", "story_stage"])
def test_relock_refuses_stale_and_false_evidence(tmp_path, monkeypatch, defect):
    ep, prior, current, evidence, attestation, auth = _setup(tmp_path)
    state = _mock_dependencies(monkeypatch, prior, current, auth)
    if defect == "unchanged_source":
        current["final_story_review"]["story_sha256"] = evidence["story_sha256"]
        prior["story_sha256"] = evidence["story_sha256"]
        state["contract"] = current
        evidence["previous_story_sha256"] = evidence["story_sha256"]
    elif defect == "prior_passed":
        prior["summary"]["passed"] = True
    elif defect == "contract_sha":
        evidence["previous_contract_authority_sha256"] = "0" * 64
    elif defect == "attestation_sha":
        evidence["story_sha256"] = "1" * 64
    elif defect == "story_stage":
        import episode_state_persistence
        monkeypatch.setattr(episode_state_persistence, "load", lambda ep: {"current_state": "STORYBOARD_LOCKED"})
    attestation.write_text(json.dumps(evidence, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError):
        character_contract.source_revision_lock(ep, "meta/" + attestation.name)
    assert state["calls"] == 0
    assert not (ep / "meta/runtime/character-story-source-revision-a8.json").exists()


def test_first_independent_failed_review_can_repair_story_once(tmp_path, monkeypatch):
    ep, prior, current, evidence, attestation, auth = _setup(tmp_path)
    prior["critic_provenance"] = {"attempt": 1, "isolated_session": True}
    prior["issue_codes"] = ["CAUSAL_CHAIN_BROKEN", "MECHANISM_CONTRADICTION"]
    prior["subtitle_source_sha256"] = "9" * 64
    state = _mock_dependencies(monkeypatch, prior, current, auth)
    result = character_contract.source_revision_lock(ep, "meta/" + attestation.name)
    assert result["status"] == "LOCKED_REVISED"
    revision = state["contract"]["source_revision"]
    assert revision["scope"] == "CHARACTER_STORY_SOURCE_REPAIR_AFTER_FAILED_A1"
    assert revision["previous_review_attempt"] == 1
    assert revision["previous_review_authority_sha256"] == auth[1]
    assert (ep / "meta/runtime/character-story-source-revision-a2.json").is_file()
    assert state["calls"] == 1
    with pytest.raises(ValueError, match="ALREADY_USED"):
        character_contract.source_revision_lock(ep, "meta/" + attestation.name)


@pytest.mark.parametrize("defect", ["not_isolated", "not_failed", "no_issues",
                                     "subtitle_unchanged", "prior_board_drift", "wrong_attempt"])
def test_first_review_repair_rejects_invalid_authority(tmp_path, monkeypatch, defect):
    ep, prior, current, evidence, attestation, auth = _setup(tmp_path)
    prior["critic_provenance"] = {"attempt": 1, "isolated_session": True}
    prior["issue_codes"] = ["CAUSAL_CHAIN_BROKEN"]
    prior["subtitle_source_sha256"] = "9" * 64
    state = _mock_dependencies(monkeypatch, prior, current, auth)
    if defect == "not_isolated":
        prior["critic_provenance"]["isolated_session"] = False
    elif defect == "not_failed":
        prior["summary"]["passed"] = True
    elif defect == "no_issues":
        prior["issue_codes"] = []
    elif defect == "subtitle_unchanged":
        prior["subtitle_source_sha256"] = evidence["subtitle_sha256"]
    elif defect == "prior_board_drift":
        evidence["previous_story_sha256"] = "f" * 64
    elif defect == "wrong_attempt":
        prior["critic_provenance"]["attempt"] = 2
    attestation.write_text(json.dumps(evidence, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError):
        character_contract.source_revision_lock(ep, "meta/" + attestation.name)
    assert state["calls"] == 0


def test_review_a8_requires_revised_character_authority(tmp_path, monkeypatch):
    ep, prior, current, evidence, attestation, auth = _setup(tmp_path)
    revision = {
        "scope": "CHARACTER_STORY_SOURCE_REPAIR_AFTER_FAILED_A7",
        "previous_review_authority_sha256": auth[1],
        "previous_story_sha256": prior["story_sha256"],
        "story_sha256": evidence["story_sha256"],
        "storyboard_sha256": evidence["storyboard_sha256"],
        "subtitle_sha256": evidence["subtitle_sha256"],
        "attestation_sha256": _sha(attestation),
    }
    contract = {"status": "LOCKED", "source_revision": revision}
    monkeypatch.setattr(story_review, "_locked_documentary_rubric", lambda ep: False)
    monkeypatch.setattr(story_review, "load_review", lambda ep: prior)
    monkeypatch.setattr(story_review, "review_authority_sha256", lambda ep: auth[1])
    monkeypatch.setattr(story_review, "story_paths", lambda ep: (ep / "docs/story.md", ep / "docs/storyboard.md"))
    monkeypatch.setattr(character_contract, "load", lambda ep: contract)
    monkeypatch.setattr(character_contract, "validate", lambda ep, **kw: [])
    monkeypatch.setattr(character_contract, "authority_sha256", lambda ep: "e" * 64)
    grant = story_review._authorize_character_source_repair(ep, attempt=8)
    assert grant["previous_review_sha256"] == auth[1]
    assert grant["new_character_authority_sha256"] == "e" * 64
    assert grant["story_sha256"] == evidence["story_sha256"]
    assert grant["global_review_attempt"] == 8
    with pytest.raises(RuntimeError, match="already authorized"):
        story_review._authorize_character_source_repair(ep, attempt=8)


def test_a8_provenance_is_not_a_pass_without_real_review():
    sha = "a" * 64
    prov = runtime_provenance.build_critic_provenance(
        "CODEX", attempt=8, allow_user_continuation_attempt=True)
    prov.update({
        "review_scope": "CHARACTER_STORY_SOURCE_REPAIR_AFTER_FAIL",
        "review_epoch": 7, "epoch_attempt": 1,
        "previous_review_sha256": sha,
        "previous_story_sha256": "b" * 64,
        "previous_storyboard_sha256": "c" * 64,
        "new_character_authority_sha256": sha,
        "character_attestation_sha256": sha,
        "current_rubric_sha256": sha,
        "subtitle_source_sha256": sha,
    })
    data = {
        "schema_version": 1, "story_os_version": story_os_version(),
        "story_sha256": sha, "storyboard_sha256": sha,
        "revision_count": 7, "critic_provenance": prov,
        "subtitle_source_sha256": sha,
        "contract": {k: "x" for k in story_review.CONTRACT_FIELDS},
        "blind_retell": {k: "x" for k in story_review.BLIND_FIELDS},
        "hard_checks": {k: True for k in story_review.HARD_CHECKS},
        "issue_codes": [], "summary": {"passed": True},
    }
    data["contract"]["ending_recontextualization"] = ["a", "b", "c"]
    assert story_review.validate_payload(data, story_sha=sha, storyboard_sha=sha,
                                         version=story_os_version()) == []
    del prov["new_character_authority_sha256"]
    assert story_review.validate_payload(data, story_sha=sha, storyboard_sha=sha,
                                         version=story_os_version())
