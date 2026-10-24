"""F001 old-pixel baseline reevaluation without image-generation or canonical mutation."""
from __future__ import annotations
import argparse
import hashlib
import json
import shutil
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
import character_visual_contract as character
import codex_critic_runner as critic
import codex_user_runner
import episode_state_persistence as stages
import generation_attempt_authority as ga
import logical_asset_identity as identity
import runtime_driver
import runtime_router
import runtime_timeout_policy
import scheduler_core
import runtime_provenance
import visual_lock_baseline_gate as baseline

ROOT=Path(__file__).resolve().parents[2]
REL=Path("episodes/00_独立篇/14_深渊疗愈所_第一集_净土生命还原")
EVIDENCE=Path("meta/runtime/independent-baseline-rereviews")
class ReviewOnlyDenied(RuntimeError):pass
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def deny(s):raise ReviewOnlyDenied(s)

def quota_recovery_prefix(prefix: Path, *, oldsha: str, image_sha: str,
                          contract_sha: str, promptsha: str, now=None) -> tuple[Path,str]:
    """Exactly one fresh review after a real logged Codex usage-limit error.

    Previous terminal technical evidence is immutable and input SHA-bound.
    Other failures, finished content verdicts and pre-reset attempts are not
    eligible for this narrow exception. It never authorizes image generation.
    """
    report=prefix.with_suffix(".json")
    log=prefix.with_suffix(".log.jsonl")
    if not report.is_file() or not log.is_file() or report.is_symlink() or log.is_symlink():
        deny("PRIOR_QUOTA_FAILURE_EVIDENCE_MISSING")
    previous=json.loads(report.read_text(encoding="utf-8"))
    provenance=previous.get("critic_provenance") or {}
    if (previous.get("status")!="TECHNICAL_FAILURE"
        or previous.get("critic_returncode")!=1
        or previous.get("reply") not in ({},None)
        or previous.get("prior_review_sha256")!=oldsha
        or previous.get("image_sha256")!=image_sha
        or previous.get("frame_contract_sha256")!=contract_sha
        or previous.get("prompt_sha256")!=promptsha
        or previous.get("image_generation_calls")!=0
        or previous.get("image_attempts_reserved")!=0
        or provenance.get("log_sha256")!=sha(log)):
        deny("PRIOR_FAILURE_NOT_EXACT_QUOTA_SOURCE")
    text=log.read_text(encoding="utf-8-sig",errors="replace")
    match=re.search(r"try again at (\d{1,2}:\d{2})\s*(AM|PM)",text,re.I)
    if ("usage limit" not in text.lower() or "turn.failed" not in text
        or "turn.completed" in text or not match):
        deny("PRIOR_FAILURE_NOT_USAGE_LIMIT")
    reviewed=datetime.fromisoformat(str(provenance.get("reviewed_at") or ""))
    if reviewed.tzinfo is None:deny("QUOTA_REVIEW_TIMESTAMP_NO_TIMEZONE")
    hour,minute=map(int,match.group(1).split(":"))
    hour=hour%12+(12 if match.group(2).upper()=="PM" else 0)
    reset=reviewed.replace(hour=hour,minute=minute,second=0,microsecond=0)
    if reset<=reviewed:reset+=timedelta(days=1)
    current=now if now is not None else datetime.now(reviewed.tzinfo)
    if current<reset:
        deny("CODEX_USAGE_LIMIT_NOT_RESET:"+reset.isoformat())
    reference=sha(report)
    newkey=hashlib.sha256(
        (prefix.name+reference+"one-bounded-quota-vision-retry").encode()
    ).hexdigest()[:20]
    nextprefix=prefix.parent/("f001-quota-"+newkey)
    if any(nextprefix.with_suffix(x).exists() for x in
           (".json",".log.jsonl",".candidate.json")):
        deny("QUOTA_REVIEW_ALREADY_RETRIED")
    return nextprefix,reference


def inspect(ep,*,quota_retry=False):
    ep=Path(ep).resolve()
    if ep!=(ROOT/REL).resolve():deny("WRONG_EPISODE")
    driver=runtime_driver.status(ep)
    if (driver.get("driver_state")!="EXITED" or str(driver.get("exit_code"))!="22"
            or driver.get("liveness")!="DEAD" or driver.get("pid")!=0):
        deny("DRIVER_NOT_STOPPED_RC22")
    stage,authority=stages.load_with_source(ep)
    if authority!="mysql" or (stage or {}).get("current_state")!="STORYBOARD_LOCKED":
        deny("MYSQL_STAGE_CHANGED")
    queue=scheduler_core.load_queue(ep)
    originals=[x for x in queue.get("items") or []
         if x.get("scope")=="visual_lock" and x.get("frame")==1 and x.get("kind")=="original"]
    if len(originals)!=1 or originals[0].get("status")!="generated" or originals[0].get("id")!="ead88592f160":
        deny("BASELINE_QUEUE_CHANGED")
    if any(x.get("frame")==1 and x.get("kind")=="repair"
           and x.get("status") in {"running","queued","interrupted_unknown"}
           for x in queue.get("items") or []):
        deny("REPAIR_STILL_ACTIVE")
    key=identity.frame_asset_key(ep,1)
    st=ga.load_asset_state(ep,key)
    a2=ga.load_attempt(ep,key,2) or {}
    if (st.get("attempts_consumed")!=2 or st.get("remaining_attempts")!=0
        or st.get("active_attempt_index") is not None or ga.load_attempt(ep,key,3)
        or a2.get("status")!="SUCCEEDED"):deny("GENERATION_ATTEMPT_BUDGET_CHANGED")
    if baseline.approved(ep):deny("BASELINE_ALREADY_APPROVED")
    image=baseline.generated_baseline(ep)
    asset=baseline.repo_file(image["asset_path"])
    old=ep/baseline.REL
    if not old.is_file() or old.is_symlink():deny("PRIOR_REVIEW_MISSING")
    review=json.loads(old.read_text(encoding="utf-8"))
    if (review.get("decision")!="FAIL"
            or any(review.get(k)!=image.get(k) for k in
              ("frame","asset_path","sha256","frame_contract_sha256","queue_item_id"))):
        deny("PRIOR_FAIL_SOURCE_MISMATCH")
    if sha(asset)!=image["sha256"]:deny("CANDIDATE_PIXEL_CHANGED")
    if image["frame_contract_sha256"]!=baseline.baseline_review_obligations(ep)["frame_contract_sha256"]:
        deny("CONTRACT_CHANGED")
    prov=review.get("critic_provenance") or {}
    oldlog=ROOT/str(prov.get("log") or "")
    if (not oldlog.is_file() or oldlog.is_symlink()
        or sha(oldlog)!=prov.get("log_sha256")
        or runtime_provenance.validate_critic_provenance(prov)):
        deny("PRIOR_REVIEW_PROVENANCE_UNVERIFIED")
    prompt=baseline.codex_critic_prompt(ep)
    canonical_output=baseline.repo_rel(ep/baseline.CANDIDATE_REL)
    prompt=prompt.replace(canonical_output,
        "the independent review-only CLI output (never the canonical candidate)")
    oldsha=sha(old)
    promptsha=hashlib.sha256(prompt.encode()).hexdigest()
    keyhash=hashlib.sha256((oldsha+image["sha256"]+promptsha).encode()).hexdigest()[:20]
    prefix=ep/EVIDENCE/("f001-"+keyhash)
    artifacts=[prefix.with_suffix(s) for s in (".json",".candidate.json",".log.jsonl")]
    prior_quota_sha=None
    if any(p.exists() for p in artifacts):
        if not quota_retry:deny("SAME_SOURCE_REVIEW_ALREADY_ATTEMPTED")
        prefix,prior_quota_sha=quota_recovery_prefix(
            prefix,oldsha=oldsha,image_sha=image["sha256"],
            contract_sha=image["frame_contract_sha256"],promptsha=promptsha)
    elif quota_retry:deny("NO_QUOTA_LIMITED_REVIEW_TO_RETRY")
    return {"status":"REVIEW_ONLY_READY","ep":ep,"asset":asset,"old":old,
        "quota_recovery_from_sha256":prior_quota_sha,
        "oldlog":oldlog,"old_sha":oldsha,"oldlog_sha":sha(oldlog),
        "image_sha":image["sha256"],"contract_sha":image["frame_contract_sha256"],
        "prompt":prompt,"prompt_sha":promptsha,"prefix":prefix,
        "image_generation_calls":0,"image_attempts_reserved":0}

def verify_unchanged(src):
    if (sha(src["old"])!=src["old_sha"] or sha(src["oldlog"])!=src["oldlog_sha"]
            or sha(src["asset"])!=src["image_sha"]):
        deny("SOURCE_MUTATED_WHILE_REVIEWING")
    d=runtime_driver.status(src["ep"])
    if d.get("driver_state")!="EXITED" or str(d.get("exit_code"))!="22":
        deny("DRIVER_STARTED_WHILE_REVIEWING")
    key=identity.frame_asset_key(src["ep"],1)
    st=ga.load_asset_state(src["ep"],key)
    if (st.get("attempts_consumed")!=2 or st.get("active_attempt_index") is not None
            or ga.load_attempt(src["ep"],key,3)):
        deny("PAID_ATTEMPT_CHANGED_WHILE_REVIEWING")

def verdict(reply):
    if not isinstance(reply,dict) or reply.get("pixel_evidence_available") is not True:
        return "TECHNICAL_FAILURE"
    checks=reply.get("checks")
    if (reply.get("decision") not in {"PASS","FAIL"}
        or not isinstance(checks,dict) or set(checks)!=set(baseline.CHECKS)
        or any(v not in {"PASS","FAIL"} for v in checks.values())):
        return "TECHNICAL_FAILURE"
    if not isinstance(reply.get("face_boxes"),list):return "TECHNICAL_FAILURE"
    if (reply["decision"]=="PASS" and all(v=="PASS" for v in checks.values())):
        return "REVIEW_ONLY_PASS"
    return "REVIEW_ONLY_FAIL"

def review_only(ep,ack,*,quota_retry=False):
    if not ack:deny("EXPLICIT_NO_IMAGE_REVIEW_ACK_REQUIRED")
    source=inspect(ep,quota_retry=quota_retry)
    prefix=source["prefix"]
    prefix.parent.mkdir(parents=True,exist_ok=True)
    output=prefix.with_suffix(".candidate.json")
    log=prefix.with_suffix(".log.jsonl")
    report=prefix.with_suffix(".json")
    temporary=codex_user_runner.workspace_path(prefix="storyos-f001-vision-only-")
    attached=temporary/("baseline"+source["asset"].suffix)
    shutil.copy2(source["asset"],attached)
    if sha(attached)!=source["image_sha"]:deny("VISION_INPUT_MISMATCH")
    try:
        done=critic.launch(source["prompt"],codex=critic.resolve_codex(None),
            root=ROOT,timeout=runtime_timeout_policy.seconds("visual_baseline_critic"),
            output_path=output,attachments=[attached],
            model=runtime_router.vision_review_model(),
            reasoning_effort=runtime_router.vision_review_effort("final"),
            sandbox=critic.default_sandbox(),log_path=log)
    finally:
        shutil.rmtree(temporary,ignore_errors=True)
    verify_unchanged(source)
    reply={}
    if done.returncode==0 and output.is_file():
        try: reply=json.loads(output.read_text(encoding="utf-8-sig"))
        except (OSError,ValueError): pass
    result=verdict(reply) if done.returncode==0 else "TECHNICAL_FAILURE"
    prov=runtime_provenance.build_vision_critic_provenance(
        attempt=2,log=baseline.repo_rel(log),
        review_scope="VISUAL_LOCK_BASELINE_REVIEW_ONLY")
    prov["log_sha256"]=sha(log)
    record={"schema_version":1,"status":result,
        "review_only":True,"canonical_pass_authorized":False,
        "prior_decision":"FAIL","prior_review_sha256":source["old_sha"],
        "quota_recovery_from_sha256":source["quota_recovery_from_sha256"],
        "prior_critic_log_sha256":source["oldlog_sha"],
        "frame":1,"frame_contract_sha256":source["contract_sha"],
        "image_sha256":source["image_sha"],"prompt_sha256":source["prompt_sha"],
        "critic_provenance":prov,"critic_returncode":done.returncode,
        "reply":reply,"image_generation_calls":0,"image_attempts_reserved":0}
    with report.open("x",encoding="utf-8") as f:
        json.dump(record,f,ensure_ascii=False,sort_keys=True,indent=2);f.write("\n")
    return {"status":result,"review_only":True,"artifact":baseline.repo_rel(report),
        "image_generation_calls":0,"image_attempts_reserved":0}

def main(argv=None):
    ap=argparse.ArgumentParser()
    ap.add_argument("--episode",required=True)
    ap.add_argument("--run",action="store_true")
    ap.add_argument("--retry-after-usage-limit",action="store_true")
    ap.add_argument("--ack-review-only-no-image-generation",action="store_true")
    a=ap.parse_args(argv)
    try:
        ep=Path(a.episode).resolve()
        r=review_only(ep,a.ack_review_only_no_image_generation,quota_retry=a.retry_after_usage_limit) if a.run else inspect(ep,quota_retry=a.retry_after_usage_limit)
        if not a.run:
            r={k:r[k] for k in ("status","old_sha","image_sha","contract_sha","prompt_sha",
              "image_generation_calls","image_attempts_reserved")}
    except Exception as exc:
        r={"status":"BLOCKED","exception":type(exc).__name__,"reason":str(exc)}
    print(json.dumps(r,ensure_ascii=False,sort_keys=True))
    return 0 if r["status"] in {"REVIEW_ONLY_READY","REVIEW_ONLY_PASS","REVIEW_ONLY_FAIL"} else 2
if __name__=="__main__":raise SystemExit(main())
