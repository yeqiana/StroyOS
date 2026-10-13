"""R15 slot1: release Git overlap gate never clobbers the owner's checkout."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
import storyos_release_overlap_gate as gate

def test_dirty_overlap_blocks_even_when_git_mergeable():
    data=gate.decide(
        main_commit="a"*40,feature_commit="b"*40,
        remote_main="a"*40,ancestry_ok=True,
        dirty=["episodes/_system/story_review.py","reports/account-learning-index.json"],
        incoming=["episodes/_system/story_review.py","scripts/another.py"])
    assert data["status"]=="DIRTY_FILE_OVERLAP_REFUSE_MAIN_MERGE"
    assert data["overlap"]==["episodes/_system/story_review.py"]
    assert data["may_merge_primary"] is False

def test_unrelated_dirty_is_not_a_license_to_reset_or_stash():
    data=gate.decide(
        main_commit="a"*40,feature_commit="b"*40,
        remote_main="a"*40,ancestry_ok=True,
        dirty=["reports/account-learning-index.json"],
        incoming=["episodes/_system/story_review.py"])
    assert data["status"]=="REVIEWABLE_FF_CANDIDATE"
    assert data["may_merge_primary"] is False
    assert data["read_only"] is True

def test_remote_advanced_fails_before_dirty_overlap():
    data=gate.decide(main_commit="a"*40,feature_commit="b"*40,
        remote_main="c"*40,ancestry_ok=False,dirty=[],incoming=[])
    assert data["status"]=="REMOTE_MAIN_CHANGED"
    assert not data["may_merge_primary"]
