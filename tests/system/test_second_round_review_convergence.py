"""Two-stage content review closure is the same through all callers.

This reproduces the old implicit forced-PASS after the first authorized repair,
which accepted a SHA-bound image WITHOUT checking its newly failed semantics.
"""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import sys
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"episodes/_system"))
import production_ledger  # initialize the ledger facade before its internal modules
import production_ledger_run as ledger
import production_ledger_manage as manage
import repair_aggregator
import auto_repair_enqueue


def ready(*,status="REPAIR_READY",used=1,has_candidate=True):
    return {"status":status,"content_repairs_used":used,
            "current_candidate":{"path":"media/candidates/scheduled/02.png","sha256":"a"*64}
            if has_candidate else None,
            "reviews":[],"attempts":[{"result":"success","candidate":{"sha256":"a"*64}}]}


@pytest.mark.parametrize("issue",[
    "SHOT_GRAMMAR_REPEAT",         # soft: not permission to bypass evidence
    "LIGHTING_DESIGN_MISMATCH",    # maybe soft in this episode
    "KEY_PROP_DRIFT",              # story semantics: hard
    "IDENTITY_DRIFT",
    "ANATOMY_DISTORTION",
    "POV_ILLEGAL",
    "FRAME_CONTRACT_MISMATCH",
])
def test_direct_content_review_and_formal_review_both_keep_failed_repair_needs_user(issue):
    frame=ready()
    data={"policy":{"max_content_repairs_per_frame":1},"frames":{"02":frame}}
    with (patch.object(ledger,"episode_dir",return_value=Path("episode")),
          patch.object(ledger,"get_ledger",return_value=(Path("ledger.json"),data)),
          patch.object(ledger,"save_json") as save,
          patch.object(manage,"force_pass_content_exhaustion") as forced):
        ledger.cmd_review(SimpleNamespace(episode_dir="episode",frame="02",
                          decision="repair",notes=issue))
        assert frame["status"]=="NEEDS_USER"
        assert frame["reviews"][-1]["decision"]=="repair"
        assert not frame.get("forced_passes")
        assert not any(row.get("forced_pass") for row in frame["reviews"])
        forced.assert_not_called()
        assert save.call_count==1


def test_exhausted_first_candidate_also_cannot_be_silently_passed():
    frame=ready(status="ORIGINAL_READY",used=1)
    data={"policy":{"max_content_repairs_per_frame":1},"frames":{"02":frame}}
    with (patch.object(ledger,"episode_dir",return_value=Path("episode")),
          patch.object(ledger,"get_ledger",return_value=(Path("ledger.json"),data)),
          patch.object(ledger,"save_json"),
          patch.object(manage,"force_pass_content_exhaustion") as forced):
        ledger.cmd_review(SimpleNamespace(episode_dir="episode",frame="02",
                                          decision="repair",notes="failed actual-pixel critique"))
    assert frame["status"]=="NEEDS_USER"
    forced.assert_not_called()


def test_soft_acceptance_requires_a_separate_sha_bound_review_not_plain_critic_notes():
    frame=ready()
    data={"policy":{"max_content_repairs_per_frame":1},"frames":{"02":frame}}
    with (patch.object(ledger,"episode_dir",return_value=Path("episode")),
          patch.object(ledger,"get_ledger",return_value=(Path("ledger.json"),data)),
          patch.object(ledger,"save_json"),
          patch.object(manage,"force_pass_content_exhaustion") as forced):
        ledger.cmd_review(SimpleNamespace(episode_dir="episode",frame="02",
                            decision="repair",notes="soft-only, pass it automatically"))
    assert frame["status"]=="NEEDS_USER"
    forced.assert_not_called()


def test_review_pass_still_passes_and_does_not_consume_third_repair():
    frame=ready()
    data={"policy":{"max_content_repairs_per_frame":1},"frames":{"02":frame}}
    with (patch.object(ledger,"episode_dir",return_value=Path("episode")),
          patch.object(ledger,"get_ledger",return_value=(Path("ledger.json"),data)),
          patch.object(ledger,"save_json"),
          patch.object(manage,"force_pass_content_exhaustion") as forced):
        ledger.cmd_review(SimpleNamespace(episode_dir="episode",frame="02",
                                          decision="pass",notes="verified all checks pass"))
    assert frame["status"]=="PASSED"
    assert frame["content_repairs_used"]==1
    forced.assert_not_called()


def test_legacy_exhaustion_fallback_itself_is_not_a_backdoor():
    # Even callers that import the old facade function must not be able to
    # force a failed review to PASS merely because a file and SHA exist.
    with pytest.raises(ValueError,match="review|evidence|disabled|forbid|retired"):
        manage.force_pass_content_exhaustion(
            Path("episode"),"02","just accept after budget exhaustion")


def test_one_automatic_wave_and_user_exception_unchanged():
    assert repair_aggregator.MAX_AUTOMATIC_REPAIR_WAVES==1
    src=(ROOT/"episodes/_system/production_ledger_manage.py").read_text(encoding="utf-8")
    assert 'def cmd_authorize_user_exception_repair(' in src
    assert 'direct user approval text is required' in src


def test_both_review_callers_preserve_explicit_fail_closed_flag():
    import inspect
    assert "prevent_exhaustion_force_pass=True" in inspect.getsource(auto_repair_enqueue.enqueue)
    import frame_semantic_review
    assert "prevent_exhaustion_force_pass=True" in inspect.getsource(frame_semantic_review._apply_candidate_gate)
