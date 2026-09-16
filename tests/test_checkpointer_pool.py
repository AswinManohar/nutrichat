"""Tests for checkpointer pool sizing (no live DB needed)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from backend.db import checkpointer as cp


@pytest.fixture
def pool_kwargs():
    """Capture kwargs passed to AsyncConnectionPool without opening one."""
    captured = {}

    class FakePool:
        def __init__(self, *args, **kwargs):
            captured.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return None

    fake_saver = AsyncMock()
    fake_saver.setup = AsyncMock()

    with (
        patch.object(cp, "AsyncConnectionPool", FakePool),
        patch.object(cp, "AsyncPostgresSaver", lambda pool: fake_saver),
    ):
        yield captured


@pytest.mark.asyncio
async def test_pool_size_defaults_to_eight(pool_kwargs, monkeypatch):
    """With no env override, the pool defaults to max_size=8, timeout=5.0."""
    monkeypatch.delenv("CHECKPOINTER_POOL_SIZE", raising=False)
    async with cp.pooled_checkpointer():
        pass
    assert pool_kwargs["max_size"] == 8
    assert pool_kwargs["timeout"] == 5.0


@pytest.mark.asyncio
async def test_pool_size_from_env(pool_kwargs, monkeypatch):
    """CHECKPOINTER_POOL_SIZE overrides the default max_size."""
    monkeypatch.setenv("CHECKPOINTER_POOL_SIZE", "3")
    async with cp.pooled_checkpointer():
        pass
    assert pool_kwargs["max_size"] == 3
