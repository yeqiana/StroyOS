from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[2]
SYSTEM=ROOT/"episodes"/"_system"
if str(SYSTEM) not in sys.path:
    sys.path.insert(0,str(SYSTEM))

import locked_story_prompt_authoring as fast
import production_prompt_materializer as mat


def _board(ep, count=25):
    p=ep/"docs/storyboard.md"
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text("# user-locked storyboard\n\n| 帧 | 场景与动作 | 叙事功能 |\n|---|---|---|\n"+
        "".join(f"| {i:02d} | 第{i:02d}帧唯一独立场景：真实乡村生活、日常可验证的物件。 | 叙事信息增量{i:02d} |\n"
                for i in range(1,count+1)),encoding="utf-8")
    return p


def test_locked_markdown_table_extracts_exactly_25_non_generic_frames(monkeypatch,tmp_path):
    board=_board(tmp_path)
    monkeypatch.setattr(mat.frame_contract,"artifact_paths",lambda ep:(tmp_path/"docs/story.md",board))
    scenes=mat.locked_table_beats(tmp_path,expected_count=25)
    assert len(scenes)==25
    assert scenes[1]!=scenes[25]
    first=mat.prompt_for_contract({"frame":"01","storyboard_frame":{"text":""}},exact_scene=scenes[1])
    assert "第01帧唯一独立场景" in first
    assert "Frame01 按锁定分镜事件自然发生" not in first
    assert len(first)<=mat.MAX_CHARS and len(first.encode("utf-8"))<=mat.MAX_BYTES


def test_reject_missing_frame_even_if_whole_storyboard_available(monkeypatch,tmp_path):
    board=_board(tmp_path,count=24)
    monkeypatch.setattr(mat.frame_contract,"artifact_paths",lambda ep:(tmp_path/"docs/story.md",board))
    with pytest.raises(ValueError,match="frame mismatch"):
        mat.locked_table_beats(tmp_path,expected_count=25)


@pytest.mark.parametrize("count", [25, 48])
def test_exact_locked_source_generates_all_packages_without_codex(monkeypatch,tmp_path,count):
    board=_board(tmp_path,count=count)
    monkeypatch.setattr(mat.frame_contract,"artifact_paths",lambda ep:(tmp_path/"docs/story.md",board))
    monkeypatch.setattr(mat.frame_contract,"frame_count",lambda ep:count)
    monkeypatch.setattr(mat.frame_contract,"verify_all",lambda ep:[])
    monkeypatch.setattr(fast.preproduction_handoff,"verify",lambda ep:[])
    monkeypatch.setattr(fast.runtime_request,"authority_for_episode",lambda ep:{
        "story_input":{"mode":"locked_story","allow_structure_rewrite":False}
    })
    monkeypatch.setattr(mat.frame_contract,"compile_frame",lambda ep,frame,write_cache=False:{
        "frame":f"{int(frame):02d}","contract_sha256":f"{int(frame):064x}","storyboard_frame":{"text":""}
    })
    def fake_compile(ep,frame,prompt_file,write=True):
        import hashlib
        b=Path(prompt_file).read_bytes()
        return {"frame_contract_sha256":f"{int(frame):064x}",
                "scene_prompt_sha256":hashlib.sha256(b).hexdigest(),
                "package_sha256":hashlib.sha256(b+str(frame).encode()).hexdigest()}
    monkeypatch.setattr(fast.prompt_package,"compile_frame",fake_compile)
    written=[]
    monkeypatch.setattr(fast.runtime_atomic_store,"atomic_write_json",lambda p,data:written.append(data))
    proof=fast.run(tmp_path)
    assert proof["status"]=="PASS" and proof["model_execution_dispatched"] is False
    assert len(proof["frame_packages"])==count
    assert len(list((tmp_path/"prompts/production").glob("*.txt")))==count
    assert len(written)==1
    second=fast.run(tmp_path)
    assert second["created_count"]==0 and second["reused_count"]==count


def test_non_locked_authority_cannot_use_deterministic_shortcut(monkeypatch,tmp_path):
    monkeypatch.setattr(fast.runtime_request,"authority_for_episode",lambda ep:{
        "story_input":{"mode":"auto_create","allow_structure_rewrite":True}
    })
    assert not fast.applicable(tmp_path)
    with pytest.raises(RuntimeError,match="only accepts"):
        fast.run(tmp_path)
