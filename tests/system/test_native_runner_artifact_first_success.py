"""Evidence-first native Codex image success: permanent regression from 2026-10-19 canary.

The real authenticated image call exported one 1254x1254 PNG even though its
agent_message denied success and the JSONL had no image tool event.
"""
from __future__ import annotations
import base64
import hashlib
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"episodes/_system"))
import codex_subscription_image as image
import codex_user_runner

RID="a"*32
THREAD="01a15412-710b-74d1-8fa4-16c424ed7acb"
OTHER="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
ARTIFACT=f"{THREAD}/exec-5841851e-1709-4407-9b6d-c832f72459e9.png"


def sample(tmp_path, *, artifact=ARTIFACT, thread=THREAD, request=RID, task="image",
           content=None, image_size=(1254,1254), valid=True):
    workdir=tmp_path/"story-os-image-smoke"
    location=codex_user_runner.exported_artifacts_dir(workdir) / ARTIFACT
    location.parent.mkdir(parents=True)
    if valid:
        Image.new("RGB",image_size,(190,65,35)).save(location)
    else:
        location.write_text("not an image",encoding="utf-8")
    output=(json.dumps({"type":"thread.started","thread_id":THREAD})+"\n"+
            json.dumps({"type":"item.completed","item":{"type":"agent_message",
            "text":"图像生成工具已调用一次，但未返回图片或状态信息，因此无法确认图像已生成。"}})+"\n").encode()
    receipt={"request_id":request,"returncode":0,"output_base64":base64.b64encode(output).decode(),
             "output_bytes":len(output),"output_sha256":hashlib.sha256(output).hexdigest(),
             "evidence":{"request_id":request,"task_type":task,"transport_route":"native_codex",
                         "thread_ids":[thread],"generated_artifacts":[artifact]}}
    if content: receipt.update(content)
    return workdir,location,receipt


def test_real_canary_image_overrides_doubtful_agent_text(tmp_path):
    wd,path,receipt=sample(tmp_path)
    with patch.object(codex_user_runner,"read_task_result",return_value=receipt):
        chosen=image.runner_verified_exported_candidate(wd,RID)
    assert chosen==path.resolve()
    assert image.provider_raw_candidate_viable(chosen)
    assert image.logged_backend_failure("agent_message says image unavailable; 429",
         returncode=0,candidate_valid=True,candidate_viable=True) is None


@pytest.mark.parametrize("case",[
    "wrong_request","wrong_evidence_request","wrong_task","wrong_route",
    "other_thread","traversal","missing_export","corrupt_stdout",
    "wrong_output_bytes","tool_failure","bad_image","tiny_image",
])
def test_other_request_or_wrong_artifact_never_admitted(tmp_path,case):
    wd,path,receipt=sample(tmp_path,valid=case!="bad_image",
                           image_size=(100,100) if case=="tiny_image" else (1254,1254))
    if case=="wrong_request":receipt["request_id"]="b"*32
    elif case=="wrong_evidence_request":receipt["evidence"]["request_id"]="b"*32
    elif case=="wrong_task":receipt["evidence"]["task_type"]="review"
    elif case=="wrong_route":receipt["evidence"]["transport_route"]="opencodex"
    elif case=="other_thread":receipt["evidence"]["thread_ids"]=[OTHER]
    elif case=="traversal":receipt["evidence"]["generated_artifacts"]=["../elsewhere.png"]
    elif case=="missing_export":receipt["evidence"]["generated_artifacts"]=[]
    elif case=="corrupt_stdout":receipt["output_sha256"]="0"*64
    elif case=="wrong_output_bytes":receipt["output_bytes"]=-1
    elif case=="tool_failure":receipt["returncode"]=1
    with patch.object(codex_user_runner,"read_task_result",return_value=receipt):
        assert image.runner_verified_exported_candidate(wd,RID) is None


def test_missing_receipt_never_scans_other_images(tmp_path):
    wd,path,_=sample(tmp_path)
    with patch.object(codex_user_runner,"read_task_result",return_value=None):
        assert image.runner_verified_exported_candidate(wd,RID) is None


def test_wrong_runner_request_never_uses_incidental_exported_image():
    worker=(ROOT/"episodes/_system/codex_subscription_image.py").read_text(encoding="utf-8")
    assert "runner_verified_exported_candidate(workdir, runner_request_id)" in worker


def test_provider_square_output_normalized_to_release_canvas(tmp_path):
    raw=tmp_path/"raw.png"
    target=tmp_path/"release.png"
    Image.new("RGB",(1254,1254),(170,60,50)).save(raw)
    image.normalize(raw,target,1080,1080)
    with Image.open(target) as img:
        assert img.size==(1080,1080)


def test_wrong_aspect_provider_output_requires_explicit_exception(tmp_path):
    raw=tmp_path/"raw.png"
    target=tmp_path/"portrait.png"
    Image.new("RGB",(1254,1254),(170,60,50)).save(raw)
    with pytest.raises(image.NormalizeError):
        image.normalize(raw,target,1080,1350)
    assert not target.exists()
