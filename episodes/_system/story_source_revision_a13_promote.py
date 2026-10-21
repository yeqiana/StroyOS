#!/usr/bin/env python3
"""Authorized A13 source revision promotion, never a review PASS or model call."""
from __future__ import annotations
import hashlib,json,os,shutil,sys,argparse
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
SYSTEM=ROOT/"episodes"/"_system"
sys.path.insert(0,str(SYSTEM))
import story_review,story_serial_recheck,story_narrative_form,runtime_request,runtime_driver
HERE=next(d for d in ROOT.rglob('story-source-revision-a13') if d.is_dir() and (d/'candidate-manifest.json').is_file())
EP=HERE.parents[2]
NAMES=("story.md","storyboard.md","subtitles.yaml")
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def evidence():
 m=json.loads((HERE/"candidate-manifest.json").read_text("utf-8"))
 if m.get("status")!="CANDIDATE_ONLY" or m.get("user_authorized_limited_revision") is not True: raise ValueError("CANDIDATE_AUTHORIZATION_MISSING")
 r=runtime_request.authority_for_episode(EP)
 if not story_narrative_form.is_locked(r) or story_narrative_form.from_request(r)!="SERIAL_EPISODE":raise ValueError("WRONG_LOCKED_SERIAL_REQUEST")
 source=next((EP/"docs/source").glob("*.txt"))
 if sha(source)!=m["original_user_source_sha256"]:raise ValueError("ORIGINAL_USER_SOURCE_MODIFIED")
 old=story_review.load_review(EP)
 if not isinstance(old,dict) or (old.get("summary") or {}).get("passed") is not False:raise ValueError("A12_FORMAL_FAIL_REQUIRED")
 pr=old.get("critic_provenance") or {}
 if pr.get("attempt")!=12 or pr.get("review_scope")!=story_serial_recheck.REVIEW_SCOPE:raise ValueError("A12_FAIL_PROVENANCE_MISMATCH")
 from review_record_persistence import _payload_content_sha
 previous=_payload_content_sha(old)
 for n in NAMES:
  if sha(EP/"docs"/n)!=m["baseline_sha256"][n]:raise ValueError("BASELINE_SOURCE_DRIFT:"+n)
  if sha(HERE/"candidate/docs"/n)!=m["candidate_sha256"][n]:raise ValueError("CANDIDATE_DRIFT:"+n)
  field={"story.md":"story_sha256","storyboard.md":"storyboard_sha256","subtitles.yaml":"subtitle_source_sha256"}[n]
  if old.get(field)!=m["baseline_sha256"][n]:raise ValueError("A12_FAIL_NOT_BOUND_TO_BASELINE:"+n)
 owner=runtime_driver.status(EP)
 if owner.get("driver_state") in {"RUNNING","ALIVE_NOT_BEATING","UNKNOWN"}:raise ValueError("WRITER_OR_DRIVER_ACTIVE")
 if (HERE/"authority.json").exists() or (HERE/"promoted.json").exists():raise ValueError("SOURCE_REVISION_ALREADY_RESERVED")
 return {"schema":"storyos.authorized_source_revision_a13.v1","authorization":"user_explicitly_approved_limited_48_frame_story_edit_on_2026-10-20",
  "previous_review_attempt":12,"previous_review_scope":pr["review_scope"],
  "previous_failed_review_sha256":previous,"source_story_sha256":m["baseline_sha256"]["story.md"],
  "source_storyboard_sha256":m["baseline_sha256"]["storyboard.md"],
  "source_subtitle_sha256":m["baseline_sha256"]["subtitles.yaml"],
  "candidate_story_sha256":m["candidate_sha256"]["story.md"],
  "candidate_storyboard_sha256":m["candidate_sha256"]["storyboard.md"],
  "candidate_subtitle_sha256":m["candidate_sha256"]["subtitles.yaml"],
  "source_original_sha256":m["original_user_source_sha256"],"changed_frames":m["changed_frames"],
  "review_status":"PENDING_NEW_SOURCE_REVISION_CRITIC_NOT_A12_REPLAY",
  "mysql_review_records_modified":False,"original_user_source_modified":False}
def run(apply):
 proof=evidence()
 if not apply:return {"status":"AUTHORIZED_SOURCE_REVISION_READY","audit":proof,"read_only":True}
 before=HERE/"baseline/docs"
 before.mkdir(parents=True,exist_ok=True)
 for n in NAMES:
  target=before/n
  with target.open("xb") as f:
   raw=(EP/"docs"/n).read_bytes();f.write(raw);f.flush();os.fsync(f.fileno())
  assert sha(target)==proof[{"story.md":"source_story_sha256","storyboard.md":"source_storyboard_sha256","subtitles.yaml":"source_subtitle_sha256"}[n]]
 token=HERE/"authority.json"
 with token.open("x",encoding="utf-8") as f:
  json.dump(proof,f,ensure_ascii=False,sort_keys=True,indent=2)
  f.write("\n");f.flush();os.fsync(f.fileno())
 updated=[]
 try:
  for n in NAMES:
   target=EP/"docs"/n; temporary=target.with_suffix(target.suffix+".a13-tmp")
   shutil.copyfile(HERE/"candidate/docs"/n,temporary)
   os.replace(temporary,target);updated.append(n)
  for n in NAMES:
   key={"story.md":"candidate_story_sha256","storyboard.md":"candidate_storyboard_sha256","subtitles.yaml":"candidate_subtitle_sha256"}[n]
   assert sha(EP/"docs"/n)==proof[key],(n,"promoted source drift")
  assert sha(next((EP/"docs/source").glob("*.txt")))==proof["source_original_sha256"]
 except Exception:
  for n in updated:shutil.copyfile(before/n,EP/"docs"/n)
  raise
 receipt={"status":"AUTHENTIC_SOURCE_REVISION_PROMOTED_REVIEW_PENDING",**proof}
 done=HERE/"promoted.json"
 with done.open("x",encoding="utf-8") as f:
  json.dump(receipt,f,ensure_ascii=False,indent=2);f.write("\n");f.flush();os.fsync(f.fileno())
 return {"status":receipt["status"],"frames_modified":proof["changed_frames"],
         "story_sha":proof["candidate_story_sha256"],"storyboard_sha":proof["candidate_storyboard_sha256"],
         "old_fail_sha":proof["previous_failed_review_sha256"],"review":"PENDING"}
def main():
 ap=argparse.ArgumentParser()
 ap.add_argument("--apply-authorized-revision",action="store_true")
 a=ap.parse_args()
 try:
  print(json.dumps(run(a.apply_authorized_revision),ensure_ascii=False,indent=2));return 0
 except Exception as exc:
  print("REJECTED:"+str(exc));return 22
if __name__=="__main__":raise SystemExit(main())
