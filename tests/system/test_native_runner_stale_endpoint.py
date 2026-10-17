"""User-mode Runner stale-endpoint recovery is identity and PID fenced."""
import json
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "episodes/_system"))
import codex_user_runner as runner

USER = "RENRP\\yeqian"


def endpoint(tmp_path, **override):
    data = {
        "schema_version": runner.SCHEMA_VERSION,
        "host": "127.0.0.1", "port": 2045,
        "pid": 31836, "user": USER,
        "token": "local-test-nonce",
        "codex_user_runner": str(Path(runner.__file__).resolve()),
    }
    data.update(override)
    root = tmp_path / "runtime"
    root.mkdir(exist_ok=True)
    path = root / runner.ENDPOINT_NAME
    path.write_text(json.dumps(data), encoding="utf-8")
    return root, path


def recover(tmp_path, pid_exists, identity=USER):
    with mock.patch.object(runner, "runtime_dir", return_value=tmp_path / "runtime"), \
         mock.patch.object(runner, "current_identity", return_value=identity), \
         mock.patch("psutil.pid_exists", side_effect=pid_exists):
        return runner.reconcile_dead_endpoint()


def test_stale_dead_endpoint_recovered_without_copying_token(tmp_path):
    _, path = endpoint(tmp_path)
    state = recover(tmp_path, lambda pid: False)
    assert state["status"] == "STALE_ENDPOINT_RECOVERED"
    assert not path.exists()
    assert "local-test-nonce" not in json.dumps(state)


def test_live_pid_not_removed(tmp_path):
    _, path = endpoint(tmp_path)
    state = recover(tmp_path, lambda pid: True)
    assert state["status"] == "BLOCKED"
    assert path.exists()


def test_other_user_endpoint_not_removed(tmp_path):
    _, path = endpoint(tmp_path, user="OTHER\\user")
    state = recover(tmp_path, lambda pid: False)
    assert state["status"] == "BLOCKED"
    assert path.exists()


def test_noninteractive_identity_cannot_reclaim(tmp_path):
    _, path = endpoint(tmp_path)
    state = recover(tmp_path, lambda pid: False, identity="NT AUTHORITY\\SYSTEM")
    assert state["status"] == "BLOCKED"
    assert path.exists()


def test_untrusted_executable_and_nonloopback_rejected(tmp_path):
    _, path = endpoint(tmp_path, codex_user_runner="C:/fake/codex_user_runner.py")
    assert recover(tmp_path, lambda pid: False)["status"] == "BLOCKED"
    assert path.exists()
    path.unlink()
    _, path = endpoint(tmp_path, host="0.0.0.0")
    assert recover(tmp_path, lambda pid: False)["status"] == "BLOCKED"
    assert path.exists()


def test_unknown_pid_status_fails_closed(tmp_path):
    _, path = endpoint(tmp_path)
    state = recover(tmp_path, lambda pid: (_ for _ in ()).throw(PermissionError("no process authority")))
    assert state["status"] == "BLOCKED"
    assert path.exists()


def test_absent_endpoint_is_idempotent(tmp_path):
    (tmp_path / "runtime").mkdir()
    state = recover(tmp_path, lambda pid: True)
    assert state["status"] == "ENDPOINT_ABSENT"

def test_malformed_endpoint_not_removed(tmp_path):
    root = tmp_path / "runtime"
    root.mkdir()
    path = root / runner.ENDPOINT_NAME
    path.write_text('[]', encoding="utf-8")
    state = recover(tmp_path, lambda pid: False)
    assert state["status"] == "BLOCKED"
    assert path.exists()


def test_direct_serve_never_overwrites_existing_endpoint(monkeypatch, tmp_path):
    root, path = endpoint(tmp_path)
    before = path.read_bytes()
    monkeypatch.setattr(runner, "runtime_dir", lambda: root)
    monkeypatch.setattr(runner, "current_identity", lambda: USER)
    assert runner.serve() == 4
    assert path.read_bytes() == before