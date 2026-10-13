"""Redis runtime state storage, with fail-closed atomic fenced lease operations."""
import json

from platform.state.runtime_state_store import RuntimeStateStore


_DELETE_OWNED = (
    'if redis.call("GET", KEYS[1]) == ARGV[1] then '
    'return redis.call("DEL", KEYS[1]) else return 0 end'
)
_RENEW_OWNED = (
    'if redis.call("GET", KEYS[1]) == ARGV[1] then '
    'return redis.call("EXPIRE", KEYS[1], ARGV[2]) else return 0 end'
)


class RedisRuntimeStateStore(RuntimeStateStore):
    def __init__(self, client=None):
        self.client = client

    def set_state(self, key, value, expire_seconds=None):
        if self.client:
            self.client.set(key, json.dumps(value), ex=expire_seconds)

    def set_if_absent(self, key, value, expire_seconds=None):
        if not self.client:
            return False
        result = self.client.set(key, json.dumps(value), ex=expire_seconds, nx=True)
        return bool(result)

    def get_state(self, key):
        if not self.client:
            return None
        value = self.client.get(key)
        return json.loads(value) if value else None

    def delete_state(self, key):
        if self.client:
            self.client.delete(key)

    def compare_and_delete(self, key, expected):
        """Lua GET+DEL atomic against serialized lock including unique token."""
        if not self.client or not callable(getattr(self.client, "eval", None)):
            return False
        return bool(self.client.eval(_DELETE_OWNED, 1, key, json.dumps(expected)))

    def compare_and_expire(self, key, expected, expire_seconds):
        """Atomic lease heartbeat; stale token cannot extend a successor."""
        if (not self.client or not callable(getattr(self.client, "eval", None))
                or not isinstance(expire_seconds, int) or expire_seconds <= 0):
            return False
        return bool(self.client.eval(_RENEW_OWNED, 1, key, json.dumps(expected), expire_seconds))
