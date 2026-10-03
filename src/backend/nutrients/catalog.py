"""Lookups over the nutrient catalogue: aliases, key sets and public view.

Everything here is derived from :func:`backend.config.get_catalog` — the
catalogue file is the single definition (spec 008 FR-015/FR-018); this
module only indexes it.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from backend.config import NutrientCatalog, NutrientDef, get_catalog


def _active(catalog: NutrientCatalog) -> list[NutrientDef]:
    """Return the catalogue's active entries in file order."""
    return [n for n in catalog.nutrients if n.status == "active"]


@lru_cache(maxsize=1)
def _alias_map() -> dict[str, str]:
    """Map every USDA alias (lowercased) to its catalogue key."""
    mapping: dict[str, str] = {}
    for n in get_catalog().nutrients:
        for name in n.usda_names:
            mapping[name.lower()] = n.key
    return mapping


def nutrient(key: str) -> NutrientDef:
    """Return the catalogue entry for ``key``.

    Raises:
        KeyError: If ``key`` is not in the catalogue.
    """
    for n in get_catalog().nutrients:
        if n.key == key:
            return n
    raise KeyError(key)


def key_for_usda_name(name: str) -> str | None:
    """Return the catalogue key a USDA nutrient name maps to, or None."""
    return _alias_map().get(name.lower())


def usda_names_by_priority(key: str) -> list[str]:
    """Return the USDA aliases of ``key`` in priority order (first wins)."""
    return list(nutrient(key).usda_names)


@lru_cache(maxsize=1)
def stored_keys() -> tuple[str, ...]:
    """Active keys stored in item micros / meal summaries.

    Excludes entries kept in a meal_log column (fiber) or derived on read
    (salt) — storing those again would duplicate data (FR-018).
    """
    return tuple(
        n.key for n in _active(get_catalog()) if n.column is None and n.derived is None
    )


@lru_cache(maxsize=1)
def usda_only_keys() -> frozenset[str]:
    """Keys that are never AI-estimated (FR-004a)."""
    return frozenset(n.key for n in get_catalog().nutrients if n.usda_only)


@lru_cache(maxsize=1)
def estimable_keys() -> tuple[str, ...]:
    """Stored keys the AI fallback may estimate (stored minus USDA-only)."""
    only = usda_only_keys()
    return tuple(k for k in stored_keys() if k not in only)


def resolve_key(name_or_key: str) -> str | None:
    """Resolve a catalogue key or any USDA alias to a catalogue key.

    Used by coaching, whose parser may emit either form.
    """
    candidate = name_or_key.strip()
    lowered = candidate.lower()
    for n in get_catalog().nutrients:
        if n.key == lowered:
            return n.key
    return key_for_usda_name(candidate)


def public_view() -> dict[str, Any]:
    """Catalogue as served to clients (GET /meta/nutrients).

    Drops server-only fields (usda_names, max_per_100g, column).
    """
    catalog = get_catalog()
    hidden = {"usda_names", "max_per_100g", "column"}
    return {
        "version": catalog.version,
        "groups": [g.model_dump() for g in catalog.groups],
        "nutrients": [
            n.model_dump(by_alias=True, exclude=hidden) for n in catalog.nutrients
        ],
    }
