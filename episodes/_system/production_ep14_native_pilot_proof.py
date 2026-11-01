"""One-frame EP14 native image capability pilot; never general UNKNOWN promotion.

A real native App Server provider capability boolean plus a fresh authenticated
Codex Runner text-only tool-visibility session are required. These facts do not
prove an image was produced; only the first new reviewed F009 render is eligible
for one actual controlled paid Attempt. F029/F048 remain held until a genuine
F009 image and Attempt receipt exist.
"""
from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import subprocess
import threading
import time
from pathlib import Path

import codex_subscription_image as backend
import production_native_baseline_proof as baseline

PILOT_FRAME = 9
PILOT_STATUS = "PILOT_FRAME_09_ONLY_REAL_PROVIDER_PROOF"
POSTPONED_STATUS = "pilot_hold"


class PilotDenied(ValueError):
    pass


def _provider_capabilities_read(*, timeout: float = 18) -> dict:
    """Read actual native app-server RPC; never call model/image tools."""
    command = (["cmd.exe", "/d", "/s", "/c",
                "codex app-server --listen stdio://"]
               if os.name == "nt" else
               ["codex", "app-server", "--listen", "stdio://"])
    proc = subprocess.Popen(command, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            encoding="utf-8", errors="replace", text=True,
                            bufsize=1)
    pending = queue.Queue()

    def collect():
        try:
            for line in proc.stdout:
                try:
                    item = json.loads(line)
                except (TypeError, ValueError):
                    continue
                if isinstance(item, dict) and item.get("id") in (1, 2):
                    pending.put(item)
        except Exception:
            pass

    threading.Thread(target=collect, daemon=True).start()

    def send(value):
        proc.stdin.write(json.dumps(value, separators=(",", ":")) + "\n")
        proc.stdin.flush()

    def receive(ident, deadline):
        while time.monotonic() < deadline:
            try:
                item = pending.get(timeout=max(0.01, deadline-time.monotonic()))
            except queue.Empty:
                break
            if item.get("id") == ident:
                return item
        return None

    try:
        deadline = time.monotonic() + max(1, min(30, float(timeout)))
        send({"id": 1, "method": "initialize",
              "params": {"clientInfo": {"name": "StoryOS-EP14-ReadOnly",
                                         "version": "1.0.0"},
                         "capabilities": {"experimentalApi": True}}})
        initial = receive(1, deadline)
        if not isinstance(initial, dict) or not isinstance(initial.get("result"), dict):
            raise PilotDenied("EP14_NATIVE_APP_SERVER_INIT_NOT_VERIFIED")
        send({"id": 2, "method": "modelProvider/capabilities/read", "params": {}})
        answer = receive(2, deadline)
        capabilities = answer.get("result") if isinstance(answer, dict) else None
        if (not isinstance(capabilities, dict)
                or type(capabilities.get("imageGeneration")) is not bool
                or type(capabilities.get("webSearch")) is not bool):
            raise PilotDenied("EP14_NATIVE_PROVIDER_CAPABILITIES_RPC_INVALID")
        return {
            "imageGeneration": capabilities["imageGeneration"],
            "webSearch": capabilities["webSearch"],
            "source": "NATIVE_CODEX_APP_SERVER_MODEL_PROVIDER_CAPABILITIES_READ",
            "model_tool_registry_verified": False,
            "image_generation_called": False,
        }
    except (OSError, BrokenPipeError, TimeoutError) as exc:
        raise PilotDenied("EP14_NATIVE_PROVIDER_RPC_EXEC_FAILED") from exc
    finally:
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass


def attest_one_frame(strict: dict, payload: dict, controller: dict,
                     codex: str | None = None) -> dict:
    """Explicitly scoped trial, never represented as explicit tool-registry PASS."""
    if (strict.get("status") != "BLOCKED"
            or strict.get("failure_class") != "LOGIN_AUTH_IMAGE_TOOL_CAPABILITY_UNKNOWN"
            or strict.get("image_generation_called") is not False
            or strict.get("image_attempt_authority_called") is not False
            or payload.get("model") != "gpt-image-2.5-flare"
            or payload.get("quality") != "high"
            or controller.get("model") != "gpt-6-luna"
            or controller.get("reasoning_effort") != "high"):
        raise PilotDenied("EP14_PILOT_EXACT_NATIVE_UNKNOWN_SCOPE_REQUIRED")
    native_capability = _provider_capabilities_read()
    if native_capability["imageGeneration"] is not True:
        raise PilotDenied("EP14_NATIVE_PROVIDER_IMAGE_GENERATION_NOT_SUPPORTED")
    secondary = baseline.attest_secondary(strict, payload, controller, codex)
    if secondary is None:
        raise PilotDenied("EP14_AUTHENTICATED_NATIVE_RUNNER_TOOL_VISIBILITY_NOT_ATTESTED")
    stable = {
        "source": native_capability["source"],
        "imageGeneration": True,
        "catalog_sha256": secondary["catalog_sha256"],
        "transport_model": secondary["transport_model"],
        "transport_effort": secondary["transport_effort"],
        "payload_model": secondary["payload_model"],
        "payload_quality": secondary["payload_quality"],
        "image_generation_visible_secondary": True,
    }
    evidence_sha = hashlib.sha256(json.dumps(
        stable, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return {
        **secondary,
        "status": "READY_FOR_REAL_CAPABILITY_PROOF",
        "trial_scope": PILOT_STATUS,
        "trial_frame": PILOT_FRAME,
        "native_provider_capabilities_imageGeneration": True,
        "native_provider_capability_sha256": evidence_sha,
        "tool_capability_state": "UNKNOWN",
        "tool_registry_attestation": "UNAVAILABLE",
        "image_generation_called": False,
        "image_attempt_authority_called": False,
    }


def eligible(ep: Path, item: dict, payload: dict, controller: dict) -> bool:
    """Only the reviewed, activated F009 SHA may enter this proof path."""
    if (int(item.get("frame") or 0) != PILOT_FRAME
            or item.get("kind") != "repair"
            or item.get("scope") != "batch"
            or item.get("status") not in {"queued", "running"}
            or payload.get("model") != "gpt-image-2.5-flare"
            or payload.get("quality") != "high"
            or controller.get("model") != "gpt-6-luna"
            or controller.get("reasoning_effort") != "high"):
        return False
    try:
        import production_ep14_canonical_activation as active
        value = active.load_for_dispatch(ep, item)
        marker = active.scheduler_core.load_queue(ep).get(active.QUEUE_KEY) or {}
        return bool(
            marker.get("pilot_mode") == PILOT_STATUS
            and marker.get("pilot_frame") == PILOT_FRAME
            and marker.get("postimage_pixel_review_required") is True
            and value.get("render_content_sha256") ==
            item.get("prompt_package", {}).get("package_sha256")
        )
    except Exception:
        return False
