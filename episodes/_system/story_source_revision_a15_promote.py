#!/usr/bin/env python3
"""Authorized A15 consolidated 48-frame source revision after independently failed A14."""
from __future__ import annotations
import argparse,hashlib,json,os,shutil
from pathlib import Path
import story_review,story_source_revision_a14_review as a14,story_narrative_form,runtime_request,runtime_driver,story_source_revision_a15_review as a15
ROOT=Path(__file__).resolve().parents[2]
HERE=next(d for d in ROOT.rglob("story-source-revision-a15")
          if d.is_dir() and (d/"candidate-manifest.json").is_file())
EP=HERE.parents[2]
NAMES=("story.md","storyboard.md","subtitles.yaml")
FIELDS={"story.md":"story_sha256","storyboard.md":"storyboard_sha256","subtitles.yaml":"subtitle_source_sha256"}
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def evidence():
 m=json.loads((HERE/"candidate-manifest.json").read_text("utf-8"))
 qa=json.loads((HERE/"full48-audit.json").read_text("utf-8"))
 if (qa.get("status")!="PASS" or qa.get("canonical_untouched") is not True
     or len(qa.get("frames") or [])!=48 or qa.get("changed_frames")!=m.get("changed_frames")
     or qa.get("issues")):raise ValueError("A15_FULL48_AUDIT_MISSING_OR_FAILED")
 if (m.get("status")!="A15_CANDIDATE_ONLY_A14_FAIL_PRESERVED"
     or m.get("changed_frames")!=[25,28,30,31,32,33,38,41,42,43,44,45,46,47,48]):raise ValueError("A15_SCOPE_OR_APPROVAL_MISMATCH")
 request=runtime_request.authority_for_episode(EP)
 if not story_narrative_form.is_locked(request) or story_narrative_form.from_request(request)!="SERIAL_EPISODE":
  raise ValueError("A15_WRONG_RUNTIME_REQUEST")
 prior=story_review.load_review(EP)
 if (not isinstance(prior,dict) or (prior.get("summary") or {}).get("passed") is not False
     or (prior.get("critic_provenance") or {}).get("attempt")!=14
     or (prior.get("critic_provenance") or {}).get("review_scope")!=a14.REVIEW_SCOPE):
  raise ValueError("A14_OFFICIAL_FAIL_REQUIRED")
 from review_record_persistence import _payload_content_sha
 previous=_payload_content_sha(prior)
 if not a15.historical_a14_fail_exists(EP,previous):
  raise ValueError("A14_FAILED_HISTORY_NOT_DURABLE")
 for n in NAMES:
  if sha(EP/"docs"/n)!=m["old_source_sha256"][n]:raise ValueError("A15_BASELINE_DRIFT:"+n)
  if sha(HERE/"candidate/docs"/n)!=m["candidate_source_sha256"][n]:raise ValueError("A15_CANDIDATE_DRIFT:"+n)
  if prior.get(FIELDS[n])!=m["old_source_sha256"][n]:raise ValueError("A14_FAILED_SOURCE_MISMATCH:"+n)
  if m["old_source_sha256"][n]==m["candidate_source_sha256"][n] and n!="subtitles.yaml":
   raise ValueError("A15_SOURCE_CHANGE_REQUIRED:"+n)
 a14approval=EP/"meta/runtime/story-source-revision-a14/authority.json"
 prev_approval=json.loads(a14approval.read_text("utf-8"))
 original=next((EP/"docs/source").glob("*.txt"))
 original_sha=sha(original)
 if original_sha!=prev_approval["source_original_sha256"]:raise ValueError("ORIGINAL_USER_BYTES_DRIFT")
 owner=runtime_driver.status(EP)
 if owner.get("driver_state") in {"RUNNING","ALIVE_NOT_BEATING","UNKNOWN"}:raise ValueError("A15_DRIVER_ACTIVE")
 if (HERE/"authority.json").exists() or (HERE/"promoted.json").exists():raise ValueError("A15_ALREADY_RESERVED")
 return {"schema":"storyos.authorized_source_revision_a15.v1",
  "authorization":"user_explicit_one_pass_four_issue_repair",
  "previous_review_attempt":14,"previous_review_scope":a14.REVIEW_SCOPE,
  "previous_failed_review_sha256":previous,
  "previous_source_approval_sha256":sha(a14approval),
  "full48_audit_sha256":sha(HERE/"full48-audit.json"),
  "source_story_sha256":m["old_source_sha256"]["story.md"],
  "source_storyboard_sha256":m["old_source_sha256"]["storyboard.md"],
  "source_subtitle_sha256":m["old_source_sha256"]["subtitles.yaml"],
  "candidate_story_sha256":m["candidate_source_sha256"]["story.md"],
  "candidate_storyboard_sha256":m["candidate_source_sha256"]["storyboard.md"],
  "candidate_subtitle_sha256":m["candidate_source_sha256"]["subtitles.yaml"],
  "source_original_sha256":original_sha,
  "changed_frames":[25,28,30,31,32,33,38,41,42,43,44,45,46,47,48],
  "review_status":"PENDING_NEW_SOURCE_CRITIC_A15_NO_A14_REPLAY",
  "historical_review_modified":False}
def run(apply:bool):
 proof=evidence()
 if not apply:return {"status":"A15_SOURCE_REVISION_ADMISSIBLE","audit":proof,"read_only":True}
 before=HERE/"baseline/docs"
 before.mkdir(parents=True,exist_ok=True)
 for n in NAMES:
  target=before/n
  with target.open("xb") as f:
   data=(EP/"docs"/n).read_bytes();f.write(data);f.flush();os.fsync(f.fileno())
  key={"story.md":"source_story_sha256","storyboard.md":"source_storyboard_sha256","subtitles.yaml":"source_subtitle_sha256"}[n]
  if sha(target)!=proof[key]:raise ValueError("A15_BACKUP_SHA_MISMATCH:"+n)
 ticket=HERE/"authority.json"
 with ticket.open("x",encoding="utf-8") as f:
  json.dump(proof,f,ensure_ascii=False,indent=2,sort_keys=True);f.write("\n");f.flush();os.fsync(f.fileno())
 updated=[]
 try:
  for n in NAMES:
   dest=EP/"docs"/n;temp=dest.with_suffix(dest.suffix+".a15-tmp")
   shutil.copyfile(HERE/"candidate/docs"/n,temp);os.replace(temp,dest);updated.append(n)
  for n in NAMES:
   key={"story.md":"candidate_story_sha256","storyboard.md":"candidate_storyboard_sha256","subtitles.yaml":"candidate_subtitle_sha256"}[n]
   if sha(EP/"docs"/n)!=proof[key]:raise ValueError("A15_PROMOTION_DRIFT:"+n)
  if sha(next((EP/"docs/source").glob("*.txt")))!=proof["source_original_sha256"]:
   raise ValueError("A15_USER_ORIGINAL_CHANGED")
 except Exception:
  for n in updated:shutil.copyfile(before/n,EP/"docs"/n)
  raise
 receipt={"status":"AUTHENTIC_SOURCE_REVISION_PROMOTED_REVIEW_PENDING",**proof}
 with (HERE/"promoted.json").open("x",encoding="utf-8") as f:
  json.dump(receipt,f,ensure_ascii=False,indent=2);f.write("\n");f.flush();os.fsync(f.fileno())
 return {"status":"A15_SOURCE_PROMOTED_REVIEW_PENDING",
   "changed_frames":proof["changed_frames"],"previous_fail_sha":proof["previous_failed_review_sha256"],
   "review":"PENDING","images_generated":0}
def main():
 parser=argparse.ArgumentParser()
 parser.add_argument("--apply-authorized-revision",action="store_true")
 args=parser.parse_args()
 try:
  print(json.dumps(run(args.apply_authorized_revision),ensure_ascii=False))
  return 0
 except Exception as e:
  print("A15_PROMOTION_BLOCKED:"+str(e));return 22
if __name__=="__main__":raise SystemExit(main())
