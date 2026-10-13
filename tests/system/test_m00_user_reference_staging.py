#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fast offline M00 user capture and complete reference evidence regression."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "episodes/_system"), str(ROOT / "scripts")]
import image_scheduler
import image_worker_pool
import production_ledger_core
import production_ledger_run
import storyos_m00_reference_stage as stage
import user_visual_reference_contract as overlay


def _write_inputs(tmp_path):
    repo = tmp_path / "repo"
    srcdir = tmp_path / "source"
    ep = repo / "episodes/e"
    ep.mkdir(parents=True)
    srcdir.mkdir()
    from PIL import Image
    path = srcdir / "original.png"
    Image.new("RGB", (25, 35), (128, 120, 100)).save(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"schema_version": 1, "uploads": [{
        "filename": "original.png", "sha256": digest,
        "source_attachment_id": "file_exact_user_attachment",
    }]}), encoding="utf-8")
    return repo, ep, srcdir, manifest, digest


def test_preflight_does_not_write_or_bind_episode(tmp_path):
    repo, ep, source, manifest, digest = _write_inputs(tmp_path)
    output = stage.prepare(source, manifest, repo, apply=False)
    assert output["status"] == "PREFLIGHT_ONLY"
    assert output["items"][0]["sha256"] == digest
    assert not (repo / stage.TARGET_REL).exists()
    assert not (ep / "meta").exists()
    assert output["references_bound_to_episode"] is False


def test_stage_verifies_original_and_provenance(tmp_path, monkeypatch):
    repo, ep, source, manifest, digest = _write_inputs(tmp_path)
    out = stage.prepare(source, manifest, repo, apply=True)
    item = out["items"][0]
    assert hashlib.sha256((repo / item["path"]).read_bytes()).hexdigest() == digest
    monkeypatch.setattr(overlay, "ROOT", repo)
    monkeypatch.setattr(overlay.episode_contract_persistence, "load_latest", lambda *_a, **_k: {"items": [item]})
    assert overlay.approved_user_capture_style(ep, item["path"])
    assert production_ledger_core.approved_capture_style_source(ep, item["path"]) == "explicit_user_upload_capture_style"
    refs = overlay.references_for_frame(ep, 1, "batch")
    assert refs[0]["path"] == item["path"]
    assert refs[0]["sha256"] == digest
    assert refs[0]["kind"] == "capture_style"


def test_unapproved_or_generated_reference_is_rejected(tmp_path, monkeypatch):
    repo, ep, source, manifest, digest = _write_inputs(tmp_path)
    item = stage.prepare(source, manifest, repo, apply=True)["items"][0]
    monkeypatch.setattr(overlay, "ROOT", repo)
    template = {"items": [dict(item)]}
    monkeypatch.setattr(overlay.episode_contract_persistence, "load_latest", lambda *_a, **_k: template)
    for field, invalid in (
        ("origin", "generated_frame"), ("reference_use", "copy_user_actions"),
        ("source_attachment_id", ""), ("sha256", "a" * 64),
    ):
        row = dict(item, **{field: invalid})
        template["items"] = [row]
        assert not overlay.approved_user_capture_style(ep, item["path"])
    generated = repo / "episodes/e/media/approved/01.png"
    generated.parent.mkdir(parents=True, exist_ok=True)
    generated.write_bytes((repo / item["path"]).read_bytes())
    template["items"] = [dict(item, path="episodes/e/media/approved/01.png")]
    assert not overlay.approved_user_capture_style(ep, template["items"][0]["path"])


def test_missing_source_or_wrong_sha_is_blocked(tmp_path):
    repo, ep, source, manifest, digest = _write_inputs(tmp_path)
    contents = json.loads(manifest.read_text(encoding="utf-8"))
    contents["uploads"][0]["sha256"] = "0" * 64
    manifest.write_text(json.dumps(contents), encoding="utf-8")
    import pytest
    with pytest.raises(ValueError, match="SHA_MISMATCH"):
        stage.prepare(source, manifest, repo, apply=True)
    assert not (repo / stage.TARGET_REL).exists()


def _attempt(paths):
    return {"request": {"references": [
        {"path": p, "sha256": "a" * 64, "kind": "capture_style"} for p in paths
    ]}, "reference_execution": {}}


def _receipt(paths):
    return {"references": [
        {"path": p, "sha256": "a" * 64, "order": i + 1}
        for i, p in enumerate(paths)
    ], "generation_route": "codex_subscription"}


def test_reference_all_sent_matches_exactly():
    paths = ["assets/id.png", ".storyos/user-visual-references/capture.png"]
    attempt = _attempt(paths)
    full = production_ledger_run.merge_provider_reference_evidence(
        attempt, _receipt(paths), {"sha256": "b" * 64})
    assert full["verified"] and len(full["selected_references"]) == 2
    partial = production_ledger_run.merge_provider_reference_evidence(
        attempt, _receipt(paths[:1]), {"sha256": "b" * 64})
    assert not partial["verified"] and partial["passed_to_provider"]
    extra = production_ledger_run.merge_provider_reference_evidence(
        attempt, _receipt(paths + ["unexpected.png"]), {"sha256": "b" * 64})
    assert not extra["verified"]
    duplicate = production_ledger_run.merge_provider_reference_evidence(
        attempt, _receipt(paths[:1] * 2), {"sha256": "b" * 64})
    assert not duplicate["verified"]
    drifted = _receipt(paths)
    drifted["references"][1]["sha256"] = "f" * 64
    assert not production_ledger_run.merge_provider_reference_evidence(
        attempt, drifted, {"sha256": "b" * 64})["verified"]


def test_user_reference_still_respects_two_slot_identity_priority():
    base = [{"path": "P01.png", "kind": "identity", "role": "P01"},
            {"path": "prop.png", "kind": "prop"}]
    style = [{"path": ".storyos/user-visual-references/capture.png", "kind": "capture_style"}]
    refs = image_scheduler._merge_execution_references(base, style)
    assert [r["kind"] for r in refs] == ["identity", "capture_style"]

def test_payload_blocks_sha_drift_between_enqueue_and_controller(tmp_path):
    import pytest
    repo, ep, source, manifest, digest = _write_inputs(tmp_path)
    item = stage.prepare(source, manifest, repo, apply=True)["items"][0]
    dest = repo / item["path"]
    refs = [dest]
    expected = [item]
    validated = image_worker_pool._payload_reference_evidence(ep, repo, refs, expected)
    assert validated[0]["sha256"] == digest
    with pytest.raises(ValueError, match="DECLARED_PATH_MISMATCH"):
        image_worker_pool._payload_reference_evidence(ep, repo, refs, [dict(item, path="wrong.png")])
    with pytest.raises(ValueError, match="DECLARATION_COUNT_MISMATCH"):
        image_worker_pool._payload_reference_evidence(ep, repo, refs, [])
    # Disallow replacing an image with different bytes after the queue was frozen.
    dest.write_bytes(b"changed after enqueue")
    with pytest.raises(ValueError, match="SOURCE_SHA_DRIFT"):
        image_worker_pool._payload_reference_evidence(ep, repo, refs, expected)
