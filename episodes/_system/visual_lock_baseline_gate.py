#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Machine bridge between Visual Lock baseline generation and the parallel three."""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, shutil, subprocess, sys, tempfile
from pathlib import Path
import character_visual_contract
import codex_user_runner
import frame_contract
import codex_critic_runner
import episode_performance
import product_review_adapter
import production_queue_store
import scheduler_core
import runtime_provenance
import runtime_router
import storyos_config
import story_json
import runtime_timeout_policy
import runtime_command
import production_ledger
import production_ledger_persistence
import local_vision_shadow

ROOT=Path(__file__).resolve().parents[2]
SYSTEM=Path(__file__).resolve().parent
REL=Path("meta/visual-lock-baseline-review.json")
CANDIDATE_REL=Path("meta/.visual-lock-baseline-review.candidate.json")
CHECKS=("visual_profile_match","reality_first","ordinary_life_density","unposed_capture","not_cinematic","capture_credibility","identity_usable","group_members_distinct","identity_anchor_usable")

def now():return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")
def read_json(p):
    return story_json.read_json(p)
def write_json(p,d):
    story_json.write_json(p, d)
def sha_file(p):
    h=hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):h.update(b)
    return h.hexdigest()
def repo_file(raw):
    p=Path(str(raw));p=p.resolve() if p.is_absolute() else (ROOT/p).resolve();p.relative_to(ROOT.resolve())
    if not p.is_file():raise ValueError(f"file missing: {raw}")
    return p
def repo_rel(p):return Path(p).resolve().relative_to(ROOT.resolve()).as_posix()

def baseline_plan(ep):
    p=Path(ep)/"meta/visual-lock-plan.json"
    if not p.is_file():raise ValueError("visual-lock-plan missing")
    row=next((x for x in (read_json(p).get("items") or []) if x.get("role")=="ordinary_baseline"),None)
    if not row:raise ValueError("ordinary_baseline missing from visual-lock-plan")
    return row
def baseline_frame(ep):return int(baseline_plan(ep)["frame"])

def _revision_baseline_binding(ep):
    """Return the current Revision's frozen baseline inputs, if any."""
    plan_path=Path(ep)/"meta/visual-lock-plan.json"
    if not plan_path.is_file():return None
    plan=read_json(plan_path)
    revision_id=str(plan.get("production_revision_id") or "").strip()
    if not revision_id:return None
    row=next((r for r in (plan.get("items") or [])
              if r.get("role")=="ordinary_baseline"),None)
    if not isinstance(row,dict) or row.get("production_revision_id")!=revision_id:
        raise ValueError("BASELINE_REVISION_PLAN_BINDING_MISSING")
    bound={key:row.get(key) for key in
           ("production_revision_id","input_sha256","prompt_sha256")}
    if any(not isinstance(value,str) or len(value)!=64
           for key,value in bound.items() if key!="production_revision_id"):
        raise ValueError("BASELINE_REVISION_PLAN_SHA_MISSING")
    return bound

def _review_matches_revision(review, binding):
    return all(str(review.get(key) or "")==str(value or "")
               for key,value in binding.items())

def generated_baseline(ep):
    ep=Path(ep).resolve();frame=baseline_frame(ep);q=scheduler_core.load_queue(ep)
    rows=[x for x in (q.get("items") or []) if int(x.get("frame") or -1)==frame and x.get("scope") in {"visual_lock","repair","baseline_candidate"} and x.get("status")=="generated" and x.get("output_path")]
    if not rows:raise ValueError(f"ordinary_baseline frame {frame:02d} is not generated")
    row=rows[-1];asset=repo_file(row["output_path"])
    return {"frame":frame,"asset_path":repo_rel(asset),"sha256":sha_file(asset),"frame_contract_sha256":frame_contract.compile_frame(ep,frame,write_cache=False)["contract_sha256"],"queue_item_id":row.get("id")}

def prepare_review(ep,force=False):
    ep=Path(ep).resolve();p=ep/REL
    binding=_revision_baseline_binding(ep)
    if p.is_file():
        previous=read_json(p)
        if not force and (binding is None or _review_matches_revision(previous,binding)):
            return previous
        if binding and not _review_matches_revision(previous,binding):
            # Never silently discard the old Revision/legacy actual-pixel review.
            original=p.read_bytes();digest=hashlib.sha256(original).hexdigest()
            archive=ep/"meta/runtime/review-exports"/f"visual-lock-baseline-review-{digest[:16]}.json"
            archive.parent.mkdir(parents=True,exist_ok=True)
            try:
                with archive.open("xb") as handle:handle.write(original)
            except FileExistsError:
                if archive.read_bytes()!=original:
                    raise ValueError("BASELINE_HISTORY_ARCHIVE_COLLISION")
    src=generated_baseline(ep);cv=character_visual_contract.load(ep) or {};primary=[str(x) for x in (cv.get("primary_cast_ids") or [])]
    d={"schema_version":1,"status":"DRAFT","decision":"PENDING","created_at":now(),"role":"ordinary_baseline",**src,
       **(binding or {}),
       "reviewer_scope":"delegated_pixel_review","checks":{k:"PENDING" for k in CHECKS},
       "face_boxes":[{"character_id":cid,"x":None,"y":None,"w":None,"h":None} for cid in primary],
       "note":"Inspect actual pixels. Face boxes are normalized 0..1 and derive crops only."}
    write_json(p,d)
    # Local YuNet shadow: derived candidate face boxes for the baseline image.
    # Fail-soft; never changes the review, face_boxes, gates, or episode state.
    local_vision_shadow.run_visual_face_shadow(ep)
    episode_performance.safe_begin_named_span(ep,"VISUAL_LOCK_BASELINE_REVIEW",source="visual_lock_baseline_gate",
                                              metadata={"frame":src.get("frame"),"asset_path":src.get("asset_path")})
    return d

def _box_errors(ep,review):
    if not character_visual_contract.pixel_master_required(ep):return []
    primary=set(str(x) for x in ((character_visual_contract.load(Path(ep)) or {}).get("primary_cast_ids") or []));boxes=review.get("face_boxes") or [];seen=set();e=[]
    for row in boxes:
        cid=str((row or {}).get("character_id") or "")
        if cid not in primary:continue
        try:x,y,w,h=[float(row[k]) for k in ("x","y","w","h")]
        except Exception:e.append(f"face box {cid} incomplete");continue
        if not (0<=x<1 and 0<=y<1 and 0.04<=w<=1 and 0.04<=h<=1 and x+w<=1.001 and y+h<=1.001):e.append(f"face box {cid} invalid")
        seen.add(cid)
    for cid in primary-seen:e.append(f"primary face box missing: {cid}")
    return e

def validate_review(ep):
    ep=Path(ep).resolve();p=ep/REL
    if not p.is_file():return ["visual-lock-baseline-review.json missing"]
    d=read_json(p);e=[]
    if d.get("schema_version")!=1:e.append("baseline review schema_version must be 1")
    if d.get("decision")!="PASS":e.append("baseline review decision must be PASS")
    try:
        binding=_revision_baseline_binding(ep)
        if binding and not _review_matches_revision(d,binding):
            e.append("BASELINE_REVIEW_REVISION_BINDING_MISSING_OR_STALE")
    except Exception as exc:
        e.append(str(exc))
    try:src=generated_baseline(ep)
    except Exception as exc:return [str(exc)]
    for k in ("frame","asset_path","sha256"):
        if str(d.get(k) or "").lower()!=str(src.get(k) or "").lower():e.append(f"baseline review {k} stale")
    if not frame_contract.recorded_contract_matches_current(ep, d.get("frame") or src.get("frame"), str(d.get("frame_contract_sha256") or "")):
        e.append("baseline review frame_contract_sha256 stale")
    for k in CHECKS:
        if str((d.get("checks") or {}).get(k) or "").upper()!="PASS":e.append(f"baseline review check {k} must PASS")
    e.extend(_box_errors(ep,d));return e

def _mark_baseline_pass(ep,review):
    ep=Path(ep).resolve();gpath=ep/"meta/story-gates.json";g=read_json(gpath);items=(((g.get("visual") or {}).get("calibration") or {}).get("items") or []);hit=False
    for row in items:
        if isinstance(row,dict) and row.get("role")=="ordinary_baseline":
            row["asset_path"]=review["asset_path"];row["sha256"]=review["sha256"];row["frame_contract_sha256"]=review["frame_contract_sha256"];row["decision"]="passed";row["note"]="baseline separately PASS; parallel-three may start";hit=True
    if not hit:raise ValueError("ordinary_baseline calibration item missing")
    write_json(gpath,g)

def _ledger_pass(ep,frame):
    ep=Path(ep).resolve()
    if not production_ledger.authority_exists(ep):return
    key=f"{int(frame):02d}"
    d=production_ledger.load_authority(ep,default={}) or {};row=((d.get("frames") or {}).get(key) or {});status=str(row.get("status") or "")
    if status in {"ORIGINAL_READY","REPAIR_READY"}:
        cp=runtime_command.run_argv([sys.executable,str(SYSTEM/"production_ledger.py"),"review",str(ep),"--frame",key,"--decision","pass","--notes","Visual Lock ordinary baseline separate PASS"],cwd=ROOT,capture=True)
        if cp.returncode!=0:raise ValueError("baseline ledger PASS failed: "+cp.stdout[-1200:])
        d=production_ledger.load_authority(ep,default={}) or {};row=((d.get("frames") or {}).get(key) or {});status=str(row.get("status") or "")
    # A baseline PASS is already a real actual-pixel approval. Leaving the row
    # PASSED with approved_asset=null breaks incremental review and later release
    # binding. Promote the exact SHA-bound candidate immediately; locking still
    # remains the responsibility of the later canonical production/release path.
    if status=="PASSED" and not isinstance(row.get("approved_asset"),dict):
        cp=runtime_command.run_argv([sys.executable,str(SYSTEM/"production_ledger.py"),"promote",str(ep),"--frame",key],cwd=ROOT,capture=True)
        if cp.returncode!=0:raise ValueError("baseline ledger promote failed: "+cp.stdout[-1200:])

def critic_prompt(ep):
    draft=prepare_review(ep,force=False);candidate=Path(ep)/CANDIDATE_REL
    face_hint=local_vision_shadow.face_hint(ep)
    return f"""You are a fresh isolated Story OS Visual Lock ordinary-baseline actual-pixel reviewer.
Inspect the attached baseline image itself. This PASS unlocks the parallel-three Visual Lock images and may create the provisional character pixel master, so fail closed on visible identity/capture/style problems.
Required checks: {list(CHECKS)}
The target is an ordinary believable phone/photo baseline: reality-first, unposed, non-cinematic, usable identity, distinct group members where applicable.
Capture/style review is genre/action neutral: judge the actual locked story and frame; never demand any example action, location, prop, cast size, or motion intensity. Stillness can be authentic. Motion blur and camera defects require physical causes. Reject forced drama, invented action, director-blocked staging, and excessive cinematic polish.
If this Episode is an explicit pure daily-life / no-anomaly story, ordinary_life_density means believable resident/friend life (breakfast, walking, chatting, errands, rest). Do NOT require a visible job workflow merely because a reusable celestial visual profile also supports worker stories.
For core characters, this baseline is also Frame01 Character Identity Anchor evidence. The image must be usable as a later identity reference: clear face visibility, recognizable person, not only back view, not too distant, and suitable for Character Master creation.
Write ONLY JSON to {repo_rel(candidate)}:
{{"decision":"PASS|FAIL","checks":{{"visual_profile_match":"PASS|FAIL","reality_first":"PASS|FAIL","ordinary_life_density":"PASS|FAIL","unposed_capture":"PASS|FAIL","not_cinematic":"PASS|FAIL","capture_credibility":"PASS|FAIL","identity_usable":"PASS|FAIL","group_members_distinct":"PASS|FAIL","identity_anchor_usable":"PASS|FAIL"}},"face_boxes":[{{"character_id":"P01","x":0.0,"y":0.0,"w":0.1,"h":0.1}}],"note":"actual-pixel evidence"}}
Face boxes use normalized 0..1 coordinates and must cover every primary cast member when pixel master is required.
Local pre-scan (advisory only, never authoritative):
{face_hint or "none"}

Do not modify source files or the image.
"""

def codex_critic_prompt(ep):
    character_contract = character_visual_contract.load(Path(ep)) or {}
    primary_ids = [str(x) for x in character_contract.get("primary_cast_ids") or []]
    members = character_contract.get("members") or {}
    primary_hair = {cid: ((members.get(cid) or {}).get("hair") or {}).get("haircut_anchor", "")
                    for cid in primary_ids}
    candidate=Path(ep)/CANDIDATE_REL
    schema='{"pixel_evidence_available":true,"decision":"PASS|FAIL","checks":{"visual_profile_match":"PASS|FAIL","reality_first":"PASS|FAIL","ordinary_life_density":"PASS|FAIL","unposed_capture":"PASS|FAIL","not_cinematic":"PASS|FAIL","capture_credibility":"PASS|FAIL","identity_usable":"PASS|FAIL","group_members_distinct":"PASS|FAIL","identity_anchor_usable":"PASS|FAIL"},"face_boxes":[{"character_id":"P01","x":0.0,"y":0.0,"w":0.1,"h":0.1}],"note":"actual-pixel evidence"}'
    face_hint=local_vision_shadow.face_hint(ep)
    return f"""You are a fresh isolated Story OS Visual Lock ordinary-baseline actual-pixel reviewer.
The baseline image is already attached to this request. Inspect the attached pixels directly.
Do NOT search the filesystem, do NOT call shell/tools, and do NOT modify any source file or image.
This PASS unlocks the parallel-three Visual Lock images and may create the provisional character pixel master, so fail closed on visible identity/capture/style problems.
Required checks: {list(CHECKS)}
The target is an ordinary believable phone/photo baseline: reality-first, unposed, non-cinematic, usable identity, distinct group members where applicable.
Capture/style review is genre/action neutral: judge the actual locked story and frame; never demand any example action, location, prop, cast size, or motion intensity. Stillness can be authentic. Motion blur and camera defects require physical causes. Reject forced drama, invented action, director-blocked staging, and excessive cinematic polish.
If this Episode is an explicit pure daily-life / no-anomaly story, ordinary_life_density means believable resident/friend life (breakfast, walking, chatting, errands, rest). Do NOT require a visible job workflow merely because a reusable celestial visual profile also supports worker stories.
For core characters, this baseline is also Frame01 Character Identity Anchor evidence. The image must be usable as a later identity reference: clear face visibility, recognizable person, not only back view, not too distant, and suitable for Character Master creation.
Face boxes use normalized 0..1 coordinates and must cover every primary cast member when pixel master is required.
The authoritative primary cast IDs in this Episode are {primary_ids}. Their hair identity cues are {json.dumps(primary_hair, ensure_ascii=False)}.
Use these exact primary IDs in face_boxes; a supporting character ID (for example P02) never substitutes for P03.
Locate each primary person by visual identity; never relabel an unrelated face or fabricate a box.
If a primary person is absent or cannot be identified confidently from the pixels and cast contract, return FAIL and explain which ID is missing.
If the attachment cannot actually be decoded/seen, set pixel_evidence_available=false; that is an infrastructure failure, not a content FAIL.
Local pre-scan (advisory only, never authoritative):
{face_hint or "none"}

Respond ONLY with one JSON object matching this schema, with no markdown and no commentary:
{schema}
The CLI will persist your final JSON response to {repo_rel(candidate)}.
"""


def run_product_critic(ep,attempt=1):
    ep=Path(ep).resolve();draft=prepare_review(ep,force=False);runtime,_=runtime_router.detect()
    if runtime not in {"WORK","WEB"}:raise ValueError("baseline product critic requires WORK/WEB")
    spec_source=character_visual_contract.materialize_export(ep)
    sources=[repo_file(draft["asset_path"]),ep/"meta/story-gates.json"]
    if spec_source is not None:sources.append(spec_source)
    prov=frame_contract.provenance(ep,int(draft["frame"]))
    if prov:
        contract_source=frame_contract.materialize_export(ep,int(draft["frame"]))
        if not contract_source.is_file():raise ValueError(f"baseline frame contract export missing: {prov.get('path')}")
        sources.append(contract_source)
    request=product_review_adapter.prepare(ep,kind="visual-lock-baseline",runtime=runtime,attempt=attempt,prompt=critic_prompt(ep),source_paths=sources,candidate_path=ep/CANDIDATE_REL)
    return request

def finalize_product_critic(ep,attempt=1,runtime="WORK"):
    ep=Path(ep).resolve();draft=prepare_review(ep,force=False);candidate=ep/CANDIDATE_REL
    data,provenance=product_review_adapter.finalize_candidate(ep,kind="visual-lock-baseline",runtime=runtime,attempt=attempt,candidate_path=candidate)
    review={**draft,"decision":str(data.get("decision") or "FAIL").upper(),"checks":data.get("checks") or {},"face_boxes":data.get("face_boxes") or [],"note":str(data.get("note") or ""),"critic_provenance":provenance}
    write_json(ep/REL,review)
    errors=validate_review(ep)
    if errors:return {"status":"FAIL","errors":errors}
    result=approve(ep)
    product_review_adapter.mark_complete(ep,"visual-lock-baseline",attempt=attempt,final_path=ep/REL)
    candidate.unlink(missing_ok=True)
    return {"status":"PASS",**result}

def run_codex_critic(ep,attempt=1,codex_raw=None,timeout=None):
    ep=Path(ep).resolve();draft=prepare_review(ep,force=True);candidate=ep/CANDIDATE_REL;candidate.unlink(missing_ok=True)
    if timeout is None:
        timeout = runtime_timeout_policy.seconds("visual_baseline_critic")
    asset=repo_file(draft["asset_path"]);before=sha_file(asset)
    staging=codex_user_runner.workspace_path(prefix="story-os-baseline-");staged=staging/("baseline"+asset.suffix.lower())
    shutil.copy2(asset,staged)
    # STORY_OS_CRITIC_MODEL_OVERRIDE: see visual_lock_v21.py. The pinned image
    # controller model is for image generation; a vision critic uses the optional
    # dedicated critic key when configured, else the Codex CLI default model.
    model=runtime_router.vision_review_model()
    effort=runtime_router.vision_review_effort("final")
    codex=codex_critic_runner.resolve_codex(codex_raw);log=ep/"meta"/f"visual-lock-baseline-critic-attempt-{attempt}.jsonl"
    try:
        done=codex_critic_runner.launch(
            codex_critic_prompt(ep),
            codex=codex,
            root=ROOT,
            timeout=timeout,
            output_path=candidate,
            attachments=[staged],
            model=model,
            reasoning_effort=effort,
            sandbox=codex_critic_runner.default_sandbox(),
            log_path=log,
        )
    finally:
        shutil.rmtree(staging,ignore_errors=True)
    if done.returncode!=0:raise ValueError(f"baseline Codex critic failed rc={done.returncode}; log={repo_rel(log)}")
    if not candidate.is_file():raise ValueError(f"baseline Codex critic did not produce candidate JSON; log={repo_rel(log)}")
    if sha_file(asset)!=before:raise ValueError("baseline Codex critic modified source image")
    data=read_json(candidate);provenance=runtime_provenance.build_vision_critic_provenance(attempt=attempt,log=repo_rel(log),review_scope="VISUAL_LOCK_BASELINE",allow_bounded_candidate_attempt=attempt>2);provenance["log_sha256"]=sha_file(log)
    note=str(data.get("note") or "")
    no_pixels=(data.get("pixel_evidence_available") is False or any(token in note.lower() for token in ("no pixel evidence","could not be decoded","vision sidecar","cannot inspect pixels","unable to inspect pixels")))
    if no_pixels:
        candidate.unlink(missing_ok=True)
        return {"status":"TECHNICAL_FAILURE","issue_codes":["INPUT_IMAGES_UNAVAILABLE"],"note":note,"critic_provenance":provenance}
    review={**draft,"decision":str(data.get("decision") or "FAIL").upper(),"checks":data.get("checks") or {},"face_boxes":data.get("face_boxes") or [],"note":note,"critic_provenance":provenance}
    write_json(ep/REL,review);errors=validate_review(ep)
    candidate.unlink(missing_ok=True)
    if errors:return {"status":"FAIL","errors":errors}
    return {"status":"PASS",**approve(ep)}

def approve(ep):
    ep=Path(ep).resolve();errors=validate_review(ep)
    if errors:raise ValueError("; ".join(errors[:12]))
    review=read_json(ep/REL);_mark_baseline_pass(ep,review);_ledger_pass(ep,review["frame"])
    needs_master=character_visual_contract.pixel_master_required(ep)
    review["status"]="LOCKED";review["approved_at"]=now();review["provisional_master_created"]=needs_master;write_json(ep/REL,review)
    review_sha=sha_file(ep/REL);master=None
    if needs_master:
        master=character_visual_contract.lock_provisional_pixel_master(ep,frame=review["frame"],asset_path=review["asset_path"],asset_sha256=review["sha256"],frame_contract_sha256=review["frame_contract_sha256"],baseline_review_sha256=review_sha,face_boxes=review.get("face_boxes") or [])
        if Path(review["asset_path"]).suffix.lower()==".png":
            primary=set(str(x) for x in ((character_visual_contract.load(ep) or {}).get("primary_cast_ids") or []));made=set(((read_json(ep/character_visual_contract.CROPS_REL).get("items") or {}).keys())) if (ep/character_visual_contract.CROPS_REL).is_file() else set();missing=primary-made
            if missing:raise ValueError("primary derived crops missing: "+",".join(sorted(missing)))
    episode_performance.safe_end_named_span(ep,"VISUAL_LOCK_BASELINE_REVIEW",status="PASS",
                                            metadata={"frame":review["frame"],"pixel_master_status":(master or {}).get("status")})
    return {"baseline_review":"PASS","frame":review["frame"],"baseline_review_sha256":review_sha,"pixel_master_status":(master or {}).get("status"),"crop_result":(master or {}).get("crop_result")}

def approved(ep):
    ep=Path(ep).resolve()
    # A later higher-level pixel review may explicitly reopen a previously
    # PASSED baseline. In that state the historical baseline review/Pixel Master
    # are superseded evidence only and must not satisfy dependency gates.
    try:
        frame = baseline_frame(ep)
        ledger = production_ledger.load_authority(ep,default={}) or {}
        row = ((ledger.get("frames") or {}).get(f"{int(frame):02d}") or {})
        if str(row.get("status") or "") not in {"PASSED", "LOCKED"}:
            return False
    except production_ledger_persistence.ProductionLedgerAuthorityIncomplete:
        raise
    except Exception:
        return False
    if validate_review(ep):return False
    try:
        binding=_revision_baseline_binding(ep)
        if binding:
            # A new Revision's Pending baseline can never inherit legacy PASS.
            # The fresh review and the current calibration row must both bind
            # the same immutable Revision input and actual pixel SHA.
            gates=read_json(ep/"meta/story-gates.json")
            rows=(((gates.get("visual") or {}).get("calibration") or {}).get("items") or [])
            item=next((r for r in rows if isinstance(r,dict)
                       and r.get("role")=="ordinary_baseline"),None)
            review=read_json(ep/REL)
            if (not item or item.get("decision")!="passed"
                    or not _review_matches_revision(item,binding)
                    or item.get("asset_path")!=review.get("asset_path")
                    or item.get("sha256")!=review.get("sha256")):
                return False
    except Exception:
        return False
    if character_visual_contract.pixel_master_required(ep):return not character_visual_contract.validate_pixel_master(ep,allow_provisional=True)
    return True

def validate_final_requirement(ep):
    """Final verify accepts real baseline review or an explicitly marked legacy backfill."""
    ep=Path(ep).resolve();errors=validate_review(ep)
    if not errors:return []
    mp=ep/character_visual_contract.PIXEL_MASTER_REL
    if mp.is_file():
        try:
            d=read_json(mp)
            if d.get("migration_source")=="legacy_four_admission_review_backfill" and d.get("status")=="LOCKED":
                master_errors=character_visual_contract.validate_pixel_master(ep)
                if not master_errors:return []
        except Exception:pass
    return errors

def is_baseline_dependency(ep,dep):
    try:return int(dep)==baseline_frame(ep)
    except Exception:return False

def awaiting_review(ep,q):
    try:
        frame=baseline_frame(ep)
        if approved(ep):return False
        # Once a bounded repair has been authorized, generation must run before
        # another review. Otherwise the original generated row would keep this
        # gate true and starve the queued repair forever.
        generation_active=any(
            int(x.get("frame") or -1)==frame and x.get("kind") in {"repair","baseline_candidate"}
            and x.get("status") in {"queued","running","tech_failed"}
            for x in (q.get("items") or [])
        )
        if generation_active:return False
        try:
            current=generated_baseline(ep)
        except Exception:
            return False
        # Do not re-review the exact same failed pixels forever. Once a SHA-bound
        # FAIL has been recorded, the runtime must either enqueue the next bounded
        # baseline candidate or stop after the pool is exhausted.
        review=read_json(Path(ep)/REL) if (Path(ep)/REL).is_file() else {}
        if str(review.get("decision") or "").upper()=="FAIL" and str(review.get("sha256") or "").lower()==str(current.get("sha256") or "").lower():
            return False
        # Visual Lock dependents may have moved into repair/baseline-candidate
        # scopes after bounded review failures. They still depend on the current
        # baseline identity anchor and must keep baseline review routable.
        dependents=any(x.get("status")=="queued" and frame in [int(v) for v in (x.get("depends_on") or [])] for x in (q.get("items") or []))
        return bool(current.get("asset_path")) and dependents
    except Exception:return False

def self_test():assert len(CHECKS)>=8;print("VISUAL LOCK BASELINE GATE SELF-TEST PASS")
def main():
    ap=argparse.ArgumentParser();sub=ap.add_subparsers(dest="cmd",required=True)
    p=sub.add_parser("prepare-review");p.add_argument("episode_dir");p.add_argument("--force",action="store_true")
    p=sub.add_parser("run-critic");p.add_argument("episode_dir");p.add_argument("--attempt",type=int,default=1);p.add_argument("--codex");p.add_argument("--timeout",type=int,default=None)
    p=sub.add_parser("finalize-review");p.add_argument("episode_dir");p.add_argument("--attempt",type=int,default=1);p.add_argument("--runtime",choices=["WORK","WEB"],default="WORK")
    p=sub.add_parser("approve");p.add_argument("episode_dir");p=sub.add_parser("verify");p.add_argument("episode_dir");p=sub.add_parser("status");p.add_argument("episode_dir");sub.add_parser("self-test");a=ap.parse_args()
    if a.cmd=="self-test":self_test();return 0
    ep=Path(a.episode_dir).resolve()
    try:
        if a.cmd=="prepare-review":print(json.dumps(prepare_review(ep,a.force),ensure_ascii=False,indent=2));return 0
        if a.cmd=="run-critic":
            vision_runtime,_=runtime_router.vision_review_runtime()
            if a.codex or vision_runtime=="CODEX":
                result=run_codex_critic(ep,a.attempt,a.codex,a.timeout);print(json.dumps(result,ensure_ascii=False,indent=2));return 0 if result.get("status")=="PASS" else 2
            print(json.dumps(run_product_critic(ep,a.attempt),ensure_ascii=False,indent=2));return product_review_adapter.HOST_ACTION_REQUIRED_RC
        if a.cmd=="finalize-review":
            result=finalize_product_critic(ep,a.attempt,a.runtime);print(json.dumps(result,ensure_ascii=False,indent=2));return 0 if result.get("status")=="PASS" else 2
        if a.cmd=="approve":print(json.dumps(approve(ep),ensure_ascii=False,indent=2));return 0
        if a.cmd=="verify":
            e=validate_review(ep)
            if e:[print("FAIL:",x) for x in e];return 2
            print("VISUAL LOCK BASELINE REVIEW VERIFIED");return 0
        queue=scheduler_core.load_queue(ep)
        print(json.dumps({"approved":approved(ep),"awaiting_review":awaiting_review(ep,queue)},ensure_ascii=False,indent=2));return 0
    except Exception as exc:print("BASELINE GATE ERROR:",exc);return 3
if __name__=="__main__":raise SystemExit(main())
