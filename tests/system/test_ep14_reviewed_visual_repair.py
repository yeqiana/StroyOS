"""Strict offline regression for real completed Controller LF repair and Episode14 wave.

No paid Provider calls or live MySQL; source model-execution receipt is immutable.
"""
import hashlib,json,sys
from pathlib import Path
from unittest.mock import patch
import pytest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/"episodes/_system"))
import image_payload_controller as controller
import production_ep14_visual_repair as repairs

def event_stream(text,*,completed=True,duplicate=False,failed=False):
    parts=[{"type":"thread.started","thread_id":"01a16924-9ea0-7631-ac02-006ddf5a9e15"},
           {"type":"item.completed","item":{"type":"agent_message","text":text}}]
    if duplicate:parts.append(parts[-1])
    if failed:parts.append({"type":"turn.failed"})
    if completed:parts.append({"type":"turn.completed"})
    return "\n".join(json.dumps(x,ensure_ascii=False) for x in parts)

def test_strict_controller_rejects_but_scoped_completed_unescaped_LF_is_safe():
    text='{"scene_prompt":"夜间庭院\n转运车上的厚布"}'
    stream=event_stream(text)
    with pytest.raises(controller.ImagePayloadControllerError,match="SCHEMA_INVALID"):
        controller._parse_controller_output(stream)
    assert controller._parse_controller_output(
        stream,allow_unescaped_linefeeds=True)=={
            "scene_prompt":"夜间庭院\n转运车上的厚布"}

@pytest.mark.parametrize("text,complete,duplicate,failed",[
    ('{"scene_prompt":"a\nb"}',False,False,False),
    ('{"scene_prompt":"a\nb"}',True,True,False),
    ('{"scene_prompt":"a\nb"}',True,False,True),
    ('{"scene_prompt":"a\nb","extra":"payload"}',True,False,False),
    ('{"scene_prompt":"a\x00b"}',True,False,False),
    ('{"scene_prompt":"a\nb"',True,False,False),
    ('{"scene_prompt":"\\q\nb"}',True,False,False),
])
def test_no_partial_duplicate_extra_null_or_bad_escape(text,complete,duplicate,failed):
    with pytest.raises(controller.ImagePayloadControllerError):
        controller._parse_controller_output(
            event_stream(text,completed=complete,duplicate=duplicate,failed=failed),
            allow_unescaped_linefeeds=True)

def test_completed_success_receipt_reuses_exact_F045_without_overwrite(tmp_path):
    ep=tmp_path/"episodes/00_独立篇"/"14_深渊疗愈所_第一集_净土生命还原"
    receipt=ep/"meta/provider-receipts/model-executions/imgctrl-123.json"
    receipt.parent.mkdir(parents=True)
    output=event_stream('{"scene_prompt":"长焦拍摄\n灯光仅来自庭院"}')
    data={"status":"SUCCESS","step":"IMAGE_PAYLOAD_REQUEST",
          "call_id":"imgctrl-123","model_role":"image.controller",
          "profile":"image_controller","requested_model":"gpt-6-luna",
          "reasoning_effort":"high","model_policy_sha256":"m"*64,
          "controller_input_fingerprint":"i"*64,
          "image_generation_enabled":False,
          "effective_model_source":"EXPLICIT_RUNTIME_BINDING",
          "controller_validation_version":controller.CONTROLLER_VALIDATION_VERSION,
          "scoped_output_stream":output}
    receipt.write_text(json.dumps(data,ensure_ascii=False),encoding="utf-8")
    old_bytes=receipt.read_bytes()
    request={"request_fingerprint":"p"*64,"scene_prompt":"长焦拍摄\n灯光仅来自庭院"}
    opts=dict(ep=ep,path=receipt,call_id="imgctrl-123",input_fingerprint="i"*64,
              binding={"model_policy_sha256":"m"*64},
              identity={"frame_id":"45"},fields={},payload={},controller_input={})
    with patch.object(controller,"_build_validated_request",return_value=request):
        r=controller._reuse_existing_receipt(**opts)
        assert r["reused"] and r["request_fingerprint"]=="p"*64
        assert r["controller_source_receipt_sha256"]==hashlib.sha256(old_bytes).hexdigest()
        assert receipt.read_bytes()==old_bytes
        file=Path(r["controller_format_recovery"])
        correction=json.loads(file.read_text(encoding="utf-8"))
        assert correction["image_generation_calls"]==0
        assert correction["paid_attempts_reserved"]==0
        again=controller._reuse_existing_receipt(**opts)
        assert again["controller_format_recovery"]==str(file)
    opts["identity"]={"frame_id":"47"}
    with pytest.raises(controller.ImagePayloadControllerError,match="SCHEMA_INVALID"):
        controller._reuse_existing_receipt(**opts)

def test_no_recovery_when_success_receipt_has_mismatched_output_sha(tmp_path):
    ep=tmp_path/"episodes/00_独立篇"/"14_深渊疗愈所_第一集_净土生命还原"
    f=ep/"meta/model-executions/out.json";f.parent.mkdir(parents=True)
    data={"status":"SUCCESS","step":"IMAGE_PAYLOAD_REQUEST","call_id":"id",
          "model_role":"image.controller","profile":"image_controller",
          "requested_model":"gpt-6-luna","reasoning_effort":"high",
          "model_policy_sha256":"m","controller_input_fingerprint":"i",
          "image_generation_enabled":False,"effective_model_source":"EXPLICIT_RUNTIME_BINDING",
          "controller_validation_version":controller.CONTROLLER_VALIDATION_VERSION,
          "controller_output_sha256":"bad",
          "scoped_output_stream":event_stream('{"scene_prompt":"a\nb"}')}
    f.write_text(json.dumps(data,ensure_ascii=False),encoding="utf-8")
    with pytest.raises(controller.ImagePayloadControllerError,match="SCHEMA_INVALID"):
        controller._reuse_existing_receipt(ep=ep,path=f,call_id="id",input_fingerprint="i",
            binding={"model_policy_sha256":"m"},identity={"frame_id":"45"},
            fields={},payload={},controller_input={})

def test_ep14_rearm_without_ack_cannot_mutate_queue(tmp_path):
    assert repairs.rearm(tmp_path,ack=False)=={
        "status":"BLOCKED","reason":"OPERATOR_ACK_REQUIRED"}

def test_foreign_repair_never_receives_EP14_native_tool_permission(tmp_path):
    ep=tmp_path/"episodes/00_独立篇"/"13_失物归还的那扇门"
    assert repairs.eligible(ep,{"frame":45,"kind":"repair","scope":"repair",
        "id":repairs.FRAMES[45]}, {},{}) is False
    assert repairs.eligible(ep,{"frame":1,"kind":"repair","scope":"repair",
        "id":"c006c22820c9"}, {},{}) is False

def test_rc22_source_guard_can_only_recover_true_three_frame_wave(tmp_path,monkeypatch):
    ep=tmp_path
    with patch.object(repairs.runtime_driver,"status",return_value={
        "driver_state":"EXITED","liveness":"DEAD","pid":0,"exit_code":"22"}):
        result=repairs.verify_rearmed(ep)
    assert result["status"]=="BLOCKED"

def test_prior_known_ep13_pilot_remains_on_distinct_path():
    import production_native_repair_pilot as pilot
    text=(ROOT/"episodes/_system/production_native_repair_pilot.py").read_text(encoding="utf-8")
    assert "production_ep14_visual_repair.eligible" in text
    assert "ep.name != \"13_失物归还的那扇门\"" in text


def test_rc22_exact_driver_record_uses_official_remediation_module(monkeypatch):
    ep=repairs.ROOT/"episodes"/"00_独立篇"/repairs.EPISODE
    q={"items":[{"frame":f,"id":iid,"scope":"repair","kind":"repair",
        "status":"queued","native_ep14_repair_rearm_count":1,
        "native_repair_visibility_sha256":"a"*64,
        "ep14_review_sha256":"b"*64,"prompt_package":{},
        "frame_contract":{}} for f,iid in repairs.FRAMES.items()]}
    monkeypatch.setattr(repairs.model_policy,"resolve",lambda *args,**kw:{})
    monkeypatch.setattr(repairs.scheduler_core,"load_queue",lambda *_:q)
    monkeypatch.setattr(repairs.runtime_driver,"status",lambda *_:{
        "driver_state":"EXITED","liveness":"DEAD","pid":0,
        "exit_code":"22","record":{"exit_code":22}})
    monkeypatch.setattr(repairs,"eligible",lambda *args,**kwargs:True)
    monkeypatch.setattr(repairs,"sha",lambda *_:"b"*64)
    result=repairs.verify_rearmed(ep)
    assert result["status"]=="VISUAL_LOCK_RC22_EP14_REPAIR_REARMED"
    assert result["new_paid_attempts"]==0
    assert len(result["repair_queue_sha256"])==64
