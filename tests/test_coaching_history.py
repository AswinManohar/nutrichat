from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from redis.exceptions import RedisError

from backend.db import redis_client
from backend.db.redis_client import (
    CoachingTurn,
    append_coaching_turns,
    get_coaching_history,
)


class FakeRedis:
    """In-memory stand-in covering the list ops the history store uses."""

    def __init__(self) -> None:
        self.lists: dict[str, list[str]] = {}
        self.ttls: dict[str, int] = {}

    def pipeline(self, transaction: bool = True) -> FakeRedis:
        return self

    async def __aenter__(self) -> FakeRedis:
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    def rpush(self, key: str, *values: str) -> None:
        self.lists.setdefault(key, []).extend(values)

    def ltrim(self, key: str, start: int, end: int) -> None:
        items = self.lists.get(key, [])
        # Redis semantics: negative indices count from the tail, inclusive end.
        n = len(items)
        start = max(0, start + n) if start < 0 else start
        end = end + n if end < 0 else end
        self.lists[key] = items[start : end + 1]

    def expire(self, key: str, seconds: int) -> None:
        self.ttls[key] = seconds

    async def execute(self) -> list:
        return []

    async def lrange(self, key: str, start: int, end: int) -> list[str]:
        items = self.lists.get(key, [])
        n = len(items)
        end = end + n if end < 0 else end
        return items[start : end + 1]


class BrokenRedis:
    def pipeline(self, transaction: bool = True) -> BrokenRedis:
        return self

    async def __aenter__(self) -> BrokenRedis:
        raise RedisError("down")

    async def __aexit__(self, *exc) -> bool:
        return False

    async def lrange(self, key: str, start: int, end: int) -> list[str]:
        raise RedisError("down")


@pytest.fixture
def fake_redis():
    client = FakeRedis()
    with patch("backend.db.redis_client.get_redis", return_value=client):
        yield client


async def test_append_then_get_returns_turns_in_order(fake_redis):
    await append_coaching_turns(
        "user-1",
        [
            CoachingTurn(role="user", content="how much protein today?"),
            CoachingTurn(role="assistant", content="95g so far."),
        ],
    )
    await append_coaching_turns(
        "user-1",
        [
            CoachingTurn(role="user", content="and yesterday?"),
            CoachingTurn(role="assistant", content="120g."),
        ],
    )

    history = await get_coaching_history("user-1")

    assert [t.content for t in history] == [
        "how much protein today?",
        "95g so far.",
        "and yesterday?",
        "120g.",
    ]
    assert [t.role for t in history] == ["user", "assistant", "user", "assistant"]


async def test_append_caps_history_to_configured_turns(fake_redis):
    cap = redis_client._COACHING_HISTORY_TURNS
    for i in range(cap + 3):
        await append_coaching_turns(
            "user-1",
            [
                CoachingTurn(role="user", content=f"q{i}"),
                CoachingTurn(role="assistant", content=f"a{i}"),
            ],
        )

    history = await get_coaching_history("user-1")

    assert len(history) == cap * 2
    assert history[0].content == "q3"
    assert history[-1].content == f"a{cap + 2}"


async def test_append_sets_ttl_on_history_key(fake_redis):
    await append_coaching_turns("user-1", [CoachingTurn(role="user", content="hi")])

    assert fake_redis.ttls["coach_history:user-1"] == (
        redis_client._COACHING_HISTORY_TTL_S
    )


async def test_get_history_empty_when_nothing_stored(fake_redis):
    assert await get_coaching_history("nobody") == []


async def test_get_history_skips_malformed_entries(fake_redis):
    fake_redis.lists["coach_history:user-1"] = [
        json.dumps({"role": "user", "content": "ok"}),
        "not json",
        json.dumps({"role": "bogus", "content": "x"}),
    ]

    history = await get_coaching_history("user-1")

    assert [t.content for t in history] == ["ok"]


async def test_history_store_is_best_effort_when_redis_down():
    with patch("backend.db.redis_client.get_redis", return_value=BrokenRedis()):
        await append_coaching_turns("user-1", [CoachingTurn(role="user", content="hi")])
        assert await get_coaching_history("user-1") == []
