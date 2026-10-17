"""Redis-only Driver projection must survive long official reviews."""
import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "episodes/_system"))
import runtime_driver
from platform.state.storyos_hot_state import EpisodeHotStateStore


class ExpiringMemoryStore:
    def __init__(self):
        self.now = 0
        self.data = {}

    def set_state(self, key, value, expire_seconds=None):
        until = self.now + expire_seconds if expire_seconds is not None else None
        self.data[key] = (copy.deepcopy(value), until)

    def get_state(self, key):
        item = self.data.get(key)
        if item is None:
            return None
        value, until = item
        if until is not None and self.now >= until:
            del self.data[key]
            return None
        return copy.deepcopy(value)

    def delete_state(self, key):
        self.data.pop(key, None)


def test_driver_state_survives_40_minute_review():
    redis = ExpiringMemoryStore()
    store = EpisodeHotStateStore(redis)
    store.put("episode", "DRIVER_STATE", {"pid": 30516, "rc": "RUNNING"})
    redis.now += 60 * 40
    assert store.get("episode", "DRIVER_STATE") == {"pid": 30516, "rc": "RUNNING"}


def _mock_redis_driver(monkeypatch, store):
    monkeypatch.setattr(runtime_driver.hot_state_bridge, "compatibility_write_allowed", lambda: False)
    monkeypatch.setattr(runtime_driver.hot_state_bridge, "mirror",
                        lambda _ep, kind, value: store.put("episode", kind, value))
    monkeypatch.setattr(runtime_driver.hot_state_bridge, "read",
                        lambda _ep, kind: {"mode": "redis", "value": store.get("episode", kind)})


def test_driver_status_visible_after_long_review(monkeypatch, tmp_path):
    redis = ExpiringMemoryStore()
    store = EpisodeHotStateStore(redis)
    ep = tmp_path / "episode"
    ep.mkdir()
    _mock_redis_driver(monkeypatch, store)
    monkeypatch.setattr(runtime_driver, "liveness", lambda pid: "ALIVE")
    monkeypatch.setattr(runtime_driver, "_beating", lambda ep, pid: True)
    runtime_driver._begin_record(ep, {"pid": 30516, "rc": "RUNNING"})
    redis.now += 60 * 40
    result = runtime_driver.status(ep)
    assert result["driver_state"] == "RUNNING"
    assert result["pid"] == 30516


def test_dead_driver_still_requires_restart_evidence(monkeypatch, tmp_path):
    redis = ExpiringMemoryStore()
    store = EpisodeHotStateStore(redis)
    ep = tmp_path / "episode"
    ep.mkdir()
    _mock_redis_driver(monkeypatch, store)
    monkeypatch.setattr(runtime_driver, "liveness", lambda pid: "DEAD")
    runtime_driver._begin_record(ep, {"pid": 30516, "rc": "RUNNING"})
    redis.now += 60 * 40
    result = runtime_driver.status(ep)
    assert result["driver_state"] == "ABNORMAL_DISAPPEARANCE"
    assert result["liveness"] == "DEAD"
