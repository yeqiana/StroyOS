"""R11 slot1: hard SHA provenance for renamed StoryOS story assets."""
from pathlib import Path
import hashlib
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
import storyos_relocated_review_recovery as recovery
import pytest

EP_REL=Path("episodes/15_天界生活日常/01_天界普通女生的一天")
OLD="episodes/天界普通女生的一天"

def case():
    ep=ROOT/EP_REL
    m=__import__("json").loads((ep/"meta/release-manifest.json").read_text("utf-8-sig"))
    req=__import__("json").loads((ep/"meta/runtime/reviews/story-semantic-attempt-2-request.json").read_text("utf-8-sig"))
    return ep,m,req

def historical_v1_manifest(manifest: dict) -> dict:
    """The prior Git rename proof refers to immutable V1.0, not V1.1."""
    previous=__import__("copy").deepcopy(manifest)
    previous["artifacts"]["storyboard"]=str(
        next((ROOT/EP_REL/"docs").glob("*正式分镜_V1.0.md"))
        .relative_to(ROOT)).replace("\\","/")
    return previous

def test_actual_migrated_episode_sources_proved_from_git_and_frozen_sha():
    ep,m,req=case()
    verdict=recovery.verify_relocated_artifacts(
        ROOT,ep,historical_v1_manifest(m),req["source_files"],
        check_all_frozen_sources=False)
    assert verdict["status"]=="GIT_RENAME_AND_REVIEW_SHA_VERIFIED"
    assert len(verdict["paths"])==3
    assert all(v["old"].startswith(OLD+"/") for v in verdict["paths"].values())
    assert all(v["new"].startswith(EP_REL.as_posix()+"/") for v in verdict["paths"].values())

def test_source_sha_poison_blocks_even_matching_basename():
    ep,m,req=case()
    poisoned=[dict(x) for x in req["source_files"]]
    for x in poisoned:
        if x["path"]==m["artifacts"]["story"]:
            x["sha256"]="0"*64
    result=recovery.verify_relocated_artifacts(ROOT,ep,m,poisoned)
    assert result["status"]=="CRITIC_SOURCE_SHA_DRIFT"

def test_real_legacy_review_must_not_be_replayed_after_rubric_sha_drift():
    ep,m,req=case()
    # The story/board are unchanged, but current production rubric is not the
    # same frozen rubric that was independently reviewed in September.
    verdict=recovery.verify_relocated_artifacts(ROOT,ep,m,req["source_files"])
    assert verdict["status"]=="CRITIC_SOURCE_SHA_DRIFT"


def test_non_episode_source_sha_poison_also_blocks_replay():
    ep,m,req=case()
    poisoned=[dict(x) for x in req["source_files"]]
    poisoned[-1]["sha256"]="0"*64
    result=recovery.verify_relocated_artifacts(ROOT,ep,m,poisoned)
    assert result["status"]=="CRITIC_SOURCE_SHA_DRIFT"

def test_ambiguous_non_git_rename_blocked(monkeypatch):
    ep,m,req=case()
    monkeypatch.setattr(recovery,"blob_at",lambda rev,path,root:"a"*40 if rev.endswith("^") else "b"*40)
    assert recovery.verify_relocated_artifacts(
        ROOT,ep,historical_v1_manifest(m),req["source_files"],
        check_all_frozen_sources=False)["status"]=="GIT_BYTE_IDENTITY_UNVERIFIED"
