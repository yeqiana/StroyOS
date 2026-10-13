#!/usr/bin/env python3
"""Read-only Story Critic attempt admission, independent of DAG reuse counters.

Do not infer a fresh Critic attempt from the number of historic DAG step runs.
A finalized review without its canonical authority must be reconciled, never
replayed; a pending WORK review cannot be relabeled native Codex approval.
"""
from __future__ import annotations


def decide(*, dag_attempt: int, official_review: dict | None,
           request_rows: dict[int, dict], candidate_exists: dict[int, bool]) -> dict:
    base={"may_dispatch":False,"attempt":None,"return_code":22,
          "dag_attempt_ignored":dag_attempt,"read_only":True,
          "model_calls":0,"sql_writes":0}
    if (type(dag_attempt) is not int or dag_attempt < 1
            or not isinstance(request_rows,dict) or not isinstance(candidate_exists,dict)
            or any(type(i) is not int or i not in (1,2)
                   or not isinstance(row,dict) for i,row in request_rows.items())):
        return {**base,"status":"REVIEW_AUTHORITY_UNVERIFIED"}
    # Distinct user-authorized migrated-rubric epoch #9 is already a NEW
    # independent Critic, not another review of the stale WORK #1/#2.
    # This is only a request to revalidate the official receipt; the DAG
    # must call story_review.verify before returning a successful step.
    if isinstance(official_review,dict):
        prov=official_review.get("critic_provenance") or {}
        if (
            (prov.get("attempt")==9
                and prov.get("review_scope")=="MIGRATED_EPISODE_RUBRIC_REVALIDATION"
                and prov.get("direct_user_continuation_review") is True
                and prov.get("review_epoch")==8 and prov.get("epoch_attempt")==1)
            or (prov.get("attempt")==10
                and prov.get("review_scope")=="EPISODE_SOURCE_REVISION_AFTER_A9_TIMEOUT"
                and prov.get("direct_user_continuation_review") is True
                and prov.get("review_epoch")==9 and prov.get("epoch_attempt")==1)
        ) and (official_review.get("summary") or {}).get("passed") is True:
            return {**base,"status":"EXISTING_REVIEW_MUST_BE_REVALIDATED"}
    for i,row in sorted(request_rows.items()):
        if row.get("status")=="FINALIZED" and not isinstance(official_review,dict):
            return {**base,"status":"FINALIZED_REVIEW_WITHOUT_CANONICAL_PROOF"}
        if row.get("status") not in ("FINALIZED","AWAITING_PRODUCT_REVIEW",
                                     "EXPIRED","CANCELLED","SUPERSEDED"):
            return {**base,"status":"REVIEW_REQUEST_STATE_UNVERIFIED"}
    pending=[i for i,row in sorted(request_rows.items())
             if row.get("status")=="AWAITING_PRODUCT_REVIEW"]
    if pending:
        if len(pending)>1 or (pending[0]==1 and 2 in request_rows):
            return {**base,"status":"REVIEW_REQUEST_LIFECYCLE_CONFLICT"}
        return {**base,"status":"EXISTING_REVIEW_REQUIRES_FINALIZATION",
                "attempt":pending[0],"return_code":20,
                "candidate_present":candidate_exists.get(pending[0]) is True}
    if isinstance(official_review,dict):
        provenance=official_review.get("critic_provenance") or {}
        index=provenance.get("attempt")
        if type(index) is not int or index not in (1,2):
            return {**base,"status":"OFFICIAL_REVIEW_ATTEMPT_UNVERIFIED"}
        if (official_review.get("summary") or {}).get("passed") is True:
            return {**base,"status":"EXISTING_REVIEW_MUST_BE_REVALIDATED"}
        if index!=1 or 2 in request_rows:
            return {**base,"status":"REVIEW_CONTINUATION_REQUIRES_EXPLICIT_AUTHORITY"}
        return {**base,"status":"DISPATCH_BOUNDED_STORY_CRITIC",
                "may_dispatch":True,"attempt":2,"return_code":0}
    # Existing terminal requests without an official review cannot grant a
    # fresh attempt, even if an old alias or DB projection has disappeared.
    if request_rows:
        return {**base,"status":"REVIEW_LIFECYCLE_RECONCILIATION_REQUIRED"}
    return {**base,"status":"DISPATCH_BOUNDED_STORY_CRITIC",
            "may_dispatch":True,"attempt":1,"return_code":0}
