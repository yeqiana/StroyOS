"""No-provider full native prompt staging review, bound to original source hashes."""
import copy
import hashlib
import json
import sys
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/"episodes/_system")]
import production_ep14_review_staging_package as staged


@pytest.fixture
def fixture(tmp_path,monkeypatch):
    ep=tmp_path/"episodes"/"00_独立篇"/"14_深渊疗愈所_第一集_净土生命还原"
    ep.mkdir(parents=True)
    calls=[]
    def candidate(path,frame):
        calls.append((path,frame))
        if frame not in (9,29,48):raise ValueError("exact scope")
        old=f"REJECTED ORIGINAL STORYBOARD FRAME {frame}"
        treatment=f"ALTERNATIVE RENDER CONTRACT {frame} | NOT YET AUTHORIZED"
        return {
            "frame":frame,
            "status":"INDEPENDENT_REVIEW_REQUIRED",
            "review_approved":False,
            "production_dispatch_authorized":False,
            "old_frame_contract_sha256":"a"*64,
            "old_storyboard_excerpt_sha256":"b"*64,
            "old_scene_prompt_sha256":"c"*64,
            "proposed_render_contract_sha256":"d"*64,
            "proposed_render_contract_text":treatment,
            "proposed_scene_prompt":f"Nonviolent scene for frame {frame}",
            "preserved_story_beats":["continuity","story reason"],
        }
    monkeypatch.setattr(staged.treatment,"compile_candidate",candidate)
    monkeypatch.setattr(staged.treatment,"EP",ep)
    for f in (9,29,48):
        monkeypatch.setitem(staged.treatment.ORIGINAL,f,("a"*64,"c"*64,"b"*64))
    monkeypatch.setattr(staged.treatment.frame_contract,"compile_frame",
        lambda *a,**kw:{"storyboard_frame":{"text":f"REJECTED ORIGINAL STORYBOARD FRAME {a[1]}"}})
    import image_model_policy
    monkeypatch.setattr(image_model_policy,"for_episode",lambda ep:{
        "model":"gpt-image-2.5-flare","quality":"high","strict_model":True
    })
    return ep,calls


@pytest.mark.parametrize("frame",[9,29,48])
def test_native_worker_prompt_composed_but_never_executed(fixture,frame):
    ep,calls=fixture
    result=staged.stage(ep,frame)
    assert result["review_status"]=="AWAITING_INDEPENDENT_SEMANTIC_AND_CONTENT_REVIEW"
    assert not result["review_approved"]
    assert not result["dispatch_authorized"]
    assert result["paid_generation_calls"]==result["mysql_writes"]==result["authority_writes"]==0
    assert f"REJECTED ORIGINAL STORYBOARD FRAME {frame}" not in result["full_native_worker_prompt"]
    assert "NOT YET AUTHORIZED" in result["full_native_worker_prompt"]
    assert "model=gpt-image-2.5-flare, quality=high, canvas=1080x1350" in result["full_native_worker_prompt"]
    assert "<frame_contract>" in result["full_native_worker_prompt"]
    assert "<scene>" in result["full_native_worker_prompt"]
    assert calls==[(ep,frame)]
    assert len(result["full_native_worker_prompt_sha256"])==64


def test_full_worker_prompt_hash_is_stable(fixture):
    ep,_=fixture
    a=staged.stage_all(ep);b=staged.stage_all(ep)
    assert a==b
    assert a["independent_review_status"]=="PENDING"
    assert not a["production_dispatch_authorized"]
    assert a["paid_generation_calls"]==a["mysql_writes"]==0
    assert [x["frame"] for x in a["frames"]]==[9,29,48]


def test_original_storyboard_leak_in_visual_block_denied(fixture,monkeypatch):
    ep,_=fixture
    import codex_subscription_image as native
    original=native.worker_prompt
    def leak(*a,**kw):
        return original(*a,**kw)+"\nREJECTED ORIGINAL STORYBOARD FRAME 9"
    monkeypatch.setattr(native,"worker_prompt",leak)
    with pytest.raises(ValueError,match="REJECTED_ORIGINAL_STORYBOARD_LEAK"):
        staged.stage(ep,9)


def test_unapproved_marker_required(fixture,monkeypatch):
    ep,_=fixture
    def _alter(path,frame):
        return {"frame":frame,"status":"INDEPENDENT_REVIEW_REQUIRED","review_approved":False,"production_dispatch_authorized":False,"old_frame_contract_sha256":"a"*64,
                "old_storyboard_excerpt_sha256":"b"*64,
                "old_scene_prompt_sha256":"c"*64,
                "proposed_render_contract_sha256":"d"*64,
                "proposed_render_contract_text":"UNMARKED CONTRACT",
                "proposed_scene_prompt":"calm white interior",
                "preserved_story_beats":[]}
    monkeypatch.setattr(staged.treatment,"compile_candidate",_alter)
    with pytest.raises(ValueError,match="UNAPPROVED_RENDER_CONTRACT"):
        staged.stage(ep,9)



def test_offline_saved_snapshot_sha_bound_and_non_authoritative(fixture,monkeypatch):
    import json
    ep,calls=fixture
    rows=[staged.treatment.compile_candidate(ep,f) for f in (9,29,48)]
    calls.clear()
    path=ep/staged.SNAPSHOT_REL
    path.parent.mkdir(parents=True,exist_ok=True)
    payload=json.dumps({"review_status":"PENDING","frames":rows},
        ensure_ascii=False,indent=2).encode("utf8")
    path.write_bytes(payload)
    monkeypatch.setattr(staged,"SNAPSHOT_SHA",hashlib.sha256(payload).hexdigest())
    def no_live_contract(*a,**kw):
        raise AssertionError("offline reviewer must not pretend to verify current DB/Frame Contract")
    monkeypatch.setattr(staged.treatment.frame_contract,"compile_frame",no_live_contract)
    report=staged.stage_all_offline(ep)
    assert report["live_source_authority_verified"] is False
    assert report["independent_review_status"]=="PENDING"
    assert report["production_dispatch_authorized"] is False
    assert report["paid_generation_calls"]==report["mysql_writes"]==0
    assert all(x["live_source_authority_verified"] is False for x in report["frames"])
    assert calls==[]
    path.write_bytes(payload+b"tampered")
    with pytest.raises(ValueError,match="IMMUTABLE_REVIEW_SNAPSHOT"):
        staged.stage_all_offline(ep)

def test_review_packet_includes_sha_bound_editorial_overlays_and_timing(fixture, monkeypatch):
    ep,_ = fixture
    original = staged.treatment.compile_candidate
    overlay = {
        "render_in_image_model": False,
        "source": "docs/storyboard.md Frame 48",
        "lines": [
            "福主林岚，骨重八斤七两。",
            "堪作中堂主梁，名录已入。",
            "明日下元醮子时，受戒入桩。",
        ],
    }
    def with_editorial(path, frame):
        result = original(path, frame)
        if frame == 48:
            result["editorial_overlay_contract"] = copy.deepcopy(overlay)
        if frame == 29:
            result["editorial_timing_cue"] = {
                "subjective_insert_intended_duration_ms": 100,
                "production_format": "image_and_text_not_video",
            }
        return result
    monkeypatch.setattr(staged.treatment, "compile_candidate", with_editorial)
    a = staged.stage_all(ep)
    row48 = next(r for r in a["frames"] if r["frame"] == 48)
    row29 = next(r for r in a["frames"] if r["frame"] == 29)
    assert row48["editorial_overlay_contract"]["lines"] == overlay["lines"]
    assert row48["editorial_overlay_contract_sha256"] == staged.canonical_sha(overlay)
    assert row29["editorial_timing_cue"]["subjective_insert_intended_duration_ms"] == 100
    assert not a["production_dispatch_authorized"]
    assert a["paid_generation_calls"] == a["mysql_writes"] == 0
    overlay["lines"][1] += "。"
    b = staged.stage_all(ep)
    assert a["bundle_sha256"] != b["bundle_sha256"]  # exact editorial bytes are SHA-bound

def test_unsafe_overlay_cannot_be_staged(fixture, monkeypatch):
    ep,_ = fixture
    original = staged.treatment.compile_candidate
    def unsafe(path, frame):
        entry = original(path, frame)
        entry["editorial_overlay_contract"] = {
            "render_in_image_model": True, "lines": ["不要用模型绘制文字"]
        }
        return entry
    monkeypatch.setattr(staged.treatment, "compile_candidate", unsafe)
    with pytest.raises(ValueError, match="REVIEW_EDITORIAL_OVERLAY_INVALID"):
        staged.stage(ep, 48)
