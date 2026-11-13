"""Load and validate the clinical YAML tables (config/clinical/).

Each file is validated by a Pydantic model. A missing or invalid file raises
:class:`TablesUnavailable`: callers must then refuse to show a recipe (and the
red-flag screen fails closed), never fall back to a default. The SHA-256 of
each file's bytes is its version; it is stored with every check and escalation
so a decision can be traced to the exact table text. Files are re-read when
their mtime changes.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date
from pathlib import Path
from typing import Annotated, Literal, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from backend.config import get_tunables

_BACKEND_DIR = Path(__file__).resolve().parents[1]


class TablesUnavailable(Exception):
    """A clinical table is missing, unreadable or invalid."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Header(_Strict):
    version: int
    reviewed_by: str = Field(min_length=1)
    reviewed_on: date | None = None


class AllergenGroup(_Strict):
    label: str
    terms: list[str] = Field(min_length=1)
    exclude_terms: list[str] = Field(default_factory=list)


class AllergenGroups(_Header):
    groups: dict[str, AllergenGroup]


class NutrientCeilingRule(_Strict):
    kind: Literal["nutrient_ceiling"]
    nutrient: str
    amount: float = Field(gt=0)
    unit: str
    reason: str


class AvoidTermsRule(_Strict):
    kind: Literal["avoid_terms"]
    terms: list[str] = Field(min_length=1)
    reason: str


class Drug(_Strict):
    names: list[str] = Field(min_length=1)
    rules: list[
        Annotated[NutrientCeilingRule | AvoidTermsRule, Field(discriminator="kind")]
    ]


class DrugFoodInteractions(_Header):
    drugs: dict[str, Drug]


class TextureLimitation(_Strict):
    default_max: str


class TextureRules(_Header):
    levels: list[str] = Field(min_length=1)
    limitations: dict[str, TextureLimitation]
    crunchy_or_dry_blocked_for: list[str]
    crunchy_terms: list[str]

    @model_validator(mode="after")
    def _levels_known(self) -> TextureRules:
        for name, limitation in self.limitations.items():
            if limitation.default_max not in self.levels:
                raise ValueError(f"{name}: default_max not in levels")
        return self


class GripRules(_Strict):
    blocked_equipment: list[str]
    blocked_step_terms: list[str]


class StandingTimeRules(_Strict):
    compare: Literal["active_minutes"]


class PhysicalRules(_Header):
    grip: GripRules
    standing_time: StandingTimeRules


class TermGroup(_Strict):
    label: str
    terms: list[str] = Field(min_length=1)
    exclude_terms: list[str] = Field(default_factory=list)


class DietRule(_Strict):
    groups: list[str]
    terms: list[str]


class DietRules(_Header):
    term_groups: dict[str, TermGroup]
    settings: dict[str, DietRule]


class ConditionLimit(_Strict):
    label: str
    expects_limits: list[str]


class ConditionLimits(_Header):
    conditions: dict[str, ConditionLimit]


class RedFlagRule(_Strict):
    id: str = Field(min_length=1)
    label: str
    patterns: list[str] = Field(min_length=1)
    response: str = Field(min_length=1)

    @model_validator(mode="after")
    def _patterns_compile(self) -> RedFlagRule:
        for pattern in self.patterns:
            try:
                re.compile(pattern, re.IGNORECASE)
            except re.error as exc:
                raise ValueError(f"{self.id}: invalid pattern {pattern!r}") from exc
        return self


class RedFlags(_Header):
    fallback_unavailable_text: str = Field(min_length=1)
    rules: list[RedFlagRule]


class ClinicalTables(_Strict):
    """Every clinical table plus the content hash of each file."""

    allergen_groups: AllergenGroups
    drug_food_interactions: DrugFoodInteractions
    diet_rules: DietRules
    texture_rules: TextureRules
    physical_rules: PhysicalRules
    condition_limits: ConditionLimits
    red_flags: RedFlags
    hashes: dict[str, str]

    @model_validator(mode="after")
    def _diet_groups_known(self) -> ClinicalTables:
        known = set(self.diet_rules.term_groups) | set(self.allergen_groups.groups)
        for setting, rule in self.diet_rules.settings.items():
            unknown = [g for g in rule.groups if g not in known]
            if unknown:
                raise ValueError(f"diet_rules {setting}: unknown groups {unknown}")
        return self


_MODELS: dict[str, type[_Header]] = {
    "allergen_groups": AllergenGroups,
    "drug_food_interactions": DrugFoodInteractions,
    "diet_rules": DietRules,
    "texture_rules": TextureRules,
    "physical_rules": PhysicalRules,
    "condition_limits": ConditionLimits,
    "red_flags": RedFlags,
}

# path -> (mtime_ns, sha256, parsed). A file is re-read only when its mtime moves.
_cache: dict[Path, tuple[int, str, _Header]] = {}


def _load_file(path: Path, model: type[_Header]) -> tuple[str, _Header]:
    try:
        mtime = path.stat().st_mtime_ns
        cached = _cache.get(path)
        if cached is not None and cached[0] == mtime:
            return cached[1], cached[2]
        raw = path.read_bytes()
        parsed = model.model_validate(yaml.safe_load(raw))
    except (OSError, yaml.YAMLError, ValidationError, ValueError) as exc:
        _cache.pop(path, None)
        raise TablesUnavailable(f"{path.name}: {exc}") from exc
    digest = hashlib.sha256(raw).hexdigest()
    _cache[path] = (mtime, digest, parsed)
    return digest, parsed


def clinical_dir(directory: Path | None = None) -> Path:
    """Folder holding the clinical YAML files (default: the tunable)."""
    return directory or _BACKEND_DIR / get_tunables().safety.clinical_dir


def load_red_flags(directory: Path | None = None) -> tuple[str, RedFlags]:
    """Load only the red-flag file, so other broken tables cannot affect it.

    Args:
        directory: Folder holding the YAML files; defaults like load_tables.

    Returns:
        The file's SHA-256 and the validated rules.

    Raises:
        TablesUnavailable: If red_flags.yaml is missing, unreadable or invalid.
    """
    digest, parsed = _load_file(clinical_dir(directory) / "red_flags.yaml", RedFlags)
    return digest, cast(RedFlags, parsed)


def load_tables(directory: Path | None = None) -> ClinicalTables:
    """Load all clinical tables, re-reading any file whose mtime changed.

    Args:
        directory: Folder holding the YAML files. Defaults to the
            ``safety.clinical_dir`` tunable, relative to ``src/backend``.

    Returns:
        The validated tables with a SHA-256 content hash per file.

    Raises:
        TablesUnavailable: If any file is missing, unreadable or invalid.
    """
    base = clinical_dir(directory)
    parsed: dict[str, _Header] = {}
    hashes: dict[str, str] = {}
    for name, model in _MODELS.items():
        hashes[name], parsed[name] = _load_file(base / f"{name}.yaml", model)
    try:
        return ClinicalTables.model_validate({**parsed, "hashes": hashes})
    except ValidationError as exc:
        raise TablesUnavailable(str(exc)) from exc
