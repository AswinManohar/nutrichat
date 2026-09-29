"""Enable RLS on the tables added by 013/014/015.

Supabase exposes the `public` schema through PostgREST, so a table without
row level security is readable and writable by anyone holding the anon key
(which ships in the Android app). Migrations 002/003/007 enable RLS with an
owner policy; 013 (device_token), 014 (coaching_response, guideline_chunk)
and 015 (food_correction) did not.

- device_token, coaching_response, food_correction: owner-only policy
  (auth.uid() = user_id), same idiom as 007.
- guideline_chunk: shared curated corpus written by the ingest CLI and read
  by the backend only; RLS on with no policy, so the REST API sees nothing.

The backend connects as the table owner, which bypasses RLS, so server
behaviour is unchanged.

Revision ID: 017_rls_new_tables
Revises: 016_merge
Create Date: 2026-09-29
"""

from __future__ import annotations

from alembic import op

revision = "017_rls_new_tables"
down_revision = "016_merge"
branch_labels = None
depends_on = None

_OWNER_TABLES = ("device_token", "coaching_response", "food_correction")


def upgrade() -> None:
    for table in _OWNER_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_owner ON {table} "
            "USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id)"
        )
    op.execute("ALTER TABLE guideline_chunk ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("ALTER TABLE guideline_chunk DISABLE ROW LEVEL SECURITY")
    for table in reversed(_OWNER_TABLES):
        op.execute(f"DROP POLICY IF EXISTS {table}_owner ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
