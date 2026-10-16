"""同一段 scene prompt 遇到等价 Frame Contract 投影不得错误阻断。"""
from pathlib import Path
import hashlib
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "episodes/_system"))
import prompt_package


def _setup(monkeypatch, tmp_path, *, equivalent):
    scene = "这是一段已经从锁定分镜生成的生活场景。"
    prompt = tmp_path / "02.txt"
    prompt.write_text(scene + "\n", encoding="utf-8")
    contract = {
        "frame": "02", "contract_sha256": "b" * 64,
        "storyboard_frame": {"text": scene}, "prompt_contract": "verified",
    }
    previous = {
        "frame_contract_sha256": "a" * 64,
        "scene_prompt_sha256": hashlib.sha256(scene.encode("utf-8")).hexdigest(),
    }
    evidence_calls = []
    monkeypatch.setattr(prompt_package.frame_contract, "compile_frame",
                        lambda ep, frame, write_cache: contract)
    monkeypatch.setattr(prompt_package.prompt_package_persistence, "load_latest",
                        lambda ep, frame: previous)
    monkeypatch.setattr(prompt_package.image_model_policy, "for_episode",
                        lambda ep: {"model": "mock", "quality": "high"})
    def verify(ep, frame, old_sha, *, current):
        evidence_calls.append((ep, frame, old_sha, current))
        return equivalent
    monkeypatch.setattr(prompt_package.frame_contract,
                        "equivalent_to_current", verify)
    return prompt, contract, previous, evidence_calls


def test_sha_equivalent_projection_reuses_locked_prompt_without_dispatch(monkeypatch, tmp_path):
    prompt, contract, previous, calls = _setup(monkeypatch, tmp_path, equivalent=True)
    result = prompt_package.compile_frame(tmp_path, 2, prompt, write=False)
    assert result["scene_prompt_sha256"] == previous["scene_prompt_sha256"]
    assert result["frame_contract_sha256"] == contract["contract_sha256"]
    assert calls == [(tmp_path, 2, previous["frame_contract_sha256"], contract)]
    assert not list(tmp_path.rglob("*.json"))


def test_meaningful_contract_drift_never_borrows_old_scene(monkeypatch, tmp_path):
    prompt, contract, previous, calls = _setup(monkeypatch, tmp_path, equivalent=False)
    with pytest.raises(ValueError, match="PROMPT_SOURCE_DRIFT"):
        prompt_package.compile_frame(tmp_path, 2, prompt, write=False)
    assert calls == [(tmp_path, 2, previous["frame_contract_sha256"], contract)]
    assert not list(tmp_path.rglob("*.json"))
