"""The paid Critic CLI must recheck live authority INSIDE the entrypoint."""
import sys
import types
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"episodes"/"_system"))
import story_review


def test_real_paid_entrypoint_refuses_before_reserving_epoch_or_launch(monkeypatch):
    monkeypatch.setitem(sys.modules,"storyos_autonomy_r12_critic_preflight",
        types.SimpleNamespace(inspect=lambda ref:{
            "may_start_new_text_review":False,"status":"IMAGE_ATTEMPT_AUTHORITY_UNVERIFIED"}))
    monkeypatch.setattr(story_review.story_review_rubric_migration,"authorize",
        lambda *args,**kwargs: (_ for _ in ()).throw(AssertionError("ticket unexpectedly created")))
    monkeypatch.setattr(story_review.codex_critic_runner,"launch",
        lambda *args,**kwargs: (_ for _ in ()).throw(AssertionError("MODEL CALLED")))
    ep=ROOT/"episodes/15_天界生活日常/01_天界普通女生的一天"
    with pytest.raises(RuntimeError,match="IMAGE_ATTEMPT_AUTHORITY_UNVERIFIED"):
        story_review.run_critic(ep,attempt=9,codex_raw="codex",
            direct_user_migrated_rubric=True,timeout=15)


def test_old_legacy_work_pass_can_never_be_promoted_to_a9_without_real_codex_provenance():
    import story_review_rubric_migration as migration
    ep=ROOT/"episodes/15_天界生活日常/01_天界普通女生的一天"
    legacy=migration.read_legacy_review(ep)
    payload={**legacy,"revision_count":8,
        "critic_provenance":{**legacy["critic_provenance"],
            "attempt":9,"review_epoch":8,"epoch_attempt":1,
            "direct_user_continuation_review":True,
            "review_scope":migration.REVIEW_SCOPE,
            "previous_review_sha256":"1"*64,
            "previous_review_request_sha256":"2"*64,
            "previous_standard_sha256":"3"*64,
            "current_standard_sha256":"4"*64,
            "current_rubric_sha256":"5"*64}}
    assert migration.validate_epoch(ep,payload["critic_provenance"]) is False
