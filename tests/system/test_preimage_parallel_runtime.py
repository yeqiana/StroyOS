from __future__ import annotations
import json, sys, tempfile, threading, time, unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT/"episodes/_system"))
import preimage_protocol
import preimage_task_contract as tasks

class PreimageParallelRuntimeTest(unittest.TestCase):
 def test_four_independent_candidates_commit_after_real_overlap(self):
  with tempfile.TemporaryDirectory() as raw:
   ep=Path(raw); (ep/"meta").mkdir(); state=ep/"meta/episode-state.json"; state.write_text(json.dumps({"current_state":"STORYBOARD_LOCKED"}),encoding="utf-8")
   (ep/"meta/story-gates.json").write_text(json.dumps({"story":{"locked":True},"visual":{}}),encoding="utf-8")
   before=state.read_bytes(); gate=threading.Barrier(4)
   def worker(task):
    gate.wait(timeout=3); time.sleep(.15)
    payload=tasks.valid_payload(task)
    self.assertEqual(tasks.write_candidate(ep,task,tasks.candidate_template(task,payload)),[])
    return 0
   result=preimage_protocol.execute_local(ep,worker,max_workers=4)
   self.assertEqual(result["status"],"PASS"); self.assertGreaterEqual(result["observed_preimage_parallelism_peak"],2)
   self.assertEqual(state.read_bytes(),before)
   self.assertTrue((ep/"meta/runtime/preimage-authority-barrier.json").is_file())
   self.assertTrue((ep/"meta/runtime/preimage-committed-snapshot.json").is_file())

 def test_verified_committed_barrier_reuses_preimage_without_paid_model_retry(self):
  with tempfile.TemporaryDirectory() as raw:
   ep=Path(raw); (ep/"meta").mkdir()
   (ep/"meta/story-gates.json").write_text(json.dumps({"story":{"locked":True},"visual":{}}),encoding="utf-8")
   import preimage_authority_snapshot as snapshots
   snap=snapshots.build(ep); rows=tasks.plan_tasks(ep,snap)
   for task in rows:
    self.assertEqual(tasks.write_candidate(ep,task,tasks.candidate_template(task,tasks.valid_payload(task))),[])
   committed=preimage_protocol.commit_candidates(ep,snap,rows)
   self.assertEqual(committed["status"],"PASS")
   def model_must_not_run(task):
    raise AssertionError("duplicate paid PREIMAGE dispatch: "+task["task_type"])
   reused=preimage_protocol.execute_local(ep,model_must_not_run)
   self.assertEqual(reused["status"],"PASS")
   self.assertEqual(reused["recovery"],"REUSED_VERIFIED_PREIMAGE_BARRIER")
   self.assertEqual(reused["observed_preimage_parallelism_peak"],0)


 def test_single_worker_never_counts_queued_work_as_parallel(self):
  with tempfile.TemporaryDirectory() as raw:
   ep=Path(raw); (ep/"meta").mkdir(); (ep/"meta/story-gates.json").write_text(json.dumps({"story":{},"visual":{}}),encoding="utf-8")
   def worker(task):
    time.sleep(.04); self.assertEqual(tasks.write_candidate(ep,task,tasks.candidate_template(task,tasks.valid_payload(task))),[]); return 0
   result=preimage_protocol.execute_local(ep,worker,max_workers=1)
   self.assertEqual(result["status"],"PASS")
   self.assertEqual(result["observed_preimage_parallelism_peak"],1)
   self.assertEqual(result["measurement_method"],"active_worker_enter_exit")

 def test_fresh_snapshot_can_atomically_replace_preimage_owned_scopes(self):
  with tempfile.TemporaryDirectory() as raw:
   ep=Path(raw); (ep/"meta").mkdir(); gates=ep/"meta/story-gates.json"
   gates.write_text(json.dumps({"story":{"locked":True},"character":{"finalize":{"old":True}},"visual":{
    "environment_contract":{"old":True},"frame_directives":{"old":True},"world_identity":{"old":True},
    "world_state":{"old":True},"temporal_continuity":{"old":True},"wardrobe":{"old":True},
    "narrative_core":{"old":True},"shot_progression":{"old":True},"capture_grammar":{"old":True}}}),encoding="utf-8")
   import preimage_authority_snapshot as snapshots
   snap=snapshots.build(ep); rows=tasks.plan_tasks(ep,snap)
   for task in rows:
    payload=tasks.valid_payload(task)
    self.assertEqual(tasks.write_candidate(ep,task,tasks.candidate_template(task,payload)),[])
   result=preimage_protocol.commit_candidates(ep,snap,rows)
   self.assertEqual(result["status"],"PASS")
   current=json.loads(gates.read_text(encoding="utf-8"))
   self.assertNotEqual(current["character"]["finalize"],{"old":True})
   self.assertNotEqual(current["visual"]["environment_contract"],{"old":True})
   self.assertTrue((ep/"meta/runtime/preimage-authority-barrier.json").is_file())

 def test_changed_authority_rejects_old_snapshot_as_stale(self):
  with tempfile.TemporaryDirectory() as raw:
   ep=Path(raw); (ep/"meta").mkdir(); (ep/"meta/story-gates.json").write_text(json.dumps({"story":{},"visual":{}}),encoding="utf-8")
   import preimage_authority_snapshot as snapshots
   snap=snapshots.build(ep); rows=tasks.plan_tasks(ep,snap)
   for task in rows:
    payload=tasks.valid_payload(task)
    self.assertEqual(tasks.write_candidate(ep,task,tasks.candidate_template(task,payload)),[])
   (ep/"meta/story-gates.json").write_text(json.dumps({"story":{"changed":True},"visual":{}}),encoding="utf-8")
   result=preimage_protocol.commit_candidates(ep,snap,rows)
   self.assertEqual(result["status"],"STALE")
   self.assertFalse((ep/"meta/runtime/preimage-authority-barrier.json").exists())

 def test_invalid_candidate_causes_zero_authority_writes(self):
  with tempfile.TemporaryDirectory() as raw:
   ep=Path(raw); (ep/"meta").mkdir(); gates=ep/"meta/story-gates.json"; gates.write_text(json.dumps({"story":{},"visual":{}}),encoding="utf-8")
   import preimage_authority_snapshot as snapshots
   snap=snapshots.build(ep); rows=tasks.plan_tasks(ep,snap); before=gates.read_bytes()
   for task in rows:
    payload=tasks.valid_payload(task)
    if task["task_type"]=="WORLD_PREPARE": payload.pop("visual.wardrobe")
    candidate=tasks.candidate_template(task,payload)
    if task["task_type"]=="WORLD_PREPARE": candidate["payload"]["visual.wardrobe"]={}  # present but semantically invalid
    if task["task_type"]!="WORLD_PREPARE": self.assertEqual(tasks.write_candidate(ep,task,candidate),[])
    else: self.assertTrue(tasks.verify_candidate(candidate,task))
   result=preimage_protocol.commit_candidates(ep,snap,rows)
   self.assertEqual(result["status"],"FAILED"); self.assertEqual(gates.read_bytes(),before)

if __name__=="__main__": unittest.main()
