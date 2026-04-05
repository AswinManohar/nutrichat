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
