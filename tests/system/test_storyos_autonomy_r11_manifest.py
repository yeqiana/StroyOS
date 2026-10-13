"""R11 independent source path repair: no silent Review/mysql authority promotion."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
import storyos_manifest_relocation as m

EP="episodes/15_天界生活日常/01_天界普通女生的一天"

def test_real_git_relocation_is_proven_but_rubric_revision_blocks_review_replay():
    report=m.plan(EP)
    # Once V1.1 is the official *candidate* source, the legacy V1.0
    # relocation proof must fail before any old review can be projected.
    assert report["status"]=="CRITIC_SOURCE_SHA_DRIFT"
    assert report.get("legacy_review_replay_allowed") is not True
    assert report.get("can_recover_review") is not True
    assert report["mysql_writes"]==report["review_writes"]==0

def test_manifest_repair_refuses_worktree_without_touching_real_episode(tmp_path,monkeypatch):
    # Hermetic: a checked-out Worktree is represented by a .git file.
    # This guard must be verified regardless of where pytest itself runs.
    (tmp_path/".git").write_text("gitdir: isolated")
    ep=tmp_path/"episodes"/"fixture"
    ep.mkdir(parents=True)
    monkeypatch.setattr(m.native,"ROOT",tmp_path)
    monkeypatch.setattr(m.native,"canonical_episode",lambda ref:ep)
    monkeypatch.setattr(m,"plan",lambda _:
        (_ for _ in ()).throw(AssertionError("worktree cannot plan writes")))
    result=m.apply("synthetic",{"status":"PATH_RELOCATION_PROVEN","manifest_sha256":"a"*64})
    assert result["status"]=="NOT_PRIMARY_CHECKOUT"
    assert result["manifest_writes"]==0


def test_manifest_repair_refuses_stale_expected_sha_on_primary_fixture(tmp_path,monkeypatch):
    import subprocess
    (tmp_path/".git").mkdir()
    ep=tmp_path/"episodes"/"fixture"
    ep.mkdir(parents=True)
    monkeypatch.setattr(m.native,"ROOT",tmp_path)
    monkeypatch.setattr(m.native,"canonical_episode",lambda ref:ep)
    monkeypatch.setattr(m.subprocess,"run",lambda *a,**k:
        subprocess.CompletedProcess(a,0,stdout=str(tmp_path)))
    monkeypatch.setattr(m,"plan",lambda _:{
        "status":"PATH_RELOCATION_PROVEN","manifest_sha256":"b"*64,
        "request_sha256":"q"*64,"paths":{}})
    result=m.apply("synthetic",{"status":"PATH_RELOCATION_PROVEN","manifest_sha256":"a"*64})
    assert result["status"]=="EVIDENCE_CHANGED"
    assert result["manifest_writes"]==0

def test_cli_no_ack_refuses_mutation(capsys):
    assert m.main([EP,"--apply"])==2
    assert "PRODUCTION_ACK_REQUIRED" in capsys.readouterr().out
