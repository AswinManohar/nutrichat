from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from redis.exceptions import RedisError

from backend.agent.context import _fetch_staples
from backend.agent.tools.history import get_staple_foods
from backend.db.redis_client import get_cached_staples, set_cached_staples


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttl: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value
        if ex is not None:
            self.ttl[key] = ex


class _BrokenRedis:
    async def get(self, key: str) -> str | None:
        raise RedisError("down")

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        raise RedisError("down")


def _session_returning(rows: list[MagicMock]) -> MagicMock:
    session = MagicMock()
    session.execute = AsyncMock(return_value=rows)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=session)


def _row(meal_type: str, food_name: str) -> MagicMock:
    return MagicMock(meal_type=meal_type, food_name=food_name)


async def test_get_staple_foods_groups_orders_and_truncates() -> None:
    rows = [
        _row("dinner", "Dal"),
        _row("breakfast", "Oats"),
        _row("breakfast", "B" * 80),
        _row("brunch", "Eggs"),
    ]
    factory = _session_returning(rows)

    with patch("backend.agent.tools.history.get_session", return_value=factory):
        staples = await get_staple_foods("user-1", days=30, min_count=3)

    assert list(staples) == ["breakfast", "dinner", "brunch"]
    assert staples["breakfast"] == ["Oats", "B" * 40]
    params = factory.return_value.execute.call_args.args[1]
    assert params["min_count"] == 3
    assert (params["date_to"] - params["date_from"]).days == 29


async def test_staples_cache_round_trip_sets_ttl() -> None:
    client = _FakeRedis()
    with patch("backend.db.redis_client.get_redis", return_value=client):
        assert await get_cached_staples("user-1") is None
        await set_cached_staples("user-1", {"breakfast": ["Oats"]})
        assert await get_cached_staples("user-1") == {"breakfast": ["Oats"]}

    assert client.ttl["staples:user-1"] > 0


async def test_staples_cache_treats_outage_and_garbage_as_miss() -> None:
    with patch("backend.db.redis_client.get_redis", return_value=_BrokenRedis()):
        assert await get_cached_staples("user-1") is None
        await set_cached_staples("user-1", {"breakfast": ["Oats"]})  # no raise

    client = _FakeRedis()
    client.store["staples:user-1"] = "not json"
    with patch("backend.db.redis_client.get_redis", return_value=client):
        assert await get_cached_staples("user-1") is None


async def test_fetch_staples_uses_cache_and_skips_database_on_hit() -> None:
    query = AsyncMock(return_value={"lunch": ["Rice"]})
    client = _FakeRedis()
    with (
        patch("backend.db.redis_client.get_redis", return_value=client),
        patch("backend.agent.context.get_staple_foods", query),
    ):
        first = await _fetch_staples("user-1")
        second = await _fetch_staples("user-1")

    assert first == second == {"lunch": ["Rice"]}
    query.assert_awaited_once()


async def test_fetch_staples_caches_an_empty_result() -> None:
    query = AsyncMock(return_value={})
    with (
        patch("backend.db.redis_client.get_redis", return_value=_FakeRedis()),
        patch("backend.agent.context.get_staple_foods", query),
    ):
        await _fetch_staples("user-1")
        await _fetch_staples("user-1")

    query.assert_awaited_once()


async def test_fetch_staples_degrades_to_empty_when_everything_is_down() -> None:
    with (
        patch("backend.db.redis_client.get_redis", return_value=_BrokenRedis()),
        patch(
            "backend.agent.context.get_staple_foods",
            AsyncMock(side_effect=RuntimeError("db down")),
        ),
    ):
        assert await _fetch_staples("user-1") == {}


async def test_get_staple_foods_against_live_postgres() -> None:
    """Requires DATABASE_URL with migrations applied."""
    from tests.conftest import DATABASE_URL_PRESET

    if not DATABASE_URL_PRESET:
        pytest.skip("DATABASE_URL not set")

    import uuid
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import delete

    from backend.db.models import MealLog, UserGoal
    from backend.db.session import dispose_engine, get_session

    user_id = str(uuid.uuid4())
    noon = datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0)

    def meal(days_ago: int, meal_type: str, foods: list[str], **kw) -> MealLog:
        return MealLog(
            user_id=user_id,
            logged_at=noon - timedelta(days=days_ago),
            meal_type=meal_type,
            kcal=100,
            protein_g=1,
            carbs_g=1,
            fat_g=1,
            fiber_g=1,
            entities=[{"food_name": f, "kcal": 50} for f in foods],
            **kw,
        )

    session_factory = get_session()
    async with session_factory() as session:
        session.add(UserGoal(user_id=user_id, dietary_prefs={}))
        await session.flush()
        session.add_all(
            [
                meal(1, "breakfast", ["Oats", "Banana"]),
                meal(2, "breakfast", ["Oats", "Banana"]),
                meal(3, "breakfast", ["Oats"]),
                # Same food twice in one meal counts as one meal.
                meal(4, "dinner", ["Dal", "Dal"]),
                meal(5, "dinner", ["Dal"]),
                # Outside the window, and a deleted meal: neither counts.
                meal(45, "breakfast", ["Banana"]),
                meal(6, "breakfast", ["Banana"], deleted_at=noon),
            ]
        )
        await session.commit()
    try:
        staples = await get_staple_foods(user_id, days=30, min_count=3)
        assert staples == {"breakfast": ["Oats"]}

        staples = await get_staple_foods(user_id, days=30, min_count=2)
        assert staples == {"breakfast": ["Oats", "Banana"], "dinner": ["Dal"]}
    finally:
        async with session_factory() as session:
            await session.execute(delete(UserGoal).where(UserGoal.user_id == user_id))
            await session.commit()
        await dispose_engine()
