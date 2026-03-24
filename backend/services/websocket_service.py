from __future__ import annotations

import asyncio
import json
from collections import defaultdict

from fastapi import WebSocket


REDIS_CHANNEL_PREFIX = "task_logs:"


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: dict[str, set[WebSocket]] = defaultdict(set)

    async def connect(self, task_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections[task_id].add(websocket)

    def disconnect(self, task_id: str, websocket: WebSocket) -> None:
        self.active_connections[task_id].discard(websocket)
        if not self.active_connections[task_id]:
            self.active_connections.pop(task_id, None)

    async def broadcast(self, task_id: str, message: dict) -> None:
        stale: list[WebSocket] = []
        for connection in list(self.active_connections.get(task_id, set())):
            try:
                await connection.send_json(message)
            except Exception:
                stale.append(connection)
        for item in stale:
            self.disconnect(task_id, item)

    def publish(self, task_id: str, message: dict) -> None:
        """Publish via Redis pub/sub so Celery workers can reach WS clients."""
        try:
            import redis as redis_sync
            from backend.core.config import get_settings
            r = redis_sync.from_url(get_settings().redis_url)
            channel = f"{REDIS_CHANNEL_PREFIX}{task_id}"
            r.publish(channel, json.dumps(message))
            r.close()
        except Exception:
            # Fallback: direct broadcast if already on the event loop
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.broadcast(task_id, message))
            except RuntimeError:
                pass

    async def start_redis_subscriber(self, redis_url: str) -> None:
        """Background task: subscribe to all task_logs channels and forward to WS."""
        import redis.asyncio as aioredis
        while True:
            r = None
            pubsub = None
            try:
                r = aioredis.from_url(redis_url)
                pubsub = r.pubsub()
                await pubsub.psubscribe(f"{REDIS_CHANNEL_PREFIX}*")
                while True:
                    raw = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                    if raw is None:
                        continue
                    if raw.get("type") != "pmessage":
                        continue
                    try:
                        channel: str = raw["channel"].decode() if isinstance(raw["channel"], bytes) else raw["channel"]
                        task_id = channel.removeprefix(REDIS_CHANNEL_PREFIX)
                        data = raw["data"]
                        message = json.loads(data.decode() if isinstance(data, bytes) else data)
                        await self.broadcast(task_id, message)
                    except Exception:
                        continue
            except Exception:
                await asyncio.sleep(2)
            finally:
                try:
                    if pubsub:
                        await pubsub.close()
                    if r:
                        await r.aclose()
                except Exception:
                    pass


websocket_manager = ConnectionManager()
