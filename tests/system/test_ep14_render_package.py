"""The EP14 derived render packages never mutate original Prompt Package authority."""
from __future__ import annotations
import hashlib
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "episodes/_system"))
import production_ep14_render_package as packages


def digest(text):
    return hashlib.sha256(text.encode("utf8")).hexdigest()


@pytest.fixture
def sample(monkeypatch, tmp_path):
    import production_ep14_visual_treatment_preview as treatment
    import frame_contract
    import image_model_policy
    ep = tmp_path.resolve()
    monkeypatch.setattr(treatment, "EP", ep)
    staged = []
    variants = []
    audited = []
    render_by_frame = {}
    for f in (9, 29, 48):
        original = f"LOCKED ORIGINAL STORYBOARD FRAME {f}: DO NOT RENDER ORIGINAL"
        raw_sha = digest(f"locked-contract-{f}")
        storyboard_sha = digest(original)
        render_sha = digest(f"render-v{f}")
        scene = f"safe derived visual scene {f}"
        worker = digest(f"native-prompt-{f}")
        variant_sha = digest(f"variant-{f}")
        controller_sha = digest(f"independently reviewed controller scene {f}")
        preview_receipt = {
            "status": "REVIEWED_PREVIEW_ONLY_NOT_CANONICAL",
            "production_dispatch_authorized": False,
            "render_variant_sha256": variant_sha,
            "reviewed_native_worker_prompt_sha256": worker,
            "controller_scene_sha256": controller_sha,
            "controller_runner_log_sha256": digest(f"runner-{f}"),
        }
        staged.append({
            "frame": f, "review_approved": False, "dispatch_authorized": False,
            "full_native_worker_prompt_sha256": worker,
            "original_frame_contract_sha256": raw_sha,
            "original_storyboard_excerpt_sha256": storyboard_sha,
            "scene_prompt": scene, "candidate_render_contract_sha256": render_sha,
        })
        variants.append({
            "frame": f, "production_dispatch_authorized": False,
            "canonical_prompt_package_written": False,
            "render_variant_sha256": variant_sha,
            "original_frame_contract_sha256": raw_sha,
            "original_storyboard_frame_sha256": storyboard_sha,
            "alternative_render_contract_sha256": render_sha,
            "alternative_scene_prompt_sha256": digest(scene),
            "verified_text_review_receipt": {
                "status": "TEXT_REVIEW_VERIFIED_NOT_FINAL_CONTROLLER_APPROVAL",
                "production_dispatch_authorized": False,
                "reviewed_worker_prompt_sha256": worker,
            },
            "verified_noncanonical_controller_draft_receipt": preview_receipt,
        })
        audited.append({
            "frame": f, "controller_draft_scene_sha256": controller_sha,
            "controller_draft_runner_log_sha256": preview_receipt["controller_runner_log_sha256"],
        })
        render_by_frame[f] = {
            "proposed_scene_prompt": scene,
            "proposed_render_contract_sha256": render_sha,
            "proposed_render_contract_text": (
                f"PROPOSED RENDER TREATMENT | frame={f:02d} | NOT YET AUTHORIZED\n"
                "[ALTERNATIVE VISUAL TREATMENT, REVIEW PENDING]\n"
                f"safe visual render content without original storyboard {f}"
            ),
        }
    def original_frame(ep, f, *, write_cache=False):
        assert write_cache is False
        original = f"LOCKED ORIGINAL STORYBOARD FRAME {f}: DO NOT RENDER ORIGINAL"
        return {
            "contract_sha256": digest(f"locked-contract-{f}"),
            "prompt_contract": f"ORIGINAL LOCKED SOURCE FRAME {f}: {original}",
            "storyboard_frame": {"sha256": digest(original), "text": original},
        }
    monkeypatch.setattr(frame_contract, "compile_frame", original_frame)
    monkeypatch.setattr(treatment, "compile_candidate", lambda ep, f: render_by_frame[f])
    monkeypatch.setattr(image_model_policy, "for_episode",
                        lambda ep: {"model": "gpt-image-2.5-flare", "quality": "high"})
    return ep, staged, variants, audited, render_by_frame


def test_package_is_derived_without_original_storyboard_render_leak(sample):
    ep, staged, variants, reviewed, _ = sample
    for f, s, v, audit in zip((9, 29, 48), staged, variants, reviewed):
        pkg = packages.compile_preview(ep, s, v, audit)
        assert pkg["frame"] == f"{f:02d}"
        assert pkg["frame_contract_sha256"] == s["original_frame_contract_sha256"]
        assert "LOCKED ORIGINAL STORYBOARD FRAME" not in pkg["frame_prompt_contract"]
        assert "NOT YET AUTHORIZED" in pkg["frame_prompt_contract"]
        assert "ALTERNATIVE VISUAL TREATMENT" in pkg["frame_prompt_contract"]
        assert pkg["storyboard_source"]["sha256"] == s["original_storyboard_excerpt_sha256"]
        assert "text" not in pkg["storyboard_source"]
        assert pkg["storyboard_source"]["render_original_text_injected"] is False
        assert pkg["storyboard_source"]["authority"] == "LOCKED_ORIGINAL_STORYBOARD_HASH_ONLY"
        assert "LOCKED ORIGINAL STORYBOARD FRAME" not in str(pkg["storyboard_source"])
        assert pkg["source_prompt"] == "EP14_DERIVED_RENDER_VARIANT_NONCANONICAL"
        assert pkg["status"] == "REVIEWED_PROPOSED_PACKAGE_NOT_ACTIVATED"
        assert pkg["canonical_activation"] is False
        assert pkg["production_dispatch_authorized"] is False
        assert pkg["canonical_prompt_package_written"] is False
        assert pkg["mysql_writes"] == 0
        assert pkg["paid_attempts_reserved"] == 0
        assert packages.compile_preview(ep, s, v, audit)["package_sha256"] == pkg["package_sha256"]


def test_reviewed_three_frame_bundle_has_single_stable_fingerprint(sample):
    ep, staged, variants, audited, _ = sample
    review = {
        "status": "VERIFIED_NONCANONICAL_CONTROLLER_REVIEW_NOT_PRODUCTION_ADMISSION",
        "production_dispatch_authorized": False, "frames": audited,
    }
    result = packages.compile_bundle(ep, staged, variants, review)
    assert len(result["frames"]) == 3
    assert result["status"] == "THREE_FRAME_REVIEWED_PACKAGE_PROPOSAL_NOT_CANONICAL"
    assert len(result["bundle_sha256"]) == 64
    assert result["bundle_sha256"] == packages.compile_bundle(
        ep, list(reversed(staged)), list(reversed(variants)),
        {**review, "frames": list(reversed(audited))},
    )["bundle_sha256"]
    assert result["canonical_prompt_packages_written"] is False
    assert result["production_dispatch_authorized"] is False


@pytest.mark.parametrize("reason", [
    "wrong_frame", "wrong_episode", "source_drift", "story_sha_drift",
    "no_review", "fake_controller", "wrong_controller_log",
    "wrong_controller_scene", "different_scene", "old_story_leak",
    "no_review_marker", "false_approval", "false_dispatch",
    "old_frame_prompt", "render_contract_drift",
])
def test_invalid_or_stale_render_proposal_fails_closed(sample, reason):
    ep, staged, variants, audited, render_by_frame = sample
    s, v, a = staged[0], variants[0], audited[0]
    if reason == "wrong_frame":
        s["frame"] = 20
    elif reason == "wrong_episode":
        ep = ep / "wrong"
    elif reason == "source_drift":
        s["original_frame_contract_sha256"] = "0" * 64
    elif reason == "story_sha_drift":
        s["original_storyboard_excerpt_sha256"] = "0" * 64
    elif reason == "no_review":
        v["verified_text_review_receipt"] = None
    elif reason == "fake_controller":
        v["verified_noncanonical_controller_draft_receipt"]["production_dispatch_authorized"] = True
    elif reason == "wrong_controller_log":
        a["controller_draft_runner_log_sha256"] = "0" * 64
    elif reason == "wrong_controller_scene":
        a["controller_draft_scene_sha256"] = "0" * 64
    elif reason == "different_scene":
        s["scene_prompt"] = "unreviewed scene"
    elif reason == "old_story_leak":
        render_by_frame[9]["proposed_render_contract_text"] += (
            "\nLOCKED ORIGINAL STORYBOARD FRAME 9: DO NOT RENDER ORIGINAL")
    elif reason == "no_review_marker":
        render_by_frame[9]["proposed_render_contract_text"] = "safe alternate contract"
    elif reason == "false_approval":
        s["review_approved"] = True
    elif reason == "false_dispatch":
        v["production_dispatch_authorized"] = True
    elif reason == "old_frame_prompt":
        render_by_frame[9]["proposed_render_contract_text"] = (
            "ORIGINAL LOCKED SOURCE FRAME 9: LOCKED ORIGINAL STORYBOARD FRAME 9")
    elif reason == "render_contract_drift":
        render_by_frame[9]["proposed_render_contract_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        packages.compile_preview(ep, s, v, a)


@pytest.mark.parametrize("reason", [
    "missing_frame", "duplicate_frame", "wrong_review_status",
    "false_production_permission", "missing_audit", "missing_variant",
])
def test_no_partial_approval_of_three_frame_bundle(sample, reason):
    ep, staged, variants, audited, _ = sample
    review = {
        "status": "VERIFIED_NONCANONICAL_CONTROLLER_REVIEW_NOT_PRODUCTION_ADMISSION",
        "production_dispatch_authorized": False, "frames": audited,
    }
    if reason == "missing_frame":
        staged.pop()
    elif reason == "duplicate_frame":
        staged[2]["frame"] = 29
    elif reason == "wrong_review_status":
        review["status"] = "UNVERIFIED"
    elif reason == "false_production_permission":
        review["production_dispatch_authorized"] = True
    elif reason == "missing_audit":
        audited.pop()
    elif reason == "missing_variant":
        variants.pop()
    with pytest.raises(ValueError):
        packages.compile_bundle(ep, staged, variants, review)
