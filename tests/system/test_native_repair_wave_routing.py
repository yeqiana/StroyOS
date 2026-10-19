"""Final Semantic committed failure must resume its one bounded repair lane before human-only siblings."""
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import patch
import pytest

ROOT=Path(__file__).resolve().parents[2]
SYSTEM=ROOT/"episodes"/"_system"
if str(SYSTEM) not in sys.path:
    sys.path.insert(0,str(SYSTEM))

import next_action
import vision_review_executor
import story_json


def _ep(tmp_path):
    ep=tmp_path/"episode"
    (ep/"meta/runtime").mkdir(parents=True)
    story_json.write_json(ep/"meta/frame-semantic-candidate-attempt-1.json",{
        "review_scope":"CANDIDATE_FULL_FRAME_SET","recorded_at":"2026-10-19T13:29:18+08:00",
        "failed_frames":["01","03"],"critic_result":{"frames":[{"frame":"01","issue_codes":["DRIFT"]}]},
        "reviewed_assets":[{"frame":"01","sha256":"a"*64}]})
    return ep


def test_authorized_frozen_failure_prioritized_over_needs_user_without_new_critic(monkeypatch,tmp_path):
    ep=_ep(tmp_path)
    ledger={"01":{"status":"REPAIR_AUTHORIZED"},"02":{"status":"LOCKED"},
            "03":{"status":"NEEDS_USER"}}
    queue={"items":[{"frame":1,"status":"generated"},{"frame":2,"status":"generated"},{"frame":3,"status":"generated"}]}
    monkeypatch.setattr(next_action.runtime_portability,"assert_episode_directory",lambda _:None)
    monkeypatch.setattr(next_action.runtime_portability,"episode_label",lambda _:"synthetic")
    monkeypatch.setattr(next_action.runtime_router,"detect",lambda:("CODEX",{}))
    monkeypatch.setattr(next_action.runtime_router,"image_execution_runtime",lambda:("CODEX",{}))
    monkeypatch.setattr(next_action.runtime_router,"vision_review_runtime",lambda:("CODEX",{}))
    monkeypatch.setattr(next_action.runtime_execution,"effective_mode",lambda _:"full_auto")
    monkeypatch.setattr(next_action,"state",lambda _:"VISUAL_CALIBRATED")
    monkeypatch.setattr(next_action.episode_lifecycle,"disposition",lambda _:"ACTIVE")
    monkeypatch.setattr(next_action,"pending_product_review",lambda *_a,**_k:None)
    monkeypatch.setattr(next_action,"redundant_product_review_residue",lambda *_a,**_k:[])
    monkeypatch.setattr(next_action,"host_loop",lambda _:{"host_loop":"IDLE"})
    monkeypatch.setattr(next_action,"product_review_lifecycle_events",lambda _:[])
    monkeypatch.setattr(next_action.scheduler_core,"load_queue",lambda _:queue)
    monkeypatch.setattr(next_action.scheduler_core,"progress",lambda *_a,**_k:{})
    monkeypatch.setattr(next_action.production_ledger,"load_authority",lambda *_a,**_k:{"frames":ledger})
    monkeypatch.setattr(next_action,"queue_summary",lambda _:{"raw":queue,"blocked_items":[],"queued_frames":[],"counts":{}})
    monkeypatch.setattr(next_action,"_expected_frames",lambda _:3)
    monkeypatch.setattr(next_action,"_represented_original_frames",lambda *_:set(range(1,4)))
    monkeypatch.setattr(next_action.production_batch_review,"pending",lambda _:[])
    monkeypatch.setattr(next_action.visual_lock_baseline_gate,"awaiting_review",lambda *_:False)
    with patch("image_scheduler.ready_items",return_value=([],[])):
        choice=next_action.derive(ep)
    assert choice["action"]=="MATERIALIZE_REPAIR_WAVE"
    assert choice["executor"]=="CODEX_VISION"
    assert choice["hard_stop"] is False
    assert choice["auto_recoverable"] is True


def test_frozen_review_recovery_never_restarts_pixel_critic(monkeypatch,tmp_path):
    ep=_ep(tmp_path)
    monkeypatch.setattr(vision_review_executor,"_require_capability",lambda:None)
    findings={"attempt":1,"evidence_sha256":"d"*64,"findings":[{"frame_id":"01","repairable":True}]}
    with patch("repair_aggregator.collect_first_pass_findings",return_value=findings) as collect, \
         patch("repair_aggregator.materialize_wave",autospec=True,return_value={
             "status":"STARTED","plan":{"summary":{"eligible_repairs":1}}}) as wave, \
         patch.object(vision_review_executor.frame_semantic_review,"run_critic",side_effect=AssertionError("do not rerun critic")):
        result=vision_review_executor.execute(ep,{"action":"MATERIALIZE_REPAIR_WAVE","executor":"CODEX_VISION","attempt":1})
    assert result["status"]=="REPAIR_ENQUEUED"
    collect.assert_called_once_with(ep,attempt=1)
    wave.assert_called_once_with(ep,attempt=1,findings=findings)


def test_missing_completed_review_never_grants_repair_action(tmp_path):
    ep=_ep(tmp_path)
    assert next_action._frozen_authorized_repair_frames(ep,{"01":{"status":"REPAIR_AUTHORIZED"}})==[1]
    (ep/"meta/frame-semantic-candidate-attempt-1.json").unlink()
    assert next_action._frozen_authorized_repair_frames(ep,{"01":{"status":"REPAIR_AUTHORIZED"}})==[]



def test_completed_wave_never_replays_or_overrides_user_stop(tmp_path):
    ep=_ep(tmp_path)
    story_json.write_json(ep/"meta/runtime/repair-wave-1.json",{
        "status":"COMPLETED", "frames":[{"frame_id":"01","repairable":True,"repair_status":"PASS"}]})
    assert next_action._frozen_authorized_repair_frames(
        ep,{"01":{"status":"REPAIR_AUTHORIZED"},"03":{"status":"NEEDS_USER"}})==[]


def test_no_authorized_ledger_frame_cannot_turn_failed_review_into_paid_repair(tmp_path):
    ep=_ep(tmp_path)
    assert next_action._frozen_authorized_repair_frames(
        ep,{"01":{"status":"NEEDS_USER"},"03":{"status":"NEEDS_USER"}})==[]


def test_unverified_review_scope_or_recording_never_routes_repair(tmp_path):
    ep=_ep(tmp_path)
    p=ep/"meta/frame-semantic-candidate-attempt-1.json"
    for bad in ({"review_scope":"CANDIDATE_FULL_FRAME_SET"}, {"review_scope":"UNVERIFIED",
                "recorded_at":"2026-10-19","failed_frames":["01"],"reviewed_assets":[{"frame":"01"}]}):
        story_json.write_json(p,bad)
        assert next_action._frozen_authorized_repair_frames(ep,{"01":{"status":"REPAIR_AUTHORIZED"}})==[]


def test_failed_prompt_is_not_falsely_reported_as_enqueued(monkeypatch,tmp_path):
    ep=_ep(tmp_path)
    monkeypatch.setattr(vision_review_executor,"_require_capability",lambda:None)
    findings={"attempt":1,"evidence_sha256":"d"*64,"findings":[{"frame_id":"01","repairable":True}]}
    with patch("repair_aggregator.collect_first_pass_findings",return_value=findings), \
         patch("repair_aggregator.materialize_wave",autospec=True,return_value={
             "status":"STARTED","plan":{"frames":[{"frame_id":"01","repairable":True,
                 "repair_status":"PROMPT_TECH_FAILED"}]}}):
        outcome=vision_review_executor.execute(ep,{"action":"MATERIALIZE_REPAIR_WAVE",
                                                   "executor":"CODEX_VISION","attempt":1})
    assert outcome["status"]=="TECHNICAL_FAILURE"


def test_review_action_rejects_attempt_two_before_any_model_or_queue_mutation(monkeypatch,tmp_path):
    ep=_ep(tmp_path)
    monkeypatch.setattr(vision_review_executor,"_require_capability",lambda:None)
    with patch("repair_aggregator.materialize_wave",side_effect=AssertionError("not authorized")):
        with pytest.raises(vision_review_executor.VisionReviewError):
            vision_review_executor.execute(ep,{"action":"MATERIALIZE_REPAIR_WAVE",
                                              "executor":"CODEX_VISION","attempt":2})
