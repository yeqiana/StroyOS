"""R7 slot2: never enter a paid Provider on unproven post-commit Fence."""
from pathlib import Path
import sys
from contextlib import nullcontext
import pytest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"episodes"/"_system"))
import image_generation_gateway as gw
from generation_attempt_authority import AttemptDenied

def test_single_validation_false_blocks_paid_call(monkeypatch,tmp_path):
    events=[]
    lease={"episode_id":"ep","logical_asset_key":"ep/01","fencing_token":3}
    monkeypatch.setattr(gw.global_image_capacity,"image_permits",lambda *_:nullcontext())
    monkeypatch.setattr(gw.authority,"commit_dispatch",lambda *a,**k:dict(lease))
    monkeypatch.setattr(gw.authority,"validate_committed_dispatch",lambda *a,**k:False)
    monkeypatch.setattr(gw.authority,"fail_after_dispatch",lambda *a,**k:events.append("fail_closed"))
    with pytest.raises(AttemptDenied,match="STALE_GENERATION_ATTEMPT_FENCE"):
        gw.provider_generate(tmp_path,lease,3,"native",lambda:events.append("PAID"))
    assert events==["fail_closed"]

def test_batch_validation_false_blocks_paid_call(monkeypatch,tmp_path):
    events=[]
    lease={"episode_id":"ep","logical_asset_key":"ep/01","fencing_token":3}
    monkeypatch.setattr(gw.global_image_capacity,"image_permits",lambda *_:nullcontext())
    monkeypatch.setattr(gw.authority,"commit_dispatch_many",lambda *a,**k:[dict(lease)])
    monkeypatch.setattr(gw.authority,"validate_committed_dispatch_many",lambda *a,**k:False)
    monkeypatch.setattr(gw.authority,"fail_after_dispatch",lambda *a,**k:events.append("fail_closed"))
    with pytest.raises(AttemptDenied,match="STALE_GENERATION_ATTEMPT_FENCE"):
        gw.provider_generate_many(tmp_path,[lease],"native",lambda:events.append("PAID"))
    assert events==["fail_closed"]

def test_batch_partial_committed_receipt_cannot_enter_provider(monkeypatch,tmp_path):
    events=[]
    leases=[{"episode_id":"ep","logical_asset_key":"ep/01","fencing_token":3},
            {"episode_id":"ep","logical_asset_key":"ep/02","fencing_token":4}]
    monkeypatch.setattr(gw.global_image_capacity,"image_permits",lambda *_:nullcontext())
    monkeypatch.setattr(gw.authority,"commit_dispatch_many",lambda *a,**k:[dict(leases[0])])
    monkeypatch.setattr(gw.authority,"validate_committed_dispatch_many",lambda *a,**k:True)
    monkeypatch.setattr(gw.authority,"fail_after_dispatch",lambda *a,**k:events.append("fail_closed"))
    with pytest.raises(AttemptDenied,match="GENERATION_ATTEMPT_BATCH_COMMIT_INCOMPLETE"):
        gw.provider_generate_many(tmp_path,leases,"native",lambda:events.append("PAID"))
    assert "PAID" not in events
