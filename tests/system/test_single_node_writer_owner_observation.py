"""Writer observation is non-authorizing, process-bound and survives crash safely."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
SYSTEM = ROOT / "episodes" / "_system"
sys.path.insert(0, str(SYSTEM))
import runner_state_store
import writer_owner_observation
from platform.operations.local_writer_owner_readonly import (
    observe_writer_owner, MAX_AGE_SECONDS, REL
)

CHILD = r"""
import sys
from pathlib import Path
# This raw Python child does not run through the normal StoryOS CI bootstrap.
import platform as stdlib_platform
stdlib_platform.__path__ = [str(Path(sys.argv[1]).resolve().parents[1] / "platform")]
sys.path.insert(0,sys.argv[1])
import runner_state_store
import writer_owner_observation
ep=Path(sys.argv[2])
assert runner_state_store.acquire_lock(ep)
epoch=writer_owner_observation.new_epoch(ep)
assert epoch
assert writer_owner_observation.emit(ep,epoch,held=True)
print("HELD",flush=True)
sys.stdin.readline()
assert writer_owner_observation.emit(ep,epoch,held=False)
runner_state_store.release_lock(ep)
"""


def _spawn(ep):
    return subprocess.Popen(
        [sys.executable, "-P", "-u", "-c", CHILD, str(SYSTEM), str(ep)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True,
    )


def _cleanup(process):
    if process.poll() is None:
        process.kill()
        process.wait(timeout=8)
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream:
            stream.close()


def test_two_processes_actual_lock_and_fresh_owner_observation(tmp_path):
    ep = tmp_path / "series" / "episode"
    ep.mkdir(parents=True)
    child = _spawn(ep)
    try:
        child_banner = child.stdout.readline().strip()
        assert child_banner == "HELD", ("child process did not acquire OS lock", child.poll(), child.stderr.read()[-800:])
        assert not runner_state_store.acquire_lock(ep)
        observed = observe_writer_owner(ep)
        assert observed["status"] == "FRESH_PRODUCER_LOCK_CLAIM"
        assert observed["producer_process_verified"]
        assert observed["kernel_lock_verified"] is False
        assert observed["provider_inflight_verified"] is False
        assert "pid" not in observed and "epoch" not in observed
        child.stdin.write("\n")
        child.stdin.flush()
        child.wait(timeout=8)
        assert child.returncode == 0
        assert observe_writer_owner(ep)["status"] == "UNKNOWN"
        assert observe_writer_owner(ep)["reason"] == "OWNER_NOT_REPORTED_HELD"
        assert runner_state_store.acquire_lock(ep)
        runner_state_store.release_lock(ep)
    finally:
        _cleanup(child)


def test_killed_process_stale_lock_claim_does_not_stay_live(tmp_path):
    ep = tmp_path / "episode"
    ep.mkdir()
    child = _spawn(ep)
    try:
        child_banner = child.stdout.readline().strip()
        assert child_banner == "HELD", ("child process did not acquire OS lock", child.poll(), child.stderr.read()[-800:])
        assert observe_writer_owner(ep)["status"] == "FRESH_PRODUCER_LOCK_CLAIM"
        child.kill()
        child.wait(timeout=8)
        observed = observe_writer_owner(ep)
        assert observed["status"] == "UNKNOWN"
        assert observed["reason"] == "OWNER_PROCESS_NOT_VERIFIED"
        assert runner_state_store.acquire_lock(ep)
        runner_state_store.release_lock(ep)
    finally:
        _cleanup(child)


def test_wrong_episode_and_pid_reuse_rejected(tmp_path):
    ep = tmp_path / "episode"
    other = tmp_path / "other"
    ep.mkdir(); other.mkdir()
    epoch = writer_owner_observation.new_epoch(ep)
    assert epoch
    assert writer_owner_observation.emit(ep, epoch, held=True)
    assert observe_writer_owner(ep)["status"] == "FRESH_PRODUCER_LOCK_CLAIM"
    record = json.loads((ep / REL).read_text(encoding="utf-8"))
    record["process_created_at"] -= 1000
    (ep / REL).write_text(json.dumps(record), encoding="utf-8")
    assert observe_writer_owner(ep)["reason"] == "OWNER_PROCESS_NOT_VERIFIED"
    # A different episode cannot borrow the same producer claim.
    (other / "meta" / "runtime").mkdir(parents=True)
    (other / REL).write_text(json.dumps(record), encoding="utf-8")
    assert observe_writer_owner(other)["reason"] == "OWNER_EPISODE_MISMATCH"


def test_expired_naive_future_and_released_are_unknown(tmp_path):
    ep = tmp_path / "ep"
    ep.mkdir()
    epoch = writer_owner_observation.new_epoch(ep)
    assert epoch
    assert writer_owner_observation.emit(ep, epoch, held=True)
    file = ep / REL
    initial = json.loads(file.read_text(encoding="utf-8"))
    for age, expected in (
        (MAX_AGE_SECONDS + 20, "OWNER_HEARTBEAT_STALE"),
        (-70, "OWNER_HEARTBEAT_STALE"),
    ):
        d = dict(initial)
        d["heartbeat_at"] = (datetime.now(timezone.utc) - timedelta(seconds=age)).isoformat()
        file.write_text(json.dumps(d), encoding="utf-8")
        assert observe_writer_owner(ep)["reason"] == expected
    d = dict(initial)
    d["heartbeat_at"] = datetime.now().replace(tzinfo=None).isoformat()
    file.write_text(json.dumps(d), encoding="utf-8")
    assert observe_writer_owner(ep)["reason"] == "OWNER_TIME_INVALID"
    assert writer_owner_observation.emit(ep, epoch, held=False)
    assert observe_writer_owner(ep)["reason"] == "OWNER_NOT_REPORTED_HELD"


def test_failed_unsafe_file_never_exposes_claim(tmp_path):
    ep = tmp_path / "ep"
    ep.mkdir()
    assert observe_writer_owner(ep)["reason"] == "NO_CANONICAL_DRIVER_OWNER_EVIDENCE"
    path = ep / REL
    path.parent.mkdir(parents=True)
    path.write_bytes(b"x" * 2400)
    assert observe_writer_owner(ep)["reason"] == "OWNER_EVIDENCE_UNSAFE"
    path.write_text('{"some": "secret"}', encoding="utf-8")
    r = observe_writer_owner(ep)
    assert r["status"] == "UNKNOWN"
    assert "secret" not in json.dumps(r)
    path.unlink()
    external = tmp_path / "external.json"
    external.write_text('{"status":"HELD"}', encoding="utf-8")
    try:
        path.symlink_to(external)
    except (OSError, NotImplementedError):
        return
    assert observe_writer_owner(ep)["reason"] == "OWNER_EVIDENCE_UNSAFE"


def test_canonical_daemon_reports_only_inside_existing_os_lock(tmp_path, monkeypatch):
    import persistent_runner_daemon

    ep = tmp_path / "canonical"
    ep.mkdir()
    snapshots = []

    def bounded_no_provider_episode(episode, **kwargs):
        # This is the actual daemon's lock interval, with its production
        # engine replaced by an inert test function: no task execution.
        snapshots.append(observe_writer_owner(episode))
        assert not runner_state_store.acquire_lock(episode)
        return 0

    monkeypatch.setattr(persistent_runner_daemon.episode_runner, "run_episode", bounded_no_provider_episode)
    monkeypatch.setattr(persistent_runner_daemon.runtime_trace, "emit", lambda *a, **k: None)
    result = persistent_runner_daemon.run(ep, interval=1)
    assert result == 0
    assert snapshots[0]["status"] == "FRESH_PRODUCER_LOCK_CLAIM"
    assert observe_writer_owner(ep)["reason"] == "OWNER_NOT_REPORTED_HELD"
    assert runner_state_store.acquire_lock(ep)
    runner_state_store.release_lock(ep)


def test_canonical_daemon_lock_denial_does_not_emit_owner_claim(tmp_path, monkeypatch):
    import persistent_runner_daemon

    ep = tmp_path / "canonical"
    ep.mkdir()
    monkeypatch.setattr(persistent_runner_daemon.runner_state_store, "acquire_lock", lambda *_: False)
    assert persistent_runner_daemon.run(ep) == 25
    assert observe_writer_owner(ep)["reason"] == "NO_CANONICAL_DRIVER_OWNER_EVIDENCE"


def test_observability_write_failure_never_interrupts_driver(tmp_path, monkeypatch):
    import persistent_runner_daemon

    ep = tmp_path / "canonical"
    ep.mkdir()
    monkeypatch.setattr(persistent_runner_daemon.runtime_trace, "emit", lambda *a, **k: None)
    monkeypatch.setattr(persistent_runner_daemon.episode_runner, "run_episode", lambda *a, **k: 0)
    monkeypatch.setattr(persistent_runner_daemon.writer_owner_observation, "emit", lambda *a, **k: False)
    assert persistent_runner_daemon.run(ep, interval=1) == 0
    assert observe_writer_owner(ep)["status"] == "UNKNOWN"
    assert runner_state_store.acquire_lock(ep)
    runner_state_store.release_lock(ep)
