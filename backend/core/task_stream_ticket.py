from __future__ import annotations

import json
import secrets
from time import time
from typing import Any

import redis.asyncio as aioredis
from redis.exceptions import RedisError

from backend.core.config import get_settings


class TaskStreamTicketStoreUnavailable(RuntimeError):
    pass


class TaskStreamTicketStore:
    """Short-lived, one-time tickets used to authenticate browser WebSockets."""

    def __init__(self) -> None:
        self._redis_client: aioredis.Redis | None = None
        self._memory_tickets: dict[str, dict[str, Any]] = {}

    @property
    def settings(self):
        return get_settings()

    def _key(self, ticket: str) -> str:
        return f"{self.settings.auth_session_key_prefix}:task-stream-ticket:{ticket}"

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

    async def issue(
        self,
        *,
        user_id: str,
        task_id: str,
        ttl_seconds: int = 60,
    ) -> str:
        ticket = secrets.token_urlsafe(32)
        payload = {
            "user_id": str(user_id),
            "task_id": str(task_id),
            "expires_at": int(time()) + ttl_seconds,
        }
        if self.settings.auth_session_backend == "memory":
            self._memory_tickets[ticket] = payload
            return ticket
        try:
            await self._redis().setex(
                self._key(ticket),
                ttl_seconds,
                json.dumps(payload, ensure_ascii=False),
            )
        except RedisError as exc:
            raise TaskStreamTicketStoreUnavailable("Task stream ticket store is unavailable") from exc
        return ticket

    async def consume(self, *, ticket: str, task_id: str) -> dict[str, Any] | None:
        if not ticket:
            return None
        if self.settings.auth_session_backend == "memory":
            payload = self._memory_tickets.pop(ticket, None)
        else:
            try:
                raw = await self._redis().getdel(self._key(ticket))
            except RedisError as exc:
                raise TaskStreamTicketStoreUnavailable("Task stream ticket store is unavailable") from exc
            if not raw:
                return None
            try:
                payload = json.loads(raw)
            except (TypeError, ValueError):
                return None
        if not isinstance(payload, dict):
            return None
        if int(payload.get("expires_at") or 0) < int(time()):
            return None
        if str(payload.get("task_id") or "") != str(task_id):
            return None
        return payload

    async def close(self) -> None:
        if self._redis_client is not None:
            await self._redis_client.aclose()
            self._redis_client = None
        self._memory_tickets.clear()


task_stream_ticket_store = TaskStreamTicketStore()

