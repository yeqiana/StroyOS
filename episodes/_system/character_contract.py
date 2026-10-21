#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Story OS Character Contract.

Character/entry/scene selection is a Story Build Input Contract, not a new Episode stage.
"""
from __future__ import annotations

import argparse, datetime as dt, hashlib, json, random, re
from pathlib import Path
import world_identity_contract  # STORY_OS_V221_WORLD_IDENTITY
import runtime_request
import story_json
import episode_contract_persistence

ROOT = Path(__file__).resolve().parents[2]
STD = ROOT / "standards"
REL = Path("meta/character-contract.json")
CONTRACT_TYPE = "CHARACTER"
POOL_FILES = {
    "characters": STD / "character-pools.json",
    "entries": STD / "entry-motivation-pools.json",
    "scenes": STD / "scene-pools.json",
    "forbidden": STD / "forbidden-character-roles.json",
}

def now():
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")

def read_json(path):
    return story_json.read_json(path)

def write_json(path,data):
    story_json.write_json(path, data)



def load(ep):
    ep=Path(ep).resolve()
    return episode_contract_persistence.load_latest(
        ep, CONTRACT_TYPE, legacy_path=ep/REL
    )


def save(ep,data,*,expected_sha256=None):
    ep=Path(ep).resolve()
    episode_contract_persistence.save(
        ep,
        CONTRACT_TYPE,
        REL,
        data,
        status=str(data.get("status") or "ACTIVE"),
        expected_sha256=expected_sha256,
    )
    return data


def authority_sha256(ep):
    data=load(ep)
    if not isinstance(data,dict):return None
    raw=json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()

def pools():
    return {k:read_json(v) for k,v in POOL_FILES.items()}

def request(ep):
    return runtime_request.authority_for_episode(Path(ep).resolve()) or {}

def visual_profile_id(ep):
    r=request(ep)
    return str(r.get("visual_profile") or "").strip()


def source_text(ep):
    # Runtime Request may contain operational commands alongside an explicit
    # 创作要求 section.  Character selection must consume creative intent only.
    return runtime_request.creative_source_text(request(ep))

def seed_for(ep):
    r=request(ep)
    provenance=r.get("provenance") or {}
    migration=provenance.get("image_model_migration") or {}
    # Provider/model migrations mint a new execution request id but must not
    # reshuffle creative identity. Keep the original creative request stable.
    creative_id=(provenance.get("creative_request_id") or migration.get("source_request_id")
                 or r.get("request_id") or "")
    raw=str(creative_id)+"|"+str(((r.get("topic") or {}).get("title")) or "")+"|"+ep.as_posix()
    return int(hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16],16)

def weighted_choice(rng,weights):
    items=list(weights.items()); total=sum(float(v) for _,v in items)
    point=rng.random()*total; acc=0.0
    for key,value in items:
        acc+=float(value)
        if point<=acc:return key
    return items[-1][0]

def explicit_year(text):
    years=[int(x) for x in re.findall(r"\b(20\d{2})\b",text)]
    for y in years:
        if 2004<=y<=2010 or 2019<=y<=2026:return y
    return None

def choose_era(text,rng,p):
    y=explicit_year(text)
    if y is not None:return ("2004_2010" if y<=2010 else "modern_2020s"),y,"user_text"
    if any(x in text for x in ("2004","2005","2006","2007","2008","2009","2010","MP3","MP4","功能机","翻盖手机")):
        era="2004_2010"
    elif any(x in text for x in ("2020","2021","2022","2023","2024","2025","2026","智能手机","直播")):
        era="modern_2020s"
    else:
        era=weighted_choice(rng,p["characters"]["era_weights_when_unspecified"])
    year=rng.choice(p["characters"]["eras"][era]["default_years"])
    return era,year,"explicit_hint_or_weighted"

def choose_cast(text,rng,p):
    group=any(x in text for x in ("四五个","4-5","4—5","四个人","五个人","小团体","小团伙","一群朋友","几个朋友"))
    pair=any(x in text for x in ("两个人","情侣","两名","俩人"))
    female=("女生" in text or "女孩" in text) and not ("男生" in text or "男女" in text)
    male=("男生" in text or "男孩" in text) and not ("女生" in text or "男女" in text)
    if group:
        size=5 if "五" in text else 4
        return "mixed_friend_group_4_5",size
    if pair:return "pair",2
    if female:return "single_female",1
    if male:return "single_male",1
    bucket=weighted_choice(rng,p["characters"]["cast_size_weights"])
    if bucket=="small_group_4_5":return "mixed_friend_group_4_5",rng.choice([4,5])
    if bucket=="pair":return "pair",2
    return rng.choice(["single_male","single_female"]),1

def choose_entry(text,rng,p):
    for keyword,entry in p["entries"]["keyword_map"].items():
        if keyword in text:return entry,"user_hint"
    return weighted_choice(rng,p["entries"]["default_weights"]),"weighted"

def choose_scene(entry,rng,p):
    cat=rng.choice(p["scenes"]["entry_to_scene_preferences"][entry])
    place=rng.choice(p["scenes"]["scenes"][cat])
    return cat,place

def member_rows(era,cast_type,size,rng,p):
    era_cfg=p["characters"]["eras"][era]
    age_lo,age_hi=era_cfg["core_age_range"]
    if size==1:
        genders=["female" if cast_type=="single_female" else "male"]
    elif size>=4:
        patterns=p["characters"]["group_gender_patterns"][str(size)]
        genders=list(rng.choice(patterns))
    else:
        genders=["male","female"][:size]
    rows=[]
    for i,g in enumerate(genders,1):
        wardrobe=rng.choice(era_cfg["wardrobe_female" if g=="female" else "wardrobe_male"])
        rows.append({
            "id":f"P{i:02d}",
            "pov":i==1,
            "gender":g,
            "age":rng.randint(age_lo,age_hi),
            "build":"普通年轻人体型",
            "hair":"普通黑色日常发型",
            "clothing_anchor":wardrobe,
            "device_anchor":rng.choice(era_cfg["devices"]) if i==1 else None
        })
    return rows

def prepare(ep,force=False):
    ep=Path(ep).resolve()
    existing=load(ep)
    if isinstance(existing,dict) and not force:return existing
    p=pools(); text=source_text(ep); rng=random.Random(seed_for(ep))
    profile_id=visual_profile_id(ep)
    fictional_mundane_worker = profile_id == "M02_HEAVEN_MUNDANE_WORKER_V1"
    fictional_mundane_resident = profile_id == "M04_HEAVEN_MUNDANE_LIFE_V1"
    fictional_mundane = fictional_mundane_worker or fictional_mundane_resident
    era,year,era_source=choose_era(text,rng,p)
    if fictional_mundane_worker:
        # M02 is the explicit fictional-world workplace profile. Reuse the modern
        # pool only as a human age/body baseline; do not route into travel/horror.
        era="modern_2020s"; year=2026; era_source="fictional_world_human_baseline"
        cast_type=rng.choice(["single_male","single_female"]); size=1
        entry="casual_work"; entry_source="visual_profile:M02_HEAVEN_MUNDANE_WORKER_V1"
        scene_cat="casual_work_site"; scene_place="天界普通基层工作站"
    elif fictional_mundane_resident:
        # M04 is ordinary resident life, not a disguised worker profile. Preserve
        # explicit friend/group wording while keeping the entry itself mundane.
        era="modern_2020s"; year=2026; era_source="fictional_world_human_baseline"
        cast_type,size=choose_cast(text,rng,p)
        entry="daily_life"; entry_source="visual_profile:M04_HEAVEN_MUNDANE_LIFE_V1"
        scene_cat="modern_indoor"; scene_place="天界普通居民区、云街与公共生活区"
    else:
        cast_type,size=choose_cast(text,rng,p)
        entry,entry_source=choose_entry(text,rng,p)
        scene_cat,scene_place=choose_scene(entry,rng,p)
    rel=rng.choice(p["characters"]["relationship_pool"]) if size>1 else "单人"
    members=member_rows(era,cast_type,size,rng,p)
    if fictional_mundane_worker:
        for member in members:
            member["clothing_anchor"] = "朴素耐磨的米白灰蓝天界基层工作服，真实布料褶皱与使用痕迹，无华丽仙袍"
            if member.get("pov"):
                member["device_anchor"] = "随身上岗记录牌（自带留影功能）"
    elif fictional_mundane_resident:
        for member in members:
            member["clothing_anchor"] = "朴素轻便的东方天界日常衣着，真实布料褶皱与生活使用痕迹，无华丽仙袍"
            if member.get("pov"):
                member["device_anchor"] = "随身留影玉牌（仅承担私人相册记录功能）"
    world_identity = world_identity_contract.effective(ep) if world_identity_contract.required(ep) else None
    if world_identity is not None:
        population = world_identity.get("population") or {}
        for member in members:
            member["nationality_context"] = population.get("nationality_context")
            member["resident_context"] = population.get("resident_context")
        world_identity_summary = {
            "profile_id": world_identity.get("profile_id"),
            "country": (world_identity.get("world") or {}).get("country"),
            "region": (world_identity.get("world") or {}).get("region"),
            "nationality_context": population.get("nationality_context"),
            "resident_context": population.get("resident_context"),
            "effective_sha256": world_identity.get("effective_sha256"),
        }
    else:
        world_identity_summary = None
    no_plan=p["entries"]["entries"][entry]["no_anomaly_plan"]
    data={
        "schema_version":1,
        "status":"DRAFT",
        "derived_from_pools":True,
        "not_episode_stage":True,
        "created_at":now(),
        "selection_seed":seed_for(ep),
        "era":{"bucket":era,"year":year,"source":era_source,
               "world_era":"fictional" if fictional_mundane else None},
        "world_identity":world_identity_summary,
        "fictional_world": ({
            "profile_id": profile_id,
            "reality_basis": "fictional_world_mundane",
            "ordinary_life_rule": (
                "天界基层岗位按普通工作流程运转，人物是普通工作人员而非英雄/神仙主角"
                if fictional_mundane_worker else
                "天界按普通居民的生活秩序运转，人物是普通居民和朋友，不承担岗位强制、英雄、调查或神秘任务"
            ),
            "capture_device": (
                "随身上岗记录牌（自带留影功能）" if fictional_mundane_worker
                else "随身留影玉牌（仅承担私人相册记录功能）"
            ),
        } if fictional_mundane else None),
        "cast":{"type":cast_type,"size":size,"relationship":rel,"members":members},
        "pov":{"character_id":"P01","first_person":True},
        "entry":{"type":entry,"label":p["entries"]["entries"][entry]["label"],"source":entry_source,"reason":"由 Story Build 基于该生活化动机具体化"},
        "scene":{"primary_category":scene_cat,"primary_place":scene_place},
        "role_policy":{
            "protagonist_role":(
                "天界普通基层工作人员" if fictional_mundane_worker
                else "天界普通居民/普通朋友小团体" if fictional_mundane_resident
                else "普通年轻人/普通朋友小团体"
            ),
            "career_function":"none" if fictional_mundane else "arrival_only",
            "solves_anomaly_professionally":False
        },
        "no_anomaly_test":{
            "question":"如果删掉所有异常，这一天是否仍像真实生活？",
            "ordinary_day_plan":(
                "正常上班、交接、处理工单、吃饭、收尾后下班" if fictional_mundane_worker
                else "起床、吃饭、办普通生活琐事、和朋友相处、散步后回家" if fictional_mundane_resident
                else no_plan
            ),
            "pass":True,
            "must_be_rechecked_before_story_lock":True,
            "rechecked_against_final_story":False
        },
        "continuity_policy":{
            "member_count_changes_require_story_event":True,
            "pov_character_id_stable":True,
            "clothing_and_device_anchors_propagate_to_frame_contract":True
        },
        "ordinary_person_score":100,
        "forbidden_role_check":{"pass":True,"hits":[]},
        "story_build_note":(
            "这是 M02 天界普通工作人员 Story Build Input Contract。工作是故事日常本身，不得升级成神仙英雄任务；Story Lock 前锁定具体岗位并复核 NO-ANOMALY TEST。"
            if fictional_mundane_worker else
            "这是 M04 天界普通居民生活 Story Build Input Contract。生活和朋友关系是故事本身，不得为了视觉档案强行加入岗位/工单，也不得升级成英雄、调查或探秘任务。"
            if fictional_mundane_resident else
            "这是 Story Build Input Contract。可以在同一母池边界内细化，但不得换成抢修/调查等功能型职业主角。Story Lock 前将 status 改为 LOCKED 并复核字段。"
        )
    }
    return save(ep,data)

def forbidden_hits(data,p):
    raw=json.dumps(data,ensure_ascii=False)
    hits=[x for x in p["forbidden"]["forbidden_cn"] if x in raw]
    hits += [x for x in p["forbidden"]["forbidden_entry_patterns_cn"] if x in raw]
    return sorted(set(hits))

def score(data,p):
    s=100
    cast=data.get("cast") or {}
    members=cast.get("members") or []
    if not isinstance(members,list) or not members:s-=40
    if int(cast.get("size") or 0)!=len(members):s-=20
    for m in members:
        age=int(m.get("age") or 0)
        if not 19<=age<=30:s-=10
        if not str(m.get("clothing_anchor") or "").strip():s-=5
    if forbidden_hits(data,p):s-=70
    role=data.get("role_policy") or {}
    if role.get("solves_anomaly_professionally") is True:s-=40
    if role.get("career_function") not in {"arrival_only","none",None}:s-=20
    entry=((data.get("entry") or {}).get("type"))
    if entry not in (p["entries"]["entries"] or {}):s-=25
    no=data.get("no_anomaly_test") or {}
    if no.get("pass") is not True:s-=25
    if not str(no.get("ordinary_day_plan") or "").strip():s-=15
    return max(0,s)

def validate(ep,require_locked=False,*,candidate=None):
    ep=Path(ep).resolve()
    data=candidate if candidate is not None else load(ep)
    if not isinstance(data,dict):return ["meta/character-contract.json missing; run prepare"]
    p=pools(); errors=[]
    if world_identity_contract.required(ep):
        errors.extend(world_identity_contract.verify(ep))
        wi = world_identity_contract.effective(ep)
        summary = data.get("world_identity") or {}
        if summary.get("effective_sha256") != wi.get("effective_sha256"):
            errors.append("character contract world_identity stale or missing")
        expected_nat = (wi.get("population") or {}).get("nationality_context")
        for member in ((data.get("cast") or {}).get("members") or []):
            if member.get("nationality_context") != expected_nat:
                errors.append(f"{member.get('id')} nationality_context must match world identity")
    if data.get("schema_version")!=1:errors.append("schema_version must be 1")
    if require_locked and data.get("status")!="LOCKED":errors.append("character contract status must be LOCKED before Story Lock")
    hits=forbidden_hits(data,p)
    if hits:errors.append("forbidden protagonist/entry role detected: "+", ".join(hits))
    cast=data.get("cast") or {}; members=cast.get("members") or []
    size=cast.get("size")
    if not isinstance(size,int) or not 1<=size<=5:errors.append("cast.size must be 1..5")
    if not isinstance(members,list) or len(members)!=size:errors.append("cast.members must match cast.size")
    if size>=4:
        genders={m.get("gender") for m in members}
        if not {"male","female"}.issubset(genders):errors.append("4-5 person default friend group must be mixed gender")
    era=(data.get("era") or {}).get("bucket")
    if era not in p["characters"]["eras"]:errors.append("invalid era bucket")
    role=data.get("role_policy") or {}
    if role.get("solves_anomaly_professionally") is True:errors.append("protagonist must not professionally solve anomaly")
    if role.get("career_function") not in {"arrival_only","none",None}:errors.append("career function must be arrival_only/none")
    no=data.get("no_anomaly_test") or {}
    if no.get("pass") is not True:errors.append("NO-ANOMALY TEST must PASS")
    if require_locked and no.get("rechecked_against_final_story") is not True:
        errors.append("NO-ANOMALY TEST must be rechecked_against_final_story=true before Story Lock")
    computed=score(data,p)
    if computed<75:errors.append(f"ORDINARY_PERSON_SCORE too low: {computed} < 75")
    review=data.get("final_story_review")
    if require_locked and isinstance(review,dict):
        try:
            rel=Path(str(review.get("story_path") or ""))
            source=(ep/rel).resolve()
            if rel.is_absolute() or not source.is_relative_to(ep) or not source.is_file():
                errors.append("final Story review source missing or outside Episode")
            elif hashlib.sha256(source.read_bytes()).hexdigest()!=review.get("story_sha256"):
                errors.append("final Story review source SHA drift")
        except (ValueError,OSError):
            errors.append("final Story review source unverifiable")
    return errors

def approved_story_rebind(ep, *, write=False):
    """Synchronize a locked Character Contract to an independently approved Story.

    Read-only unless called with write=True by the canonical authorized Driver.
    A verified PASS is not permission to change the cast/roles, rewrite the Story,
    or skip the canonical Episode State transition. In MySQL this appends a
    new immutable Character Contract version with compare-and-swap.
    """
    from copy import deepcopy
    import episode_state_persistence
    import story_review

    ep = Path(ep).resolve()

    def result(status, **extra):
        return {"status": status, "read_only": not write,
                "model_calls": 0, "image_calls": 0, **extra}

    review = story_review.load_review(ep)
    if not isinstance(review, dict) or (review.get("summary") or {}).get("passed") is not True:
        return result("NO_OFFICIAL_STORY_PASS")
    # Fail closed even if the review payload says PASS: the entire authoritative
    # critic proof, current Story/Storyboard/Subtitles and rubric must verify.
    if not story_review.review_required(ep):
        return result("STORY_REVIEW_NOT_REQUIRED_CANNOT_AUTOBIND")
    stage = (episode_state_persistence.load(ep) or {}).get("current_state")
    if stage not in {"IDEA_LOCKED", "STORYBOARD_LOCKED"}:
        return result("APPROVED_STORY_REBIND_STAGE_UNSAFE", stage=stage)
    gate = story_json.read_json(ep / "meta/story-gates.json", default=None)
    if (not isinstance(gate, dict)
            or (gate.get("reviews") or {}).get("story") != "passed"
            or (gate.get("story") or {}).get("task_closed") is not True):
        return result("OFFICIAL_STORY_GATE_NOT_CLOSED")
    errors = story_review.verify(ep)
    if errors or review.get("issue_codes") != []:
        return result("OFFICIAL_STORY_PASS_UNVERIFIED", errors=[str(x) for x in errors[:5]])
    provenance = review.get("critic_provenance") or {}
    if (not isinstance(provenance.get("attempt"), int)
            or isinstance(provenance.get("attempt"), bool)
            or provenance["attempt"] < 1):
        return result("OFFICIAL_STORY_REVIEW_ATTEMPT_UNVERIFIED")
    review_sha = story_review.review_authority_sha256(ep)
    if not isinstance(review_sha, str) or len(review_sha) != 64:
        return result("OFFICIAL_STORY_REVIEW_SHA_MISSING")

    current = load(ep)
    if not isinstance(current, dict) or current.get("status") != "LOCKED":
        return result("FROZEN_CHARACTER_CONTRACT_MISSING")
    existing = current.get("final_story_review") or {}
    path = Path(str(existing.get("story_path") or ""))
    if path.is_absolute() or ".." in path.parts or path.as_posix() != "docs/story.md":
        return result("FROZEN_STORY_SOURCE_PATH_UNVERIFIED")
    story = ep / path
    if not story.is_file():
        return result("OFFICIAL_STORY_SOURCE_MISSING")
    latest_sha = hashlib.sha256(story.read_bytes()).hexdigest()
    if review.get("story_sha256") != latest_sha:
        return result("OFFICIAL_STORY_SOURCE_CHANGED")
    old_sha = existing.get("story_sha256")
    if old_sha == latest_sha:
        bad = validate(ep, require_locked=True, candidate=current)
        return result("ALREADY_BOUND" if not bad else "EXISTING_CHARACTER_CONTRACT_INVALID",
                      errors=[str(x) for x in bad[:5]])
    if not isinstance(old_sha, str) or len(old_sha) != 64:
        return result("PREVIOUS_CHARACTER_STORY_SHA_UNVERIFIED")
    # Only this one source-SHA mismatch is eligible for deterministic repair.
    # Any world/cast/no-anomaly/role problem remains a human review blocker.
    problems = validate(ep, require_locked=True, candidate=current)
    if problems != ["final Story review source SHA drift"]:
        return result("CHARACTER_SEMANTIC_OR_IDENTITY_DRIFT",
                      errors=[str(x) for x in problems[:5]])
    text = story.read_text(encoding="utf-8-sig")
    members = ((current.get("cast") or {}).get("members") or [])
    names = [str(x.get("name") or "").strip() for x in members if isinstance(x, dict)]
    if not names or len(names) != len(members) or len(set(names)) != len(names):
        return result("FROZEN_CAST_IDENTITY_UNVERIFIED")
    if any(name not in text for name in names):
        return result("FROZEN_CAST_MEMBER_MISSING_IN_NEW_STORY")
    expected = authority_sha256(ep)
    if not isinstance(expected, str) or len(expected) != 64:
        return result("CHARACTER_CONTRACT_CAS_SHA_MISSING")

    candidate = deepcopy(current)
    bind = {
        "scope": "VERIFIED_OFFICIAL_STORY_PASS_REBIND",
        "previous_story_sha256": old_sha,
        "story_sha256": latest_sha,
        "official_review_sha256": review_sha,
        "review_attempt": provenance["attempt"],
        "review_scope": provenance.get("review_scope") or "OFFICIAL_STORY_REVIEW",
        "previous_character_sha256": expected,
    }
    candidate["final_story_review"] = {
        **existing,
        "source": "verified_official_story_pass_rebind",
        "story_sha256": latest_sha,
        "previous_story_sha256": old_sha,
        "official_review_sha256": review_sha,
    }
    # Preserve all earlier source_revision authority fields. The SQL repository
    # separately retains the entire old payload as a previous version.
    candidate["approved_story_rebindings"] = [
        *(candidate.get("approved_story_rebindings") or []), bind,
    ]
    candidate_errors = validate(ep, require_locked=True, candidate=candidate)
    if candidate_errors:
        return result("REBOUND_CHARACTER_CONTRACT_INVALID",
                      errors=[str(x) for x in candidate_errors[:5]])
    if not write:
        return result("VERIFIED_REBIND_READY", bind=bind)

    # Recheck everything that can change between validation and CAS. The
    # MySQL version repository owns the final atomic compare-and-swap.
    if ((episode_state_persistence.load(ep) or {}).get("current_state") != stage
            or hashlib.sha256(story.read_bytes()).hexdigest() != latest_sha
            or story_review.review_authority_sha256(ep) != review_sha
            or story_review.verify(ep)
            or (story_json.read_json(ep / "meta/story-gates.json", default={}).get("reviews") or {}).get("story") != "passed"
            or authority_sha256(ep) != expected):
        return result("APPROVED_STORY_AUTHORITY_CHANGED_BEFORE_CAS")
    try:
        save(ep, candidate, expected_sha256=expected)
    except Exception as exc:
        return result("CHARACTER_VERSION_CAS_FAILED", reason=type(exc).__name__)
    return result("REBOUND_VERIFIED", bind=bind,
                  new_contract_sha256=authority_sha256(ep))


def reviewed_story_lock(ep, review_file):
    """Review/lock an existing Character Contract against a persisted final Story.

    Only the current contract owner may run this command. A model transport
    SUCCESS is insufficient; the Story worker must attest the saved story
    bytes and its ordinary-day rationale before the canonical store is updated.
    """
    from copy import deepcopy
    ep=Path(ep).resolve()
    record=Path(review_file)
    record=(record if record.is_absolute() else ep/record).resolve()
    if not record.is_relative_to(ep) or not record.is_file() or record.suffix.lower()!=".json":
        raise ValueError("CHARACTER_REVIEW_PATH_INVALID")
    if record.stat().st_size>65536:
        raise ValueError("CHARACTER_REVIEW_TOO_LARGE")
    review=story_json.read_json(record,default=None)
    if not isinstance(review,dict) or review.get("schema_version")!=1:
        raise ValueError("CHARACTER_REVIEW_SCHEMA_INVALID")
    current=load(ep)
    if not isinstance(current,dict):
        raise ValueError("CHARACTER_CONTRACT_AUTHORITY_MISSING")
    expected=str(review.get("expected_contract_sha256") or "").lower()
    if current.get("status")!="LOCKED" and (not re.fullmatch(r"[0-9a-f]{64}",expected) or authority_sha256(ep)!=expected):
        raise ValueError("CHARACTER_CONTRACT_AUTHORITY_SHA_MISMATCH")
    rel=Path(str(review.get("story_path") or ""))
    story=(ep/rel).resolve()
    if (rel.is_absolute() or not story.is_relative_to(ep) or not story.is_file()
            or story.suffix.lower() not in {".md",".txt",".json"}):
        raise ValueError("FINAL_STORY_SOURCE_INVALID")
    original=story.read_bytes()
    digest=hashlib.sha256(original).hexdigest()
    if len(original)<100 or digest!=str(review.get("story_sha256") or "").lower():
        raise ValueError("FINAL_STORY_SHA_OR_LENGTH_INVALID")
    verdict=review.get("no_anomaly_test")
    if (not isinstance(verdict,dict) or verdict.get("pass") is not True
            or len(str(verdict.get("ordinary_day_plan") or "").strip())<10
            or len(str(verdict.get("review_reason") or "").strip())<20):
        raise ValueError("NO_ANOMALY_RECHECK_EVIDENCE_INCOMPLETE")
    review_sha=hashlib.sha256(record.read_bytes()).hexdigest()
    if current.get("status")=="LOCKED":
        prior=current.get("final_story_review") or {}
        if prior.get("review_source_sha256")==review_sha and prior.get("story_sha256")==digest:
            if validate(ep,require_locked=True):
                raise ValueError("CHARACTER_EXISTING_LOCK_INVALID")
            return {"status":"ALREADY_LOCKED","committed":False,"authority_sha256":expected}
        raise ValueError("CHARACTER_ALREADY_LOCKED")
    proposal=review.get("proposed_contract")
    if proposal is not None:
        if not isinstance(proposal,dict):
            raise ValueError("CHARACTER_PROPOSAL_INVALID")
        for key in ("schema_version","created_at","selection_seed","world_identity"):
            if proposal.get(key)!=current.get(key):
                raise ValueError("CHARACTER_PROPOSAL_ORIGIN_DRIFT")
        updated=deepcopy(proposal)
    else:
        updated=deepcopy(current)
    updated["status"]="LOCKED"
    updated["locked_at"]=now()
    updated["no_anomaly_test"]={
        **(updated.get("no_anomaly_test") or {}),
        "pass":True,
        "ordinary_day_plan":str(verdict["ordinary_day_plan"]).strip(),
        "rechecked_against_final_story":True,
    }
    updated["final_story_review"]={
        "source":"scoped_story_worker_attestation",
        "story_path":rel.as_posix(),
        "story_sha256":digest,
        "review_reason":str(verdict["review_reason"]).strip(),
        "review_source_sha256":review_sha,
    }
    errors=validate(ep,require_locked=True,candidate=updated)
    if errors:
        raise ValueError("CHARACTER_CONTRACT_REVIEW_FAIL: "+"; ".join(errors[:5]))
    # Re-read before appending a new authority version; the canonical single-
    # writer Episode rule still governs concurrent production ownership.
    if authority_sha256(ep)!=expected:
        raise ValueError("CHARACTER_AUTHORITY_CHANGED_BEFORE_SAVE")
    save(ep,updated,expected_sha256=expected)
    return {"status":"LOCKED","committed":True,"authority_sha256":authority_sha256(ep),
            "story_sha256":digest}



def source_revision_lock(ep, review_file):
    """CAS-bind a materially repaired Story to an existing frozen Character Contract.

    A real independent Story Review #1 FAIL may authorize the normal #2
    story rewrite; the historical narrowly-scoped #7 -> #8 revision remains
    supported. Prior contract/review versions stay immutable in MySQL.
    A model output, a filename or a hand-edited PASS is never authority.
    """
    from copy import deepcopy
    import episode_state_persistence
    import story_review

    ep = Path(ep).resolve()
    if (episode_state_persistence.load(ep) or {}).get("current_state") != "IDEA_LOCKED":
        raise ValueError("CHARACTER_SOURCE_REVISION_STAGE_NOT_IDEA_LOCKED")
    candidate = (ep / Path(review_file)).resolve()
    if (not candidate.is_relative_to(ep) or candidate.suffix.lower() != ".json"
            or not candidate.is_file() or candidate.stat().st_size > 65536):
        raise ValueError("CHARACTER_SOURCE_REVISION_ATTESTATION_INVALID")
    data = story_json.read_json(candidate)
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("CHARACTER_SOURCE_REVISION_SCHEMA_INVALID")
    current = load(ep)
    if not isinstance(current, dict) or current.get("status") != "LOCKED":
        raise ValueError("CHARACTER_SOURCE_REVISION_REQUIRES_EXISTING_LOCK")
    if current.get("source_revision") is not None:
        raise ValueError("CHARACTER_SOURCE_REVISION_ALREADY_USED")
    expected = authority_sha256(ep)
    if data.get("previous_contract_authority_sha256") != expected:
        raise ValueError("CHARACTER_SOURCE_REVISION_CONTRACT_SHA_DRIFT")
    prior = story_review.load_review(ep)
    provenance = (prior or {}).get("critic_provenance") or {}
    attempt = provenance.get("attempt")
    early_repair = (
        attempt == 1
        and provenance.get("isolated_session") is True
        and isinstance(prior.get("issue_codes"), list)
        and bool(prior["issue_codes"])
        and isinstance(prior.get("storyboard_sha256"), str)
        and isinstance(prior.get("subtitle_source_sha256"), str)
        and len(prior["subtitle_source_sha256"]) == 64
    ) if isinstance(prior, dict) else False
    legacy_a8 = (
        attempt == 7
        and set(prior.get("issue_codes") or ()) == {
            "STORY_COMPREHENSION_FAIL", "CAUSAL_CHAIN_BROKEN", "CLIMAX_PAYOFF_WEAK"
        }
    ) if isinstance(prior, dict) else False
    if (not isinstance(prior, dict)
            or (prior.get("summary") or {}).get("passed") is not False
            or not (early_repair or legacy_a8)):
        raise ValueError("CHARACTER_SOURCE_REVISION_PRIOR_REVIEW_NOT_ELIGIBLE")
    prior_review_sha = story_review.review_authority_sha256(ep)
    old_story_sha = (current.get("final_story_review") or {}).get("story_sha256")
    if (not prior_review_sha
            or data.get("previous_review_authority_sha256") != prior_review_sha
            or data.get("previous_story_sha256") != old_story_sha
            or prior.get("story_sha256") != old_story_sha):
        raise ValueError("CHARACTER_SOURCE_REVISION_PREVIOUS_EVIDENCE_DRIFT")

    story_path = ep / "docs/story.md"
    board_path = ep / "docs/storyboard.md"
    subtitle_path = ep / "docs/subtitles.yaml"
    if not all(p.is_file() for p in (story_path, board_path, subtitle_path)):
        raise ValueError("CHARACTER_SOURCE_REVISION_INPUTS_MISSING")
    new_story_sha = hashlib.sha256(story_path.read_bytes()).hexdigest()
    new_board_sha = hashlib.sha256(board_path.read_bytes()).hexdigest()
    subtitle_sha = hashlib.sha256(subtitle_path.read_bytes()).hexdigest()
    if (new_story_sha == old_story_sha
            or new_board_sha == prior.get("storyboard_sha256")
            or (early_repair and subtitle_sha == prior["subtitle_source_sha256"])
            or data.get("story_sha256") != new_story_sha
            or data.get("storyboard_sha256") != new_board_sha
            or data.get("subtitle_sha256") != subtitle_sha):
        raise ValueError("CHARACTER_SOURCE_REVISION_SOURCE_SHA_NOT_REPAIRED")
    text = story_path.read_text(encoding="utf-8-sig")
    for member in ((current.get("cast") or {}).get("members") or []):
        name = str(member.get("name") or "").strip()
        if name and name not in text:
            raise ValueError("CHARACTER_SOURCE_REVISION_CAST_IDENTITY_DRIFT")
    review = data.get("no_anomaly_test")
    if (not isinstance(review, dict) or review.get("pass") is not True
            or len(str(review.get("ordinary_day_plan") or "").strip()) < 10
            or len(str(review.get("review_reason") or "").strip()) < 20
            or review.get("story_sha256") != new_story_sha):
        raise ValueError("CHARACTER_SOURCE_REVISION_ORDINARY_DAY_EVIDENCE_INVALID")
    marker = ep / ("meta/runtime/character-story-source-revision-a2.json"
                   if early_repair else "meta/runtime/character-story-source-revision-a8.json")
    if marker.exists():
        raise ValueError("CHARACTER_SOURCE_REVISION_ALREADY_AUTHORIZED")
    attestation_sha = hashlib.sha256(candidate.read_bytes()).hexdigest()
    updated = deepcopy(current)
    updated["no_anomaly_test"] = {
        **(updated.get("no_anomaly_test") or {}),
        "pass": True,
        "ordinary_day_plan": str(review["ordinary_day_plan"]).strip(),
        "rechecked_against_final_story": True,
    }
    updated["final_story_review"] = {
        "source": "sha_bound_character_story_source_revision",
        "story_path": "docs/story.md",
        "story_sha256": new_story_sha,
        "review_source_sha256": attestation_sha,
        "review_reason": str(review["review_reason"]).strip(),
        "previous_story_sha256": old_story_sha,
    }
    binding = {
        "schema_version": 1,
        "scope": ("CHARACTER_STORY_SOURCE_REPAIR_AFTER_FAILED_A1"
                  if early_repair else "CHARACTER_STORY_SOURCE_REPAIR_AFTER_FAILED_A7"),
        "previous_contract_authority_sha256": expected,
        "previous_review_authority_sha256": prior_review_sha,
        "previous_story_sha256": old_story_sha,
        "story_sha256": new_story_sha,
        "storyboard_sha256": new_board_sha,
        "subtitle_sha256": subtitle_sha,
        "attestation_sha256": attestation_sha,
        "previous_review_attempt": attempt,
    }
    updated["source_revision"] = binding
    failures = validate(ep, require_locked=True, candidate=updated)
    if failures:
        raise ValueError("CHARACTER_SOURCE_REVISION_CONTRACT_INVALID: " + "; ".join(failures[:5]))
    if authority_sha256(ep) != expected or story_review.review_authority_sha256(ep) != prior_review_sha:
        raise ValueError("CHARACTER_SOURCE_REVISION_CONCURRENT_AUTHORITY_CHANGE")
    # MySQL contract repository appends a new immutable version under CAS.
    # The binding lives in that authoritative payload even if projection fails.
    save(ep, updated, expected_sha256=expected)
    marker.parent.mkdir(parents=True, exist_ok=True)
    story_json.write_json(marker, binding)
    return {"status": "LOCKED_REVISED", "story_sha256": new_story_sha,
            "authority_sha256": authority_sha256(ep),
            "source_revision": binding}

def lock(ep):
    ep=Path(ep).resolve()
    data=prepare(ep)
    data["status"]="LOCKED"
    data["locked_at"]=now()
    # Do not auto-set rechecked_against_final_story; the Story worker must explicitly recheck it.
    p=pools()
    data["forbidden_role_check"]={"pass":not bool(forbidden_hits(data,p)),"hits":forbidden_hits(data,p)}
    data["ordinary_person_score"]=score(data,p)
    return save(ep,data)

def prompt_block(ep):
    d=load(ep)
    if not isinstance(d,dict):return ""
    return json.dumps(d,ensure_ascii=False,sort_keys=True)

def self_test():
    p=pools()
    assert "2004_2010" in p["characters"]["eras"]
    assert "modern_2020s" in p["characters"]["eras"]
    assert "repair_worker" in p["forbidden"]["forbidden_ids"]
    assert "casual_work" in p["entries"]["entries"]
    print("CHARACTER CONTRACT SELF-TEST PASS")

def main():
    ap=argparse.ArgumentParser(description=__doc__); sub=ap.add_subparsers(dest="cmd",required=True)
    p=sub.add_parser("prepare");p.add_argument("episode_dir");p.add_argument("--force",action="store_true")
    p=sub.add_parser("lock");p.add_argument("episode_dir")
    p=sub.add_parser("validate");p.add_argument("episode_dir");p.add_argument("--require-locked",action="store_true")
    p=sub.add_parser("show");p.add_argument("episode_dir");p.add_argument("--with-sha",action="store_true")
    p=sub.add_parser("review-lock");p.add_argument("episode_dir");p.add_argument("--review",required=True)
    p=sub.add_parser("source-revision-lock");p.add_argument("episode_dir");p.add_argument("--review",required=True)
    sub.add_parser("self-test")
    a=ap.parse_args()
    if a.cmd=="self-test":self_test();return 0
    ep=Path(a.episode_dir).resolve()
    if a.cmd=="prepare":
        print(json.dumps(prepare(ep,a.force),ensure_ascii=False,indent=2));return 0
    if a.cmd=="lock":
        print(json.dumps(lock(ep),ensure_ascii=False,indent=2));return 0
    if a.cmd=="source-revision-lock":
        try: result=source_revision_lock(ep,a.review)
        except (ValueError,OSError) as exc:
            print("CHARACTER SOURCE REVISION BLOCKED:",str(exc));return 2
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    if a.cmd=="review-lock":
        try:result=reviewed_story_lock(ep,a.review)
        except (ValueError,OSError) as exc:
            print("CHARACTER REVIEW LOCK BLOCKED:",str(exc));return 2
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    if a.cmd=="validate":
        errors=validate(ep,a.require_locked)
        if errors:
            [print("FAIL:",x) for x in errors];return 2
        print("CHARACTER CONTRACT VERIFIED");return 0
    data=load(ep) or {}
    result={"contract":data,"authority_sha256":authority_sha256(ep)} if a.with_sha else data
    print(json.dumps(result,ensure_ascii=False,indent=2));return 0

if __name__=="__main__": raise SystemExit(main())
