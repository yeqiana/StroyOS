"""Episode14 render-version proposal is never approval or Attempt entitlement."""
from __future__ import annotations
import hashlib,json,sys
from pathlib import Path
from unittest.mock import Mock
import pytest
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/"episodes/_system")]
import production_ep14_render_relock_preflight as relock

def preview(frame):
    source=f"unapproved native text for {frame} | NOT YET AUTHORIZED"
    scene=f"nonviolent narrative photographic reinterpretation {frame}"
    original_frame,original_scene,original_excerpt=relock.treatment.ORIGINAL[frame]
    return {
        "frame":frame,
        "review_approved":False,"dispatch_authorized":False,
        "review_status":"AWAITING_INDEPENDENT_SEMANTIC_AND_CONTENT_REVIEW",
        "render_contract_status":"DRAFT_NOT_CANONICAL",
        "live_source_authority_verified":True,
        "episode_model_policy_verified":True,
        "original_frame_contract_sha256":original_frame,
        "original_scene_prompt_sha256":original_scene,
        "original_storyboard_excerpt_sha256":original_excerpt,
        "scene_prompt":scene,
        "candidate_scene_prompt_sha256":hashlib.sha256(scene.encode()).hexdigest(),
        "full_native_worker_prompt":source,
        "full_native_worker_prompt_sha256":hashlib.sha256(source.encode()).hexdigest(),
        "candidate_render_contract_sha256":"1"*64,
        "staging_package_sha256":"2"*64,
        "model":"gpt-image-2.5-flare","quality":"high","canvas":"1080x1350",
    }

@pytest.mark.parametrize("frame",[9,29,48])
def test_new_variant_hash_binds_original_without_rewriting(frame):
    src=preview(frame)
    before=json.dumps(src,sort_keys=True)
    result=relock.draft_binding(src)
    assert result["status"]=="READY_FOR_SEPARATE_INDEPENDENT_REVIEW"
    assert result["render_variant_sha256"]!=result["original_frame_contract_sha256"]
    assert result["required_independent_review"]["approved"] is False
    assert result["required_independent_review"]["must_review_final_model_controller_output"] is True
    assert result["canonical_prompt_package_written"] is False
    assert result["production_dispatch_authorized"] is False
    assert result["model_calls"]==result["mysql_writes"]==result["paid_attempts_reserved"]==0
    assert json.dumps(src,sort_keys=True)==before
    assert relock.draft_binding(src)==result

def test_review_not_proven_must_fail_closed():
    for mutation in (
        lambda p:p.update(review_approved=True),
        lambda p:p.update(live_source_authority_verified=False),
        lambda p:p.update(episode_model_policy_verified=False),
        lambda p:p.update(dispatch_authorized=True),
        lambda p:p.update(review_status="APPROVED"),
        lambda p:p.update(render_contract_status="CANONICAL"),
    ):
        src=preview(9)
        mutation(src)
        with pytest.raises(ValueError,match="LIVE_UNAPPROVED_SOURCE"):
            relock.draft_binding(src)

def test_tampering_of_request_scene_and_original_provenance_refused():
    for mutation in (
        lambda p:p.update(scene_prompt="tampered"),
        lambda p:p.update(full_native_worker_prompt="tampered"),
        lambda p:p.update(full_native_worker_prompt=""),
        lambda p:p.update(original_scene_prompt_sha256="3"*64),
        lambda p:p.update(original_storyboard_excerpt_sha256="4"*64),
        lambda p:p.update(candidate_render_contract_sha256=""),
        lambda p:p.update(staging_package_sha256=""),
    ):
        src=preview(29);mutation(src)
        with pytest.raises(ValueError):
            relock.draft_binding(src)

def test_legacy_rejected_generation_text_never_promotable():
    src=preview(48)
    src["full_native_worker_prompt"]+="脱敏生图 Prompt"
    src["full_native_worker_prompt_sha256"]=hashlib.sha256(src["full_native_worker_prompt"].encode()).hexdigest()
    with pytest.raises(ValueError,match="PROPOSED_NATIVE"):
        relock.draft_binding(src)

def test_wrong_frame_never_enters_binding():
    src=preview(9);src["frame"]=20
    with pytest.raises(ValueError,match="LIVE_UNAPPROVED_SOURCE"):
        relock.draft_binding(src)