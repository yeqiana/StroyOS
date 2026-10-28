"""Offline, SHA-bound visual treatment preview for Episode14 safety-refused frames.

The locked storyboard/story remain historical narrative authority; the old
storyboard and its embedded old image prompt must NEVER be sent to the provider
in an alternate visual render. This module only produces *unapproved* preview
data. It cannot reserve an Attempt, write a prompt package, alter an asset,
change review authority, or enable paid dispatch.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import frame_contract

ROOT=Path(__file__).resolve().parents[2]
EP=ROOT/"episodes"/"00_独立篇"/"14_深渊疗愈所_第一集_净土生命还原"
SCHEMA="ep14_render_treatment_draft_v1"
# Original frame contract / original immutable scene SHA / reviewed storyboard excerpt SHA.
ORIGINAL={
    9:("8f380693ebcc5a356883d8c57c5c34b27bbd1acba133d17be40ab65fc62139fe",
       "01a340404ed87adb9babc7dbfba1c833186b4750c629c9c1772048db6e1d55bf",
       "6852f83e00ab3971fab203578902d443fb43dd654853f56cc547703dc8eca016"),
    29:("178f9d815f7256c2d3aebd794b2dd4e45277c2fbac4287b40cd8bb1f7a410943",
        "fe22125c51cd95da3996e957998e8a6f0f9a3ad662184ecb8dd83be1784e8039",
        "cd37efc8be7f5a29bcc860f6d7bba696c94ab67d7f0f27501814b024d4d35fd4"),
    48:("dacd3c3243b1408068dbcfadac09081e82157bdc0d3f1e0323e1183d9803daed",
        "29e24fb9972e85ede43f5be254883c0148b513e55109ebe5ffbf8fdcf1ac762a",
        "10cb0d6358128fa4d1d4752e02fd9fc6f54b306948cc3530d2869371f215ee08"),
}
# Only the renderable visual treatment. Narrative/dialogue/script remain locked
# separately and are NOT reinterpreted as permission to revise the story.
VISUAL={
    9:{
        "treatment":"[REC] 阿泽的第一人称近距离手持摄影，焦点落在三十岁女性接待主管的纯白硬挺高立领与2mm炭灰细滚边。衣领后方布料被一个约拳头大小的圆润轮廓均匀顶起，外表仍只有完好衣料；主管每次吞咽时这个圆润衣领轮廓都产生幅度很小、节律清楚的同步起伏。衣领上方自然完整的皮肤可见，无伤口、无液体、无身体组织裸露。室内暖光、微距浅景深、4:5竖幅。",
        "scene":"第一人称[REC]近距离手持微距，三十岁女性接待主管纯白高立领与2mm炭灰细边在清晰焦点；领后硬挺白色衣料形成约拳头大小的平滑圆形外撑轮廓，随她吞咽微微规律起伏，皮肤自然完整，无伤无血、完全被衣服覆盖。真实室内暖光、轻微抓拍感、4:5竖幅。",
        "preserve":["女性接待主管","纯白高立领与2mm炭灰细边","衣领后拳头大小的圆润外撑轮廓","随吞咽有规律的轻微衣料起伏","阿泽第一人称[REC]微距"],
        "medium":"photographic first-person [REC] macro"
    },
    29:{
        "treatment":"[NON-REC] 仅存在于阿泽意识中的0.1秒主观幻视，不是摄影机捕捉的影像，也不是已证实的地下往事。第28帧已记录餐桌银刀在45度俯角下对准冻膏正中，此主观心象只匹配45度俯角和中心对位，不虚构Frame28刀刃方向：潮湿暗洞背景，仅见一只枯槁老手（黄斑、青筋凸起，只有手部入镜、无人物全身）握旧青铜弯刀，青铜弯刀在深红色厚树脂漆板中心对位处切入一道细缝，紫色枝状纹路是板面特征，琥珀红色的清亮漆液从缝隙缓慢渗出，此视觉对应未宣称Frame28提供了切入运动方向证据。所有材料都是非生物工艺品；没有人体组织或受伤者。强烈的心理惊悚视觉、4:5竖幅。",
        "scene":"阿泽脑中突发的[NON-REC]非实拍主观幻视：依据第28帧银刀对准冻膏正中、45度俯角的锁定来源，只匹配45度角和中心对位，实际刀刃切入方向仍未有源证据；仅见一只枯槁老手（黄斑、青筋凸起，只有手入镜、无人物全身）握旧青铜弯刀在深红色厚树脂漆板中心切入，板面有紫色枝状装饰纹，切出一道细缝，琥珀红色非生物漆液从缝边浮出。暗洞石壁，心理时间提示为0.1秒，仅呈现一张静态图文心象，不生成视频、不要求实际时长或转场，明确非生物材料、无人受伤、非历史实录，4:5。",
        "preserve":["阿泽瞬间主观幻视、非REC","参照第28帧银刀对准冻膏正中、45度俯角的中心对位，不宣称来源记录了切入方向","古青铜弯形工具的切入动作","紫色分叉纹路与琥珀红漆液","非已证实的历史事实"],
        "medium":"symbolic non-REC subjective visual insert",
        "editorial_timing_cue":{
            "source":"docs/storyboard.md Frame 29",
            "subjective_insert_intended_duration_ms":100,
            "still_image_cannot_encode_duration":True,
            "production_format":"image_and_text_not_video",
            "static_composition_reference_frame":28,
            "composition_reference_scope":"Frame28 45-degree angle and knife aimed at jelly center only; NOT verified cutting gesture",
            "editorial_semantics":"STATIC IMAGE AND TEXT ONLY; 100ms is mental narrative time, not encoded clip duration or moving transition"
        }
    },
    48:{
        "treatment":"[REC] 阿泽从客房窗边猛地拉合窗帘、转身（窗外景色不入画），保持阿泽肩高度持机的第一人称视角（不可出现阿泽自己的肩部）。晓雨仍守在昏迷的林岚身边，握着收拢状态的折叠工兵铲并指向没有机械锁孔的白色移门。镜头下移对焦于从门底塞进来的巴掌大黄色硬纸签，纸签本体是平整连续的纯空白黄纸，无字、无横线、无框、无三行占位符或排版标记；实际三行朱砂小楷仅由后期按锁定原文叠加，不让生成模型造字。人物和动作仍清晰可辨而证物更锐利；夜间客房暖暗光、4:5竖幅。",
        "scene":"[REC] 阿泽从窗边完全拉合窗帘后转身拍摄的第一人称肩高度持机视角（窗帘遮蔽窗外，雾景不可见）（不可出现阿泽自己的肩部）；守在昏迷林岚身边的晓雨，手握折叠工兵铲、指向白色无锁孔移门；门底露出巴掌大黄色硬纸签，纸签为整块平整连续的空白黄色硬纸，无字、无横线、无框、无三行占位符及排版标记；保留足够纸面供后期按锁定原文叠加三行朱砂字。纸签锐利、人物与工兵铲仍清楚可辨，真实客房暖暗光，4:5。",
        "preserve":["阿泽从窗边转身的[REC]第一人称","晓雨守在林岚身边","折叠工兵铲指向门","无机械锁孔的白色移门","黄色纸签三行朱砂小楷、准确正文由后期叠加"],
        "medium":"photographic first-person evidence close-up",
        "postproduction_text_overlay":{
            "render_in_image_model":False,
            "source":"docs/storyboard.md Frame 48",
            "position":"yellow slip below white sliding door",
            "lines":["福主林岚，骨重八斤七两。","堪作中堂主梁，名录已入。","明日下元醮子时，受戒入桩。"],
            "overlay_authority":"locked-storyboard-exact-text-only"
        }
    },
}


def _sha(data: bytes)->str:
    return hashlib.sha256(data).hexdigest()

def _sha_json(data:dict)->str:
    return _sha(json.dumps(data,ensure_ascii=False,sort_keys=True,
                           separators=(",",":")).encode("utf8"))

def _rebind_section(text: str, heading: str, revise) -> str:
    """Revise a JSON render-only block, never the locked underlying authority."""
    marker="\n["+heading+"]\n"
    if text.count(marker)!=1:
        raise ValueError("RENDER_OVERRIDDEN_SECTION_NOT_UNIQUE:"+heading)
    start=text.index(marker)+len(marker)
    end=text.find("\n[",start)
    if end<0:
        raise ValueError("RENDER_OVERRIDDEN_SECTION_NOT_CLOSED:"+heading)
    try:
        original=json.loads(text[start:end].strip())
    except (TypeError,ValueError) as exc:
        raise ValueError("RENDER_OVERRIDDEN_SECTION_NOT_JSON:"+heading) from exc
    if not isinstance(original,dict):
        raise ValueError("RENDER_OVERRIDDEN_SECTION_NOT_OBJECT:"+heading)
    import copy
    revised=revise(copy.deepcopy(original))
    if not isinstance(revised,dict) or revised==original:
        raise ValueError("RENDER_OVERRIDE_EMPTY:"+heading)
    rendered=json.dumps(revised,ensure_ascii=False,sort_keys=True,separators=(",",":"))
    return text[:start]+rendered+"\n"+text[end:]


def _restore_untruncated_review_blocks(text: str, source: dict) -> str:
    """Restore full review-only JSON from SHA-bound source when compiler truncated it."""
    for heading, key in (
        ("CHARACTER / POV CONTRACT", "character_contract"),
        ("CHARACTER VISUAL / ORIGINAL IDENTITY", "character_visual_contract"),
    ):
        marker = "\n[" + heading + "]\n"
        if marker not in text:
            continue  # minimal historical test fixtures
        begin = text.index(marker) + len(marker)
        end = text.find("\n[", begin)
        if end < 0:
            raise ValueError("REVIEW_CHARACTER_BLOCK_NOT_CLOSED:" + heading)
        original = text[begin:end].strip()
        if not original.endswith("…"):
            try:
                json.loads(original)
            except ValueError as exc:
                raise ValueError("REVIEW_CHARACTER_BLOCK_NOT_COMPLETE_JSON:" + heading) from exc
            continue
        material = source.get("hash_material")
        if not isinstance(material, dict) or not isinstance(material.get(key), dict):
            raise ValueError("REVIEW_FULL_SOURCE_JSON_MISSING:" + key)
        complete = json.dumps(
            material[key], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if not complete.startswith(original[:-1]):
            raise ValueError("REVIEW_CHARACTER_SOURCE_PROJECTION_DRIFT:" + key)
        text = text[:begin] + complete + "\n" + text[end:]
    return text


def _derived_device_profile(text:str, frame:int)->str:
    start="----- LOCKED DEVICE CAPTURE PHYSICS -----\n"
    stop="----- END LOCKED DEVICE CAPTURE PHYSICS -----"
    if start not in text and stop not in text:
        return text  # Minimal synthetic contract used by unit test fixtures.
    if text.count(start)!=1 or text.count(stop)!=1:
        raise ValueError("RENDER_DEVICE_PROFILE_SOURCE_UNRECOGNIZED")
    a=text.index(start);b=text.index(stop,a)+len(stop)
    active=("NONE: frame 29 is a NON-REC internal subjective insert, no camera made the image"
            if frame==29 else
            "Sony A7S3 mirrorless held by Ah Ze (P01), [REC] story-locked camera")
    derived=("----- FRAME-LOCAL DEVICE EVIDENCE (RENDER ONLY) -----\n"
             +"active_capture_device="+active+"\n"
             +"source_priority=locked_episode_story_over_generic_M00_capture_style\n"
             +"no_simulated_phone_camera_or_fake_device_metadata=true\n"
             +"----- END FRAME-LOCAL DEVICE EVIDENCE -----")
    return text[:a]+derived+text[b:]


def _derived_context_consistency(text:str,frame:int)->str:
    text=_derived_device_profile(text,frame)
    def continuity(d):
        a=dict(d.get("anchors") or {})
        a["location"]={9:"white_lobby",29:"subjective_cave_insert",
                       48:"guest_room"}[frame]
        a["weather_time"]={9:"warm white lobby interior at night; no rain indoors",
                           29:"instant subjective vision while physical body remains indoors dining hall",
                           48:"late night inside heated white guest room; cold fog outside"}[frame]
        a["key_prop"]=("no recorded device for frame 29; physical A7S3 remains in dining hall"
                       if frame==29 else "Sony A7S3 camera held by Ah Ze, the [REC] photographer")
        d["anchors"]=a
        return d
    text=_rebind_section(text,"CONTINUITY",continuity)
    if frame==29:
        def subjective_directive(d):
            d["frame_mode"]="subjective_nonrecorded_insert"
            cues=list(d.get("required_visual_cues") or [])
            cues.append("No REC, no camera metadata, no real flashback; 45 degree match-cut with Frame28")
            d["required_visual_cues"]=cues
            return d
        def subjective_world(d):
            old=dict(d.get("recorder") or {})
            d["recorder"]={
                "active_device":"NONE_FOR_THIS_SUBJECTIVE_FRAME",
                "physical_scene_device":old.get("active_device") or "Sony A7S3",
                "photographer_id":"P01",
                "no_physical_recording_of_imagined_cave":True,
            }
            return d
        def subjective_core(d):
            info=dict(d.get("narrative_evidence") or {})
            info["new_information_this_frame"]="Unexpected subjective association; NOT a camera record or verified past event"
            d["narrative_evidence"]=info
            return d
        text=_rebind_section(text,"FRAME DIRECTIVE",subjective_directive)
        text=_rebind_section(text,"PERSISTENT WORLD STATE",subjective_world)
        text=_rebind_section(text,"VISUAL NARRATIVE CORE V2.2",subjective_core)
    if frame==48:
        def interior_wardrobe(d):
            d["location_type"]="indoor"
            d["scene_context"]="inside heated guest room, near white sliding door"
            return d
        def ahze_camera(d):
            d["device_position"]="Ah Ze holds camera at shoulder height, but Ah Ze's own shoulder is OUT of frame"
            d["framing_constraint"]="first-person camera-owner is Ah Ze; no photographer body or phantom third camera"
            return d
        text=_rebind_section(text,"SCENE-AWARE WARDROBE",interior_wardrobe)
        text=_rebind_section(text,"CAPTURE EVENT",ahze_camera)
    return text


def _derived_capture_revision(text: str, frame:int) -> str:
    if frame==9:
        def collar_capture(d):
            d["framing_constraint"]="[REC] macro of stiff white collar, round fully clothed contour and precise rhythm of fabric motion"
            d["retained_reason"]="Near-field first-person proof of unusual collar movement, without exposed biology"
            return d
        def collar_shot(d):
            d["anomaly_concealment"]=dict(d.get("anomaly_concealment") or {})
            d["anomaly_concealment"]["physical_anchor"]="smooth outward contour of intact stiff white collar fabric"
            return d
        text=_rebind_section(text,"CAPTURE EVENT",collar_capture)
        text=_rebind_section(text,"SHOT PROGRESSION / ACTION / ANOMALY LOGIC",collar_shot)
    elif frame==29:
        def subjective_capture(d):
            d.update({
                "capture_device":"NONE_NON_REC_SUBJECTIVE_INSERT",
                "device_position":"mental 45-degree angle matched to frame 28; not camera footage",
                "photographer_id":"P01_INTERNAL_VISION",
                "framing_constraint":"identical 45-degree angle and cutting gesture; no REC overlay",
                "why_capture_now":"NON_REC: abrupt hallucination triggered by silver knife cutting food",
                "retained_reason":"Subjective vision is neither recording nor verified historic memory",
                "operator_state":"subjective involuntary impression",
            })
            return d
        def subjective_shot(d):
            d.update({
                "action":"0.1-second 45-degree match-cut as silver knife enters jelly; old curved bronze tool cuts nonbiological lacquer-resin board",
                "camera_position":"subjective identical 45-degree top-down composition, NON_REC",
                "capture_purpose":"NOT_CAPTURED: subjective hallucination, not historical proof",
                "pov_mode":"Aze_subjective_nonrecorded_NonREC",
                "primary_subject":"bronze tool cutting a decorated red lacquer-resin board",
                "visual_function":"psychological match-cut; implied uncanny danger without depicting bodily injury",
                "location_zone":"subjective_dark_cave_vision_not_physically_entered",
                "emotion":{"intensity":3,"response_sync":"instant","state":"intrusive_horror","trigger":"silver knife cutting food"},
            })
            return d
        def subjective_temporal(d):
            d["elapsed_minutes_from_prev"]=0
            d["transition_reason"]="instant mental flash; physical scene remains dining hall"
            d["weather"]="not a physical transition; cave imagery is only subjective"
            return d
        def subjective_global_capture(d):
            d["primary_capture"]={"device":"NONE_NON_REC_INTERNAL_VISION","id":"subjective_frame29"}
            d["shooting_reason"]="not photographed: an involuntary subjective impression at silver-knife contact"
            d["secondary_captures"]=[]
            d["secondary_source_explanation"]="NO REC or camera file for this mental insert"
            return d
        def subjective_narrative(d):
            authored=dict(d.get("camera_authorship") or {})
            authored.update({
                "camera_owner":"P01_INTERNAL_VISION",
                "camera_owner_must_be_physically_explainable":False,
                "camera_position":"45-degree composition matched to prior recorded dining-table shot",
                "capture_device":"NONE_NON_REC_INTERNAL_VISION",
                "device_state":"no_camera_subjective_insert",
                "owner_class":"subjective_character_consciousness",
                "pov_mode":"subjective_Aze_nonREC",
            })
            d["camera_authorship"]=authored
            moment=dict(d.get("moment") or {})
            moment["save_reason"]="Aze intrusive image is not video footage or verified past event"
            d["moment"]=moment
            return d
        text=_rebind_section(text,"CAPTURE / AUTHENTICITY",subjective_global_capture)
        text=_rebind_section(text,"CAPTURE EVENT",subjective_capture)
        text=_rebind_section(text,"SHOT PROGRESSION / ACTION / ANOMALY LOGIC",subjective_shot)
        text=_rebind_section(text,"TEMPORAL CONTINUITY",subjective_temporal)
        text=_rebind_section(text,"VISUAL NARRATIVE CORE V2.2",subjective_narrative)
        for stale in ("地底闪回","Personal evidence from the travelers first person camera"):
            if stale in text:
                raise ValueError("RENDER_SUBJECTIVE_CAMERA_CONTRADICTION:"+stale)
    return _derived_context_consistency(text,frame)


def _review_v4_remaining_conflicts(text: str, ep: Path, frame: int) -> str:
    """Frame-local review candidate only; no mutation of the locked source contract."""
    if frame == 9:
        return text

    if frame == 29:
        def scoped_global(old):
            begin = "----- GLOBAL CAPTURE GRAMMAR -----"
            end = "----- END GLOBAL CAPTURE GRAMMAR -----"
            if old.count(begin) != 1 or old.count(end) != 1:
                raise ValueError("NONREC_GLOBAL_GRAMMAR_BLOCK_NOT_UNIQUE")
            a = old.index(begin)
            b = old.index(end, a) + len(end)
            replacement = (
                "----- FRAME 29 NON-REC GRAMMAR EXCEPTION -----\n"
                "mode=NON_REC_P01_internal_subjective_vision\n"
                "real_photographer=NONE_FOR_THIS_FRAME\n"
                "physical_camera=NONE_FOR_THIS_FRAME\n"
                "handheld_recording=false\n"
                "save_reason=not_applicable_to_nonrecorded_mental_image\n"
                "scene_is_not_verified_past_or_real_cave\n"
                "match_cut=frame28_45_degree_center_aim_only_cut_direction_unverified\n"
                "----- END FRAME 29 NON-REC GRAMMAR EXCEPTION -----")
            return (old[:a] + replacement + old[b:]).replace(
                "capture physics and story era override decorative texture",
                "frame29 mental image has no physical capture; narrative and story era remain locked").replace(
                "do not silently substitute another visual profile or capture grammar",
                "frame29 explicitly overrides physical capture grammar only for NON-REC mental image")
        text = _review_section_text(text, "VISUAL DNA", scoped_global)

        def auth(d):
            d["photographer"] = None
            d["primary_capture"] = {"device": "NONE_NON_REC_INTERNAL_VISION", "id": "subjective_frame29"}
            d["shooting_reason"] = "not recorded; involuntary P01 mental image"
            d["capture_states"] = {"stable": "NON_REC exemption: physical capture rules not applicable",
                                   "restricted": "not a real scene", "lost_control": "not a recording"}
            return d
        text = _rebind_section(text, "CAPTURE / AUTHENTICITY", auth)
        text = _rebind_section(text, "SHOT PROGRESSION / ACTION / ANOMALY LOGIC",
            lambda d: dict(d, continuity_exception_reason="non-recorded mental insert; real body stays in dining hall",
                scene_position_id="subjective_inner_image_29",
                action="阿泽突发主观心象：第28帧银刀对准冻膏正中且45度俯角；本帧青铜弯刀在对应中心位置切开漆板，不假定真实刀刃方向",
                primary_subject="青铜弯刀切暗紫枝纹红色非生物树脂板（nonbiological lacquer-resin board），琥珀红树脂液渗出",
                emotion={"state": "intrusive_horror", "intensity": 3, "response_sync": "instant",
                         "trigger": "silver table knife touches and cuts the jelly"},
                lighting_design={"contrast_mode": "dark subjective cave",
                                 "invented_cinematic_light": False,
                                 "physically_motivated": False,
                                 "practical_source": "NON_REC_no_physical_ceiling_light",
                                 "suspense_function": "resin cut against damp dark stone"}))
        text = _rebind_section(text, "SCENE-AWARE WARDROBE",
            lambda d: dict(d, activity="阿泽瞬间闯入非实拍的主观心象（不是历史闪回）",
                         scene_context="NON_REC dark cavern imagery; real body remains dining_hall",
                         weather="nonphysical imagined damp cave; actual dining hall remains warm and dry"))
        text = _rebind_section(text, "ENVIRONMENT PHYSICS",
            lambda d: {"condition": "NON_REC subjective imagery: damp dark cave; physical Aze remains in dining hall",
                       "time_of_day": "psychological instant, real world night",
                       "physical_cues": ["nonbiological lacquer-resin panel with branching purple pattern",
                                         "curved bronze knife precisely cuts resin and amber-red resin seeps out"],
                       "lighting": "indeterminate imagined low ambient visibility, NOT ceiling light",
                       "ground_state": "dark stone in imagined cavern, not dining floor",
                       "visibility": "close-up showing withered elderly hand with age spots and raised tendons gripping curved bronze blade, central resin groove, purple branching decoration, amber-red resin liquid and imagined damp cave stone background; no full person or real camera",
                       "wind": "not applicable to mental image",
                       "precipitation": "not applicable",
                       "temperature_feel": "imagined cave dampness, not real environment",
                       "conditional_effects": []})
        def narrative(d):
            d["narrative_evidence"]["continuity_exception_reason"] = (
                "NON_REC psychological insertion, not a flashback nor physical relocation")
            d["human_response"] = {
                "human_present": True,
                "emotion": {"state": "intrusive_horror", "intensity": 3,
                            "response_sync": "instant",
                            "trigger": "silver table knife touches and cuts the jelly"},
                "interaction": {"type": "mental_reaction", "actor": "P01", "target": "subjective resin cut",
                                "action": "involuntary NON_REC perception", "meaningful": True},
            }
            d["moment"]["action_in_progress"] = "阿泽突发主观心象：青铜弯刀切开树脂板"
            d["moment"]["save_reason"] = "No camera recording; static narrative frame shows a mental instant"
            d["shot_grammar"].update(
                family="P01_internal_non_recorded_mental_insert",
                location_zone="imagined_dark_cave_not_physical_dining_hall")
            d["camera_authorship"].update(
                camera_owner="P01_INTERNAL_CONSCIOUSNESS",
                camera_position="no camera; 45-degree subjective match cut to Frame28",
                capture_device="NONE_NON_REC_INTERNAL_VISION",
                device_state="not_recorded")
            return d
        text = _rebind_section(text, "VISUAL NARRATIVE CORE V2.2", narrative)
        # The original locked storyboard row establishes angle and plate center.
        storyboard = (ep / "docs/storyboard.md").read_text(encoding="utf8")
        source_rows = [line for line in storyboard.splitlines() if line.startswith("| 28 |")]
        if len(source_rows) != 1 or "45 度俯角" not in source_rows[0] or "对准膏块正中" not in source_rows[0]:
            raise ValueError("FRAME28_LOCKED_MATCH_CUT_SOURCE_UNVERIFIED")
        from hashlib import sha256
        evidence = ("[LOCKED FRAME28 MATCH CUT SOURCE]\n"
                    + "sha256=" + sha256(source_rows[0].encode("utf8")).hexdigest() + "\n"
                    + "storyboard_frame28=" + source_rows[0] + "\n"
                    + "Frame28 proves 45-degree top-down angle and silver knife aimed at the plate center only; it does NOT prove a cut already happened or the movement direction. Frame29 uses the same angle and center alignment; no claimed direction or pixel-perfect match. Verify actual visual consistency later during image review.\n\n")
        marker = "[FRAME DIRECTIVE]\n"
        if text.count(marker) != 1:
            raise ValueError("FRAME29_DIRECTIVE_MISSING")
        text = text.replace(marker, evidence + marker, 1)
        for forbidden in ("0.1 秒极速闪回硬切", "银刀切入餐盘", "旧青铜礼器"):
            if forbidden in text:
                raise ValueError("FRAME29_OLD_SEMANTICS_REMAIN:" + forbidden)
        # V6: every generated field must honor the locked Frame28 evidence boundary.
        # This changes the unapproved review candidate only, not canonical Story/Frame28.
        def still_capture_event(d):
            d["framing_constraint"] = (
                "STATIC IMAGE: 45-degree top-down framing and center alignment only, "
                "matching Frame28 knife AIMED at the jelly center; NO proof of cutting gesture "
                "or movement direction; no REC overlay or camera")
            d["why_capture_now"] = (
                "NOT CAPTURED: sudden psychological image triggered by noticing "
                "the silver knife aimed at the jelly center in Frame28; "
                "no verified cutting motion in Frame28")
            d["device_position"] = (
                "NO PHYSICAL CAMERA: mental static composition at 45 degrees, "
                "aligned to Frame28 plate center only")
            return d
        text = _rebind_section(text, "CAPTURE EVENT", still_capture_event)
        def still_directive(d):
            d["required_visual_cues"] = [
                "static subjective NON-REC image echoes Frame28's 45-degree angle and "
                "knife aimed at jelly center; no verified Frame28 cutting direction",
                "ONLY one withered old hand with age spots and raised tendons, gripping curved bronze knife, cuts center of nonbiological red resin panel "
                "with purple branching decoration and amber-red resin liquid",
                "dark cave is an involuntary mental image, NOT a real site or proof of earlier events",
                "one still image; no video edit, transition, motion continuity, real duration or REC metadata",
            ]
            return d
        text = _rebind_section(text, "FRAME DIRECTIVE", still_directive)
        def still_shot(d):
            d["emotion"]["trigger"] = (
                "Frame28 silver knife AIMED at jelly center, not a verified cut")
            d["visual_function"] = (
                "STATIC composition echo of Frame28 angle and center alignment; "
                "mental horror, NOT a video match-cut or verified physical event")
            return d
        text = _rebind_section(
            text, "SHOT PROGRESSION / ACTION / ANOMALY LOGIC", still_shot)
        def mental_world(d):
            d["render_scope"] = (
                "REAL_WORLD_BACKGROUND_ONLY: P01 P02 P03 statuses, wardrobe, "
                "Sony A7S3 and dining room are physical continuity context only; "
                "NONE of these companions, devices or restaurant setting shall appear "
                "inside the NON_REC mental cave image")
            for person in ("P01", "P02", "P03"):
                d["characters"][person]["visible_in_this_mental_image"] = False
            d["recorder"]["photographer_id"] = None
            d["recorder"]["active_device"] = "NONE_FOR_THIS_SUBJECTIVE_FRAME"
            return d
        text = _rebind_section(text, "PERSISTENT WORLD STATE", mental_world)
        def mental_wardrobe(d):
            d["render_scope"] = (
                "REAL_WORLD_BACKGROUND_ONLY: all clothing and present fields describe "
                "people in the physical dining room, not the NON_REC mental image. "
                "Do not depict P01, P02 or P03 or their costumes in the cave")
            for person in ("P01", "P02", "P03"):
                d["outfits"][person]["render_in_this_mental_image"] = False
            return d
        text = _rebind_section(text, "SCENE-AWARE WARDROBE", mental_wardrobe)
        def still_narrative(d):
            d["human_response"]["emotion"]["trigger"] = (
                "Frame28 silver knife AIMED at jelly center, not an actual cut")
            d["camera_roster_policy"]["primary_photographer_required"] = False
            d["camera_roster_policy"]["frame29_nonrec_exception"] = (
                "NO cameraman, no camera file, no companions or dining-room people in "
                "subjective cave rendering; physical-camera defaults do not apply")
            d["camera_authorship"]["camera_position"] = (
                "NO CAMERA: static 45-degree top-down subjective composition, "
                "center aligned with Frame28 plate only; not a video match cut")
            d["sequence_grammar"] = {
                **dict(d.get("sequence_grammar") or {}),
                "selection": "FRAME29_NONREC_STATIC_MENTAL_IMAGE_EXCEPTION",
                "render_applicability": "NOT APPLICABLE: SG01 personal-evidence capture grammar governs only the physical dining-room continuity",
                "no_real_scene_camera_or_person_in_mental_frame": True,
                "composition_reference": "static 45-degree angle and plate-center aim from Frame28, no inferred cutting motion",
            }
            memory = dict(d.get("visual_memory_continuity") or {})
            memory["physical_scene_background_persist"] = list(memory.get("persist") or [])
            memory["persist"] = []
            memory["render_applicability"] = (
                "NON_REC mental image does NOT inherit real participants, wardrobe, "
                "A7S3, carried props, dining room, weather or physical lighting; "
                "the only cross-frame reference is static 45-degree angle and center alignment")
            memory["time_reversal_requires_explicit_flashback_or_jump"] = False
            d["visual_memory_continuity"] = memory
            d["narrative_evidence"]["visual_editing_scope"] = (
                "STATIC TWO-IMAGE COMPOSITIONAL ECHO ONLY; no frame-to-frame "
                "motion continuity, actual duration, video or historical flashback")
            d["moment"]["save_reason"] = (
                "Static storytelling image of P01's NON_REC mental instant, "
                "not a saved camera file or a moving clip")
            return d
        text = _rebind_section(text, "VISUAL NARRATIVE CORE V2.2", still_narrative)
        return text

    if frame == 48:
        def world(d):
            d["location"] = "guest_room"
            d["characters"]["P02"]["status"] = "unconscious"
            d["characters"]["P02"]["clothing_anchor"] = "白色高领长袍（第22帧已换装）"
            d["props"]["P03"] = "折叠工兵铲；指向没有机械锁孔的白色移门"
            return d
        text = _rebind_section(text, "PERSISTENT WORLD STATE", world)
        def closed_curtain(d):
            d["physical_cues"] = [
                "closed curtain fully occludes outside fog/courtyard; no exterior is visible",
                "interior practical lights remain the source",
                "blank unmarked yellow paper slip lies beneath the closed white sliding door",
            ]
            d["visibility"] = "clear interior view only; closed curtain blocks outside sightline"
            return d
        text = _rebind_section(text, "ENVIRONMENT PHYSICS", closed_curtain)
        def shot(d):
            d.update(
                camera_position="阿泽客房窗边转身后肩高度持 Sony A7S3 的第一人称，无摄影者肩部",
                location_zone="guest_room",
                scene_position_id="guest_room_white_sliding_door_48",
                primary_subject="晓雨守着昏迷林岚，持折叠工兵铲指向无机械锁孔白色移门；门底黄色硬纸签",
                action="阿泽拉帘后持机转身，晓雨举折叠工兵铲指向白门，林岚昏迷",
                interaction={"actor": "P03", "target": "white_sliding_door",
                             "action": "Xiaoyu holds visible folding entrenching shovel pointing at white door while guarding unconscious Lin Lan",
                             "meaningful": True, "type": "point_out"},
            )
            return d
        text = _rebind_section(text, "SHOT PROGRESSION / ACTION / ANOMALY LOGIC", shot)
        def narrative(d):
            d["camera_authorship"]["camera_position"] = (
                "阿泽从客房窗边转身，肩高度本人第一人称REC摄影，自己的肩部和相机本体均不入镜")
            d["camera_authorship"]["active_camera_body_must_not_appear_in_frame"] = True
            d["shot_grammar"].update(
                family="AhZe_first_person_guest_room_REC_no_own_shoulder",
                location_zone="guest_room")
            d["human_response"]["interaction"] = {
                "actor": "P03", "target": "white_sliding_door",
                "action": "Xiaoyu holds visible folding entrenching shovel pointing at the white door beside unconscious Lin Lan",
                "meaningful": True, "type": "point_out"}
            d["moment"]["action_in_progress"] = (
                "Ah Ze turns from curtain; Xiaoyu keeps vigil over unconscious Lin Lan and points folding shovel toward door")
            d["narrative_evidence"]["new_information_this_frame"] = "yellow paper slip evidence beneath white door, exact text added in post"
            return d
        text = _rebind_section(text, "VISUAL NARRATIVE CORE V2.2", narrative)
        def wardrobe(d):
            d["outfits"]["P02"]["garments"] = ["白色高领长袍"]
            d["outfits"]["P02"]["look_id"] = "P02_WHITE_HIGH_COLLAR_POST_FRAME22"
            d["activity"] = "阿泽拉帘转身，晓雨守在昏迷的林岚旁拿工兵铲指向白色移门"
            return d
        text = _rebind_section(text, "SCENE-AWARE WARDROBE", wardrobe)
        def directive(d):
            d["required_visual_cues"] = [
                "white sliding door without mechanical keyhole",
                "yellow hard-paper slip beneath door has one continuous completely blank face; NO letters, no rules, no boxes, no three-row placeholder or typography marks; postproduction overlays exact three lines later",
                "Xiaoyu holds recognizable folding entrenching shovel pointed toward white door while guarding unconscious Lin Lan",
                "first-person Sony A7S3 REC from Ah Ze after turning from window, without Ah Ze's shoulder",
                "exact red text exists ONLY in editorial postproduction, not image generation",
            ]
            return d
        text = _rebind_section(text, "FRAME DIRECTIVE", directive)
        if "courtyard_and_airlock" in text or "过肩主观" in text:
            raise ValueError("FRAME48_STALE_LOCATION_OR_SHOULDER")
        return text
    raise ValueError("EP14_EXACT_FRAME_ONLY")


def _review_section_text(text: str, heading: str, revise) -> str:
    marker = "\n[" + heading + "]\n"
    if text.count(marker) != 1:
        raise ValueError("REVIEW_SECTION_NOT_UNIQUE:" + heading)
    a = text.index(marker) + len(marker)
    b = text.find("\n[", a)
    if b < 0:
        raise ValueError("REVIEW_SECTION_NOT_CLOSED:" + heading)
    replacement = revise(text[a:b].rstrip())
    return text[:a] + replacement + "\n" + text[b:]


def compile_candidate(ep:Path,frame:int)->dict:
    ep=Path(ep).resolve();frame=int(frame)
    if ep!=EP.resolve() or frame not in ORIGINAL:
        raise ValueError("EXACT_EP14_FRAME_SCOPE_REQUIRED")
    contract=frame_contract.compile_frame(ep,frame,write_cache=False)
    old_contract,old_scene,old_excerpt=ORIGINAL[frame]
    prompt=ep/"prompts"/"production"/f"{frame:02d}.txt"
    if (contract.get("contract_sha256")!=old_contract
            or (contract.get("storyboard_frame") or {}).get("sha256")!=old_excerpt
            or not prompt.is_file() or _sha(prompt.read_bytes())!=old_scene):
        raise ValueError("IMMUTABLE_SOURCE_CONTRACT_OR_SCENE_CHANGED")
    previous=contract["prompt_contract"]
    # Do NOT append new wording to a prompt that still includes old
    # storyboard text and embedded old generation instructions.
    beginning="[STORYBOARD FRAME]\n";ending="\n[VISUAL DNA]"
    if previous.count(beginning)!=1 or previous.count(ending)!=1:
        raise ValueError("RENDER_PROMPT_LAYOUT_UNRECOGNIZED")
    start=previous.index(beginning)+len(beginning)
    end=previous.index(ending,start)
    original_excerpt=(contract.get("storyboard_frame") or {}).get("text") or ""
    if not original_excerpt or original_excerpt not in previous[start:end]:
        raise ValueError("OLD_STORYBOARD_EXCERPT_NOT_BOUND")
    treatment=VISUAL[frame]
    new_excerpt=(
        "[ALTERNATIVE VISUAL TREATMENT, REVIEW PENDING]\n"
        +treatment["treatment"]+"\n"
        +"Treat this section as a proposed visual interpretation only; "
         "source story and exact dialogue remain under separate locked authority.\n"
    )
    proposed=previous[:start]+new_excerpt+previous[end:]
    proposed=_derived_capture_revision(proposed,frame)
    proposed=_restore_untruncated_review_blocks(proposed,contract)
    proposed=_review_v4_remaining_conflicts(proposed,ep,frame)
    if original_excerpt in proposed:
        raise ValueError("OLD_REJECTED_STORYBOARD_LEAK")
    material={
        "schema_version":SCHEMA,"frame":frame,
        "old_frame_contract_sha256":old_contract,
        "old_storyboard_excerpt_sha256":old_excerpt,
        "old_scene_prompt_sha256":old_scene,
        "treatment_sha256":_sha_json(treatment),
        "proposed_render_excerpt_sha256":_sha(new_excerpt.encode("utf8")),
        "derived_render_block_sha256":_sha(proposed.encode("utf8")),
    }
    render_sha=_sha_json(material)
    before=f"RESOLVED FRAME CONTRACT | frame={frame:02d} | sha256={old_contract}"
    if proposed.count(before)!=1:
        raise ValueError("OLD_CONTRACT_HEADER_NOT_FOUND")
    proposed=proposed.replace(before,
        f"PROPOSED RENDER TREATMENT | frame={frame:02d} | sha256={render_sha} | NOT YET AUTHORIZED",1)
    return {
        **material,
        "proposed_render_contract_sha256":render_sha,
        "proposed_render_contract_text":proposed,
        "proposed_scene_prompt":treatment["scene"],
        "preserved_story_beats":treatment["preserve"],
        "render_medium":treatment["medium"],
        "editorial_overlay_contract":treatment.get("postproduction_text_overlay"),
        "editorial_timing_cue":treatment.get("editorial_timing_cue"),
        "status":"INDEPENDENT_REVIEW_REQUIRED",
        "review_approved":False,
        "production_dispatch_authorized":False,
        "requires_new_canonical_prompt_package":True,
        "requires_paid_attempt_2_risk_ack":True,
    }

def compile_all(ep:Path)->dict:
    rows=[compile_candidate(ep,n) for n in sorted(ORIGINAL)]
    return {
        "schema_version":SCHEMA,
        "scope":"EP14_F009_F029_F048_REVIEW_ONLY",
        "frames":rows,"review_status":"PENDING",
        "image_calls":0,"attempts_reserved":0,"sql_writes":0,
        "storyboard_modified":False,"canonical_prompt_packages_modified":False,
        "production_dispatch_authorized":False,
        "preview_sha256":_sha_json({str(r["frame"]):r["proposed_render_contract_sha256"]
                                    for r in rows}),
    }

if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument("episode_dir",type=Path)
    a=parser.parse_args()
    print(json.dumps(compile_all(a.episode_dir),ensure_ascii=False,indent=2))
