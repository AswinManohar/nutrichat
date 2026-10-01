"""Regression tests for the T009/T010 pending-resolution wiring (spec 003).

A pending confirmation card shows via `GET /meals/pending`. After a client
logs it locally through `POST /meals/log-items` with the card's
`conversation_id`, the paused LangGraph thread must be marked resolved so
`GET /meals/pending` no longer returns it (research R4). Repeating the same
`client_request_id` must stay idempotent and not re-raise/duplicate the
resolution.

Uses a real `InMemorySaver` checkpointer and the real compiled graph (not a
mock) so this exercises actual LangGraph state semantics, while
`persist_meal` itself is mocked to avoid needing a live database.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from backend.agent.graph import build_graph
from backend.agent.tools.meals import MealLogResult
from backend.api import meals

_USER = "user-1"
_CONVO = "convo-1"


def _item(name: str = "toast", fdc_id: int = 172687) -> dict:
    return {
        "food_name": name,
        "qty_g": 28,
        "target_qty_g": 28,
        "kcal": 82.0,
        "protein_g": 2.5,
        "carbs_g": 15.0,
        "fat_g": 1.0,
        "fiber_g": 1.0,
        "sugar_g": 0.0,
        "sat_fat_g": 0.0,
        "fdc_id": fdc_id,
        "confidence": 1.0,
        "candidates": [],
        "source": "usda_local",
        "estimated": False,
        "source_dish": None,
        "nutrients": {},
    }


def _result(meal_id: str = "m1") -> MealLogResult:
    return MealLogResult(
        meal_id=meal_id,
        meal_type="breakfast",
        n_items=1,
        kcal=82.0,
        protein_g=2.5,
        carbs_g=15.0,
        fat_g=1.0,
        fiber_g=1.0,
        message="Logged",
    )


async def _seed_pending_card(checkpointer, user_id: str, thread_id: str) -> None:
    """Seed a paused card in the checkpointer, as `present_node` would."""
    graph = build_graph(checkpointer)
    config = {"configurable": {"thread_id": thread_id, "user_id": user_id}}
    await graph.aupdate_state(
        config,
        {
            "usda_results": [
                {
                    "fdc_id": 2345,
                    "food_name": "Shrimp toast",
                    "qty_g": 28.0,
                    "match_confidence": 0.6,
                    "kcal": 78.0,
                    "protein_g": 3.0,
                    "carbs_g": 8.0,
                    "fat_g": 3.5,
                    "fiber_g": 0.3,
                }
            ],
            "messages": [],
        },
        as_node="present",
    )


@pytest.fixture
def checkpointer() -> InMemorySaver:
    return InMemorySaver()


@pytest.fixture
def client(checkpointer: InMemorySaver, app_factory) -> TestClient:
    app = app_factory(meals.router, user_id=_USER)
    app.state.checkpointer = checkpointer
    return TestClient(app)


def test_pending_card_resolved_after_log_items(
    client: TestClient, checkpointer: InMemorySaver
) -> None:
    import asyncio

    asyncio.run(_seed_pending_card(checkpointer, _USER, f"{_USER}:{_CONVO}"))

    # Card is visible before logging.
    resp = client.get(f"/meals/pending?conversation_id={_CONVO}")
    assert resp.status_code == 200
    assert resp.json()["paused"] is True

    # Log it via log-items with the same conversation_id.
    with patch("backend.api.meals.persist_meal", AsyncMock(return_value=_result())):
        resp = client.post(
            "/meals/log-items",
            json={
                "meal_type": "breakfast",
                "conversation_id": _CONVO,
                "items": [_item()],
            },
        )
    assert resp.status_code == 200

    # Pending card is gone.
    resp = client.get(f"/meals/pending?conversation_id={_CONVO}")
    assert resp.status_code == 200
    assert resp.json() == {"paused": False}


def test_log_items_without_conversation_id_does_not_touch_pending(
    client: TestClient, checkpointer: InMemorySaver
) -> None:
    import asyncio

    asyncio.run(_seed_pending_card(checkpointer, _USER, f"{_USER}:{_CONVO}"))

    with patch("backend.api.meals.persist_meal", AsyncMock(return_value=_result())):
        resp = client.post(
            "/meals/log-items",
            json={"meal_type": "breakfast", "items": [_item()]},
        )
    assert resp.status_code == 200

    # No conversation_id was sent, so the unrelated pending card survives.
    resp = client.get(f"/meals/pending?conversation_id={_CONVO}")
    assert resp.json()["paused"] is True


def test_replayed_client_request_id_stays_idempotent_and_still_resolves(
    client: TestClient, checkpointer: InMemorySaver
) -> None:
    import asyncio

    asyncio.run(_seed_pending_card(checkpointer, _USER, f"{_USER}:{_CONVO}"))

    logged = AsyncMock(return_value=_result())
    with (
        patch("backend.api.meals.persist_meal", logged),
        patch(
            "backend.api.meals._find_by_client_request_id",
            AsyncMock(return_value=None),
        ),
    ):
        resp1 = client.post(
            "/meals/log-items",
            json={
                "meal_type": "breakfast",
                "conversation_id": _CONVO,
                "client_request_id": "req-1",
                "items": [_item()],
            },
        )
    assert resp1.status_code == 200
    logged.assert_awaited_once()

    # Replay: persist_meal must not be called again, dedup response returned,
    # pending resolution still applied (already resolved -> no-op).
    with (
        patch("backend.api.meals.persist_meal", logged),
        patch(
            "backend.api.meals._find_by_client_request_id",
            AsyncMock(
                return_value=type(
                    "Row",
                    (),
                    {
                        "meal_id": "m1",
                        "meal_type": "breakfast",
                        "entities": [],
                        "kcal": 82.0,
                        "protein_g": 2.5,
                        "carbs_g": 15.0,
                        "fat_g": 1.0,
                        "fiber_g": 1.0,
                    },
                )()
            ),
        ),
    ):
        resp2 = client.post(
            "/meals/log-items",
            json={
                "meal_type": "breakfast",
                "conversation_id": _CONVO,
                "client_request_id": "req-1",
                "items": [_item()],
            },
        )
    assert resp2.status_code == 200
    assert resp2.json()["deduplicated"] is True
    logged.assert_awaited_once()  # still only the first call

    resp = client.get(f"/meals/pending?conversation_id={_CONVO}")
    assert resp.json() == {"paused": False}


# ---------------------------------------------------------------------------
# T013: `correction` field on log-items items
# ---------------------------------------------------------------------------


def test_correction_mismatched_to_fdc_id_is_422(client: TestClient) -> None:
    item = _item(name="Bread, white, toasted", fdc_id=172687)
    item["correction"] = {
        "original_phrase": "toast",
        "from_fdc_id": 2345,
        "from_name": "Shrimp toast",
        "to_fdc_id": 999999,  # does not match item's fdc_id (172687)
        "method": "search",
        "query": "white bread toasted",
    }
    resp = client.post(
        "/meals/log-items",
        json={"meal_type": "breakfast", "items": [item]},
    )
    assert resp.status_code == 422


def test_valid_correction_is_passed_through_to_persist_meal(
    client: TestClient,
) -> None:
    item = _item(name="Bread, white, toasted", fdc_id=172687)
    item["correction"] = {
        "original_phrase": "toast",
        "from_fdc_id": 2345,
        "from_name": "Shrimp toast",
        "to_fdc_id": 172687,
        "method": "search",
        "query": "white bread toasted",
    }
    persist = AsyncMock(return_value=_result())
    with patch("backend.api.meals.persist_meal", persist):
        resp = client.post(
            "/meals/log-items",
            json={"meal_type": "breakfast", "items": [item]},
        )
    assert resp.status_code == 200
    persist.assert_awaited_once()
    kwargs = persist.await_args.kwargs
    assert kwargs["corrections"] == [
        {
            "original_phrase": "toast",
            "from_fdc_id": 2345,
            "from_name": "Shrimp toast",
            "to_fdc_id": 172687,
            "method": "search",
            "query": "white bread toasted",
        }
    ]


def test_items_without_correction_pass_none(client: TestClient) -> None:
    persist = AsyncMock(return_value=_result())
    with patch("backend.api.meals.persist_meal", persist):
        resp = client.post(
            "/meals/log-items",
            json={"meal_type": "breakfast", "items": [_item()]},
        )
    assert resp.status_code == 200
    assert persist.await_args.kwargs["corrections"] == [None]


def test_replayed_client_request_id_does_not_call_persist_meal_again(
    client: TestClient,
) -> None:
    item = _item(name="Bread, white, toasted", fdc_id=172687)
    item["correction"] = {
        "original_phrase": "toast",
        "from_fdc_id": 2345,
        "from_name": "Shrimp toast",
        "to_fdc_id": 172687,
        "method": "search",
        "query": "white bread toasted",
    }
    persist = AsyncMock(return_value=_result())
    with (
        patch("backend.api.meals.persist_meal", persist),
        patch(
            "backend.api.meals._find_by_client_request_id",
            AsyncMock(return_value=None),
        ),
    ):
        resp1 = client.post(
            "/meals/log-items",
            json={
                "meal_type": "breakfast",
                "client_request_id": "req-corr-1",
                "items": [item],
            },
        )
    assert resp1.status_code == 200
    persist.assert_awaited_once()

    with (
        patch("backend.api.meals.persist_meal", persist),
        patch(
            "backend.api.meals._find_by_client_request_id",
            AsyncMock(
                return_value=type(
                    "Row",
                    (),
                    {
                        "meal_id": "m1",
                        "meal_type": "breakfast",
                        "entities": [],
                        "kcal": 82.0,
                        "protein_g": 2.5,
                        "carbs_g": 15.0,
                        "fat_g": 1.0,
                        "fiber_g": 1.0,
                    },
                )()
            ),
        ),
    ):
        resp2 = client.post(
            "/meals/log-items",
            json={
                "meal_type": "breakfast",
                "client_request_id": "req-corr-1",
                "items": [item],
            },
        )
    assert resp2.status_code == 200
    assert resp2.json()["deduplicated"] is True
    # persist_meal (and therefore any food_correction insert) is not called
    # again on replay — no new row is written.
    persist.assert_awaited_once()


def test_food_correction_fk_cascades_on_meal_delete() -> None:
    """Schema-level check: no local Postgres available in this sandbox, so
    this asserts the ON DELETE CASCADE is declared on the model/migration
    rather than exercising a live cascade delete."""
    from backend.db.models import FoodCorrection

    fk = next(iter(FoodCorrection.__table__.c.meal_log_id.foreign_keys))
    assert fk.column.table.name == "meal_log"
    assert fk.ondelete == "CASCADE"


# ---------------------------------------------------------------------------
# Extra requirement: `resolved` must reset to False on a NEW user turn in a
# reused thread, otherwise a second card in that thread would never show as
# pending (get_pending_card checks `resolved` and would see the stale True
# left over from the first card's log-items resolution).
# ---------------------------------------------------------------------------


def test_resolved_flag_reset_on_fresh_meal_logging_turn() -> None:
    """A brand-new (unpaused) meal-logging turn must seed `resolved: False`
    in the initial graph state. Without this, a thread reused after an
    earlier card was resolved via POST /meals/log-items (T008/T009) would
    leave `resolved: True` in the checkpoint, and get_pending_card would
    then treat this turn's NEW card as already handled the moment it
    pauses again."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    from backend.agent.orchestrator import handle_message
    from backend.agent.system_one import RoutingJudgment

    def _log_judgment() -> RoutingJudgment:
        return RoutingJudgment(
            intent="log_meal",
            certainty=0.99,
            raw_choice="log_meal",
            reports_food=0.99,
            needs_guidance=0.01,
            latency_ms=1.0,
        )

    async def _run() -> None:
        graph = MagicMock()
        paused_state = MagicMock(next=())
        resumed_state = MagicMock(next=("present",))
        graph.aget_state = AsyncMock(side_effect=[paused_state, resumed_state])
        graph.aupdate_state = AsyncMock()
        graph.ainvoke = AsyncMock(
            return_value={
                "messages": [],
                "usda_results": [],
            }
        )
        with (
            patch("backend.agent.orchestrator.build_graph", return_value=graph),
            patch(
                "backend.agent.orchestrator.judge_message",
                AsyncMock(return_value=(_log_judgment(), None)),
            ),
            patch(
                "backend.agent.orchestrator.consume_llm_credit",
                AsyncMock(return_value=True),
            ),
        ):
            await handle_message(_USER, "2 eggs and toast", _CONVO, None)

        graph.ainvoke.assert_awaited_once()
        initial_state = graph.ainvoke.await_args.args[0]
        assert initial_state["resolved"] is False

    asyncio.run(_run())
