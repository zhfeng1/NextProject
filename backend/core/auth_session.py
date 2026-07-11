from __future__ import annotations

import json
from datetime import datetime, timezone
from time import time
from typing import Any

import redis.asyncio as aioredis
from redis.exceptions import RedisError

from backend.core.config import get_settings


class AuthSessionStoreUnavailable(RuntimeError):
    pass


class AuthSessionStore:
    def __init__(self) -> None:
        self._redis_client: aioredis.Redis | None = None
        self._memory_sessions: dict[str, dict[str, Any]] = {}

    @property
    def settings(self):
        return get_settings()

    def _session_key(self, session_id: str) -> str:
        return f"{self.settings.auth_session_key_prefix}:session:{session_id}"

    def _user_sessions_key(self, user_id: str) -> str:
        return f"{self.settings.auth_session_key_prefix}:user:{user_id}:sessions"

    def _redis(self) -> aioredis.Redis:
        if self._redis_client is None:
            self._redis_client = aioredis.from_url(
                self.settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=3,
                socket_timeout=3,
            )
        return self._redis_client

    async def create_session(
        self,
        *,
        session_id: str,
        user_id: str,
        ttl_seconds: int,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        payload = {
            "session_id": session_id,
            "user_id": user_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": int(time()) + ttl_seconds,
            **(metadata or {}),
        }
        if self.settings.auth_session_backend == "memory":
            self._memory_sessions[session_id] = payload
            return
        try:
            client = self._redis()
            async with client.pipeline(transaction=True) as pipe:
                pipe.setex(self._session_key(session_id), ttl_seconds, json.dumps(payload, ensure_ascii=False))
                pipe.sadd(self._user_sessions_key(user_id), session_id)
                pipe.expire(self._user_sessions_key(user_id), ttl_seconds)
                await pipe.execute()
        except RedisError as exc:
            raise AuthSessionStoreUnavailable("Redis session store is unavailable") from exc

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        if not session_id:
            return None
        if self.settings.auth_session_backend == "memory":
            payload = self._memory_sessions.get(session_id)
            if payload and int(payload.get("expires_at") or 0) > int(time()):
                return dict(payload)
            self._memory_sessions.pop(session_id, None)
            return None
        try:
            raw = await self._redis().get(self._session_key(session_id))
        except RedisError as exc:
            raise AuthSessionStoreUnavailable("Redis session store is unavailable") from exc
        if not raw:
            return None
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None

    async def delete_session(self, session_id: str) -> None:
        if not session_id:
            return
        if self.settings.auth_session_backend == "memory":
            self._memory_sessions.pop(session_id, None)
            return
        try:
            client = self._redis()
            raw = await client.get(self._session_key(session_id))
            user_id = ""
            if raw:
                try:
                    user_id = str((json.loads(raw) or {}).get("user_id") or "")
                except (TypeError, ValueError):
                    user_id = ""
            async with client.pipeline(transaction=True) as pipe:
                pipe.delete(self._session_key(session_id))
                if user_id:
                    pipe.srem(self._user_sessions_key(user_id), session_id)
                await pipe.execute()
        except RedisError as exc:
            raise AuthSessionStoreUnavailable("Redis session store is unavailable") from exc

    async def close(self) -> None:
        if self._redis_client is not None:
            await self._redis_client.aclose()
            self._redis_client = None


auth_session_store = AuthSessionStore()
