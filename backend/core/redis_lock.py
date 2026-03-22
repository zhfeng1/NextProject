"""Redis-based distributed lock for site-level task concurrency control."""
from __future__ import annotations

import redis

from backend.core.config import get_settings

_LOCK_PREFIX = "nextproject:site-lock:"
_DEFAULT_TTL = 2100  # task timeout (1800s) + 300s margin

# Lua script: only the lock holder can release
_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""


def _get_redis() -> redis.Redis:
    settings = get_settings()
    return redis.Redis.from_url(settings.redis_url, decode_responses=True)


def acquire_site_lock(site_id: str, task_id: str, ttl: int = _DEFAULT_TTL) -> bool:
    """Try to acquire a lock for the given site. Returns True if acquired."""
    r = _get_redis()
    return bool(r.set(f"{_LOCK_PREFIX}{site_id}", task_id, nx=True, ex=ttl))


def release_site_lock(site_id: str, task_id: str) -> bool:
    """Release the lock only if held by the given task. Returns True if released."""
    r = _get_redis()
    result = r.eval(_RELEASE_SCRIPT, 1, f"{_LOCK_PREFIX}{site_id}", task_id)
    return bool(result)


__all__ = [
    "acquire_site_lock",
    "release_site_lock",
]
