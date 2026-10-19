from __future__ import annotations

import sys
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SYSTEM = ROOT / "episodes" / "_system"
if str(SYSTEM) not in sys.path:
    sys.path.insert(0, str(SYSTEM))

import repair_aggregator
import runtime_observability
import batch_repair_arbiter
import auto_repair_enqueue
import story_json
import vision_review_executor


def _findings():
    rows = []
    for frame in range(1, 21):
        if frame not in {3, 7, 11, 14, 18}:
            continue
        rows.append({
            "logical_asset_key": f"synthetic/frame-{frame:02d}",
            "frame_id": f"{frame:02d}",
            "source_generation_key": f"GK-{frame:02d}",
            "source_artifact_sha256": f"{frame:064x}"[-64:],
            "failure_codes": ["KEY_PROP_DRIFT"],
            "failure_summary": "key prop mismatch",
            "human_only": frame == 18,
            "stale": False,
            "repairable": frame != 18 and frame != 14,
            "remaining_generation_attempts": 0 if frame == 14 else 1,
            "repair_status": "ELIGIBLE",
            "source_item_id": f"q-{frame}",
            "review_receipt_sha256": "a" * 64,
        })
    return {"episode_id": "synthetic", "attempt": 1, "evidence_sha256": "a" * 64, "findings": rows}


def _policy():
    return {"model": "gpt-6-luna", "profile": "structured_text", "reasoning_effort": "high",
            "model_policy_sha256": "b" * 64, "policy_version": "test-policy"}


def test_synthetic_twenty_frame_set_aggregates_one_repair_wave(tmp_path):
    plan = repair_aggregator.build_repair_plan(tmp_path, _findings(), policy=_policy())
    assert plan["summary"]["total_failures"] == 5
    assert plan["summary"]["eligible_repairs"] == 3
    assert [row["frame_id"] for row in plan["frames"] if row["repairable"]] == ["03", "07", "11"]
    assert next(row for row in plan["frames"] if row["frame_id"] == "14")["repair_status"] == "BUDGET_EXHAUSTED"
    assert next(row for row in plan["frames"] if row["frame_id"] == "18")["repair_status"] == "NEEDS_USER"
    assert plan["repair_wave_id"].endswith("/production/repair-wave-1")
    assert plan["policy_sha256"] == "b" * 64
    repair_aggregator._write_plan(tmp_path,plan)
    result=repair_aggregator.finalize_wave(tmp_path,repair_reviews={"03":"PASS","07":"PASS","11":"REPAIR_NEEDED"})
    rows={row["frame_id"]:row["repair_status"] for row in result["plan"]["frames"]}
    assert rows["03"]=="PASS" and rows["07"]=="PASS" and rows["11"]=="NEEDS_USER"
    assert rows["14"]=="BUDGET_EXHAUSTED" and rows["18"]=="NEEDS_USER"
    assert result["plan"]["summary"]["eligible_repairs"]==3
    assert result["plan"]["summary"]["repaired_pass"]==2
    assert result["plan"]["summary"]["needs_user"]==3


def test_second_automatic_wave_is_hard_denied(tmp_path):
    plan = repair_aggregator.build_repair_plan(tmp_path, _findings(), policy=_policy())
    plan["status"] = "STARTED"
    repair_aggregator._write_plan(tmp_path, plan)
    changed = _findings()
    changed["evidence_sha256"] = "c" * 64
    with patch.object(repair_aggregator, "_event") as event:
        result = repair_aggregator.materialize_wave(tmp_path, findings=changed, policy=_policy())
    assert result["status"] == "SECOND_AUTOMATIC_REPAIR_WAVE_FORBIDDEN"
    event.assert_called_once()


def test_resume_from_persisted_review_receipt_reuses_existing_wave(tmp_path):
    evidence = {"schema_version":1,"attempt":1,"review_scope":"CANDIDATE_FULL_FRAME_SET",
                "recorded_at":"2026-09-30T00:00:00Z","failed_frames":[]}
    evidence_path=tmp_path/"meta"/"frame-semantic-candidate-attempt-1.json"
    evidence_path.parent.mkdir(parents=True)
    story_json.write_json(evidence_path,evidence)
    plan={"schema_version":1,"episode_id":"synthetic","repair_wave_id":"synthetic/production/repair-wave-1",
          "source_review_receipts":[{"path":"meta/frame-semantic-candidate-attempt-1.json",
                                      "sha256":repair_aggregator._sha(evidence_path)}],
          "status":"COMPLETED","frames":[],"summary":{}}
    repair_aggregator._write_plan(tmp_path,plan)
    with patch.object(repair_aggregator,"_event") as event:
        result=repair_aggregator.materialize_wave(tmp_path,findings=evidence)
    assert result["status"]=="ALREADY_COMPLETED"
    assert result["plan"]["repair_wave_id"]==plan["repair_wave_id"]
    event.assert_not_called()


def test_wave_finalization_turns_second_content_failure_into_needs_user(tmp_path):
    plan = repair_aggregator.build_repair_plan(tmp_path, _findings(), policy=_policy())
    repair_aggregator._write_plan(tmp_path, plan)
    outcomes = {"03": "PASS", "07": "PASS", "11": "REPAIR_NEEDED"}
    result = repair_aggregator.finalize_wave(tmp_path, repair_reviews=outcomes)
    assert result["status"] == "COMPLETED"
    assert result["plan"]["summary"]["repaired_pass"] == 2
    assert result["plan"]["summary"]["needs_user"] == 3
    assert next(row for row in result["plan"]["frames"] if row["frame_id"] == "11")["repair_status"] == "NEEDS_USER"


def test_repair_telemetry_contract_accepts_phase3_events(tmp_path):
    for name in ("FIRST_PASS_REVIEW_COMPLETE", "REPAIR_WAVE_PLANNED", "REPAIR_WAVE_STARTED",
                 "REPAIR_PROMPT_STARTED", "REPAIR_PROMPT_FINISHED", "REPAIR_ENQUEUED",
                 "REPAIR_GENERATION_STARTED", "REPAIR_GENERATION_FINISHED",
                 "REPAIR_REVIEW_STARTED", "REPAIR_REVIEW_FINISHED",
                 "REPAIR_WAVE_COMPLETED", "REPAIR_WAVE_DENIED_SECOND_WAVE"):
        event = runtime_observability.runtime_event(tmp_path, name,
            episode_id="synthetic", repair_wave_id="synthetic/production/repair-wave-1",
            logical_asset_key="synthetic/frame-03", source_generation_key="GK-03",
            failure_codes=["KEY_PROP_DRIFT"], remaining_attempts=1)
        assert event["event_type"] == name


def test_fast_scout_does_not_authorize_production_repair(monkeypatch, tmp_path):
    assessment = {"action":"SINGLE_REPAIR","frame":3,"batch_id":"B1",
                 "deviation_score":90,"criticality_score":90}
    with patch.object(batch_repair_arbiter, "authorize_single_repair") as authorize:
        result = batch_repair_arbiter.apply(tmp_path, assessment)
    assert result["repair_deferred"] == "FIRST_PASS_REVIEW_BARRIER"
    assert result["ledger_repair_authorized"] is False
    authorize.assert_not_called()


def test_old_production_scout_marker_is_deferred_by_compatibility_facade(monkeypatch, tmp_path):
    queue = {"items":[{"id":"q1","frame":3,"scope":"batch","status":"scout_repair"}]}
    monkeypatch.setattr(auto_repair_enqueue.scheduler_core,"load_queue",lambda _ep:queue)
    with patch.object(auto_repair_enqueue,"enqueue") as enqueue:
        result=auto_repair_enqueue.enqueue_marked_repairs(tmp_path)
    assert result["results"][0]["status"] == "DEFERRED_FIRST_PASS_BARRIER"
    enqueue.assert_not_called()


def test_wave_materialization_is_idempotent_after_partial_resume(monkeypatch, tmp_path):
    rows = [row for row in _findings()["findings"] if row["repairable"]]
    queue = {"items":[]}
    for row in rows:
        artifact=tmp_path/f"frame-{row['frame_id']}.png"
        artifact.write_bytes(row["source_artifact_sha256"].encode())
        import hashlib
        row["source_artifact_sha256"]=hashlib.sha256(artifact.read_bytes()).hexdigest()
        prompt=tmp_path/f"frame-{row['frame_id']}.txt"
        prompt.write_text("original prompt",encoding="utf-8")
        queue["items"].append({"id":f"src-{row['frame_id']}","frame":int(row["frame_id"]),
            "scope":"batch","kind":"original","status":"generated",
            "generation_key":row["source_generation_key"],"output_path":str(artifact),
            "prompt_file":str(prompt),"depends_on":[]})
    findings={"episode_id":"synthetic","attempt":1,"evidence_sha256":"a"*64,"findings":rows}
    calls={"prompt":0,"enqueue":0}
    fail_frame_07_once={"value":True}
    monkeypatch.setattr(repair_aggregator.scheduler_core,"load_queue",lambda _ep:queue)
    monkeypatch.setattr(repair_aggregator.scheduler_core,"queue_transaction",lambda _ep:nullcontext())
    monkeypatch.setattr(repair_aggregator.scheduler_core,"save_queue",lambda _ep,_q:None)
    import image_model_policy
    monkeypatch.setattr(image_model_policy,"for_episode",lambda _ep:{"model":"gpt-image-2.5-flare","quality":"high"})

    def prompt_runner(ep, *, task_input):
        calls["prompt"]+=1
        if task_input["logical_asset_key"].endswith("frame-07") and fail_frame_07_once["value"]:
            fail_frame_07_once["value"]=False
            raise RuntimeError("synthetic crash after Frame03 materialization")
        path=ep/"meta"/"runtime"/"repair-prompts"/(task_input["logical_asset_key"].rsplit("-",1)[-1]+".txt")
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text("仅修失败维度",encoding="utf-8")
        return {"status":"SUCCESS","fingerprint":"fp-"+task_input["logical_asset_key"],"prompt_path":str(path),"receipt_path":"receipt.json"}

    def add_item(ep, **kwargs):
        calls["enqueue"]+=1
        item={"id":f"repair-{kwargs['frame']}","status":"queued",**kwargs}
        queue["items"].append(item)
        return item

    with patch.object(repair_aggregator,"_event"):
        try:
            repair_aggregator.materialize_wave(tmp_path,findings=findings,prompt_runner=prompt_runner,
                                               add_item_fn=add_item,policy=_policy())
            raise AssertionError("simulated partial materialization should interrupt")
        except RuntimeError as exc:
            assert "synthetic crash" in str(exc)
        second=repair_aggregator.materialize_wave(tmp_path,findings=findings,prompt_runner=prompt_runner,
                                                    add_item_fn=add_item,policy=_policy())
    assert second["status"] == "STARTED" and second["resumed"] is True
    assert calls == {"prompt":4,"enqueue":3}
    repair_rows=[row for row in queue["items"] if row.get("repair_wave_id")]
    assert len(repair_rows)==3
    assert len({row["capture_id"] for row in repair_rows})==3


def test_formal_first_pass_failure_delegates_once_to_aggregator(monkeypatch,tmp_path):
    evidence={"schema_version":1,"attempt":1,"review_scope":"CANDIDATE_FULL_FRAME_SET",
        "failed_frames":["03"],"critic_result":{"frames":[{"frame":"03","issue_codes":["KEY_PROP_DRIFT"]}]}}
    path=tmp_path/"meta"/"frame-semantic-candidate-attempt-1.json"
    path.parent.mkdir(parents=True,exist_ok=True)
    story_json.write_json(path,evidence)
    monkeypatch.setattr(vision_review_executor,"_require_capability",lambda:None)
    monkeypatch.setattr(vision_review_executor.frame_semantic_review,"run_critic",lambda *_a,**_k:2)
    with patch("repair_aggregator.materialize_wave",autospec=True,return_value={"status":"STARTED","plan":{"repair_wave_id":"E/production/repair-wave-1"}}) as aggregate, \
         patch.object(vision_review_executor.auto_repair_enqueue,"enqueue") as immediate:
        result=vision_review_executor.execute(tmp_path,{"action":"REVIEW_FINAL_PRODUCTION","executor":"CODEX_VISION","attempt":1})
    assert result["status"]=="REPAIR_ENQUEUED"
    aggregate.assert_called_once_with(tmp_path,attempt=1,findings=evidence)
    immediate.assert_not_called()


def test_sha_drifted_first_pass_artifact_is_stale_and_not_repairable(monkeypatch,tmp_path):
    artifact=tmp_path/"candidate.png"
    artifact.write_bytes(b"new pixels")
    evidence={"recorded_at":"2026-09-30T00:00:00Z","review_scope":"CANDIDATE_FULL_FRAME_SET",
        "failed_frames":["03"],"reviewed_assets":[{"frame":"03","sha256":"a"*64}],
        "critic_result":{"frames":[{"frame":"03","issue_codes":["KEY_PROP_DRIFT"]}]}}
    ledger={"frames":{"03":{"status":"REPAIR_AUTHORIZED","current_candidate":{
        "path":str(artifact),"sha256":"a"*64}}}}
    monkeypatch.setattr(repair_aggregator.production_ledger,"load_authority",lambda *_a,**_k:ledger)
    monkeypatch.setattr(repair_aggregator,"_queue_source",lambda *_a,**_k:{"generation_key":"GK-3"})
    with patch("generation_attempt_authority.remaining",side_effect=AssertionError("stale pixels must not read budget")):
        result=repair_aggregator.collect_first_pass_findings(tmp_path,evidence=evidence)
    finding=result["findings"][0]
    assert finding["stale"] is True
    assert finding["repairable"] is False
    assert finding["repair_status"] == "STALE"
