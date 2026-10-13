"""R12 final fourth-slot regression: 1-shot, no duplicate debit, retired GC."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
sys.path.insert(0,str(ROOT/"episodes"/"_system"))
import story_review_rubric_migration as migration
import storyos_autonomy_fast_test as fast

def test_fresh_epoch_ticket_is_exclusive_even_after_crashed_worker(tmp_path,monkeypatch):
    selected={
        "status":"ONE_SHOT_NEW_CRITIC_EPOCH_READY",
        "legacy_review_sha256":"a"*64,"prior_review_request_sha256":"b"*64,
        "prior_review_request_id":"old-request","prior_standard_sha256":"c"*64,
        "current_standard_sha256":"d"*64,
        "current_story_sha256":"e"*64,"storyboard_sha256":"f"*64}
    import story_review
    (tmp_path/".git").mkdir()
    monkeypatch.setattr(story_review,"ROOT",tmp_path)
    monkeypatch.setattr(migration,"plan",lambda ep:selected)
    stamp=migration.authorize(tmp_path,attempt=9,current_rubric_sha256="1"*64)
    assert stamp["review_scope"]==migration.REVIEW_SCOPE
    import pytest
    with pytest.raises(FileExistsError):
        migration.authorize(tmp_path,attempt=9,current_rubric_sha256="1"*64)
    assert (tmp_path/migration.EPOCH_REL).is_file()

def test_r12_four_fast_slots_and_extreme_capacity_test_still_registered():
    for slot in ("r12-critic-epoch","r12-driver-gate","r12-frame01-proof","r12-integrated"):
        assert slot in fast.SLOTS and fast.test_commands(slot=slot)
    cmds=fast.test_commands(slot="all",stress=True)
    assert any("test_multi_episode_global_image_capacity.py" in x for x in cmds[-1])
    assert any("test_storyos_autonomy_r12_critic_epoch.py" in x for row in cmds for x in row)

def test_duplicate_native_review_not_automatically_a_second_image_generation():
    import storyos_autonomy_r12_critic_preflight as preflight
    x=preflight.decide(
        stage={"status":"STAGE_ELIGIBLE","stage":"STORYBOARD_LOCKED","source":"mysql"},
        paid={"status":"ATTEMPT_HISTORY_READ_ONLY","active_attempt_assets":[],
              "outcome_unknown_assets":[]},
        driver={"driver_state":"STOPPED","liveness":"DEAD"},
        codex={"status":"NATIVE_AUTH_CONTEXT_READY","opencodex_used":False,
               "interactive_codex_auth_context_present":True,
               "cli_runner_same_binary_verified":True},
        review={"status":"ALREADY_AUTHORIZED_NO_RETRY"})
    assert x["can_dispatch_image"] is False
    assert x["may_start_new_text_review"] is False
