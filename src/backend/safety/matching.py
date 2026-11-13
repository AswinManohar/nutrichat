"""Match free text against the clinical tables' terms.

One matcher for every writer (coach tools, curator, backfill), the recipe
checker and the reply guard: case-folded, word-boundary (a plural still
matches), longest term wins, minus the group's ``exclude_terms``
(specs/013 research R8).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from backend.safety.profile import (
    AllergyValue,
    DietSettingValue,
    FoodExclusionValue,
    HardEntry,
    MedicationValue,
    confirmed,
)
from backend.safety.tables import ClinicalTables, TablesUnavailable


@lru_cache(maxsize=2048)
def _pattern(term: str) -> re.Pattern[str]:
    return re.compile(rf"\b{re.escape(term.casefold())}(?:e?s)?\b")


def matched_term(
    text: str, terms: Iterable[str], exclude_terms: Iterable[str] = ()
) -> str | None:
    """The longest of ``terms`` found in ``text`` once ``exclude_terms`` are removed."""
    folded = text.casefold()
    for excluded in exclude_terms:
        folded = _pattern(excluded).sub(" ", folded)
    hits = [t for t in terms if _pattern(t).search(folded)]
    return max(hits, key=len, default=None)


def find_terms(
    text: str, terms: Iterable[str], exclude_terms: Iterable[str] = ()
) -> list[tuple[str, int, int]]:
    """Every occurrence of ``terms`` in the case-folded ``text``.

    Args:
        text: Free text.
        terms: Words to find.
        exclude_terms: Phrases blanked out first, so they never match.

    Returns:
        ``(term, start, end)`` per occurrence, offsets into ``text.casefold()``.
    """
    folded = text.casefold()
    for excluded in exclude_terms:
        folded = _pattern(excluded).sub(lambda m: " " * len(m.group()), folded)
    return [
        (term, m.start(), m.end())
        for term in terms
        for m in _pattern(term).finditer(folded)
    ]


def allergen_group_for(text: str, tables: ClinicalTables) -> str | None:
    """Return the allergen group a statement names, or None.

    Args:
        text: A fact such as "Allergic to peanuts".
        tables: Clinical tables holding the allergen groups.

    Returns:
        The group key owning the longest matching term.
    """
    best: tuple[int, str] | None = None
    for key, group in tables.allergen_groups.groups.items():
        term = matched_term(text, group.terms, group.exclude_terms)
        if term is not None and (best is None or len(term) > best[0]):
            best = (len(term), key)
    return best[1] if best else None


def restriction_value(
    text: str, tables: ClinicalTables
) -> tuple[AllergyValue | FoodExclusionValue, str | None]:
    """Type a free-text restriction: an allergy when a group matches, else an exclusion.

    Args:
        text: The restriction as stated.
        tables: Clinical tables holding the allergen groups.

    Returns:
        The value and the label to store with it (None when the value derives
        its own label).
    """
    group = allergen_group_for(text, tables)
    if group is not None:
        return AllergyValue(allergen_group=group), None
    return FoodExclusionValue(terms=[text]), text


@dataclass(frozen=True)
class TermRule:
    """Words that one confirmed entry forbids (allergy, exclusion, diet, drug)."""

    entry_id: str
    rule: Literal["allergen", "food_exclusion", "diet_setting", "interaction"]
    name: str
    terms: tuple[str, ...]
    exclude_terms: tuple[str, ...] = ()
    reason: str = ""

    def hit(self, text: str) -> str | None:
        """The forbidden term found in ``text``, or None."""
        return matched_term(text, self.terms, self.exclude_terms)


def medication_drug(entry: HardEntry, tables: ClinicalTables) -> str | None:
    """The interactions-table key for a medication entry, or None if unknown."""
    value = entry.value
    if not isinstance(value, MedicationValue):
        return None
    drugs = tables.drug_food_interactions.drugs
    if value.matched_drug in drugs:
        return value.matched_drug
    for key, drug in drugs.items():
        if matched_term(value.name, drug.names) is not None:
            return key
    return None


def _group(tables: ClinicalTables, key: str) -> tuple[str, list[str], list[str]]:
    """Label, terms and exclusions of a diet or allergen group."""
    group = tables.diet_rules.term_groups.get(key) or tables.allergen_groups.groups.get(
        key
    )
    if group is None:
        raise TablesUnavailable(f"group {key!r} is not in the clinical tables")
    return group.label, group.terms, group.exclude_terms


def term_rules(entries: list[HardEntry], tables: ClinicalTables) -> list[TermRule]:
    """The word lists the confirmed entries forbid; pending entries never bind.

    Args:
        entries: The patient's live hard entries.
        tables: Clinical tables.

    Returns:
        One rule per allergy, exclusion, diet-setting group or drug rule.

    Raises:
        TablesUnavailable: A confirmed entry names a group the tables lack.
    """
    rules: list[TermRule] = []
    for entry in confirmed(entries):
        value = entry.value
        if isinstance(value, AllergyValue):
            if value.allergen_group is None:
                rules.append(
                    TermRule(
                        entry.id,
                        "allergen",
                        ", ".join(value.custom_terms or []),
                        tuple(value.custom_terms or []),
                    )
                )
            else:
                label, terms, excluded = _group(tables, value.allergen_group)
                rules.append(
                    TermRule(entry.id, "allergen", label, tuple(terms), tuple(excluded))
                )
        elif isinstance(value, FoodExclusionValue):
            rules.append(
                TermRule(
                    entry.id,
                    "food_exclusion",
                    ", ".join(value.terms),
                    tuple(value.terms),
                )
            )
        elif isinstance(value, DietSettingValue):
            rule = tables.diet_rules.settings.get(value.setting)
            for key in rule.groups if rule else []:
                label, terms, excluded = _group(tables, key)
                rules.append(
                    TermRule(
                        entry.id,
                        "diet_setting",
                        f"{value.setting.replace('_', ' ')} ({label})",
                        tuple(terms),
                        tuple(excluded),
                    )
                )
            if rule and rule.terms:
                rules.append(
                    TermRule(
                        entry.id,
                        "diet_setting",
                        value.setting.replace("_", " "),
                        tuple(rule.terms),
                    )
                )
        elif isinstance(value, MedicationValue):
            drug = medication_drug(entry, tables)
            for item in tables.drug_food_interactions.drugs[drug].rules if drug else []:
                if item.kind == "avoid_terms":
                    rules.append(
                        TermRule(
                            entry.id,
                            "interaction",
                            value.name,
                            tuple(item.terms),
                            reason=item.reason,
                        )
                    )
    return rules
