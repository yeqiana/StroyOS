"""CAS stage of EP14 render revisions must never unblock Provider-refused originals."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "episodes/_system"))
import production_ep14_render_queue_stage as staging


def sh(i: str) -> str:
    return hashlib.sha256(i.encode("utf8")).hexdigest()


@pytest.fixture
def live(monkeypatch, tmp_path):
    import production_ep14_render_relock_preflight as pre
    import scheduler_core
    ep = tmp_path / "episode"
    ep.mkdir()
    rows = []
    materials = []
    for frame in sorted(staging.FRAMES):
        original_sha = sh(f"original-frame-{frame}")
        row = {
            "id": f"item-{frame}", "frame": frame, "kind": "original",
            "scope": "batch", "status": "external_blocked",
            "prompt_file": f"original/{frame:02d}.txt", "attempts": 2,
            "requires_content_revision": True,
            "no_automatic_original_prompt_retry": True,
            "prompt_package": {
                "package_sha256": sh(f"original-pkg-{frame}"),
                "frame_contract_sha256": original_sha,
                "scene_prompt_sha256": sh(f"unsafe-original-scene-{frame}"),
            },
        }
        rows.append(row)
        worker_sha = sh(f"reviewed-worker-{frame}")
        variant_sha = sh(f"reviewed-variant-{frame}")
        materials.append({
            "frame": frame,
            "original_frame_contract_sha256": original_sha,
            "producer_preview_prompt_sha256": worker_sha,
            "render_variant_sha256": variant_sha,
            "reviewed_render_prompt_package_proposal_sha256": sh(f"new-pkg-{frame}"),
            "production_dispatch_authorized": False,
            "verified_text_review_receipt": {
                "status": "TEXT_REVIEW_VERIFIED_NOT_FINAL_CONTROLLER_APPROVAL",
                "reviewed_worker_prompt_sha256": worker_sha,
            },
            "verified_noncanonical_controller_draft_receipt": {
                "status": "REVIEWED_PREVIEW_ONLY_NOT_CANONICAL",
                "production_dispatch_authorized": False,
                "render_variant_sha256": variant_sha,
                "controller_scene_sha256": sh(f"scene-preview-{frame}"),
            },
        })
    other = {
        "id": "untouched-generated-asset", "scope": "batch",
        "frame": 30, "kind": "original", "status": "generated",
    }
    queue = {
        "schema_version": 1, "created_at": "unchanged", "updated_at": "before",
        "items": [*rows, other], "waves": [{"existing": 1}],
    }
    data = {"q": deepcopy(queue), "saves": 0}
    report = {
        "status": "REVIEW_HANDOFF_READY_NOT_PRODUCTION_READY",
        "independent_text_review_verified": True,
        "noncanonical_controller_output_review_verified": True,
        "production_dispatch_authorized": False,
        "canonical_render_prompt_packages_activated": False,
        "reviewed_render_prompt_package_proposal_status":
            "THREE_FRAME_REVIEWED_PACKAGE_PROPOSAL_NOT_CANONICAL",
        "reviewed_render_prompt_package_bundle_sha256": sh("bundle"),
        "frames": materials,
    }
    monkeypatch.setattr(pre, "inspect_episode", lambda path: deepcopy(report))
    monkeypatch.setattr(scheduler_core, "load_queue", lambda path: deepcopy(data["q"]))
    def save(path, candidate):
        data["saves"] += 1
        data["q"] = deepcopy(candidate)
        data["q"]["updated_at"] = "after"
    monkeypatch.setattr(scheduler_core, "save_queue", save)
    @contextmanager
    def tx(path):
        yield
    monkeypatch.setattr(scheduler_core, "queue_transaction", tx)
    return ep, data, report, queue


def stage_once(ep):
    proposal = staging.plan(ep)
    return staging.stage(
        ep,
        expected_queue_sha256=proposal["expected_queue_sha256"],
        expected_render_bundle_sha256=proposal["render_bundle_sha256"],
    )


def test_all_three_sha_metadata_committed_together_and_originals_untouched(live):
    ep, data, report, initial = live
    p = staging.plan(ep)
    assert p["status"] == "READY_TO_STAGE_BUT_NOT_TO_PRODUCE"
    assert data["saves"] == 0
    result = stage_once(ep)
    assert result["status"] == "STAGED_BLOCKED_NOT_CANONICAL"
    assert result["frames"] == [9, 29, 48]
    assert result["paid_attempts_reserved"] == 0
    assert result["production_dispatch_authorized"] is False
    assert data["saves"] == 1
    q = data["q"]
    assert q[staging.QUEUE_KEY]["binding_sha256"] == result["stage_binding_sha256"]
    assert q[staging.QUEUE_KEY]["canonical_prompt_packages_activated"] is False
    assert q["items"][-1] == initial["items"][-1]
    assert q["waves"] == initial["waves"]
    for original, staged in zip(initial["items"][:3], q["items"][:3]):
        assert {k: v for k, v in staged.items() if k != staging.ROW_KEY} == original
        assert staged["status"] == "external_blocked"
        assert staged["requires_content_revision"] is True
        assert staged["no_automatic_original_prompt_retry"] is True
        assert staged["prompt_package"] == original["prompt_package"]
        assert staged[staging.ROW_KEY]["status"] == "STAGED_BLOCKED"
        assert staged[staging.ROW_KEY]["production_dispatch_authorized"] is False


def test_second_stage_is_idempotent_and_does_not_rewrite_queue(live):
    ep, data, _, _ = live
    first = stage_once(ep)
    assert data["saves"] == 1
    p = staging.plan(ep)
    assert p["already_staged"] is True
    second = stage_once(ep)
    assert second["status"] == "ALREADY_STAGED_BLOCKED"
    assert second["idempotent"] is True
    assert second["stage_binding_sha256"] == first["stage_binding_sha256"]
    assert data["saves"] == 1


@pytest.mark.parametrize("error", [
    "queue_cas", "bundle_cas", "queue_no_flag", "queue_not_blocked",
    "queue_changed_package", "queue_duplicate", "partial_stage",
    "review_unverified", "controller_unverified", "wrong_source_sha",
    "controller_not_bound", "fake_dispatch_grant",
])
def test_unsafe_or_stale_queue_state_never_writes(live, error):
    ep, data, report, original = live
    p = staging.plan(ep)
    queue_sha = p["expected_queue_sha256"]
    bundle_sha = p["render_bundle_sha256"]
    if error == "queue_cas":
        queue_sha = "1" * 64
    elif error == "bundle_cas":
        bundle_sha = "2" * 64
    elif error == "queue_no_flag":
        data["q"]["items"][0]["requires_content_revision"] = False
    elif error == "queue_not_blocked":
        data["q"]["items"][0]["status"] = "queued"
    elif error == "queue_changed_package":
        data["q"]["items"][0]["prompt_package"]["package_sha256"] = "0" * 64
    elif error == "queue_duplicate":
        data["q"]["items"].append(deepcopy(data["q"]["items"][0]))
    elif error == "partial_stage":
        data["q"]["items"][0][staging.ROW_KEY] = {"status": "STAGED_BLOCKED"}
    elif error == "review_unverified":
        report["independent_text_review_verified"] = False
        # The mock reads 'report' via deep copy on each pass.
    elif error == "controller_unverified":
        report["noncanonical_controller_output_review_verified"] = False
    elif error == "wrong_source_sha":
        report["frames"][0]["original_frame_contract_sha256"] = "1" * 64
    elif error == "controller_not_bound":
        report["frames"][1]["verified_noncanonical_controller_draft_receipt"]["render_variant_sha256"] = "0" * 64
    elif error == "fake_dispatch_grant":
        report["production_dispatch_authorized"] = True
    with pytest.raises(staging.StageDenied):
        staging.stage(ep, expected_queue_sha256=queue_sha,
                      expected_render_bundle_sha256=bundle_sha)
    assert data["saves"] == 0


def test_staged_metadata_never_overrides_image_worker_safety_refusal(live, monkeypatch):
    ep, data, _, _ = live
    stage_once(ep)
    import image_worker_pool
    monkeypatch.setattr(image_worker_pool.production_native_batch_followon,
                        "_is_ep14", lambda path: True)
    for item in data["q"]["items"][:3]:
        assert image_worker_pool._content_revision_dispatch_denied(ep, item) is True
