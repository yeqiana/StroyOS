"""The alternative render preview has NO authority to dispatch paid images."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import Mock
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/"episodes/_system")]
import production_ep14_visual_treatment_preview as visual


@pytest.fixture
def local_fixture(tmp_path,monkeypatch):
    ep=tmp_path/"episodes"/"00_独立篇"/"14_深渊疗愈所_第一集_净土生命还原"
    ep.mkdir(parents=True)
    monkeypatch.setattr(visual,"EP",ep)
    mocked={}
    for frame in (9,29,48):
        original=f"LOCKED-ORIGINAL-FRAME-{frame}-WITH-OLD-INSTRUCTIONS"
        old_scene=f"original prompt {frame}".encode("utf8")
        path=ep/"prompts"/"production"/f"{frame:02d}.txt"
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(old_scene)
        old_contract="a"*63+str(frame%10)
        old_excerpt=hashlib.sha256(original.encode("utf8")).hexdigest()
        old_scene_sha=hashlib.sha256(old_scene).hexdigest()
        monkeypatch.setitem(visual.ORIGINAL,frame,(old_contract,old_scene_sha,old_excerpt))
        mocked[frame]={
            "contract_sha256":old_contract,
            "storyboard_frame":{"text":original,"sha256":old_excerpt},
            "prompt_contract":(
                f"RESOLVED FRAME CONTRACT | frame={frame:02d} | sha256={old_contract}\n"
                "This derived contract is mandatory.\n"
                "[STORYBOARD FRAME]\n"+original+"\n\n[VISUAL DNA]\n"
                "Unchanged world identity, camera and light notes.\n"
                "[CAPTURE / AUTHENTICITY]\n{}\n"
                "[CONTINUITY]\n{}\n"
                "[PERSISTENT WORLD STATE]\n{}\n"
                "[ENVIRONMENT PHYSICS]\n{}\n"
                "[FRAME DIRECTIVE]\n{}\n"
                "[SCENE-AWARE WARDROBE]\n{}\n"
                "[CAPTURE EVENT]\n{}\n"
                "[SHOT PROGRESSION / ACTION / ANOMALY LOGIC]\n{}\n"
                "[TEMPORAL CONTINUITY]\n{}\n"
                "[VISUAL NARRATIVE CORE V2.2]\n{}\n"
                "[FINAL]\n{}\n"),
        }
    # V4 independent-review projection tests need representative complete blocks.
    # These remain tiny mocked contracts, never provider or MySQL authority.
    for frame in (29, 48):
        source = mocked[frame]["prompt_contract"]
        if frame == 29:
            source = source.replace(
                "Unchanged world identity, camera and light notes.\n",
                "Unchanged world identity, camera and light notes.\n"
                "----- GLOBAL CAPTURE GRAMMAR -----\n"
                "camera_operator=participant_or_companion_inside_event\n"
                "camera_position=physically_plausible_human_position\n"
                "----- END GLOBAL CAPTURE GRAMMAR -----\n",
            )
        d = lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        world = {"characters": {k: {"status": "present", "clothing_anchor": "mixed"} for k in ("P01", "P02", "P03")},
                 "props": {}, "recorder": {"active_device": "A7S3"}}
        wardrobe = {"outfits": {k: {"garments": ["mixed"], "look_id": "P02_BASE"} for k in ("P01", "P02", "P03")},
                    "location_type": "outdoor", "scene_context": "courtyard_and_airlock"}
        visual_narrative = {
            "narrative_evidence": {"continuity_exception_reason": "", "new_information_this_frame": "old"},
            "human_response": {"emotion": {"state": "ordinary", "intensity": 0},
                               "interaction": {"actor": "P03", "target": "paper"}},
            "moment": {"action_in_progress": "old flashback", "save_reason": "recording"},
            "shot_grammar": {"family": "过肩主观视角", "location_zone": "courtyard_and_airlock"},
            "camera_authorship": {"camera_position": "过肩主观视角"},
            "camera_roster_policy": {"primary_photographer_required": True},
        }
        for heading, value in (
            ("PERSISTENT WORLD STATE", world),
            ("ENVIRONMENT PHYSICS", {"condition": "old dining room"}),
            ("SCENE-AWARE WARDROBE", wardrobe),
            ("VISUAL NARRATIVE CORE V2.2", visual_narrative),
        ):
            source = source.replace(
                "[" + heading + "]\n{}\n",
                "[" + heading + "]\n" + d(value) + "\n",
            )
        mocked[frame]["prompt_contract"] = source
    board = ep / "docs/storyboard.md"
    board.parent.mkdir(parents=True)
    board.write_text(
        "| 28 | 右手握着银刀对准膏块正中，刀尖即将切入冻膏。 | 餐盘 45 度俯角特写 |\n",
        encoding="utf8",
    )
    resolver=Mock(side_effect=lambda ep,f,write_cache=False:mocked[f])
    monkeypatch.setattr(visual.frame_contract,"compile_frame",resolver)
    return ep,mocked,resolver


@pytest.mark.parametrize("frame",[9,29,48])
def test_preview_removes_old_storyboard_prompt_without_legacy_leak(frame,local_fixture):
    ep,contracts,resolver=local_fixture
    before=json.dumps(contracts,sort_keys=True,ensure_ascii=False)
    out=visual.compile_candidate(ep,frame)
    assert out["review_approved"] is False
    assert out["production_dispatch_authorized"] is False
    assert out["requires_new_canonical_prompt_package"] is True
    assert out["requires_paid_attempt_2_risk_ack"] is True
    text=out["proposed_render_contract_text"]
    assert contracts[frame]["storyboard_frame"]["text"] not in text
    assert "[VISUAL DNA]\nUnchanged world identity" in text
    assert "[ALTERNATIVE VISUAL TREATMENT, REVIEW PENDING]" in text
    assert f"sha256={out['proposed_render_contract_sha256']}" in text
    assert out["old_frame_contract_sha256"]==contracts[frame]["contract_sha256"]
    assert json.dumps(contracts,sort_keys=True,ensure_ascii=False)==before
    resolver.assert_called_with(ep,frame,write_cache=False)


def test_hash_stability_scope_and_zero_side_effects(local_fixture):
    ep,contracts,resolver=local_fixture
    first=visual.compile_all(ep)
    second=visual.compile_all(ep)
    assert first==second
    assert first["review_status"]=="PENDING"
    assert first["image_calls"]==first["attempts_reserved"]==first["sql_writes"]==0
    assert first["production_dispatch_authorized"] is False
    assert [x["frame"] for x in first["frames"]]==[9,29,48]
    with pytest.raises(ValueError,match="EXACT_EP14_FRAME_SCOPE_REQUIRED"):
        visual.compile_candidate(ep,20)
    with pytest.raises(ValueError,match="EXACT_EP14_FRAME_SCOPE_REQUIRED"):
        visual.compile_candidate(ep.parent/"13_other",9)


def test_old_source_tamper_prevents_preview(local_fixture):
    ep,contracts,resolver=local_fixture
    path=ep/"prompts/production/09.txt"
    path.write_text("changed",encoding="utf8")
    with pytest.raises(ValueError,match="IMMUTABLE_SOURCE"):
        visual.compile_candidate(ep,9)
    path.write_text("original prompt 9",encoding="utf8")
    contracts[29]["contract_sha256"]="0"*64
    with pytest.raises(ValueError,match="IMMUTABLE_SOURCE"):
        visual.compile_candidate(ep,29)


def test_old_excerpt_in_other_section_fails_closed(local_fixture):
    ep,contracts,resolver=local_fixture
    excerpt=contracts[9]["storyboard_frame"]["text"]
    contracts[9]["prompt_contract"]+=f"\n[OTHER]\n{excerpt}\n"
    with pytest.raises(ValueError,match="OLD_REJECTED_STORYBOARD_LEAK"):
        visual.compile_candidate(ep,9)


def test_no_missing_section_or_unexpected_contract_version(local_fixture):
    ep,contracts,resolver=local_fixture
    contracts[48]["prompt_contract"]=contracts[48]["prompt_contract"].replace(
        "[STORYBOARD FRAME]","[SHOTBOARD]")
    with pytest.raises(ValueError,match="RENDER_PROMPT_LAYOUT_UNRECOGNIZED"):
        visual.compile_candidate(ep,48)


def test_f009_round_collar_clue_is_preserved_without_body_damage(local_fixture):
    ep,_,_=local_fixture
    out=visual.compile_candidate(ep,9)
    assert "圆形" in out["proposed_scene_prompt"] or "圆润" in out["proposed_scene_prompt"]
    assert "吞咽" in out["proposed_scene_prompt"]
    assert "无伤无血" in out["proposed_scene_prompt"]
    assert "smooth outward contour" in out["proposed_render_contract_text"]
    assert out["production_dispatch_authorized"] is False


def test_f029_nonrecorded_match_cut_overrides_derived_conflicts(local_fixture):
    ep,_,_=local_fixture
    out=visual.compile_candidate(ep,29)
    contract=out["proposed_render_contract_text"]
    assert "[NON-REC]" in out["proposed_scene_prompt"]
    assert "45度" in out["proposed_scene_prompt"]
    assert "切出" in out["proposed_scene_prompt"]
    assert "NONE_NON_REC_SUBJECTIVE_INSERT" in contract
    assert "Aze_subjective_nonrecorded_NonREC" in contract
    assert "nonbiological lacquer-resin board" in contract
    assert out["review_approved"] is False


def test_f048_exact_text_is_separate_from_image_prompt(local_fixture):
    ep,_,_=local_fixture
    out=visual.compile_candidate(ep,48)
    lines=out["editorial_overlay_contract"]["lines"]
    assert lines==["福主林岚，骨重八斤七两。","堪作中堂主梁，名录已入。","明日下元醮子时，受戒入桩。"]
    assert out["editorial_overlay_contract"]["render_in_image_model"] is False
    assert all(x not in out["proposed_scene_prompt"] for x in lines)
    assert "折叠工兵铲" in out["proposed_scene_prompt"]


def test_f029_missing_capture_section_fails_closed(local_fixture):
    ep,contracts,_=local_fixture
    contracts[29]["prompt_contract"]=contracts[29]["prompt_contract"].replace("[CAPTURE EVENT]","[MISSING]")
    import pytest
    with pytest.raises(ValueError,match="RENDER_OVERRIDDEN_SECTION_NOT_UNIQUE"):
        visual.compile_candidate(ep,29)


def test_frame29_all_render_only_fields_nonrec_and_timeline_not_video(local_fixture):
    ep,_,_=local_fixture
    d=visual.compile_candidate(ep,29)
    text=d["proposed_render_contract_text"]
    assert '"frame_mode":"subjective_nonrecorded_insert"' in text
    assert "NONE_FOR_THIS_SUBJECTIVE_FRAME" in text
    assert "subjective_cave_insert" in text
    assert "normal_record" not in text
    assert d["editorial_timing_cue"]["subjective_insert_intended_duration_ms"]==100
    assert d["editorial_timing_cue"]["production_format"]=="image_and_text_not_video"


def test_indoor_guestroom_and_a7s3_override_are_render_only(local_fixture):
    ep,_,_=local_fixture
    x=visual.compile_candidate(ep,48)
    rendered=x["proposed_render_contract_text"]
    assert '"location_type":"indoor"' in rendered
    assert "guest_room" in rendered
    assert "no photographer body or phantom third camera" in rendered
    assert x["review_approved"] is False


def test_review_only_restores_full_shabound_character_json_without_ellipsis():
    source = {"hash_material": {
        "character_contract": {"cast": [{"id": "P01", "name": "阿泽"}], "camera": "A7S3"},
        "character_visual_contract": {"members": [{"name": "林岚"}, {"name": "晓雨"}]},
    }}
    def raw(key):
        return json.dumps(source["hash_material"][key], ensure_ascii=False,
                          sort_keys=True, separators=(",", ":"))
    preview = ("\n[CHARACTER / POV CONTRACT]\n" + raw("character_contract")[:18] + "…\n"
               "[CHARACTER VISUAL / ORIGINAL IDENTITY]\n" + raw("character_visual_contract")[:19] + "…\n"
               "[END]\n{}")
    result = visual._restore_untruncated_review_blocks(preview, source)
    assert "…" not in result
    assert raw("character_contract") in result
    assert raw("character_visual_contract") in result
    assert preview != result


def test_review_only_denies_corrupted_or_missing_full_json():
    source = {"hash_material": {"character_contract": {"cast": [1, 2, 3]}}}
    bad = "\n[CHARACTER / POV CONTRACT]\n{\"other\":1…\n[END]\n{}"
    with pytest.raises(ValueError, match="REVIEW_CHARACTER_SOURCE_PROJECTION_DRIFT"):
        visual._restore_untruncated_review_blocks(bad, source)
    with pytest.raises(ValueError, match="REVIEW_FULL_SOURCE_JSON_MISSING"):
        visual._restore_untruncated_review_blocks(bad, {"hash_material": {}})


def test_f029_does_not_fabricate_frame28_motion_or_video_timing(local_fixture):
    ep, _, _ = local_fixture
    row = visual.compile_candidate(ep, 29)
    contract = row["proposed_render_contract_text"]
    scene = row["proposed_scene_prompt"]
    assert "[LOCKED FRAME28 MATCH CUT SOURCE]" in contract
    assert "does NOT prove a cut already happened or the movement direction" in contract
    assert "第28帧银刀对准冻膏正中" in scene
    assert "一张静态图文心象" in scene
    assert "实际刀刃切入方向仍未有源证据" in scene
    assert row["production_dispatch_authorized"] is False


def test_f029_nonrec_visual_scope_hand_and_static_match_only(local_fixture):
    ep, _, _ = local_fixture
    row = visual.compile_candidate(ep, 29)
    contract = row["proposed_render_contract_text"]
    scene = row["proposed_scene_prompt"]
    assert "枯槁老手" in scene and "枯槁老手" in contract
    assert "visible" in contract or "visibility" in contract
    assert "STATIC TWO-IMAGE COMPOSITIONAL ECHO ONLY" in contract
    assert '"primary_photographer_required":false' in contract
    assert '"persist":[]' in contract
    assert '"physical_scene_background_persist"' in contract
    assert '"render_in_this_mental_image":false' in contract
    assert "no verified Frame28 cutting direction" in contract
    timing = row["editorial_timing_cue"]
    assert timing["static_composition_reference_frame"] == 28
    assert timing["production_format"] == "image_and_text_not_video"
    assert timing["still_image_cannot_encode_duration"] is True
    assert row["production_dispatch_authorized"] is False


def test_f048_closed_curtain_visibility_and_postproduction_blank_slip(local_fixture):
    ep, _, _ = local_fixture
    row = visual.compile_candidate(ep, 48)
    contract = row["proposed_render_contract_text"]
    scene = row["proposed_scene_prompt"]
    assert "窗帘遮蔽窗外" in scene
    assert "无横线、无框、无三行占位符" in scene
    assert "closed curtain fully occludes outside fog/courtyard" in contract
    assert "closed curtain blocks outside sightline" in contract
    assert "one continuous completely blank face" in contract
    assert "NO letters, no rules, no boxes" in contract
    assert "THREE BLANK layout rows" not in contract
    assert "foggy courtyard remains outside the window" not in contract
    assert row["editorial_overlay_contract"]["render_in_image_model"] is False
    assert row["review_approved"] is False
    assert row["production_dispatch_authorized"] is False
