from __future__ import annotations

from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class UserGoal(Base):
    """Nutrition goals and dietary preferences per user.

    Written by the onboarding API. Read by build_context() on every turn.
    One row per user — user_id is the PK (sourced from Supabase Auth UUID).
    """

    __tablename__ = "user_goal"

    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    tracking_mode: Mapped[str] = mapped_column(
        Text, nullable=False, default="goals", server_default="goals"
    )
    kcal_goal: Mapped[float | None] = mapped_column(Float, nullable=True)
    protein_goal: Mapped[float | None] = mapped_column(Float, nullable=True)
    fiber_goal: Mapped[float | None] = mapped_column(Float, nullable=True)
    dietary_prefs: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # Typical first-meal time ("HH:MM", 24h) captured during onboarding as a
    # behavioral implementation intention. Drives future reminder scheduling.
    first_meal_time: Mapped[str | None] = mapped_column(Text, nullable=True)
    streak_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    llm_requests_used: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    llm_quota: Mapped[int] = mapped_column(
        Integer, nullable=False, default=50, server_default="50"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class PushSubscription(Base):
    """A browser Web Push subscription for a user.

    Written by POST /push/subscribe during onboarding (or later). The recurring
    sender that delivers reminders to these endpoints is out of scope here.
    One user may have multiple subscriptions (one per browser/device); endpoint
    is unique so re-subscribing the same browser upserts rather than duplicates.
    """

    __tablename__ = "push_subscription"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), nullable=False, index=True
    )
    endpoint: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    p256dh: Mapped[str] = mapped_column(Text, nullable=False)
    auth: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class MealLog(Base):
    """Every logged meal with full nutrient breakdown and pgvector embedding.

    Written by the log_meal tool. Embedding column populated async by Celery.
    Source of truth for today's totals: get_today_totals sums the rows in the
    current nutrition-day window (Redis holds a write-through cache copy).
    """

    __tablename__ = "meal_log"

    meal_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("user_goal.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    logged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    meal_type: Mapped[str] = mapped_column(String(20), nullable=False)
    kcal: Mapped[float] = mapped_column(Float, nullable=False)
    protein_g: Mapped[float] = mapped_column(Float, nullable=False)
    carbs_g: Mapped[float] = mapped_column(Float, nullable=False)
    fat_g: Mapped[float] = mapped_column(Float, nullable=False)
    fiber_g: Mapped[float] = mapped_column(Float, nullable=False)
    entities: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    label: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding: Mapped[list | None] = mapped_column(Vector(768), nullable=True)
    flags: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        # PRD-specified B-tree indexes
        Index("ix_meal_log_user_logged_at", "user_id", "logged_at"),
        Index("ix_meal_log_user_protein", "user_id", "protein_g"),
        Index("ix_meal_log_hybrid", "user_id", "meal_type", "protein_g", "logged_at"),
        # Keyset pagination cursor for the integration API
        Index("ix_meal_log_cursor", "user_id", "updated_at", "meal_id"),
        Index("ix_meal_log_user_label", "user_id", "label"),
        # IVFFlat index created via raw DDL in the Alembic migration
        # because SQLAlchemy Index() does not support operator classes.
    )


class UserMemory(Base):
    """Extracted preference facts for a user, embedded for ANN retrieval.

    Written by Celery extract_and_store_facts. Read by build_context() via
    pgvector ANN search to retrieve the top-3 most relevant preferences.
    """

    __tablename__ = "user_memory"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("user_goal.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    fact: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list | None] = mapped_column(Vector(768), nullable=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (Index("ix_user_memory_user_id", "user_id"),)


class UserMeal(Base):
    """A user's saved composite meal ("My Meals").

    Written by POST /my-meals from a confirmed, decomposed meal. `ingredients`
    uses the same JSONB shape as `meal_log.entities`, so logging from a saved
    meal reuses the whole downstream path. Macro totals are denormalized for
    quick listing; `embedding` powers later semantic match (V2).
    """

    __tablename__ = "user_meal"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("user_goal.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    name_normalized: Mapped[str] = mapped_column(Text, nullable=False)
    ingredients: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    kcal: Mapped[float] = mapped_column(Float, nullable=False)
    protein_g: Mapped[float] = mapped_column(Float, nullable=False)
    carbs_g: Mapped[float] = mapped_column(Float, nullable=False)
    fat_g: Mapped[float] = mapped_column(Float, nullable=False)
    fiber_g: Mapped[float] = mapped_column(Float, nullable=False)
    embedding: Mapped[list | None] = mapped_column(Vector(768), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index(
            "ix_user_meal_user_normalized",
            "user_id",
            "name_normalized",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


class FoodSource(Base):
    """USDA FoodData Central cache.

    Cache-first: usda_lookup_batch checks here before hitting the FDC API.
    Written on cache miss. fdc_id is the USDA FoodData Central identifier.
    """

    __tablename__ = "food_source"

    fdc_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    food_name: Mapped[str] = mapped_column(String(255), nullable=False)
    nutrients: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    nutrients_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    data_quality: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source_db: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="FDC"
    )
    cached_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_food_source_food_name", "food_name"),)


class DailySummary(Base):
    """Pre-aggregated daily nutrition totals.

    Written by the Celery aggregate_daily_summary task at 00:05 daily.
    Used as a Redis fallback and as input to weekly_summary aggregation.
    Never computed from meal_log at request time.
    """

    __tablename__ = "daily_summary"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("user_goal.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    kcal: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    protein_g: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    fiber_g: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    protein_goal_hit: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    has_veg_day: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("user_id", "date", name="uq_daily_summary_user_date"),
        Index("ix_daily_summary_user_date", "user_id", "date"),
        Index("ix_daily_summary_cursor", "user_id", "updated_at", "id"),
    )


class WeeklySummary(Base):
    """Pre-aggregated weekly patterns and adherence stats.

    Written by Celery build_weekly_summary on Sunday 23:00.
    Read by build_context() to populate the weekly pattern block (~120 tokens).
    """

    __tablename__ = "weekly_summary"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("user_goal.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    avg_protein_g: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    days_hit_protein: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    weak_spots: Mapped[list] = mapped_column(
        ARRAY(String), nullable=False, default=list
    )
    missed_meals: Mapped[list] = mapped_column(
        ARRAY(String), nullable=False, default=list
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("user_id", "week_start", name="uq_weekly_summary_user_week"),
        Index("ix_weekly_summary_user_week", "user_id", "week_start"),
        Index("ix_weekly_summary_cursor", "user_id", "updated_at", "id"),
    )


class NutrientCheckup(Base):
    """Pre-aggregated rolling 7-day nutrient averages + trend vs prior week.

    Written nightly by the Celery build_nutrient_checkup task. Read by
    GET /nutrient-checkup for the dashboard card. Never computed from
    meal_log at request time.
    """

    __tablename__ = "nutrient_checkup"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("user_goal.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    nutrients: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    notable_nutrients: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list
    )
    summary_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    telegram_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    chat_nudge_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("user_id", "date", name="uq_nutrient_checkup_user_date"),
        Index("ix_nutrient_checkup_user_date", "user_id", "date"),
    )


class TelegramLink(Base):
    """Binds a Telegram chat to a NutriChat user.

    Written by the bot process after a `/link <code>` command validates a
    short-lived Redis code. RLS is enabled with no policies — service-role
    only (matches the integration_token posture).
    """

    __tablename__ = "telegram_link"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("user_goal.user_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class IntegrationToken(Base):
    """Service token for read-only third-party access to nutrition data.

    Minted via `python -m backend.scripts.mint_token`. Tokens are stored as
    a SHA-256 hash; the plaintext `nck_<token>` value is shown only once at
    mint time. RLS is enabled with no policies — service-role only.
    """

    __tablename__ = "integration_token"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("user_goal.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    scopes: Mapped[list] = mapped_column(
        ARRAY(String), nullable=False, default=lambda: ["nutrition:read"]
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_integration_token_token_hash", "token_hash"),
    )
