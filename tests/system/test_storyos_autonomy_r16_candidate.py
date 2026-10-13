"""R16 slot2: candidate FAIL and receipt UNKNOWN are read-only facts."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
import storyos_a9_receipt_reconcile as r

def decide(candidate=None,evidence="RUNNER_RECEIPT_MISSING",existing=True):
    return r.decide(epoch_present=True,candidate=candidate,
        candidate_exists=existing,evidence_status=evidence,
        official_review_present=False)
def test_timeout_candidate_declared_fail_does_not_create_mysql_review():
    result=decide({"summary":{"passed":False}},
        evidence="PAID_CRITIC_TIMEOUT_NO_AUTORETRY")
    assert result["status"]=="PAID_CRITIC_TIMEOUT_NO_AUTORETRY"
    assert result["candidate_declared_pass"] is False
    assert result["sql_writes"]==result["model_calls"]==0
    assert not result["may_retry_attempt_9"]
    assert not result["can_mark_review_pass"]

def test_unattested_candidate_must_not_be_promoted_even_if_it_claims_pass():
    assert decide({"summary":{"passed":True}})["status"]=="A9_UNVERIFIED_CANDIDATE_RECONCILE"
    assert not decide({"summary":{"passed":True}})["can_dispatch_image"]

def test_missing_candidate_after_ticket_is_unknown_not_new_authority():
    assert decide(None,existing=False)["status"]=="A9_OUTCOME_UNKNOWN_NO_CANDIDATE"

def test_legacy_review_presence_does_not_imply_new_provenance():
    p=r.decide(epoch_present=True,candidate=None,candidate_exists=False,
        evidence_status="PAID_CRITIC_TIMEOUT_NO_AUTORETRY",
        official_review_present=True)
    assert p["status"]=="OFFICIAL_REVIEW_NEEDS_CANONICAL_VALIDATION"
    assert not p["can_publish"]
