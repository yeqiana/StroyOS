"""No-paid-call safety revision review + direct worker defense."""
from __future__ import annotations
import copy,hashlib,sys
from pathlib import Path
from unittest.mock import Mock
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/"episodes/_system")]
import production_ep14_safety_content_review as review
import image_worker_pool as worker

def make_data():
    b=[{"frame":f,"scope":"batch","status":"generated"} for f in range(1,49) if f not in (1,5,45,47)]
    entries=[];prompts={};contracts={};first={};states={}
    for f in (9,29,48):
        row=next(x for x in b if x["frame"]==f)
        row.update({"status":"external_blocked","requires_content_revision":True,
                    "no_automatic_original_prompt_retry":True,
                    "provider_safety_refusal_receipt_sha256":"a"*64,
                    "frame_contract":{"contract_sha256":str(f)*64},
                    "prompt_package":{"package_sha256":str(f)*64}})
        raw=f"immutable original prompt {f}".encode()
        prompts[f]=raw
        contracts[f]={"contract_sha256":str(f)*64,
                      "storyboard_frame":{"text":"raw original storyboard",
                                          "sha256":"b"*64}}
        first[f]={"status":"FAILED_AFTER_DISPATCH",
                  "failure_class":"IMAGE_PROVIDER_SAFETY_REJECTED"}
        states[f]={"attempts_consumed":1,"active_attempt_index":None,
                   "second_exists":False}
        entries.append({"frame":f,
            "candidate_scene_prompt":"A safe non-graphic documentary reinterpretation preserving the story beat.",
            "semantic_reason":"Preserve the underlying story beat",
            "previous_prompt_sha256":hashlib.sha256(raw).hexdigest(),
            "locked_frame_contract_sha256":str(f)*64,
            "old_package_sha256":str(f)*64})
    draft={"type":"NON_EXECUTABLE_SAFETY_CONTENT_REVISION_CANDIDATES",
           "paid_attempts_authorized":0,"frames":entries}
    driver={"driver_state":"EXITED","liveness":"DEAD","pid":0}
    return [draft,{"items":b},prompts,contracts,first,states,driver]

def check(x):
    return review.evaluate(*x)

def test_read_only_packet_never_fake_pass_or_paid_authorization():
    result=check(make_data())
    assert result["status"]=="CONTENT_REVIEW_REQUIRED"
    assert result["existing_images"]==45
    assert result["new_attempts"]==result["model_calls"]==result["sql_writes"]==0
    assert result["can_dispatch"] is False
    assert [x["frame"] for x in result["frames"]]==[9,29,48]
    assert all(x["review_approved"] is False for x in result["frames"])
    assert all("OLD_LOCKED_STORYBOARD" in x["blocked_root_cause"] for x in result["frames"])

def test_any_drift_fails_closed():
    for mutation,reason in (
        (lambda a:a[2].__setitem__(9,b"tampered"),"ORIGINAL_PROMPT_SHA_MISMATCH"),
        (lambda a:a[3][29].__setitem__("contract_sha256","x"),"LOCKED_FRAME_OR_PROMPT_PACKAGE_DRIFT"),
        (lambda a:a[5][48].__setitem__("second_exists",True),"FIRST_ATTEMPT_NOT_STRICTLY_TERMINAL"),
        (lambda a:a[0]["frames"][0].__setitem__("candidate_scene_prompt",""),"CANDIDATE_EMPTY"),
        (lambda a:a[6].__setitem__("liveness","ALIVE"),"DRIVER_NOT_STOPPED"),
    ):
        args=make_data();mutation(args);result=check(args)
        assert result["status"]=="SOURCE_DRIFT_BLOCKED"
        assert reason in result["errors"] or any(reason in r["problems"] for r in result["frames"])

def test_queue_reorder_and_unsafe_extra_frame_blocks():
    args=make_data()
    next(x for x in args[1]["items"] if x["frame"]==20)["status"]="queued"
    assert check(args)["status"]=="SOURCE_DRIFT_BLOCKED"

def test_direct_worker_blocks_before_global_capacity_or_paid_attempt(tmp_path,monkeypatch):
    ep=tmp_path/"episodes"/"00_独立篇"/"14_深渊疗愈所_第一集_净土生命还原"
    ep.mkdir(parents=True)
    monkeypatch.setattr(worker.production_native_batch_followon,"_is_ep14",
                        lambda _:True)
    capacity=Mock(side_effect=AssertionError("Image capacity must never be taken"))
    monkeypatch.setattr(worker.global_image_capacity,"image_permits",capacity)
    for f in (9,29,48):
        item={"id":f"id{f}","frame":f,"scope":"batch",
              "status":"queued","no_automatic_original_prompt_retry":True}
        answer=worker.execute(ep,item,60,None)
        assert answer["returncode"]==93
        assert answer["image_attempt_reserve_called"] is False
    capacity.assert_not_called()

def test_stale_worker_copy_still_blocked_by_canonical_queue(tmp_path,monkeypatch):
    ep=tmp_path/"episodes"/"00_独立篇"/"14_深渊疗愈所_第一集_净土生命还原"
    ep.mkdir(parents=True)
    monkeypatch.setattr(worker.production_native_batch_followon,"_is_ep14",lambda _:True)
    import scheduler_core
    monkeypatch.setattr(scheduler_core,"load_queue",
                        lambda _:{"items":[{"id":"id9","scope":"batch","frame":9,
                                          "status":"external_blocked",
                                          "no_automatic_original_prompt_retry":True}]})
    assert worker._content_revision_dispatch_denied(
        ep,{"id":"id9","scope":"batch","frame":9,"status":"queued"})
    assert not worker._content_revision_dispatch_denied(
        ep,{"id":"id20","scope":"batch","frame":20,"status":"queued"})


def test_cleared_queue_flags_cannot_bypass_immutable_mysql_refusal(tmp_path,monkeypatch):
    import scheduler_core
    import generation_attempt_authority as ga
    ep=tmp_path/"episodes"/"00_独立篇"/"14_深渊疗愈所_第一集_净土生命还原"
    ep.mkdir(parents=True)
    monkeypatch.setattr(worker.production_native_batch_followon,"_is_ep14",lambda _:True)
    item={"id":"frame29","scope":"batch","frame":29,"status":"queued"}
    monkeypatch.setattr(scheduler_core,"load_queue",lambda _:{"items":[item]})
    monkeypatch.setattr(ga,"load_attempt",lambda *_:{
        "status":"FAILED_AFTER_DISPATCH",
        "failure_class":"IMAGE_PROVIDER_SAFETY_REJECTED"})
    assert worker._content_revision_dispatch_denied(ep,item)
