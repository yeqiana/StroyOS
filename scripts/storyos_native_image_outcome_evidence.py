#!/usr/bin/env python3
"""Read-only, exact-thread evidence for a previously dispatched native Codex image.

Never treat an agent's HTTP 429 text, CLI rc=0, or absent generated image as
proof that the provider did not dispatch/charge. Does not mutate Attempt or
permit retries; returns only corroborated evidence for a later authority flow.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "episodes" / "_system"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SYSTEM))

import generation_attempt_authority
import image_artifact_collector
import logical_asset_identity
import production_recovery
import scheduler_core

REQUEST_ID = re.compile(r"[0-9a-f]{32}", re.I)
THREAD_ID = re.compile(r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}", re.I)


def _base(status: str = "NATIVE_EVIDENCE_UNVERIFIED") -> dict:
    return {
        "status": status, "read_only": True, "model_calls": 0, "sql_writes": 0,
        "image_generation_verified": False, "provider_outcome_verified": False,
        "may_retry_paid_attempt": False, "thread_scoped_pixel_count": 0,
        "pixel_candidates": [],
    }


def inspect(episode_dir: Path, *, frame: int, attempt_index: int,
            root: Path = ROOT) -> dict:
    """Deny by default, with exact MySQL / item / lifecycle / Runner identity."""
    report = _base()
    try:
        root = Path(root).resolve()
        ep = Path(episode_dir).resolve()
        if (frame < 1 or attempt_index < 1
                or not ep.is_dir() or not ep.is_relative_to(root / "episodes")):
            return report
        key = logical_asset_identity.frame_asset_key(ep, frame)
        attempt = generation_attempt_authority.load_attempt(ep, key, attempt_index)
        if not isinstance(attempt, dict):
            return report
        report["canonical_attempt_status"] = str(attempt.get("status") or "")
        if attempt.get("status") != "OUTCOME_UNKNOWN":
            report["status"] = "NOT_OUTCOME_UNKNOWN"
            return report
        request_id = str(attempt.get("runner_request_id") or "")
        generation_key = str(attempt.get("generation_key") or "")
        if not REQUEST_ID.fullmatch(request_id) or not generation_key:
            return report
        queue = scheduler_core.load_queue(ep)
        matches = [item for item in queue.get("items") or []
                   if isinstance(item, dict) and int(item.get("frame") or 0) == frame
                   and item.get("scope") in {"repair", "original"}]
        if len(matches) != 1 or not isinstance(matches[0].get("id"), str):
            return report
        item = matches[0]
        lifecycle = production_recovery._read(
            production_recovery.lifecycle_path(ep, item))
        if (not isinstance(lifecycle, dict)
                or str(lifecycle.get("item_id") or "") != item["id"]
                or int(lifecycle.get("attempt") or 0) != attempt_index
                or lifecycle.get("generation_key") != generation_key
                or lifecycle.get("runner_request_id") != request_id):
            return report
        receipt_path = (root / "runtime" / "codex-user-runner" /
                        "task-results" / (request_id + ".json"))
        if not receipt_path.is_file():
            return report
        raw_receipt = receipt_path.read_bytes()
        receipt = json.loads(raw_receipt)
        native = receipt.get("evidence")
        if (not isinstance(native, dict) or
                receipt.get("request_id") != request_id or
                native.get("request_id") != request_id or
                native.get("task_type") != "image" or
                native.get("transport_route") not in (None, "native_codex")):
            return report
        stdout = base64.b64decode(receipt.get("output_base64") or "", validate=True)
        if (hashlib.sha256(stdout).hexdigest() != receipt.get("output_sha256")
                or len(stdout) != receipt.get("output_bytes")):
            return report
        threads = native.get("thread_ids")
        if (not isinstance(threads, list) or len(threads) != 1
                or not isinstance(threads[0], str)
                or not THREAD_ID.fullmatch(threads[0])):
            return report
        events = []
        for line in stdout.decode("utf-8", "replace").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict):
                events.append(event)
        started = {str(e.get("thread_id") or "")
                   for e in events if e.get("type") == "thread.started"}
        if threads[0] not in started:
            return report
        mentioned_429 = any(
            "429" in str(e.get("item", {}).get("text") or "")
            for e in events if isinstance(e.get("item"), dict)
            and e["item"].get("type") == "agent_message")
        tool_events = sum(
            1 for e in events if (
                "image_generation" in str(e.get("type") or "").lower()
                or (isinstance(e.get("item"), dict)
                    and "image_generation" in str(
                        e["item"].get("type") or "").lower())))
        report.update({
            "status": "PROVIDER_OUTCOME_UNVERIFIED",
            "runner_receipt_sha256": hashlib.sha256(raw_receipt).hexdigest(),
            "runner_output_digest_verified": True,
            "native_agent_message_mentions_429": mentioned_429,
            "native_image_tool_event_count": tool_events,
            "native_runner_exit_code": receipt.get("returncode"),
            "native_generated_artifact_count": len(
                native.get("generated_artifacts") or []),
            "thread_identity_verified": True,
        })
        home = native.get("codex_home")
        if not isinstance(home, dict) or home.get("accessible") is not True:
            return report
        home_path = Path(str(home.get("path") or "")).expanduser().resolve()
        # The authenticated user may own many generated image threads; never
        # scan siblings or arbitrary paths supplied through mutable metadata.
        if home_path.name.lower() != ".codex" or not home_path.is_dir():
            return report
        thread_dir = home_path / "generated_images" / threads[0]
        report["native_home_scope_verified"] = True
        report["native_thread_directory_present"] = thread_dir.is_dir()
        pixels = []
        if thread_dir.is_dir():
            for path in sorted(thread_dir.rglob("*"))[:128]:
                if (not path.is_file() or path.is_symlink()
                        or path.suffix.lower() not in {".png", ".jpg", ".jpeg"}
                        or not path.resolve().is_relative_to(thread_dir.resolve())
                        or not image_artifact_collector.valid_image(path)):
                    continue
                pixels.append({
                    "sha256": image_artifact_collector.sha256_file(path),
                    "bytes": path.stat().st_size,
                })
        report["thread_scoped_pixel_count"] = len(pixels)
        report["pixel_candidates"] = pixels
        report["status"] = ("RECOVERY_CANDIDATE_NEEDS_SHA_ADMISSION" if pixels
                            else "PAID_ATTEMPT_UNRESOLVED_NO_PIXEL")
        return report
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
        # Report only the exception class; never surface filesystem secrets.
        report["reason_code"] = "EVIDENCE_READ_" + type(exc).__name__.upper()
        return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("episode", type=Path)
    parser.add_argument("--frame", type=int, required=True)
    parser.add_argument("--attempt", type=int, required=True)
    args = parser.parse_args()
    ep = args.episode if args.episode.is_absolute() else ROOT / args.episode
    result = inspect(ep, frame=args.frame, attempt_index=args.attempt)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    # This is diagnostic-only even if a pixel was found; never return a
    # production authorization or declare provider failure/success.
    return 0 if result["status"] != "NATIVE_EVIDENCE_UNVERIFIED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
