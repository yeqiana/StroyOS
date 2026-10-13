"""R12 slot2: Driver accepts real independent attempt9 only after validation."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"episodes"/"_system"))
import story_review_attempt_admission as admission
import runtime_dag
import story_review
import product_review_adapter as reqs

PROV={"attempt":9,"review_scope":"MIGRATED_EPISODE_RUBRIC_REVALIDATION",
      "direct_user_continuation_review":True,"review_epoch":8,"epoch_attempt":1}
REQS={1:{"status":"AWAITING_PRODUCT_REVIEW"},2:{"status":"FINALIZED"}}

def test_a9_official_pass_is_read_only_revalidate_not_a9_redo():
    r=admission.decide(dag_attempt=163,
        official_review={"summary":{"passed":True},"critic_provenance":PROV},
        request_rows=REQS,candidate_exists={})
    assert r["status"]=="EXISTING_REVIEW_MUST_BE_REVALIDATED"
    assert r["may_dispatch"] is False

def test_dag_reuses_verified_a9_without_launching_another_provider(tmp_path,monkeypatch):
    monkeypatch.setattr(reqs,"_request_exists",lambda path:True)
    monkeypatch.setattr(reqs,"_read_json",lambda path:REQS[int(path.name.split("-attempt-")[1][0])])
    monkeypatch.setattr(story_review,"load_review",lambda ep:
        {"summary":{"passed":True},"critic_provenance":PROV})
    monkeypatch.setattr(story_review,"verify",lambda ep:[])
    monkeypatch.setattr(runtime_dag,"run",lambda argv:(_ for _ in ()).throw(
        AssertionError("paid model second call")))
    rc,note=runtime_dag._run_targeted_review(tmp_path,kind="story-semantic",
        attempt=163,codex=None,timeout=60,run_id="r12",trace_id="r12")
    assert rc==0 and "VERIFIED" in note

def test_dag_rejects_a9_when_binding_invalid_even_after_pass(tmp_path,monkeypatch):
    monkeypatch.setattr(reqs,"_request_exists",lambda path:True)
    monkeypatch.setattr(reqs,"_read_json",lambda path:REQS[int(path.name.split("-attempt-")[1][0])])
    monkeypatch.setattr(story_review,"load_review",lambda ep:
        {"summary":{"passed":True},"critic_provenance":PROV})
    monkeypatch.setattr(story_review,"verify",lambda ep:["sha invalid"])
    rc,note=runtime_dag._run_targeted_review(tmp_path,kind="story-semantic",
        attempt=163,codex=None,timeout=60,run_id="r12",trace_id="r12")
    assert rc==22 and "sha invalid" in note
