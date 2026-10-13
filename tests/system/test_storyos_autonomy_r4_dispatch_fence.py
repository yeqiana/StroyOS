"""R4 slot1: dispatch fence must still be current immediately before paid Provider."""
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import patch
import pytest

ROOT=Path(__file__).resolve().parents[2]
SYSTEM=ROOT/"episodes"/"_system"
if str(SYSTEM) not in sys.path:sys.path.insert(0,str(SYSTEM))
import image_generation_gateway as gw
import generation_attempt_authority as authority

@pytest.mark.parametrize("batch", [False,True])
def test_fence_recheck_is_between_commit_and_provider(monkeypatch,tmp_path,batch):
    events=[]
    lease={"episode_id":"ep", "logical_asset_key":"ep/f1",
           "fencing_token":11,"lease_token_hash":"owner-11",
           "attempt_index":1}
    with patch.object(gw.global_image_capacity,"image_permits") as permits:
        from contextlib import nullcontext
        permits.return_value=nullcontext()
        monkeypatch.setattr(authority,"commit_dispatch",
                            lambda *a,**k: events.append("commit") or dict(lease))
        monkeypatch.setattr(authority,"commit_dispatch_many",
                            lambda *a,**k: events.append("commit") or [dict(lease)])
        monkeypatch.setattr(authority,"validate_committed_dispatch",
                            lambda *a,**k: events.append("recheck") or True)
        monkeypatch.setattr(authority,"validate_committed_dispatch_many",
                            lambda *a,**k: events.append("recheck") or True)
        monkeypatch.setattr(authority,"mark_observed",
                            lambda *a,**k:events.append("observed"))
        provider=lambda:events.append("provider") or "img"
        if batch: result=gw.provider_generate_many(tmp_path,[lease],"native",provider)
        else: result=gw.provider_generate(tmp_path,lease,11,"native",provider)
    assert result=="img"
    assert events==["commit","recheck","provider","observed"]


@pytest.mark.parametrize("batch",[False,True])
def test_lost_fence_after_commit_never_crosses_paid_boundary(monkeypatch,tmp_path,batch):
    lease={"episode_id":"ep", "logical_asset_key":"ep/f1","fencing_token":11}
    provider=[]
    from contextlib import nullcontext
    monkeypatch.setattr(gw.global_image_capacity,"image_permits",lambda *a: nullcontext())
    monkeypatch.setattr(authority,"commit_dispatch",lambda *a,**k:dict(lease))
    monkeypatch.setattr(authority,"commit_dispatch_many",lambda *a,**k:[dict(lease)])
    def lost(*a,**k):raise authority.AttemptDenied("STALE_GENERATION_ATTEMPT_FENCE")
    monkeypatch.setattr(authority,"validate_committed_dispatch",lost)
    monkeypatch.setattr(authority,"validate_committed_dispatch_many",lost)
    monkeypatch.setattr(authority,"fail_after_dispatch",lambda *a,**k:None)
    with pytest.raises(authority.AttemptDenied,match="STALE_GENERATION_ATTEMPT_FENCE"):
        if batch: gw.provider_generate_many(tmp_path,[lease],"native",lambda:provider.append(1))
        else:gw.provider_generate(tmp_path,lease,11,"native",lambda:provider.append(1))
    assert not provider
    assert lease["_phase"]=="TERMINAL"

def test_committed_check_rejects_stale_row_without_paid_provider():
    lease={"episode_id":"ep","logical_asset_key":"ep/f1","attempt_index":1,
           "fencing_token":3,"lease_token_hash":"token"}
    class FakeDb:
        def __init__(self):self.closed=False
        def transaction(self):
            from contextlib import nullcontext
            return nullcontext()
        def close(self):self.closed=True
    db=FakeDb()
    with patch.object(authority,"_connect",return_value=db), \
         patch.object(authority,"_locked_lease",return_value=({"FENCING_COUNTER":3},
                                                              {"STATUS":"OUTCOME_UNKNOWN"})):
        with pytest.raises(authority.AttemptDenied,match="STALE_GENERATION_ATTEMPT_FENCE"):
            authority.validate_committed_dispatch(Path("."),lease,3)
    assert db.closed
