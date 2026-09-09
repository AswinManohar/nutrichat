"""Coaching feedback loop + guideline retrieval tables.

Adds `guideline_chunk` (embedded passages from curated public dietary
guidelines, pgvector IVFFlat cosine index), `coaching_response` (every
coaching reply with its inputs, ratable by the user), and
`user_goal.conditions` (declared health conditions used to filter which
guideline passages the coach may cite).

Revision ID: 012
Revises: 011
Create Date: 2026-09-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # user_goal.conditions
    op.add_column(
        "user_goal",
        sa.Column(
            "conditions",
            ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )

    # guideline_chunk
    op.create_table(
        "guideline_chunk",
        sa.Column(
            "id",
            UUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("source_title", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("section", sa.Text(), nullable=False),
        sa.Column("condition", sa.Text(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False, unique=True),
        # Placeholder type, altered to vector(768) below (same idiom as 001).
        sa.Column("embedding", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.execute(
        "ALTER TABLE guideline_chunk "
        "ALTER COLUMN embedding TYPE vector(768) USING NULL"
    )
    op.create_index("ix_guideline_chunk_condition", "guideline_chunk", ["condition"])
    op.execute("""
        CREATE INDEX ix_guideline_chunk_embedding
        ON guideline_chunk
        USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100)
        """)

    # coaching_response
    op.create_table(
        "coaching_response",
        sa.Column("id", UUID(), primary_key=True),
        sa.Column(
            "user_id",
            UUID(),
            sa.ForeignKey("user_goal.user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("conversation_id", sa.Text(), nullable=True),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("parsed_query", JSONB(), nullable=False),
        sa.Column(
            "retrieved_chunk_ids",
            ARRAY(UUID()),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("citations", JSONB(), nullable=False),
        sa.Column("response_text", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("trace_id", sa.Text(), nullable=True),
        sa.Column("rating", sa.Text(), nullable=True),
        sa.Column("rating_comment", sa.String(500), nullable=True),
        sa.Column("rated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_coaching_response_user_id", "coaching_response", ["user_id"])
    op.create_index(
        "ix_coaching_response_created_at", "coaching_response", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_coaching_response_created_at", table_name="coaching_response")
    op.drop_index("ix_coaching_response_user_id", table_name="coaching_response")
    op.drop_table("coaching_response")
    op.execute("DROP INDEX IF EXISTS ix_guideline_chunk_embedding")
    op.drop_index("ix_guideline_chunk_condition", table_name="guideline_chunk")
    op.drop_table("guideline_chunk")
    op.drop_column("user_goal", "conditions")
