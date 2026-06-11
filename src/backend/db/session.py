from __future__ import annotations

import os
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@lru_cache(maxsize=1)
def _engine():
    return create_async_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)


def get_session() -> async_sessionmaker[AsyncSession]:
    """Return a cached async session factory. Call inside async functions."""
    return async_sessionmaker(_engine(), class_=AsyncSession, expire_on_commit=False)


async def dispose_engine() -> None:
    """Dispose the cached engine's connection pool and clear the cache.

    The engine's asyncpg connections are bound to the event loop active
    when they're created. Callers that run a fresh event loop per
    invocation (e.g. Celery tasks via asyncio.run) must call this at the
    end of each invocation, or the next invocation's loop will fail with
    "Future attached to a different loop".
    """
    await _engine().dispose()
    _engine.cache_clear()
