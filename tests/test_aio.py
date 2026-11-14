from __future__ import annotations

import asyncio

from backend.agent.aio import resolved


async def test_resolved_returns_the_value() -> None:
    assert await resolved([1, 2]) == [1, 2]
    assert await resolved(None) is None


async def test_resolved_keeps_position_in_gather() -> None:
    async def slow() -> str:
        await asyncio.sleep(0)
        return "x"

    assert await asyncio.gather(slow(), resolved(None), resolved([])) == [
        "x",
        None,
        [],
    ]
