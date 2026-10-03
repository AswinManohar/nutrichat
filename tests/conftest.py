from __future__ import annotations

import os

# Set dummy env vars before any module-level LLM initialization
os.environ.setdefault("GOOGLE_API_KEY", "dummy-key-for-testing")
# No key -> routing takes the Gemini path, so an exported key can never send
# the suite to the TypeSafe network.
os.environ.pop("TYPESAFE_API_KEY", None)
# True when the operator pointed the suite at a real database. The fallback
# below only exists so imports work; integration tests that would write rows
# skip unless DATABASE_URL was set deliberately.
DATABASE_URL_PRESET = "DATABASE_URL" in os.environ
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://nutrichat:nutrichat@127.0.0.1:5411/nutrichat"
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")


# Imports below must stay after the env setup above: backend modules read the
# environment at import time.
from collections.abc import Callable  # noqa: E402
from types import ModuleType  # noqa: E402
from typing import Any  # noqa: E402
from unittest.mock import AsyncMock, MagicMock  # noqa: E402

import pytest  # noqa: E402
from fastapi import APIRouter, FastAPI  # noqa: E402

from backend.auth.supabase import get_current_user_id  # noqa: E402
from tests.auth_helpers import DEFAULT_TEST_USER, with_header_auth  # noqa: E402

TEST_USER_ID = DEFAULT_TEST_USER
"""User id every shared auth override resolves to unless told otherwise."""

_UNSET: Any = object()


@pytest.fixture
def app_factory() -> Callable[..., FastAPI]:
    """Return a builder for a FastAPI app wrapping the given routers.

    The builder signature is ``(*routers, user_id=TEST_USER_ID,
    header_auth=False) -> FastAPI``:

    * ``user_id`` (str): ``get_current_user_id`` is overridden to return it.
    * ``user_id=None``: no override, so the real 401 path is exercised.
    * ``header_auth=True``: the user comes from the ``X-Debug-User-Id`` header
      (default ``TEST_USER_ID``) via ``tests.auth_helpers.with_header_auth``;
      ``user_id`` is ignored.

    Returns:
        The builder callable.
    """

    def build(
        *routers: APIRouter,
        user_id: str | None = TEST_USER_ID,
        header_auth: bool = False,
    ) -> FastAPI:
        app = FastAPI()
        for router in routers:
            app.include_router(router)
        if header_auth:
            with_header_auth(app)
        elif user_id is not None:
            app.dependency_overrides[get_current_user_id] = lambda: user_id
        return app

    return build


@pytest.fixture
def make_session() -> Callable[..., MagicMock]:
    """Return a builder for a mocked async DB session.

    The builder signature is ``(*, get_result=..., execute_row=...) ->
    MagicMock``. The session is an async context manager whose ``execute``,
    ``commit`` and ``refresh`` are ``AsyncMock``. ``get_result`` (when given)
    becomes the return value of ``await session.get(...)``; ``execute_row``
    (when given) is returned by ``(await session.execute(...)).fetchone()``.
    Tests needing richer behaviour assign attributes on the returned session.

    Returns:
        The builder callable.
    """

    def build(*, get_result: Any = _UNSET, execute_row: Any = _UNSET) -> MagicMock:
        session = MagicMock()
        session.execute = AsyncMock()
        session.commit = AsyncMock()
        session.refresh = AsyncMock()
        if execute_row is not _UNSET:
            result = MagicMock()
            result.fetchone.return_value = execute_row
            session.execute = AsyncMock(return_value=result)
        if get_result is not _UNSET:
            session.get = AsyncMock(return_value=get_result)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        return session

    return build


@pytest.fixture
def mock_session_factory() -> Callable[[MagicMock], MagicMock]:
    """Return a wrapper turning a session mock into a ``get_session()`` value.

    ``get_session()`` returns a factory and ``factory()`` returns an async
    context manager yielding the session. Given a session, the wrapper makes
    it an async context manager and returns that factory, ready for
    ``patch("pkg.module.get_session", return_value=factory)``.

    Returns:
        The wrapper callable.
    """

    def wrap(session: MagicMock) -> MagicMock:
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        return MagicMock(return_value=session)

    return wrap


@pytest.fixture
def patch_get_session(
    monkeypatch: pytest.MonkeyPatch,
    mock_session_factory: Callable[[MagicMock], MagicMock],
) -> Callable[[ModuleType, MagicMock], MagicMock]:
    """Return a helper that patches ``module.get_session`` to yield a session.

    The helper signature is ``(module, session) -> MagicMock`` and returns the
    session. The patch lasts for the rest of the test.

    Returns:
        The helper callable.
    """

    def patch_it(module: ModuleType, session: MagicMock) -> MagicMock:
        factory = mock_session_factory(session)
        monkeypatch.setattr(module, "get_session", MagicMock(return_value=factory))
        return session

    return patch_it


@pytest.fixture(autouse=True)
def _no_background_micro_estimates(monkeypatch: pytest.MonkeyPatch) -> None:
    """Spec 008: never let a test fire a real background micro-estimate call.

    Estimating a food schedules a Gemini call off the card's critical path;
    stub it to "no micros" so no test touches the network or leaves tasks
    pending. Tests of that machinery patch ``_run_micro_estimate`` themselves.
    """
    from backend.agent.tools import usda

    async def _none(food_name: str) -> dict[str, float]:
        return {}

    monkeypatch.setattr(usda, "_run_micro_estimate", _none)
    usda._micro_tasks.clear()
