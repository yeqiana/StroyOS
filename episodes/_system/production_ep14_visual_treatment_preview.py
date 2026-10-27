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
        "treatment":"真实生活随手拍微距，接待主管的纯白硬挺高领、炭灰色细镶边和颈部上方自然完整的皮肤。她礼貌说话时，衣料边缘轻微起伏，投下不规则柔和阴影，营造细微的不安。室内自然光，浅景深，竖幅4:5。",
        "scene":"接待主管高立领微距，白色硬挺衣料、炭灰细边、自然皮肤与轻微衣褶阴影。普通真实照片质感，略有抓拍感，室内柔光，4:5竖构图。",
        "preserve":["接待主管","白色高领与炭灰细边","近距离机位","不安的异常感"],
        "medium":"photographic observational close-up"
    },
    29:{
        "treatment":"阿泽瞬间闪现的主观幻视，画面不是客观实拍。与银刀碰触膏体时相同的45度俯角：潮湿石壁前一块暗红色树脂漆板，板面铺有紫色枝蔓纹。年长者的手握古旧青铜装饰刀，轻触漆面，留下琥珀色树脂色痕。45度俯视、竖幅4:5、明确主观意象。",
        "scene":"非实拍主观幻视，45度俯视，石壁前暗红树脂漆板、紫色枝状装饰纹理、年长者手持古旧青铜工具轻触漆面，琥珀色树脂色痕。民俗手工艺静物质感，4:5竖幅。",
        "preserve":["阿泽主观幻视","与上一刀切动作匹配的45度俯角","青铜古器","紫色枝纹与琥珀色痕迹"],
        "medium":"symbolic non-photographic subjective insert"
    },
    48:{
        "treatment":"第一人称视角从白色客房移门处低角度观察，门缝下伸出一张黄色硬纸签，纸签有三行朱砂色的小楷书写痕迹。远处晓雨手握折叠户外工具的姿态虚焦，重点是纸签作为谜团证物。精确文字留待后期字幕由原故事校对。室内自然暗光，4:5竖幅。",
        "scene":"白色客房移门门槛的真实手持照片视角，黄色硬纸签从门缝露出，三行朱砂色书写笔触；背景人物与折叠户外工具轻微虚焦，纸签锐利对焦，室内自然暗光，4:5竖幅。精确文字后期处理。",
        "preserve":["客房白色移门","门缝黄色纸签","三行朱砂小楷","第一人称发现线索与悬念"],
        "medium":"photographic evidence detail"
    },
}

def _sha(data: bytes)->str:
    return hashlib.sha256(data).hexdigest()

def _sha_json(data:dict)->str:
    return _sha(json.dumps(data,ensure_ascii=False,sort_keys=True,
                           separators=(",",":")).encode("utf8"))

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
    if original_excerpt in proposed:
        raise ValueError("OLD_REJECTED_STORYBOARD_LEAK")
    material={
        "schema_version":SCHEMA,"frame":frame,
        "old_frame_contract_sha256":old_contract,
        "old_storyboard_excerpt_sha256":old_excerpt,
        "old_scene_prompt_sha256":old_scene,
        "treatment_sha256":_sha_json(treatment),
        "proposed_render_excerpt_sha256":_sha(new_excerpt.encode("utf8")),
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
