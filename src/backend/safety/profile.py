"""The hard profile: typed, append-only facts that bind every coaching turn.

One row per version of a fact (``profile_entry``). Values are never rewritten:
an edit retires the old row and inserts a new one that ``replaces_id`` it, and
a database trigger enforces this. Only ``confirmed`` entries bind; ``pending``
ones are shown to the model as "awaiting confirmation" and never applied.

This module must not import ``backend.agent`` (tests/safety/test_boundaries.py).
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from collections.abc import Collection
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_tunables
from backend.db.models import ProfileEntry
from backend.db.session import get_session
from backend.safety.tables import ClinicalTables

logger = logging.getLogger(__name__)

EntryType = Literal[
    "allergy",
    "diagnosis",
    "medication",
    "physical_limitation",
    "nutrient_limit",
    "diet_setting",
    "food_exclusion",
]
EntrySource = Literal["patient", "clinician", "inferred"]
EntryState = Literal["pending", "confirmed", "retired"]

# Diet settings the clients show as chips (union of the web and Android lists).
DIET_CHIPS: frozenset[str] = frozenset(
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

# Spellings clients have sent for a chip. The web onboarding stores
# "pescetarian"; dropping it would silently lose a diet setting.
DIET_CHIP_ALIASES: dict[str, str] = {"pescetarian": "pescatarian"}


def normalize_diet_key(key: str) -> str:
    """Map a client's diet key to its chip name (unknown keys unchanged)."""
    return DIET_CHIP_ALIASES.get(key, key)


_TYPE_ORDER: tuple[str, ...] = (
    "allergy",
    "food_exclusion",
    "diet_setting",
    "diagnosis",
    "medication",
    "physical_limitation",
    "nutrient_limit",
)
_MAX_LABEL_CHARS = 200


class ProfileError(Exception):
    """Base class for hard-profile domain errors."""


class EntryNotFound(ProfileError):
    """No such entry for this user."""


class StateConflict(ProfileError):
    """The entry is in a state the requested action cannot reach."""


class ProfileFull(ProfileError):
    """The user already holds ``safety.hard_profile_max_entries`` live entries."""


class ProfileTooLarge(ProfileError):
    """More confirmed entries than the cap: the block must not be truncated."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AllergyValue(_Strict):
    """An allergy to a table group or to custom terms."""

    allergen_group: str | None = None
    custom_terms: list[str] | None = Field(default=None, min_length=1, max_length=10)
    severity: str | None = Field(default=None, max_length=50)

    @model_validator(mode="after")
    def _one_of_group_or_terms(self) -> AllergyValue:
        if (self.allergen_group is None) == (self.custom_terms is None):
            raise ValueError("give exactly one of allergen_group or custom_terms")
        return self


class DiagnosisValue(_Strict):
    """A condition key from condition_limits.yaml, or free text."""

    condition: str = Field(min_length=1, max_length=100)


class MedicationValue(_Strict):
    """A medication as stated, and the interactions-table key when it matched."""

    name: str = Field(min_length=1, max_length=100)
    matched_drug: str | None = None


class PhysicalLimitationValue(_Strict):
    """A chewing, swallowing, grip or standing-time limitation."""

    kind: Literal["chewing", "swallowing", "grip", "standing_time"]
    max_texture: str | None = None
    max_active_minutes: int | None = Field(default=None, gt=0)


class NutrientLimitValue(_Strict):
    """A ceiling (``amount``) with an optional display-only low end."""

    nutrient: Literal[
        "sodium", "potassium", "phosphorus", "protein", "fluid", "carbohydrate"
    ]
    amount: float = Field(gt=0)
    min_amount: float | None = Field(default=None, ge=0)
    unit: Literal["mg", "g", "ml"]
    period: Literal["per_meal", "per_day"]

    @model_validator(mode="after")
    def _range_is_ordered(self) -> NutrientLimitValue:
        if self.min_amount is not None and self.min_amount >= self.amount:
            raise ValueError("min_amount must be below amount")
        return self


class DietSettingValue(_Strict):
    """One of the diet chips."""

    setting: str

    @model_validator(mode="after")
    def _known_chip(self) -> DietSettingValue:
        if self.setting not in DIET_CHIPS:
            raise ValueError(f"unknown diet setting {self.setting!r}")
        return self


class FoodExclusionValue(_Strict):
    """Foods or phrases the patient never eats."""

    terms: list[str] = Field(min_length=1, max_length=10)


EntryValue = (
    AllergyValue
    | DiagnosisValue
    | MedicationValue
    | PhysicalLimitationValue
    | NutrientLimitValue
    | DietSettingValue
    | FoodExclusionValue
)

_VALUE_MODELS: dict[str, type[BaseModel]] = {
    "allergy": AllergyValue,
    "diagnosis": DiagnosisValue,
    "medication": MedicationValue,
    "physical_limitation": PhysicalLimitationValue,
    "nutrient_limit": NutrientLimitValue,
    "diet_setting": DietSettingValue,
    "food_exclusion": FoodExclusionValue,
}
_TYPE_OF: dict[type[BaseModel], str] = {m: t for t, m in _VALUE_MODELS.items()}


def parse_value(entry_type: str, raw: dict) -> EntryValue:
    """Validate a raw value against the model for its type.

    Args:
        entry_type: One of the seven entry types.
        raw: The value dict (API body or database JSONB).

    Returns:
        The typed value.

    Raises:
        ValueError: On an unknown type or an invalid value.
    """
    model = _VALUE_MODELS.get(entry_type)
    if model is None:
        raise ValueError(f"unknown entry type {entry_type!r}")
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc


class HardEntry(BaseModel):
    """One hard-profile entry as read from the database."""

    id: str
    type: EntryType
    value: EntryValue
    stored_label: str | None = None
    source: EntrySource
    state: EntryState
    created_at: datetime
    created_by: str
    confirmed_at: datetime | None = None
    confirmed_by: str | None = None
    retire_requested_at: datetime | None = None
    retired_at: datetime | None = None
    retired_by: str | None = None
    retired_reason: str | None = None
    replaces_id: str | None = None
    acknowledged_at: datetime | None = None

    model_config = ConfigDict(extra="forbid")


def _to_entry(row: ProfileEntry) -> HardEntry:
    return HardEntry(
        id=row.id,
        type=row.entry_type,
        value=parse_value(row.entry_type, row.value),
        stored_label=row.label,
        source=row.source,
        state=row.state,
        created_at=row.created_at,
        created_by=row.created_by,
        confirmed_at=row.confirmed_at,
        confirmed_by=row.confirmed_by,
        retire_requested_at=row.retire_requested_at,
        retired_at=row.retired_at,
        retired_by=row.retired_by,
        retired_reason=row.retired_reason,
        replaces_id=row.replaces_id,
        acknowledged_at=row.acknowledged_at,
    )


def _sort_key(entry: HardEntry) -> tuple[int, datetime]:
    return _TYPE_ORDER.index(entry.type), entry.confirmed_at or entry.created_at


def confirmed(entries: list[HardEntry]) -> list[HardEntry]:
    """The entries that bind, in type order then confirmation time."""
    return sorted((e for e in entries if e.state == "confirmed"), key=_sort_key)


def version_of(entries: list[HardEntry]) -> str:
    """SHA-256 over the sorted ``id:confirmed_at`` of the confirmed entries."""
    parts = sorted(
        f"{e.id}:{e.confirmed_at.isoformat() if e.confirmed_at else ''}"
        for e in entries
        if e.state == "confirmed"
    )
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


def _num(value: float) -> str:
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def limit_text(value: NutrientLimitValue) -> str:
    """The limit as shown to the patient, e.g. ``up to 1,500 mg a day``."""
    period = "a day" if value.period == "per_day" else "a meal"
    if value.min_amount is not None:
        return f"{_num(value.min_amount)}-{_num(value.amount)} {value.unit} {period}"
    return f"up to {_num(value.amount)} {value.unit} {period}"


_PHYSICAL_LABELS = {
    "chewing": "Difficulty chewing",
    "swallowing": "Difficulty swallowing",
    "grip": "Limited grip strength",
    "standing_time": "Limited standing time",
}


def _condition_text(value: DiagnosisValue, tables: ClinicalTables) -> str:
    known = tables.condition_limits.conditions.get(value.condition)
    return known.label if known else value.condition


def label_for(entry: HardEntry, tables: ClinicalTables) -> str:
    """The patient-facing label: stored for free text, derived otherwise.

    Args:
        entry: The entry.
        tables: Clinical tables (allergen and condition labels).

    Returns:
        A short label such as ``Peanut allergy`` or ``Sodium: up to 1,500 mg
        a day``.
    """
    if entry.stored_label:
        return entry.stored_label
    value = entry.value
    if isinstance(value, AllergyValue):
        if value.allergen_group is None:
            return "Allergy: " + ", ".join(value.custom_terms or [])
        group = tables.allergen_groups.groups.get(value.allergen_group)
        name = group.label if group else value.allergen_group
        return f"{name[:1].upper()}{name[1:]} allergy"
    if isinstance(value, DiagnosisValue):
        name = _condition_text(value, tables)
        return f"{name[:1].upper()}{name[1:]}"
    if isinstance(value, MedicationValue):
        return value.name
    if isinstance(value, PhysicalLimitationValue):
        label = _PHYSICAL_LABELS[value.kind]
        if value.max_texture:
            return f"{label}: up to {value.max_texture.replace('_', ' ')} textures"
        if value.max_active_minutes:
            return f"{label}: up to {value.max_active_minutes} minutes on your feet"
        return label
    if isinstance(value, NutrientLimitValue):
        return f"{value.nutrient.capitalize()}: {limit_text(value)}"
    if isinstance(value, DietSettingValue):
        return value.setting.replace("_", " ").capitalize()
    return "No " + ", ".join(value.terms)


def missing_values(entries: list[HardEntry], tables: ClinicalTables) -> list[str]:
    """Limits a declared condition expects that the patient has not set."""
    set_limits = {
        e.value.nutrient
        for e in confirmed(entries)
        if isinstance(e.value, NutrientLimitValue)
    }
    missing: list[str] = []
    for entry in confirmed(entries):
        value = entry.value
        known = (
            tables.condition_limits.conditions.get(value.condition)
            if isinstance(value, DiagnosisValue)
            else None
        )
        missing += [
            f"{nutrient} limit for {known.label}"
            for nutrient in (known.expects_limits if known else [])
            if nutrient not in set_limits
        ]
    return missing


def active_diet_settings(entries: list[HardEntry]) -> list[str]:
    """Confirmed diet settings, sorted."""
    return sorted(
        e.value.setting
        for e in confirmed(entries)
        if isinstance(e.value, DietSettingValue)
    )


def declared_conditions(entries: list[HardEntry]) -> list[str]:
    """Confirmed diagnoses (condition keys or free text), oldest first."""
    return [e.value.condition for e in confirmed(entries) if e.type == "diagnosis"]


def render_block(entries: list[HardEntry], tables: ClinicalTables) -> str:
    """Render the hard profile for the coaching prompt.

    Every confirmed entry is listed in full; pending ones are listed apart as
    not to be applied. Nothing is ever dropped to fit.

    Args:
        entries: Live entries (pending and confirmed).
        tables: Clinical tables for derived labels.

    Returns:
        The block, or "" when the profile is empty.

    Raises:
        ProfileTooLarge: If there are more confirmed entries than
            ``safety.hard_profile_max_entries``.
    """
    binding = confirmed(entries)
    if len(binding) > get_tunables().safety.hard_profile_max_entries:
        raise ProfileTooLarge(f"{len(binding)} confirmed entries")

    def labels(kind: str) -> list[str]:
        return [label_for(e, tables) for e in binding if e.type == kind]

    lines: list[str] = []
    if allergies := labels("allergy"):
        lines.append(
            "- Allergies (never serve, including derived ingredients): "
            + "; ".join(allergies)
        )
    if exclusions := labels("food_exclusion"):
        lines.append("- Never suggest (hard restrictions): " + "; ".join(exclusions))
    if settings := active_diet_settings(binding):
        lines.append(
            "- Diet settings (binding): "
            + ", ".join(s.replace("_", " ") for s in settings)
        )
    if conditions := [
        _condition_text(e.value, tables) for e in binding if e.type == "diagnosis"
    ]:
        lines.append("- Declared health conditions: " + ", ".join(conditions) + ".")
    for heading, kind in (
        ("Medications", "medication"),
        ("Physical limitations", "physical_limitation"),
        ("Nutrient limits", "nutrient_limit"),
    ):
        if found := labels(kind):
            lines.append(f"- {heading}: " + "; ".join(found))
    pending = sorted(
        (e for e in entries if e.state == "pending"), key=lambda e: e.created_at
    )
    if pending:
        lines.append(
            "- Awaiting confirmation, do not apply until the patient confirms: "
            + "; ".join(label_for(e, tables) for e in pending)
        )
    if not lines:
        return ""
    return "\n".join(["Patient safety profile (binding on every suggestion):", *lines])


def _keep_label(value: EntryValue, label: str | None) -> str | None:
    """Labels are stored only where the value cannot derive its own."""
    free_text = isinstance(value, FoodExclusionValue) or (
        isinstance(value, AllergyValue) and value.custom_terms is not None
    )
    if not (label and free_text):
        return None
    return label.strip()[:_MAX_LABEL_CHARS] or None


async def _lock(session: AsyncSession, user_id: str) -> None:
    """Serialise writers of one user's profile (cap and idempotency checks)."""
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"profile_entry:{user_id}"},
    )


async def _live_rows(session: AsyncSession, user_id: str) -> list[ProfileEntry]:
    result = await session.execute(
        select(ProfileEntry).where(
            ProfileEntry.user_id == user_id, ProfileEntry.state != "retired"
        )
    )
    return list(result.scalars().all())


async def _ensure_room(session: AsyncSession, user_id: str) -> None:
    cap = get_tunables().safety.hard_profile_max_entries
    if len(await _live_rows(session, user_id)) >= cap:
        raise ProfileFull(f"{cap} live entries")


async def _existing_request(
    session: AsyncSession, user_id: str, client_request_id: str | None
) -> ProfileEntry | None:
    if client_request_id is None:
        return None
    result = await session.execute(
        select(ProfileEntry).where(
            ProfileEntry.user_id == user_id,
            ProfileEntry.client_request_id == client_request_id,
        )
    )
    return result.scalars().first()


async def _get_row(session: AsyncSession, user_id: str, entry_id: str) -> ProfileEntry:
    try:
        uuid.UUID(entry_id)
    except ValueError as exc:
        raise EntryNotFound(entry_id) from exc
    row = (
        await session.execute(
            select(ProfileEntry)
            .where(ProfileEntry.id == entry_id, ProfileEntry.user_id == user_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise EntryNotFound(entry_id)
    return row


def _new_row(
    user_id: str,
    value: EntryValue,
    *,
    label: str | None,
    source: str,
    state: str,
    created_by: str,
    client_request_id: str | None,
    replaces_id: str | None = None,
) -> ProfileEntry:
    now = datetime.now(UTC)
    return ProfileEntry(
        id=str(uuid.uuid4()),
        user_id=user_id,
        entry_type=_TYPE_OF[type(value)],
        value=value.model_dump(exclude_none=True),
        label=_keep_label(value, label),
        source=source,
        state=state,
        created_at=now,
        created_by=created_by,
        confirmed_at=now if state == "confirmed" else None,
        confirmed_by=created_by if state == "confirmed" else None,
        client_request_id=client_request_id,
        replaces_id=replaces_id,
    )


def _retire_row(row: ProfileEntry, by: str, reason: str) -> None:
    row.state = "retired"
    row.retired_at = datetime.now(UTC)
    row.retired_by = by
    row.retired_reason = reason


async def load_hard_profile(user_id: str) -> list[HardEntry]:
    """Read the live entries (pending and confirmed): one indexed query.

    Args:
        user_id: Supabase Auth UUID.

    Returns:
        Live entries in type order, then confirmation time.

    Raises:
        Exception: Any database or validation failure propagates. Callers
            that bind a reply to the profile must treat it as "cannot answer".
    """
    async with get_session()() as session:
        rows = await _live_rows(session, user_id)
    return sorted((_to_entry(r) for r in rows), key=_sort_key)


async def load_history(user_id: str) -> list[HardEntry]:
    """Every entry including retired ones, newest first."""
    async with get_session()() as session:
        result = await session.execute(
            select(ProfileEntry)
            .where(ProfileEntry.user_id == user_id)
            .order_by(ProfileEntry.created_at.desc())
        )
    return [_to_entry(r) for r in result.scalars().all()]


async def get_entry(user_id: str, entry_id: str) -> HardEntry:
    """One entry of this user in any state.

    Raises:
        EntryNotFound: Unknown id, or one that belongs to another user.
    """
    async with get_session()() as session:
        return _to_entry(await _get_row(session, user_id, entry_id))


async def add_entry(
    user_id: str,
    value: EntryValue,
    *,
    source: EntrySource,
    state: Literal["pending", "confirmed"],
    created_by: str,
    label: str | None = None,
    client_request_id: str | None = None,
) -> HardEntry:
    """Insert a new entry; a repeated ``client_request_id`` returns the first.

    Args:
        user_id: Supabase Auth UUID.
        value: The typed value; its class decides the entry type.
        source: Who the fact came from.
        state: ``confirmed`` when the patient entered it themselves,
            otherwise ``pending``.
        created_by: ``patient``, ``curator``, ``backfill`` or ``reviewer:<id>``.
        label: Free-text label; kept only for food exclusions and custom
            allergies.
        client_request_id: Idempotency key for app writes.

    Returns:
        The stored entry.

    Raises:
        ProfileFull: If the user already holds the maximum live entries.
    """
    async with get_session()() as session, session.begin():
        await _lock(session, user_id)
        existing = await _existing_request(session, user_id, client_request_id)
        if existing is not None:
            return _to_entry(existing)
        await _ensure_room(session, user_id)
        row = _new_row(
            user_id,
            value,
            label=label,
            source=source,
            state=state,
            created_by=created_by,
            client_request_id=client_request_id,
        )
        session.add(row)
        await session.flush()
        return _to_entry(row)


async def confirm(user_id: str, entry_id: str, *, by: str = "patient") -> HardEntry:
    """Pending to confirmed; on an inferred confirmed entry, acknowledge it.

    Raises:
        EntryNotFound: Unknown entry.
        StateConflict: The entry is retired.
    """
    async with get_session()() as session, session.begin():
        await _lock(session, user_id)
        row = await _get_row(session, user_id, entry_id)
        if row.state == "pending":
            row.state = "confirmed"
            row.confirmed_at = datetime.now(UTC)
            row.confirmed_by = by
        elif row.state == "retired":
            raise StateConflict("a retired entry cannot be confirmed")
        elif row.source == "inferred" and row.acknowledged_at is None:
            row.acknowledged_at = datetime.now(UTC)
        return _to_entry(row)


async def deny(user_id: str, entry_id: str, *, by: str = "patient") -> HardEntry:
    """Pending to retired (``denied``). Repeating it returns the entry.

    Raises:
        EntryNotFound: Unknown entry.
        StateConflict: The entry is confirmed, or retired for another reason.
    """
    async with get_session()() as session, session.begin():
        await _lock(session, user_id)
        row = await _get_row(session, user_id, entry_id)
        if row.state == "pending":
            _retire_row(row, by, "denied")
        elif not (row.state == "retired" and row.retired_reason == "denied"):
            raise StateConflict("only a pending entry can be denied")
        return _to_entry(row)


async def retire(
    user_id: str, entry_id: str, *, by: str = "patient", reason: str = "retired"
) -> HardEntry:
    """Confirmed to retired. Retiring a retired entry returns it unchanged.

    Raises:
        EntryNotFound: Unknown entry.
        StateConflict: The entry is still pending (deny it instead).
    """
    async with get_session()() as session, session.begin():
        await _lock(session, user_id)
        row = await _get_row(session, user_id, entry_id)
        if row.state == "pending":
            raise StateConflict("a pending entry is denied, not retired")
        if row.state == "confirmed":
            _retire_row(row, by, reason)
        return _to_entry(row)


async def request_retirement(user_id: str, entry_id: str) -> HardEntry:
    """Mark a confirmed entry as awaiting the patient's confirmation to retire.

    It keeps binding until the patient confirms through :func:`retire`.

    Raises:
        EntryNotFound: Unknown entry.
        StateConflict: The entry is not confirmed.
    """
    async with get_session()() as session, session.begin():
        await _lock(session, user_id)
        row = await _get_row(session, user_id, entry_id)
        if row.state != "confirmed":
            raise StateConflict("only a confirmed entry can be retired")
        if row.retire_requested_at is None:
            row.retire_requested_at = datetime.now(UTC)
        return _to_entry(row)


async def replace(
    user_id: str,
    entry_id: str,
    value: EntryValue,
    *,
    created_by: str = "patient",
    label: str | None = None,
    client_request_id: str | None = None,
) -> HardEntry:
    """Edit = retire the old entry (``replaced``) and insert a confirmed new one.

    One transaction. A repeated ``client_request_id`` returns the first result.

    Raises:
        EntryNotFound: Unknown entry.
        StateConflict: The old entry is not confirmed, or the new value has a
            different type.
    """
    async with get_session()() as session, session.begin():
        await _lock(session, user_id)
        existing = await _existing_request(session, user_id, client_request_id)
        if existing is not None:
            return _to_entry(existing)
        old = await _get_row(session, user_id, entry_id)
        if old.state != "confirmed" or old.entry_type != _TYPE_OF[type(value)]:
            raise StateConflict("only a confirmed entry can be replaced by its type")
        _retire_row(old, created_by, "replaced")
        await session.flush()
        row = _new_row(
            user_id,
            value,
            label=label,
            source="patient",
            state="confirmed",
            created_by=created_by,
            client_request_id=client_request_id,
            replaces_id=old.id,
        )
        session.add(row)
        await session.flush()
        return _to_entry(row)


async def set_declarations(
    user_id: str,
    *,
    conditions: list[str] | None,
    managed_conditions: Collection[str],
    diet_settings: Collection[str],
) -> None:
    """Make the Settings choices match the profile, in one transaction.

    The Settings screens enter facts directly, which counts as the patient's
    confirmation: new choices become confirmed entries (a pending one is
    confirmed), dropped ones are retired (a pending one is denied). Diagnoses
    outside ``managed_conditions`` are left alone.

    Args:
        user_id: Supabase Auth UUID.
        conditions: Wanted condition keys; None leaves conditions unchanged.
        managed_conditions: The condition keys Settings can set.
        diet_settings: Wanted diet chips (all chips are managed).

    Raises:
        ProfileFull: If adding would pass the entry cap.
    """
    wanted: dict[str, list[str]] = {"diet_setting": list(dict.fromkeys(diet_settings))}
    if conditions is not None:
        wanted["diagnosis"] = [
            c for c in dict.fromkeys(conditions) if c in managed_conditions
        ]
    async with get_session()() as session, session.begin():
        await _lock(session, user_id)
        live = await _live_rows(session, user_id)
        for entry_type, keys in wanted.items():
            field = "setting" if entry_type == "diet_setting" else "condition"
            present: set[str] = set()
            for row in (r for r in live if r.entry_type == entry_type):
                key = row.value[field]
                managed = entry_type == "diet_setting" or key in managed_conditions
                if not managed:
                    continue
                if key in keys:
                    present.add(key)
                    if row.state == "pending":
                        row.state = "confirmed"
                        row.confirmed_at = datetime.now(UTC)
                        row.confirmed_by = "patient"
                else:
                    _retire_row(row, "patient", "removed_in_settings")
            for key in (k for k in keys if k not in present):
                await _ensure_room(session, user_id)
                session.add(
                    _new_row(
                        user_id,
                        parse_value(entry_type, {field: key}),
                        label=None,
                        source="patient",
                        state="confirmed",
                        created_by="patient",
                        client_request_id=None,
                    )
                )
                await session.flush()
