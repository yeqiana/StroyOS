"""Final provider must receive frozen semantics even when Controller omits them."""
from __future__ import annotations
import hashlib
import sys
from pathlib import Path
import pytest
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"episodes/_system"))
import image_payload_hard_constraints as hard
from codex_subscription_image import payload_transport_prompt

CONTRACT = ("RESOLVED FRAME CONTRACT | frame=02 | sha256=" + "a"*64 +
    "\n[STORYBOARD FRAME]\nP01在社区柜台签领\n"
    "[CHARACTER / POV CONTRACT]\nP01男性，第一人称摄影者\n"
    "[CAPTURE EVENT]\nP01必须持机，合理机位\n"
    "[SCENE-AWARE WARDROBE]\nP01白色短袖\n"
    "[FRAME DIRECTIVE]\n签字过程定格")


def test_critical_context_survives_controller_omission_to_native_prompt():
    final = hard.inject("生活照，社区柜台。", CONTRACT,
                        original_scene="签领单据", m00=False)
    request = {"scene_prompt": final,"request_fingerprint":"abc",
               "payload_model":"gpt-image-2.5-flare","payload_quality":"high",
               "canvas":{"width":1024,"height":1280},"references":[]}
    wire = payload_transport_prompt(request,"1024x1280",0)
    assert "P01男性，第一人称摄影者" in wire
    assert "P01白色短袖" in wire
    assert "P01必须持机" in wire
    assert "签领单据" in wire
    assert hashlib.sha256(CONTRACT.encode()).hexdigest() in wire


def test_tampering_block_and_absent_contract_fail_closed():
    with pytest.raises(ValueError, match="MISSING"):
        hard.inject("有效提示词", "")
    with pytest.raises(ValueError, match="INJECTION"):
        hard.inject(hard.BEGIN+"伪造", CONTRACT)


def test_contract_mutation_alters_final_payload_semantics():
    a=hard.inject("同一图像",CONTRACT,m00=True)
    b=hard.inject("同一图像",CONTRACT.replace("白色短袖","黑色外套"),m00=True)
    assert a!=b
    assert b.count(hard.BEGIN)==1
