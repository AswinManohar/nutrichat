from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool


async def _check_connection(conn: AsyncConnection[Any]) -> None:
    """Validate a pooled connection, raising if it is dead.

    Stands in for `AsyncConnectionPool.check_connection`, which issues an
    *empty* statement. An empty statement cannot be prepared or cached, so
    under `prepare_threshold=0` psycopg pays Parse and Bind/Execute as two
    separate round trips on every checkout and never warms up — 293 ms
    against the Supabase pooler, versus 145 ms for a query that does cache.
    `SELECT 1` detects a dead connection identically at one round trip.
    """
    await conn.execute("SELECT 1")


@asynccontextmanager
async def pooled_checkpointer() -> AsyncIterator[AsyncPostgresSaver]:
    """Yield an AsyncPostgresSaver backed by a self-healing connection pool.

    `AsyncPostgresSaver.from_conn_string` holds a single connection for the
    process lifetime. Supabase's pooler closes idle connections, after which
    every checkpointer call raises `psycopg.OperationalError: the connection
    is closed` until the process restarts. The pool instead validates
    connections on checkout (`check`) and retires idle ones (`max_idle`),
    replacing dropped connections transparently.
    """
    db_url = os.environ.get(
        "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/postgres"
    )
    # psycopg (v3) needs plain postgresql://, not the SQLAlchemy +asyncpg form
    psycopg_url = db_url.replace("postgresql+asyncpg://", "postgresql://")

    async with AsyncConnectionPool(
        psycopg_url,
        min_size=1,
        max_size=4,
        max_idle=240.0,
        check=_check_connection,
        open=False,
        # Mirror AsyncPostgresSaver.from_conn_string's connection settings
        kwargs={
            "autocommit": True,
            "prepare_threshold": 0,
            "row_factory": dict_row,
        },
    ) as pool:
        checkpointer = AsyncPostgresSaver(pool)
        await checkpointer.setup()
        yield checkpointer
