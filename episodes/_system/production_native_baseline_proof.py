"""One-shot production Visual Lock baseline capability preflight.

Never marks a review PASS. The actual pixel operation still requires the
canonical MySQL Generation Attempt, global capacity, and provider gateway.
"""
from __future__ import annotations
import hashlib
import json
import re
from pathlib import Path
import codex_subscription_image
import episode_state_persistence
import generation_attempt_authority
import image_model_policy
import image_payload_transport
import logical_asset_identity
import story_json
import runtime_request
import runtime_router
import storage_config

ROOT = Path(__file__).resolve().parents[2]

REASON = "PRODUCTION_NATIVE_VISUAL_BASELINE_FIRST_ATTEMPT_PROOF"
PLAN = [(1, "ordinary_baseline"), (16, "worst_capture_condition"),
        (8, "first_major_anomaly"), (17, "high_impact_admission")]
# One-shot production proof is scoped to named Episodes with already frozen
# 1+3 admissions. This is not a general UNKNOWN-capability override.
PRODUCTION_EPISODE_PLANS = {
    "06_五十亩山地之后_全新重制": PLAN,
    "13_失物归还的那扇门": [
        (1, "ordinary_baseline"), (8, "worst_capture_condition"),
        (3, "first_major_anomaly"), (18, "high_impact_admission"),
    ],
}


def verified_second_baseline_retry(ep: Path, item: dict) -> bool:
    """Exact Episode 13 network-failed Attempt 1, never a general entitlement."""
    try:
        ep = Path(ep).resolve()
        if (ep.name != "13_失物归还的那扇门"
                or ep.parent.name != "00_独立篇"
                or item.get("scope") != "visual_lock"
                or int(item.get("frame") or 0) != 1
                or item.get("technical_retry_source_code") != "IMAGE_BACKEND_ERROR"
                or item.get("generation_attempt_reason") != "TECHNICAL_RETRY"):
            return False
        key = logical_asset_identity.frame_asset_key(ep, 1)
        previous = generation_attempt_authority.load_attempt(ep, key, 1) or {}
        return bool(
            previous.get("attempt_index") == 1
            and previous.get("status") == "FAILED_AFTER_DISPATCH"
            and previous.get("failure_class") == "IMAGE_TOOL_NETWORK_ERROR_DURABLE_RECEIPT"
            and previous.get("result_ref") in (None, "")
            and previous.get("provider") == "codex_subscription"
            and previous.get("payload_model") == "gpt-image-2.5-flare"
            and previous.get("payload_quality") == "high"
            and previous.get("dispatch_committed_at")
            and previous.get("generation_observed_at")
            and previous.get("generation_key") ==
                generation_attempt_authority.stable_generation_key(
                    previous["episode_id"], key, 1)
        )
    except Exception:
        return False


def _verified_baseline_plan(ep: Path, rows: list[dict]) -> list[tuple[int, str]] | None:
    """Admit a new Episode only with a SHA-bound deterministic frozen plan."""
    legacy = PRODUCTION_EPISODE_PLANS.get(ep.name)
    if legacy is not None:
        return legacy
    import visual_lock_v21
    proposed = visual_lock_v21.choose_plan(ep)
    expected = proposed.get("items") or []
    roles = (
        "ordinary_baseline", "worst_capture_condition",
        "first_major_anomaly", "high_impact_admission",
    )
    if (len(rows) != 4 or len(expected) != 4
            or [r.get("role") for r in rows] != list(roles)
            or len({int(r.get("frame") or 0) for r in rows}) != 4):
        return None
    for actual, selected in zip(rows, expected):
        if any(str(actual.get(key) or "") != str(selected.get(key) or "")
               for key in ("id", "frame", "role", "contract_sha256")):
            return None
        if not re.fullmatch(r"[0-9a-f]{64}", str(actual.get("contract_sha256") or "")):
            return None
    policy = proposed.get("policy") or {}
    if policy.get("baseline_first") is not True or int(policy.get("calibration_count") or 0) != 4:
        return None
    return [(int(r["frame"]), str(r["role"])) for r in rows]


def eligible(ep: Path, item: dict, payload: dict, controller: dict,
             *, blocked_predispatch: bool = False, queue_override: dict | None = None) -> bool:
    """Read-only fail-closed admission for *only* the first official pixel."""
    try:
        ep = Path(ep).resolve()
        if (not ep.is_relative_to(ROOT / "episodes")
                or ep.parent.name != "00_独立篇"):
            return False
        path = ep / "meta/visual-lock-plan.json"
        if not path.is_file():
            return False
        rows = story_json.read_json(path).get("items") or []
        plan = _verified_baseline_plan(ep, rows)
        if plan is None:
            return False
        frame_set = {frame for frame, _role in plan}
        if len(frame_set) != 4 or plan[0][0] != 1:
            return False
        if ep.name not in PRODUCTION_EPISODE_PLANS:
            _, source = episode_state_persistence.load_with_source(ep)
            if source != "mysql":
                return False
        verified_retry = verified_second_baseline_retry(ep, item)
        if verified_retry and generation_attempt_authority.load_attempt(
                ep, logical_asset_identity.frame_asset_key(ep, 1), 2) is not None:
            return False
        episode_request = runtime_request.effective_for_episode(ep) or {}
        if (episode_request.get("mode") != "full_auto"
                or (episode_request.get("runtime") or {}).get("execution_mode") != "dag"
                or runtime_router.image_execution_runtime()[0] != "CODEX"):
            return False
        db = storage_config.mysql_connection_kwargs()
        if (str(db.get("host")) not in ("127.0.0.1", "localhost")
                or not 1 <= int(db.get("port") or 0) <= 65535):
            return False
        if (episode_state_persistence.load(ep) or {}).get("current_state") != "STORYBOARD_LOCKED":
            return False
        if (int(item.get("frame") or 0) != 1 or item.get("scope") != "visual_lock"
                or item.get("kind") != "original"
                or (not verified_retry and
                    (item.get("technical_retry_source_code")
                     or item.get("generation_attempt_reason") not in
                        ("", None, "PRIMARY_GENERATION")))):
            return False
        if ([(int(x.get("frame") or 0), x.get("role")) for x in rows] != plan
                or [list(x.get("depends_on") or []) for x in rows] != [[], [1], [1], [1]]):
            return False
        review = (story_json.read_json(ep / "meta/story-gates.json").get("reviews") or {})
        if review.get("story") != "passed" or any(
                review.get(k) != "pending" for k in ("visual_admission", "authenticity", "continuity")):
            return False
        import image_scheduler
        queue = (queue_override if queue_override is not None
                 else image_scheduler.load_queue(ep)).get("items") or []
        if len(queue) != 4:
            return False
        indexed = {int(x.get("frame") or 0): x for x in queue}
        if sorted(indexed) != sorted(frame_set):
            return False
        if (indexed[1].get("id") != item.get("id")
                or indexed[1].get("status") not in (
                    ("blocked",) if blocked_predispatch
                    else ("queued", "running", "generating"))):
            return False
        if any(indexed[f].get("scope") != "visual_lock"
               or indexed[f].get("kind") != "original"
               or list(indexed[f].get("depends_on") or []) != ([] if f == 1 else [1])
               or (f != 1 and indexed[f].get("status") != "queued")
               for f in sorted(frame_set)):
            return False
        if any(r.get("output_path") or r.get("candidate_output_path")
               for r in indexed.values()):
            return False
        native = image_payload_transport.selected_route(1)
        policy = image_model_policy.for_episode(ep)
        if (native.get("provider") != "codex_subscription"
                or payload.get("model") != "gpt-image-2.5-flare"
                or payload.get("quality") != "high"
                or policy.get("model") != "gpt-image-2.5-flare"
                or policy.get("quality") != "high"
                or item.get("model") != "gpt-image-2.5-flare"
                or controller.get("model") != "gpt-6-luna"
                or controller.get("reasoning_effort") != "high"
                or not re.fullmatch(r"[0-9a-f]{64}", str(controller.get("model_policy_sha256") or ""))):
            return False
        for frame in sorted(frame_set):
            key = logical_asset_identity.frame_asset_key(ep, frame)
            state = generation_attempt_authority.load_asset_state(ep, key)
            consumed = int(state.get("attempts_consumed") or 0)
            if state.get("active_attempt_index") is not None:
                return False
            if (consumed != 1 if verified_retry and frame == 1
                    else consumed != 0):
                return False
        return True
    except Exception:
        return False


# A true content fix, never an operator-signed visual PASS.
BASELINE_CONTENT_REPAIR_REASON = "PRODUCTION_NATIVE_VISUAL_LOCK_BASELINE_CONTENT_REPAIR"


def eligible_baseline_content_repair(ep: Path, item: dict, payload: dict,
                                     controller: dict) -> bool:
    """Exact, one-time native image repair after one proven network loss."""
    try:
        import image_scheduler
        import visual_lock_baseline_gate
        import visual_profile_review_persistence
        import production_ledger

        ep = Path(ep).resolve()
        if (ep.name != "13_失物归还的那扇门"
                or ep.parent.name != "00_独立篇"
                or not ep.is_relative_to(ROOT / "episodes")
                or item.get("scope") != "repair"
                or item.get("kind") != "baseline_candidate"
                or int(item.get("frame") or 0) != 1
                or item.get("generation_attempt_reason") != "VISUAL_LOCK_CONTENT_REPAIR"
                or not str(item.get("capture_id") or "").startswith(
                    "visual-lock-candidate-")
                or item.get("model") != "gpt-image-2.5-flare"):
            return False
        request = runtime_request.effective_for_episode(ep) or {}
        db = storage_config.mysql_connection_kwargs()
        if (request.get("mode") != "full_auto"
                or (request.get("runtime") or {}).get("execution_mode") != "dag"
                or runtime_router.image_execution_runtime()[0] != "CODEX"
                or str(db.get("host")) not in {"127.0.0.1", "localhost"}
                or int(db.get("port") or 0) != 3307
                or (episode_state_persistence.load(ep) or {}).get("current_state") != "STORYBOARD_LOCKED"):
            return False
        if (payload.get("model") != "gpt-image-2.5-flare"
                or payload.get("quality") != "high"
                or controller.get("model") != "gpt-6-luna"
                or controller.get("reasoning_effort") != "high"
                or image_payload_transport.selected_route(1).get("provider") != "codex_subscription"):
            return False
        key = logical_asset_identity.frame_asset_key(ep, 1)
        first = generation_attempt_authority.load_attempt(ep, key, 1) or {}
        second = generation_attempt_authority.load_attempt(ep, key, 2) or {}
        third = generation_attempt_authority.load_attempt(ep, key, 3)
        state = generation_attempt_authority.load_asset_state(ep, key)
        if (first.get("status") != "FAILED_AFTER_DISPATCH"
                or first.get("failure_class") != "IMAGE_TOOL_NETWORK_ERROR_DURABLE_RECEIPT"
                or second.get("status") != "SUCCEEDED"
                or second.get("provider") != "codex_subscription"
                or not second.get("result_ref")
                or third is not None
                or state.get("attempts_consumed") != 2
                or state.get("active_attempt_index") is not None):
            return False
        evidence = story_json.read_json(
            ep / "meta/runtime/native-baseline-frame01-tool-proof.json")
        if (evidence.get("proof_kind") != "TRUSTED_NATIVE_RUNNER_THREAD_SCOPED_IMAGE_SHA"
                or evidence.get("generation_key") != second.get("generation_key")):
            return False
        queue = image_scheduler.load_queue(ep).get("items") or []
        if (len(queue) != 5
                or sum(int(r.get("frame") or 0) == 1 for r in queue) != 2
                or not any(r.get("id") == item.get("id") and r.get("status") in
                           {"queued", "running", "generating"} for r in queue)
                or sorted(int(r.get("frame") or 0) for r in queue) != [1, 1, 3, 8, 18]
                or not all(r.get("status") == "generated" for r in queue
                           if r.get("id") != item.get("id"))):
            return False
        ledger = production_ledger.load_authority(ep, default={}) or {}
        baseline = (ledger.get("frames") or {}).get("01") or {}
        ledger_state = str(baseline.get("status") or "")
        latest = (baseline.get("attempts") or [{}])[-1]
        active_is_exact_candidate = (
            ledger_state == "REPAIRING"
            and latest.get("kind") == "baseline_candidate"
            and latest.get("result") == "pending"
            and (latest.get("request") or {}).get("capture_id") == item.get("capture_id")
            and latest.get("runtime_transaction_id")
        )
        if (not (ledger_state == "NEEDS_USER" or active_is_exact_candidate)
                or int(baseline.get("content_repairs_used") or 0) != 0
                or (baseline.get("current_candidate") or {}).get("sha256")
                   != evidence.get("normalized_png_sha256")
                or visual_lock_baseline_gate.validate_review(ep)):
            return False
        prior_baseline_review = story_json.read_json(
            ep / visual_lock_baseline_gate.REL)
        if (prior_baseline_review.get("status") != "LOCKED"
                or prior_baseline_review.get("decision") != "PASS"
                or prior_baseline_review.get("sha256")
                   != evidence.get("normalized_png_sha256")):
            return False
        review = visual_profile_review_persistence.load(ep) or {}
        row = next((x for x in review.get("calibration") or []
                    if x.get("id") == "V-B" and int(x.get("frame") or 0) == 1),
                   None)
        return bool(row and (row.get("issues") or
                    any(v is not True for v in (row.get("checks") or {}).values())))
    except Exception:
        return False


FOLLOWON_REASON = "PRODUCTION_NATIVE_VISUAL_LOCK_AFTER_REVIEWED_BASELINE"


def eligible_reviewed_followon(ep: Path, item: dict, payload: dict, controller: dict) -> bool:
    """Scoped Episode 13 M00 follow-on, requiring real reviewed first-frame pixels."""
    try:
        import codex_user_runner
        import image_scheduler
        import visual_lock_baseline_gate

        ep = Path(ep).resolve()
        frame = int(item.get("frame") or 0)
        if (ep.name != "13_失物归还的那扇门"
                or ep.parent.name != "00_独立篇"
                or not ep.is_relative_to(ROOT / "episodes")
                or frame not in {3, 8, 18}
                or item.get("scope") != "visual_lock"
                or item.get("kind") != "original"
                or item.get("model") != "gpt-image-2.5-flare"):
            return False
        request = runtime_request.effective_for_episode(ep) or {}
        db = storage_config.mysql_connection_kwargs()
        if (request.get("mode") != "full_auto"
                or (request.get("runtime") or {}).get("execution_mode") != "dag"
                or runtime_router.image_execution_runtime()[0] != "CODEX"
                or str(db.get("host")) not in {"127.0.0.1", "localhost"}
                or int(db.get("port") or 0) != 3307
                or (episode_state_persistence.load(ep) or {}).get("current_state") != "STORYBOARD_LOCKED"):
            return False
        plan = story_json.read_json(ep / "meta/visual-lock-plan.json").get("items") or []
        if ([(int(r.get("frame") or 0), r.get("role")) for r in plan]
                != PRODUCTION_EPISODE_PLANS[ep.name]
                or [list(r.get("depends_on") or []) for r in plan] != [[], [1], [1], [1]]):
            return False
        if (image_payload_transport.selected_route(1).get("provider") != "codex_subscription"
                or payload.get("model") != "gpt-image-2.5-flare"
                or payload.get("quality") != "high"
                or image_model_policy.for_episode(ep).get("model") != "gpt-image-2.5-flare"
                or controller.get("model") != "gpt-6-luna"
                or controller.get("reasoning_effort") != "high"):
            return False
        queue = image_scheduler.load_queue(ep).get("items") or []
        by_frame = {int(r.get("frame") or 0): r for r in queue}
        if (len(queue) != 4 or set(by_frame) != {1, 3, 8, 18}
                or by_frame[1].get("status") != "generated"
                or by_frame[frame].get("id") != item.get("id")
                or by_frame[frame].get("status") not in {"queued", "running", "generating"}
                or any(r.get("scope") != "visual_lock"
                       or list(r.get("depends_on") or []) != [1]
                       for n, r in by_frame.items() if n != 1)
                or not visual_lock_baseline_gate.approved(ep)):
            return False
        key = logical_asset_identity.frame_asset_key(ep, 1)
        first = generation_attempt_authority.load_attempt(ep, key, 2) or {}
        first_state = generation_attempt_authority.load_asset_state(ep, key)
        current = generation_attempt_authority.load_asset_state(
            ep, logical_asset_identity.frame_asset_key(ep, frame))
        if (first.get("status") != "SUCCEEDED"
                or first.get("provider") != "codex_subscription"
                or first.get("payload_model") != "gpt-image-2.5-flare"
                or first_state.get("attempts_consumed") != 2
                or first_state.get("active_attempt_index") is not None
                or current.get("attempts_consumed") != 0
                or current.get("active_attempt_index") is not None):
            return False
        evidence = story_json.read_json(ep / "meta/runtime/native-baseline-frame01-tool-proof.json")
        if (evidence.get("proof_kind") != "TRUSTED_NATIVE_RUNNER_THREAD_SCOPED_IMAGE_SHA"
                or evidence.get("status") != "OBSERVED_AWAITING_INDEPENDENT_VISUAL_REVIEW"
                or evidence.get("generation_key") != first.get("generation_key")
                or evidence.get("attempt_index") != 2
                or evidence.get("visual_review_pass") is not False
                or evidence.get("provider_model_attested") is not False):
            return False
        raw = list((ep / "media/raw").glob("01-*.png"))
        candidate = ROOT / str(by_frame[1].get("output_path") or "")
        runner_id = str(evidence.get("runner_request_id") or "")
        receipt = ROOT / "runtime/codex-user-runner/task-results" / (runner_id + ".json")
        if (len(raw) != 1 or not candidate.is_file() or not receipt.is_file()
                or hashlib.sha256(raw[0].read_bytes()).hexdigest() != evidence.get("raw_png_sha256")
                or hashlib.sha256(candidate.read_bytes()).hexdigest() != evidence.get("normalized_png_sha256")
                or hashlib.sha256(receipt.read_bytes()).hexdigest() != evidence.get("runner_receipt_sha256")):
            return False
        home, _ = codex_user_runner.codex_home()
        source_root = (home / "generated_images").resolve()
        exported = (source_root / str(evidence.get("exported_artifact_relative_path") or "")).resolve()
        return bool(exported.is_relative_to(source_root) and exported.is_file()
                    and hashlib.sha256(exported.read_bytes()).hexdigest() == evidence["raw_png_sha256"])
    except Exception:
        return False


def attest_secondary(strict: dict, payload: dict, controller: dict, codex: str | None) -> dict | None:
    """Verify native text-only tool visibility without treating it as pixel PASS."""
    if (strict.get("status") != "BLOCKED"
            or strict.get("failure_class") != "LOGIN_AUTH_IMAGE_TOOL_CAPABILITY_UNKNOWN"
            or strict.get("image_generation_called") is not False
            or strict.get("image_attempt_authority_called") is not False):
        return None
    try:
        probe = codex_subscription_image.payload_capability_preflight(
            model=payload["model"], quality=payload["quality"], codex_raw=codex,
            allow_unknown_capability_proof=True)
    except Exception:
        return None
    if (probe.get("status") != "READY_FOR_REAL_CAPABILITY_PROOF"
            or probe.get("tool_capability_state") != "UNKNOWN"
            or probe.get("image_generation_visible_secondary") is not True
            or probe.get("visibility_response_completed") is not True
            or probe.get("tool_visibility_evidence_level") != "SECONDARY_ATTESTATION"
            or probe.get("session_start") != "PASS"
            or probe.get("candidate_catalog_member") is not True
            or probe.get("provider") != "codex_subscription"
            or probe.get("payload_model") != payload.get("model")
            or probe.get("payload_quality") != payload.get("quality")
            or probe.get("transport_model") != controller.get("model")
            or probe.get("transport_effort") != controller.get("reasoning_effort")
            or probe.get("image_generation_called") is not False
            or probe.get("image_attempt_authority_called") is not False
            or probe.get("explicit_negative_evidence") is not False
            or not re.fullmatch(r"[0-9a-f]{64}", str(probe.get("catalog_sha256") or ""))):
        return None
    return probe


def first_attempt_only(lease: dict) -> bool:
    return bool(isinstance(lease, dict) and int(lease.get("attempt_index") or 0) == 1
                and int(lease.get("fencing_token") or 0) > 0
                and lease.get("generation_key") and lease.get("lease_token"))


def admitted_baseline_lease(ep: Path, item: dict, lease: dict) -> bool:
    if first_attempt_only(lease):
        return True
    return bool(
        isinstance(lease, dict)
        and verified_second_baseline_retry(ep, item)
        and int(lease.get("attempt_index") or 0) == 2
        and int(lease.get("fencing_token") or 0) == 2
        and lease.get("generation_key")
        and lease.get("lease_token")
    )


def evidence_sha(probe: dict) -> str:
    stable = {k: probe.get(k) for k in ("catalog_sha256", "transport_model",
        "transport_effort", "payload_model", "payload_quality",
        "tool_visibility_evidence_level", "image_generation_visible_secondary")}
    return hashlib.sha256(json.dumps(stable, sort_keys=True).encode()).hexdigest()



def observe_real_tool_pixel(log: Path, pixel: Path) -> dict | None:
    """Inspect actual Codex JSONL and an actual PNG, never model prose."""
    try:
        log, pixel = Path(log), Path(pixel)
        if not log.is_file() or not pixel.is_file() or pixel.stat().st_size < 40:
            return None
        with pixel.open("rb") as f:
            if f.read(8) != b"\x89PNG\r\n\x1a\n":
                return None
        if not codex_subscription_image.provider_raw_candidate_viable(pixel):
            return None
        events = []
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, dict):
                events.append(value)
        if (sum(e.get("type") == "turn.completed" for e in events) != 1
                or any(e.get("type") == "turn.failed" for e in events)):
            return None
        tool_calls = [
            e for e in events
            if e.get("type") == "item.completed"
            and isinstance(e.get("item"), dict)
            and (e["item"].get("type") == "image_generation_call"
                 or (e["item"].get("type") == "tool_call"
                     and e["item"].get("name") == "image_generation"))
        ]
        if len(tool_calls) != 1:
            return None
        return {
            "tool_call_count": 1,
            "pixel_sha256": hashlib.sha256(pixel.read_bytes()).hexdigest(),
            "pixel_size": pixel.stat().st_size,
            "provider_log_sha256": hashlib.sha256(log.read_bytes()).hexdigest(),
        }
    except Exception:
        return None



def verify_runner_scoped_generated_image(
    *,
    runner_result: dict,
    runner_request_id: str,
    codex_log: Path,
    raw_pixel: Path,
    trusted_codex_home: Path,
) -> dict | None:
    """Read-only runner attestation for an exported native Codex image.

    This verifies *provenance*, not the paid payload model or visual quality.
    Unlike the CLI JSONL, the native user-mode Runner exports thread-specific
    generated_images artifacts, including when Codex emits no image tool event
    into the public --json stream. Never set Generation Attempt state here.
    """
    try:
        if not isinstance(runner_result, dict) or not re.fullmatch(
            r"[0-9a-f]{32}", str(runner_request_id or "")
        ):
            return None
        ev = runner_result.get("evidence")
        if (not isinstance(ev, dict)
                or runner_result.get("request_id") != runner_request_id
                or ev.get("request_id") != runner_request_id
                or runner_result.get("returncode") != 0
                or ev.get("returncode") != 0
                or ev.get("task_type") != "image"
                or ev.get("transport_route") != "native_codex"):
            return None
        threads = ev.get("thread_ids")
        artifacts = ev.get("generated_artifacts")
        if (not isinstance(threads, list) or len(threads) != 1
                or not isinstance(artifacts, list) or len(artifacts) != 1):
            return None
        thread = threads[0]
        if not isinstance(thread, str) or not re.fullmatch(r"[0-9a-f-]{36}", thread):
            return None
        relative_str = artifacts[0]
        if not isinstance(relative_str, str) or "\\" in relative_str:
            return None
        relative = Path(relative_str)
        if (relative.is_absolute()
                or len(relative.parts) != 2
                or relative.parts[0] != thread
                or not relative.parts[1].lower().endswith(".png")):
            return None
        source_root = (Path(trusted_codex_home).resolve() / "generated_images").resolve()
        exported = (source_root / relative).resolve()
        if not exported.is_relative_to(source_root) or not exported.is_file():
            return None
        raw_pixel = Path(raw_pixel)
        log = Path(codex_log)
        if not raw_pixel.is_file() or not log.is_file():
            return None
        def png_sha(file: Path) -> str | None:
            if file.stat().st_size < 40:
                return None
            with file.open("rb") as stream:
                if stream.read(8) != b"\x89PNG\r\n\x1a\n":
                    return None
            return hashlib.sha256(file.read_bytes()).hexdigest()
        exported_sha = png_sha(exported)
        raw_sha = png_sha(raw_pixel)
        if not exported_sha or exported_sha != raw_sha:
            return None
        events = []
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict):
                events.append(event)
        starts = [row for row in events if row.get("type") == "thread.started"]
        ends = [row for row in events if row.get("type") == "turn.completed"]
        if (len(starts) != 1 or starts[0].get("thread_id") != thread
                or len(ends) != 1 or any(row.get("type") == "turn.failed" for row in events)):
            return None
        native_tool_events = [
            row for row in events if row.get("type") == "item.completed"
            and isinstance(row.get("item"), dict)
            and (row["item"].get("type") == "image_generation_call"
                 or (row["item"].get("type") == "tool_call"
                     and row["item"].get("name") == "image_generation"))
        ]
        # Even a perfect runner provenance check is not pixel QA, an
        # attested payload-model identity, or a MySQL Attempt resolution.
        return {
            "proof_kind": "TRUSTED_NATIVE_RUNNER_THREAD_SCOPED_IMAGE_SHA",
            "runner_request_id": runner_request_id,
            "native_codex_thread_id": thread,
            "exported_artifact_relative_path": relative.as_posix(),
            "source_png_sha256": exported_sha,
            "raw_png_sha256": raw_sha,
            "raw_png_bytes": raw_pixel.stat().st_size,
            "native_codex_log_sha256": hashlib.sha256(log.read_bytes()).hexdigest(),
            "native_image_generation_jsonl_events": len(native_tool_events),
            "provider_model_attested": False,
            "review_pass": False,
            "mysql_generation_attempt_state_changed": False,
        }
    except (OSError, ValueError, TypeError, KeyError):
        return None


def record_unreviewed_pixel(ep: Path, item: dict, lease: dict,
                           log: Path, pixel: Path, runner_request_id: str) -> dict:
    """Append-only, never a reviewer or entitlement PASS; refuse duplicates."""
    proof = observe_real_tool_pixel(log, pixel)
    if proof is None or not admitted_baseline_lease(ep, item, lease) or item.get("frame") != 1:
        raise RuntimeError("NATIVE_BASELINE_PIXEL_TOOL_PROOF_UNVERIFIED")
    package = item.get("prompt_package") or {}
    if any(not re.fullmatch(r"[0-9a-f]{64}", str(package.get(key) or ""))
           for key in ("frame_contract_sha256", "package_sha256")):
        raise RuntimeError("NATIVE_BASELINE_PIXEL_SOURCE_SHA_UNBOUND")
    proof.update({
        "schema_version": 1,
        "status": "OBSERVED_AWAITING_INDEPENDENT_VISUAL_REVIEW",
        "episode": str(Path(ep).resolve()),
        "queue_item_id": item.get("id"),
        "logical_asset_frame": 1,
        "generation_key": lease["generation_key"],
        "attempt_index": int(lease["attempt_index"]),
        "fencing_token": lease["fencing_token"],
        "runner_request_id": runner_request_id,
        "frame_contract_sha256": (item.get("prompt_package") or {}).get("frame_contract_sha256"),
        "prompt_package_sha256": (item.get("prompt_package") or {}).get("package_sha256"),
        "review_pass": False,
    })
    target = Path(ep) / "meta/runtime/native-baseline-frame01-tool-proof.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8", newline="\n") as fp:
        json.dump(proof, fp, ensure_ascii=False, sort_keys=True, indent=2)
        fp.write("\n")
    return proof
