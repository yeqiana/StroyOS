"""R10 integration: refuse irreversible duplicate Critic before subprocess."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"episodes"/"_system"))
import runtime_dag
import story_review
import product_review_adapter as pra


def test_targeted_story_never_spawns_162_or_repeats_finalized_attempt(tmp_path,monkeypatch):
    monkeypatch.setattr(story_review,"load_review",lambda ep:None)
    monkeypatch.setattr(pra,"request_path",
                        lambda ep,kind,attempt:tmp_path/str(attempt))
    monkeypatch.setattr(pra,"_request_exists",lambda p:True)
    monkeypatch.setattr(pra,"_read_json",lambda p:{
        "status":"AWAITING_PRODUCT_REVIEW" if p.name=="1" else "FINALIZED"})
    monkeypatch.setattr(runtime_dag,"run",
                        lambda argv: (_ for _ in ()).throw(AssertionError("DUPLICATE_DISPATCH")))
    rc,note=runtime_dag._run_targeted_review(
        tmp_path,kind="story-semantic",attempt=162,codex=None,
        timeout=100,run_id="r10",trace_id="r10")
    assert rc==22
    assert "FINALIZED_REVIEW_WITHOUT_CANONICAL_PROOF" in note


def test_new_story_review_uses_first_attempt_not_162(tmp_path,monkeypatch):
    monkeypatch.setattr(story_review,"load_review",lambda ep:None)
    monkeypatch.setattr(pra,"_request_exists",lambda p:False)
    commands=[]
    class Result:
        returncode=0
        stdout="official story review completed"
    monkeypatch.setattr(runtime_dag,"run",lambda argv:(commands.append(argv),Result())[1])
    rc,note=runtime_dag._run_targeted_review(
        tmp_path,kind="story-semantic",attempt=162,codex=None,
        timeout=100,run_id="r10",trace_id="r10")
    assert rc==0 and commands
    assert commands[0][commands[0].index("--attempt")+1]=="1"
    assert "official story review" in note
