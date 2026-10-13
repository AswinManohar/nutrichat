from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from backend.agent import orchestrator
from backend.agent.coaching import CoachingResult, QueryParsed
from backend.agent.orchestrator import _IntentResult, _route, handle_message
from backend.agent.system_one import RoutingJudgment
from backend.config import get_tunables
from backend.db.redis_client import CoachingTurn


@pytest.fixture(autouse=True)
def _mock_fact_task():
    """Keep extract_and_store_facts.delay() off the real Redis broker."""
    with patch("backend.agent.orchestrator.extract_and_store_facts") as task_mock:
        yield task_mock


@pytest.fixture(autouse=True)
def _no_response_store():
    """Keep coaching_response persistence off the database in every test."""
    with patch(
        "backend.agent.orchestrator.save_coaching_response",
        new_callable=AsyncMock,
        return_value=None,
    ):
        yield


@pytest.fixture(autouse=True)
def _mock_history_store():
    """Keep the coaching history writes off the real Redis."""
    with patch(
        "backend.agent.orchestrator.append_coaching_turns", new_callable=AsyncMock
    ) as append_mock:
        yield append_mock


_OFFER = get_tunables().glide.log_offer_text


def _judgment(
    intent: str = "log_meal",
    certainty: float = 0.99,
    reports_food: float = 0.02,
    needs_guidance: float = 0.1,
    raw_choice: str | None = None,
) -> RoutingJudgment:
    return RoutingJudgment(
        intent=intent,
        certainty=certainty,
        raw_choice=raw_choice or intent,
        reports_food=reports_food,
        needs_guidance=needs_guidance,
        latency_ms=250.0,
        model="glide",
        input_tokens=700,
    )


def _judged(*args, **kwargs) -> AsyncMock:
    """A judge_message stand-in that returns this judgment."""
    return AsyncMock(return_value=(_judgment(*args, **kwargs), None))


def _task(result):
    """A finished judgment task, as handle_message would pass to _route."""
    return asyncio.ensure_future(AsyncMock(return_value=result)())


def _gemini(intent: str) -> MagicMock:
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=_IntentResult(type=intent))
    return llm


# ---------------------------------------------------------------------------
# _route: the decision rule (spec FR-004 to FR-006, data-model.md)
# ---------------------------------------------------------------------------


async def test_route_confident_judgment_is_acted_on_without_gemini():
    # "protein" in the message: the deleted keyword lists sent this to coaching.
    llm = _gemini("coaching")
    with patch.object(orchestrator, "_intent_llm", llm):
        decision = await _route("protein shake", _task((_judgment("log_meal"), None)))

    assert decision.intent == "log_meal"
    assert decision.path == "judgment"
    assert decision.offer_to_log is False
    llm.ainvoke.assert_not_called()


async def test_route_confident_coaching_judgment():
    llm = _gemini("log_meal")
    with patch.object(orchestrator, "_intent_llm", llm):
        decision = await _route(
            "how much protein have I had today?", _task((_judgment("coaching"), None))
        )

    assert (decision.intent, decision.path) == ("coaching", "judgment")
    llm.ainvoke.assert_not_called()


async def test_route_unavailable_judgment_asks_gemini():
    llm = _gemini("coaching")
    with patch.object(orchestrator, "_intent_llm", llm):
        decision = await _route("is rice healthy", _task((None, "TimeoutError")))

    llm.ainvoke.assert_awaited_once()
    assert decision.intent == "coaching"
    assert decision.path == "second_opinion_unavailable"
    assert decision.judgment is None
    assert decision.offer_to_log is False
    assert decision.routing_record() is None


async def test_route_without_a_judgment_task_asks_gemini():
    llm = _gemini("log_meal")
    with patch.object(orchestrator, "_intent_llm", llm):
        decision = await _route("coffee", None)

    assert decision.path == "second_opinion_unavailable"
    assert decision.intent == "log_meal"


async def test_route_offer_to_log_only_for_coaching_that_reports_food():
    llm = _gemini("coaching")
    with patch.object(orchestrator, "_intent_llm", llm):
        mixed = await _route(
            "I had pizza, was that bad?",
            _task((_judgment("coaching", reports_food=0.97), None)),
        )
        pure = await _route(
            "is pizza healthy?", _task((_judgment("coaching", reports_food=0.02), None))
        )
        meal = await _route(
            "pizza", _task((_judgment("log_meal", reports_food=0.99), None))
        )

    assert mixed.offer_to_log is True
    assert pure.offer_to_log is False
    assert meal.offer_to_log is False


async def test_route_record_has_the_documented_keys():
    decision = await _route(
        "I had pizza, was that bad?",
        _task((_judgment("coaching", reports_food=0.9, needs_guidance=0.8), None)),
    )

    assert decision.routing_record() == {
        "path": "judgment",
        "certainty": 0.99,
        "raw_choice": "coaching",
        "reports_food": 0.9,
        "needs_guidance_jev": 0.8,
        "offer_to_log": True,
        "judge_model": "glide",
    }


def _mock_graph(*, is_paused: bool, still_paused: bool = False, usda_results=None):
    graph = MagicMock()
    paused_state = MagicMock(next=("present",) if is_paused else ())
    resumed_state = MagicMock(next=("present",) if still_paused else ())
    graph.aget_state = AsyncMock(side_effect=[paused_state, resumed_state])
    graph.aupdate_state = AsyncMock()
    graph.ainvoke = AsyncMock(
        return_value={
            "messages": [AIMessage(content="ok")],
            "usda_results": usda_results or [],
        }
    )
    return graph


async def test_handle_message_paused_graph_always_resumes_meal_logging():
    graph = _mock_graph(is_paused=True)

    llm = _gemini("coaching")
    with (
        patch("backend.agent.orchestrator.build_graph", return_value=graph),
        patch("backend.agent.orchestrator.judge_message", new=_judged("coaching")),
        patch.object(orchestrator, "_intent_llm", llm),
        patch(
            "backend.agent.orchestrator._handle_coaching", new_callable=AsyncMock
        ) as coaching_mock,
    ):
        result = await handle_message(
            "user-1", "how much protein is that", "thread-1", None
        )

    llm.ainvoke.assert_not_called()
    coaching_mock.assert_not_called()
    graph.aupdate_state.assert_awaited_once()
    assert result["status"] == "success"
    assert result["paused"] is False


async def test_handle_message_image_always_meal_logging():
    graph = _mock_graph(is_paused=False)

    with (
        patch("backend.agent.orchestrator.build_graph", return_value=graph),
        patch(
            "backend.agent.orchestrator.judge_message", new=_judged("coaching")
        ) as judge_mock,
        patch(
            "backend.agent.orchestrator._handle_coaching", new_callable=AsyncMock
        ) as coaching_mock,
        patch(
            "backend.agent.orchestrator.consume_llm_credit",
            new=AsyncMock(return_value=True),
        ),
    ):
        result = await handle_message(
            "user-1", "what's this?", "thread-1", None, image_b64="abc123"
        )

    judge_mock.assert_not_called()
    coaching_mock.assert_not_called()
    graph.ainvoke.assert_awaited_once()
    assert result["status"] == "success"


async def test_handle_message_fresh_coaching_intent_routes_to_coaching():
    graph = _mock_graph(is_paused=False)

    with (
        patch("backend.agent.orchestrator.build_graph", return_value=graph),
        patch("backend.agent.orchestrator.judge_message", new=_judged("coaching")),
        patch(
            "backend.agent.orchestrator.consume_llm_credit",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "backend.agent.orchestrator._coaching_agent.handle",
            new_callable=AsyncMock,
            return_value=CoachingResult(
                message="You've had 1,240 kcal today.",
                parsed=QueryParsed(time_range="today"),
            ),
        ) as handle_mock,
    ):
        result = await handle_message(
            "user-1", "how many calories today?", "thread-1", None
        )

    handle_mock.assert_awaited_once_with("user-1", "how many calories today?")
    graph.ainvoke.assert_not_called()
    assert result == {
        "status": "success",
        "message": "You've had 1,240 kcal today.",
        "paused": False,
        "items": [],
    }


async def test_handle_message_fresh_log_meal_intent_runs_graph():
    graph = _mock_graph(is_paused=False)

    with (
        patch("backend.agent.orchestrator.build_graph", return_value=graph),
        patch("backend.agent.orchestrator.judge_message", new=_judged("log_meal")),
        patch(
            "backend.agent.orchestrator.consume_llm_credit",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "backend.agent.orchestrator._coaching_agent.handle", new_callable=AsyncMock
        ) as handle_mock,
    ):
        result = await handle_message("user-1", "I had 2 eggs", "thread-1", None)

    handle_mock.assert_not_called()
    graph.ainvoke.assert_awaited_once()
    assert result["status"] == "success"


async def test_handle_message_enqueues_fact_extraction(_mock_fact_task):
    graph = _mock_graph(is_paused=False)

    with (
        patch("backend.agent.orchestrator.build_graph", return_value=graph),
        patch("backend.agent.orchestrator.judge_message", new=_judged("log_meal")),
        patch(
            "backend.agent.orchestrator.consume_llm_credit",
            new=AsyncMock(return_value=True),
        ),
    ):
        await handle_message("user-1", "I had 2 eggs", "thread-1", None)

    _mock_fact_task.delay.assert_called_once_with("user-1", "I had 2 eggs", "ok")


async def test_handle_message_skips_fact_extraction_for_card_actions(_mock_fact_task):
    for user_input, action in (("break it down", "decompose"), ("   ", None)):
        graph = _mock_graph(is_paused=True)
        with patch("backend.agent.orchestrator.build_graph", return_value=graph):
            await handle_message("user-1", user_input, "thread-1", None, action=action)

    _mock_fact_task.delay.assert_not_called()


# ---------------------------------------------------------------------------
# Coaching history recording (both intents)
# ---------------------------------------------------------------------------


_EGG_ITEM = {
    "food_name": "Egg, whole, cooked, fried",
    "qty_g": 100.0,
    "match_confidence": 0.9,
    "kcal": 196.0,
    "protein_g": 13.6,
    "carbs_g": 0.8,
    "fat_g": 15.0,
    "fiber_g": 0.0,
    "fdc_id": 1,
}
_TOAST_ITEM = {
    "food_name": "Bread, white, toasted",
    "qty_g": 30.0,
    "match_confidence": 0.8,
    "kcal": 80.0,
    "protein_g": 2.4,
    "carbs_g": 15.0,
    "fat_g": 1.0,
    "fiber_g": 0.8,
    "fdc_id": 2,
}


async def test_coaching_turn_is_recorded_verbatim(_mock_history_store):
    graph = _mock_graph(is_paused=False)

    with (
        patch("backend.agent.orchestrator.build_graph", return_value=graph),
        patch("backend.agent.orchestrator.judge_message", new=_judged("coaching")),
        patch(
            "backend.agent.orchestrator.consume_llm_credit",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "backend.agent.orchestrator._coaching_agent.handle",
            new_callable=AsyncMock,
            return_value=CoachingResult(
                message="You've had 1,240 kcal today.",
                parsed=QueryParsed(time_range="today"),
            ),
        ),
    ):
        await handle_message("user-1", "how many calories today?", "thread-1", None)

    _mock_history_store.assert_awaited_once_with(
        "user-1",
        [
            CoachingTurn(role="user", content="how many calories today?"),
            CoachingTurn(role="assistant", content="You've had 1,240 kcal today."),
        ],
    )


async def test_paused_logging_turn_is_recorded_as_card_summary(_mock_history_store):
    graph = _mock_graph(
        is_paused=False, still_paused=True, usda_results=[_EGG_ITEM, _TOAST_ITEM]
    )

    with (
        patch("backend.agent.orchestrator.build_graph", return_value=graph),
        patch("backend.agent.orchestrator.judge_message", new=_judged("log_meal")),
        patch(
            "backend.agent.orchestrator.consume_llm_credit",
            new=AsyncMock(return_value=True),
        ),
    ):
        await handle_message("user-1", "fried egg and toast", "thread-1", None)

    user_id, turns = _mock_history_store.await_args.args
    assert user_id == "user-1"
    assert turns[0] == CoachingTurn(role="user", content="fried egg and toast")
    summary = turns[1].content
    assert turns[1].role == "assistant"
    assert "Egg, whole, cooked, fried 100g" in summary
    assert "Bread, white, toasted 30g" in summary
    assert "276 kcal" in summary
    assert "16g protein" in summary
    assert "awaiting confirmation" in summary


async def test_completed_logging_turn_is_recorded_with_reply(_mock_history_store):
    graph = _mock_graph(is_paused=True, still_paused=False)
    graph.ainvoke.return_value = {
        "messages": [
            AIMessage(content="Fried egg and toast logged. Solid protein hit.")
        ],
        "usda_results": [_EGG_ITEM, _TOAST_ITEM],
        "meal_id": "m-1",
    }

    with patch("backend.agent.orchestrator.build_graph", return_value=graph):
        await handle_message("user-1", "confirm", "thread-1", None)

    _, turns = _mock_history_store.await_args.args
    assert turns == [
        CoachingTurn(role="user", content="confirm"),
        CoachingTurn(
            role="assistant", content="Fried egg and toast logged. Solid protein hit."
        ),
    ]


async def test_image_turn_without_text_is_recorded_as_photo(_mock_history_store):
    graph = _mock_graph(is_paused=False, still_paused=True, usda_results=[_EGG_ITEM])

    with (
        patch("backend.agent.orchestrator.build_graph", return_value=graph),
        patch(
            "backend.agent.orchestrator.consume_llm_credit",
            new=AsyncMock(return_value=True),
        ),
    ):
        await handle_message("user-1", "", "thread-1", None, image_b64="abc")

    _, turns = _mock_history_store.await_args.args
    assert turns[0] == CoachingTurn(role="user", content="[sent a meal photo]")


async def test_history_write_failure_does_not_fail_the_turn(_mock_history_store):
    _mock_history_store.side_effect = RuntimeError("boom")
    graph = _mock_graph(is_paused=False)

    with (
        patch("backend.agent.orchestrator.build_graph", return_value=graph),
        patch("backend.agent.orchestrator.judge_message", new=_judged("coaching")),
        patch(
            "backend.agent.orchestrator.consume_llm_credit",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "backend.agent.orchestrator._coaching_agent.handle",
            new_callable=AsyncMock,
            return_value=CoachingResult(
                message="ok", parsed=QueryParsed(time_range="today")
            ),
        ),
    ):
        result = await handle_message("user-1", "how am I doing?", "thread-1", None)

    assert result["message"] == "ok"


# ---------------------------------------------------------------------------
# Offer to log (FR-002a) and the routing record (FR-014)
# ---------------------------------------------------------------------------


async def test_mixed_message_reply_ends_with_offer_to_log():
    graph = _mock_graph(is_paused=False)
    with (
        patch("backend.agent.orchestrator.build_graph", return_value=graph),
        patch(
            "backend.agent.orchestrator.judge_message",
            new=_judged("coaching", reports_food=0.95),
        ),
        patch(
            "backend.agent.orchestrator.consume_llm_credit",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "backend.agent.orchestrator._coaching_agent.handle",
            new_callable=AsyncMock,
            return_value=CoachingResult(
                message="One pizza won't derail you.",
                parsed=QueryParsed(time_range="today"),
            ),
        ),
    ):
        result = await handle_message(
            "user-1", "I had pizza, was that bad?", "thread-1", None
        )

    assert result["message"] == f"One pizza won't derail you.\n\n{_OFFER}"
    graph.ainvoke.assert_not_called()


async def test_pure_question_reply_has_no_offer():
    graph = _mock_graph(is_paused=False)
    with (
        patch("backend.agent.orchestrator.build_graph", return_value=graph),
        patch(
            "backend.agent.orchestrator.judge_message",
            new=_judged("coaching", reports_food=0.1),
        ),
        patch(
            "backend.agent.orchestrator.consume_llm_credit",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "backend.agent.orchestrator._coaching_agent.handle",
            new_callable=AsyncMock,
            return_value=CoachingResult(
                message="Pizza is fine in moderation.",
                parsed=QueryParsed(time_range="today"),
            ),
        ),
    ):
        result = await handle_message("user-1", "is pizza healthy?", "thread-1", None)

    assert result["message"] == "Pizza is fine in moderation."


async def test_coaching_turn_passes_routing_record_to_store():
    graph = _mock_graph(is_paused=False)
    with (
        patch("backend.agent.orchestrator.build_graph", return_value=graph),
        patch(
            "backend.agent.orchestrator.judge_message",
            new=_judged("coaching", reports_food=0.02, needs_guidance=0.9),
        ),
        patch(
            "backend.agent.orchestrator.consume_llm_credit",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "backend.agent.orchestrator._coaching_agent.handle",
            new_callable=AsyncMock,
            return_value=CoachingResult(
                message="ok", parsed=QueryParsed(time_range="today")
            ),
        ) as handle_mock,
        patch(
            "backend.agent.orchestrator.save_coaching_response",
            new_callable=AsyncMock,
            return_value=None,
        ) as save_mock,
    ):
        await handle_message("user-1", "should I eat less sugar?", "thread-1", None)

    # Retrieval is still driven only by Gemini's parse inside the agent.
    handle_mock.assert_awaited_once_with("user-1", "should I eat less sugar?")
    assert save_mock.await_args.kwargs["routing"] == {
        "path": "judgment",
        "certainty": 0.99,
        "raw_choice": "coaching",
        "reports_food": 0.02,
        "needs_guidance_jev": 0.9,
        "offer_to_log": False,
        "judge_model": "glide",
    }


async def test_unavailable_judgment_stores_no_routing_record():
    graph = _mock_graph(is_paused=False)
    with (
        patch("backend.agent.orchestrator.build_graph", return_value=graph),
        patch(
            "backend.agent.orchestrator.judge_message",
            new=AsyncMock(return_value=(None, "not_configured")),
        ),
        patch.object(orchestrator, "_intent_llm", _gemini("coaching")),
        patch(
            "backend.agent.orchestrator.consume_llm_credit",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "backend.agent.orchestrator._coaching_agent.handle",
            new_callable=AsyncMock,
            return_value=CoachingResult(
                message="ok", parsed=QueryParsed(time_range="today")
            ),
        ),
        patch(
            "backend.agent.orchestrator.save_coaching_response",
            new_callable=AsyncMock,
            return_value=None,
        ) as save_mock,
    ):
        result = await handle_message("user-1", "hi", "thread-1", None)

    assert save_mock.await_args.kwargs["routing"] is None
    assert result["message"] == "ok"


# ---------------------------------------------------------------------------
# Overlap and cancellation (US4, research R4, FR-009)
# ---------------------------------------------------------------------------


async def test_pending_card_cancels_the_in_flight_judgment():
    graph = _mock_graph(is_paused=True)
    finished = asyncio.Event()

    async def never_answers(_message: str):
        await asyncio.Event().wait()
        finished.set()

    with (
        patch("backend.agent.orchestrator.build_graph", return_value=graph),
        patch("backend.agent.orchestrator.judge_message", new=never_answers),
    ):
        result = await asyncio.wait_for(
            handle_message("user-1", "yes", "thread-1", None), timeout=2
        )

    # Cancelled before it could answer (possibly before it even started);
    # the card reply never waits on it.
    assert not finished.is_set()
    graph.aupdate_state.assert_awaited_once()
    assert result["status"] == "success"


async def test_blank_text_starts_no_judgment():
    graph = _mock_graph(is_paused=False)
    with (
        patch("backend.agent.orchestrator.build_graph", return_value=graph),
        patch(
            "backend.agent.orchestrator.judge_message", new=_judged("coaching")
        ) as judge_mock,
        patch.object(orchestrator, "_intent_llm", _gemini("log_meal")),
        patch(
            "backend.agent.orchestrator.consume_llm_credit",
            new=AsyncMock(return_value=True),
        ),
    ):
        await handle_message("user-1", "   ", "thread-1", None)

    judge_mock.assert_not_called()


async def test_judgment_overlaps_the_checkpoint_read():
    graph = _mock_graph(is_paused=False)

    async def slow_state(_config):
        await asyncio.sleep(0.2)
        return MagicMock(next=())

    graph.aget_state = AsyncMock(side_effect=slow_state)

    async def slow_judgment(_message: str):
        await asyncio.sleep(0.2)
        return _judgment("coaching"), None

    with (
        patch("backend.agent.orchestrator.build_graph", return_value=graph),
        patch("backend.agent.orchestrator.judge_message", new=slow_judgment),
        patch(
            "backend.agent.orchestrator._handle_coaching",
            new_callable=AsyncMock,
            return_value={
                "status": "success",
                "message": "ok",
                "paused": False,
                "items": [],
            },
        ),
    ):
        start = time.perf_counter()
        await handle_message("user-1", "how am I doing?", "thread-1", None)
        elapsed = time.perf_counter() - start

    assert elapsed < 0.35, f"judgment and checkpoint read ran serially ({elapsed:.2f}s)"
