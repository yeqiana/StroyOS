from platform.state.worker_heartbeat import WorkerHeartbeat
from platform.state.episode_lock_manager import EpisodeLockManager


class FakeStateStore:
    def __init__(self):
        self.data = {}

    def set_state(self, key, value, expire_seconds=None):
        self.data[key] = value

    def get_state(self, key):
        return self.data.get(key)

    def delete_state(self, key):
        self.data.pop(key, None)


def test_worker_heartbeat():
    store = FakeStateStore()
    heartbeat = WorkerHeartbeat(store)

    heartbeat.heartbeat("worker01")

    assert store.get_state("storyos:worker:worker01:heartbeat")["status"] == "ONLINE"


def test_episode_lock():
    store = FakeStateStore()
    manager = EpisodeLockManager(store)

    # A legacy get-then-set store lacks atomic NX+TTL/CAS. Fail closed.
    assert manager.acquire("ep001", "worker01") is False
    assert manager.acquire("ep001", "worker02") is False
    assert manager.release("ep001") is False
    assert store.get_state("storyos:lock:episode:ep001") is None
