#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Character visual identity spec + provisional/final pixel master + derived crops.

Lifecycle:
STORY_LOCK: textual identity spec only.
BASELINE_PASS: PROVISIONAL pixel master + deterministic face crops.
FOUR_ADMISSION_PASS: promote the same pixel master to LOCKED.
Production uses LOCKED master; Visual Lock dependents may use PROVISIONAL master.
"""
from __future__ import annotations
import argparse, binascii, datetime as dt, hashlib, json, struct, zlib
from pathlib import Path
import world_identity_contract  # STORY_OS_V221_WORLD_IDENTITY
import story_json
import character_contract
import character_three_view
import episode_contract_persistence
import runtime_workspace

ROOT=Path(__file__).resolve().parents[2]
REL=Path("meta/character-visual-contract.json")
CONTRACT_TYPE="CHARACTER_VISUAL"
PIXEL_MASTER_REL=Path("meta/character-pixel-master.json")
CROPS_REL=Path("meta/character-master-crops.json")
CROPS_DIR=Path("media/identity/character-masters")
SERIES_IDENTITY_REL=Path("meta/series-character-identity.json")
PRIMARY_ATTRACTIVENESS="moderately_above_average_but_real"
SECONDARY_ATTRACTIVENESS="ordinary_camera_friendly"
FEMALE_LEAD_BUILD="slim_proportionate_natural"
MALE_LEAD_BUILD="lean_proportionate_natural"

def now():return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")
def read_json(p):
    return story_json.read_json(p)
def write_json(p,d):
    story_json.write_json(p, d)



def load(ep):
    ep=Path(ep).resolve()
    return episode_contract_persistence.load_latest(
        ep, CONTRACT_TYPE, legacy_path=ep/REL
    )


def exists(ep):
    return isinstance(load(ep),dict)


def save(ep,data):
    ep=Path(ep).resolve()
    episode_contract_persistence.save(
        ep, CONTRACT_TYPE, REL, data,
        status=str(data.get("status") or "ACTIVE"),
    )
    return data


def authority_sha256(ep):
    data=load(ep)
    if not isinstance(data,dict):return None
    raw=json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _legacy_spec_sha_matches_current_authority(ep, stored_sha):
    """Accept a pre-MySQL pixel-master binding only when semantics are unchanged.

    Historical pixel masters were bound to the byte SHA of
    meta/character-visual-contract.json. After the contract moved to MySQL,
    authority_sha256 hashes canonical JSON, so byte formatting alone can
    change the digest. Preserve the immutable historical binding when (and only
    when) the stored digest still matches that legacy file and the legacy
    document is structurally equal to the current MySQL authority.
    """
    ep=Path(ep).resolve();legacy=ep/REL;stored=str(stored_sha or "").lower()
    if not stored or not legacy.is_file():return False
    try:
        if sha_file(legacy).lower()!=stored:return False
        historical=read_json(legacy);current=load(ep)
    except Exception:
        return False
    return isinstance(historical,dict) and isinstance(current,dict) and historical==current


def materialize_export(ep):
    ep=Path(ep).resolve()
    legacy=ep/REL
    if legacy.is_file():
        return legacy
    data=load(ep)
    if not isinstance(data,dict):
        return None
    return runtime_workspace.write_json(
        ep, "exports/character-visual-contract.json", data
    )
def sha_file(p):
    h=hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):h.update(b)
    return h.hexdigest()
def repo_rel(p):return Path(p).resolve().relative_to(ROOT.resolve()).as_posix()
def series_identity_path(ep):
    ep=Path(ep).resolve()
    return ep.parent/SERIES_IDENTITY_REL

def _repo_asset(raw):
    p=Path(str(raw));p=p.resolve() if p.is_absolute() else (ROOT/p).resolve()
    p.relative_to(ROOT.resolve())
    return p

def validate_series_identity(ep):
    p=series_identity_path(ep)
    if not p.is_file():return []
    d=read_json(p);e=[]
    if d.get("schema_version")!=1:e.append("series character identity schema_version must be 1")
    if d.get("approved") is not True:e.append("series character identity must be approved=true")
    chars=d.get("characters") or {}
    if not isinstance(chars,dict) or not chars:e.append("series character identity characters missing")
    rows=[]
    group=d.get("group_identity_asset")
    if isinstance(group,dict):rows.append(("group",group))
    for cid,row in chars.items():
        if not isinstance(row,dict):e.append(f"series character identity {cid} invalid");continue
        asset=row.get("primary_asset")
        if not isinstance(asset,dict):e.append(f"series character identity {cid} primary_asset missing");continue
        rows.append((str(cid),asset))
        for index,support in enumerate(row.get("supporting_assets") or []):
            if not isinstance(support,dict):e.append(f"series character identity {cid} supporting_asset[{index}] invalid");continue
            rows.append((f"{cid}:supporting:{index}",support))
    for cid,row in rows:
        try:
            fp=_repo_asset(row.get("path"))
            if not fp.is_file():e.append(f"series character identity {cid} asset missing")
            elif sha_file(fp).lower()!=str(row.get("sha256") or "").lower():e.append(f"series character identity {cid} sha mismatch")
        except Exception:e.append(f"series character identity {cid} asset path invalid")
    return e

def series_identity_reference(ep,character_id=None):
    p=series_identity_path(ep)
    if not p.is_file():return None
    errors=validate_series_identity(ep)
    if errors:raise ValueError("invalid series character identity: "+"; ".join(errors[:8]))
    d=read_json(p);cid=str(character_id or "").strip();row=None
    if cid:row=((d.get("characters") or {}).get(cid) or {}).get("primary_asset")
    if not isinstance(row,dict):row=d.get("group_identity_asset")
    if not isinstance(row,dict):return None
    return {"path":row["path"],"role":f"series_character_identity:{cid or 'group'}","kind":"identity","sha256":row["sha256"],"character_id":cid or None,"status":"SERIES_LOCKED","authority_path":repo_rel(p)}

def _primary_ids(cp):
    members=((cp.get("cast") or {}).get("members") or [])
    pov=str(((cp.get("pov") or {}).get("character_id")) or "")
    ids=[]
    if pov:ids.append(pov)
    pov_gender=next((m.get("gender") for m in members if str(m.get("id"))==pov),None)
    opposite=next((str(m.get("id")) for m in members if str(m.get("id"))!=pov and m.get("gender") and m.get("gender")!=pov_gender),None)
    if opposite:ids.append(opposite)
    return ids[:2]

def prepare(ep,force=False):
    ep=Path(ep).resolve()
    existing=load(ep)
    if isinstance(existing,dict) and not force:return existing
    cp=character_contract.load(ep) or {}
    members=((cp.get("cast") or {}).get("members") or [])
    world_identity = world_identity_contract.effective(ep) if world_identity_contract.required(ep) else None
    three_view_anchor = character_three_view.summary(ep)
    primary=set(_primary_ids(cp));rows={}
    for m in members:
        cid=str(m.get("id") or "");g=str(m.get("gender") or "");is_primary=cid in primary
        if g=="female" and is_primary:body=FEMALE_LEAD_BUILD
        elif g=="male" and is_primary:body=MALE_LEAD_BUILD
        else:body="ordinary_healthy_natural"
        rows[cid]={
          "visual_priority":"primary" if is_primary else "supporting",
          "attractiveness":PRIMARY_ATTRACTIVENESS if is_primary else SECONDARY_ATTRACTIVENESS,
          "body_build":body,"body_build_story_override_reason":"",
          "face_identity":{
            "original_character":True,"independently_distinct_face":True,
            "celebrity_likeness":False,"influencer_face":False,
            "fashion_model_styling":False,"reference_similarity_target":"low",
            "skin_texture":"natural_visible_texture","slight_asymmetry":True,
            "identity_spec_locked":False
          },
          "hair":{
            "haircut_anchor":"","hair_length_anchor":"",
            "allowed_state_variation":["wet","windblown","messy","hood_up","tied_or_untied_with_story_reason"],
            "exact_reference_hairstyle_copy":False
          },
          "world_identity":{
            "profile_id": world_identity.get("profile_id") if world_identity else None,
            "nationality_context": ((world_identity.get("population") or {}).get("nationality_context")) if world_identity else None,
            "resident_context": ((world_identity.get("population") or {}).get("resident_context")) if world_identity else None,
            "effective_sha256": world_identity.get("effective_sha256") if world_identity else None
          },
          "presentation":{
            "heavy_makeup":False,"porcelain_skin":False,
            "excessive_face_symmetry":False,"ai_beauty_face":False,
            "camera_friendly_but_believable":True
          }
        }
    d={
      "schema_version":2,"status":"DRAFT","created_at":now(),
      "lock_model":"identity_spec__provisional_baseline_master__final_visual_lock_master",
      "primary_cast_ids":list(primary),"members":rows,
      "reference_policy":{
        "allowed_reference_roles":["age_vibe","attractiveness_range","realism","capture_style","clothing_direction","color_mood"],
        "must_not_copy":["exact_face_geometry","exact_eye_nose_mouth_combination","exact_hairstyle","distinctive_personal_markers","celebrity_identity"],
        "reference_is_not_identity_master":True,"real_person_exact_likeness_forbidden":True
      },
      "preproduction_identity_anchor":three_view_anchor,
      "identity_anchor_policy":{
        "three_view_role":"PREPRODUCTION_IDENTITY_ANCHOR",
        "three_view_identity_consistency":"strict_character",
        "generic_reference_policy_applies":False,
        "pixel_master_supersedes_three_view":True
      },
      "master_policy":{
        "preferred_identity_source":["character_individual_crop","character_pixel_master","character_three_view_anchor","ordinary_baseline_group_selfie","original_character_library_asset"],
        "preproduction_only_must_not_generate_master_images":True,
        "ordinary_baseline_can_become_group_identity_master":True,
        "pixel_master_artifact":PIXEL_MASTER_REL.as_posix(),
        "crop_manifest_artifact":CROPS_REL.as_posix(),
        "provisional_master_after_baseline_review_pass":True,
        "final_master_after_four_admission_pass":True,
        "derived_crops_are_not_new_identity_generation":True
      },
      "realism_priority":True,
      "note":"Story Lock 只锁规格；baseline 单独 PASS 后建立临时像素母版，四项 Visual Lock 全 PASS 后升级为正式母版。"
    }
    return save(ep,d)

def _identity_spec_locked(face):
    if "identity_spec_locked" in face:return face.get("identity_spec_locked") is True
    return face.get("master_identity_locked") is True

def validate(ep,require_locked=True):
    ep=Path(ep).resolve();d=load(ep)
    if not isinstance(d,dict):return ["meta/character-visual-contract.json missing"]
    e=[]
    effective_world = world_identity_contract.effective(ep) if world_identity_contract.required(ep) else None
    if effective_world is not None:
        e.extend(world_identity_contract.verify(ep))
    if int(d.get("schema_version") or 1) not in {1,2}:e.append("unsupported character visual schema_version")
    if require_locked and d.get("status")!="LOCKED":e.append("character visual contract must be LOCKED")
    rp=d.get("reference_policy") or {}
    if rp.get("real_person_exact_likeness_forbidden") is not True:e.append("exact real-person likeness must be forbidden")
    if rp.get("reference_is_not_identity_master") is not True:e.append("reference image must not become identity master")
    try:
        current_three_view=character_three_view.summary(ep)
    except ValueError as exc:
        e.append(str(exc));current_three_view={"applicable":False}
    stored_three_view=d.get("preproduction_identity_anchor") or {"applicable":False}
    if current_three_view.get("applicable"):
        if stored_three_view.get("applicable") is not True or stored_three_view.get("manifest_sha256")!=current_three_view.get("manifest_sha256"):
            e.append("character three-view anchor stale or missing from character visual contract")
        policy=d.get("identity_anchor_policy") or {}
        if policy.get("three_view_role")!="PREPRODUCTION_IDENTITY_ANCHOR":e.append("three-view identity anchor policy missing")
        if policy.get("pixel_master_supersedes_three_view") is not True:e.append("three-view must be superseded by pixel master")
    elif stored_three_view.get("applicable") is True:
        e.append("character three-view anchor source missing")
    primary=set(str(x) for x in (d.get("primary_cast_ids") or []));members=d.get("members") or {}
    if not members:e.append("character visual members missing")
    cp=character_contract.load(ep)
    if isinstance(cp,dict):
        expected_ids={str(m.get("id") or "") for m in (((cp.get("cast") or {}).get("members") or [])) if str(m.get("id") or "")}
        actual_ids={str(cid) for cid in members}
        missing=sorted(expected_ids-actual_ids);extra=sorted(actual_ids-expected_ids)
        if missing:e.append("character visual members missing cast ids: "+", ".join(missing))
        if extra:e.append("character visual members contain unknown cast ids: "+", ".join(extra))
    for cid,row in members.items():
        face=row.get("face_identity") or {};hair=row.get("hair") or {};pres=row.get("presentation") or {}
        if effective_world is not None:
            wrow=row.get("world_identity") or {}
            if wrow.get("effective_sha256") != effective_world.get("effective_sha256"):
                e.append(f"{cid} world_identity stale or missing")
            if wrow.get("nationality_context") != ((effective_world.get("population") or {}).get("nationality_context")):
                e.append(f"{cid} nationality_context must match world identity")
        if face.get("original_character") is not True:e.append(f"{cid} original_character must be true")
        if face.get("independently_distinct_face") is not True:e.append(f"{cid} independently_distinct_face must be true")
        if face.get("celebrity_likeness") is not False:e.append(f"{cid} celebrity_likeness must be false")
        if face.get("reference_similarity_target")!="low":e.append(f"{cid} reference_similarity_target must be low")
        if require_locked and not _identity_spec_locked(face):e.append(f"{cid} identity_spec_locked must be true")
        if not str(hair.get("haircut_anchor") or "").strip():e.append(f"{cid} haircut_anchor must be explicit")
        if not str(hair.get("hair_length_anchor") or "").strip():e.append(f"{cid} hair_length_anchor must be explicit")
        if hair.get("exact_reference_hairstyle_copy") is not False:e.append(f"{cid} exact reference hairstyle copy forbidden")
        if pres.get("porcelain_skin") is not False or pres.get("ai_beauty_face") is not False:e.append(f"{cid} over-beautified face forbidden")
        if cid in primary and row.get("attractiveness")!=PRIMARY_ATTRACTIVENESS:e.append(f"{cid} primary attractiveness must stay moderately-above-average but real")
        if row.get("body_build")=="story_specific" and not str(row.get("body_build_story_override_reason") or "").strip():e.append(f"{cid} story_specific body build requires override reason")
    return e

def pixel_master_required(ep):
    ep=Path(ep).resolve();p=ep/"meta/opening-social-anchor.json"
    if not p.is_file():return False
    try:
        d=read_json(p)
        if d.get("applicable") is not True:return False
        for x in d.get("opening_frames") or []:
            if not isinstance(x,dict) or x.get("selfie") is not True:continue
            try:n=int(x.get("frame"))
            except Exception:continue
            if n in {1,2} and int(x.get("people_visible") or 0)>=2:return True
        return False
    except Exception:return False

def _pixel_master_data(ep,*,frame,asset_path,asset_sha256,frame_contract_sha256,status,baseline_review_sha256=None):
    ep=Path(ep).resolve();errs=validate(ep,True)
    if errs:raise ValueError("character visual spec invalid: "+"; ".join(errs[:8]))
    asset=_repo_asset(asset_path)
    if not asset.is_file():raise ValueError(f"pixel master asset missing: {asset_path}")
    actual=sha_file(asset)
    if actual.lower()!=str(asset_sha256 or "").lower():raise ValueError("pixel master asset sha mismatch")
    old=read_json(ep/PIXEL_MASTER_REL) if (ep/PIXEL_MASTER_REL).is_file() else {}
    return {
      "schema_version":2,"status":status,"created_at":old.get("created_at") or now(),"updated_at":now(),
      "source_role":"ordinary_baseline","frame":f"{int(frame):02d}","asset_path":repo_rel(asset),"sha256":actual,
      "frame_contract_sha256":str(frame_contract_sha256 or ""),"character_visual_contract_path":REL.as_posix(),
      "character_visual_contract_sha256":authority_sha256(ep),
      "baseline_review_path":"meta/visual-lock-baseline-review.json" if baseline_review_sha256 else old.get("baseline_review_path"),
      "baseline_review_sha256":baseline_review_sha256 or old.get("baseline_review_sha256"),
      "crop_manifest_path":CROPS_REL.as_posix() if (ep/CROPS_REL).is_file() else old.get("crop_manifest_path"),
      "crop_manifest_sha256":sha_file(ep/CROPS_REL) if (ep/CROPS_REL).is_file() else old.get("crop_manifest_sha256"),
      "immutable_identity_evidence":status=="LOCKED"
    }

def lock_provisional_pixel_master(ep,*,frame,asset_path,asset_sha256,frame_contract_sha256,baseline_review_sha256,face_boxes=None):
    ep=Path(ep).resolve();existing=read_json(ep/PIXEL_MASTER_REL) if (ep/PIXEL_MASTER_REL).is_file() else None
    if existing and existing.get("status")=="LOCKED":
        same_locked_evidence=(
            str(existing.get("frame") or "").zfill(2)==f"{int(frame):02d}"
            and str(existing.get("sha256") or "").lower()==str(asset_sha256 or "").lower()
            and str(existing.get("frame_contract_sha256") or "").lower()==str(frame_contract_sha256 or "").lower()
            and str(existing.get("baseline_review_sha256") or "").lower()==str(baseline_review_sha256 or "").lower()
        )
        if same_locked_evidence:return existing
    data=_pixel_master_data(ep,frame=frame,asset_path=asset_path,asset_sha256=asset_sha256,frame_contract_sha256=frame_contract_sha256,status="PROVISIONAL",baseline_review_sha256=baseline_review_sha256)
    write_json(ep/PIXEL_MASTER_REL,data)
    crop_result=derive_face_crops(ep,face_boxes or [],allow_non_png=True)
    if (ep/CROPS_REL).is_file():
        data["crop_manifest_path"]=CROPS_REL.as_posix();data["crop_manifest_sha256"]=sha_file(ep/CROPS_REL);write_json(ep/PIXEL_MASTER_REL,data)
    data["crop_result"]=crop_result;return data

def lock_pixel_master(ep,*,frame,asset_path,asset_sha256,frame_contract_sha256,source_role="ordinary_baseline"):
    ep=Path(ep).resolve();old=read_json(ep/PIXEL_MASTER_REL) if (ep/PIXEL_MASTER_REL).is_file() else {}
    data=_pixel_master_data(ep,frame=frame,asset_path=asset_path,asset_sha256=asset_sha256,frame_contract_sha256=frame_contract_sha256,status="LOCKED",baseline_review_sha256=old.get("baseline_review_sha256"))
    write_json(ep/PIXEL_MASTER_REL,data)
    if (ep/CROPS_REL).is_file():
        crops=read_json(ep/CROPS_REL);crops["source_master_status"]="LOCKED";crops["updated_at"]=now();write_json(ep/CROPS_REL,crops)
        data["crop_manifest_sha256"]=sha_file(ep/CROPS_REL);write_json(ep/PIXEL_MASTER_REL,data)
    return data

def validate_pixel_master(ep,expected=None,allow_provisional=False):
    ep=Path(ep).resolve();p=ep/PIXEL_MASTER_REL
    if not p.is_file():return ["character pixel master missing"]
    d=read_json(p);e=[]
    if int(d.get("schema_version") or 1) not in {1,2}:e.append("unsupported character pixel master schema_version")
    allowed={"LOCKED","PROVISIONAL"} if allow_provisional else {"LOCKED"}
    if d.get("status") not in allowed:e.append(f"character pixel master status must be one of {sorted(allowed)}")
    spec_sha=authority_sha256(ep)
    if not spec_sha:e.append("character visual spec missing")
    else:
        stored_spec_sha=str(d.get("character_visual_contract_sha256") or "").lower()
        if stored_spec_sha!=spec_sha.lower() and not _legacy_spec_sha_matches_current_authority(ep,stored_spec_sha):
            e.append("character pixel master spec sha stale")
    try:
        asset=_repo_asset(d.get("asset_path"))
        if not asset.is_file():e.append("character pixel master asset missing")
        elif sha_file(asset).lower()!=str(d.get("sha256") or "").lower():e.append("character pixel master asset sha mismatch")
    except Exception:e.append("character pixel master asset path invalid")
    if d.get("source_role")!="ordinary_baseline":e.append("character pixel master must come from ordinary_baseline")
    review_sha=str(d.get("baseline_review_sha256") or "")
    if review_sha:
        rp=ep/str(d.get("baseline_review_path") or "meta/visual-lock-baseline-review.json")
        if not rp.is_file():e.append("character pixel master baseline review missing")
        elif sha_file(rp).lower()!=review_sha.lower():e.append("character pixel master baseline review sha stale")
    if expected:
        for key in ("asset_path","sha256"):
            if str(d.get(key) or "").lower()!=str(expected.get(key) or "").lower():
                e.append(f"character pixel master {key} mismatch")
        if str(d.get("frame_contract_sha256") or "").lower() != str(expected.get("frame_contract_sha256") or "").lower():
            import frame_contract
            if not frame_contract.recorded_contract_matches_current(
                    ep, d.get("frame"), d.get("frame_contract_sha256")):
                e.append("character pixel master frame_contract_sha256 mismatch")
        if str(d.get("frame") or "").zfill(2)!=str(expected.get("frame") or "").zfill(2):e.append("character pixel master frame mismatch")
    return e

def pixel_master_reference(ep,allow_provisional=False):
    ep=Path(ep).resolve();p=ep/PIXEL_MASTER_REL
    if not p.is_file():return None
    errors=validate_pixel_master(ep,allow_provisional=allow_provisional)
    if errors:raise ValueError("invalid character pixel master: "+"; ".join(errors[:8]))
    d=read_json(p);return {"path":d["asset_path"],"role":"character_pixel_master","kind":"identity","sha256":d["sha256"],"frame":d.get("frame"),"status":d.get("status")}

PNG_SIG=b"\x89PNG\r\n\x1a\n"
def _png_chunk(kind,data):return struct.pack(">I",len(data))+kind+data+struct.pack(">I",binascii.crc32(kind+data)&0xffffffff)
def _paeth(a,b,c):
    p=a+b-c;pa=abs(p-a);pb=abs(p-b);pc=abs(p-c)
    return a if pa<=pb and pa<=pc else (b if pb<=pc else c)
def _decode_png(path):
    data=Path(path).read_bytes()
    if not data.startswith(PNG_SIG):raise ValueError("source is not PNG")
    pos=8;idat=[];ihdr=None
    while pos+12<=len(data):
        n=struct.unpack(">I",data[pos:pos+4])[0];kind=data[pos+4:pos+8];payload=data[pos+8:pos+8+n];pos+=12+n
        if kind==b"IHDR":ihdr=payload
        elif kind==b"IDAT":idat.append(payload)
        elif kind==b"IEND":break
    if ihdr is None:raise ValueError("PNG IHDR missing")
    width,height,bitdepth,color,comp,flt,interlace=struct.unpack(">IIBBBBB",ihdr);channels={0:1,2:3,4:2,6:4}.get(color)
    if bitdepth!=8 or channels is None or interlace!=0:raise ValueError("PNG cropper supports 8-bit non-interlaced grayscale/RGB/GA/RGBA")
    bpp=channels;stride=width*bpp;raw=zlib.decompress(b"".join(idat));rows=[];i=0;prev=bytearray(stride)
    for _ in range(height):
        f=raw[i];i+=1;scan=bytearray(raw[i:i+stride]);i+=stride;out=bytearray(stride)
        for x,val in enumerate(scan):
            a=out[x-bpp] if x>=bpp else 0;b=prev[x];c=prev[x-bpp] if x>=bpp else 0
            if f==0:r=val
            elif f==1:r=(val+a)&255
            elif f==2:r=(val+b)&255
            elif f==3:r=(val+((a+b)//2))&255
            elif f==4:r=(val+_paeth(a,b,c))&255
            else:raise ValueError(f"unsupported PNG filter {f}")
            out[x]=r
        rows.append(bytes(out));prev=out
    return width,height,bitdepth,color,bpp,rows

def _crop_png(src,dst,left,top,right,bottom):
    width,height,bitdepth,color,bpp,rows=_decode_png(src);left=max(0,min(width-1,int(left)));top=max(0,min(height-1,int(top)));right=max(left+1,min(width,int(right)));bottom=max(top+1,min(height,int(bottom)))
    cropped=[row[left*bpp:right*bpp] for row in rows[top:bottom]];raw=b"".join(b"\x00"+r for r in cropped);ihdr=struct.pack(">IIBBBBB",right-left,bottom-top,bitdepth,color,0,0,0)
    out=PNG_SIG+_png_chunk(b"IHDR",ihdr)+_png_chunk(b"IDAT",zlib.compress(raw,9))+_png_chunk(b"IEND",b"")
    Path(dst).parent.mkdir(parents=True,exist_ok=True);Path(dst).write_bytes(out);return right-left,bottom-top

def _validate_box(row):
    cid=str(row.get("character_id") or "").strip();vals=[]
    for k in ("x","y","w","h"):
        v=row.get(k)
        if not isinstance(v,(int,float)) or isinstance(v,bool):raise ValueError(f"{cid} face box {k} invalid")
        vals.append(float(v))
    x,y,w,h=vals
    if not cid or not (0<=x<1 and 0<=y<1 and 0.04<=w<=1 and 0.04<=h<=1 and x+w<=1.001 and y+h<=1.001):raise ValueError(f"{cid} face box invalid")
    return cid,x,y,w,h

def derive_face_crops(ep,face_boxes,allow_non_png=False):
    ep=Path(ep).resolve();master=read_json(ep/PIXEL_MASTER_REL);src=_repo_asset(master.get("asset_path"));primary=set(str(x) for x in ((load(ep) or {}).get("primary_cast_ids") or []));valid=[]
    for row in face_boxes or []:
        cid,x,y,bw,bh=_validate_box(row)
        if cid in primary:valid.append((cid,x,y,bw,bh))
    if not valid:return {"created":[],"warnings":["no primary face boxes supplied"]}
    if src.suffix.lower()!=".png":
        if allow_non_png:return {"created":[],"warnings":["source master is not PNG; group master fallback retained"]}
        raise ValueError("derived face crop requires PNG source")
    width,height,_,_,_,_=_decode_png(src);items={};created=[]
    for cid,x,y,bw,bh in valid:
        pad_x=bw*0.45;pad_y=bh*0.60;l=(x-pad_x)*width;t=(y-pad_y)*height;r=(x+bw+pad_x)*width;b=(y+bh+pad_y)*height
        dst=ep/CROPS_DIR/f"{cid}.png";cw,ch=_crop_png(src,dst,l,t,r,b)
        items[cid]={"character_id":cid,"path":repo_rel(dst),"sha256":sha_file(dst),"face_box":{"x":x,"y":y,"w":bw,"h":bh},"crop_size":[cw,ch],"derived_not_generated":True};created.append(cid)
    manifest={"schema_version":1,"source_master_path":master.get("asset_path"),"source_master_sha256":master.get("sha256"),"source_master_status":master.get("status"),"created_at":now(),"updated_at":now(),"items":items}
    write_json(ep/CROPS_REL,manifest);return {"created":created,"warnings":[]}

def validate_crops(ep):
    ep=Path(ep).resolve();p=ep/CROPS_REL
    if not p.is_file():return []
    d=read_json(p);e=[];master=read_json(ep/PIXEL_MASTER_REL) if (ep/PIXEL_MASTER_REL).is_file() else {}
    if d.get("schema_version")!=1:e.append("crop manifest schema_version must be 1")
    if str(d.get("source_master_sha256") or "").lower()!=str(master.get("sha256") or "").lower():e.append("crop manifest source master sha stale")
    for cid,row in (d.get("items") or {}).items():
        try:
            fp=_repo_asset(row.get("path"))
            if not fp.is_file():e.append(f"crop {cid} missing")
            elif sha_file(fp).lower()!=str(row.get("sha256") or "").lower():e.append(f"crop {cid} sha mismatch")
        except Exception:e.append(f"crop {cid} path invalid")
    return e

def three_view_reference(ep,character_id):
    return character_three_view.reference(Path(ep).resolve(), character_id)


def crop_reference(ep,character_id,allow_provisional=False):
    ep=Path(ep).resolve()
    if validate_pixel_master(ep,allow_provisional=allow_provisional):return None
    p=ep/CROPS_REL
    if not p.is_file() or validate_crops(ep):return None
    row=(read_json(p).get("items") or {}).get(str(character_id))
    if not isinstance(row,dict):return None
    return {"path":row["path"],"role":f"character_crop:{character_id}","kind":"identity","sha256":row["sha256"],"character_id":str(character_id)}

def self_test():
    assert PIXEL_MASTER_REL.as_posix()=="meta/character-pixel-master.json";assert CROPS_REL.as_posix()=="meta/character-master-crops.json";assert _identity_spec_locked({"identity_spec_locked":True});assert _identity_spec_locked({"master_identity_locked":True});print("CHARACTER VISUAL FINAL CLOSURE SELF-TEST PASS")

def main():
    ap=argparse.ArgumentParser();sub=ap.add_subparsers(dest="cmd",required=True)
    p=sub.add_parser("prepare");p.add_argument("episode_dir");p.add_argument("--force",action="store_true")
    p=sub.add_parser("validate");p.add_argument("episode_dir");p.add_argument("--allow-draft",action="store_true")
    p=sub.add_parser("verify-pixel-master");p.add_argument("episode_dir");p.add_argument("--allow-provisional",action="store_true")
    p=sub.add_parser("verify-crops");p.add_argument("episode_dir");p=sub.add_parser("show");p.add_argument("episode_dir");p=sub.add_parser("show-pixel-master");p.add_argument("episode_dir");sub.add_parser("self-test");a=ap.parse_args()
    if a.cmd=="self-test":self_test();return 0
    ep=Path(a.episode_dir).resolve()
    if a.cmd=="prepare":print(json.dumps(prepare(ep,a.force),ensure_ascii=False,indent=2));return 0
    if a.cmd=="validate":e=validate(ep,not a.allow_draft)
    elif a.cmd=="verify-pixel-master":e=validate_pixel_master(ep,allow_provisional=a.allow_provisional)
    elif a.cmd=="verify-crops":e=validate_crops(ep)
    else:
        if a.cmd=="show-pixel-master":
            p=ep/PIXEL_MASTER_REL;print(p.read_text(encoding="utf-8-sig") if p.is_file() else "{}")
        else:
            print(json.dumps(load(ep) or {},ensure_ascii=False,indent=2))
        return 0
    if e:[print("FAIL:",x) for x in e];return 2
    print("VERIFIED");return 0
if __name__=="__main__":raise SystemExit(main())
