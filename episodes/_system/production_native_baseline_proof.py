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


def eligible(ep: Path, item: dict, payload: dict, controller: dict) -> bool:
    """Read-only fail-closed admission for *only* the first official pixel."""
    try:
        ep = Path(ep).resolve()
        if (not ep.is_relative_to(ROOT / "episodes")
                or ep.name != "06_五十亩山地之后_全新重制"
                or ep.parent.name != "00_独立篇"):
            return False
        episode_request = runtime_request.effective_for_episode(ep) or {}
        if (episode_request.get("mode") != "full_auto"
                or (episode_request.get("runtime") or {}).get("execution_mode") != "dag"
                or runtime_router.image_execution_runtime()[0] != "CODEX"):
            return False
        db = storage_config.mysql_connection_kwargs()
        if (str(db.get("host")) not in ("127.0.0.1", "localhost")
                or int(db.get("port") or 0) != 3307):
            return False
        if (episode_state_persistence.load(ep) or {}).get("current_state") != "STORYBOARD_LOCKED":
            return False
        if (int(item.get("frame") or 0) != 1 or item.get("scope") != "visual_lock"
                or item.get("kind") != "original"
                or item.get("technical_retry_source_code")
                or item.get("generation_attempt_reason") not in ("", None, "PRIMARY_GENERATION")):
            return False
        path = ep / "meta/visual-lock-plan.json"
        if not path.is_file():
            return False
        rows = story_json.read_json(path).get("items") or []
        if ([(int(x.get("frame") or 0), x.get("role")) for x in rows] != PLAN
                or [list(x.get("depends_on") or []) for x in rows] != [[], [1], [1], [1]]):
            return False
        review = (story_json.read_json(ep / "meta/story-gates.json").get("reviews") or {})
        if review.get("story") != "passed" or any(
                review.get(k) != "pending" for k in ("visual_admission", "authenticity", "continuity")):
            return False
        import image_scheduler
        queue = image_scheduler.load_queue(ep).get("items") or []
        if len(queue) != 4:
            return False
        indexed = {int(x.get("frame") or 0): x for x in queue}
        if sorted(indexed) != [1, 8, 16, 17]:
            return False
        if (indexed[1].get("id") != item.get("id")
                or indexed[1].get("status") not in ("queued", "running", "generating")):
            return False
        if any(indexed[f].get("scope") != "visual_lock"
               or indexed[f].get("kind") != "original"
               or list(indexed[f].get("depends_on") or []) != ([] if f == 1 else [1])
               or (f != 1 and indexed[f].get("status") != "queued")
               for f in (1, 8, 16, 17)):
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
        for frame in (1, 8, 16, 17):
            key = logical_asset_identity.frame_asset_key(ep, frame)
            state = generation_attempt_authority.load_asset_state(ep, key)
            if int(state.get("attempts_consumed") or 0) or state.get("active_attempt_index") is not None:
                return False
        return True
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


def record_unreviewed_pixel(ep: Path, item: dict, lease: dict,
                           log: Path, pixel: Path, runner_request_id: str) -> dict:
    """Append-only, never a reviewer or entitlement PASS; refuse duplicates."""
    proof = observe_real_tool_pixel(log, pixel)
    if proof is None or not first_attempt_only(lease) or item.get("frame") != 1:
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
        "attempt_index": 1,
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
