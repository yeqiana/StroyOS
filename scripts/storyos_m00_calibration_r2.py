#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Isolated real-image M00 test. NOT a production Attempt / Episode authority.

This is an opt-in TEST_ONLY native Codex experiment with a machine-wide image
capacity permit, independent private receipts, and no automatic retry.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "episodes" / "_system"
sys.path.insert(0, str(SYSTEM))

import codex_subscription_image
import codex_user_runner
import global_image_capacity
import m00_calibration_receipts
import m00_capture_profile_contract
import m00_scene_fidelity_guard
import m00_style_guard
import visual_profile_bridge_v224

PRIVATE = ROOT / ".storyos/user-visual-references"
OLD_PLAN = PRIVATE / "calibration-plans/m00-four-scene-20261013.json"
CONFIG = ROOT / "standards/m00_calibration_cases_r2.json"
OUTPUT = PRIVATE / "test-only-calibration"
_BEGIN = "----- LOCKED DEVICE CAPTURE PHYSICS -----"
_END = "----- END LOCKED DEVICE CAPTURE PHYSICS -----"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stable_hash(value: object) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("M00_TESTONLY_INVALID_JSON_OBJECT")
    return data


def rebind_capture_device(base_visual: str, device_text: str) -> str:
    """Use already frozen M00/Capture Grammar; only swap the TEST's device."""
    source = str(base_visual)
    if not m00_style_guard.is_m00(source) or source.count(_BEGIN) != 1 or source.count(_END) != 1:
        raise ValueError("M00_TESTONLY_VISUAL_BASE_INVALID")
    prefix, rest = source.split(_BEGIN + "\n", 1)
    _, suffix = rest.split("\n" + _END, 1)
    return prefix + _BEGIN + "\n" + device_text + "\n" + _END + suffix


def make_bundle(case_id: str, *, repo: Path = ROOT, base_visual: str | None = None) -> dict:
    root = repo.resolve()
    options = read_json(root / "standards/m00_calibration_cases_r2.json")
    matches = [row for row in options.get("cases", []) if isinstance(row, dict) and row.get("id") == case_id]
    if not options.get("test_only") or len(matches) != 1:
        raise ValueError("M00_TESTONLY_CASE_UNKNOWN")
    case = matches[0]
    if case_id not in {"C02", "C04"} or case.get("new_frame_id") != case_id + "-R2":
        raise ValueError("M00_TESTONLY_REVISION_INVALID")
    plan_path = root / ".storyos/user-visual-references/calibration-plans/m00-four-scene-20261013.json"
    old = read_json(plan_path)
    if old.get("purpose") != "M00_CROSS_GENRE_PIXEL_CALIBRATION_NOT_PRODUCTION":
        raise ValueError("M00_TESTONLY_OLD_PLAN_INVALID")
    originals = [row for row in old.get("frames", []) if isinstance(row, dict) and row.get("id") == case_id]
    if len(originals) != 1 or originals[0].get("capture_profile") != case.get("capture_profile"):
        raise ValueError("M00_TESTONLY_CAPTURE_PROFILE_DRIFT")
    scene = str(case.get("scene_prompt") or "").strip()
    evidence = case.get("observable_evidence")
    if len(scene) < 60 or not isinstance(evidence, list) or len(evidence) < 3 or any(
        not isinstance(value, str) or not value.strip() for value in evidence
    ):
        raise ValueError("M00_TESTONLY_VISIBLE_EVIDENCE_MISSING")
    if "由故事定义" in scene or "待定义" in scene:
        raise ValueError("M00_TESTONLY_EVENT_UNDERDEFINED")

    ref_base = (root / ".storyos/user-visual-references").resolve()
    refs = originals[0].get("references")
    if not isinstance(refs, list) or not 1 <= len(refs) <= 2:
        raise ValueError("M00_TESTONLY_REFERENCE_COUNT")
    reference_paths: list[Path] = []
    reference_rows: list[dict] = []
    for row in refs:
        if not isinstance(row, dict) or row.get("kind") != "capture_style":
            raise ValueError("M00_TESTONLY_REFERENCE_NOT_STYLE")
        path = (root / str(row.get("path") or "")).resolve()
        if not path.is_relative_to(ref_base) or not path.is_file():
            raise ValueError("M00_TESTONLY_REFERENCE_OUTSIDE_PRIVATE_SCOPE")
        sha = str(row.get("sha256") or "").lower()
        if len(sha) != 64 or digest(path) != sha:
            raise ValueError("M00_TESTONLY_REFERENCE_SHA_DRIFT")
        reference_paths.append(path)
        reference_rows.append({"path": path.relative_to(root).as_posix(), "sha256": sha,
                               "kind": "capture_style", "role": "camera_physics_only"})
    device = m00_capture_profile_contract.compile_device_contract(str(case["capture_profile"]), root=root)
    # compile_prompt_contract resolves immutable M00 mother grammar; no Episode is mutated.
    baseline = base_visual or visual_profile_bridge_v224.compile_prompt_contract(root / "episodes")["text"]
    visual = rebind_capture_device(baseline, device["text"])
    prompt = m00_style_guard.enforce(scene_prompt=scene, visual_contract=visual)
    prompt = m00_scene_fidelity_guard.enforce_event(
        scene_prompt=prompt, source_scene_prompt=scene, visual_contract=visual)
    prompt = m00_scene_fidelity_guard.enforce_motion(scene_prompt=prompt, visual_contract=visual)
    identity = {
        "test_only": True, "case": case_id, "revision": "R2",
        "scene_sha256": hashlib.sha256(scene.encode("utf-8")).hexdigest(),
        "case_file_sha256": digest(root / "standards/m00_calibration_cases_r2.json"),
        "plan_sha256": digest(plan_path),
        "device_profile_sha256": device["sha256"],
        "visual_contract_sha256": hashlib.sha256(visual.encode("utf-8")).hexdigest(),
        "references": reference_rows, "scene_prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
    }
    fp = stable_hash(identity)
    request = {
        "request_fingerprint": fp, "payload_model": "gpt-image-2.5-flare",
        "payload_quality": "high", "canvas": {"width": 1080, "height": 1350, "aspect_ratio": "4:5"},
        "references": reference_rows, "scene_prompt": prompt,
    }
    instructions = codex_subscription_image.payload_transport_prompt(request, "1080x1350", len(reference_rows))
    instructions += "\nTEST_ONLY_EXPERIMENT; NEVER CLAIM EPISODE OR MYSQL AUTHORITY; NO SHELL OR OTHER TOOLS."
    return {"identity": identity, "request": request, "prompt": instructions,
            "device": device, "ref_paths": reference_paths,
            "case": case, "fingerprint": fp, "out": root / ".storyos/user-visual-references/test-only-calibration" / case["new_frame_id"]}


def _atomic_update(path: Path, data: dict) -> None:
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _image_candidates(wd: Path) -> list[Path]:
    artifacts = codex_user_runner.exported_artifacts_dir(wd)
    candidates = []
    if artifacts.is_dir():
        candidates += [f for f in artifacts.rglob("*")
                       if f.is_file() and f.suffix.lower() in {".png", ".jpeg", ".jpg", ".webp"}]
    if (wd / "out.png").is_file():
        candidates.append(wd / "out.png")
    return candidates


def _copy_real_image(source: Path, destination: Path) -> list[int]:
    from PIL import Image
    if destination.exists():
        raise ValueError("M00_TESTONLY_OUTPUT_ALREADY_EXISTS")
    with Image.open(source) as image:
        image.verify()
    with Image.open(source) as image:
        dims = [image.width, image.height]
        if min(dims) < 512 or max(dims) > 10000:
            raise ValueError("M00_TESTONLY_OUTPUT_DIMENSIONS_INVALID")
        image.convert("RGB").save(destination, format="PNG")
    return dims


def execute_bundle(bundle: dict, *, timeout: int = 360) -> dict:
    """Execute one verified Test-only bundle; same native Bridge and OS permits."""
    if not 60 <= timeout <= 900:
        raise ValueError("M00_TESTONLY_TIMEOUT_INVALID")
    folder = bundle["out"]
    folder.mkdir(parents=True, exist_ok=True)
    receipt_path = folder / "test-only-record.json"
    if receipt_path.exists():
        raise ValueError("M00_TESTONLY_ALREADY_DISPATCHED_NO_RETRY")
    with global_image_capacity.image_permits(1, wait_seconds=45):
        # Exclusive creation is the one-shot guard across repeated sessions/processes.
        evidence = {
            "frame": bundle["case"]["new_frame_id"], "status": "STARTED",
            "mock": {"authority": "TEST_ONLY_LOCAL", "production_authority": False,
                     "mysql_attempt": False, "episode_authority": False},
            "request_id": str(uuid.uuid4()), "request_fingerprint": bundle["fingerprint"],
            "request_identity": bundle["identity"], "capture_profile": bundle["device"]["profile_id"],
            "references": bundle["request"]["references"],
            "transport_model": "gpt-6-luna", "transport_effort": "high",
            "model_requested": "gpt-image-2.5-flare", "quality_requested": "high",
            "start_time": time.time(), "output": None,
        }
        with receipt_path.open("x", encoding="utf-8") as file:
            json.dump(evidence, file, ensure_ascii=False, indent=2)
        try:
            with codex_user_runner.workspace(prefix="m00-r2-test-") as temporary:
                wd = Path(temporary)
                proxies = [
                    codex_subscription_image._reference_proxy(reference, wd, index)
                    for index, reference in enumerate(bundle["ref_paths"], 1)
                ]
                executable = codex_subscription_image.resolve_codex(None)
                command = codex_subscription_image.execution_command_prefix(executable) + [
                    "exec", "--skip-git-repo-check", "--ephemeral", "--ignore-rules",
                    "-c", "skills.include_instructions=false", "-c", "project_doc_max_bytes=0",
                    "--enable", "image_generation", "-m", "gpt-6-luna",
                    "-c", 'model_reasoning_effort="high"',
                    "-s", codex_subscription_image.image_worker_sandbox_mode(
                        bridged=codex_user_runner.bridge_required(), has_references=True),
                    "-C", str(wd), "--json",
                ]
                for proxy in proxies:
                    command.extend(["-i", str(proxy)])
                command.append("-")
                with (folder / "codex-events.jsonl").open("w", encoding="utf-8") as sink:
                    result = codex_user_runner.run_model_codex(
                        command, input=bundle["prompt"], stdout=sink, stderr=subprocess.STDOUT,
                        cwd=wd, timeout=timeout, text=True, encoding="utf-8", errors="replace",
                        check=False, task_type="image", codex_home_mode="inherit",
                        request_id=evidence["request_id"])
                images = _image_candidates(wd)
                # Never accept extra unrelated files as image_generation evidence.
                evidence["codex_returncode"] = result.returncode
                evidence["runner_transport"] = codex_user_runner.provider_transport_evidence(
                    getattr(result, "remote", {}))
                if result.returncode == 0 and len(images) == 1:
                    final = folder / "generated.png"
                    evidence["dimensions"] = _copy_real_image(images[0], final)
                    evidence["output"] = final.relative_to(ROOT).as_posix()
                    evidence["output_sha256"] = digest(final)
                    evidence["image_artifact_count"] = 1
                    evidence["status"] = "IMAGE_CREATED"
                else:
                    evidence["status"] = "OUTCOME_UNKNOWN" if images or result.returncode != 0 else "NO_IMAGE_ARTIFACT"
                    evidence["image_artifact_count"] = len(images)
        except Exception as exc:
            evidence.update(status="OUTCOME_UNKNOWN", error_type=type(exc).__name__,
                            error_summary=str(exc)[:180])
        finally:
            evidence["finish_time"] = time.time()
            _atomic_update(receipt_path, evidence)
        return evidence


def execute(case_id: str, *, timeout: int = 360) -> dict:
    return execute_bundle(make_bundle(case_id), timeout=timeout)


def recover(case_id: str, *, generated_images_root: Path | None = None) -> dict:
    """Recover one already-produced image using the *same* durable request.

    Never invokes Codex, image_generation, or a new request. No automatic retry.
    """
    bundle = make_bundle(case_id)
    folder = bundle["out"]
    receipt_path = folder / "test-only-record.json"
    if not receipt_path.is_file():
        raise ValueError("M00_TESTONLY_RECOVERY_NO_ORIGINAL_REQUEST")
    doc = read_json(receipt_path)
    if doc.get("status") != "OUTCOME_UNKNOWN" or doc.get("request_fingerprint") != bundle["fingerprint"]:
        raise ValueError("M00_TESTONLY_RECOVERY_NOT_ALLOWED")
    rid = str(doc.get("request_id") or "")
    if not rid or (folder / "generated.png").exists():
        raise ValueError("M00_TESTONLY_RECOVERY_OUTPUT_OR_REQUEST_INVALID")
    durable = codex_user_runner.read_task_result(rid)
    if not isinstance(durable, dict) or durable.get("request_id") != rid or durable.get("returncode") != 124:
        raise ValueError("M00_TESTONLY_RECOVERY_DURABLE_TIMEOUT_NOT_PROVEN")
    proof = durable.get("evidence") or {}
    thread_ids = proof.get("thread_ids") or []
    artifacts = proof.get("generated_artifacts") or []
    if len(thread_ids) != 1 or len(artifacts) != 1:
        raise ValueError("M00_TESTONLY_RECOVERY_THREAD_ARTIFACT_AMBIGUOUS")
    candidate = Path(str(artifacts[0]))
    if (candidate.is_absolute() or ".." in candidate.parts or len(candidate.parts) < 2
            or candidate.parts[0] != str(thread_ids[0]) or candidate.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}):
        raise ValueError("M00_TESTONLY_RECOVERY_ARTIFACT_PATH_INVALID")
    source_root = (generated_images_root or Path.home() / ".codex/generated_images").resolve()
    source = (source_root / candidate).resolve()
    if not source.is_relative_to(source_root) or not source.is_file():
        raise ValueError("M00_TESTONLY_RECOVERY_ARTIFACT_MISSING")
    destination = folder / "generated.png"
    dims = _copy_real_image(source, destination)
    doc.update(status="IMAGE_RECOVERED_AFTER_RUNNER_TIMEOUT",
               output=destination.relative_to(ROOT).as_posix(), output_sha256=digest(destination),
               dimensions=dims, image_artifact_count=1,
               recovery={"type": "THREAD_SCOPED_DURABLE_ARTIFACT", "runner_returncode": 124,
                         "request_id": rid, "thread_id": str(thread_ids[0]),
                         "original_path": candidate.as_posix(), "source_sha256": digest(source),
                         "different_from_clean_completion": True},
               recovered_at=time.time())
    _atomic_update(receipt_path, doc)
    return doc


def status(case_id: str) -> dict:
    bundle = make_bundle(case_id)
    folder = bundle["out"]
    record = folder / "test-only-record.json"
    baseline = OUTPUT / case_id / "test-only-record.json"
    old = read_json(baseline) if baseline.is_file() else {}
    fresh = read_json(record) if record.is_file() else {}
    truth = m00_calibration_receipts.inspect_frame(OUTPUT, bundle["case"]["new_frame_id"])
    return {
        "case": case_id, "new_status": truth["status"],
        "new_verified": truth["verified"],
        "old_sha256": old.get("output_sha256"),
        "new_sha256": fresh.get("output_sha256"),
        "new_capture_profile": fresh.get("capture_profile"),
        "new_request_fingerprint_matches": fresh.get("request_fingerprint") == bundle["fingerprint"] if fresh else None,
        "required_visible_evidence": bundle["case"]["observable_evidence"],
        "pixel_review_status": "PENDING_ACTUAL_PIXELS",
        "automatically_approved": False,
        "retry_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("plan", "run", "status", "recover"))
    parser.add_argument("--case", choices=("C02", "C04"), required=True)
    parser.add_argument("--ack-testonly-paid-image", action="store_true")
    parser.add_argument("--timeout", type=int, default=360)
    args = parser.parse_args()
    if args.operation == "plan":
        plan = make_bundle(args.case)
        print(json.dumps({"case": args.case, "new_frame_id": plan["case"]["new_frame_id"],
                          "capture_profile": plan["device"]["profile_id"],
                          "device_sha256": plan["device"]["sha256"],
                          "request_fingerprint": plan["fingerprint"],
                          "reference_sha_verified": len(plan["ref_paths"]),
                          "expected_visual_evidence": plan["case"]["observable_evidence"],
                          "status": "READY_NOT_DISPATCHED", "test_only": True}, ensure_ascii=False))
        return 0
    if args.operation == "status":
        print(json.dumps(status(args.case), ensure_ascii=False))
        return 0
    if args.operation == "recover":
        recovered = recover(args.case)
        print(json.dumps({"frame": recovered["frame"], "status": recovered["status"],
                          "output_sha256": recovered["output_sha256"],
                          "new_image_generation_calls": 0}, ensure_ascii=False))
        return 0
    if not args.ack_testonly_paid_image:
        raise SystemExit("M00_TESTONLY_EXPLICIT_ACK_REQUIRED")
    evidence = execute(args.case, timeout=args.timeout)
    print(json.dumps({"frame": evidence["frame"], "status": evidence["status"],
                      "request_id": evidence["request_id"],
                      "output_sha256": evidence.get("output_sha256"),
                      "dimensions": evidence.get("dimensions"),
                      "error_type": evidence.get("error_type")}, ensure_ascii=False))
    return 0 if evidence["status"] == "IMAGE_CREATED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
