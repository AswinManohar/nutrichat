from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agent import reply_judge
from backend.agent.glide import GlideResponse, GlideUnavailable
from backend.agent.tools.usda_local import FoodDbUnavailable
from backend.config import get_tunables
from backend.safety import profile
from backend.safety.tables import load_tables
from tests.profile_helpers import hard_entry

_MIN = get_tunables().safety.reply_guard_min_probability


def _answer(probability: float) -> GlideResponse:
    return GlideResponse(
        answers={"suggests_avoided_food": {"noul": probability}},
        model="fastino/GLiDE",
        input_tokens=10,
    )


class _Match:
    description = "Fish, salmon, raw"
    match_confidence = 1.0


@pytest.fixture
def entries() -> list[profile.HardEntry]:
    return [hard_entry(profile.AllergyValue(allergen_group="peanut"))]


@pytest.fixture(autouse=True)
def usda():
    with patch.object(reply_judge.usda_local, "lookup", return_value=_Match()):
        yield


@pytest.fixture
def client():
    with patch.object(reply_judge, "_get_client", return_value=MagicMock()) as get:
        yield get


async def test_a_probability_at_the_threshold_is_a_violation(entries, client) -> None:
    ask = AsyncMock(return_value=_answer(_MIN))

    with patch.object(reply_judge.glide, "ask", ask):
        verdict = await reply_judge.guard("Salmon tonight.", entries, load_tables())

    assert verdict.layer == "glide" and verdict.glide_probability == _MIN
    assert verdict.violations and verdict.retry_reason
    state = ask.await_args.args[1]
    assert state == {"reply": "Salmon tonight.", "avoid": "peanut"}


async def test_a_probability_below_the_threshold_passes(entries, client) -> None:
    with patch.object(
        reply_judge.glide, "ask", AsyncMock(return_value=_answer(_MIN - 0.01))
    ):
        verdict = await reply_judge.guard("Salmon tonight.", entries, load_tables())

    assert verdict.violations == [] and verdict.glide_probability == _MIN - 0.01


async def test_glide_down_leaves_layers_one_and_two_standing(entries, client) -> None:
    with patch.object(
        reply_judge.glide, "ask", AsyncMock(side_effect=GlideUnavailable("timeout"))
    ):
        verdict = await reply_judge.guard("Salmon tonight.", entries, load_tables())

    assert verdict.violations == [] and verdict.glide_probability is None


async def test_no_api_key_skips_the_judgment(entries) -> None:
    with (
        patch.object(reply_judge, "_get_client", return_value=None),
        patch.object(reply_judge.glide, "ask", AsyncMock()) as ask,
    ):
        verdict = await reply_judge.guard("Salmon tonight.", entries, load_tables())

    assert verdict.violations == []
    ask.assert_not_awaited()


async def test_a_lexical_violation_never_calls_glide(entries, client) -> None:
    with patch.object(reply_judge.glide, "ask", AsyncMock()) as ask:
        verdict = await reply_judge.guard("Peanut stew.", entries, load_tables())

    assert verdict.layer == "lexical"
    ask.assert_not_awaited()


async def test_no_food_phrase_or_no_constraint_skips_glide(entries, client) -> None:
    with (
        patch.object(reply_judge.usda_local, "lookup", return_value=None),
        patch.object(reply_judge.glide, "ask", AsyncMock()) as ask,
    ):
        await reply_judge.guard("Well done today!", entries, load_tables())
        await reply_judge.guard("Salmon tonight.", [], load_tables())

    ask.assert_not_awaited()


async def test_a_food_database_failure_propagates(entries, client) -> None:
    with (
        patch.object(
            reply_judge.usda_local, "lookup", side_effect=FoodDbUnavailable("gone")
        ),
        pytest.raises(FoodDbUnavailable),
    ):
        await reply_judge.guard("Salmon tonight.", entries, load_tables())
