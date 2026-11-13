"""The deterministic recipe check (FR-009): no model, no I/O, no randomness.

``check`` compares a generated recipe, its USDA-resolved ingredients and
nutrient totals with the patient's confirmed hard entries and the clinical
tables. It never raises on a bad recipe: it returns the failures. Pending
entries never bind; only confirmed ones are evaluated.

This module must not import ``backend.agent`` (tests/safety/test_boundaries.py).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.safety.limits import LimitProgress
from backend.safety.matching import (
    TermRule,
    matched_term,
    medication_drug,
    term_rules,
)
from backend.safety.profile import (
    AllergyValue,
    DietSettingValue,
    FoodExclusionValue,
    HardEntry,
    MedicationValue,
    NutrientLimitValue,
    PhysicalLimitationValue,
    confirmed,
    limit_text,
    missing_values,
    version_of,
)
from backend.safety.recipe import (
    GRAMS_PER_UNIT,
    NutrientTotal,
    Recipe,
    ResolvedIngredient,
    malformed_reasons,
    totals_for,
)
from backend.safety.tables import ClinicalTables

Rule = Literal[
    "malformed",
    "allergen",
    "food_exclusion",
    "diet_setting",
    "interaction",
    "nutrient_limit",
    "texture",
    "physical",
]


class Failure(BaseModel):
    """One rule a recipe broke, with the values compared."""

    rule: Rule
    entry_id: str | None
    detail: str
    value: float | None = None
    limit: float | None = None
    unit: str | None = None

    model_config = ConfigDict(extra="forbid")


class Applied(BaseModel):
    """A confirmed entry that was evaluated.

    ``phrase`` names the reason ("your peanut allergy") and ``kept`` what the
    recipe was kept to ("free of peanut"); the patient-facing sentence is
    built from both (safety/render.py).
    """

    entry_id: str
    phrase: str
    kept: str

    model_config = ConfigDict(extra="forbid")


class Conflict(BaseModel):
    """Two rules on one nutrient and period; the stricter was applied (FR-035)."""

    note: str
    entry_ids: list[str]

    model_config = ConfigDict(extra="forbid")


class CheckResult(BaseModel):
    """Outcome of one check, stored whole as the recommendation's snapshot."""

    passed: bool
    failures: list[Failure]
    applied: list[Applied]
    missing_values: list[str]
    conflicts: list[Conflict]
    notes: list[str] = Field(default_factory=list)
    profile_version: str
    entry_ids: list[str]
    table_versions: dict[str, str]
    totals: list[NutrientTotal]
    attempt: int

    model_config = ConfigDict(extra="forbid")


_PHYSICAL_PHRASES = {
    "chewing": ("your chewing difficulty", "soft enough to chew"),
    "swallowing": ("your swallowing difficulty", "easy to swallow"),
    "grip": ("your grip strength", "easy on your hands"),
    "standing_time": ("your limited standing time", "quick to make on your feet"),
}


def _number(value: float) -> str:
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def _convert(amount: float, from_unit: str, to_unit: str) -> float:
    return amount * GRAMS_PER_UNIT[from_unit] / GRAMS_PER_UNIT[to_unit]


def _term_failures(
    rules: list[TermRule], resolved: list[ResolvedIngredient]
) -> list[Failure]:
    failures: list[Failure] = []
    for rule in rules:
        for ingredient in resolved:
            for source, text in (
                ("ingredient", ingredient.name),
                ("USDA", ingredient.usda_description),
            ):
                term = rule.hit(text) if text else None
                if term is None:
                    continue
                detail = f"{rule.rule}: {rule.name} ({source}: {text}, term: {term})"
                if rule.reason:
                    detail += f", {rule.reason}"
                failures.append(
                    Failure(rule=rule.rule, entry_id=rule.entry_id, detail=detail)
                )
                break
    return failures


def _total(totals: list[NutrientTotal], nutrient: str) -> NutrientTotal:
    return next(t for t in totals if t.nutrient == nutrient)


def _limit_failure(
    rule: Literal["nutrient_limit", "interaction"],
    entry_id: str,
    label: str,
    total: NutrientTotal,
    ceiling: float,
    unit: str,
    already: float = 0.0,
) -> Failure | None:
    """A failure when ``already`` plus the recipe's total passes ``ceiling``."""
    if total.amount is None:
        return Failure(
            rule=rule,
            entry_id=entry_id,
            detail=(
                f"{rule}: {label} unknown, the food database has no value for "
                f"{', '.join(total.unknown_from)}"
            ),
            limit=ceiling,
            unit=unit,
        )
    amount = _convert(total.amount, total.unit, unit) + already
    if amount <= ceiling:
        return None
    return Failure(
        rule=rule,
        entry_id=entry_id,
        detail=(
            f"{rule}: {label} {_number(amount)} {unit} "
            f"is over {_number(ceiling)} {unit}"
        ),
        value=round(amount, 2),
        limit=ceiling,
        unit=unit,
    )


def _nutrient_failures(
    entries: list[HardEntry],
    totals: list[NutrientTotal],
    today_intake: Mapping[str, LimitProgress],
    tables: ClinicalTables,
) -> list[Failure]:
    found: list[Failure | None] = []
    for entry in entries:
        value = entry.value
        if isinstance(value, NutrientLimitValue):
            progress = today_intake.get(entry.id)
            already = progress.so_far if value.period == "per_day" and progress else 0.0
            found.append(
                _limit_failure(
                    "nutrient_limit",
                    entry.id,
                    f"{value.nutrient} {limit_text(value)}",
                    _total(totals, value.nutrient),
                    value.amount,
                    value.unit,
                    already,
                )
            )
        elif isinstance(value, MedicationValue):
            drug = medication_drug(entry, tables)
            for item in tables.drug_food_interactions.drugs[drug].rules if drug else []:
                if item.kind == "nutrient_ceiling":
                    found.append(
                        _limit_failure(
                            "interaction",
                            entry.id,
                            f"{item.nutrient.replace('_', ' ')} with {value.name} "
                            f"({item.reason})",
                            _total(totals, item.nutrient),
                            item.amount,
                            item.unit,
                        )
                    )
    return [f for f in found if f is not None]


def _texture_failures(
    recipe: Recipe, entries: list[HardEntry], tables: ClinicalTables
) -> list[Failure]:
    rules = tables.texture_rules
    failures: list[Failure] = []
    for entry in entries:
        value = entry.value
        if not (
            isinstance(value, PhysicalLimitationValue)
            and value.kind in rules.limitations
        ):
            continue
        allowed = value.max_texture or rules.limitations[value.kind].default_max
        if allowed not in rules.levels:
            allowed = rules.limitations[value.kind].default_max
        if rules.levels.index(recipe.texture) > rules.levels.index(allowed):
            failures.append(
                Failure(
                    rule="texture",
                    entry_id=entry.id,
                    detail=f"texture: {recipe.texture} is firmer than {allowed} "
                    f"({value.kind})",
                )
            )
        if value.kind not in rules.crunchy_or_dry_blocked_for:
            continue
        crunchy = [
            i.name
            for i in recipe.ingredients
            if matched_term(i.name, rules.crunchy_terms)
        ]
        if recipe.crunchy_or_dry or crunchy:
            failures.append(
                Failure(
                    rule="texture",
                    entry_id=entry.id,
                    detail="texture: crunchy or dry"
                    + (f" ({', '.join(crunchy)})" if crunchy else "")
                    + f" ({value.kind})",
                )
            )
    return failures


def _physical_failures(
    recipe: Recipe, entries: list[HardEntry], tables: ClinicalTables
) -> list[Failure]:
    failures: list[Failure] = []
    for entry in entries:
        value = entry.value
        if not isinstance(value, PhysicalLimitationValue):
            continue
        if value.kind == "standing_time" and value.max_active_minutes is not None:
            if recipe.active_minutes > value.max_active_minutes:
                failures.append(
                    Failure(
                        rule="physical",
                        entry_id=entry.id,
                        detail=f"physical: {recipe.active_minutes} active minutes "
                        f"is over {value.max_active_minutes}",
                        value=recipe.active_minutes,
                        limit=value.max_active_minutes,
                        unit="min",
                    )
                )
        elif value.kind == "grip":
            grip = tables.physical_rules.grip
            equipment = [
                e
                for e in recipe.equipment
                if any(b.casefold() in e.casefold() for b in grip.blocked_equipment)
            ]
            steps = [
                t
                for t in grip.blocked_step_terms
                if any(t.casefold() in s.casefold() for s in recipe.steps)
            ]
            for found in (*equipment, *steps):
                failures.append(
                    Failure(
                        rule="physical",
                        entry_id=entry.id,
                        detail=f"physical: {found} is hard on weak grip",
                    )
                )
    return failures


def _applied(entry: HardEntry, tables: ClinicalTables) -> Applied | None:
    """The patient-facing phrase for an entry the check evaluates, else None."""
    value = entry.value
    if isinstance(value, AllergyValue):
        label = (
            ", ".join(value.custom_terms or [])
            if value.allergen_group is None
            else tables.allergen_groups.groups[value.allergen_group].label
        )
        return Applied(
            entry_id=entry.id, phrase=f"your {label} allergy", kept=f"free of {label}"
        )
    if isinstance(value, FoodExclusionValue):
        terms = ", ".join(value.terms)
        return Applied(
            entry_id=entry.id,
            phrase=f"your choice to avoid {terms}",
            kept=f"free of {terms}",
        )
    if isinstance(value, DietSettingValue):
        name = value.setting.replace("_", " ")
        return Applied(entry_id=entry.id, phrase=f"your {name} diet", kept=name)
    if isinstance(value, MedicationValue):
        if medication_drug(entry, tables) is None:
            return None
        return Applied(
            entry_id=entry.id,
            phrase=f"your {value.name}",
            kept=f"safe alongside {value.name}",
        )
    if isinstance(value, PhysicalLimitationValue):
        phrase, kept = _PHYSICAL_PHRASES[value.kind]
        return Applied(entry_id=entry.id, phrase=phrase, kept=kept)
    if isinstance(value, NutrientLimitValue):
        period = "per day" if value.period == "per_day" else "per meal"
        return Applied(
            entry_id=entry.id,
            phrase=f"your {value.nutrient} limit of {_number(value.amount)} "
            f"{value.unit} {period}",
            kept=f"low in {value.nutrient}",
        )
    return None


def _ceilings(
    entries: list[HardEntry], tables: ClinicalTables
) -> dict[tuple[str, str], list[tuple[float, str, str]]]:
    """Per (nutrient, period): every (amount in grams, label, entry id)."""
    found: dict[tuple[str, str], list[tuple[float, str, str]]] = {}
    for entry in entries:
        value = entry.value
        if isinstance(value, NutrientLimitValue):
            key = (value.nutrient, value.period)
            grams = value.amount * GRAMS_PER_UNIT[value.unit]
            found.setdefault(key, []).append(
                (grams, f"{_number(value.amount)} {value.unit}", entry.id)
            )
        elif isinstance(value, MedicationValue):
            drug = medication_drug(entry, tables)
            for item in tables.drug_food_interactions.drugs[drug].rules if drug else []:
                if item.kind == "nutrient_ceiling":
                    found.setdefault((item.nutrient, "per_meal"), []).append(
                        (
                            item.amount * GRAMS_PER_UNIT[item.unit],
                            f"{_number(item.amount)} {item.unit} ({value.name})",
                            entry.id,
                        )
                    )
    return found


def find_conflicts(entries: list[HardEntry], tables: ClinicalTables) -> list[Conflict]:
    """Limits on one nutrient and period that differ; the stricter one applies."""
    conflicts: list[Conflict] = []
    for (nutrient, period), limits in _ceilings(entries, tables).items():
        if len({grams for grams, _, _ in limits}) < 2:
            continue
        stricter = min(limits)
        name = nutrient.replace("_", " ")
        when = "a day" if period == "per_day" else "a meal"
        conflicts.append(
            Conflict(
                note=f"Your {name} limits differ "
                f"({' and '.join(label for _, label, _ in limits)} {when}); "
                f"I followed the stricter one, {stricter[1]}.",
                entry_ids=[entry_id for _, _, entry_id in limits],
            )
        )
    return conflicts


def _notes(
    entries: list[HardEntry], today_intake: Mapping[str, LimitProgress]
) -> list[str]:
    notes: list[str] = []
    for entry in entries:
        progress = today_intake.get(entry.id)
        if (
            isinstance(entry.value, NutrientLimitValue)
            and entry.value.period == "per_day"
            and progress
            and progress.unknown_items
        ):
            notes.append(
                f"Some foods logged today have no {entry.value.nutrient} value, "
                "so today's total may be low."
            )
    return notes


def _physical_missing(entries: list[HardEntry]) -> list[str]:
    return [
        "active-time limit for your limited standing time"
        for e in entries
        if isinstance(e.value, PhysicalLimitationValue)
        and e.value.kind == "standing_time"
        and e.value.max_active_minutes is None
    ]


def check(
    recipe: Recipe,
    resolved: list[ResolvedIngredient],
    entries: list[HardEntry],
    today_intake: Mapping[str, LimitProgress],
    tables: ClinicalTables,
    attempt: int = 1,
) -> CheckResult:
    """Check a recipe against the patient's confirmed profile.

    Args:
        recipe: The generated recipe.
        resolved: Its ingredients matched in USDA, in recipe order.
        entries: The patient's live hard entries; pending ones are ignored.
        today_intake: Today's progress per limit entry id, from
            ``limits.intake_today`` (needed for per-day limits).
        tables: Clinical tables.
        attempt: Which generation attempt this is, recorded in the result.

    Returns:
        The result; ``passed`` only when there are no failures.

    Raises:
        TablesUnavailable: A confirmed entry names a group the tables lack.
    """
    binding = confirmed(entries)
    totals = totals_for(recipe, resolved)
    failures = [
        Failure(rule="malformed", entry_id=None, detail=f"malformed: {reason}")
        for reason in malformed_reasons(recipe)
    ]
    if not failures:
        failures = [
            *_term_failures(term_rules(binding, tables), resolved),
            *_nutrient_failures(binding, totals, today_intake, tables),
            *_texture_failures(recipe, binding, tables),
            *_physical_failures(recipe, binding, tables),
        ]
    return CheckResult(
        passed=not failures,
        failures=failures,
        applied=[a for e in binding if (a := _applied(e, tables))],
        missing_values=[
            *missing_values(entries, tables),
            *_physical_missing(binding),
        ],
        conflicts=find_conflicts(binding, tables),
        notes=_notes(binding, today_intake),
        profile_version=version_of(entries),
        entry_ids=[e.id for e in binding],
        table_versions=dict(tables.hashes),
        totals=totals,
        attempt=attempt,
    )
