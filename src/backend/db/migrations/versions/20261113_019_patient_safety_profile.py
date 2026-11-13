"""Patient safety profile: hard profile, audit and review tables.

Adds profile_entry (the hard profile: allergies, diagnoses, medications,
limits, diet settings, exclusions), recommendation / check_failure (what was
shown and every failed check), red_flag_escalation and review_item (the
reviewer queue). See specs/013-patient-safety-profile/data-model.md.

- profile_entry rows are versioned facts: the trigger profile_entry_immutable
  rejects rewriting a value and lets state only move forward, so the record
  of what a patient declared cannot be silently changed.
- Backfill COPIES user_goal.conditions, the diet chips in
  user_goal.dietary_prefs and live user_memory restriction rows into
  profile_entry. The originals are left in place and ck_user_memory_category
  keeps 'restriction', so the release running during the deploy keeps
  working; migration 020 removes them. The category check only gains
  'cuisine', 'budget' and 'cooking_time'.
- user_memory.created_at shows when a preference was learned.
- RLS: owner-only policy on every new table, as in 017/018. The backend
  connects as the table owner, which bypasses RLS.

Revision ID: 019_patient_safety_profile
Revises: 018_user_memory_profile
Create Date: 2026-11-13
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import sqlalchemy as sa
import yaml
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "019_patient_safety_profile"
down_revision = "018_user_memory_profile"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

# Copied from agent/memory.py DIET_CHIPS: migrations must not import app code,
# and the chips as of this migration are what the backfill understands.
_DIET_CHIPS = frozenset(
    {
        "vegan",
        "vegetarian",
        "pescatarian",
        "keto",
        "paleo",
        "gluten_free",
        "dairy_free",
        "no_nuts",
        "low_carb",
        "low_sodium",
        "low_sugar",
        "high_protein",
    }
)
# The web onboarding stores this spelling; see safety/profile.py.
_DIET_ALIASES = {"pescetarian": "pescatarian"}
_ALLERGEN_FILE = (
    Path(__file__).parents[3] / "config" / "clinical" / "allergen_groups.yaml"
)

_OLD_CATEGORIES = ("restriction", "dislike", "like", "habit", "context", "preference")
_NEW_CATEGORIES = _OLD_CATEGORIES + ("cuisine", "budget", "cooking_time")
_ENTRY_TYPES = (
    "allergy",
    "diagnosis",
    "medication",
    "physical_limitation",
    "nutrient_limit",
    "diet_setting",
    "food_exclusion",
)
_NEW_TABLES = (
    "profile_entry",
    "recommendation",
    "check_failure",
    "red_flag_escalation",
    "review_item",
)


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _uuid_pk() -> sa.Column:
    return sa.Column(
        "id",
        pg.UUID(as_uuid=False),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )


def _user_fk() -> sa.Column:
    return sa.Column(
        "user_id",
        pg.UUID(as_uuid=False),
        sa.ForeignKey("user_goal.user_id", ondelete="CASCADE"),
        nullable=False,
    )


def _now_col(name: str) -> sa.Column:
    return sa.Column(
        name, sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )


def _ts(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=True)


# Columns that may be set once, from NULL, and never changed after.
_SET_ONCE = (
    "confirmed_at",
    "confirmed_by",
    "retired_at",
    "retired_by",
    "retired_reason",
    "mentioned_at",
    "acknowledged_at",
)
_ONCE_CHECK = "\n     OR ".join(
    f"(OLD.{c} IS NOT NULL AND NEW.{c} IS DISTINCT FROM OLD.{c})" for c in _SET_ONCE
)

_IMMUTABLE_FN = """
CREATE FUNCTION profile_entry_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.state = 'retired' THEN
    RAISE EXCEPTION 'profile_entry % is retired and cannot change', OLD.id;
  END IF;
  IF NEW.id IS DISTINCT FROM OLD.id
     OR NEW.user_id IS DISTINCT FROM OLD.user_id
     OR NEW.entry_type IS DISTINCT FROM OLD.entry_type
     OR NEW.value IS DISTINCT FROM OLD.value
     OR NEW.label IS DISTINCT FROM OLD.label
     OR NEW.source IS DISTINCT FROM OLD.source
     OR NEW.created_at IS DISTINCT FROM OLD.created_at
     OR NEW.created_by IS DISTINCT FROM OLD.created_by
     OR NEW.evidence IS DISTINCT FROM OLD.evidence
     OR NEW.replaces_id IS DISTINCT FROM OLD.replaces_id
     OR NEW.inference_probability IS DISTINCT FROM OLD.inference_probability THEN
    RAISE EXCEPTION 'profile_entry % is immutable apart from its state', OLD.id;
  END IF;
  IF NEW.state <> OLD.state AND NOT (
       (OLD.state = 'pending' AND NEW.state IN ('confirmed', 'retired'))
       OR (OLD.state = 'confirmed' AND NEW.state = 'retired')) THEN
    RAISE EXCEPTION 'profile_entry % cannot go from % to %',
      OLD.id, OLD.state, NEW.state;
  END IF;
  IF {once_check} THEN
    RAISE EXCEPTION 'profile_entry % state columns can be set only once', OLD.id;
  END IF;
  RETURN NEW;
END;
$$
"""


def _create_tables() -> None:
    op.create_table(
        "profile_entry",
        _uuid_pk(),
        _user_fk(),
        sa.Column("entry_type", sa.Text, nullable=False),
        sa.Column("value", pg.JSONB, nullable=False),
        sa.Column("label", sa.String(200), nullable=True),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("state", sa.Text, nullable=False),
        _now_col("created_at"),
        sa.Column("created_by", sa.Text, nullable=False),
        sa.Column("evidence", sa.Text, nullable=True),
        sa.Column(
            "replaces_id",
            pg.UUID(as_uuid=False),
            sa.ForeignKey("profile_entry.id"),
            nullable=True,
        ),
        _ts("confirmed_at"),
        sa.Column("confirmed_by", sa.Text, nullable=True),
        _ts("retired_at"),
        sa.Column("retired_by", sa.Text, nullable=True),
        sa.Column("retired_reason", sa.Text, nullable=True),
        _ts("retire_requested_at"),
        _ts("readback_asked_at"),
        sa.Column("conversation_id", sa.Text, nullable=True),
        sa.Column("client_request_id", sa.Text, nullable=True),
        sa.Column("inference_probability", sa.Float(24), nullable=True),
        _ts("mentioned_at"),
        _ts("acknowledged_at"),
        sa.CheckConstraint(
            f"entry_type IN ({_in_list(_ENTRY_TYPES)})", name="ck_profile_entry_type"
        ),
        sa.CheckConstraint(
            "source IN ('patient', 'clinician', 'inferred')",
            name="ck_profile_entry_source",
        ),
        sa.CheckConstraint(
            "state IN ('pending', 'confirmed', 'retired')",
            name="ck_profile_entry_state",
        ),
        sa.CheckConstraint(
            "state <> 'confirmed' OR confirmed_at IS NOT NULL",
            name="ck_profile_entry_confirmed_at",
        ),
        sa.CheckConstraint(
            "state <> 'retired' OR retired_at IS NOT NULL",
            name="ck_profile_entry_retired_at",
        ),
        sa.CheckConstraint(
            "source <> 'clinician' OR created_by LIKE 'reviewer:%'",
            name="ck_profile_entry_clinician_actor",
        ),
    )
    op.execute(
        "CREATE INDEX ix_profile_entry_live ON profile_entry (user_id) "
        "WHERE state <> 'retired'"
    )
    op.execute(
        "CREATE INDEX ix_profile_entry_review ON profile_entry (state, created_at) "
        "WHERE state = 'pending'"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_profile_entry_client_request "
        "ON profile_entry (user_id, client_request_id) "
        "WHERE client_request_id IS NOT NULL"
    )
    op.execute(_IMMUTABLE_FN.replace("{once_check}", _ONCE_CHECK))
    op.execute(
        "CREATE TRIGGER profile_entry_immutable BEFORE UPDATE ON profile_entry "
        "FOR EACH ROW EXECUTE FUNCTION profile_entry_immutable()"
    )

    op.create_table(
        "recommendation",
        _uuid_pk(),
        _user_fk(),
        sa.Column("conversation_id", sa.Text, nullable=True),
        sa.Column(
            "coaching_response_id",
            pg.UUID(as_uuid=False),
            sa.ForeignKey("coaching_response.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("recipe", pg.JSONB, nullable=False),
        sa.Column("check_snapshot", pg.JSONB, nullable=False),
        sa.Column("attempts", sa.SmallInteger, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("rejection_reason", sa.String(500), nullable=True),
        _now_col("created_at"),
        _now_col("status_at"),
        # Upper bound lives in tunables (safety.max_recipe_attempts) only.
        sa.CheckConstraint("attempts >= 1", name="ck_recommendation_attempts"),
        sa.CheckConstraint(
            "status IN ('shown', 'accepted', 'rejected')",
            name="ck_recommendation_status",
        ),
    )
    op.create_index(
        "ix_recommendation_user_created",
        "recommendation",
        ["user_id", sa.text("created_at DESC")],
    )

    op.create_table(
        "check_failure",
        _uuid_pk(),
        _user_fk(),
        sa.Column(
            "recommendation_id",
            pg.UUID(as_uuid=False),
            sa.ForeignKey("recommendation.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("attempt", sa.SmallInteger, nullable=False),
        sa.Column("recipe", pg.JSONB, nullable=False),
        sa.Column("failures", pg.JSONB, nullable=False),
        sa.Column("profile_version", sa.Text, nullable=False),
        sa.Column("outcome", sa.Text, nullable=False),
        _now_col("created_at"),
        sa.CheckConstraint(
            "outcome IN ('regenerated', 'dropped', 'reply_replaced')",
            name="ck_check_failure_outcome",
        ),
    )
    op.create_index("ix_check_failure_user_id", "check_failure", ["user_id"])

    op.create_table(
        "red_flag_escalation",
        _uuid_pk(),
        _user_fk(),
        sa.Column("conversation_id", sa.Text, nullable=True),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("rule_id", sa.Text, nullable=False),
        sa.Column("rule_label", sa.Text, nullable=False),
        sa.Column("rules_version", sa.Text, nullable=False),
        sa.Column("notify_status", sa.Text, nullable=False),
        sa.Column(
            "notify_attempts", sa.SmallInteger, nullable=False, server_default="0"
        ),
        _ts("notified_at"),
        _now_col("created_at"),
        sa.CheckConstraint(
            "notify_status IN ('pending', 'sent', 'failed', 'no_recipient')",
            name="ck_red_flag_escalation_notify_status",
        ),
    )
    op.create_index(
        "ix_red_flag_escalation_user_id", "red_flag_escalation", ["user_id"]
    )

    op.create_table(
        "review_item",
        _uuid_pk(),
        _user_fk(),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("subject_id", pg.UUID(as_uuid=False), nullable=False),
        sa.Column("detail", pg.JSONB, nullable=True),
        sa.Column("decision", sa.Text, nullable=True),
        sa.Column("decided_by", sa.Text, nullable=True),
        _ts("decided_at"),
        sa.Column("comment", sa.Text, nullable=True),
        _now_col("created_at"),
        sa.CheckConstraint(
            "kind IN ('pending_entry', 'rule_conflict', 'escalation', "
            "'plan_sample', 'unknown_medication')",
            name="ck_review_item_kind",
        ),
        sa.CheckConstraint(
            "decision IS NULL OR decision IN "
            "('approved', 'rejected', 'edited', 'handled')",
            name="ck_review_item_decision",
        ),
        sa.UniqueConstraint("kind", "subject_id", name="uq_review_item_subject"),
    )
    op.execute(
        "CREATE INDEX ix_review_item_open ON review_item (decision, created_at DESC) "
        "WHERE decision IS NULL"
    )
    op.create_index("ix_review_item_user_id", "review_item", ["user_id"])

    for table in _NEW_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS {table}_owner ON {table}")
        op.execute(
            f"CREATE POLICY {table}_owner ON {table} "
            "USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id)"
        )


def _load_allergen_groups() -> dict[str, dict[str, list[str]]]:
    with _ALLERGEN_FILE.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)["groups"]


def _contains(text: str, term: str) -> bool:
    return re.search(rf"\b{re.escape(term)}\b", text) is not None


def _allergen_group(fact: str, groups: dict[str, dict[str, list[str]]]) -> str | None:
    """Return the allergen group a restriction fact names, longest term first."""
    folded = fact.casefold()
    best: tuple[int, str] | None = None
    for key, group in groups.items():
        text = folded
        for excluded in group.get("exclude_terms", []):
            text = re.sub(rf"\b{re.escape(excluded.casefold())}\b", " ", text)
        for term in group["terms"]:
            if _contains(text, term.casefold()) and (
                best is None or len(term) > best[0]
            ):
                best = (len(term), key)
    return best[1] if best else None


def _insert_backfill(
    conn: sa.Connection,
    user_id: str,
    entry_type: str,
    value: dict[str, Any],
    label: str | None,
    at: datetime,
) -> bool:
    """Insert one confirmed backfill entry unless an equivalent one exists."""
    result = conn.execute(
        sa.text(
            "INSERT INTO profile_entry (user_id, entry_type, value, label, source, "
            "state, created_at, created_by, confirmed_at, confirmed_by) "
            "SELECT :user_id, :entry_type, CAST(:value AS jsonb), :label, 'patient', "
            "'confirmed', :at, 'backfill', :at, 'backfill' "
            "WHERE NOT EXISTS (SELECT 1 FROM profile_entry WHERE user_id = :user_id "
            "AND created_by = 'backfill' AND entry_type = :entry_type "
            "AND value = CAST(:value AS jsonb))"
        ),
        {
            "user_id": user_id,
            "entry_type": entry_type,
            "value": json.dumps(value),
            "label": label,
            "at": at,
        },
    )
    return result.rowcount == 1


def _backfill(conn: sa.Connection) -> None:
    """Copy declared conditions, diet chips and restrictions into profile_entry.

    Idempotent: an equivalent backfill entry is never inserted twice.
    """
    groups = _load_allergen_groups()
    counts = {"diagnosis": 0, "diet_setting": 0, "allergy": 0, "food_exclusion": 0}

    goals = conn.execute(
        sa.text("SELECT user_id, conditions, dietary_prefs, updated_at FROM user_goal")
    ).all()
    for user_id, conditions, prefs, updated_at in goals:
        user_id = str(user_id)
        for condition in conditions or []:
            if _insert_backfill(
                conn, user_id, "diagnosis", {"condition": condition}, None, updated_at
            ):
                counts["diagnosis"] += 1
        for key, on in (prefs or {}).items():
            if not on:
                continue
            key = _DIET_ALIASES.get(key, key)
            if key not in _DIET_CHIPS:
                logger.warning(
                    "019 backfill: user %s dietary_prefs key %r is not a diet chip; "
                    "left in place",
                    user_id,
                    key,
                )
            elif _insert_backfill(
                conn, user_id, "diet_setting", {"setting": key}, None, updated_at
            ):
                counts["diet_setting"] += 1

    restrictions = conn.execute(
        sa.text(
            "SELECT user_id, fact, updated_at FROM user_memory "
            "WHERE category = 'restriction' AND deleted_at IS NULL"
        )
    ).all()
    for user_id, fact, updated_at in restrictions:
        group = _allergen_group(fact, groups)
        if group is not None:
            inserted = _insert_backfill(
                conn,
                str(user_id),
                "allergy",
                {"allergen_group": group},
                None,
                updated_at,
            )
            kind = "allergy"
        else:
            inserted = _insert_backfill(
                conn,
                str(user_id),
                "food_exclusion",
                {"terms": [fact]},
                fact[:200],
                updated_at,
            )
            kind = "food_exclusion"
        counts[kind] += inserted
    logger.info("019 backfill inserted: %s", counts)


def upgrade() -> None:
    op.add_column(
        "user_memory",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    # Existing facts keep the date they were last written, not the deploy date.
    op.execute("UPDATE user_memory SET created_at = updated_at")
    op.drop_constraint("ck_user_memory_category", "user_memory", type_="check")
    op.create_check_constraint(
        "ck_user_memory_category",
        "user_memory",
        f"category IN ({_in_list(_NEW_CATEGORIES)})",
    )
    _create_tables()
    _backfill(op.get_bind())


def downgrade() -> None:
    for table in reversed(_NEW_TABLES):
        op.execute(f"DROP POLICY IF EXISTS {table}_owner ON {table}")
    op.drop_table("review_item")
    op.drop_table("red_flag_escalation")
    op.drop_table("check_failure")
    op.drop_table("recommendation")
    op.drop_table("profile_entry")
    op.execute("DROP FUNCTION IF EXISTS profile_entry_immutable()")

    op.drop_constraint("ck_user_memory_category", "user_memory", type_="check")
    # Rows of the removed kinds would violate the restored check.
    op.execute(
        "UPDATE user_memory SET category = 'preference' "
        "WHERE category IN ('cuisine', 'budget', 'cooking_time')"
    )
    op.create_check_constraint(
        "ck_user_memory_category",
        "user_memory",
        f"category IN ({_in_list(_OLD_CATEGORIES)})",
    )
    op.drop_column("user_memory", "created_at")
