"""Turn user_memory into a curated, typed preference profile.

Until now user_memory was append-only: every row had category 'preference',
nothing was ever replaced or removed, and the coach saw only the three rows
nearest the current message. The profile is now small, typed, and rendered
in full into every coaching prompt (see agent/memory.py).

- category: constrained to the fact kinds. 'preference' stays valid for rows
  written before this migration until the backfill re-types them.
- source: who wrote the fact. Existing rows were extracted from chat.
- deleted_at: tombstone for a fact the user removed, so the curator does not
  learn it again.
- ix_user_memory_live: the per-turn read is "live rows for one user".
- RLS: 001 created the table without it; owner-only policy as in 007/017.
  The backend connects as the table owner, which bypasses RLS.

The embedding column and its ivfflat index are left in place for the legacy
read path and dropped in a later migration.

Revision ID: 018_user_memory_profile
Revises: 017_rls_new_tables
Create Date: 2026-10-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "018_user_memory_profile"
down_revision = "017_rls_new_tables"
branch_labels = None
depends_on = None

_KINDS = ("restriction", "dislike", "like", "habit", "context", "preference")
_SOURCES = ("stated", "inferred_from_chat", "inferred_from_logs")


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.add_column(
        "user_memory",
        sa.Column(
            "source",
            sa.String(20),
            nullable=False,
            server_default="inferred_from_chat",
        ),
    )
    op.add_column(
        "user_memory",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_user_memory_category", "user_memory", f"category IN ({_in_list(_KINDS)})"
    )
    op.create_check_constraint(
        "ck_user_memory_source", "user_memory", f"source IN ({_in_list(_SOURCES)})"
    )
    op.execute(
        "CREATE INDEX ix_user_memory_live ON user_memory (user_id) "
        "WHERE deleted_at IS NULL"
    )
    op.execute("ALTER TABLE user_memory ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS user_memory_owner ON user_memory")
    op.execute(
        "CREATE POLICY user_memory_owner ON user_memory "
        "USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id)"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS user_memory_owner ON user_memory")
    op.execute("ALTER TABLE user_memory DISABLE ROW LEVEL SECURITY")
    op.execute("DROP INDEX IF EXISTS ix_user_memory_live")
    op.drop_constraint("ck_user_memory_source", "user_memory", type_="check")
    op.drop_constraint("ck_user_memory_category", "user_memory", type_="check")
    # Tombstones would come back to life without deleted_at.
    op.execute("DELETE FROM user_memory WHERE deleted_at IS NOT NULL")
    op.drop_column("user_memory", "deleted_at")
    op.drop_column("user_memory", "source")
