"""R12: new one-time Codex review epoch cannot borrow historical WORK PASS."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"episodes"/"_system"))
import story_review_rubric_migration as migration
import story_review

EP=ROOT/"episodes/15_天界生活日常/01_天界普通女生的一天"

def test_real_migrated_story_has_exact_legacy_review_and_changed_formal_standard(monkeypatch):
    monkeypatch.setattr(story_review,'load_review',lambda ep:None)
    result=migration.plan(EP)
    assert result["status"]=="ONE_SHOT_NEW_CRITIC_EPOCH_READY"
    assert result["may_reuse_old_pass"] is False
    assert result["prior_standard_sha256"]!=result["current_standard_sha256"]
    assert result["prior_story_sha256"]==result["current_story_sha256"]
    assert result["attempt"]==9
    assert result["provider_calls"]==0

def test_rubric_drift_requires_current_review_not_mutated_legacy(monkeypatch):
    monkeypatch.setattr(story_review,'load_review',lambda ep:None)
    result=migration.plan(EP)
    assert result["legacy_review_sha256"]
    assert result["prior_review_request_id"]
    assert result["old_review_still_readonly"] is True

def test_review_gate_rejects_fake_migration_review_without_sha_authority():
    old=migration.read_legacy_review(EP)
    payload={**old,"critic_provenance":{**old["critic_provenance"],
        "attempt":9,"direct_user_continuation_review":True,
        "review_scope":"MIGRATED_EPISODE_RUBRIC_REVALIDATION",
        "review_epoch":8,"epoch_attempt":1},
        "revision_count":8}
    story,board=story_review.story_paths(EP)
    issues=story_review.validate_payload(payload,story_sha=story_review.sha256_file(story),
        storyboard_sha=story_review.sha256_file(board),
        version=story_review.episode_contract_version(EP))
    assert issues
