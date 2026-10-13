"""A10 after a proven, paid A9 timeout: no reset, no borrowed PASS."""
import hashlib
import json
from pathlib import Path
import sys
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/"episodes/_system"),str(ROOT/"scripts")]
import story_review as sr
import story_review_rubric_migration as a9
import story_review_a10_source_revision as a10
import storyos_a9_receipt_reconcile as receipt
import storyos_autonomy_r12_critic_preflight as preflight
import story_review_attempt_admission as admission


@pytest.fixture
def source(tmp_path,monkeypatch):
    (tmp_path/".git").mkdir()
    ep=tmp_path / a10.EXPECTED_EPISODE
    docs=ep/"docs"
    docs.mkdir(parents=True)
    story=docs/"02_story_V1.0.md"
    board=docs/"03_20张分镜修订草稿_V1.1.md"
    story.write_text("unchanged story",encoding="utf-8")
    board.write_text("corrected frame 15 and wooden hairpin, 20 frames",encoding="utf-8")
    captions=docs/"subtitles.yaml"
    captions.write_text("frames:\n"+"".join(
        f'  {i}: "第{i}张日常生活记录"\n' for i in range(1,21)),encoding="utf-8")
    old=ep/a9.EPOCH_REL
    old.parent.mkdir(parents=True)
    old.write_text(json.dumps({
        "schema":"storyos.story_review_migrated_rubric_epoch.v1",
        "review_scope":a9.REVIEW_SCOPE,"global_review_attempt":9,
        "story_sha256":sr.sha256_file(story),
        "storyboard_sha256":"f"*64
    }),encoding="utf-8")
    a9candidate=ep/sr.CANDIDATE_REL
    a9candidate.parent.mkdir(parents=True,exist_ok=True)
    a9candidate.write_text('{"summary":{"passed":false}}',encoding="utf-8")
    monkeypatch.setattr(sr,"ROOT",tmp_path)
    monkeypatch.setattr(sr,"load_review",lambda e:None)
    monkeypatch.setattr(sr,"story_paths",lambda e:(story,board))
    monkeypatch.setattr(sr,"_review_rubric_digest",lambda _: "e"*64)
    monkeypatch.setattr(receipt,"inspect",lambda ep,root=None:{
        "status":"PAID_CRITIC_TIMEOUT_NO_AUTORETRY",
        "runner_receipt_count":1,"candidate_declared_pass":False
    })
    return ep,story,board,captions,a9candidate


def test_a10_independent_source_epoch_ready_but_never_pass(source):
    ep,*_=source
    plan=a10.plan(ep)
    assert plan["status"]=="ONE_SHOT_REVISED_SOURCE_READY"
    assert plan["attempt"]==10
    assert plan["can_dispatch_model"] is False
    assert plan["can_dispatch_image"] is False
    assert plan["model_calls"]==plan["sql_writes"]==0


def test_a10_ticket_is_exclusive_and_binds_both_source_and_old_receipt(source):
    ep,story,board,captions,a9candidate=source
    before=a9candidate.read_bytes()
    epoch=a10.authorize(ep,attempt=10,current_rubric_sha256="e"*64)
    assert epoch["review_scope"]==a10.REVIEW_SCOPE
    prov={**epoch,"attempt":10}
    assert a10.validate_epoch(ep,prov)
    assert a9candidate.read_bytes()==before
    with pytest.raises(RuntimeError):
        a10.authorize(ep,attempt=10,current_rubric_sha256="e"*64)
    board.write_text("drift",encoding="utf-8")
    assert not a10.validate_epoch(ep,prov)


def test_a10_full_story_review_payload_has_to_verify_real_new_source(source):
    ep, story, board, captions, old_candidate=source
    stamp=a10.authorize(ep,attempt=10,current_rubric_sha256="e"*64)
    import runtime_provenance
    prov=runtime_provenance.build_critic_provenance(
        "CODEX",attempt=10,allow_user_continuation_attempt=True)
    for key in ("review_scope","review_epoch","epoch_attempt",
                "current_rubric_sha256","previous_storyboard_sha256",
                "previous_a9_ticket_sha256","previous_a9_candidate_sha256",
                "subtitle_source_sha256"):
        prov[key]=stamp[key]
    data={
        "schema_version":1,"story_os_version":"2.6.1",
        "story_sha256":sr.sha256_file(story),
        "storyboard_sha256":sr.sha256_file(board),
        "subtitle_source_sha256":stamp["subtitle_source_sha256"],
        "revision_count":9,"critic_provenance":prov,
        "contract":{k:"NOT_APPLICABLE: ordinary life" for k in sr.CONTRACT_FIELDS},
        "blind_retell":{k:"ordinary daily life" for k in sr.BLIND_FIELDS},
        "hard_checks":{k:True for k in sr.HARD_CHECKS},
        "issue_codes":[],"summary":{"passed":True},
    }
    data["contract"]["ending_recontextualization"]=["hairpin","paper wrap","cloud bridge"]
    errors=sr.validate_payload(data,story_sha=sr.sha256_file(story),
                               storyboard_sha=sr.sha256_file(board),version="2.6.1")
    assert errors==[]
    data["critic_provenance"]["previous_a9_candidate_sha256"]="0"*64
    assert not a10.validate_epoch(ep,data["critic_provenance"])
    assert old_candidate.read_text(encoding="utf-8")=='{"summary":{"passed":false}}'


def test_canonical_a10_pass_can_replace_only_unbound_historical_gate(source,monkeypatch):
    ep,story,board,captions,old_candidate=source
    gates=ep/"meta/story-gates.json"
    original={"reviews":{"story":"passed"},"review_authority_bindings":{}}
    gates.write_text(json.dumps(original),encoding="utf-8")
    monkeypatch.setattr(sr,"verify",lambda ep:[])
    monkeypatch.setattr(sr,"load_review",lambda ep:{
        "summary":{"passed":True},
        "critic_provenance":{"attempt":10,"review_scope":a10.REVIEW_SCOPE},
        "story_sha256":sr.sha256_file(story),
        "storyboard_sha256":sr.sha256_file(board)})
    monkeypatch.setattr(sr,"review_authority_sha256",lambda ep:"b"*64)
    monkeypatch.setattr(a10,"validate_epoch",lambda ep,prov:True)
    result=sr.project_verified_story_gate(ep)
    assert result["attempt"]==10
    assert json.loads(gates.read_text("utf-8"))[
        "review_authority_bindings"]["story"]["authority_sha256"]=="b"*64
    gates.write_text(json.dumps(original),encoding="utf-8")
    monkeypatch.setattr(a10,"validate_epoch",lambda ep,prov:False)
    with pytest.raises(ValueError):
        sr.project_verified_story_gate(ep)
    assert json.loads(gates.read_text("utf-8"))==original


def test_a10_native_admission_and_early_fences():
    ready=dict(
       stage={"source":"mysql","status":"STAGE_ELIGIBLE","stage":"STORYBOARD_LOCKED"},
       paid={"status":"ATTEMPT_HISTORY_READ_ONLY","active_attempt_assets":[],
             "outcome_unknown_assets":[],"unverified_status_assets":[]},
       driver={"driver_state":"NEVER_STARTED","liveness":"DEAD"},
       codex={"status":"NATIVE_AUTH_CONTEXT_READY",
              "opencodex_used":False,"interactive_codex_auth_context_present":True,
              "cli_runner_same_binary_verified":True},
       review={"status":"ONE_SHOT_REVISED_SOURCE_READY","attempt":10})
    r=preflight.decide(**ready)
    assert r["may_start_new_text_review"] is True
    assert r["review_attempt"]==10
    assert r["can_dispatch_image"] is False
    bad=preflight.decide(**{**ready,"paid":{
        **ready["paid"],"outcome_unknown_assets":["frame01"]}})
    assert not bad["may_start_new_text_review"]
    assert preflight.decide(**{**ready,"codex":{
        **ready["codex"],"opencodex_used":True}})["may_start_new_text_review"] is False


def test_a10_success_cannot_be_borrowed_from_a9_or_legacy_history(source):
    ep,story,board,captions,a9candidate=source
    assert not receipt.canonical_a10_review_verified(ep)
    existing=admission.decide(dag_attempt=162,
        official_review={"critic_provenance":{"attempt":10,
          "review_scope":a10.REVIEW_SCOPE,"review_epoch":9,"epoch_attempt":1,
          "direct_user_continuation_review":True},
          "summary":{"passed":True}},
        request_rows={1:{"status":"AWAITING_PRODUCT_REVIEW"},
                      2:{"status":"FINALIZED"}},
        candidate_exists={})
    assert existing["status"]=="EXISTING_REVIEW_MUST_BE_REVALIDATED"
    assert not existing["may_dispatch"]
    from storyos_a9_receipt_reconcile import decide
    d=decide(epoch_present=True,candidate={"summary":{"passed":False}},
             candidate_exists=True,evidence_status="PAID_CRITIC_TIMEOUT_NO_AUTORETRY",
             official_review_present=False)
    assert d["can_publish"] is False
    assert d["may_retry_attempt_9"] is False
