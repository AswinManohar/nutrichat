"""Trace shape and cost records for a turn, checked with Logfire's test exporter.

Everything is offline: I/O is mocked the way the neighbouring tests do it. The
spans under test are the ones added in ``backend.tracing``; the last test
checks that none of them carries the user's text.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult, LLMResult
from langchain_google_genai import ChatGoogleGenerativeAI
from logfire.testing import CaptureLogfire
from pydantic import BaseModel

from backend import tracing
from backend.agent import glide
from backend.agent.coaching import agent as coaching_agent
from backend.agent.cost import LlmCostCallback
from backend.agent.food.usda import NutritionEstimate, usda_lookup_batch
from backend.agent.food.usda_local import LocalMatch
from backend.agent.llm import FLASH_LITE_MODEL, make_llm
from backend.agent.meal_logging import graph
from backend.agent.meal_logging.meals import FoodEntity

SECRET = "SECRET-USER-TEXT"


def _spans(capfire: CaptureLogfire, name: str) -> list[Any]:
    return [s for s in _exported(capfire) if s.name == name]


def _exported(capfire: CaptureLogfire) -> list[Any]:
    """Finished spans and log records; Logfire also exports a pending copy."""
    return [
        s
        for s in capfire.exporter.exported_spans
        if s.attributes.get("logfire.span_type") != "pending_span"
    ]


def _only(capfire: CaptureLogfire, name: str) -> Any:
    found = _spans(capfire, name)
    assert len(found) == 1, [s.name for s in _exported(capfire)]
    return found[0]


def _client(handler: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url="https://glide.test",
        transport=httpx.MockTransport(handler),
    )


_QUESTIONS = {"q": glide.noul("Is it food?")}
_OK_BODY = {
    "model": "glide",
    "answers": {"q": {"type": "noul", "noul": 0.9, "confidence": 0.9}},
    "usage": {"input_tokens": 42, "output_tokens": 1},
}


# (a) glide.ask ---------------------------------------------------------------


async def test_glide_ask_span_records_purpose_and_ok_outcome(capfire):
    client = _client(lambda request: httpx.Response(200, json=_OK_BODY))
    await glide.ask(client, {"message": SECRET}, _QUESTIONS, purpose="routing")

    attrs = _only(capfire, tracing.GLIDE_ASK).attributes
    assert attrs["purpose"] == "routing"
    assert attrs["outcome"] == "ok"
    assert attrs["input_tokens"] == 42
    assert attrs["model"]


async def test_glide_ask_timeout_is_an_outcome_not_a_span_error(capfire):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(glide.GlideUnavailable) as raised:
        await glide.ask(
            _client(handler), {"message": SECRET}, _QUESTIONS, purpose="memory_judge"
        )

    assert raised.value.reason == "timeout"
    span = _only(capfire, tracing.GLIDE_ASK)
    assert span.attributes["outcome"] == "timeout"
    assert span.attributes["purpose"] == "memory_judge"
    assert not span.events
    assert span.status.status_code.name != "ERROR"


async def test_glide_ask_http_status_outcome(capfire):
    client = _client(lambda request: httpx.Response(503))
    with pytest.raises(glide.GlideUnavailable):
        await glide.ask(client, {"message": "x"}, _QUESTIONS, purpose="reply_guard")
    assert _only(capfire, tracing.GLIDE_ASK).attributes["outcome"] == "http_503"


async def test_glide_ask_cancellation_propagates(capfire):
    started = asyncio.Event()

    async def hang(request: httpx.Request) -> httpx.Response:
        started.set()
        await asyncio.sleep(30)
        return httpx.Response(200, json=_OK_BODY)

    task = asyncio.create_task(
        glide.ask(_client(hang), {"message": "x"}, _QUESTIONS, purpose="routing")
    )
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


# (b) food.lookup_batch / food.resolve ----------------------------------------


_LOCAL_MACROS = {
    "kcal": 150.0,
    "protein_g": 10.0,
    "carbs_g": 1.0,
    "fat_g": 11.0,
    "fiber_g": 0.0,
    "sugar_g": 0.0,
    "sat_fat_g": 3.0,
}


def _local_match(confidence: float) -> LocalMatch:
    return LocalMatch(
        fdc_id=172187,
        description="Egg, whole",
        match_confidence=confidence,
        candidates=["Egg, whole"],
        macros_per_100g=_LOCAL_MACROS,
        nutrients_per_100g={},
    )


_ESTIMATE = NutritionEstimate(
    kcal=450.0,
    protein_g=25.0,
    carbs_g=55.0,
    fat_g=12.0,
    fiber_g=3.0,
    sugar_g=2.0,
    sat_fat_g=4.0,
)


async def test_lookup_batch_children_for_hit_and_llm_fallback(capfire):
    good = FoodEntity(food_name="egg", qty_g=100.0, unit="g")
    weak = FoodEntity(food_name=f"{SECRET} biryani", qty_g=300.0, unit="bowl")

    def lookup(name: str, **kwargs: Any) -> LocalMatch:
        return _local_match(0.95 if name == "egg" else 0.05)

    fake_run = MagicMock()
    fake_run.output = _ESTIMATE
    with (
        patch("backend.agent.food.usda._use_local", return_value=True),
        patch("backend.agent.food.usda.usda_local.lookup", side_effect=lookup),
        patch(
            "backend.agent.food.usda._estimate_cache_lookup",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch("backend.agent.food.usda._estimate_cache_write", new_callable=AsyncMock),
        patch(
            "backend.agent.food.usda._estimate_agent.run",
            new_callable=AsyncMock,
            return_value=fake_run,
        ),
    ):
        results = await usda_lookup_batch([good, weak])

    assert [r.estimated for r in results] == [False, True]
    batch = _only(capfire, tracing.FOOD_LOOKUP_BATCH)
    assert batch.attributes["n_entities"] == 2
    assert batch.attributes["n_estimated"] == 1
    assert batch.attributes["n_miss"] == 0

    children = _spans(capfire, tracing.FOOD_RESOLVE)
    assert len(children) == 2
    assert {c.parent.span_id for c in children} == {batch.context.span_id}
    by_source = {c.attributes["source"]: c for c in children}
    assert set(by_source) == {"local", "llm_estimate"}
    assert by_source["local"].attributes["fell_back"] is False
    assert by_source["local"].attributes["fdc_id"] == 172187
    assert by_source["llm_estimate"].attributes["fell_back"] is True
    assert by_source["llm_estimate"].attributes["fdc_id"] == -1


async def test_lookup_batch_counts_a_miss_when_the_estimate_fails(capfire):
    entity = FoodEntity(food_name="mystery", qty_g=50.0, unit="g")
    with (
        patch("backend.agent.food.usda._use_local", return_value=True),
        patch("backend.agent.food.usda.usda_local.lookup", return_value=None),
        patch(
            "backend.agent.food.usda._estimate_cache_lookup",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "backend.agent.food.usda._estimate_agent.run",
            new_callable=AsyncMock,
            side_effect=RuntimeError("provider down"),
        ),
    ):
        results = await usda_lookup_batch([entity])

    assert results[0].fdc_id == -1
    assert _only(capfire, tracing.FOOD_LOOKUP_BATCH).attributes["n_miss"] == 1
    child = _only(capfire, tracing.FOOD_RESOLVE)
    assert child.attributes["source"] == "miss"
    assert child.attributes["fell_back"] is True


# (c) coaching.context --------------------------------------------------------


async def test_context_span_marks_the_restrictions_only_fallback(capfire):
    with (
        patch(
            "backend.agent.coaching.agent.build_context",
            new_callable=AsyncMock,
            side_effect=RuntimeError("embedding API down"),
        ),
        patch(
            "backend.agent.coaching.agent.load_restrictions",
            new_callable=AsyncMock,
            return_value=MagicMock(),
        ),
        patch(
            "backend.agent.coaching.agent.build_restrictions_prompt",
            return_value="restrictions",
        ),
    ):
        prompt = await coaching_agent._context_prompt("user-1", [])

    assert prompt == "restrictions"
    span = _only(capfire, tracing.COACHING_CONTEXT)
    assert span.attributes["fallback"] == "restrictions_only"
    assert span.attributes["handled_error"] == "build_context"
    assert [e.name for e in span.events] == ["exception"]


async def test_context_span_fallback_is_none_on_success(capfire):
    with (
        patch(
            "backend.agent.coaching.agent.build_context",
            new_callable=AsyncMock,
            return_value=MagicMock(),
        ),
        patch("backend.agent.coaching.agent.build_system_prompt", return_value="ctx"),
    ):
        await coaching_agent._context_prompt("user-1", [])

    assert _only(capfire, tracing.COACHING_CONTEXT).attributes["fallback"] == "none"


# (d) handled failures --------------------------------------------------------


async def test_extract_node_failure_is_recorded_and_still_falls_back(capfire):
    state = {"messages": [HumanMessage(content=SECRET)]}
    with (
        patch.object(graph, "extract_entities", side_effect=RuntimeError("boom")),
        tracing.stage_span(tracing.TURN),
    ):
        result = await graph.extract_node(state)

    assert result == {"entities": [], "pre_decompose_entities": []}
    turn = _only(capfire, tracing.TURN)
    assert turn.attributes["handled_error"] == "extract_entities"
    events = [e for e in turn.events if e.name == "exception"]
    assert len(events) == 1
    assert events[0].attributes["exception.type"] == "RuntimeError"
    # Recorded, not escaped: the turn span is not failed.
    assert turn.status.status_code.name != "ERROR"


# (e) LangChain cost callback -------------------------------------------------


def _llm_cost_records(capfire: CaptureLogfire) -> list[Any]:
    return _spans(capfire, "llm_cost")


def _result_with_usage(usage: dict | None) -> LLMResult:
    message = AIMessage(content="ok", usage_metadata=usage)
    return LLMResult(generations=[[ChatGeneration(message=message)]])


def test_cost_callback_emits_llm_cost_with_operation_and_tokens(capfire):
    callback = LlmCostCallback(FLASH_LITE_MODEL, "extract_entities")
    callback.on_llm_end(
        _result_with_usage(
            {"input_tokens": 1000, "output_tokens": 200, "total_tokens": 1200}
        )
    )

    (record,) = _llm_cost_records(capfire)
    assert record.attributes["operation"] == "extract_entities"
    assert record.attributes["model"] == FLASH_LITE_MODEL
    assert record.attributes["input_tokens"] == 1000
    assert record.attributes["output_tokens"] == 200
    assert record.attributes["cost_usd"] > 0


def test_cost_callback_skips_missing_usage_without_raising(capfire):
    LlmCostCallback(FLASH_LITE_MODEL, "x").on_llm_end(_result_with_usage(None))
    LlmCostCallback(FLASH_LITE_MODEL, "x").on_llm_end(LLMResult(generations=[]))
    assert _llm_cost_records(capfire) == []


def test_cost_callback_skips_an_unknown_model(capfire):
    LlmCostCallback("no-such-model", "x").on_llm_end(
        _result_with_usage({"input_tokens": 5, "output_tokens": 5, "total_tokens": 10})
    )
    assert _llm_cost_records(capfire) == []


class _Out(BaseModel):
    value: int


async def test_make_llm_callback_fires_through_structured_output_in_a_thread(
    capfire,
):
    usage = {"input_tokens": 300, "output_tokens": 30, "total_tokens": 330}
    reply = AIMessage(
        content=json.dumps({"value": 7}),
        tool_calls=[{"name": "_Out", "args": {"value": 7}, "id": "call-1"}],
        usage_metadata=usage,
    )
    chat_result = ChatResult(generations=[ChatGeneration(message=reply)])
    llm = make_llm(operation="probe").with_structured_output(_Out)

    with patch.object(ChatGoogleGenerativeAI, "_generate", return_value=chat_result):
        out = await asyncio.to_thread(llm.invoke, "hello")

    assert out == _Out(value=7)
    (record,) = _llm_cost_records(capfire)
    assert record.attributes["operation"] == "probe"
    assert record.attributes["input_tokens"] == 300


def test_make_llm_without_operation_attaches_no_callback():
    assert not make_llm().callbacks


# (f) privacy -----------------------------------------------------------------


async def test_added_spans_carry_no_user_text(capfire):
    """GLiDE, food lookup and handled-failure spans never export the text."""
    client = _client(lambda request: httpx.Response(200, json=_OK_BODY))
    await glide.ask(client, {"message": SECRET}, _QUESTIONS, purpose="routing")

    entity = FoodEntity(food_name=f"{SECRET} stew", qty_g=100.0, unit="g")
    fake_run = MagicMock()
    fake_run.output = _ESTIMATE
    with (
        patch("backend.agent.food.usda._use_local", return_value=True),
        patch("backend.agent.food.usda.usda_local.lookup", return_value=None),
        patch(
            "backend.agent.food.usda._estimate_cache_lookup",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch("backend.agent.food.usda._estimate_cache_write", new_callable=AsyncMock),
        patch(
            "backend.agent.food.usda._estimate_agent.run",
            new_callable=AsyncMock,
            return_value=fake_run,
        ),
    ):
        await usda_lookup_batch([entity])

    state = {"messages": [HumanMessage(content=SECRET)]}
    with (
        patch.object(graph, "extract_entities", side_effect=RuntimeError("boom")),
        tracing.stage_span(tracing.TURN),
    ):
        await graph.extract_node(state)

    added = {
        tracing.GLIDE_ASK,
        tracing.FOOD_LOOKUP_BATCH,
        tracing.FOOD_RESOLVE,
        tracing.TURN,
    }
    exported = [s for s in _exported(capfire) if s.name in added]
    assert len(exported) >= 4
    for span in exported:
        dumped = json.dumps(
            {
                "attributes": dict(span.attributes or {}),
                "events": [dict(e.attributes or {}) for e in span.events],
            },
            default=str,
        )
        assert SECRET not in dumped, span.name
