"""Tests for the resolve-ingredient service (spec 006, US4, T051)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.agent.tools import replace_ingredient as svc
from backend.agent.tools.replace_ingredient import (
    QuotaExhausted,
    RephraseRequired,
    ReplacementFood,
    ReplacementResult,
    ReplacingIngredient,
    ResolveUnavailable,
)
from backend.agent.tools.usda import USDAResult
from backend.api import my_meals
from backend.quota import UPGRADE_MSG

_REPLACING = ReplacingIngredient(food_name="rice white cooked", qty_g=150, unit="cup")


def _food(qty: float = 200, unit: str = "g", stated: bool = False) -> ReplacementFood:
    return ReplacementFood(
        food_name="rice brown cooked", qty_g=qty, unit=unit, amount_stated=stated
    )


def _usda(qty_g: float, estimated: bool = False) -> USDAResult:
    return USDAResult(
        fdc_id=-1 if estimated else 123,
        food_name="rice brown cooked",
        qty_g=qty_g,
        match_confidence=0.9,
        candidates=[],
        kcal=100.0,
        nutrients={},
        source="LLM_ESTIMATE" if estimated else "USDA",
        estimated=estimated,
    )


async def _run(
    foods: list[ReplacementFood],
    *,
    mode: str = "swap",
    replacing: ReplacingIngredient | None = _REPLACING,
    credit: bool = True,
    estimated: bool = False,
    llm_side_effect: BaseException | None = None,
) -> tuple[object, AsyncMock, AsyncMock]:
    llm = AsyncMock(return_value=ReplacementResult(foods=foods))
    if llm_side_effect is not None:
        llm.side_effect = llm_side_effect

    async def _lookup(entities: list) -> list[USDAResult]:
        return [_usda(entities[0].qty_g, estimated)]

    lookup = AsyncMock(side_effect=_lookup)
    consume = AsyncMock(return_value=credit)
    with (
        patch.object(svc, "_replace_llm", SimpleNamespace(ainvoke=llm)),
        patch.object(svc, "usda_lookup_batch", lookup),
    ):
        result = await svc.resolve_ingredient(
            "user-1",
            mode,  # type: ignore[arg-type]
            "brown",
            "Chicken biryani",
            replacing if mode == "swap" else None,
            consume_credit=consume,
        )
    return result, llm, lookup


# ---- Service cases -------------------------------------------------------


async def test_one_food_returns_item() -> None:
    result, llm, _ = await _run([_food()])
    assert result.item.food_name == "rice brown cooked"
    llm.assert_awaited_once()
    messages = llm.await_args.args[0]
    assert len(messages) == 2
    assert "mode: swap" in messages[1].content


async def test_swap_without_amount_keeps_old_grams_and_unit() -> None:
    result, _, lookup = await _run([_food(qty=200, unit="g", stated=False)])
    assert result.kept_previous_qty is True
    assert result.amount_stated is False
    assert result.unit == "cup"
    assert result.item.qty_g == 150
    entity = lookup.await_args.args[0][0]
    assert (entity.qty_g, entity.unit) == (150, "cup")


async def test_swap_with_amount_uses_model_grams() -> None:
    result, _, _ = await _run([_food(qty=195, unit="cup", stated=True)])
    assert result.kept_previous_qty is False
    assert result.amount_stated is True
    assert result.item.qty_g == 195


async def test_add_without_amount_uses_model_grams() -> None:
    result, _, _ = await _run(
        [_food(qty=118, unit="serving", stated=False)], mode="add"
    )
    assert result.kept_previous_qty is False
    assert result.item.qty_g == 118
    assert result.unit == "serving"


async def test_no_foods_requires_rephrase() -> None:
    with pytest.raises(RephraseRequired):
        await _run([])


async def test_two_foods_requires_rephrase() -> None:
    with pytest.raises(RephraseRequired):
        await _run([_food(), _food()])


async def test_credit_refused_skips_llm() -> None:
    llm = AsyncMock()
    consume = AsyncMock(return_value=False)
    with patch.object(svc, "_replace_llm", SimpleNamespace(ainvoke=llm)):
        with pytest.raises(QuotaExhausted):
            await svc.resolve_ingredient(
                "user-1", "add", "ghee", "Dal", None, consume_credit=consume
            )
    llm.assert_not_called()


async def test_timeout_is_unavailable() -> None:
    with pytest.raises(ResolveUnavailable):
        await _run([_food()], llm_side_effect=TimeoutError())


async def test_estimated_lookup_passes_through() -> None:
    result, _, _ = await _run([_food()], estimated=True)
    assert result.item.estimated is True
    assert result.item.fdc_id == -1


# ---- Route cases ---------------------------------------------------------


_REPLACING_BODY = {"food_name": "rice white cooked", "qty_g": 150, "unit": "cup"}


@pytest.fixture
def route_client(app_factory: Callable[..., FastAPI]) -> Iterator[TestClient]:
    """Client for the my-meals router with the Redis rate limiter bypassed."""
    allowed = SimpleNamespace(allowed=True, remaining=20, retry_after_s=0)
    with patch("backend.ratelimit.check_rate_limit", AsyncMock(return_value=allowed)):
        yield TestClient(app_factory(my_meals.router))


def _body(**overrides: object) -> dict:
    body: dict = {
        "mode": "swap",
        "text": "brown",
        "meal_name": "Chicken biryani",
        "replacing": _REPLACING_BODY,
    }
    body.update(overrides)
    return {k: v for k, v in body.items() if v is not None}


def _post(
    client: TestClient,
    body: dict,
    *,
    foods: list[ReplacementFood] | None = None,
    credit: bool = True,
    llm_side_effect: BaseException | None = None,
):
    llm = AsyncMock(
        return_value=ReplacementResult(foods=[_food()] if foods is None else foods)
    )
    if llm_side_effect is not None:
        llm.side_effect = llm_side_effect

    async def _lookup(entities: list) -> list[USDAResult]:
        return [_usda(entities[0].qty_g)]

    consume = AsyncMock(return_value=credit)

    def _resolve(*args: object, **kwargs: object):
        # The service's consume_credit default is bound at def time, so inject it.
        return svc.resolve_ingredient(*args, consume_credit=consume, **kwargs)

    with (
        patch.object(svc, "_replace_llm", SimpleNamespace(ainvoke=llm)),
        patch.object(svc, "usda_lookup_batch", AsyncMock(side_effect=_lookup)),
        patch.object(my_meals, "resolve_ingredient", _resolve),
    ):
        return client.post("/my-meals/resolve-ingredient", json=body), llm


def test_route_happy_swap_keeps_grams(route_client: TestClient) -> None:
    resp, _ = _post(route_client, _body())
    assert resp.status_code == 200
    data = resp.json()
    assert data["unit"] == "cup"
    assert data["amount_stated"] is False
    assert data["kept_previous_qty"] is True
    assert data["item"]["qty_g"] == 150
    assert set(data) == {"item", "unit", "amount_stated", "kept_previous_qty"}


def test_route_happy_add(route_client: TestClient) -> None:
    resp, _ = _post(route_client, _body(mode="add", replacing=None))
    assert resp.status_code == 200
    assert resp.json()["item"]["qty_g"] == 200
    assert resp.json()["kept_previous_qty"] is False


def test_route_402_quota_exhausted(route_client: TestClient) -> None:
    resp, llm = _post(route_client, _body(), credit=False)
    assert resp.status_code == 402
    assert resp.json() == {
        "detail": {"code": "quota_exhausted", "message": UPGRADE_MSG}
    }
    llm.assert_not_awaited()


def test_route_422_rephrase(route_client: TestClient) -> None:
    resp, _ = _post(route_client, _body(), foods=[])
    assert resp.status_code == 422
    assert resp.json() == {
        "detail": {
            "code": "rephrase",
            "message": "Describe one food, e.g. 'brown rice' or '1 tbsp ghee'.",
        }
    }


def test_route_422_swap_requires_replacing(route_client: TestClient) -> None:
    resp, _ = _post(route_client, _body(replacing=None))
    assert resp.status_code == 422
    assert isinstance(resp.json()["detail"], list)


def test_route_422_add_rejects_replacing(route_client: TestClient) -> None:
    resp, _ = _post(route_client, _body(mode="add"))
    assert resp.status_code == 422
    assert isinstance(resp.json()["detail"], list)


def test_route_503_unavailable(route_client: TestClient) -> None:
    resp, _ = _post(route_client, _body(), llm_side_effect=TimeoutError())
    assert resp.status_code == 503
    assert resp.json() == {"detail": {"code": "resolve_unavailable"}}
