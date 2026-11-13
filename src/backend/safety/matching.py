"""Map free text to the hard profile's allergen groups.

One matcher for every writer (coach tools, curator, backfill): case-folded,
word-boundary, longest term wins, minus the group's ``exclude_terms``
(specs/013 research R8).
"""

from __future__ import annotations

import re

from backend.safety.profile import AllergyValue, FoodExclusionValue
from backend.safety.tables import ClinicalTables


def _contains(text: str, term: str) -> bool:
    return re.search(rf"\b{re.escape(term)}\b", text) is not None


def allergen_group_for(text: str, tables: ClinicalTables) -> str | None:
    """Return the allergen group a statement names, or None.

    Args:
        text: A fact such as "Allergic to peanuts".
        tables: Clinical tables holding the allergen groups.

    Returns:
        The group key owning the longest matching term.
    """
    folded = text.casefold()
    best: tuple[int, str] | None = None
    for key, group in tables.allergen_groups.groups.items():
        remaining = folded
        for excluded in group.exclude_terms:
            remaining = re.sub(rf"\b{re.escape(excluded.casefold())}\b", " ", remaining)
        for term in group.terms:
            if _contains(remaining, term.casefold()) and (
                best is None or len(term) > best[0]
            ):
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
