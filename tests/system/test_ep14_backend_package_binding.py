"""Backend EP14 content-revision authority must never read the refused old prompt."""
from argparse import Namespace
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "episodes/_system"))
import codex_subscription_image as backend
import production_ep14_render_queue_stage as stage
import production_native_batch_followon as followon
import scheduler_core
import logical_asset_identity
import prompt_package


@pytest.fixture
def fake_authority(tmp_path, monkeypatch):
    ep = tmp_path / "episodes" / "00_独立篇" / "14_深渊疗愈所_第一集_净土生命还原"
    ep.mkdir(parents=True)
    monkeypatch.setattr(followon, "_is_ep14", lambda p: Path(p).resolve() == ep.resolve())
    prompt = ep / "09.txt"
    prompt.write_text("OLD PROVIDER-SAFETY-REFUSED STORY CONTENT", encoding="utf8")
    item = {"id": "f09-locked-request", "frame": 9, "scope": "batch",
            "status": "external_blocked", "requires_content_revision": True,
            "no_automatic_original_prompt_retry": True}
    source = {
        "package_sha256": "a" * 64,
        "frame_contract_sha256": "b" * 64,
        "scene_prompt_sha256": "c" * 64,
        "scene_prompt": "Safe separately reviewed replacement",
        "frame_prompt_contract": "REVIEWED REVISED RENDER CONTRACT",
        "storyboard_source": {
            "frame": "09", "sha256": "d" * 64,
            "authority": "LOCKED_ORIGINAL_STORYBOARD_HASH_ONLY",
            "render_original_text_injected": False,
        },
        "canonical_activation": True,
        "production_dispatch_authorized": True,
    }
    request = {"logical_asset_key": logical_asset_identity.frame_asset_key(ep, 9),
               "frame_contract_sha256": source["frame_contract_sha256"]}
    monkeypatch.setattr(scheduler_core, "load_queue", lambda path: {"items": [item]})
    # An attempt to read the refused original should always explode.
    monkeypatch.setattr(prompt_package, "compile_frame",
                        lambda *args, **kw: pytest.fail("OLD_REFUSED_PROMPT_RECOMPILED"))
    args = Namespace(frame="09", _queue_item_id=item["id"],
                     _activated_render_package=source.copy(),
                     _canonical_payload_request=request.copy())
    return ep, prompt, item, source, args, monkeypatch


def test_refused_original_will_never_be_read_by_ep14_backend(fake_authority):
    ep, prompt, item, source, args, monkeypatch = fake_authority
    # Existing preview-only stage cannot authorize dispatch.
    monkeypatch.setattr(stage, "load_for_dispatch",
                        lambda ep, row: (_ for _ in ()).throw(
                            stage.StageDenied("STAGED_BLOCKED_NOT_CANONICAL")))
    with pytest.raises(backend.BackendError, match="NOT_ACTIVATED"):
        backend._effective_frame_prompt_package(ep, args, prompt)


@pytest.mark.parametrize("missing", [
    "missing_item", "missing_package", "missing_request", "wrong_item",
    "wrong_package", "wrong_scene", "wrong_frame_contract", "wrong_request_asset",
    "wrong_request_contract", "missing_activation", "no_dispatch_grant",
    "original_story_text_leaked", "fake_original_story_identity",
])
def test_bad_worker_or_backend_input_denied_without_fallback(fake_authority, missing):
    ep, prompt, item, source, args, monkeypatch = fake_authority
    monkeypatch.setattr(stage, "load_for_dispatch", lambda ep, row: source)
    if missing == "missing_item":
        args._queue_item_id = None
    elif missing == "missing_package":
        args._activated_render_package = None
    elif missing == "missing_request":
        args._canonical_payload_request = None
    elif missing == "wrong_item":
        args._queue_item_id = "unknown"
    elif missing == "wrong_package":
        args._activated_render_package["package_sha256"] = "0" * 64
    elif missing == "wrong_scene":
        args._activated_render_package["scene_prompt"] = "old unsafe scene"
    elif missing == "wrong_frame_contract":
        args._activated_render_package["frame_contract_sha256"] = "0" * 64
    elif missing == "wrong_request_asset":
        args._canonical_payload_request["logical_asset_key"] = "wrong"
    elif missing == "wrong_request_contract":
        args._canonical_payload_request["frame_contract_sha256"] = "0" * 64
    elif missing == "missing_activation":
        source["canonical_activation"] = False
    elif missing == "no_dispatch_grant":
        source["production_dispatch_authorized"] = False
    elif missing == "original_story_text_leaked":
        source["storyboard_source"]["text"] = "OLD PROVIDER-SAFETY-REFUSED STORY CONTENT"
    elif missing == "fake_original_story_identity":
        source["storyboard_source"]["render_original_text_injected"] = True
    with pytest.raises(backend.BackendError):
        backend._effective_frame_prompt_package(ep, args, prompt)


def test_verified_canonical_variant_is_backend_source_not_disk_original(fake_authority):
    ep, prompt, item, source, args, monkeypatch = fake_authority
    # An explicit mock models the *future* formal activation authority.
    # The live implementation still raises StageDenied until approved.
    monkeypatch.setattr(stage, "load_for_dispatch", lambda ep, row: source)
    approved = backend._effective_frame_prompt_package(ep, args, prompt)
    assert approved is source
    assert "OLD PROVIDER-SAFETY-REFUSED" not in approved["scene_prompt"]
    assert approved["scene_prompt_sha256"] == "c" * 64


def test_normal_episode_backend_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(followon, "_is_ep14", lambda p: False)
    called = []
    def compile_original(ep, frame, file):
        called.append(frame)
        return {"package_sha256": "f" * 64}
    monkeypatch.setattr(prompt_package, "compile_frame", compile_original)
    result = backend._effective_frame_prompt_package(
        tmp_path, Namespace(frame="07"), tmp_path / "07.txt")
    assert result["package_sha256"] == "f" * 64
    assert called == [7]


def test_attempt_authority_uses_effective_controller_package_not_legacy_queue(monkeypatch):
    import image_worker_pool as worker
    def resolve(role, *, episode):
        if role == "image.controller":
            return {
                "model": "gpt-6-luna", "profile": "EP14",
                "reasoning_effort": "high", "policy_version": 1,
                "model_policy_sha256": "e" * 64,
            }
        return {"model": "gpt-image-2.5-flare", "quality": "high"}
    monkeypatch.setattr(worker.model_policy, "resolve", resolve)
    old_package = {"package_sha256": "1" * 64, "frame_contract_sha256": "2" * 64}
    actual = {"package_sha256": "a" * 64, "frame_contract_sha256": "2" * 64,
              "render_variant_sha256": "f" * 64}
    item = {"id": "ep14-09", "scope": "batch", "frame": 9,
            "prompt_package": old_package}
    ctx = worker.generation_attempt_context(
        Path("episode"), item, {"model": "gpt-image-2.5-flare", "quality": "high"},
        effective_package=actual)
    assert ctx["prompt_package_sha256"] == actual["package_sha256"]
    assert ctx["prompt_package_sha256"] != old_package["package_sha256"]
    assert ctx["render_variant_sha256"] == actual["render_variant_sha256"]
    assert ctx["frame_contract_sha256"] == old_package["frame_contract_sha256"]
    assert item["prompt_package"] == old_package


def test_legacy_attempt_context_keeps_original_package_and_schema(monkeypatch):
    import image_worker_pool as worker
    monkeypatch.setattr(worker.model_policy, "resolve",
                        lambda role, *, episode: {
                            "model": "gpt-6-luna" if role == "image.controller" else "gpt-image-2.5-flare",
                            "profile": "EP14", "reasoning_effort": "high",
                            "model_policy_sha256": "e" * 64,
                        })
    item = {"id": "normal", "scope": "batch", "prompt_package": {
        "package_sha256": "1" * 64, "frame_contract_sha256": "2" * 64,
    }}
    ctx = worker.generation_attempt_context(Path("episode"), item, {
        "model": "gpt-image-2.5-flare", "quality": "high"})
    assert ctx["prompt_package_sha256"] == "1" * 64
    assert "render_variant_sha256" not in ctx


def test_backend_guard_survives_disabled_frame_contract_switch(fake_authority, monkeypatch, tmp_path):
    ep, prompt, item, source, args, _ = fake_authority
    monkeypatch.setattr(backend.resolved_frame_contract, "required", lambda ep: False)
    monkeypatch.setattr(backend, "read_canvas", lambda ep: (1080, 1350, "4:5"))
    monkeypatch.setattr(backend, "compile_prompt_contract",
                        lambda ep: {"text": "visual profile"})
    # No Controller or Provider may run even when Frame Contract required()
    # is disabled by a broken configuration or a legacy compatibility mode.
    args = Namespace(episode_dir=ep, frame="09", prompt_file=prompt,
                     reference=[], output=tmp_path / "img.png",
                     log=tmp_path / "log.jsonl", overwrite=False)
    with pytest.raises(backend.BackendError, match="ACTIVE_QUEUE_PACKAGE"):
        backend.generate_for_frame(args)
    assert not args.output.exists()
