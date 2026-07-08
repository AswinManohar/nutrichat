"""Trigram GIN index on food_source.food_name for the USDA cache lookup.

The USDA cache probe in agent/tools/usda.py filters with
`food_name ILIKE '%name%'`. The leading wildcard makes the existing B-tree
`ix_food_source_food_name` unusable, so the probe degrades to a sequential
scan as the cache grows. A pg_trgm GIN index serves that pattern, letting
Postgres index-scan the same query — no change to the query or its results,
purely a latency fix.

The existing B-tree index is kept: it still serves the exact-match
LLM-estimate lookup (`food_name = :normalized`).

Revision ID: 011
Revises: 010
Create Date: 2026-07-08
"""

from __future__ import annotations

from alembic import op

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_food_source_food_name_trgm "
        "ON food_source USING gin (food_name gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_food_source_food_name_trgm")
    # pg_trgm may be used by other objects — leave the extension in place.
