#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Story OS V2.1 Concept Ambition + Image-first Propagation Gate."""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, os, shutil, subprocess, sys
from pathlib import Path
from story_os_contract import story_os_version
import codex_user_runner  # STORY_OS_V2_7_CODEX_USER_MODE_BRIDGE
import runtime_router
import runtime_provenance
import product_review_adapter
import story_json
import runtime_review_persistence
import runtime_timeout_policy
import episode_state_persistence
import runtime_request

ROOT = Path(__file__).resolve().parents[2]
CANDIDATES_REL = Path("meta/concept-candidates.json")
REVIEW_REL = Path("meta/concept-ambition-review.json")
CANDIDATE_REVIEW_REL = Path("meta/.concept-ambition-review.candidate.json")
MIN_VERSION = (2, 1, 0)
SCORE_LIMITS = {
    "one_line_hook": 20, "hero_frame": 20, "escalation_ceiling": 20,
    "climax_visual_payoff": 15, "mechanism_novelty": 15, "discussion_space": 10,
}
WORDLESS_KEYS = ("stop_scroll", "escalation_readable", "curiosity_gap")
VIRAL_KEYS = ("cover", "mid", "climax")
BANDS = {"A1", "A2", "A3", "A4", "A5"}

def now():
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")

def read_json(path):
    return story_json.read_json(path)

def write_json(path, data):
    story_json.write_json(path, data)

def sha256_file(path):
    import content_fingerprint
    return content_fingerprint.sha256_file(path)

def version_tuple(raw):
    try: return tuple(int(x) for x in str(raw or "").split("."))
    except Exception: return (0,)

def episode_contract_version(ep):
    versions = []
    state = episode_state_persistence.load(Path(ep).resolve()) or {}
    raw = str(state.get("tool_version") or "")
    vt = version_tuple(raw)
    if vt != (0,): versions.append((vt, raw))
    for rel in ("meta/release-manifest.json", "meta/story-gates.json"):
        p = ep / rel
        if not p.is_file(): continue
        try:
            raw = str(read_json(p).get("tool_version") or "")
            vt = version_tuple(raw)
            if vt != (0,): versions.append((vt, raw))
        except Exception: pass
    return max(versions, key=lambda x:x[0])[1] if versions else story_os_version()

def required(ep):
    if version_tuple(episode_contract_version(ep)) < MIN_VERSION:
        return False
    try:
        request = runtime_request.authority_for_episode(Path(ep).resolve())
    except Exception:
        request = None
    story_input = (request or {}).get("story_input") if isinstance(request, dict) else None
    # Concept-pool generation is an authoring gate. A user-locked story forbids
    # structural invention, so demanding 8-12 alternative concepts would violate
    # the request instead of improving it. Downstream Story Review still applies.
    if (isinstance(story_input, dict)
            and story_input.get("mode") == "locked_story"
            and story_input.get("allow_structure_rewrite") is False):
        return False
    return True

def resolve_ep(raw):
    ep = Path(raw).resolve()
    if not ep.is_dir(): raise SystemExit(f"episode directory not found: {ep}")
    try: ep.relative_to(ROOT.resolve())
    except ValueError: raise SystemExit("episode must be inside repository")
    return ep

def text(v): return str(v or "").strip()

def validate_candidates(data):
    errors = []
    rows = data.get("candidates")
    if not isinstance(rows, list) or not 8 <= len(rows) <= 12:
        return ["concept-candidates.json must contain 8-12 candidates"]
    ids = set()
    for i,row in enumerate(rows):
        where=f"candidates[{i}]"
        if not isinstance(row,dict):
            errors.append(f"{where} must be object"); continue
        cid=text(row.get("id"))
        if not cid: errors.append(f"{where}.id missing")
        elif cid in ids: errors.append(f"duplicate candidate id: {cid}")
        ids.add(cid)
        for key in ("title","one_line_hook","concept_class","discussion_question"):
            if not text(row.get(key)): errors.append(f"{where}.{key} missing")
        ceiling=row.get("anomaly_ceiling")
        if not isinstance(ceiling,dict): errors.append(f"{where}.anomaly_ceiling must be object")
        else:
            for key in ("initial","middle","climax"):
                if not text(ceiling.get(key)): errors.append(f"{where}.anomaly_ceiling.{key} missing")
        frames=row.get("viral_frames")
        if not isinstance(frames,dict): errors.append(f"{where}.viral_frames must be object")
        else:
            for key in VIRAL_KEYS:
                item=frames.get(key)
                if not isinstance(item,dict):
                    errors.append(f"{where}.viral_frames.{key} must be object"); continue
                if not text(item.get("visual")): errors.append(f"{where}.viral_frames.{key}.visual missing")
                if not text(item.get("why_stop")): errors.append(f"{where}.viral_frames.{key}.why_stop missing")
    return errors

def score_row(row, errors, where):
    scores=row.get("scores")
    if not isinstance(scores,dict):
        errors.append(f"{where}.scores must be object"); return -1
    total=0
    for key,maxv in SCORE_LIMITS.items():
        val=scores.get(key)
        if isinstance(val,bool) or not isinstance(val,(int,float)) or not 0 <= float(val) <= maxv:
            errors.append(f"{where}.scores.{key} must be 0..{maxv}"); continue
        total += int(val)
    if row.get("concept_voltage") != total:
        errors.append(f"{where}.concept_voltage must equal score sum {total}")
    return total

def validate_review(ep, review):
    if not required(ep): return []
    errors=[]
    cp=ep/CANDIDATES_REL
    if not cp.is_file(): return ["meta/concept-candidates.json missing"]
    candidates=read_json(cp)
    errors += validate_candidates(candidates)
    if errors: return errors
    if str(review.get("candidates_sha256") or "").lower() != sha256_file(cp).lower():
        errors.append("concept ambition review candidates_sha256 drift")
    if review.get("schema_version") != 1: errors.append("concept ambition review schema_version must be 1")
    prov=review.get("critic_provenance") or {}
    errors += runtime_provenance.validate_critic_provenance(prov)
    expected_ids=[str(x.get("id") or "") for x in candidates["candidates"]]
    rows=review.get("candidates")
    if not isinstance(rows,list) or len(rows)!=len(expected_ids):
        errors.append("concept ambition review must return one row per candidate"); rows=[]
    seen=set(); high=0; by_id={}
    for i,row in enumerate(rows):
        where=f"review.candidates[{i}]"
        if not isinstance(row,dict): errors.append(f"{where} must be object"); continue
        cid=text(row.get("id")); seen.add(cid); by_id[cid]=row
        band=text(row.get("ambition_band"))
        if band not in BANDS: errors.append(f"{where}.ambition_band must be A1..A5")
        if band in {"A4","A5"}: high += 1
        score_row(row,errors,where)
        wt=row.get("wordless_test")
        if not isinstance(wt,dict): errors.append(f"{where}.wordless_test must be object")
        else:
            for key in WORDLESS_KEYS:
                if not isinstance(wt.get(key),bool): errors.append(f"{where}.wordless_test.{key} must be boolean")
    if seen != set(expected_ids): errors.append("concept ambition review ids do not match candidate ids")
    if high < 3: errors.append("candidate pool must contain at least 3 A4/A5 high-ambition concepts")
    selected=text(review.get("selected_id"))
    if selected not in by_id: errors.append("selected_id must reference a reviewed candidate")
    else:
        row=by_id[selected]
        if not isinstance(row.get("concept_voltage"),(int,float)) or float(row["concept_voltage"]) < 80:
            errors.append("selected concept_voltage must be >= 80")
        if row.get("ambition_band") not in {"A3","A4","A5"}:
            errors.append("selected ambition band must be A3/A4/A5")
        wt=row.get("wordless_test") or {}
        if not all(wt.get(k) is True for k in WORDLESS_KEYS):
            errors.append("selected concept must pass all three wordless tests")
    if not text(review.get("selection_reason")): errors.append("selection_reason missing")
    if review.get("issue_codes") not in ([],None): errors.append("issue_codes must be empty for PASS")
    if (review.get("summary") or {}).get("passed") is not True: errors.append("summary.passed must be true")
    return errors

def verify(ep):
    if not required(ep): return []
    p=ep/REVIEW_REL
    if not p.is_file(): return ["meta/concept-ambition-review.json missing"]
    try: return validate_review(ep,read_json(p))
    except Exception as exc: return [str(exc)]

def resolve_codex(raw):
    import codex_cli_contract
    return codex_cli_contract.resolve_path(raw)

def prefix(codex):
    import codex_cli_contract
    return codex_cli_contract.command_prefix(codex)

def ordinary_life_mode(ep):
    p=Path(ep)/"meta/shot-progression-review.json"
    if not p.is_file():return False
    try:
        d=read_json(p)
        return d.get("anomaly_applicable") is False and bool(text(d.get("anomaly_exception_reason")))
    except Exception:
        return False

def critic_prompt(ep, cp, out, attempt):
    rel_ep=ep.relative_to(ROOT).as_posix()
    rel_cp=cp.relative_to(ROOT).as_posix()
    rel_out=out.relative_to(ROOT).as_posix()
    ordinary_override="" if not ordinary_life_mode(ep) else """
ORDINARY-LIFE AMBITION OVERRIDE (takes precedence over anomaly-band wording below):
- This Episode is explicitly anomaly_applicable=false. Do NOT add horror, mystery, investigation, paranormal behavior or an anomaly merely to raise concept_voltage.
- Interpret ambition bands by image/world/social scale for this Episode: A1 restrained everyday moment; A2 clear setting contrast; A3 strong celestial-life visual contrast; A4 large/high-impact world-scale daily-life image; A5 overwhelming world-scale daily-life image that still preserves ordinary behavior.
- Reward realistic celestial scale, character appeal, friendship chemistry, ordinary-life specificity, visual state change and wordless Cover/Mid/Climax readability.
- mechanism_novelty means novelty of the everyday-life visual/story engine, not an anomaly mechanism.
- At least 3 A4/A5 directions are still required, but they must achieve that through peaceful celestial-world scale and ordinary-life contrast, never through anomaly injection.
"""
    return f"""You are the independent Story OS V2.1 Concept Ambition + Image-first Propagation Critic.
Review ALL 8-12 concepts in {rel_cp}. This is a fresh isolated review.
{ordinary_override}
DOCTRINE:
- Concept ambition comes BEFORE capture realism.
- Do NOT lower a concept because its place, creature, ruin, dream-space, anomaly scale, case phenomenon, geography or world rule cannot exist in reality.
- Reality-first constrains HOW the later image is captured, not WHAT may happen.
- Reward concepts whose Cover/Mid/Climax images work before captions.
- Penalize generic unease, text-dependent reveals, tiny escalation, discovery-only climaxes and visually ordinary payoffs.
- Fictional cases, impossible ruins, dream intrusion, cosmic anomalies, giant-scale anomalies and surreal geography are valid.
- The pool must include at least 3 genuinely high-ambition A4/A5 directions.

Bands: A1 restrained oddity; A2 clear anomaly; A3 strong anomaly; A4 large/high-impact anomaly; A5 world-rule loss/overwhelming anomaly.

Scores: one_line_hook 0-20; hero_frame 0-20; escalation_ceiling 0-20; climax_visual_payoff 0-15; mechanism_novelty 0-15; discussion_space 0-10.
concept_voltage = exact sum.

Wordless test: stop_scroll, escalation_readable, curiosity_gap.
Select exactly ONE concept. Winner must score >=80 and pass all 3 wordless checks.
If no valid winner exists, summary.passed=false.

Write ONLY JSON to {rel_out}:
{{
  "candidates":[{{
    "id":"C01","ambition_band":"A4",
    "scores":{{"one_line_hook":18,"hero_frame":19,"escalation_ceiling":18,"climax_visual_payoff":14,"mechanism_novelty":13,"discussion_space":9}},
    "concept_voltage":91,
    "wordless_test":{{"stop_scroll":true,"escalation_readable":true,"curiosity_gap":true}},
    "strengths":["..."],"risks":["..."]
  }}],
  "selected_id":"C01",
  "selection_reason":"...",
  "issue_codes":[],
  "summary":{{"passed":true}}
}}
Episode: {rel_ep}
Attempt: {attempt}
"""

def _finalize_review(ep, review, before, provenance):
    review["schema_version"]=1
    review["story_os_version"]=episode_contract_version(ep)
    review["candidates_sha256"]=before
    review["critic_provenance"]=provenance
    final=ep/REVIEW_REL
    if final.is_file():
        prior=read_json(final)
        prior_sha=text(prior.get("candidates_sha256")).lower() if isinstance(prior,dict) else ""
        if prior_sha and prior_sha != str(before).lower():
            history=ep/"meta"/"review-history"/f"concept-ambition-review-{prior_sha}.json"
            history.parent.mkdir(parents=True,exist_ok=True)
            if history.exists():
                raise RuntimeError(f"refusing to overwrite archived concept review: {history}")
            shutil.copy2(final,history)
    write_json(final,review)
    (ep/CANDIDATE_REVIEW_REL).unlink(missing_ok=True)
    errs=validate_review(ep,review)
    if errs:
        print("CONCEPT AMBITION REVIEW FAIL")
        [print("FAIL:",e) for e in errs]; return 2
    print("CONCEPT AMBITION REVIEW PASS"); return 0


def finalize_product_review(ep, attempt, runtime):
    cp=ep/CANDIDATES_REL; candidate=ep/CANDIDATE_REVIEW_REL
    review,provenance=product_review_adapter.finalize_candidate(
        ep,kind="concept-ambition",runtime=runtime,attempt=attempt,candidate_path=candidate)
    rc=_finalize_review(ep,review,sha256_file(cp),provenance)
    if rc==0: product_review_adapter.mark_complete(ep,"concept-ambition",attempt=attempt,final_path=ep/REVIEW_REL)
    return rc


def run_critic(ep, attempt, codex_raw, timeout=None):
    if not required(ep):
        print("CONCEPT AMBITION: NOT REQUIRED FOR LEGACY EPISODE"); return 0
    if attempt not in {1,2}: raise RuntimeError("attempt must be 1 or 2")
    if timeout is None:
        timeout = runtime_timeout_policy.seconds("review_critic")
    cp=ep/CANDIDATES_REL
    if not cp.is_file(): raise RuntimeError("meta/concept-candidates.json missing")
    errs=validate_candidates(read_json(cp))
    if errs:
        [print("FAIL:",e) for e in errs]; return 2
    before=sha256_file(cp)
    candidate=ep/CANDIDATE_REVIEW_REL; candidate.unlink(missing_ok=True)
    runtime,_=runtime_router.detect()
    if runtime in {"WORK","WEB"} and not codex_raw:
        req=product_review_adapter.prepare(
            ep,kind="concept-ambition",runtime=runtime,attempt=attempt,
            prompt=critic_prompt(ep,cp,candidate,attempt),source_paths=[cp],candidate_path=candidate)
        print(json.dumps(req,ensure_ascii=False,indent=2))
        return product_review_adapter.HOST_ACTION_REQUIRED_RC
    codex=resolve_codex(codex_raw)
    cmd=prefix(codex)+["exec","--skip-git-repo-check","--ephemeral","-c",'model_reasoning_effort="medium"'," -s".strip(),"workspace-write","-C",str(ROOT),"--json","-"]
    log=ep/"meta"/f"concept-ambition-critic-{before}-attempt-{attempt}.jsonl"
    with log.open("w",encoding="utf-8",newline="\n") as h:
        # The user-mode Runner's inherited ~/.codex/tmp/arg0 can carry stale
        # Windows ACLs. Codex then fails to initialize its app-server before
        # Concept Review begins. Isolate the authenticated task home in the
        # Runner user's AppData; the existing bridge seeds auth/config, exports
        # task artifacts and removes the disposable home afterwards.
        done=codex_user_runner.run_model_codex(
            cmd, input=critic_prompt(ep,cp,candidate,attempt),
            text=True, encoding="utf-8", stdout=h, stderr=subprocess.STDOUT,
            timeout=timeout, check=False, task_type="critic",
            codex_home_mode="isolated",
        )
    if done.returncode != 0: raise RuntimeError(f"concept critic failed rc={done.returncode}; log={log}")
    if sha256_file(cp) != before: raise RuntimeError("concept critic modified candidate pool")
    if not candidate.is_file(): raise RuntimeError("concept critic did not produce candidate JSON")
    review=read_json(candidate)
    provenance=runtime_provenance.build_critic_provenance("CODEX",attempt=attempt,log=log.relative_to(ROOT).as_posix())
    return _finalize_review(ep,review,before,provenance)

def init_candidates(ep):
    p=ep/CANDIDATES_REL
    if p.exists(): print(p); return 0
    rows=[]
    for i in range(1,9):
        rows.append({"id":f"C{i:02d}","title":"","one_line_hook":"","concept_class":"",
                     "anomaly_ceiling":{"initial":"","middle":"","climax":""},
                     "viral_frames":{"cover":{"visual":"","why_stop":""},"mid":{"visual":"","why_stop":""},"climax":{"visual":"","why_stop":""}},
                     "discussion_question":""})
    write_json(p,{"schema_version":1,"story_os_version":episode_contract_version(ep),
                  "creative_doctrine":"概念不要克制，镜头必须真实；真实性约束怎么拍，不限制发生什么。","candidates":rows})
    print(p); return 0

def self_test():
    rows=[]
    for i in range(8):
        rows.append({"id":f"C{i+1:02d}","title":"x","one_line_hook":"x","concept_class":"x",
                     "anomaly_ceiling":{"initial":"x","middle":"x","climax":"x"},
                     "viral_frames":{"cover":{"visual":"x","why_stop":"x"},"mid":{"visual":"x","why_stop":"x"},"climax":{"visual":"x","why_stop":"x"}},
                     "discussion_question":"x"})
    assert validate_candidates({"candidates":rows}) == []
    assert validate_candidates({"candidates":rows[:7]})
    old=ordinary_life_mode
    globals()["ordinary_life_mode"]=lambda _ep:True
    try:
        prompt=critic_prompt(ROOT,ROOT/"dummy-concepts.json",ROOT/"dummy-review.json",1)
        assert "ORDINARY-LIFE AMBITION OVERRIDE" in prompt
        assert "Do NOT add horror" in prompt
        assert "peaceful celestial-world scale" in prompt
    finally:
        globals()["ordinary_life_mode"]=old
    print("CONCEPT AMBITION V2.1 SELF-TEST PASS")

def re_review_plan(ep: Path) -> dict:
    ep = Path(ep).resolve()
    cp = ep / CANDIDATES_REL
    review_path = ep / REVIEW_REL
    if not cp.is_file():
        return {"required": False, "reason": "CANDIDATES_MISSING"}
    current_sha = sha256_file(cp)
    review = read_json(review_path) if review_path.is_file() else {}
    reviewed_sha = str(review.get("candidates_sha256") or "").lower()
    drifted = bool(reviewed_sha and reviewed_sha != current_sha.lower())
    attempts = []
    for row in runtime_review_persistence.list_attempts(ep, "concept-ambition"):
        try:
            attempts.append(int((row.get("payload") or {}).get("attempt") or 0))
        except (TypeError, ValueError):
            continue
    reviewed_attempt = int(((review.get("critic_provenance") or {}).get("attempt") or 0)) if isinstance(review, dict) else 0
    next_attempt = max([reviewed_attempt, *attempts, 0]) + 1
    return {
        "required": (not review_path.is_file()) or drifted,
        "reason": "CANDIDATES_SHA_DRIFT" if drifted else ("REVIEW_MISSING" if not review_path.is_file() else "CURRENT_REVIEW_VALID"),
        "current_candidates_sha256": current_sha,
        "reviewed_candidates_sha256": reviewed_sha or None,
        "preserve_existing_review": review_path.is_file(),
        "next_attempt": next_attempt,
        "action": "RUN_CONCEPT_AMBITION_CRITIC" if ((not review_path.is_file()) or drifted) else "NONE",
    }


def main():
    ap=argparse.ArgumentParser(description=__doc__); sub=ap.add_subparsers(dest="cmd",required=True)
    p=sub.add_parser("init"); p.add_argument("episode_dir")
    p=sub.add_parser("run-critic"); p.add_argument("episode_dir"); p.add_argument("--attempt",type=int,default=1); p.add_argument("--codex"); p.add_argument("--timeout",type=int,default=None)
    p=sub.add_parser("finalize-review"); p.add_argument("episode_dir"); p.add_argument("--attempt",type=int,default=1); p.add_argument("--runtime",choices=["WORK","WEB"],default="WORK")
    p=sub.add_parser("verify"); p.add_argument("episode_dir")
    p=sub.add_parser("show"); p.add_argument("episode_dir")
    p=sub.add_parser("re-review-plan"); p.add_argument("episode_dir")
    sub.add_parser("self-test")
    a=ap.parse_args()
    if a.cmd=="self-test": self_test(); return 0
    ep=resolve_ep(a.episode_dir)
    if a.cmd=="init": return init_candidates(ep)
    if a.cmd=="re-review-plan":
        print(json.dumps(re_review_plan(ep),ensure_ascii=False,indent=2)); return 0
    if a.cmd=="show":
        for rel in (CANDIDATES_REL,REVIEW_REL):
            p=ep/rel; print(f"--- {rel} ---"); print(p.read_text(encoding="utf-8") if p.is_file() else "{}")
        return 0
    if a.cmd=="run-critic":
        try: return run_critic(ep,a.attempt,a.codex,a.timeout)
        except (OSError,RuntimeError,ValueError,subprocess.TimeoutExpired) as exc:
            print("CONCEPT AMBITION ERROR:",exc); return 3
    if a.cmd=="finalize-review":
        try: return finalize_product_review(ep,a.attempt,a.runtime)
        except (OSError,RuntimeError,ValueError) as exc:
            print("CONCEPT AMBITION FINALIZE ERROR:",exc); return 3
    errs=verify(ep)
    if errs:
        [print("FAIL:",e) for e in errs]; return 2
    print("CONCEPT AMBITION VERIFIED"); return 0

if __name__=="__main__": raise SystemExit(main())
