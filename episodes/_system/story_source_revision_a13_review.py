#!/usr/bin/env python3
"""One-shot A13 Critic for explicitly authorized new serial episode source bytes.

Never replay A12, edit locked source, invent review PASS, or bypass the Driver.
Requires historical A12 FAIL still in MySQL and immutable A13 source-promotion
authority. A paid timeout/unknown irreversibly consumes the fresh A13 ticket.
"""
from __future__ import annotations
import argparse,hashlib,json,os
from pathlib import Path
import story_narrative_form

ATTEMPT=13
REVIEW_EPOCH=12
REVIEW_SCOPE="SERIAL_EPISODE_AUTHORIZED_SOURCE_REVISION_AFTER_A12_FAIL"
EPOCH_REL="meta/runtime/story-review-serial-source-revision-a13.json"
CANDIDATE_REL="meta/.story-semantic-review-a13.candidate.json"
AUDIT_REL="meta/runtime/story-source-revision-a13/authority.json"
PROMOTED_REL="meta/runtime/story-source-revision-a13/promoted.json"
FRAME_COUNT=48
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def source_sha(ep):
 import story_review as sr
 story,board=sr.story_paths(ep);captions=ep/"docs/subtitles.yaml"
 if any(not p.is_file() or p.is_symlink() for p in (story,board,captions)):
  raise ValueError("A13_SOURCE_MISSING_OR_SYMLINK")
 return {"story_sha256":sha(story),"storyboard_sha256":sha(board),"subtitle_source_sha256":sha(captions)}
def _rubric():
 import story_review as sr
 return sr._review_rubric_digest(Path(sr.__file__).read_text("utf-8-sig"))
def plan(ep):
 import story_review as sr
 import story_serial_recheck as a12
 import runtime_request
 import review_record_persistence as records
 import runtime_driver
 ep=Path(ep).resolve()
 base={"status":"A13_REVIEW_NOT_ADMITTED","can_dispatch_model":False,"can_dispatch_image":False,
       "model_calls":0,"sql_writes":0,"read_only":True}
 try:
  if not ep.is_relative_to(sr.ROOT.resolve()):return {**base,"status":"A13_OUT_OF_REPOSITORY"}
  request=runtime_request.authority_for_episode(ep)
  if not story_narrative_form.is_locked(request) or story_narrative_form.from_request(request)!="SERIAL_EPISODE":
   return {**base,"status":"A13_NOT_LOCKED_SERIAL_STORY"}
  if (ep/EPOCH_REL).exists() or (ep/CANDIDATE_REL).exists():
   return {**base,"status":"A13_ALREADY_RESERVED_NO_RETRY"}
  if not (ep/AUDIT_REL).is_file() or not (ep/PROMOTED_REL).is_file():
   return {**base,"status":"A13_SOURCE_PROMOTION_AUTHORITY_MISSING"}
  authority=sr.read_json(ep/AUDIT_REL)
  promoted=sr.read_json(ep/PROMOTED_REL)
  if promoted.get("status")!="AUTHENTIC_SOURCE_REVISION_PROMOTED_REVIEW_PENDING":
   return {**base,"status":"A13_SOURCE_REVISION_NOT_PROMOTED"}
  if not all(promoted.get(k)==v for k,v in authority.items()):
   return {**base,"status":"A13_APPROVAL_PROMOTION_DRIFT"}
  if (authority.get("schema")!="storyos.authorized_source_revision_a13.v1"
   or authority.get("authorization")!="user_explicitly_approved_limited_48_frame_story_edit_on_2026-10-20"
   or authority.get("previous_review_attempt")!=12):
   return {**base,"status":"A13_USER_APPROVAL_UNVERIFIED"}
  old=sr.load_review(ep)
  if (not isinstance(old,dict) or (old.get("summary") or {}).get("passed") is not False
      or (old.get("critic_provenance") or {}).get("attempt")!=12
      or (old.get("critic_provenance") or {}).get("review_scope")!=a12.REVIEW_SCOPE):
   return {**base,"status":"A13_PREVIOUS_A12_FAIL_NOT_LATEST"}
  old_digest=records._payload_content_sha(old)
  if old_digest!=authority.get("previous_failed_review_sha256") or not a12._previous_exists(ep,old_digest):
   return {**base,"status":"A13_A12_IMMUTABLE_FAILED_REVIEW_MISSING"}
  field_map={"story_sha256":("source_story_sha256","candidate_story_sha256","story.md"),
             "storyboard_sha256":("source_storyboard_sha256","candidate_storyboard_sha256","storyboard.md"),
             "subtitle_source_sha256":("source_subtitle_sha256","candidate_subtitle_sha256","subtitles.yaml")}
  latest=source_sha(ep)
  backup=ep/"meta/runtime/story-source-revision-a13/baseline/docs"
  for k,(old_key,new_key,name) in field_map.items():
   if (old.get(k)!=authority.get(old_key) or sha(backup/name)!=authority.get(old_key)
       or latest[k]!=authority.get(new_key) or latest[k]==old.get(k)):
    return {**base,"status":"A13_SOURCE_OR_BACKUP_SHA_DRIFT"}
  original=next((ep/"docs/source").glob("*.txt"))
  if sha(original)!=authority.get("source_original_sha256"):
   return {**base,"status":"A13_ORIGINAL_USER_TEXT_DRIFT"}
  import re
  text_story=(ep/"docs/story.md").read_text("utf-8-sig")
  text_board=(ep/"docs/storyboard.md").read_text("utf-8-sig")
  if (len(re.findall(r"(?m)^### \d{2} \u5e27$",text_story))!=FRAME_COUNT
   or len(re.findall(r"(?m)^### Frame \d{2}$",text_board))!=FRAME_COUNT
   or len(re.findall(r"(?m)^\| \d{2} \|",text_board))!=FRAME_COUNT):
   return {**base,"status":"A13_FORTY_EIGHT_FRAME_CONTRACT_DRIFT"}
  owner=runtime_driver.status(ep)
  if owner.get("driver_state") in {"RUNNING","ALIVE_NOT_BEATING","UNKNOWN"}:
   return {**base,"status":"A13_DRIVER_OWNER_UNVERIFIED"}
  return {**base,"status":"A13_ONE_SHOT_SOURCE_CRITIC_READY",
          "can_dispatch_model":True,"attempt":ATTEMPT,**latest,
          "previous_review_sha256":old_digest,
          "source_approval_sha256":sha(ep/AUDIT_REL),
          "current_rubric_sha256":_rubric(),
          "current_standard_sha256":sha(sr.ROOT/"standards"/"\u5236\u4f5c\u89c4\u8303_\u6b63\u5f0f\u7248.md")}
 except Exception:
  return {**base,"status":"A13_EVIDENCE_READ_ERROR"}
def authorize(ep,expected_previous_sha):
 import story_review as sr
 ep=Path(ep).resolve()
 if not (sr.ROOT/".git").is_dir() or (sr.ROOT/".git").is_symlink():
  raise RuntimeError("A13_REQUIRES_CANONICAL_PRIMARY_CHECKOUT")
 readiness=plan(ep)
 if readiness["status"]!="A13_ONE_SHOT_SOURCE_CRITIC_READY":
  raise RuntimeError("A13_NOT_READY:"+readiness["status"])
 if expected_previous_sha!=readiness["previous_review_sha256"]:
  raise RuntimeError("A13_A12_PREVIOUS_SHA_MISMATCH")
 keys=("story_sha256","storyboard_sha256","subtitle_source_sha256",
       "previous_review_sha256","source_approval_sha256","current_rubric_sha256","current_standard_sha256")
 ticket={"schema":"storyos.source_revision_review_a13.v1",
         "authorization":"explicit_user_source_revision_one_shot",
         "review_scope":REVIEW_SCOPE,"global_review_attempt":ATTEMPT,
         "review_epoch":REVIEW_EPOCH,"epoch_attempt":1,
         **{k:readiness[k] for k in keys}}
 p=ep/EPOCH_REL;p.parent.mkdir(parents=True,exist_ok=True)
 with p.open("x",encoding="utf-8") as f:
  json.dump(ticket,f,ensure_ascii=False,sort_keys=True,indent=2)
  f.write("\n");f.flush();os.fsync(f.fileno())
 return ticket
def validate_epoch(ep,provenance):
 import story_review as sr
 import story_serial_recheck as a12
 import review_record_persistence as records
 ep=Path(ep).resolve()
 try:
  ticket=sr.read_json(ep/EPOCH_REL)
  approval=sr.read_json(ep/AUDIT_REL)
  old_key=approval.get("previous_failed_review_sha256")
  if (ticket.get("authorization")!="explicit_user_source_revision_one_shot"
   or ticket.get("review_scope")!=REVIEW_SCOPE
   or ticket.get("global_review_attempt")!=ATTEMPT
   or ticket.get("review_epoch")!=REVIEW_EPOCH
   or ticket.get("epoch_attempt")!=1
   or provenance.get("attempt")!=ATTEMPT
   or provenance.get("direct_user_continuation_review") is not True
   or provenance.get("review_scope")!=REVIEW_SCOPE):
   return False
  for k in ("review_epoch","epoch_attempt","previous_review_sha256","source_approval_sha256",
             "current_rubric_sha256","subtitle_source_sha256"):
   if ticket.get(k)!=provenance.get(k):return False
  if ticket.get("previous_review_sha256")!=old_key or not a12._previous_exists(ep,old_key):
   return False
  if sha(ep/AUDIT_REL)!=ticket.get("source_approval_sha256"):
   return False
  if any(ticket.get(k)!=v for k,v in source_sha(ep).items()):
   return False
  if ticket["current_rubric_sha256"]!=_rubric():return False
  if ticket["current_standard_sha256"]!=sha(sr.ROOT/"standards"/"\u5236\u4f5c\u89c4\u8303_\u6b63\u5f0f\u7248.md"):
   return False
  return True
 except Exception:return False
def run(ep,expected_previous_sha,codex_raw,timeout):
 import story_review as sr
 import codex_critic_runner as runner
 import runtime_provenance
 import runtime_timeout_policy
 ep=Path(ep).resolve()
 codex=sr.resolve_codex(codex_raw)
 check=plan(ep)
 if check["status"]!="A13_ONE_SHOT_SOURCE_CRITIC_READY":raise RuntimeError(check["status"])
 story,board=sr.story_paths(ep)
 candidate=ep/CANDIDATE_REL
 prompt=sr.critic_prompt(ep,story,board,candidate,ATTEMPT)
 if "SERIAL EPISODE HARD RULES" not in prompt:raise RuntimeError("A13_WRONG_STORY_RUBRIC")
 resolved_timeout=runtime_timeout_policy.resolve("serial_source_revision_review",timeout)
 token=authorize(ep,expected_previous_sha)
 log=ep/"meta/story-critic-attempt-13.jsonl"
 # From this point onward UNKNOWN, crash, timeout or FAIL are terminal for A13.
 result=runner.launch(prompt+sr.DIRECT_CODEX_EXECUTION_OVERRIDE,codex=codex,
  root=sr.ROOT,timeout=resolved_timeout,output_path=candidate,reasoning_effort="high",
  sandbox="read-only",log_path=log,codex_home_mode="isolated")
 if result.returncode!=0:raise RuntimeError("A13_MODEL_RESULT_UNKNOWN_NO_REPLAY")
 if not candidate.is_file() or any(token.get(k)!=v for k,v in source_sha(ep).items()):
  raise RuntimeError("A13_SOURCE_OR_RESULT_DRIFT_NO_REPLAY")
 data=sr.read_json(candidate)
 prov=runtime_provenance.build_critic_provenance(
  "CODEX",attempt=ATTEMPT,log=log.relative_to(sr.ROOT).as_posix(),
  allow_user_continuation_attempt=True)
 prov.update({"review_scope":REVIEW_SCOPE,"review_epoch":REVIEW_EPOCH,"epoch_attempt":1,
  "previous_review_sha256":token["previous_review_sha256"],
  "source_approval_sha256":token["source_approval_sha256"],
  "current_rubric_sha256":token["current_rubric_sha256"],
  "subtitle_source_sha256":token["subtitle_source_sha256"]})
 rc=sr._finalize_review(ep,data,attempt=ATTEMPT,before_story=token["story_sha256"],
                       before_board=token["storyboard_sha256"],provenance=prov)
 if rc!=0:return rc
 if sr.verify(ep):return 2
 sr.project_verified_story_gate(ep)
 gates=ep/"meta/story-gates.json";current=sr.read_json(gates)
 if (current.get("reviews") or {}).get("story")!="passed" or not validate_epoch(ep,prov):
  return 2
 current.setdefault("story",{})["task_closed"]=True
 sr.write_json(gates,current)
 return 0
def main():
 ap=argparse.ArgumentParser()
 sub=ap.add_subparsers(dest="command",required=True)
 p=sub.add_parser("plan");p.add_argument("episode")
 p=sub.add_parser("run");p.add_argument("episode")
 p.add_argument("--ack-one-shot-source-revision-review",action="store_true",required=True)
 p.add_argument("--expected-previous-review-sha",required=True)
 p.add_argument("--codex")
 p.add_argument("--timeout",type=int,default=None)
 args=ap.parse_args()
 ep=Path(args.episode).resolve()
 if args.command=="plan":
  print(json.dumps(plan(ep),ensure_ascii=False));return 0
 try:return run(ep,args.expected_previous_review_sha,args.codex,args.timeout)
 except (OSError,ValueError,RuntimeError) as exc:
  print("A13_SOURCE_REVISION_REVIEW_STOP:",type(exc).__name__,str(exc));return 22
if __name__=="__main__":raise SystemExit(main())
