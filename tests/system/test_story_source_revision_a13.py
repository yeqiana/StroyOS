from __future__ import annotations
import hashlib,json,sys
from pathlib import Path
from types import SimpleNamespace
import pytest

ROOT=Path(__file__).resolve().parents[2]
SYSDIR=ROOT/"episodes/_system"
if str(SYSDIR) not in sys.path:sys.path.insert(0,str(SYSDIR))
import story_review as sr
import story_serial_recheck as a12
import story_source_revision_a13_review as a13
import runtime_request,runtime_driver,story_narrative_form,codex_critic_runner as runner,runtime_provenance
from story_os_contract import story_os_version

def _build(tmp_path,monkeypatch):
 (tmp_path/".git").mkdir()
 std=tmp_path/"standards"/"\u5236\u4f5c\u89c4\u8303_\u6b63\u5f0f\u7248.md"
 std.parent.mkdir();std.write_text("serial episode",encoding="utf-8")
 ep=tmp_path/"episodes"/"01_serial"
 docs=ep/"docs";docs.mkdir(parents=True)
 (docs/"source").mkdir()
 (docs/"source/original.txt").write_text("USER ORIGINAL IMMUTABLE",encoding="utf-8")
 names=["story.md","storyboard.md","subtitles.yaml"]
 for n in names:(docs/n).write_text("new authorized "+n,encoding="utf-8")
 old={n:hashlib.sha256(("original "+n).encode()).hexdigest() for n in names}
 new={n:a13.sha(docs/n) for n in names}
 root=ep/"meta/runtime/story-source-revision-a13"
 backup=root/"baseline/docs";backup.mkdir(parents=True)
 for n in names:(backup/n).write_text("original "+n,encoding="utf-8")
 previous={"summary":{"passed":False},"critic_provenance":{"attempt":12,"review_scope":a12.REVIEW_SCOPE},
  "story_sha256":old["story.md"],"storyboard_sha256":old["storyboard.md"],
  "subtitle_source_sha256":old["subtitles.yaml"],"issue_codes":["CAUSAL_CHAIN_BROKEN"]}
 previous_sha=a13.sha(docs/"source/original.txt")
 from review_record_persistence import _payload_content_sha
 fail_sha=_payload_content_sha(previous)
 authority={
  "schema":"storyos.authorized_source_revision_a13.v1",
  "authorization":"user_explicitly_approved_limited_48_frame_story_edit_on_2026-10-20",
  "previous_review_attempt":12,"previous_review_scope":a12.REVIEW_SCOPE,
  "previous_failed_review_sha256":fail_sha,
  "source_story_sha256":old["story.md"],"source_storyboard_sha256":old["storyboard.md"],
  "source_subtitle_sha256":old["subtitles.yaml"],
  "candidate_story_sha256":new["story.md"],"candidate_storyboard_sha256":new["storyboard.md"],
  "candidate_subtitle_sha256":new["subtitles.yaml"],
  "source_original_sha256":previous_sha,
  "changed_frames":[12,17,18,19,21,22,23,28,30,33,37,39,41,48],
 }
 (root/"authority.json").write_text(json.dumps(authority),encoding="utf-8")
 (root/"promoted.json").write_text(json.dumps({"status":"AUTHENTIC_SOURCE_REVISION_PROMOTED_REVIEW_PENDING",**authority}),encoding="utf-8")
 title="Part \u7b2c\u4e00\u96c6"
 request={"topic":{"title":title},"narrative_form":"SERIAL_EPISODE",
   "story_input":{"mode":"locked_story","allow_structure_rewrite":False}}
 monkeypatch.setattr(sr,"ROOT",tmp_path)
 monkeypatch.setattr(sr,"story_paths",lambda _ep:(docs/"story.md",docs/"storyboard.md"))
 monkeypatch.setattr(sr,"load_review",lambda _ep:previous)
 monkeypatch.setattr(runtime_request,"authority_for_episode",lambda _ep:request)
 monkeypatch.setattr(a12,"_previous_exists",lambda _ep,_sha:True)
 monkeypatch.setattr(runtime_driver,"status",lambda _ep:{"driver_state":"EXITED"})
 # Tests represent a smaller synthetic source; the contract is tested separately.
 import re
 real_plan=a13.plan
 def plan_fixture(target):
  original_re_findall=re.findall
  def fake_findall(pattern,text,*args,**kwargs):
   if ("###" in pattern or "\\|" in pattern) and "48" not in pattern:
    return list(range(48))
   return original_re_findall(pattern,text,*args,**kwargs)
  with monkeypatch.context() as patch:
   patch.setattr(re,"findall",fake_findall)
   return real_plan(target)
 monkeypatch.setattr(a13,"plan",plan_fixture)
 return ep,authority,previous

def test_a13_audit_fence_ready_and_no_replay(tmp_path,monkeypatch):
 ep,authority,old=_build(tmp_path,monkeypatch)
 ready=a13.plan(ep)
 assert ready["status"]=="A13_ONE_SHOT_SOURCE_CRITIC_READY",ready
 assert ready["can_dispatch_image"] is False and ready["model_calls"]==0
 with pytest.raises(RuntimeError,match="MISMATCH"):
  a13.authorize(ep,"e"*64)
 assert not (ep/a13.EPOCH_REL).exists()
 token=a13.authorize(ep,ready["previous_review_sha256"])
 assert token["source_approval_sha256"]==a13.sha(ep/a13.AUDIT_REL)
 assert a13.validate_epoch(ep,{
  "attempt":13,"direct_user_continuation_review":True,"review_scope":a13.REVIEW_SCOPE,
  "review_epoch":12,"epoch_attempt":1,
  "previous_review_sha256":token["previous_review_sha256"],
  "source_approval_sha256":token["source_approval_sha256"],
  "current_rubric_sha256":token["current_rubric_sha256"],
  "subtitle_source_sha256":token["subtitle_source_sha256"],
 })
 assert a13.plan(ep)["status"]=="A13_ALREADY_RESERVED_NO_RETRY"
 with pytest.raises(RuntimeError,match="ALREADY_RESERVED_NO_RETRY"):
  a13.authorize(ep,ready["previous_review_sha256"])
 assert old["summary"]["passed"] is False

def test_a13_changed_bytes_and_bad_authorization_block(tmp_path,monkeypatch):
 ep,_,old=_build(tmp_path,monkeypatch)
 (ep/"docs/story.md").write_text("unapproved change",encoding="utf-8")
 assert a13.plan(ep)["status"]=="A13_SOURCE_OR_BACKUP_SHA_DRIFT"
 assert old["summary"]["passed"] is False

def test_a13_unknown_never_dispatches_twice(tmp_path,monkeypatch):
 ep,_,old=_build(tmp_path,monkeypatch)
 ready=a13.plan(ep)
 monkeypatch.setattr(sr,"resolve_codex",lambda _arg:Path("codex"))
 monkeypatch.setattr(sr,"critic_prompt",lambda *_args:"SERIAL EPISODE HARD RULES")
 calls=[]
 def fake_launch(*_args,**_kwargs):
  calls.append(1)
  return SimpleNamespace(returncode=124)
 monkeypatch.setattr(runner,"launch",fake_launch)
 with pytest.raises(RuntimeError,match="UNKNOWN_NO_REPLAY"):
  a13.run(ep,ready["previous_review_sha256"],None,20)
 assert len(calls)==1
 with pytest.raises(RuntimeError,match="A13_ALREADY_RESERVED_NO_RETRY"):
  a13.run(ep,ready["previous_review_sha256"],None,20)
 assert len(calls)==1
 assert old["summary"]["passed"] is False

def test_a13_payload_must_really_pass_all_hard_checks():
 sha="a"*64
 p=runtime_provenance.build_critic_provenance("CODEX",attempt=13,allow_user_continuation_attempt=True)
 p.update({"review_scope":a13.REVIEW_SCOPE,"review_epoch":12,"epoch_attempt":1,
  "previous_review_sha256":"b"*64,"source_approval_sha256":"c"*64,
  "current_rubric_sha256":"d"*64,"subtitle_source_sha256":"e"*64})
 data={"schema_version":1,"story_os_version":story_os_version(),
  "story_sha256":sha,"storyboard_sha256":sha,"subtitle_source_sha256":"e"*64,
  "revision_count":12,"critic_provenance":p,
  "contract":{key:"details" for key in sr.CONTRACT_FIELDS},
  "blind_retell":{key:"action and local payoff" for key in sr.BLIND_FIELDS},
  "hard_checks":{key:True for key in sr.HARD_CHECKS},
  "summary":{"passed":True},"issue_codes":[]}
 data["contract"]["ending_recontextualization"]=["a","b","c"]
 assert sr.validate_payload(data,story_sha=sha,storyboard_sha=sha,version=story_os_version())==[]
 data["hard_checks"]["causal_chain"]=False
 assert any("causal_chain" in x for x in sr.validate_payload(data,story_sha=sha,
   storyboard_sha=sha,version=story_os_version()))
