"""Typed loader for the project tunables (prompts, models, thresholds).

All tunable values live in ``tunables.yaml`` next to this module — see the
comments there for what each value does and where it is used. Code accesses
them through :func:`get_tunables`, which validates the file against the
Pydantic models below so a typo'd key or wrong type fails loudly at import
time rather than silently mid-request.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

_DEFAULT_PATH = Path(__file__).parent / "tunables.yaml"


class ModelsConfig(BaseModel):
    extraction: str
    coaching: str
    embedding: str
    embedding_dim: int = Field(gt=0)

    model_config = ConfigDict(extra="forbid")


class TokenLimitsConfig(BaseModel):
    intent_classifier_max_output: int = Field(gt=0)

    model_config = ConfigDict(extra="forbid")


class UsdaConfig(BaseModel):
    search_url: str
    data_types: str
    page_size: int = Field(gt=0)
    request_timeout_s: float = Field(gt=0)
    max_attempts: int = Field(ge=1)
    retry_backoff_s: float = Field(ge=0)
    cache_hit_confidence: float = Field(ge=0.0, le=1.0)
    low_confidence_flag_below: float = Field(ge=0.0, le=1.0)
    suggest_alternative_below: float = Field(ge=0.0, le=1.0)
    match_confidence_floor: float = Field(ge=0.0, le=1.0)
    llm_estimate_confidence: float = Field(ge=0.0, le=1.0)

    model_config = ConfigDict(extra="forbid")


class MemoryConfig(BaseModel):
    dedup_distance_threshold: float = Field(ge=0.0, le=2.0)
    new_fact_confidence: float = Field(ge=0.0, le=1.0)
    top_k_preferences: int = Field(gt=0)

    model_config = ConfigDict(extra="forbid")


class JunkConfig(BaseModel):
    sugar_density_g: float = Field(ge=0)
    sat_fat_density_g: float = Field(ge=0)
    fiber_floor_g: float = Field(ge=0)

    model_config = ConfigDict(extra="forbid")


class SummariesConfig(BaseModel):
    veg_day_fiber_threshold_g: float = Field(ge=0)
    weak_spot_ratio: float = Field(ge=0.0, le=1.0)
    missed_meal_min_days: int = Field(ge=0)

    model_config = ConfigDict(extra="forbid")


class RedisConfig(BaseModel):
    today_key_ttl_s: int = Field(gt=0)

    model_config = ConfigDict(extra="forbid")


class DayConfig(BaseModel):
    """Defines the rolling 'nutrition day' boundary for daily totals."""

    timezone: str = Field(min_length=1)
    reset_hour: int = Field(ge=0, le=23)

    model_config = ConfigDict(extra="forbid")


class MicronutrientConfig(BaseModel):
    usda_name: str
    unit: str

    model_config = ConfigDict(extra="forbid")


class NutrientCheckupConfig(BaseModel):
    """USDA nutrient map + trend threshold + RDA baseline for the Check-up."""

    micronutrients: dict[str, MicronutrientConfig]
    flat_threshold_pct: float = Field(ge=0.0, le=1.0)
    rda: dict[str, float]

    model_config = ConfigDict(extra="forbid")


class UpperLimitEntry(BaseModel):
    """One Tolerable Upper Intake Level for a Mindful Eating safety alert."""

    usda_name: str
    unit: str
    ul: float = Field(gt=0)
    source: str
    url: str

    model_config = ConfigDict(extra="forbid")


class RoutingConfig(BaseModel):
    log_signals: list[str]
    query_signals: list[str]
    confirm_keywords: list[str]
    reject_keywords: list[str]

    model_config = ConfigDict(extra="forbid")


class PromptsConfig(BaseModel):
    extraction_system: str
    image_classify_system: str
    correction_system: str
    intent_system: str
    query_parse_system: str
    coaching_response_system: str
    coaching_role_and_tone: str
    coaching_hard_constraints: str
    fact_extraction_system: str
    nutrition_estimate_system: str
    decompose_system: str

    model_config = ConfigDict(extra="forbid")


class FeaturesConfig(BaseModel):
    auto_decompose_enabled: bool = True

    model_config = ConfigDict(extra="forbid")


class Tunables(BaseModel):
    """Validated view of tunables.yaml."""

    models: ModelsConfig
    token_limits: TokenLimitsConfig
    usda: UsdaConfig
    junk: JunkConfig
    memory: MemoryConfig
    summaries: SummariesConfig
    redis: RedisConfig
    day: DayConfig
    nutrient_checkup: NutrientCheckupConfig
    routing: RoutingConfig
    prompts: PromptsConfig
    features: FeaturesConfig
    upper_limits: dict[str, UpperLimitEntry]

    model_config = ConfigDict(extra="forbid")


@lru_cache(maxsize=1)
def get_tunables() -> Tunables:
    """Load and validate the tunables file (cached for the process lifetime).

    The path defaults to ``tunables.yaml`` beside this module; set the
    NUTRICHAT_TUNABLES_PATH env var to load an alternative file.

    Returns:
        Validated Tunables instance.

    Raises:
        FileNotFoundError: If the tunables file does not exist.
        pydantic.ValidationError: If the file has missing/unknown keys or
            values of the wrong type.
    """
    path = Path(os.environ.get("NUTRICHAT_TUNABLES_PATH", _DEFAULT_PATH))
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return Tunables.model_validate(raw)


__all__ = ["Tunables", "UpperLimitEntry", "get_tunables"]
