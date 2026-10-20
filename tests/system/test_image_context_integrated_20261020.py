"""No-provider end-to-end regression: frozen authority survives Luna rewrite."""
from __future__ import annotations
import hashlib
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"episodes/_system"))
from image_payload_controller import _build_validated_request
from codex_subscription_image import payload_transport_prompt
from image_payload_request import request_fingerprint


def _build():
    original="P01在社区登记台签领四件物品"
    locked=("RESOLVED FRAME CONTRACT | frame=02 | sha256="+"f"*64+
        "\n[CHARACTER / POV CONTRACT]\nP01男性，手机摄影者，仅第一人称\n"+
        "[SCENE-AWARE WARDROBE]\nP01白色短袖\n"+
        "[CAPTURE EVENT]\nP01在服务台左侧持机\n"+
        "[FRAME DIRECTIVE]\n签领过程")
    hashes={field:"a"*64 for field in
        ("authority_input_sha256","source_prompt_sha256",
         "frame_contract_sha256","visual_contract_sha256")}
    result=_build_validated_request(
        ep=ROOT/"episodes", identity={
            "episode_id":"00_独立篇/测试","logical_asset_key":"00_独立篇/测试/frame-02",
            "frame_id":"02",**hashes},
        fields={"canvas":{"width":1024,"height":1280,"aspect_ratio":"4:5"},
                "references":[]},
        binding={"model":"gpt-6-luna","reasoning_effort":"high",
                 "policy_version":"v1","model_policy_sha256":"a"*64},
        payload={"model":"gpt-image-2.5-flare","quality":"high"},
        call_id="imgctrl-unit",controller_output={"scene_prompt":"社区柜台的一张生活照"},
        controller_input={"source_scene_prompt":original,
            "frame_prompt_contract":locked,"visual_contract":"profile=other"},
    )
    return result


def test_controller_cannot_erase_pov_wardrobe_or_event_from_final_tool_input():
    request=_build()
    prompt=payload_transport_prompt(request,"1024x1280",0)
    for fact in ("P01男性","手机摄影者","P01白色短袖","签领过程"):
        assert fact in prompt
    assert request["request_fingerprint"]==request_fingerprint(request)


def test_controller_output_same_but_frozen_contract_different_changes_wire_request():
    from image_payload_hard_constraints import inject
    old=inject("社区照片","[CHARACTER / POV CONTRACT]\nP01白衣")
    new=inject("社区照片","[CHARACTER / POV CONTRACT]\nP01黑衣")
    assert old!=new
    assert hashlib.sha256(old.encode()).hexdigest()!=hashlib.sha256(new.encode()).hexdigest()
