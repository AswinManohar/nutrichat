"""The suggestion loop with a fake recipe generator and a fake food database."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from unittest.mock import patch

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy import select

from backend.agent import suggest
from backend.agent.tools.usda_local import FoodDbUnavailable
from backend.config import get_tunables
from backend.db.models import CheckFailure, Recommendation, ReviewItem
from backend.db.session import get_session
from backend.safety import profile
from backend.safety.checker import CheckResult
from backend.safety.recipe import USDA_KEYS
from backend.safety.tables import TablesUnavailable
from tests.profile_helpers import hard_entry

_SAFETY = get_tunables().safety

_RICE = {"name": "Rice bowl", "ingredients": ["rice", "olive oil"]}
_PEANUT = {"name": "Satay bowl", "ingredients": ["rice", "peanut oil"]}


def recipe_args(spec: dict) -> dict:
    return {
        "name": spec["name"],
        "intro": "A simple bowl.",
        "ingredients": [{"name": n, "qty_g": 100} for n in spec["ingredients"]],
        "texture": "regular",
        "crunchy_or_dry": False,
        "steps": ["Cook and serve."],
        "active_minutes": 10,
        "total_minutes": 20,
        "equipment": [],
        "servings": 1,
    }


class _Match:
    fdc_id = 1
    match_confidence = 1.0
    macros_per_100g = {"kcal": 100.0, "protein_g": 2.0}
    nutrients_per_100g = {  # noqa: RUF012
        key: {"amount": 1.0, "unit": "mg"} for key in USDA_KEYS.values()
    }

    def __init__(self, name: str) -> None:
        self.description = name.title()


@pytest.fixture(autouse=True)
def no_plan_sampling(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sampling is by id hash: switch it off so other tests see no plan_sample."""
    monkeypatch.setattr(suggest._SAFETY, "plan_sample_rate", 0.0)


@pytest.fixture
def prompts() -> list[str]:
    """The instructions each generation attempt was given."""
    return []


@pytest.fixture
def generator(prompts: list[str]) -> Iterator[Callable[..., None]]:
    """Install a fake generator that replays answers (dicts, or a bad answer)."""
    answers: list[dict | str] = []

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        prompts.append(info.instructions or "")
        answer = answers.pop(0)
        args = {"name": 1} if answer == "malformed" else recipe_args(answer)
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, args)])

    def install(*replies: dict | str) -> None:
        answers[:] = replies

    with (
        suggest._recipe_agent.override(model=FunctionModel(respond)),
        patch.object(suggest.usda_local, "lookup", side_effect=_Match),
        patch.object(suggest, "_soft_block", return_value=""),
    ):
        yield install


def peanut_allergy() -> profile.HardEntry:
    return hard_entry(
        profile.AllergyValue(allergen_group="peanut"), entry_id=str(uuid.uuid4())
    )


async def run(user_id: str, entries: list[profile.HardEntry], text: str = "dinner?"):
    return await suggest.suggest_meal(user_id, text, [], entries)


async def rows(model):
    async with get_session()() as session:
        return list((await session.execute(select(model))).scalars().all())


async def user_rows(model, user_id: str):
    return [r for r in await rows(model) if r.user_id == user_id]


async def test_a_recipe_that_passes_is_shown_and_recorded(db_user, generator) -> None:
    entry = peanut_allergy()
    generator(_RICE)

    result = await run(db_user, [entry])

    assert result.recipe is not None and result.attempts == 1
    assert "Rice bowl" in result.message
    assert "Kept this free of peanut because of your peanut allergy." in result.message
    [recommendation] = await user_rows(Recommendation, db_user)
    assert recommendation.id == result.recommendation_id
    assert recommendation.status == "shown" and recommendation.attempts == 1
    snapshot = CheckResult.model_validate(recommendation.check_snapshot)
    assert snapshot.passed and snapshot.entry_ids == [entry.id]
    assert snapshot.profile_version == profile.version_of([entry])
    assert set(snapshot.table_versions) >= {"allergen_groups", "diet_rules"}
    assert recommendation.recipe["name"] == "Rice bowl"
    assert await user_rows(CheckFailure, db_user) == []


async def test_a_failed_first_attempt_is_regenerated_with_the_reason(
    db_user, generator, prompts
) -> None:
    generator(_PEANUT, _RICE)

    result = await run(db_user, [peanut_allergy()])

    assert result.recipe is not None and result.attempts == 2
    assert "Satay bowl" not in result.message
    assert "allergen: peanut" in prompts[1] and "allergen: peanut" not in prompts[0]
    [failure] = await user_rows(CheckFailure, db_user)
    assert failure.outcome == "regenerated" and failure.attempt == 1
    assert failure.recommendation_id == result.recommendation_id
    assert failure.failures[0]["rule"] == "allergen"
    assert failure.failures[0]["compared"] == {
        "value": None,
        "limit": None,
        "unit": None,
    }
    assert failure.recipe["name"] == "Satay bowl"
    [recommendation] = await user_rows(Recommendation, db_user)
    assert recommendation.attempts == 2


async def test_three_failures_drop_the_request_and_show_nothing(
    db_user, generator
) -> None:
    generator(_PEANUT, _PEANUT, _PEANUT)

    result = await run(db_user, [peanut_allergy()])

    assert result.message == _SAFETY.no_suitable_meal_text
    assert result.recipe is None and result.recommendation_id is None
    assert result.attempts == _SAFETY.max_recipe_attempts
    assert await user_rows(Recommendation, db_user) == []
    failures = sorted(await user_rows(CheckFailure, db_user), key=lambda f: f.attempt)
    assert [(f.attempt, f.outcome) for f in failures] == [
        (1, "regenerated"),
        (2, "regenerated"),
        (3, "dropped"),
    ]
    assert all(f.recommendation_id is None for f in failures)


async def test_a_malformed_answer_counts_as_a_failed_attempt(
    db_user, generator, prompts
) -> None:
    generator("malformed", _RICE)

    result = await run(db_user, [])

    assert result.recipe is not None and result.attempts == 2
    assert "malformed" in prompts[1]
    [failure] = await user_rows(CheckFailure, db_user)
    assert failure.failures[0]["rule"] == "malformed"


async def test_a_food_database_failure_shows_no_recipe(db_user, generator) -> None:
    generator(_RICE)

    with patch.object(
        suggest.usda_local, "lookup", side_effect=FoodDbUnavailable("missing")
    ):
        result = await run(db_user, [peanut_allergy()])

    assert result.message == _SAFETY.food_db_unavailable_text
    assert result.recipe is None
    assert await user_rows(Recommendation, db_user) == []


async def test_unreadable_clinical_tables_show_no_recipe(db_user, generator) -> None:
    generator(_RICE)

    with patch.object(suggest, "load_tables", side_effect=TablesUnavailable("bad")):
        result = await run(db_user, [])

    assert result.message == _SAFETY.food_db_unavailable_text and result.recipe is None


async def test_a_pending_allergy_does_not_bind(db_user, generator) -> None:
    pending = hard_entry(
        profile.AllergyValue(allergen_group="peanut"),
        "pending",
        entry_id=str(uuid.uuid4()),
    )
    generator(_PEANUT)

    result = await run(db_user, [pending])

    assert result.recipe is not None and result.attempts == 1


async def test_conflicts_and_unknown_medications_open_review_items_once(
    db_user, generator
) -> None:
    loose = hard_entry(
        profile.NutrientLimitValue(
            nutrient="sodium", amount=800, unit="mg", period="per_meal"
        ),
        entry_id=str(uuid.uuid4()),
    )
    strict = hard_entry(
        profile.NutrientLimitValue(
            nutrient="sodium", amount=400, unit="mg", period="per_meal"
        ),
        entry_id=str(uuid.uuid4()),
    )
    unknown = hard_entry(
        profile.MedicationValue(name="Zorbitrex"), entry_id=str(uuid.uuid4())
    )
    entries = [loose, strict, unknown]
    generator(_RICE, _RICE)

    await run(db_user, entries)
    await run(db_user, entries)

    items = await user_rows(ReviewItem, db_user)
    assert sorted(i.kind for i in items) == ["rule_conflict", "unknown_medication"]
    conflict = next(i for i in items if i.kind == "rule_conflict")
    assert set(conflict.detail["entries"]) == {loose.id, strict.id}
    medication = next(i for i in items if i.kind == "unknown_medication")
    assert medication.subject_id == unknown.id


def test_plan_sampling_is_deterministic_and_follows_the_rate() -> None:
    ids = [str(uuid.UUID(int=n * 7919)) for n in range(1, 2001)]

    assert not any(suggest.plan_sampled(i, 0.0) for i in ids)
    assert all(suggest.plan_sampled(i, 1.0) for i in ids)
    first = [suggest.plan_sampled(i, 0.1) for i in ids]
    assert first == [suggest.plan_sampled(i, 0.1) for i in ids]
    assert 0.05 < sum(first) / len(ids) < 0.15
    # A recipe sampled at a low rate stays sampled at a higher one.
    assert all(suggest.plan_sampled(i, 0.5) for i, hit in zip(ids, first) if hit)


async def test_a_shown_recipe_is_queued_as_a_plan_sample(
    db_user, generator, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(suggest._SAFETY, "plan_sample_rate", 1.0)
    generator(_RICE)

    result = await run(db_user, [])

    items = await user_rows(ReviewItem, db_user)
    assert [(i.kind, i.subject_id, i.decision) for i in items] == [
        ("plan_sample", result.recommendation_id, None)
    ]


async def test_a_dropped_request_is_never_sampled(
    db_user, generator, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(suggest._SAFETY, "plan_sample_rate", 1.0)
    generator(_PEANUT, _PEANUT, _PEANUT)

    await run(db_user, [peanut_allergy()])

    assert await user_rows(ReviewItem, db_user) == []
