"""Shared helpers for Celery tasks.

Each Celery task runs inside a forked worker process with its own event loop
(via ``asyncio.run``). The module-level SQLAlchemy engine is created at import
time on a *different* loop, so reusing it causes "Future attached to a
different loop" errors. This helper creates a fresh engine per task invocation.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.core.config import get_settings


@asynccontextmanager
async def task_db_session() -> AsyncIterator[AsyncSession]:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, future=True, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with session_factory() as session:
            yield session
    finally:
        await engine.dispose()
