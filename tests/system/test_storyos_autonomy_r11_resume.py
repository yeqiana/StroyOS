"""R11 recovered Driver must refuse unresolved Review and unknown paid images."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
import storyos_autonomy_resume_admission as a

BASE={"status":"DRIVER_HISTORY_UNVERIFIED","canonical_mysql_stage":"STORYBOARD_LOCKED",
      "active_attempt_count":0,"outcome_unknown_count":0}
REVIEW={"status":"FINALIZED_REVIEW_WITHOUT_CANONICAL_PROOF"}
SOURCE={"status":"PATH_RELOCATION_PROVEN","legacy_review_replay_allowed":False}

def test_real_episode_review_missing_never_triggers_driver_or_image():
    x=a.classify(BASE,REVIEW,SOURCE)
    assert x["status"]=="STOP_REVIEW_AUTHORITY_MISSING"
    assert not x["can_auto_dispatch"] and not x["can_dispatch_image"]

def test_unknown_paid_receipt_takes_priority_over_review_recovery():
    x=a.classify({**BASE,"outcome_unknown_count":1},REVIEW,SOURCE)
    assert x["status"]=="STOP_PAID_ATTEMPT_AUTHORITY"

def test_unverified_mysql_stage_not_a_resume_permit():
    x=a.classify({**BASE,"canonical_mysql_stage":None},REVIEW,SOURCE)
    assert x["status"]=="STOP_NON_STORYBOARD_MYSQL_STAGE"

def test_even_verified_review_only_allows_canonical_preflight():
    x=a.classify(BASE,{"status":"EXISTING_REVIEW_MUST_BE_REVALIDATED"},
                 {"status":"ALREADY_RELOCATED"})
    assert x["status"]=="CANONICAL_DAG_PREFLIGHT_ONLY"
    assert not x["can_dispatch_image"]
