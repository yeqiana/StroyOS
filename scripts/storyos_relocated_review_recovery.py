#!/usr/bin/env python3
"""Recover unchanged, Git-proven relocated StoryOS Episode metadata.

Default audit is strictly read-only. Only an explicit acknowledged apply may
correct a release-manifest path and persist the existing independently reviewed
PASS payload to canonical MySQL. Never edit request history, reviewer verdicts,
stories, prompts, scripts, or policy identities; never call an image Provider.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import storyos_codex_managed as native

RENAME_COMMIT = "69e7a2a8"
SUPPORTED_FIELDS = ("story", "storyboard", "visual_spec")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def blob_at(revision: str, path: str, root: Path) -> str | None:
    r = subprocess.run(["git", "rev-parse", "--verify", f"{revision}:{path}"],
                       cwd=root, capture_output=True, text=True, timeout=15)
    return r.stdout.strip() if r.returncode == 0 and re.fullmatch(r"[a-f0-9]{40,64}",r.stdout.strip()) else None


def verify_relocated_artifacts(root: Path, ep: Path, manifest: dict, frozen: list[dict], *, check_all_frozen_sources: bool=True) -> dict:
    """All three paths require a byte-identical historical Git rename.

    Frozen Critic source SHA supplies a second independent byte check for
    story/storyboard. A basename match without Git blob identity is insufficient.
    """
    arts=manifest.get("artifacts") if isinstance(manifest,dict) else None
    if not isinstance(arts,dict):
        return {"status":"MANIFEST_INVALID","paths":{}}
    frozen_by_old={str(x.get("path") or ""):str(x.get("sha256") or "").lower()
                   for x in frozen if isinstance(x,dict)}
    # Reviewer froze ALL sources, including repo-level rubric/cases. An
    # unchanged story does not justify replay if its reviewed rubric drifted.
    if not frozen_by_old or len(frozen_by_old)!=len(frozen):
        return {"status":"CRITIC_SOURCE_SHA_DRIFT","paths":{}}
    # Use immutable original request paths even after the canonical manifest
    # was migrated. A completed migration must not invalidate its own tests.
    historic_story=next((
        source for source in frozen_by_old
        if Path(source).name==Path(str(arts.get("story") or "")).name
        and source.startswith("episodes/")),None)
    historic_board=next((
        source for source in frozen_by_old
        if Path(source).name==Path(str(arts.get("storyboard") or "")).name
        and source.startswith("episodes/")),None)
    if not historic_story or not historic_board or Path(historic_story).parent!=Path(historic_board).parent:
        return {"status":"CRITIC_SOURCE_SHA_DRIFT","paths":{}}
    old_parent=Path(historic_story).parent
    old_refs={field:(old_parent/Path(str(arts.get(field) or "")).name).as_posix()
              for field in SUPPORTED_FIELDS}
    # Only the historical or verified new path is admitted; no arbitrary
    # basename-based alias remapping or half-migrated paths.
    for field in SUPPORTED_FIELDS:
        actual=arts.get(field)
        expected_new=(ep/"docs"/Path(str(actual or "")).name).relative_to(root).as_posix()
        if actual not in (old_refs[field],expected_new):
            return {"status":"ARTIFACT_REFERENCE_UNVERIFIED","field":field,"paths":{}}

    if check_all_frozen_sources:
        for source,expected_sha in frozen_by_old.items():
            if not re.fullmatch(r"[a-f0-9]{64}", expected_sha) or ".." in Path(source).parts:
                return {"status":"CRITIC_SOURCE_SHA_DRIFT","paths":{}}
            source_path=(root/source).resolve()
            if source_path.is_file() and source_path.is_relative_to(root):
                if sha256_file(source_path)!=expected_sha:
                    return {"status":"CRITIC_SOURCE_SHA_DRIFT","paths":{}}
            elif source not in (old_refs["story"], old_refs["storyboard"]):
                return {"status":"CRITIC_SOURCE_SHA_DRIFT","paths":{}}
    paths={}
    for field in SUPPORTED_FIELDS:
        old=old_refs[field]
        actual=arts.get(field)
        if not isinstance(actual,str) or not actual.startswith("episodes/") or ".." in Path(actual).parts:
            return {"status":"ARTIFACT_REFERENCE_UNVERIFIED","field":field,"paths":{}}
        current=ep/"docs"/Path(old).name
        if not current.is_file() or not current.resolve().is_relative_to(ep.resolve()):
            return {"status":"RELOCATED_FILE_MISSING","field":field,"paths":{}}
        new=current.relative_to(root).as_posix()
        before=blob_at(RENAME_COMMIT+"^",old,root)
        after=blob_at(RENAME_COMMIT,new,root)
        head=blob_at("HEAD",new,root)
        if not before or before!=after or head!=after:
            return {"status":"GIT_BYTE_IDENTITY_UNVERIFIED","field":field,"paths":{}}
        if field in ("story","storyboard"):
            if not re.fullmatch(r"[a-f0-9]{64}",frozen_by_old.get(old,"")) or sha256_file(current)!=frozen_by_old[old]:
                return {"status":"CRITIC_SOURCE_SHA_DRIFT","field":field,"paths":{}}
        paths[field]={"old":old,"new":new}
    return {"status":"GIT_RENAME_AND_REVIEW_SHA_VERIFIED","paths":paths}


def inspect(episode: str) -> dict:
    base={"status":"BLOCKED","read_only":True,"can_dispatch_image":False,
          "model_calls":0,"mysql_writes":0,"manifest_writes":0,
          "can_recover_review":False}
    try:
        ep=native.canonical_episode(episode)
        root=native.ROOT
        env=native.native_environment()
        ref=ep.relative_to(root).as_posix()
        rc,stage=native._probe(env,"scripts/storyos_episode_stage_readonly.py",["--episode",ref])
        if rc!=0 or stage.get("source")!="mysql" or stage.get("stage")!="STORYBOARD_LOCKED":
            return {**base,"status":"MYSQL_STAGE_NOT_VERIFIED"}
        a_rc,attempt=native._probe(env,"scripts/storyos_attempt_readonly_preflight.py",["--episode",ref])
        if (a_rc!=0 or attempt.get("status")!="ATTEMPT_HISTORY_READ_ONLY"
            or attempt.get("active_attempt_assets") or attempt.get("outcome_unknown_assets")
            or attempt.get("unverified_status_assets")):
            return {**base,"status":"IMAGE_ATTEMPT_NOT_VERIFIED"}
        os.environ.update(env)
        sys.path.insert(0,str(native.SYSTEM)) if str(native.SYSTEM) not in sys.path else None
        import product_review_adapter as pra
        import story_review as review
        import story_json
        import model_policy_persistence
        manifest_path=ep/"meta/release-manifest.json"
        manifest=story_json.read_json(manifest_path)
        second=pra.request_path(ep,"story-semantic",attempt=2)
        if not pra._request_exists(second):
            return {**base,"status":"HISTORIC_REVIEW_REQUEST_MISSING"}
        request=pra._read_json(second)
        if request.get("status")!="FINALIZED" or request.get("attempt")!=2:
            return {**base,"status":"HISTORIC_REQUEST_NOT_FINALIZED"}
        relocation=verify_relocated_artifacts(root,ep,manifest,request.get("source_files") or [])
        if relocation.get("status")!="GIT_RENAME_AND_REVIEW_SHA_VERIFIED":
            return {**base,**relocation}
        legacy_path=ep/review.REVIEW_REL
        if not legacy_path.is_file():
            return {**base,"status":"INDEPENDENT_REVIEW_BYTES_MISSING"}
        original=story_json.read_json(legacy_path)
        story=root/relocation["paths"]["story"]["new"]
        storyboard=root/relocation["paths"]["storyboard"]["new"]
        errors=review.validate_payload(original,story_sha=sha256_file(story),
                                      storyboard_sha=sha256_file(storyboard),
                                      version=review.episode_contract_version(ep))
        proven=(not errors and (original.get("summary") or {}).get("passed") is True
                and (original.get("critic_provenance") or {}).get("attempt")==2
                and (original.get("critic_provenance") or {}).get("request_id")==request.get("request_id")
                and original.get("story_sha256")==sha256_file(story)
                and original.get("storyboard_sha256")==sha256_file(storyboard))
        if not proven:
            return {**base,"status":"INDEPENDENT_REVIEW_PROVENANCE_FAILED","issue_count":len(errors)}
        existing=review.load_review(ep)
        if existing is not None:
            return {**base,"status":"CANONICAL_REVIEW_ALREADY_EXISTS"}
        frozen_policy=model_policy_persistence.load(ep)
        return {**base,"status":"VERIFIED_LEGACY_REVIEW_CAN_BE_RESTORED",
                "can_recover_review":True,"episode":ref,
                "review_sha256":sha256_file(legacy_path),
                "manifest_sha256":sha256_file(manifest_path),
                "frozen_model_policy_bound":bool((frozen_policy or {}).get("policy_sha256")),
                "source_relocation":relocation["paths"],
                "review_request_id":request["request_id"]}
    except Exception as exc:
        return {**base,"status":"RECOVERY_EVIDENCE_UNAVAILABLE",
                "error_type":type(exc).__name__}


def main(argv=None)->int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("episode")
    parser.add_argument("--apply",action="store_true")
    parser.add_argument("--ack-real-production",action="store_true")
    args=parser.parse_args(argv)
    report=inspect(args.episode)
    if not args.apply:
        print(json.dumps(report,ensure_ascii=False,sort_keys=True))
        return 0 if report["can_recover_review"] else 2
    if not args.ack_real_production or not report["can_recover_review"]:
        print(json.dumps({**report,"status":"REFUSED_UNVERIFIED_OR_UNACKNOWLEDGED"},ensure_ascii=False))
        return 2
    # Mutation is deliberately a separate operational step and is revalidated
    # under primary checkout in the official runtime; no implicit CLI retries.
    from storyos_relocation_apply import restore
    result=restore(args.episode,report,inspect)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))
    return 0 if result.get("status")=="RESTORED" else 2

if __name__=="__main__":
    raise SystemExit(main())
