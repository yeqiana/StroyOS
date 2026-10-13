"""R5 slot2: a successful Provider call plus lost DB receipt is OUTCOME_UNKNOWN."""
from contextlib import nullcontext
from pathlib import Path
import sys
import pytest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"episodes"/"_system"))
import image_generation_gateway as gw

def test_observation_outage_after_paid_provider_marks_unknown(monkeypatch,tmp_path):
    events=[]
    lease={"generation_key":"g1","fencing_token":7}
    monkeypatch.setattr(gw.global_image_capacity,"image_permits",lambda *_:nullcontext())
    monkeypatch.setattr(gw.authority,"commit_dispatch",lambda *a,**kw:dict(lease))
    monkeypatch.setattr(gw.authority,"validate_committed_dispatch",lambda *a,**kw:True)
    monkeypatch.setattr(gw.authority,"mark_observed",lambda *a:(_ for _ in ()).throw(OSError("db dropped")))
    monkeypatch.setattr(gw.authority,"mark_outcome_unknown",lambda *a,**kw:events.append("UNKNOWN"))
    monkeypatch.setattr(gw.authority,"fail_after_dispatch",lambda *a,**kw:events.append("FAILED"))
    with pytest.raises(OSError):
        gw.provider_generate(tmp_path,lease,7,"native",lambda:events.append("PAID") or "raw")
    assert events==["PAID","UNKNOWN"]
    assert lease["_phase"]=="TERMINAL"

def test_paid_provider_exception_is_not_observation_failure(monkeypatch,tmp_path):
    events=[]
    lease={"generation_key":"g1","fencing_token":7}
    monkeypatch.setattr(gw.global_image_capacity,"image_permits",lambda *_:nullcontext())
    monkeypatch.setattr(gw.authority,"commit_dispatch",lambda *a,**kw:dict(lease))
    monkeypatch.setattr(gw.authority,"validate_committed_dispatch",lambda *a,**kw:True)
    monkeypatch.setattr(gw.authority,"fail_after_dispatch",lambda *a,**kw:events.append("FAILED"))
    monkeypatch.setattr(gw.authority,"mark_outcome_unknown",lambda *a,**kw:events.append("UNKNOWN"))
    with pytest.raises(RuntimeError):
        gw.provider_generate(tmp_path,lease,7,"native",lambda:(_ for _ in ()).throw(RuntimeError("provider")))
    assert events==["FAILED"]

def test_batch_observation_outage_must_not_reclassify_successful_frames_failed(monkeypatch,tmp_path):
    a={"episode_id":"ep","logical_asset_key":"ep/a","fencing_token":3}
    b={"episode_id":"ep","logical_asset_key":"ep/b","fencing_token":4}
    events=[]
    monkeypatch.setattr(gw.global_image_capacity,"image_permits",lambda *_:nullcontext())
    monkeypatch.setattr(gw.authority,"commit_dispatch_many",lambda *args,**kw:[dict(x) for x in (a,b)])
    monkeypatch.setattr(gw.authority,"validate_committed_dispatch_many",lambda *a:True)
    monkeypatch.setattr(gw.authority,"mark_observed",lambda *a:(_ for _ in ()).throw(OSError("mysql lost")))
    monkeypatch.setattr(gw.authority,"mark_outcome_unknown",lambda *a,**kw:events.append("UNKNOWN"))
    monkeypatch.setattr(gw.authority,"fail_after_dispatch",lambda *a,**kw:events.append("FAILED"))
    with pytest.raises(OSError):
        gw.provider_generate_many(tmp_path,[a,b],"native",lambda:events.append("PAID") or "raw")
    assert events==["PAID","UNKNOWN","UNKNOWN"]
