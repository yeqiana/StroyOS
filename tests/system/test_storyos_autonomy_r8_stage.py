"""R8 Stage truth: local JSON must not supersede verified MySQL."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
import storyos_stage_drift_readonly as drift

def test_stale_local_storyboard_vs_publish_ready_reports_mysql_authority(tmp_path):
    ep=tmp_path/"episodes"/"test"/"one"
    (ep/"meta").mkdir(parents=True)
    (ep/"meta"/"episode-state.json").write_text('{"current_state":"STORYBOARD_LOCKED"}',encoding="utf-8")
    answer=drift.inspect(ep,root=tmp_path,
                         stage_probe=lambda ref:(0,{"status":"ALREADY_PUBLISH_READY","stage":"PUBLISH_READY","source":"mysql"}))
    assert answer["status"]=="STAGE_DRIFT"
    assert answer["local_stage"]=="STORYBOARD_LOCKED"
    assert answer["canonical_mysql_stage"]=="PUBLISH_READY"
    assert answer["canonical_stage_authoritative"] is True
    assert answer["sql_writes"]==0

def test_missing_mysql_proof_fails_closed(tmp_path):
    ep=tmp_path/"episodes"/"test"/"one"
    (ep/"meta").mkdir(parents=True)
    (ep/"meta"/"episode-state.json").write_text('{"current_state":"STORYBOARD_LOCKED"}',encoding="utf-8")
    result=drift.inspect(ep,root=tmp_path,stage_probe=lambda ref:(2,{"stage":"PUBLISH_READY","source":"json"}))
    assert result["status"]=="MYSQL_AUTHORITY_UNVERIFIED"
    assert result["canonical_stage_authoritative"] is False

def test_already_matched_stage(tmp_path):
    ep=tmp_path/"episodes"/"test"/"one"
    (ep/"meta").mkdir(parents=True)
    (ep/"meta"/"episode-state.json").write_text('{"current_state":"STORYBOARD_LOCKED"}',encoding="utf-8")
    result=drift.inspect(ep,root=tmp_path,stage_probe=lambda ref:(0,{"status":"STAGE_ELIGIBLE","stage":"STORYBOARD_LOCKED","source":"mysql"}))
    assert result["status"]=="IN_SYNC"
