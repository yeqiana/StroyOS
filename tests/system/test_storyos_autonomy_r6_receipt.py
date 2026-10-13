"""R6 slot2: network timeout after Provider handoff must be UNKNOWN, not retryable."""
from contextlib import nullcontext
from pathlib import Path
import subprocess
import sys
import pytest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"episodes"/"_system"))
import image_generation_gateway as gateway

def prepare(monkeypatch,leases,events):
    monkeypatch.setattr(gateway.global_image_capacity,"image_permits",lambda *_a:nullcontext())
    monkeypatch.setattr(gateway.authority,"commit_dispatch",lambda *a,**k:dict(leases[0]))
    monkeypatch.setattr(gateway.authority,"commit_dispatch_many",lambda *a,**k:[dict(x) for x in leases])
    monkeypatch.setattr(gateway.authority,"validate_committed_dispatch",lambda *a,**k:True)
    monkeypatch.setattr(gateway.authority,"validate_committed_dispatch_many",lambda *a,**k:True)
    monkeypatch.setattr(gateway.authority,"mark_outcome_unknown",lambda *a,**k:events.append(("UNKNOWN",a[1]["logical_asset_key"])))
    monkeypatch.setattr(gateway.authority,"fail_after_dispatch",lambda *a,**k:events.append(("FAILED",a[1]["logical_asset_key"])))


@pytest.mark.parametrize("exception",[TimeoutError("timed out"),ConnectionResetError("closed"),subprocess.TimeoutExpired(["codex"],15)])
def test_single_provider_ambiguous_network_outcome_is_unknown(monkeypatch,tmp_path,exception):
    lease={"episode_id":"ep","logical_asset_key":"ep/01","fencing_token":11}
    events=[]
    prepare(monkeypatch,[lease],events)
    with pytest.raises(type(exception)):
        gateway.provider_generate(tmp_path,lease,11,"codex_subscription",
                                  lambda:(_ for _ in ()).throw(exception))
    assert events==[("UNKNOWN","ep/01")]
    assert lease["_phase"]=="TERMINAL"


def test_native_batch_timeout_marks_each_frame_unknown(monkeypatch,tmp_path):
    a={"episode_id":"ep","logical_asset_key":"ep/01","fencing_token":7}
    b={"episode_id":"ep","logical_asset_key":"ep/02","fencing_token":8}
    events=[]
    prepare(monkeypatch,[a,b],events)
    with pytest.raises(TimeoutError):
        gateway.provider_generate_many(tmp_path,[a,b],"codex_subscription",
                                       lambda:(_ for _ in ()).throw(TimeoutError("timeout")))
    assert events==[("UNKNOWN","ep/01"),("UNKNOWN","ep/02")]


def test_batch_partial_observation_outage_only_marks_unobserved_unknown(monkeypatch,tmp_path):
    a={"episode_id":"ep","logical_asset_key":"ep/01","fencing_token":7}
    b={"episode_id":"ep","logical_asset_key":"ep/02","fencing_token":8}
    events=[]
    prepare(monkeypatch,[a,b],events)
    def observed(ep,lease,fence):
        if lease["logical_asset_key"]=="ep/01":
            events.append(("RECORDED","ep/01"))
        else:
            raise OSError("mysql failed")
    monkeypatch.setattr(gateway.authority,"mark_observed",observed)
    with pytest.raises(OSError):
        gateway.provider_generate_many(tmp_path,[a,b],"codex_subscription",
                                       lambda:"paid_batch_complete")
    assert events==[("RECORDED","ep/01"),("UNKNOWN","ep/02")]
