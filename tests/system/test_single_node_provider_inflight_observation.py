"""R13: real OS owner, gateway call edge and MySQL attempt must agree."""
from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import threading
from unittest.mock import patch

import pytest

SYSTEM = Path(__file__).resolve().parents[2] / "episodes" / "_system"
sys.path.insert(0, str(SYSTEM))
import runner_state_store
import writer_owner_observation as owner
import provider_inflight_observation as producer
import image_generation_gateway as gateway
from platform.operations.local_provider_call_readonly import (
    REL, observe_provider_calls,
)


def _db(frames=(7,), state="DISPATCH_COMMITTED", valid=True):
    return {
        "available": valid, "database_identity_verified": valid,
        "read_only_grants_verified": valid,
        "generation_attempt_records": [{
            "frame": frame, "attempt_index": 1, "status": state,
            "dispatch_recorded_at": datetime.now(timezone.utc).isoformat(),
            "terminal_recorded_at": None,
        } for frame in frames],
    }


def _lease(frame, ep):
    return {
        "episode_id": "test-series/test-episode",
        "logical_asset_key": f"test-series/test-episode/frame-{frame:02d}",
        "attempt_index": 1,
        "fencing_token": 1,
    }


@pytest.fixture
def admitted(tmp_path, monkeypatch):
    ep = tmp_path / "test-series" / "test-episode"
    ep.mkdir(parents=True)
    monkeypatch.setattr(producer.logical_asset_identity, "episode_id", lambda _: "test-series/test-episode")
    assert runner_state_store.acquire_lock(ep)
    epoch = owner.new_epoch(ep)
    assert epoch is not None
    assert owner.emit(ep, epoch, held=True)
    assert producer.attach(ep, epoch)
    try:
        yield ep, epoch
    finally:
        producer.detach(ep, epoch)
        owner.emit(ep, epoch, held=False)
        runner_state_store.release_lock(ep)


def test_single_call_edge_is_only_live_during_actual_provider_call(admitted, monkeypatch):
    ep, epoch = admitted
    lease = _lease(7, ep)
    monkeypatch.setattr(gateway.global_image_capacity, "image_permits", lambda count: nullcontext())
    monkeypatch.setattr(gateway.authority, "commit_dispatch", lambda *args, **kwargs: dict(lease))
    monkeypatch.setattr(gateway.authority, "validate_committed_dispatch", lambda *args, **kwargs: True)
    monkeypatch.setattr(gateway.authority, "mark_observed", lambda *args, **kwargs: None)
    assert observe_provider_calls(ep, _db())["status"] == "UNKNOWN"
    def fake_provider():
        result = observe_provider_calls(ep, _db())
        assert result["status"] == "FRESH_PROVIDER_CALL_EVIDENCE"
        assert result["verified_current_frames"] == [7]
        assert result["verified_current_image_attempts"][0]["attempt_index"] == 1
        assert result["provider_call_verified"] is True
        assert result["kernel_lock_verified"] is False
        assert result["task_id_verified"] is False
        assert result["stalled_verified"] is False
        assert "pid" not in json.dumps(result) and "owner_epoch" not in json.dumps(result)
        return "mock-only-no-network"
    assert gateway.provider_generate(ep, lease, 1, "mock_only", fake_provider) == "mock-only-no-network"
    assert observe_provider_calls(ep, _db())["status"] == "UNKNOWN"


def test_gateway_denied_by_stale_fence_never_reports_inflight(admitted, monkeypatch):
    ep, _ = admitted
    lease = _lease(7, ep)
    monkeypatch.setattr(gateway.global_image_capacity, "image_permits", lambda _: nullcontext())
    monkeypatch.setattr(gateway.authority, "commit_dispatch", lambda *a, **kw: dict(lease))
    monkeypatch.setattr(gateway.authority, "validate_committed_dispatch", lambda *a, **kw: False)
    with pytest.raises(Exception):
        gateway.provider_generate(ep, lease, 1, "mock_only", lambda: pytest.fail("paid call prohibited"))
    assert observe_provider_calls(ep, _db())["status"] == "UNKNOWN"


def test_no_mysql_committed_attempt_does_not_verify_provider(admitted):
    ep, _ = admitted
    with producer.provider_span(ep, [_lease(7, ep)]):
        assert observe_provider_calls(ep, _db(state="RESERVED"))["reason"] == "GENERATION_ATTEMPT_DISPATCH_NOT_VERIFIED"
        assert observe_provider_calls(ep, _db(valid=False))["reason"] == "MYSQL_ATTEMPT_AUTHORITY_NOT_VERIFIED"
        assert observe_provider_calls(ep, _db(frames=(8,)))["status"] == "UNKNOWN"


def test_batch_multiple_frames_and_terminal_cleanup(admitted):
    ep, epoch = admitted
    with producer.provider_span(ep, [_lease(7, ep), _lease(8, ep)]):
        assert producer.heartbeat(ep, epoch)
        snap = observe_provider_calls(ep, _db((7, 8)))
        assert snap["status"] == "FRESH_PROVIDER_CALL_EVIDENCE"
        assert snap["verified_current_frames"] == [7, 8]
        assert len(snap["verified_current_image_attempts"]) == 2
        assert observe_provider_calls(ep, _db((7,)))["status"] == "UNKNOWN"
    assert observe_provider_calls(ep, _db((7, 8)))["status"] == "UNKNOWN"


def test_exception_always_removes_span(admitted):
    ep, _ = admitted
    with pytest.raises(RuntimeError, match="mock error"):
        with producer.provider_span(ep, [_lease(7, ep)]):
            assert observe_provider_calls(ep, _db())["provider_call_verified"]
            raise RuntimeError("mock error")
    assert observe_provider_calls(ep, _db())["status"] == "UNKNOWN"


def test_owner_epoch_mismatch_and_release_hide_old_span(admitted):
    ep, epoch = admitted
    with producer.provider_span(ep, [_lease(7, ep)]):
        data = json.loads((ep / REL).read_text(encoding="utf-8"))
        data["owner_epoch"] = "0" * 32
        (ep / REL).write_text(json.dumps(data), encoding="utf-8")
        assert observe_provider_calls(ep, _db())["reason"] == "PROVIDER_OWNER_EPOCH_MISMATCH"
    producer.detach(ep, epoch)
    assert observe_provider_calls(ep, _db())["status"] == "UNKNOWN"


def test_stale_timestamp_malicious_file_and_owner_release(admitted):
    ep, epoch = admitted
    with producer.provider_span(ep, [_lease(7, ep)]):
        path = ep / REL
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["heartbeat_at"] = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
        path.write_text(json.dumps(raw), encoding="utf-8")
        assert observe_provider_calls(ep, _db())["reason"] == "PROVIDER_HEARTBEAT_STALE"
        raw["heartbeat_at"] = datetime.now().isoformat()  # timezone-less
        path.write_text(json.dumps(raw), encoding="utf-8")
        assert observe_provider_calls(ep, _db())["reason"] == "PROVIDER_HEARTBEAT_STALE"
    owner.emit(ep, epoch, held=False)
    assert observe_provider_calls(ep, _db())["reason"] == "DRIVER_OWNER_NOT_VERIFIED"


def test_non_driver_gateway_call_cannot_claim_live(tmp_path, monkeypatch):
    ep = tmp_path / "fake"
    ep.mkdir()
    monkeypatch.setattr(producer.logical_asset_identity, "episode_id", lambda _: "test-series/test-episode")
    with producer.provider_span(ep, [_lease(7, ep)]):
        assert not (ep / REL).exists()
    assert observe_provider_calls(ep, _db())["status"] == "UNKNOWN"


def test_real_concurrent_provider_threads_do_not_lose_frames(admitted):
    ep, epoch = admitted
    entered = threading.Barrier(3)
    release = threading.Event()
    errors = []
    def run(frame):
        try:
            with producer.provider_span(ep, [_lease(frame, ep)]):
                entered.wait(timeout=6)
                release.wait(timeout=6)
        except BaseException as e:
            errors.append(e)
    ths = [threading.Thread(target=run, args=(7,)), threading.Thread(target=run, args=(8,))]
    for t in ths: t.start()
    try:
        entered.wait(timeout=6)
        assert producer.heartbeat(ep, epoch)
        state = observe_provider_calls(ep, _db((7, 8)))
        assert state["verified_current_frames"] == [7, 8]
    finally:
        release.set()
        for t in ths: t.join(timeout=7)
    assert not errors
    assert observe_provider_calls(ep, _db((7, 8)))["status"] == "UNKNOWN"


def test_real_canonical_driver_binds_mocked_gateway_and_clears_before_unlock(tmp_path, monkeypatch):
    import persistent_runner_daemon

    ep = tmp_path / "canonical"
    ep.mkdir()
    monkeypatch.setattr(producer.logical_asset_identity, "episode_id", lambda _: "test-series/test-episode")
    monkeypatch.setattr(persistent_runner_daemon.runtime_trace, "emit", lambda *a, **kw: None)
    monkeypatch.setattr(gateway.global_image_capacity, "image_permits", lambda _: nullcontext())
    lease = _lease(7, ep)
    monkeypatch.setattr(gateway.authority, "commit_dispatch", lambda *a, **kw: dict(lease))
    monkeypatch.setattr(gateway.authority, "validate_committed_dispatch", lambda *a, **kw: True)
    monkeypatch.setattr(gateway.authority, "mark_observed", lambda *a, **kw: None)
    states = []
    def synthetic_runner(episode, **kwargs):
        assert not runner_state_store.acquire_lock(episode)
        def mock_model_call():
            states.append(observe_provider_calls(ep, _db())["status"])
            return "synthetic-not-provider"
        assert gateway.provider_generate(ep, dict(lease), 1, "mock", mock_model_call) == "synthetic-not-provider"
        states.append(observe_provider_calls(ep, _db())["status"])
        return 0
    monkeypatch.setattr(persistent_runner_daemon.episode_runner, "run_episode", synthetic_runner)
    assert persistent_runner_daemon.run(ep, interval=30) == 0
    assert states == ["FRESH_PROVIDER_CALL_EVIDENCE", "UNKNOWN"]
    assert observe_provider_calls(ep, _db())["status"] == "UNKNOWN"
    assert runner_state_store.acquire_lock(ep)
    runner_state_store.release_lock(ep)
