"""Check a meal about to be logged against the patient's confirmed profile.

The meal-logging card (and every other way a meal is saved) runs this before
saving. Unlike a suggested recipe, a logged meal is usually already eaten, so
nothing is refused outright: an allergy or a medication-food interaction
needs the patient to tap "Log anyway" (``needs_ack``), and every other hit is
a reminder shown on the card. Decided with the owner on 2026-11-13.

The word lists and limit maths are the recipe checker's (``matching``,
``limits``), so a food the coach would never suggest is also the food the
card warns about. Sentences come from ``safety.meal_warnings`` templates.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from backend.config import get_tunables
from backend.safety.limits import LimitProgress, intake_today, item_amount
from backend.safety.matching import medication_drug, term_rules
from backend.safety.profile import (
    HardEntry,
    MedicationValue,
    NutrientLimitValue,
    confirmed,
    load_hard_profile,
)
from backend.safety.tables import ClinicalTables, load_tables

logger = logging.getLogger(__name__)

_TUNABLES = get_tunables()

Severity = Literal["confirm", "note"]

# Rules a patient must acknowledge before the meal is saved.
_CONFIRM_RULES = frozenset({"allergen", "interaction", "unavailable"})


class MealWarning(BaseModel):
    """One reminder for the card; ``confirm`` ones need "Log anyway"."""

    rule: str
    severity: Severity
    entry_id: str | None
    text: str

    model_config = ConfigDict(extra="forbid")


class MealCheck(BaseModel):
    """The card's ``safety`` field: its reminders and whether to ask first."""

    warnings: list[MealWarning]
    needs_ack: bool

    model_config = ConfigDict(extra="forbid")

    @property
    def text(self) -> str:
        """The reminders as chat text, or empty when there are none."""
        if not self.warnings:
            return ""
        lines = [f"- {w.text}" for w in self.warnings]
        return "\n".join([_TUNABLES.safety.meal_warnings.intro, *lines])


def _num(value: float) -> str:
    return f"{value:,.1f}".rstrip("0").rstrip(".")


def _warning(
    rule: str, entry_id: str | None, template: str, **fields: str
) -> MealWarning:
    severity: Severity = "confirm" if rule in _CONFIRM_RULES else "note"
    return MealWarning(
        rule=rule,
        severity=severity,
        entry_id=entry_id,
        text=template.format(**fields),
    )


def _food(item: Mapping) -> str:
    """What the patient called the food, falling back to the matched name."""
    return str(item.get("input_phrase") or item.get("food_name") or "This food")


def _term_warnings(
    items: Sequence[Mapping], entries: list[HardEntry], tables: ClinicalTables
) -> list[MealWarning]:
    texts = _TUNABLES.safety.meal_warnings
    found: list[MealWarning] = []
    for rule in term_rules(entries, tables):
        for item in items:
            names = (item.get("input_phrase"), item.get("food_name"))
            if not any(rule.hit(str(n)) for n in names if n):
                continue
            found.append(
                _warning(
                    rule.rule,
                    rule.entry_id,
                    getattr(texts, rule.rule),
                    food=_food(item).capitalize(),
                    name=rule.name,
                    reason=rule.reason,
                )
            )
    return found


def _sum(items: Sequence[Mapping], nutrient: str, unit: str) -> tuple[float, list[str]]:
    """The meal's total and the foods whose amount is unknown."""
    total, unknown = 0.0, []
    for item in items:
        amount = item_amount(dict(item), nutrient, unit)
        if amount is None:
            unknown.append(_food(item))
        else:
            total += amount
    return total, unknown


def _over(
    items: Sequence[Mapping],
    entry_id: str,
    rule: Literal["nutrient_limit", "interaction_ceiling"],
    ceiling: tuple[str, float, str],
    *,
    already: float = 0.0,
    name: str = "",
    reason: str = "",
) -> list[MealWarning]:
    """Warnings for one ceiling: over it, and (for limits) foods not counted.

    A meal that adds none of the nutrient never warns, even when the day is
    already over: the reminder belongs to the meal that crossed the line.
    """
    texts = _TUNABLES.safety.meal_warnings
    nutrient, limit, unit = ceiling
    total, unknown = _sum(items, nutrient, unit)
    label = nutrient.replace("_", " ")
    found: list[MealWarning] = []
    # Unknown values are named for the patient's own limits only: most foods
    # lack a vitamin K value, and a note on every meal would hide real ones.
    if unknown and rule == "nutrient_limit":
        found.append(
            _warning(
                "unknown",
                entry_id,
                texts.unknown,
                nutrient=label,
                foods=", ".join(unknown),
            )
        )
    if total > 0 and total + already > limit:
        found.append(
            _warning(
                rule,
                entry_id,
                getattr(texts, rule),
                nutrient=label,
                total=_num(total + already),
                limit=_num(limit),
                unit=unit,
                name=name,
                reason=reason,
            )
        )
    return found


def _limit_warnings(
    items: Sequence[Mapping],
    entries: list[HardEntry],
    today: Mapping[str, LimitProgress],
    tables: ClinicalTables,
) -> list[MealWarning]:
    found: list[MealWarning] = []
    for entry in entries:
        value = entry.value
        if isinstance(value, NutrientLimitValue):
            progress = today.get(entry.id)
            per_day = value.period == "per_day" and progress is not None
            found += _over(
                items,
                entry.id,
                "nutrient_limit",
                (value.nutrient, value.amount, value.unit),
                already=progress.so_far if per_day and progress else 0.0,
            )
        elif isinstance(value, MedicationValue):
            drug = medication_drug(entry, tables)
            for rule in tables.drug_food_interactions.drugs[drug].rules if drug else []:
                if rule.kind == "nutrient_ceiling":
                    found += _over(
                        items,
                        entry.id,
                        "interaction_ceiling",
                        (rule.nutrient, rule.amount, rule.unit),
                        name=value.name,
                        reason=rule.reason,
                    )
    return found


def check_meal(
    items: Sequence[Mapping],
    entries: list[HardEntry],
    today: Mapping[str, LimitProgress],
    tables: ClinicalTables,
) -> MealCheck:
    """Check a meal's items against the confirmed profile. No I/O.

    Args:
        items: The items about to be logged (``USDAResult`` dumps).
        entries: The patient's live hard entries; pending ones never bind.
        today: Progress per limit entry id, from ``limits.intake_today``.
        tables: Clinical tables.

    Returns:
        One warning per rule and food, allergies and interactions first.

    Raises:
        TablesUnavailable: A confirmed entry names a group the tables lack.
    """
    binding = confirmed(entries)
    warnings = [
        *_term_warnings(items, binding, tables),
        *_limit_warnings(items, binding, today, tables),
    ]
    warnings.sort(key=lambda w: w.severity != "confirm")
    return MealCheck(
        warnings=warnings, needs_ack=any(w.severity == "confirm" for w in warnings)
    )


async def check_meal_for(user_id: str, items: Sequence[Mapping]) -> MealCheck:
    """Load the profile and today's intake, then check the meal.

    Fails closed: when the profile, the tables or today's meals cannot be
    read, the card says so and the meal needs "Log anyway", so a broken
    check never passes silently.

    Args:
        user_id: Supabase Auth UUID.
        items: The items about to be logged (``USDAResult`` dumps).

    Returns:
        The check; an ``unavailable`` warning when it could not run.
    """
    try:
        entries = await load_hard_profile(user_id)
        today = await intake_today(user_id, entries)
        return check_meal(items, entries, today, load_tables())
    except Exception as exc:  # noqa: BLE001 — any failure must reach the card
        logger.error("meal check failed for %s: %s", user_id, exc)
        texts = _TUNABLES.safety.meal_warnings
        return MealCheck(
            warnings=[_warning("unavailable", None, texts.unavailable)],
            needs_ack=True,
        )


class MealNeedsAck(Exception):
    """The meal hits an allergy or interaction and was not acknowledged."""

    def __init__(self, check: MealCheck) -> None:
        super().__init__("meal needs acknowledgement")
        self.check = check


async def gate_log(
    user_id: str, items: Sequence[Mapping], *, acknowledged: bool
) -> dict[str, Any]:
    """Check a meal at save time and return what to record with it.

    Every save path calls this (the chat card, ``POST /meals/log-items``,
    a saved-meal quick log), so a client that skips the card still cannot
    save an allergen without saying so.

    Args:
        user_id: Supabase Auth UUID.
        items: The items being saved (``USDAResult`` dumps).
        acknowledged: The patient tapped "Log anyway" (or confirmed in chat
            after seeing the reminder).

    Returns:
        Extra ``meal_log.flags``: ``safety_ack`` lists the acknowledged
        warnings, a snapshot of what the patient was told at the time.

    Raises:
        MealNeedsAck: The meal needs acknowledgement and did not have it.
    """
    check = await check_meal_for(user_id, items)
    if not check.needs_ack:
        return {}
    if not acknowledged:
        raise MealNeedsAck(check)
    return {
        "safety_ack": [
            {"rule": w.rule, "entry_id": w.entry_id}
            for w in check.warnings
            if w.severity == "confirm"
        ]
    }


__all__ = [
    "MealCheck",
    "MealNeedsAck",
    "MealWarning",
    "check_meal",
    "check_meal_for",
    "gate_log",
]
