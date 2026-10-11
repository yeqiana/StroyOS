"""Hermetic fail-closed native Codex generated-images provenance checks."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

SYSTEM = Path(__file__).resolve().parents[2] / "episodes" / "_system"
if str(SYSTEM) not in sys.path:
    sys.path.insert(0, str(SYSTEM))

from production_native_baseline_proof import verify_runner_scoped_generated_image


REQUEST = "b" * 32
THREAD = "01a12adb-b801-7bf0-ac83-fe74828b75f1"
FILE = "exec-6f5a7c1e-1aed-4058-a77b-3a2014f2b896.png"
PNG = b"\x89PNG\r\n\x1a\n" + b"non-real-hermetic-image-fixture" * 5


def case(tmp_path: Path):
    home = tmp_path / ".codex"
    source = home / "generated_images" / THREAD / FILE
    source.parent.mkdir(parents=True)
    source.write_bytes(PNG)
    raw = tmp_path / "episode" / "media" / "raw" / "01.png"
    raw.parent.mkdir(parents=True)
    raw.write_bytes(PNG)
    log = tmp_path / "episode" / "meta" / "image-workers" / "01.jsonl"
    log.parent.mkdir(parents=True)
    events = [
        {"type": "thread.started", "thread_id": THREAD},
        {"type": "turn.started"},
        {"type": "item.completed", "item": {"type": "agent_message", "text": ""}},
        {"type": "turn.completed", "usage": {"input_tokens": 21}},
    ]
    log.write_text(
        "Codex CLI warning preceding JSON\n"
        + "\n".join(json.dumps(x) for x in events) + "\n",
        encoding="utf-8",
    )
    result = {
        "request_id": REQUEST,
        "returncode": 0,
        "evidence": {
            "request_id": REQUEST,
            "returncode": 0,
            "task_type": "image",
            "transport_route": "native_codex",
            "thread_ids": [THREAD],
            "generated_artifacts": [f"{THREAD}/{FILE}"],
        },
    }
    return home, source, raw, log, result


def observe(home, raw, log, result):
    return verify_runner_scoped_generated_image(
        runner_result=result,
        runner_request_id=REQUEST,
        codex_log=log,
        raw_pixel=raw,
        trusted_codex_home=home,
    )


def test_real_runner_scoped_thread_image_matches_raw_without_cli_tool_item(tmp_path):
    home, source, raw, log, result = case(tmp_path)
    verdict = observe(home, raw, log, result)
    assert verdict is not None
    assert verdict["proof_kind"] == "TRUSTED_NATIVE_RUNNER_THREAD_SCOPED_IMAGE_SHA"
    assert verdict["native_image_generation_jsonl_events"] == 0
    assert verdict["source_png_sha256"] == verdict["raw_png_sha256"]
    assert verdict["runner_request_id"] == REQUEST
    assert verdict["provider_model_attested"] is False
    assert verdict["review_pass"] is False
    assert verdict["mysql_generation_attempt_state_changed"] is False


@pytest.mark.parametrize("mutate", [
    "wrong_request_id", "wrong_evidence_request_id", "non_native_route",
    "wrong_task_type", "bad_returncode", "another_thread", "two_artifacts",
    "path_escape", "sibling_thread", "source_png_sha_drift", "raw_png_sha_drift",
    "log_thread_drift", "log_incomplete", "log_failed", "deleted_source",
    "missing_codex_home", "raw_not_png",
])
def test_native_thread_proof_fails_closed(tmp_path, mutate):
    home, source, raw, log, result = case(tmp_path)
    result = copy.deepcopy(result)
    if mutate == "wrong_request_id":
        result["request_id"] = "a" * 32
    elif mutate == "wrong_evidence_request_id":
        result["evidence"]["request_id"] = "a" * 32
    elif mutate == "non_native_route":
        result["evidence"]["transport_route"] = "opencodex"
    elif mutate == "wrong_task_type":
        result["evidence"]["task_type"] = "smoke"
    elif mutate == "bad_returncode":
        result["returncode"] = 1
    elif mutate == "another_thread":
        result["evidence"]["thread_ids"] = ["f" * 36]
    elif mutate == "two_artifacts":
        result["evidence"]["generated_artifacts"].append(f"{THREAD}/other.png")
    elif mutate == "path_escape":
        result["evidence"]["generated_artifacts"] = ["../outside.png"]
    elif mutate == "sibling_thread":
        result["evidence"]["generated_artifacts"] = ["f" * 36 + f"/{FILE}"]
    elif mutate == "source_png_sha_drift":
        source.write_bytes(PNG + b"altered")
    elif mutate == "raw_png_sha_drift":
        raw.write_bytes(PNG + b"altered")
    elif mutate == "log_thread_drift":
        log.write_text('{"type":"thread.started","thread_id":"x"}\n{"type":"turn.completed"}\n')
    elif mutate == "log_incomplete":
        log.write_text('{"type":"thread.started","thread_id":"' + THREAD + '"}\n')
    elif mutate == "log_failed":
        with log.open("a") as out:
            out.write('{"type":"turn.failed"}\n')
    elif mutate == "deleted_source":
        source.unlink()
    elif mutate == "missing_codex_home":
        home = tmp_path / "some_other_home"
    elif mutate == "raw_not_png":
        raw.write_bytes(b"fake" * 30)
    assert observe(home, raw, log, result) is None


def test_runner_proof_does_not_create_or_modify_authority(tmp_path):
    home, source, raw, log, result = case(tmp_path)
    before = {p: p.read_bytes() for p in (source, raw, log)}
    assert observe(home, raw, log, result) is not None
    assert all(p.read_bytes() == value for p, value in before.items())
    assert not (tmp_path / "episode" / "meta" / "runtime").exists()
