from platform.state.episode_lock_manager import EpisodeLockManager
from platform.state.redis_runtime_state_store import RedisRuntimeStateStore
from platform.state.worker_heartbeat import WorkerHeartbeat


class FakeRedis:
    def __init__(self):
        self.data = {}
        self.expires = {}
        self.nx_calls = 0

    def set(self, key, value, ex=None, nx=False):
        if nx:
            self.nx_calls += 1
            if key in self.data:
                return None
        self.data[key] = value
        self.expires[key] = ex
        return True

    def get(self, key):
        return self.data.get(key)

    def delete(self, key):
        self.data.pop(key, None)
        self.expires.pop(key, None)

    def eval(self, script, numkeys, *args):
        assert numkeys == 1
        key, expected = args[:2]
        if self.data.get(key) != expected:
            return 0
        if 'DEL' in script:
            self.delete(key)
        elif 'EXPIRE' in script:
            self.expires[key] = int(args[2])
        return 1


class LegacyStoreWithoutAtomicWrite:
    """只实现 RuntimeStateStore 抽象方法的旧存储，用于验证回退路径。"""

    def __init__(self):
        self.data = {}

    def set_state(self, key, value, expire_seconds=None):
        self.data[key] = value

    def get_state(self, key):
        return self.data.get(key)

    def delete_state(self, key):
        self.data.pop(key, None)


def test_runtime_state_store():
    store = RedisRuntimeStateStore(FakeRedis())

    store.set_state("task:1", {"status": "RUNNING"})

    result = store.get_state("task:1")

    assert result["status"] == "RUNNING"

    store.delete_state("task:1")

    assert store.get_state("task:1") is None


def test_set_if_absent_writes_once():
    client = FakeRedis()
    store = RedisRuntimeStateStore(client)

    assert store.set_if_absent("lock:a", {"owner": "runtime-a"}) is True
    assert store.set_if_absent("lock:a", {"owner": "runtime-b"}) is False

    assert store.get_state("lock:a") == {"owner": "runtime-a"}
    assert client.nx_calls == 2


def test_set_if_absent_without_client_returns_false():
    store = RedisRuntimeStateStore()

    assert store.set_if_absent("lock:a", {"owner": "runtime-a"}) is False


def test_episode_lock_manager_uses_atomic_write():
    client = FakeRedis()
    store = RedisRuntimeStateStore(client)
    locks = EpisodeLockManager(store)

    assert locks.acquire("ep1", "runtime-a") is True
    assert locks.acquire("ep1", "runtime-b") is False

    assert client.nx_calls == 2
    assert store.get_state("storyos:lock:episode:ep1")["owner_id"] == "runtime-a"


def test_episode_lock_manager_release_allows_reacquire():
    store = RedisRuntimeStateStore(FakeRedis())
    locks = EpisodeLockManager(store)

    token = locks.acquire_lease("ep1", "runtime-a")
    assert token
    assert locks.release("ep1", "runtime-a", token) is True

    assert store.get_state("storyos:lock:episode:ep1") is None
    assert locks.acquire("ep1", "runtime-b") is True


def test_episode_lock_manager_falls_back_without_atomic_support():
    store = LegacyStoreWithoutAtomicWrite()
    locks = EpisodeLockManager(store)

    assert locks.acquire("ep1", "runtime-a") is False
    assert locks.acquire("ep1", "runtime-b") is False


def test_worker_heartbeat_passes_ttl_to_store():
    client = FakeRedis()
    store = RedisRuntimeStateStore(client)
    heartbeat = WorkerHeartbeat(store)

    heartbeat.heartbeat("worker-1", ttl_seconds=30)

    key = "storyos:worker:worker-1:heartbeat"
    assert client.expires[key] == 30
    assert store.get_state(key)["status"] == "ONLINE"


def test_worker_heartbeat_without_ttl_keeps_previous_behaviour():
    client = FakeRedis()
    store = RedisRuntimeStateStore(client)

    WorkerHeartbeat(store).heartbeat("worker-2")

    assert client.expires["storyos:worker:worker-2:heartbeat"] is None
