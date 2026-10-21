from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"episodes"/"_system"))
import story_review as sr
import story_source_revision_a14_review as a14
import story_source_revision_a13_review as a13
import story_narrative_form
import runtime_request
import runtime_driver
import codex_critic_runner
from review_record_persistence import _payload_content_sha


def _setup(tmp_path,monkeypatch):
 (tmp_path/".git").mkdir()
 st=tmp_path/"standards"/"\u5236\u4f5c\u89c4\u8303_\u6b63\u5f0f\u7248.md"
 st.parent.mkdir()
 st.write_text("serial source authority",encoding="utf-8")
 ep=tmp_path/"episodes"/"01_serial"
 docs=ep/"docs"
 docs.mkdir(parents=True)
 (docs/"source").mkdir()
 source=docs/"source"/"locked_original.txt"
 source.write_text("user original immutable bytes",encoding="utf-8")
 names=("story.md","storyboard.md","subtitles.yaml")
 baseline={}
 current={}
 original={}
 for name in names:
  if name=="story.md":
   original[name]="".join(f"### {i:02d} \u5e27\nStory {i}\n" for i in range(1,49))
   current[name]=original[name].replace("Story 29","Authorized POV 29")
  elif name=="storyboard.md":
   rows="".join(f"| {i:02d} | Visual {i} | Camera |\n" for i in range(1,49))
   base=rows+"".join(f"### Frame {i:02d}\nDetailed {i}\n" for i in range(1,49))
   original[name]=base
   current[name]=base.replace("Detailed 41","Correct left lapel 41")
  else:
   original[name]="".join(f"{i:02d}: \u5b57\u5e55 {i}\n" for i in range(1,49))
   current[name]=original[name]
  (docs/name).write_text(current[name],encoding="utf-8")
  baseline[name]=hashlib.sha256(original[name].encode("utf-8")).hexdigest()
 new={n:a14.sha(docs/n) for n in names}
 prior={"summary":{"passed":False},
  "critic_provenance":{"attempt":13,"review_scope":a13.REVIEW_SCOPE},
  "story_sha256":baseline["story.md"],
  "storyboard_sha256":baseline["storyboard.md"],
  "subtitle_source_sha256":baseline["subtitles.yaml"],
  "issue_codes":["UNSUPPORTED_POV_FLASHBACK","STORYBOARD_VISUAL_CONTRACT_CONFLICT"]}
 prior_digest=_payload_content_sha(prior)
 r=ep/"meta/runtime/story-source-revision-a14"
 backup=r/"baseline/docs"
 backup.mkdir(parents=True)
 for n in names:(backup/n).write_bytes(original[n].encode("utf-8"))
 a13auth=ep/"meta/runtime/story-source-revision-a13/authority.json"
 a13auth.parent.mkdir(parents=True)
 a13auth.write_text('{"older":"immutable"}',encoding="utf-8")
 proof={
  "schema":"storyos.authorized_source_revision_a14.v1",
  "authorization":"user_approved_a14_minimal_pov_and_lapel_correction",
  "previous_review_attempt":13,"previous_review_scope":a13.REVIEW_SCOPE,
  "previous_failed_review_sha256":prior_digest,
  "previous_source_approval_sha256":a14.sha(a13auth),
  "source_original_sha256":a14.sha(source),
  "source_story_sha256":baseline["story.md"],
  "source_storyboard_sha256":baseline["storyboard.md"],
  "source_subtitle_sha256":baseline["subtitles.yaml"],
  "candidate_story_sha256":new["story.md"],
  "candidate_storyboard_sha256":new["storyboard.md"],
  "candidate_subtitle_sha256":new["subtitles.yaml"],
  "changed_frames":[29,30,41]}
 (r/"authority.json").write_text(json.dumps(proof),encoding="utf-8")
 (r/"promoted.json").write_text(json.dumps({
  "status":"AUTHENTIC_SOURCE_REVISION_PROMOTED_REVIEW_PENDING",**proof}),encoding="utf-8")
 monkeypatch.setattr(sr,"ROOT",tmp_path)
 monkeypatch.setattr(sr,"story_paths",lambda _ep:(docs/"story.md",docs/"storyboard.md"))
 monkeypatch.setattr(sr,"load_review",lambda _ep:prior)
 monkeypatch.setattr(runtime_request,"authority_for_episode",lambda _ep:{
  "narrative_form":"SERIAL_EPISODE",
  "topic":{"title":"\u7b2c\u4e00\u96c6"},
  "story_input":{"mode":"locked_story","allow_structure_rewrite":False}})
 monkeypatch.setattr(runtime_driver,"status",lambda _ep:{"driver_state":"EXITED"})
 monkeypatch.setattr(a14,"historical_a13_fail_exists",lambda _ep,_sha:True)
 return ep,prior,proof


def test_approved_a14_can_be_reserved_once(tmp_path,monkeypatch):
 ep,prior,_=_setup(tmp_path,monkeypatch)
 plan=a14.plan(ep)
 assert plan["status"]=="A14_ONE_SHOT_SOURCE_CRITIC_READY",plan
 assert plan["can_dispatch_image"] is False
 with pytest.raises(RuntimeError,match="MISMATCH"):
  a14.authorize(ep,"0"*64)
 ticket=a14.authorize(ep,plan["previous_review_sha256"])
 assert ticket["global_review_attempt"]==14
 assert ticket["review_epoch"]==13
 provenance={
  "attempt":14,"review_scope":a14.REVIEW_SCOPE,
  "direct_user_continuation_review":True,
  "review_epoch":13,"epoch_attempt":1}
 for key in ("previous_review_sha256","source_approval_sha256",
             "current_rubric_sha256","subtitle_source_sha256"):
  provenance[key]=ticket[key]
 assert a14.validate_epoch(ep,provenance)
 assert a14.plan(ep)["status"]=="A14_ALREADY_RESERVED_NO_RETRY"
 with pytest.raises(RuntimeError,match="NO_RETRY"):
  a14.authorize(ep,plan["previous_review_sha256"])
 assert prior["summary"]["passed"] is False


def test_a14_source_drift_prevents_model_admission(tmp_path,monkeypatch):
 ep,_,_= _setup(tmp_path,monkeypatch)
 (ep/"docs/storyboard.md").write_text("unauthorized storyboard rewrite")
 assert a14.plan(ep)["status"]=="A14_SOURCE_OR_BACKUP_SHA_DRIFT"


def test_timeout_consumes_one_shot_authority(tmp_path,monkeypatch):
 ep,_,_=_setup(tmp_path,monkeypatch)
 ready=a14.plan(ep)
 monkeypatch.setattr(sr,"resolve_codex",lambda _raw:Path("codex"))
 monkeypatch.setattr(sr,"critic_prompt",lambda *_args:"SERIAL EPISODE HARD RULES")
 calls=[]
 def fake_launch(*_args,**_kwargs):
  calls.append(1)
  return SimpleNamespace(returncode=124)
 monkeypatch.setattr(codex_critic_runner,"launch",fake_launch)
 with pytest.raises(RuntimeError,match="UNKNOWN_NO_REPLAY"):
  a14.run(ep,ready["previous_review_sha256"],None,5)
 assert len(calls)==1
 with pytest.raises(RuntimeError,match="A14_ALREADY_RESERVED_NO_RETRY"):
  a14.run(ep,ready["previous_review_sha256"],None,5)
 assert len(calls)==1


def test_previous_a13_failed_digest_must_remain_valid(tmp_path,monkeypatch):
 ep,_,_=_setup(tmp_path,monkeypatch)
 monkeypatch.setattr(a14,"historical_a13_fail_exists",lambda _ep,_sha:False)
 assert a14.plan(ep)["status"]=="A14_A13_IMMUTABLE_FAILED_REVIEW_MISSING"
