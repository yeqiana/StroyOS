"""The alternative render preview has NO authority to dispatch paid images."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import Mock
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/"episodes/_system")]
import production_ep14_visual_treatment_preview as visual


@pytest.fixture
def local_fixture(tmp_path,monkeypatch):
    ep=tmp_path/"episodes"/"00_独立篇"/"14_深渊疗愈所_第一集_净土生命还原"
    ep.mkdir(parents=True)
    monkeypatch.setattr(visual,"EP",ep)
    mocked={}
    for frame in (9,29,48):
        original=f"LOCKED-ORIGINAL-FRAME-{frame}-WITH-OLD-INSTRUCTIONS"
        old_scene=f"original prompt {frame}".encode("utf8")
        path=ep/"prompts"/"production"/f"{frame:02d}.txt"
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(old_scene)
        old_contract="a"*63+str(frame%10)
        old_excerpt=hashlib.sha256(original.encode("utf8")).hexdigest()
        old_scene_sha=hashlib.sha256(old_scene).hexdigest()
        monkeypatch.setitem(visual.ORIGINAL,frame,(old_contract,old_scene_sha,old_excerpt))
        mocked[frame]={
            "contract_sha256":old_contract,
            "storyboard_frame":{"text":original,"sha256":old_excerpt},
            "prompt_contract":(
                f"RESOLVED FRAME CONTRACT | frame={frame:02d} | sha256={old_contract}\n"
                "This derived contract is mandatory.\n"
                "[STORYBOARD FRAME]\n"+original+"\n\n[VISUAL DNA]\n"
                "Unchanged world identity, camera and light notes.\n"),
        }
    resolver=Mock(side_effect=lambda ep,f,write_cache=False:mocked[f])
    monkeypatch.setattr(visual.frame_contract,"compile_frame",resolver)
    return ep,mocked,resolver


@pytest.mark.parametrize("frame",[9,29,48])
def test_preview_removes_old_storyboard_prompt_without_legacy_leak(frame,local_fixture):
    ep,contracts,resolver=local_fixture
    before=json.dumps(contracts,sort_keys=True,ensure_ascii=False)
    out=visual.compile_candidate(ep,frame)
    assert out["review_approved"] is False
    assert out["production_dispatch_authorized"] is False
    assert out["requires_new_canonical_prompt_package"] is True
    assert out["requires_paid_attempt_2_risk_ack"] is True
    text=out["proposed_render_contract_text"]
    assert contracts[frame]["storyboard_frame"]["text"] not in text
    assert "[VISUAL DNA]\nUnchanged world identity" in text
    assert "[ALTERNATIVE VISUAL TREATMENT, REVIEW PENDING]" in text
    assert f"sha256={out['proposed_render_contract_sha256']}" in text
    assert out["old_frame_contract_sha256"]==contracts[frame]["contract_sha256"]
    assert json.dumps(contracts,sort_keys=True,ensure_ascii=False)==before
    resolver.assert_called_with(ep,frame,write_cache=False)


def test_hash_stability_scope_and_zero_side_effects(local_fixture):
    ep,contracts,resolver=local_fixture
    first=visual.compile_all(ep)
    second=visual.compile_all(ep)
    assert first==second
    assert first["review_status"]=="PENDING"
    assert first["image_calls"]==first["attempts_reserved"]==first["sql_writes"]==0
    assert first["production_dispatch_authorized"] is False
    assert [x["frame"] for x in first["frames"]]==[9,29,48]
    with pytest.raises(ValueError,match="EXACT_EP14_FRAME_SCOPE_REQUIRED"):
        visual.compile_candidate(ep,20)
    with pytest.raises(ValueError,match="EXACT_EP14_FRAME_SCOPE_REQUIRED"):
        visual.compile_candidate(ep.parent/"13_other",9)


def test_old_source_tamper_prevents_preview(local_fixture):
    ep,contracts,resolver=local_fixture
    path=ep/"prompts/production/09.txt"
    path.write_text("changed",encoding="utf8")
    with pytest.raises(ValueError,match="IMMUTABLE_SOURCE"):
        visual.compile_candidate(ep,9)
    path.write_text("original prompt 9",encoding="utf8")
    contracts[29]["contract_sha256"]="0"*64
    with pytest.raises(ValueError,match="IMMUTABLE_SOURCE"):
        visual.compile_candidate(ep,29)


def test_old_excerpt_in_other_section_fails_closed(local_fixture):
    ep,contracts,resolver=local_fixture
    excerpt=contracts[9]["storyboard_frame"]["text"]
    contracts[9]["prompt_contract"]+=f"\n[OTHER]\n{excerpt}\n"
    with pytest.raises(ValueError,match="OLD_REJECTED_STORYBOARD_LEAK"):
        visual.compile_candidate(ep,9)


def test_no_missing_section_or_unexpected_contract_version(local_fixture):
    ep,contracts,resolver=local_fixture
    contracts[48]["prompt_contract"]=contracts[48]["prompt_contract"].replace(
        "[STORYBOARD FRAME]","[SHOTBOARD]")
    with pytest.raises(ValueError,match="RENDER_PROMPT_LAYOUT_UNRECOGNIZED"):
        visual.compile_candidate(ep,48)
