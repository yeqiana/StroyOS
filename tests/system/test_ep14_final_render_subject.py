"""Final EP14 render content remains independently reviewable, not dispatchable."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "episodes/_system"))
import production_ep14_final_render_subject as mod


def sha(x):
    return hashlib.sha256(x.encode("utf8")).hexdigest()


@pytest.fixture
def scenario(monkeypatch, tmp_path):
    ep = tmp_path / "episodes" / "00_独立篇" / "14_深渊疗愈所"
    ep.mkdir(parents=True)
    items=[]
    records=[]
    for frame in (9,29,48):
        head=sha(f"reviewed-render-{frame}")
        scene=f"reviewed pixel description for Frame {frame}"
        render=(
            f"PROPOSED RENDER TREATMENT | frame={frame:02d} "
            f"| sha256={head} | NOT YET AUTHORIZED\n"
            "This derived contract is mandatory. Locked sources outrank ad-hoc prompt wording.\n"
            "\n[STORYBOARD FRAME]\n[ALTERNATIVE VISUAL TREATMENT, REVIEW PENDING]\n"
            f"[REC] Safe alternative render for Frame {frame}.\n"
            "Treat this section as a proposed visual interpretation only; "
            "source story and exact dialogue remain under separate locked authority.\n"
            "[VISUAL DNA]\nprofile=M00\n"
        )
        package={
            "frame":f"{frame:02d}",
            "scene_prompt":scene,
            "scene_prompt_sha256":sha(scene),
            "frame_prompt_contract":render,
            "image_model":{"provider":"openai","model":"gpt-image-2.5-flare","quality":"high"},
            "frame_contract_sha256":sha(f"old-story-{frame}"),
            "render_variant_sha256":sha(f"derived-variant-{frame}"),
            "package_sha256":sha(f"noncanonical-pkg-{frame}"),
            "storyboard_source":{
                "sha256":sha(f"story-frame-{frame}"),"frame":f"{frame:02d}",
                "authority":"LOCKED_ORIGINAL_STORYBOARD_HASH_ONLY",
                "render_original_text_injected":False,
            },
            "canonical_activation":False,
            "production_dispatch_authorized":False,
            "status":"REVIEWED_PROPOSED_PACKAGE_NOT_ACTIVATED",
            "canonical_prompt_package_written":False,
        }
        records.append({
            "frame":frame,"id":f"candidate-{frame}","sha":package["package_sha256"],
            "payload":package,
        })
        items.append({"frame":frame,"status":"external_blocked","requires_content_revision":True})
    q={"items":items,"updated_at":"original"}
    data={"queue":deepcopy(q),"records":records,"status":"VERIFIED_THREE_MYSQL_CANDIDATES_NOT_ACTIVATED"}
    @contextmanager
    def lock(ep):
        yield
    monkeypatch.setattr(mod.scheduler_core, "queue_transaction", lock)
    monkeypatch.setattr(mod.scheduler_core, "load_queue", lambda ep: deepcopy(data["queue"]))
    monkeypatch.setattr(mod.mysql_candidates,"verify",lambda ep:{
        "status":data["status"],"frames":[9,29,48],
        "bundle_sha256":sha("mysql-candidate-bundle"),
    })
    monkeypatch.setattr(mod.mysql_candidates,"_candidate_plan",lambda ep,q:{
        "bundle_sha256":sha("mysql-candidate-bundle"),
        "stage_binding_sha256":sha("queue-stage"),
        "records":deepcopy(data["records"]),
    })
    return ep,data


def test_final_render_subject_keeps_source_sha_but_strips_all_preview_markers(scenario):
    ep,data=scenario
    result=mod.prepare(ep)
    assert result["status"]=="THREE_FINAL_CONTROLLER_SUBJECTS_READY_NOT_APPROVED"
    assert len(result["frames"])==3
    assert len(result["final_render_bundle_sha256"])==64
    assert result["canonical_activation"] is False
    assert result["production_dispatch_authorized"] is False
    assert result["provider_entitlement_verified"] is False
    assert result["final_controller_review_approved"] is False
    assert result["mysql_writes"]==0
    assert result["paid_attempts_reserved"]==0
    for candidate,final in zip(data["records"],result["frames"]):
        assert final["scene_prompt"]==candidate["payload"]["scene_prompt"]
        assert final["frame_contract_sha256"]==candidate["payload"]["frame_contract_sha256"]
        assert final["storyboard_source"]==candidate["payload"]["storyboard_source"]
        assert final["render_variant_sha256"]==candidate["payload"]["render_variant_sha256"]
        assert final["source_candidate_package_sha256"]==candidate["sha"]
        assert final["render_content_sha256"]==mod.render_package._hash_json({
            k:v for k,v in final.items()
            if k in ("frame","frame_contract_sha256","storyboard_source",
                     "scene_prompt","scene_prompt_sha256","frame_prompt_contract",
                     "image_model","render_variant_sha256","source_candidate_package_sha256")
        })
        assert "NOT YET AUTHORIZED" not in final["frame_prompt_contract"]
        assert "REVIEW PENDING" not in final["frame_prompt_contract"]
        assert "PROPOSED RENDER TREATMENT" not in final["frame_prompt_contract"]
        assert "LOCKED ORIGINAL STORYBOARD FRAME" not in final["frame_prompt_contract"]
        assert "[DERIVED VISUAL TREATMENT]" in final["frame_prompt_contract"]
        assert "[ALTERNATIVE VISUAL TREATMENT, REVIEW PENDING]" in candidate["payload"]["frame_prompt_contract"]
    assert data["queue"]["items"][0]["status"]=="external_blocked"
    assert mod.prepare(ep)["final_render_bundle_sha256"]==result["final_render_bundle_sha256"]


@pytest.mark.parametrize("bad",[
    "wrong_frame","pretend_approved","pretend_dispatched","not_candidate",
    "preview_marker_missing","fake_duplicate_marker","original_story_leak",
    "scene_sha_tampered","old_story_missing","bad_candidate_package_sha",
    "wrong_frame_in_header","bad_storyboard_provenance","no_storyboard_sha",
])
def test_invalid_final_render_input_rejected(scenario,bad):
    ep,data=scenario
    candidate=data["records"][0]["payload"]
    if bad=="wrong_frame":
        candidate["frame"]="20"
    elif bad=="pretend_approved":
        candidate["canonical_activation"]=True
    elif bad=="pretend_dispatched":
        candidate["production_dispatch_authorized"]=True
    elif bad=="not_candidate":
        candidate["status"]="PRODUCTION_APPROVED"
    elif bad=="preview_marker_missing":
        candidate["frame_prompt_contract"]=candidate["frame_prompt_contract"].replace(
            "NOT YET AUTHORIZED","")
    elif bad=="fake_duplicate_marker":
        candidate["frame_prompt_contract"]+="\nNOT YET AUTHORIZED"
    elif bad=="original_story_leak":
        candidate["frame_prompt_contract"]+="\nLOCKED ORIGINAL STORYBOARD FRAME"
    elif bad=="scene_sha_tampered":
        candidate["scene_prompt_sha256"]="0"*64
    elif bad=="old_story_missing":
        candidate["frame_contract_sha256"]=""
    elif bad=="bad_candidate_package_sha":
        candidate["package_sha256"]="not-sha"
    elif bad=="wrong_frame_in_header":
        candidate["frame_prompt_contract"]=candidate["frame_prompt_contract"].replace("frame=09","frame=29")
    elif bad=="bad_storyboard_provenance":
        candidate["storyboard_source"]["text"]="old denied storyboard"
    elif bad=="no_storyboard_sha":
        candidate["storyboard_source"]["render_original_text_injected"]=None
    with pytest.raises(mod.FinalRenderDenied):
        mod.prepare(ep)


@pytest.mark.parametrize("bad",["unverified_mysql","wrong_mysql_bundle","short_rows","queue_race"])
def test_final_bundle_rejects_incomplete_mysql_or_concurrent_queue(scenario,monkeypatch,bad):
    ep,data=scenario
    if bad=="unverified_mysql":
        data["status"]="NOT_VERIFIED"
    elif bad=="wrong_mysql_bundle":
        monkeypatch.setattr(mod.mysql_candidates,"verify",lambda ep:{
            "status":"VERIFIED_THREE_MYSQL_CANDIDATES_NOT_ACTIVATED",
            "frames":[9,29,48],"bundle_sha256":"1"*64})
    elif bad=="short_rows":
        data["records"].pop()
    elif bad=="queue_race":
        original=mod.scheduler_core.load_queue
        called=[0]
        def changing(ep):
            called[0]+=1
            r=original(ep)
            if called[0]>=2:
                r["updated_at"]="concurrent edit"
            return r
        monkeypatch.setattr(mod.scheduler_core,"load_queue",changing)
    with pytest.raises((mod.FinalRenderDenied,ValueError)):
        mod.prepare(ep)
