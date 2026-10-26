"""Episode14 actual delegated profile authority and Batch native follow-on fences."""
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import Mock
import pytest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"episodes/_system"))
import production_ep14_visual_profile_rc9 as profile
import production_native_batch_followon as followon

@pytest.fixture
def ep(tmp_path,monkeypatch):
    root=tmp_path
    path=root/"episodes"/"00_独立篇"/profile.EP.name
    (path/"meta").mkdir(parents=True)
    monkeypatch.setattr(profile,"ROOT",root)
    monkeypatch.setattr(profile,"EP",path)
    monkeypatch.setattr(followon,"ROOT",root)
    return path

def test_no_user_confirmation_is_fabricated(ep,monkeypatch):
    draft={"lifecycle_state":"SELECTED","confirmation_mode":"pending",
           "confirmed_by":None,"confirmed_at":None}
    new={"lifecycle_state":"FROZEN","confirmation_mode":"delegated_auto",
         "confirmed_by":profile.AUTH,"confirmation":{"reason":"sha"}}
    state=[draft]
    monkeypatch.setattr(profile,"_base",lambda *_:{
        "profile":state[0],"profile_sha":"before","report_sha":"sha","f002_sha":"png"})
    monkeypatch.setattr(profile,"_driver_stopped",lambda *_:True)
    monkeypatch.setattr(profile,"_archive_prior_approval",lambda *_:"priorSHA")
    monkeypatch.setattr(profile.delegated_approval,"verify",lambda *_:[])
    captured=[]
    def confirm(*args,**kwargs):
        captured.append(kwargs)
        state[0]=new
    monkeypatch.setattr(profile.lifecycle,"confirm_visual_lock",confirm)
    monkeypatch.setattr(profile.visual_profile_closure,"reconcile_episode",
                        lambda *_:{"status":"frozen"})
    monkeypatch.setattr(profile.visual_profile_gate,
                        "validate_visual_profile_for_production",
                        lambda *_,**kwargs:{"status":"pass"})
    assert profile.apply(ep,acknowledged=False)["reason"]=="EXPLICIT_PRODUCTION_ACK_REQUIRED"
    result=profile.apply(ep,acknowledged=True)
    assert result["status"]=="PASS"
    assert result["user_approved"] is False
    assert result["independent_vision_fail_preserved"] is True
    assert result["new_image_attempts"]==0
    assert len(captured)==1
    assert captured[0]["mode"]=="delegated_auto"
    assert captured[0]["confirmed_by"]==profile.AUTH
    assert "exhausted 2/2 WEAK_PASS" in captured[0]["reason"]

@pytest.mark.parametrize("lock",[
    {"lifecycle_state":"SELECTED","confirmation_mode":"pending","confirmed_by":"user"},
    {"lifecycle_state":"SELECTED","confirmation_mode":"direct_user","confirmed_by":None},
    {"lifecycle_state":"FROZEN","confirmation_mode":"delegated_auto","confirmed_by":"user","confirmation":{"reason":"sha"}},
    {"lifecycle_state":"FROZEN","confirmation_mode":"delegated_auto","confirmed_by":"StoryOS delegated-auto Visual Lock authority","confirmation":{"reason":"wrong"}}])
def test_unrelated_confirmation_fails_closed(ep,monkeypatch,lock):
    monkeypatch.setattr(profile,"_base",lambda *_:{
        "profile":lock,"profile_sha":"before","report_sha":"sha","f002_sha":"png"})
    assert profile.eligible(ep)["status"]=="BLOCKED"

def test_missing_prior_authorities_never_confirms(ep,monkeypatch):
    monkeypatch.setattr(profile,"_base",lambda *_:None)
    monkeypatch.setattr(profile,"_driver_stopped",lambda *_:True)
    confirmed=Mock(side_effect=AssertionError("must never confirm"))
    monkeypatch.setattr(profile.lifecycle,"confirm_visual_lock",confirmed)
    assert profile.apply(ep,acknowledged=True)["status"]=="BLOCKED"
    confirmed.assert_not_called()

def test_ep14_batch_geometry_is_exactly_44(ep):
    q={"items":[{"frame":f,"id":str(f),"scope":"batch"} for f in sorted(followon.EP14_FRAMES)]}
    assert len(followon._batch(q,ep))==44
    assert followon._batch(q)==[]
    q["items"].pop()
    assert followon._batch(q,ep)==[]

def test_ep14_native_requires_frozen_prior_approval(ep,monkeypatch):
    monkeypatch.setattr(followon.episode_state_persistence,"load",
                        lambda *_:{"current_state":"VISUAL_CALIBRATED"})
    monkeypatch.setattr(followon.runtime_request,"effective_for_episode",
                        lambda *_:{"mode":"full_auto","runtime":{"execution_mode":"dag"}})
    monkeypatch.setattr(followon.storage_config,"mysql_connection_kwargs",
                        lambda:{"host":"127.0.0.1","port":3307})
    monkeypatch.setattr(followon.runtime_router,"image_execution_runtime",
                        lambda:("CODEX",None))
    monkeypatch.setattr(followon.image_payload_transport,"selected_route",
                        lambda *_:{"provider":"codex_subscription"})
    monkeypatch.setattr(followon,"ROOT",ep.parents[2])
    monkeypatch.setattr(profile,"eligible",lambda *_:{"status":"BLOCKED"})
    a={"model":"gpt-image-2.5-flare","quality":"high"}
    b={"model":"gpt-6-luna","reasoning_effort":"high"}
    assert not followon._episode_authorized(ep,a,b)
    monkeypatch.setattr(profile,"eligible",
                        lambda *_:{"status":"CONFIRMED_BY_EXISTING_DELEGATION"})
    monkeypatch.setattr(followon,"_is_ep14",lambda *_:True)
    import visual_profile_gate
    monkeypatch.setattr(visual_profile_gate,"validate_visual_profile_for_production",
                        lambda *_,**kwargs:{"status":"pass"})
    assert followon._episode_authorized(ep,a,b)


def test_live_driver_never_rewrites_visual_profile(ep,monkeypatch):
    monkeypatch.setattr(profile,"_driver_stopped",lambda *_:False)
    unexpected=Mock(side_effect=AssertionError("live driver cannot authorize profile"))
    monkeypatch.setattr(profile.lifecycle,"confirm_visual_lock",unexpected)
    assert profile.apply(ep,acknowledged=True)["reason"]=="RC9_DRIVER_NOT_CONFIRMED_STOPPED"
    unexpected.assert_not_called()


def test_previous_delegated_bundle_is_snapshotted_and_immutable(ep,monkeypatch):
    prior={"approvals":{"visual_lock":{"approved":True,
           "delegated_auto_review":True,"user_approved":False,
           "artifacts":[{"role":"visual_spec","sha256":"originalsha"}]}}}
    monkeypatch.setattr(profile.delegated_approval,"load_store",
                        lambda *_:(ep/"meta/delegated-approvals.json",prior))
    proof={"profile_sha256":"originalsha","report_sha256":"reportsha"}
    expected=profile.approval_persistence.payload_sha(prior)
    assert profile._archive_prior_approval(ep,proof)==expected
    payload=profile.story_json.read_json(ep/profile.SNAPSHOT)
    assert payload["original_approval_sha256"]==expected
    assert payload["original_approval_bundle"]==prior
    assert profile._archive_prior_approval(ep,proof)==expected
    with pytest.raises(ValueError,match="drift"):
        profile._archive_prior_approval(ep,{**proof,"report_sha256":"changed"})
