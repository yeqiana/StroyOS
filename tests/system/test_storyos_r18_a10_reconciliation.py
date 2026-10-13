"""R18 bounded tests: no second Codex call; real A10 FAIL evidence stays."""
from pathlib import Path
import hashlib
import json
import sys
import inspect
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/"scripts"),str(ROOT/"episodes/_system")]
import storyos_a10_completed_result as result
import story_review as review
import storyos_a9_receipt_reconcile as receipts
import codex_critic_runner as critic

def test_runner_proof_requires_sha_and_success():
    import base64
    payload=b'{"type":"turn.completed"}'
    rid="a"*32
    sha="b"*64
    row={"request_id":rid,"returncode":0,
         "output_sha256":hashlib.sha256(payload).hexdigest(),
         "output_bytes":len(payload),
         "output_base64":base64.b64encode(payload).decode(),
         "evidence":{"request_id":rid,"task_type":"critic",
                     "transport_route":"native_codex",
                     "working_directory":str(ROOT),
                     "stdin_sha256":sha,"returncode":0,"timed_out":False}}
    assert receipts.classify_receipt(row,prompt_sha256=sha,root=ROOT)=="RUNNER_SUCCEEDED_REQUIRES_CANONICAL_FINALIZATION"
    row["evidence"]["stdin_sha256"]="c"*64
    assert receipts.classify_receipt(row,prompt_sha256=sha,root=ROOT)=="RUNNER_RECEIPT_NOT_SHA_BOUND"

def test_complete_provider_json_cannot_be_replayed_from_partial():
    value={"hard_checks":{"delete_frame_test":False},
           "issue_codes":["DELETE_FRAME_TEST_FAIL"],"summary":{"passed":False}}
    event=json.dumps({"type":"item.completed","item":{
        "type":"agent_message","text":json.dumps(value)}})
    assert critic.recover_completed_agent_json(event) is None
    assert critic.recover_completed_agent_json(
        event+"\n"+json.dumps({"type":"turn.completed"}))==value

def test_reconciliation_refuses_untrusted_episode_without_writes(tmp_path):
    report,data=result.inspect(tmp_path,root=tmp_path)
    assert data is None
    assert report["status"]=="EPISODE_OUT_OF_SCOPE"
    assert report["model_calls"]==report["sql_writes"]==0
    assert report["can_retry_attempt_10"] is False
    assert report["can_dispatch_image"] is False

def test_a10_past_review_sha_optional_preserves_candidate_on_fail():
    code=inspect.getsource(review.run_critic)
    assert 'if "previous_review_sha256" in continuation:' in code
    finalize=inspect.getsource(review._finalize_review)
    assert 'if attempt != 10 or decision == "PASS":' in finalize
    source=inspect.getsource(result.inspect)
    assert "RUNNER_SUCCEEDED_REQUIRES_CANONICAL_FINALIZATION" in source
    assert "recover_completed_agent_json" in source
    assert "DELETE_FRAME_TEST_FAIL" in source

def test_fenced_record_fail_uses_existing_payload_never_model(tmp_path,monkeypatch,capsys):
    root=tmp_path
    (root/".git").mkdir()
    ep=root/"episodes/15_天界生活日常/01_天界普通女生的一天"
    ep.mkdir(parents=True)
    monkeypatch.setattr(result,"ROOT",root)
    seen=[]
    monkeypatch.setattr(result,"inspect",lambda _:(
        {"status":"A10_PROVIDER_SUCCESS_REVIEW_FAIL",
         "may_record_fail":True,"read_only":True,"model_calls":0,
         "sql_writes":0}, {"critic_provenance":{"attempt":10}}))
    monkeypatch.setattr(review,"story_paths",lambda _:(ep/"story.md",ep/"board.md"))
    monkeypatch.setattr(review,"sha256_file",lambda _: "a"*64)
    monkeypatch.setattr(review,"_finalize_review",
        lambda ep,data,**kwargs:(seen.append(kwargs) or 2))
    assert result.main([
        "episodes/15_天界生活日常/01_天界普通女生的一天",
        "--record-verified-fail"])==0
    assert len(seen)==1 and seen[0]["attempt"]==10
    assert '"A10_OFFICIAL_FAIL_RECORDED"' in capsys.readouterr().out


def test_two_frame_concrete_fix_is_only_a_draft():
    p=ROOT/"episodes/15_天界生活日常/01_天界普通女生的一天/docs/04_删帧修订建议_V1.2.md"
    s=p.read_text(encoding="utf-8")
    for frame in ("Frame 03","Frame 04","Frame 08","Frame 09","Frame 18"):
        assert frame in s
    assert "未锁定" in s and "A10" in s and "PASS" in s
    # The published V1.1 source remains untouched by this revision proposal.
    manifest=json.loads((p.parent.parent/"meta/release-manifest.json").read_text("utf-8-sig"))
    assert manifest["artifacts"]["storyboard"].endswith("_V1.1.md")
