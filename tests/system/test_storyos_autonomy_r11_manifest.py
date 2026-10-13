"""R11 independent source path repair: no silent Review/mysql authority promotion."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
import storyos_manifest_relocation as m

EP="episodes/15_天界生活日常/01_天界普通女生的一天"

def test_real_git_relocation_is_proven_but_rubric_revision_blocks_review_replay():
    report=m.plan(EP)
    assert report["status"] in ("PATH_RELOCATION_PROVEN","RELOCATION_ALREADY_APPLIED")
    assert len(report["paths"])==3
    assert report["legacy_review_replay_allowed"] is False
    assert report["review_replay_blocker"]=="CRITIC_SOURCE_SHA_DRIFT"
    assert report["mysql_writes"]==report["review_writes"]==0

def test_manifest_repair_requires_proven_expected_sha(monkeypatch):
    ep=ROOT/EP
    monkeypatch.setattr(m.native,"canonical_episode",lambda ref:ep)
    monkeypatch.setattr(m,"plan",lambda _:{"status":"PATH_RELOCATION_PROVEN","manifest_sha256":"b"*64,"request_sha256":"q"*64,"paths":{}})
    result=m.apply(EP,{"status":"PATH_RELOCATION_PROVEN","manifest_sha256":"a"*64})
    assert result["status"]=="NOT_PRIMARY_CHECKOUT"
    assert result["manifest_writes"]==0

def test_cli_no_ack_refuses_mutation(capsys):
    assert m.main([EP,"--apply"])==2
    assert "PRODUCTION_ACK_REQUIRED" in capsys.readouterr().out
