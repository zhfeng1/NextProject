from collections.abc import AsyncIterator

from sqlalchemy.pool import StaticPool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.core.config import get_settings
from backend.models.base import Base


settings = get_settings()


if settings.database_url.startswith("postgresql"):
    engine = create_async_engine(
        settings.database_url,
        echo=settings.debug,
        future=True,
        pool_pre_ping=True,
        pool_size=20,
        max_overflow=40,
        pool_timeout=30,
        pool_recycle=3600,
    )
else:
    # SQLite does not support pool_size/max_overflow; use StaticPool instead
    engine = create_async_engine(
        settings.database_url,
        echo=settings.debug,
        future=True,
        pool_pre_ping=True,
        poolclass=StaticPool,
    )

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
