"""File-local acceptance tests for lossless tick rotation."""
from __future__ import annotations

import gzip
import json
import pytest
from scripts.storyos_runtime_tick_rotation import maybe_rotate_tick_log

def test_under_threshold_does_not_change_log(tmp_path):
    log = tmp_path / "ticks.jsonl"
    data = b'{"tick":1}\n'
    log.write_bytes(data)
    assert maybe_rotate_tick_log(log, max_bytes=1024) is None
    assert log.read_bytes() == data
    assert not (tmp_path / "tick-archives").exists()

def test_rotation_is_lossless_and_next_append_starts_fresh(tmp_path):
    log = tmp_path / "worker-ticks.jsonl"
    rows = b"".join(json.dumps({"tick": i}).encode() + b"\n" for i in range(220))
    log.write_bytes(rows)
    saved = maybe_rotate_tick_log(log, max_bytes=128)
    assert saved is not None and saved.suffix == ".gz"
    assert not log.exists()
    assert gzip.decompress(saved.read_bytes()) == rows
    with log.open("a", encoding="utf-8") as handle:
        handle.write('{"tick":221}\n')
    assert log.read_text(encoding="utf-8") == '{"tick":221}\n'
    assert gzip.decompress(saved.read_bytes()) == rows

def test_failed_compression_preserves_original_snapshot(tmp_path, monkeypatch):
    log = tmp_path / "ticks.jsonl"
    data = b'{"tick":1}\n' * 20
    log.write_bytes(data)
    def crash(*args, **kwargs):
        raise OSError("simulated compression outage")
    monkeypatch.setattr("scripts.storyos_runtime_tick_rotation.shutil.copyfileobj", crash)
    archived = maybe_rotate_tick_log(log, max_bytes=50)
    assert archived is not None and archived.suffix == ".jsonl"
    assert archived.read_bytes() == data
    assert not list((tmp_path / "tick-archives").glob("*.part"))
    log.write_bytes(b'{"tick":21}\n')
    assert log.read_bytes() == b'{"tick":21}\n'

def test_never_rotates_symlink_or_disabled_log(tmp_path):
    log = tmp_path / "ticks.jsonl"
    log.write_bytes(b"y" * 500)
    assert maybe_rotate_tick_log(log, max_bytes=0) is None
    link = tmp_path / "linked.jsonl"
    try:
        link.symlink_to(log)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation needs privilege")
    with pytest.raises(ValueError):
        maybe_rotate_tick_log(link, max_bytes=1)
    assert log.read_bytes() == b"y" * 500

def test_launcher_exposes_rotation_limit(tmp_path):
    from scripts.phase9_runtime_launcher import build_children
    specs = build_children(run_root=tmp_path, worker_id="test", interval=1,
                           consistency_every=2, stuck_minutes=1, jsonl_root=str(tmp_path),
                           tick_log_max_mib=7)
    worker = next(c for c in specs if c.name == "worker")
    assert worker.cmd[worker.cmd.index("--tick-log-max-mib") + 1] == "7"
    assert len(specs) == 2

def test_worker_config_opt_out_and_negative(tmp_path):
    from scripts.phase9_runtime_worker import RuntimeOperationsWorker
    x = RuntimeOperationsWorker(worker_id="test", tick_log=tmp_path / "ticks.jsonl",
                                tick_log_max_mib=0)
    assert x.tick_log_max_bytes == 0
    with pytest.raises(ValueError):
        RuntimeOperationsWorker(worker_id="test", tick_log_max_mib=-1)
