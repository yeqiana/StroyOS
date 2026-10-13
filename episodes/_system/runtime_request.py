#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Story OS V2.1 Runtime Request compiler.

Natural-language input -> immutable runtime request.
This module captures user intent and execution parameters only.
It MUST NOT invent creative decisions such as climax frame, weather physics or frame directives.
"""
from __future__ import annotations

import argparse, datetime as dt, hashlib, json, re
from pathlib import Path
import storyos_config
import request_intent
import story_json
import runtime_request_persistence
import storage_config
import model_policy
import phase5a_collaborative_canary

ROOT = Path(__file__).resolve().parents[2]
REQUESTS_DIR = ROOT / "runtime" / "requests"
EPISODE_REL = Path("meta/runtime-request.json")
SCHEMA_VERSION = 1
DEFAULT_BRANCH = "story"
_CONFIG = storyos_config.load_config()
_IMAGE_PROFILE = model_policy.resolve("image.payload")
DEFAULT_IMAGE_MODEL = str(_IMAGE_PROFILE["model"])
DEFAULT_IMAGE_QUALITY = str(_IMAGE_PROFILE["quality"])
DEFAULT_MAX_IMAGE_WORKERS = int(storyos_config.get_path(_CONFIG, "production.max_inflight_images"))
STORY_MODES = {"auto_create", "user_seed", "core_constraints", "locked_story"}
LOCKED_SIGNALS = ("不要改剧情","剧情已锁定","剧情已经定了","严格按这个剧情","严格按这个故事","只能润色","故事结构不要动","不要改故事")
CONSTRAINT_SIGNALS = ("必须保留","不能改","一定要有","核心设定","结尾必须","必须有")
SEED_SIGNALS = ("剧情大概是","剧情大概","大概剧情","大概讲","故事大概是","我有个想法","我想的是","故事可以是","差不多是")
FULL_AUTO_SIGNALS = ("全自动","做到最终交付","不要每一步问","不用每一步问","一路做下去","直接做完")
RESUME_SIGNALS = ("使用 resume 模式","resume 模式","从上次验证通过的断点继续","从上次断点继续","从断点继续","继续上次断点","resume")
REPAIR_ONLY_SIGNALS = ("只修","只返修","repair only","repair_only")
RELEASE_ONLY_SIGNALS = ("只做发布","只做release","release only","release_only")
DATA_REVIEW_SIGNALS = ("只做复盘","数据复盘","data review","data_review")
PREPRODUCTION_SIGNALS = ("只做前期资产","只做前期","不要生成图片","不生图","做到可以正式生图的交接状态","做到生图交接状态","preproduction only","preproduction_only")
IMAGE_CONTINUE_SIGNALS = ("从生图开始","从图片开始","接管前期资产","接管已经完成的前期资产","不要重写剧情","image continue","image_continue")
CREATIVE_SECTION_MARKERS = ("【创作要求】", "[创作要求]", "创作要求：", "创作要求:")

def now():
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")
def read_text(path): return path.read_text(encoding="utf-8-sig")
def read_json(path):
    return story_json.read_json(path)
def write_json(path,data):
    story_json.write_json(path, data)
def contains_any(text,signals):
    low=text.lower(); return any(s.lower() in low for s in signals)
def request_id(text):
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")+"_"+hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def preimage_authority_projection(data):
    """Creative Runtime Request fields that can legitimately affect PREIMAGE.

    Image provider/model/quality, worker counts, delivery mode, request timestamps
    and retry/resume bookkeeping are execution concerns. Hashing the whole request
    made a provider-model upgrade falsely invalidate Character/Environment/World
    authority. Keep only fields PREIMAGE consumers actually use as creative input.
    """
    row=data if isinstance(data,dict) else {}
    provenance=row.get("provenance") or {}
    return {
        "topic": row.get("topic") or {},
        "story_input": row.get("story_input") or {},
        "creative_hints": row.get("creative_hints") or [],
        "visual_profile": row.get("visual_profile"),
        "provenance": {
            "source": provenance.get("source"),
            "original_request": provenance.get("original_request"),
        },
    }


def preimage_authority_projection_sha256(data):
    raw=json.dumps(preimage_authority_projection(data),ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def authority_sha256(data):
    row=data if isinstance(data,dict) else {}
    raw=json.dumps(row,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()

def parse_topic(text):
    for left,right in (("「","」"),("《","》"),("『","』"),('"','"'),("“","”")):
        if left in text and right in text:
            start=text.find(left)+len(left); end=text.find(right,start)
            if end>start:
                title=text[start:end].strip()
                if title:return title,title
    for pattern in (r"(?:做一篇|制作一篇|全自动做一篇|写一篇)\s*[：:]?\s*([^\n，。,.]{2,40})",r"(?:题目|主题|题材)\s*[：:]\s*([^\n]{2,60})"):
        m=re.search(pattern,text,flags=re.I)
        if m:
            title=m.group(1).strip(" \t。,.，")
            if title:return title,title
    return None,None

def parse_branch(text):
    m=re.search(r"(?:读取|使用|切到|切换到)?\s*([A-Za-z0-9._/-]+)\s*分支",text,flags=re.I)
    return (m.group(1),"user_explicit") if m else (DEFAULT_BRANCH,"system_default")

def parse_image_model(text):
    patterns=(r"\bimage\s*[:=]\s*([A-Za-z0-9._-]+)",r"图片模型\s*(?:用|使用|[:=])\s*([A-Za-z0-9._-]+)",r"图像模型\s*(?:用|使用|[:=])\s*([A-Za-z0-9._-]+)",r"(?:用|使用)\s+(gpt-image-[A-Za-z0-9._-]+)")
    for pattern in patterns:
        m=re.search(pattern,text,flags=re.I)
        if m:return {"provider":"openai","model":m.group(1),"source":"user_explicit","strict_model":True}
    return {"provider":"openai","model":DEFAULT_IMAGE_MODEL,"source":"system_default","strict_model":False}

def split_after_marker(text,markers):
    low=text.lower()
    for marker in markers:
        idx=low.find(marker.lower())
        if idx>=0:
            tail=text[idx+len(marker):].lstrip(" ：:\t\r\n")
            return tail.strip() or None
    return None

def extract_constraints(text):
    tail=split_after_marker(text,CONSTRAINT_SIGNALS)
    if not tail:return []
    rows=[]
    for raw in tail.splitlines():
        line=re.sub(r"^\s*(?:[-*•]|\d+[.)、])\s*","",raw).strip()
        if line and len(line)<=160: rows.append(line.rstrip("。；;"))
    if not rows:
        rows=[x.strip() for x in re.split(r"[；;]",tail) if x.strip()]
    return rows[:20]

def story_input(text):
    if contains_any(text,LOCKED_SIGNALS):
        return {"mode":"locked_story","raw":split_after_marker(text,LOCKED_SIGNALS) or text.strip(),"constraints":[],"rewrite_policy":"logic_polish_only","preserve_core_intent":True,"allow_structure_rewrite":False}
    if contains_any(text,CONSTRAINT_SIGNALS):
        return {"mode":"core_constraints","raw":text.strip(),"constraints":extract_constraints(text),"rewrite_policy":"preserve_constraints_optimize_rest","preserve_core_intent":True,"allow_structure_rewrite":True}
    if contains_any(text,SEED_SIGNALS):
        return {"mode":"user_seed","raw":split_after_marker(text,SEED_SIGNALS) or text.strip(),"constraints":[],"rewrite_policy":"strengthen_and_rewrite","preserve_core_intent":True,"allow_structure_rewrite":True}
    return {"mode":"auto_create","raw":None,"constraints":[],"rewrite_policy":"auto_create","preserve_core_intent":True,"allow_structure_rewrite":True}


def _explicit_creative_section(text):
    """Return (creative, operator-prefix) only for an explicit creative boundary.

    We intentionally do not guess from command-looking lines.  Existing requests
    without a declared creative section keep their legacy semantics; prompts that
    explicitly distinguish execution instructions from 创作要求 get a safe split.
    """
    raw=str(text or "")
    for marker in CREATIVE_SECTION_MARKERS:
        idx=raw.find(marker)
        if idx >= 0:
            creative=raw[idx+len(marker):].strip()
            operator=raw[:idx].strip()
            return (creative or None, operator or None)
    return None, None


def creative_request_view(data):
    """Derived creative-only view; never mutates the immutable Runtime Request."""
    row=data if isinstance(data,dict) else {}
    provenance=row.get("provenance") or {}
    creative_text,_operator=_explicit_creative_section(provenance.get("original_request"))
    if creative_text:
        parsed_story=story_input(creative_text)
        # An explicit creative section is user-supplied creative intent even when
        # it does not contain legacy seed trigger phrases. Treating it as
        # auto_create would discard the section because auto_create.raw is None.
        if parsed_story.get("mode")=="auto_create":
            parsed_story={
                "mode":"user_seed",
                "raw":creative_text,
                "constraints":[],
                "rewrite_policy":"strengthen_and_rewrite",
                "preserve_core_intent":True,
                "allow_structure_rewrite":True,
            }
        return {
            "topic": row.get("topic") or {},
            "story_input": parsed_story,
            "creative_hints": creative_hints(creative_text),
            "visual_profile": row.get("visual_profile"),
        }
    return {
        "topic": row.get("topic") or {},
        "story_input": row.get("story_input") or {},
        "creative_hints": row.get("creative_hints") or [],
        "visual_profile": row.get("visual_profile"),
    }


def execution_policy_view(data):
    """Derived execution-only view for runtime/router consumers."""
    row=data if isinstance(data,dict) else {}
    return {
        "mode": row.get("mode"),
        "repository": row.get("repository") or {},
        "intent": row.get("intent") or {},
        "image": row.get("image") or {},
        "image_model": row.get("image_model"),
        "image_quality": row.get("image_quality"),
        "runtime": row.get("runtime") or {},
        "delivery": row.get("delivery") or {},
        "user_intent": row.get("user_intent") or {},
    }


def operator_instructions_view(data):
    """Derived operator-only instructions, deliberately excluded from creative input."""
    row=data if isinstance(data,dict) else {}
    provenance=row.get("provenance") or {}
    _creative,operator=_explicit_creative_section(provenance.get("original_request"))
    return {
        "raw": operator,
        "source": "explicit_prefix_before_creative_section" if operator else "none",
    }


def partitioned_view(data):
    return {
        "creative_request": creative_request_view(data),
        "execution_policy": execution_policy_view(data),
        "operator_instructions": operator_instructions_view(data),
    }


def creative_source_text(data):
    """Plain text used by creative/character selection without operator commands."""
    creative=creative_request_view(data)
    story=creative.get("story_input") or {}
    bits=[
        str(((creative.get("topic") or {}).get("title")) or ""),
        str(story.get("raw") or ""),
        "\n".join(str(x) for x in (story.get("constraints") or [])),
        " ".join(str(x) for x in (creative.get("creative_hints") or [])),
    ]
    return "\n".join(x for x in bits if x)

def parse_mode(text):
    if contains_any(text,RESUME_SIGNALS):return "resume"
    if contains_any(text,IMAGE_CONTINUE_SIGNALS):return "image_continue"
    if contains_any(text,PREPRODUCTION_SIGNALS):return "preproduction_only"
    if contains_any(text,REPAIR_ONLY_SIGNALS):return "repair_only"
    if contains_any(text,RELEASE_ONLY_SIGNALS):return "release_only"
    if contains_any(text,DATA_REVIEW_SIGNALS):return "data_review"
    return "full_auto"

def creative_hints(text):
    out=[]
    for line in text.splitlines():
        s=line.strip()
        if s and len(s)<=160 and any(x in s for x in ("希望","不要太","画风","质感","天气","炎热","下雨","下雪","冲击力","第一视角")):out.append(s)
    return out[:20]

def compile_request(text):
    if not isinstance(text,str) or not text.strip():raise ValueError("EMPTY_REQUEST")
    title,raw_topic=parse_topic(text); story=story_input(text); mode=parse_mode(text)
    if mode=="image_continue" and story.get("mode")=="auto_create":
        story={"mode":"locked_story","raw":None,"constraints":[],"rewrite_policy":"logic_polish_only","preserve_core_intent":True,"allow_structure_rewrite":False}
    if not title:
        if story["mode"]=="auto_create":raise ValueError("EMPTY_REQUEST: no topic/title/story seed found")
        title="AUTO_TITLE"; raw_topic=None
    branch,branch_source=parse_branch(text)
    full_auto=contains_any(text,FULL_AUTO_SIGNALS) or mode in {"full_auto","preproduction_only","image_continue","resume","repair_only","release_only","data_review"}
    image=parse_image_model(text)
    intent=request_intent.resolve(text)
    expected_intent=request_intent.expected_intent_for_mode(mode)
    if intent.get("intent") != expected_intent:
        intent={**intent,"intent":expected_intent,"reason_codes":[*(intent.get("reason_codes") or []),f"MODE_OVERRIDE_{mode.upper()}"]}
    rid=request_id(text)
    data={
        "schema_version":1,"request_id":rid,"created_at":now(),"mode":mode,
        "repository":{"branch":branch,"source":branch_source},
        "topic":{"title":title,"raw":raw_topic},
        "story_input":story,
        "intent":intent,
        "creative_hints":creative_hints(text),
        "image_model":image["model"],
        "image_quality":DEFAULT_IMAGE_QUALITY,
        "image":{**image,"quality":DEFAULT_IMAGE_QUALITY},
        "runtime":{"execution_mode":str(storyos_config.get_path(_CONFIG,"runtime.execution_mode")),"continuous_execution":bool(full_auto),"resume":True,"max_image_workers":DEFAULT_MAX_IMAGE_WORKERS,"fail_soft":True,"incremental_reuse":True},
        "delivery":{"mode":"auto","zip_required_for_completion":False},
        "user_intent":{"full_auto_authorized":bool(full_auto),"allow_story_strengthening":story["mode"]!="locked_story","allow_story_rewrite":story["mode"] in {"auto_create","user_seed","core_constraints"},"ask_before_each_step":not bool(full_auto)},
        "provenance":{"source":"natural_language","original_request":text.strip(),"creative_request_id":rid},
    }
    errors=validate_request(data)
    if errors:raise ValueError("; ".join(errors))
    return data

def validate_request(data):
    errors=[]
    try:
        phase5a_collaborative_canary.reject_runtime_request_canary_fields(data)
    except phase5a_collaborative_canary.CanaryContractError as exc:
        errors.append(str(exc))
    if data.get("schema_version")!=1:errors.append("schema_version must be 1")
    if data.get("mode") not in {"full_auto","preproduction_only","image_continue","resume","repair_only","release_only","data_review"}:errors.append("invalid mode")
    story=data.get("story_input") or {}
    intent=data.get("intent") or {}
    if intent:
        expected_intent=request_intent.expected_intent_for_mode(str(data.get("mode")))
        if intent.get("intent") != expected_intent: errors.append("intent.intent must match runtime mode")
        if intent.get("source") != "deterministic_rules": errors.append("intent.source must be deterministic_rules")
    if story.get("mode") not in STORY_MODES:errors.append("invalid story_input.mode")
    if story.get("mode")=="user_seed" and not str(story.get("raw") or "").strip():errors.append("user_seed requires raw story seed")
    if story.get("mode")=="core_constraints" and not isinstance(story.get("constraints"),list):errors.append("core_constraints requires constraints list")
    image=data.get("image") or {}
    model=str(data.get("image_model") or image.get("model") or "").strip()
    quality=str(data.get("image_quality") or image.get("quality") or DEFAULT_IMAGE_QUALITY).strip().lower()
    if not model:errors.append("image model missing")
    if quality!=DEFAULT_IMAGE_QUALITY:errors.append(f"image_quality must be {DEFAULT_IMAGE_QUALITY} for formal production")
    if data.get("image_model") is not None and image.get("model") is not None and str(data["image_model"])!=str(image["model"]):errors.append("image_model must match image.model")
    if data.get("image_quality") is not None and image.get("quality") is not None and str(data["image_quality"]).lower()!=str(image["quality"]).lower():errors.append("image_quality must match image.quality")
    if image.get("source")=="user_explicit" and image.get("strict_model") is not True:errors.append("user_explicit image model requires strict_model=true")
    workers=(data.get("runtime") or {}).get("max_image_workers")
    if not isinstance(workers,int) or not 1<=workers<=5:errors.append("runtime.max_image_workers must be 1..5")
    if not str((data.get("topic") or {}).get("title") or "").strip():errors.append("topic.title missing")
    return errors

def write_compiled(data,output=None):
    target=output.resolve() if output else REQUESTS_DIR/f"{data['request_id']}.json"; write_json(target,data); return target
def bind_data(data,episode_dir,force=False,repository_root=None):
    episode_dir=Path(episode_dir).resolve()
    repo_root=Path(repository_root).resolve() if repository_root is not None else ROOT.resolve()
    try:episode_dir.relative_to(repo_root)
    except ValueError as exc:raise ValueError("episode must be inside repository") from exc
    errors=validate_request(data)
    if errors:raise ValueError("; ".join(errors))
    target=episode_dir/EPISODE_REL
    existing=authority_for_episode(episode_dir)
    if existing is not None and not force:
        if existing!=data:raise ValueError("episode already has a different immutable runtime-request; use --force only for explicit correction")
        return target
    mode=storage_config.episode_meta_store_config()["mode"]
    if mode!="mysql":
        write_json(target,data)
    runtime_request_persistence.persist(episode_dir,data)
    return target

def bind_request(request_path,episode_dir,force=False):
    request_path=request_path.resolve()
    if not request_path.is_file():raise ValueError(f"request file missing: {request_path}")
    return bind_data(read_json(request_path),episode_dir,force=force)

def authority_for_episode(episode_dir):
    return runtime_request_persistence.load(Path(episode_dir).resolve())

def effective_for_episode(episode_dir):
    data=authority_for_episode(episode_dir)
    if data is None:return None
    errors=validate_request(data)
    if errors:raise ValueError("; ".join(errors))
    return data

def self_test():
    a=compile_request("读取 story 分支。全自动做一篇「仲夏夜惊魂」。")
    assert a["story_input"]["mode"]=="auto_create" and a["image_model"]==DEFAULT_IMAGE_MODEL and a["image_quality"]=="high"
    assert a["intent"]["intent"]=="CREATE_EPISODE"
    b=compile_request("读取 story 分支。全自动做一篇「仲夏夜惊魂」。剧情大概是：几个人住进山里民宿。")
    assert b["story_input"]["mode"]=="user_seed" and "山里民宿" in b["story_input"]["raw"]
    c=compile_request("全自动做一篇「仲夏夜惊魂」，image=gpt-image-2。必须保留：\n1. 山里民宿\n2. 最后进入旧照片")
    assert c["story_input"]["mode"]=="core_constraints" and c["image"]["strict_model"] is True
    d=compile_request("全自动做一篇「仲夏夜惊魂」。剧情已经定了，不要改剧情：主角最后回家。")
    assert d["story_input"]["mode"]=="locked_story" and d["story_input"]["allow_structure_rewrite"] is False
    e=compile_request("读取 story 分支。制作「仲夏夜惊魂」的全部前期资产，做到可以正式生图的交接状态，不要生成图片。")
    assert e["mode"]=="preproduction_only"
    f=compile_request("读取 story 分支。接管「仲夏夜惊魂」已经完成的前期资产，不要重写剧情，从生图开始继续做到最终交付。")
    assert f["mode"]=="image_continue" and f["story_input"]["allow_structure_rewrite"] is False
    g=compile_request("继续「仲夏夜惊魂」，使用 resume 模式，从上次验证通过的断点继续。")
    assert g["mode"]=="resume"
    print("RUNTIME REQUEST V2.1 SELF-TEST PASS")

def main():
    ap=argparse.ArgumentParser(description=__doc__);sub=ap.add_subparsers(dest="cmd",required=True)
    p=sub.add_parser("compile");g=p.add_mutually_exclusive_group(required=True);g.add_argument("--text");g.add_argument("--text-file",type=Path);p.add_argument("--output",type=Path)
    p=sub.add_parser("validate");p.add_argument("request_file",type=Path)
    p=sub.add_parser("bind");p.add_argument("request_file",type=Path);p.add_argument("episode_dir",type=Path);p.add_argument("--force",action="store_true")
    p=sub.add_parser("show");p.add_argument("request_file",type=Path)
    p=sub.add_parser("show-episode");p.add_argument("episode_dir",type=Path)
    sub.add_parser("self-test");a=ap.parse_args()
    try:
        if a.cmd=="self-test":self_test();return 0
        if a.cmd=="compile":
            text=a.text if a.text is not None else read_text(a.text_file);data=compile_request(text);target=write_compiled(data,a.output)
            print(json.dumps({"ok":True,"request_path":str(target),"request":data},ensure_ascii=False,indent=2));return 0
        if a.cmd=="validate":
            errors=validate_request(read_json(a.request_file.resolve()))
            if errors:[print("FAIL:",e) for e in errors];return 2
            print("RUNTIME REQUEST VALID");return 0
        if a.cmd=="bind":
            print(f"RUNTIME REQUEST BOUND: {bind_request(a.request_file,a.episode_dir,force=a.force)}");return 0
        if a.cmd=="show":print(a.request_file.resolve().read_text(encoding="utf-8-sig"));return 0
        print(json.dumps(effective_for_episode(a.episode_dir.resolve()) or {},ensure_ascii=False,indent=2));return 0
    except (OSError,ValueError,json.JSONDecodeError) as exc:
        print("RUNTIME REQUEST ERROR:",exc);return 3
if __name__=="__main__":raise SystemExit(main())
