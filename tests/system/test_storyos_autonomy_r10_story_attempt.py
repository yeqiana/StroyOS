"""R10 slot1: DAG attempt 162 is not an authorized Story Critic attempt."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"episodes"/"_system"))
import story_review_attempt_admission as a

def test_reused_161_dag_runs_are_not_story_review_attempts():
    r=a.decide(dag_attempt=162,official_review=None,request_rows={},candidate_exists={})
    assert r["attempt"]==1 and r["may_dispatch"] is True

def test_real_production_finalized_request_without_review_is_a_hard_stop():
    r=a.decide(dag_attempt=162,official_review=None,request_rows={
        1:{"status":"AWAITING_PRODUCT_REVIEW"},2:{"status":"FINALIZED"}},candidate_exists={1:False})
    assert r["status"]=="FINALIZED_REVIEW_WITHOUT_CANONICAL_PROOF"
    assert r["return_code"]==22 and r["may_dispatch"] is False

def test_pending_old_work_review_is_not_replayed_as_native():
    r=a.decide(dag_attempt=77,official_review=None,request_rows={
        1:{"status":"AWAITING_PRODUCT_REVIEW"}},candidate_exists={1:False})
    assert r["status"]=="EXISTING_REVIEW_REQUIRES_FINALIZATION"
    assert r["return_code"]==20 and not r["may_dispatch"]

def test_canonical_failed_first_review_allows_only_second_attempt():
    r=a.decide(dag_attempt=120,official_review={
        "critic_provenance":{"attempt":1},"summary":{"passed":False}},
        request_rows={1:{"status":"FINALIZED"}},candidate_exists={})
    assert r["attempt"]==2 and r["may_dispatch"]

def test_no_third_attempt_without_bound_continuation():
    r=a.decide(dag_attempt=2,official_review={
        "critic_provenance":{"attempt":2},"summary":{"passed":False}},
        request_rows={1:{"status":"FINALIZED"},2:{"status":"FINALIZED"}},candidate_exists={})
    assert r["return_code"]==22 and not r["may_dispatch"]
