"""Strict direct native image producer + receipt + baseline proof tests (offline)."""
from __future__ import annotations
import base64
import hashlib
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

SYSTEM=Path(__file__).resolve().parents[2] / "episodes" / "_system"
if str(SYSTEM) not in sys.path:
    sys.path.insert(0, str(SYSTEM))

import codex_user_runner as runner
import production_native_baseline_proof as proof
import codex_subscription_image as backend

RID="a"*32
THREAD="01a16924-9ea0-7631-ac02-006ddf5a9e15"
NAME="exec-6f5a7c1e-1aed-4058-a77b-3a2014f2b896.png"

def scenario(tmp_path,monkeypatch):
    monkeypatch.setattr(runner,"ROOT",tmp_path)
    monkeypatch.setattr(runner,"bridge_required",lambda:False)
    monkeypatch.setattr(backend,"ROOT",tmp_path)
    home=tmp_path / "sandbox" / "codex-home"
    pixel=home / "generated_images" / THREAD / NAME
    pixel.parent.mkdir(parents=True)
    image=Image.new("RGB",(1122,1402),(110,120,140))
    image.save(pixel,format="PNG")
    raw=tmp_path / "episode" / "media" / "raw" / "01.png"
    raw.parent.mkdir(parents=True)
    raw.write_bytes(pixel.read_bytes())
    events=[{"type":"thread.started","thread_id":THREAD},
            {"type":"turn.started"},
            {"type":"item.completed","item":{"type":"agent_message","text":""}},
            {"type":"turn.completed"}]
    output=b"WARNING: helper alias absent\n"+b"\n".join(json.dumps(e).encode() for e in events)+b"\n"
    log=tmp_path / "episode" / "media" / "raw" / "01.jsonl"
    log.write_bytes(output)
    return home,pixel,raw,log,output

def receipt(tmp_path, archive, output):
    data={"request_id":RID,"returncode":0,"output_bytes":len(output),
          "output_sha256":hashlib.sha256(output).hexdigest(),
          "output_base64":base64.b64encode(output).decode(),
          "evidence":{"request_id":RID,"returncode":0,
                      "task_type":"image","transport_route":"native_codex",
                      "transport":"direct_codex_user_runner",**archive}}
    path=runner.task_result_path(RID)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data),encoding="utf-8")
    return path

def test_direct_producer_captures_exact_thread_before_ephemeral_cleanup(tmp_path,monkeypatch):
    home,src,raw,log,output=scenario(tmp_path,monkeypatch)
    archive=runner._archive_direct_thread_image(RID,output,{"CODEX_HOME":str(home)})
    assert archive["thread_ids"]==[THREAD]
    assert archive["generated_artifacts"]==[f"{THREAD}/{NAME}"]
    durable=runner.task_result_path(RID).parent.parent/"image-artifacts"/RID/THREAD/NAME
    assert durable.read_bytes()==src.read_bytes()
    rec=receipt(tmp_path,archive,output)
    assert proof.verify_direct_runner_archived_pixel(log,raw,RID)["proof_kind"]=="TRUSTED_NATIVE_DIRECT_THREAD_SCOPED_IMAGE_SHA"
    assert backend.runner_verified_exported_candidate(tmp_path,RID)==durable.resolve()
    # Ephemeral home must be disposable after capture without losing proof.
    src.unlink()
    assert proof.verify_direct_runner_archived_pixel(log,raw,RID) is not None
    assert rec.is_file()

@pytest.mark.parametrize("bad",["missing_thread","missing_turn","second_thread","two_pixels","symlink","bad_png"])
def test_direct_archive_fails_closed_on_ambiguous_capture(tmp_path,monkeypatch,bad):
    home,src,raw,log,output=scenario(tmp_path,monkeypatch)
    if bad=="missing_thread":
        output=b'{"type":"turn.completed"}\n'
    elif bad=="missing_turn":
        output=b'{"type":"thread.started","thread_id":"'+THREAD.encode()+b'"}\n'
    elif bad=="second_thread":
        output+=b'{"type":"thread.started","thread_id":"'+("f"*36).encode()+b'"}\n'
    elif bad=="two_pixels":
        (src.parent/"extra.png").write_bytes(src.read_bytes())
    elif bad=="symlink":
        alias=src.parent/"alias.png"
        try: alias.symlink_to(src)
        except OSError: pytest.skip("symlinks unavailable")
    elif bad=="bad_png":
        src.write_bytes(b"PNG header only")
    assert runner._archive_direct_thread_image(RID,output,{"CODEX_HOME":str(home)})=={}

@pytest.mark.parametrize("bad",["unarchived","different_raw","wrong_receipt_sha","wrong_request","sibling_thread","deleted_archive","missing_turn"])
def test_direct_baseline_proof_fails_closed(tmp_path,monkeypatch,bad):
    home,src,raw,log,output=scenario(tmp_path,monkeypatch)
    archive=runner._archive_direct_thread_image(RID,output,{"CODEX_HOME":str(home)})
    rec=receipt(tmp_path,archive,output)
    doc=json.loads(rec.read_text())
    if bad=="unarchived":
        del doc["evidence"]["direct_artifact_archive"]
    elif bad=="different_raw":
        raw.write_bytes(raw.read_bytes()+b"changed")
    elif bad=="wrong_receipt_sha":
        doc["output_sha256"]="f"*64
    elif bad=="wrong_request":
        doc["evidence"]["request_id"]="b"*32
    elif bad=="sibling_thread":
        doc["evidence"]["generated_artifacts"]=["f"*36+"/"+NAME]
    elif bad=="deleted_archive":
        (rec.parent.parent/"image-artifacts"/RID/THREAD/NAME).unlink()
    elif bad=="missing_turn":
        log.write_bytes(log.read_bytes().replace(b'turn.completed',b'turn.failed'))
    rec.write_text(json.dumps(doc))
    assert proof.verify_direct_runner_archived_pixel(log,raw,RID) is None

def test_historical_f001_style_receipt_cannot_be_upgraded_after_fact(tmp_path,monkeypatch):
    home,src,raw,log,output=scenario(tmp_path,monkeypatch)
    receipt(tmp_path,{},output)
    assert proof.verify_direct_runner_archived_pixel(log,raw,RID) is None


def test_direct_run_persists_thread_receipt_without_provider_call(tmp_path,monkeypatch):
    import subprocess
    home,src,raw,log,output=scenario(tmp_path,monkeypatch)
    def fake_run(cmd,**kwargs):
        kwargs["stdout"].write(output.decode("utf-8"))
        kwargs["stdout"].flush()
        return subprocess.CompletedProcess(cmd,0)
    monkeypatch.setattr(runner.subprocess,"run",fake_run)
    with log.open("w",encoding="utf-8") as sink:
        completed=runner.run_codex(
            ["codex","exec"],input="offline test",stdout=sink,
            stderr=subprocess.STDOUT,cwd=tmp_path,env={"CODEX_HOME":str(home)},
            task_type="image",request_id=RID)
    assert completed.returncode==0
    row=runner.read_task_result(RID)
    assert row["evidence"]["generated_artifacts"]==[f"{THREAD}/{NAME}"]
    assert row["evidence"]["direct_artifact_archive"]=="DIRECT_THREAD_SCOPED_CAPTURE"
    assert proof.verify_direct_runner_archived_pixel(log,raw,RID) is not None

def test_direct_run_without_thread_artifact_never_claims_image(tmp_path,monkeypatch):
    import subprocess
    home,src,raw,log,output=scenario(tmp_path,monkeypatch)
    src.unlink()
    def fake_run(cmd,**kwargs):
        kwargs["stdout"].write(output.decode("utf-8"))
        kwargs["stdout"].flush()
        return subprocess.CompletedProcess(cmd,0)
    monkeypatch.setattr(runner.subprocess,"run",fake_run)
    with log.open("w",encoding="utf-8") as sink:
        completed=runner.run_codex(
            ["codex","exec"],input="offline test",stdout=sink,
            stderr=subprocess.STDOUT,cwd=tmp_path,env={"CODEX_HOME":str(home)},
            task_type="image",request_id=RID)
    assert completed.returncode==0
    row=runner.read_task_result(RID)
    assert not row["evidence"].get("generated_artifacts")
    assert proof.verify_direct_runner_archived_pixel(log,raw,RID) is None


def test_candidate_refuses_direct_archive_claim_from_bridge_receipt(tmp_path,monkeypatch):
    home,src,raw,log,output=scenario(tmp_path,monkeypatch)
    archive=runner._archive_direct_thread_image(RID,output,{"CODEX_HOME":str(home)})
    rec=receipt(tmp_path,archive,output)
    doc=json.loads(rec.read_text())
    doc["evidence"]["transport"]="user_bridge"
    rec.write_text(json.dumps(doc))
    assert backend.runner_verified_exported_candidate(tmp_path,RID) is None

def test_candidate_refuses_legacy_direct_receipt_without_archive_marker(tmp_path,monkeypatch):
    home,src,raw,log,output=scenario(tmp_path,monkeypatch)
    archive=runner._archive_direct_thread_image(RID,output,{"CODEX_HOME":str(home)})
    rec=receipt(tmp_path,archive,output)
    doc=json.loads(rec.read_text())
    del doc["evidence"]["direct_artifact_archive"]
    rec.write_text(json.dumps(doc))
    assert backend.runner_verified_exported_candidate(tmp_path,RID) is None
