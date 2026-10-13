"""R3 slot2: atomic fenced Owner lock; stale owner cannot delete successor."""
from __future__ import annotations
import json
from threading import Lock
from platform.state.episode_lock_manager import EpisodeLockManager
from platform.state.redis_runtime_state_store import RedisRuntimeStateStore

class FakeRedis:
    def __init__(self):
        self.data={}
        self.clock_lock=Lock()
    def set(self,key,value,ex=None,nx=False):
        with self.clock_lock:
            if nx and key in self.data:return False
            self.data[key]=value
            return True
    def get(self,key):
        return self.data.get(key)
    def eval(self,script,numkeys,*args):
        assert numkeys==1
        key,expected=args[:2]
        with self.clock_lock:
            if self.data.get(key)!=expected: return 0
            if "DEL" in script:
                self.data.pop(key,None)
            return 1

def test_stale_owner_cannot_release_new_lease():
    backend=FakeRedis()
    lock=EpisodeLockManager(RedisRuntimeStateStore(backend))
    token=lock.acquire_lease("ep1","worker-a")
    assert token
    assert lock.release("ep1","worker-a","wrong-token") is False
    assert lock.acquire_lease("ep1","worker-b") is None
    assert lock.release("ep1","worker-a",token) is True
    successor=lock.acquire_lease("ep1","worker-b")
    assert successor and successor!=token
    assert lock.release("ep1","worker-a",token) is False
    assert json.loads(backend.get("storyos:lock:episode:ep1"))["owner_id"]=="worker-b"

def test_unverified_store_never_takes_lease():
    class LegacyStore:
        def get_state(self,key): return None
        def set_state(self,key,value): raise AssertionError("no non atomic fallback")
        def delete_state(self,key): raise AssertionError("no blind delete")
    lock=EpisodeLockManager(LegacyStore())
    assert lock.acquire("e","w") is False
    assert lock.acquire_lease("e","w") is None
    assert lock.release("e","w","t") is False

def test_liveness_renew_requires_same_owner_token():
    client=FakeRedis()
    locks=EpisodeLockManager(RedisRuntimeStateStore(client))
    token=locks.acquire_lease("ep1","one",ttl_seconds=60)
    assert token
    assert locks.renew("ep1","two",token,ttl_seconds=60) is False
    assert locks.renew("ep1","one","wrong",ttl_seconds=60) is False
    assert locks.renew("ep1","one",token,ttl_seconds=60) is True

def test_missing_redis_eval_fails_closed_without_blind_delete():
    class AtomicNXOnly:
        def __init__(self):self.data={}
        def set_if_absent(self,key,payload,expire_seconds=None):
            self.data[key]=payload;return True
        def get_state(self,key):return self.data.get(key)
        def delete_state(self,key):raise AssertionError("blind release")
    locks=EpisodeLockManager(AtomicNXOnly())
    token=locks.acquire_lease("ep","a")
    assert token
    assert locks.release("ep","a",token) is False
