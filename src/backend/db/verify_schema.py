"""Quick smoke-test: connect to Postgres and verify all 6 tables + key indexes exist.

Usage:
    DATABASE_URL=postgresql+asyncpg://... uv run python -m backend.db.verify_schema
"""

from __future__ import annotations

import asyncio
import os
import sys

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

EXPECTED_TABLES = {
    "user_goal",
    "meal_log",
    "user_memory",
    "food_source",
    "daily_summary",
    "weekly_summary",
}

EXPECTED_INDEXES = {
    "ix_meal_log_user_logged_at",
    "ix_meal_log_user_protein",
    "ix_meal_log_hybrid",
    "ix_meal_log_embedding",
    "ix_user_memory_embedding",
    "ix_user_memory_user_id",
    "ix_food_source_food_name",
    "ix_daily_summary_user_date",
    "ix_weekly_summary_user_week",
}


async def verify() -> None:
    url = os.environ["DATABASE_URL"]
    engine = create_async_engine(url, echo=False)

    async with engine.connect() as conn:
        # Tables
        tables: set[str] = set(
            await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())
        )
        missing_tables = EXPECTED_TABLES - tables
        if missing_tables:
            print(f"FAIL — missing tables: {missing_tables}")
            sys.exit(1)
        print(f"OK   tables: {sorted(EXPECTED_TABLES)}")

        # Indexes (query pg_indexes for all expected names)
        result = await conn.execute(
            text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")
        )
        existing_indexes = {row[0] for row in result}
        missing_indexes = EXPECTED_INDEXES - existing_indexes
        if missing_indexes:
            print(f"FAIL — missing indexes: {missing_indexes}")
            sys.exit(1)
        print(f"OK   indexes: {sorted(EXPECTED_INDEXES)}")

        # pgvector extension
        result = await conn.execute(
            text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
        )
        if not result.fetchone():
            print("FAIL — pgvector extension not installed")
            sys.exit(1)
        print("OK   pgvector extension")

    await engine.dispose()
    print("\nSchema verified successfully.")


if __name__ == "__main__":
    asyncio.run(verify())
