from __future__ import annotations
import hashlib, json, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "episodes/_system"))
import authority_commit
import preimage_authority_snapshot as snapshots
import preimage_protocol
import preimage_task_contract as tasks
import preproduction_handoff
import runtime_request


def _owned_fixture() -> dict:
    """All ten PREIMAGE-owned scopes populated, plus two scopes PREIMAGE does not own."""
    return {
        "story": {"locked": True},
        "character": {"finalize": {"old": True}},
        "visual": {
            "environment_contract": {"old": True},
            "frame_directives": {"old": True},
            "world_identity": {"old": True},
            "world_state": {"old": True},
            "temporal_continuity": {"old": True},
            "wardrobe": {"old": True},
            "narrative_core": {"old": True},
            "shot_progression": {"old": True},
            "capture_grammar": {"old": True},
            # non-owned: written by visual_lock_baseline_gate._mark_baseline_pass
            "calibration": {"items": []},
            # non-owned: a frame_contract hash_material input (frame_contract.py:412,414)
            "continuity": {"note": "frame contract input"},
        },
    }


def _write_gates(ep: Path, gates: dict) -> None:
    (ep / "meta/story-gates.json").write_text(json.dumps(gates), encoding="utf-8")


def _read_gates(ep: Path) -> dict:
    return json.loads((ep / "meta/story-gates.json").read_text(encoding="utf-8"))


class PreimageScopeStalenessTest(unittest.TestCase):
    def test_non_owned_calibration_write_leaves_snapshot_valid(self):
        """The measured churn: a non-owned write must not invalidate the snapshot."""
        with tempfile.TemporaryDirectory() as raw:
            ep = Path(raw)
            (ep / "meta").mkdir()
            _write_gates(ep, _owned_fixture())
            snap = snapshots.build(ep)
            self.assertFalse(snapshots.stale_owned(ep, snap))
            gates = _read_gates(ep)
            gates["visual"]["calibration"] = {"items": [{"role": "ordinary_baseline", "decision": "passed"}]}
            _write_gates(ep, gates)
            self.assertFalse(snapshots.stale_owned(ep, snap))
            # snapshot_id must stay stable or plan_tasks can never mark a task REUSED
            self.assertEqual(snapshots.build(ep)["snapshot_id"], snap["snapshot_id"])

    def test_whole_file_projection_stays_broad_for_frame_contract(self):
        """stale() feeds frame_contract guards, which bind scopes PREIMAGE does not own.

        frame_contract.py:412,414 put ``visual.authenticity_card`` and
        ``visual.continuity`` into per-frame hash_material. Narrowing stale() to the
        PREIMAGE ownership set would let a mixed frame index ship, so a non-owned
        write must keep invalidating stale() while leaving stale_owned() clean.
        """
        with tempfile.TemporaryDirectory() as raw:
            ep = Path(raw)
            (ep / "meta").mkdir()
            _write_gates(ep, _owned_fixture())
            snap = snapshots.build(ep)
            gates = _read_gates(ep)
            gates["visual"]["continuity"]["note"] = "rewritten during frame compile"
            _write_gates(ep, gates)
            self.assertTrue(snapshots.stale(ep, snap))
            self.assertFalse(snapshots.stale_owned(ep, snap))

    def test_every_owned_scope_write_invalidates_snapshot(self):
        scopes = snapshots.owned_scopes()
        self.assertEqual(len(scopes), 10)
        for scope in scopes:
            with self.subTest(scope=scope):
                with tempfile.TemporaryDirectory() as raw:
                    ep = Path(raw)
                    (ep / "meta").mkdir()
                    _write_gates(ep, _owned_fixture())
                    snap = snapshots.build(ep)
                    self.assertFalse(snapshots.stale_owned(ep, snap))
                    gates = _read_gates(ep)
                    cursor = gates
                    parts = scope.split(".")
                    for key in parts[:-1]:
                        cursor = cursor.setdefault(key, {})
                    cursor[parts[-1]] = {"written": True}
                    _write_gates(ep, gates)
                    self.assertTrue(snapshots.stale_owned(ep, snap))

    def test_image_model_migration_does_not_invalidate_preimage_projection(self):
        with tempfile.TemporaryDirectory() as raw:
            ep = Path(raw)
            (ep / "meta/runtime").mkdir(parents=True)
            _write_gates(ep, _owned_fixture())
            request = {
                "request_id": "creative-1",
                "created_at": "old",
                "topic": {"title": "same story"},
                "story_input": {"mode": "auto_create", "raw": None, "constraints": []},
                "creative_hints": ["真实照片感"],
                "visual_profile": "M04",
                "image_model": "gpt-image-2",
                "image": {"model": "gpt-image-2", "source": "system_default", "strict_model": False},
                "runtime": {"max_image_workers": 3},
                "provenance": {"source": "natural_language", "original_request": "天界普通女生的一天"},
            }
            runtime_request.write_json(ep / "meta/runtime-request.json", request)
            snap = snapshots.build(ep)
            request["request_id"] = "execution-2"
            request["created_at"] = "new"
            request["image_model"] = "gpt-image-2.5-flare"
            request["image"]["model"] = "gpt-image-2.5-flare"
            request["runtime"]["max_image_workers"] = 1
            request["provenance"]["image_model_migration"] = {"from":"gpt-image-2","to":"gpt-image-2.5-flare"}
            runtime_request.write_json(ep / "meta/runtime-request.json", request)
            self.assertFalse(snapshots.stale_owned(ep, snap))
            self.assertFalse(snapshots.stale(ep, snap))
            request["creative_hints"] = ["改成明显插画感"]
            runtime_request.write_json(ep / "meta/runtime-request.json", request)
            self.assertTrue(snapshots.stale_owned(ep, snap))
            self.assertTrue(snapshots.stale(ep, snap))

    def test_legacy_full_request_snapshot_accepts_only_proven_model_migration(self):
        with tempfile.TemporaryDirectory() as raw:
            ep = Path(raw)
            (ep / "meta/runtime").mkdir(parents=True)
            _write_gates(ep, _owned_fixture())
            old = {
                "request_id":"old-request","topic":{"title":"same"},
                "story_input":{"mode":"auto_create","raw":None,"constraints":[]},
                "creative_hints":[],"visual_profile":"M04",
                "image_model":"gpt-image-2",
                "image":{"model":"gpt-image-2","source":"system_default","strict_model":False},
                "provenance":{"source":"natural_language","original_request":"same"},
            }
            runtime_request.write_json(ep / "meta/runtime-request.json", old)
            snap = snapshots.build(ep)
            full_sha = hashlib.sha256((ep / "meta/runtime-request.json").read_bytes()).hexdigest()
            for key in ("authority_sha256", "whole_authority_sha256"):
                legacy = dict(snap[key])
                legacy["runtime_request"] = full_sha
                legacy.pop("runtime_request_preimage", None)
                snap[key] = legacy
            current=json.loads(json.dumps(old))
            current["request_id"]="new-request"
            current["image_model"]="gpt-image-2.5-flare"
            current["image"]["model"]="gpt-image-2.5-flare"
            current["provenance"]["image_model_migration"]={
                "from":"gpt-image-2","to":"gpt-image-2.5-flare","source_request_id":"old-request"
            }
            runtime_request.write_json(ep / "meta/runtime-request.json", current)
            projection=runtime_request.preimage_authority_projection_sha256(current)
            runtime_request.write_json(ep / "meta/runtime/image-model-migration.json", {
                "preimage_authority_preserved":True,
                "preimage_authority_projection_sha256":projection,
                "request_id":"new-request","from":"gpt-image-2","to":"gpt-image-2.5-flare",
                "source_request_id":"old-request",
            })
            self.assertFalse(snapshots.stale_owned(ep, snap))
            self.assertFalse(snapshots.stale(ep, snap))
            current["creative_hints"]=["changed"]
            runtime_request.write_json(ep / "meta/runtime-request.json", current)
            self.assertTrue(snapshots.stale_owned(ep, snap))

    def test_new_handoff_hashes_runtime_request_as_projection_not_whole_file(self):
        with tempfile.TemporaryDirectory() as raw:
            ep=Path(raw); (ep/"meta").mkdir()
            runtime_request.write_json(ep/"meta/runtime-request.json", {"topic":{"title":"x"}})
            self.assertNotIn(ep/"meta/runtime-request.json", preproduction_handoff.authority_files(ep))

    def test_common_input_write_invalidates_snapshot(self):
        with tempfile.TemporaryDirectory() as raw:
            ep = Path(raw)
            (ep / "meta").mkdir()
            _write_gates(ep, _owned_fixture())
            snap = snapshots.build(ep)
            self.assertFalse(snapshots.stale_owned(ep, snap))
            (ep / "meta/character-contract.json").write_text(json.dumps({"protagonist": {"name": "A"}}), encoding="utf-8")
            self.assertTrue(snapshots.stale_owned(ep, snap))

    def test_non_owned_write_between_snapshot_and_commit_is_preserved(self):
        """Four finished candidates must survive a third-party non-owned write."""
        with tempfile.TemporaryDirectory() as raw:
            ep = Path(raw)
            (ep / "meta").mkdir()
            _write_gates(ep, _owned_fixture())
            snap = snapshots.build(ep)
            rows = tasks.plan_tasks(ep, snap)
            self.assertEqual(len(rows), 4)
            for task in rows:
                payload = tasks.valid_payload(task)
                self.assertEqual(tasks.write_candidate(ep, task, tasks.candidate_template(task, payload)), [])
            gates = _read_gates(ep)
            gates["visual"]["calibration"] = {"items": [{"role": "ordinary_baseline", "decision": "passed"}]}
            _write_gates(ep, gates)
            result = preimage_protocol.commit_candidates(ep, snap, rows)
            self.assertEqual(result["status"], "PASS")
            current = _read_gates(ep)
            # the third-party write is folded into the in-lock merge base, not dropped
            self.assertEqual(current["visual"]["calibration"]["items"][0]["decision"], "passed")
            self.assertNotEqual(current["visual"]["environment_contract"], {"old": True})
            self.assertTrue((ep / "meta/runtime/preimage-authority-barrier.json").is_file())

    def test_windows_crlf_gate_bytes_commit_with_snapshot_scope_guard(self):
        """Snapshot normalizes CRLF, atomic CAS must compare raw source bytes."""
        with tempfile.TemporaryDirectory() as raw:
            ep = Path(raw)
            (ep / "meta").mkdir()
            gates = ep / "meta/story-gates.json"
            text = json.dumps(_owned_fixture(), ensure_ascii=False, indent=2)
            gates.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
            snapshot = snapshots.build(ep)
            rows = tasks.plan_tasks(ep, snapshot)
            for task in rows:
                candidate = tasks.candidate_template(task, tasks.valid_payload(task))
                self.assertEqual(tasks.write_candidate(ep, task, candidate), [])
            self.assertFalse(snapshots.stale_owned(ep, snapshot))
            self.assertNotEqual(snapshots.sha(gates), authority_commit.sha(gates))
            result = preimage_protocol.commit_candidates(ep, snapshot, rows)
            self.assertEqual(result["status"], "PASS")
            self.assertTrue(preimage_protocol.barrier_ready(ep))

    def test_transaction_authority_guard_decides_inside_the_lock(self):
        def commit(ep: Path, guard):
            return authority_commit.commit_transaction(
                ep, "meta/story-gates.json",
                expected_sha=authority_commit.sha(ep / "meta/story-gates.json"),
                authority_guard=guard, snapshot_id="s", task_ids=["t"], node_ids=["n"],
                patches=[("character.finalize", {"new": True})],
                candidate_paths=["c"], replace_existing_scopes={"character.finalize"})

        with tempfile.TemporaryDirectory() as raw:
            ep = Path(raw)
            (ep / "meta").mkdir()
            _write_gates(ep, _owned_fixture())
            before = (ep / "meta/story-gates.json").read_bytes()
            self.assertEqual(commit(ep, lambda: False)["status"], "STALE")
            self.assertEqual((ep / "meta/story-gates.json").read_bytes(), before)

        with tempfile.TemporaryDirectory() as raw:
            ep = Path(raw)
            (ep / "meta").mkdir()
            _write_gates(ep, _owned_fixture())
            self.assertEqual(commit(ep, lambda: True)["status"], "PASS")
            self.assertEqual(_read_gates(ep)["character"]["finalize"], {"new": True})


if __name__ == "__main__":
    unittest.main()
