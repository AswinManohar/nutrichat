"""Tests for the GLiDE routing judgment (no network: the transport is faked)."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from backend.agent import glide, system_one
from backend.agent.system_one import (
    ROUTING_QUESTIONS,
    judge_message,
    warm_up,
    warn_if_unconfigured,
)

_EVAL_CASES = Path(__file__).parent.parent / "eval" / "cases" / "intent_routing.jsonl"


def _body(
    probabilities: dict[str, float],
    reports_food: float = 0.03,
    needs_guidance: float = 0.1,
) -> dict:
    """A System One response body for the three routing questions."""
    top = max(probabilities, key=lambda k: probabilities[k])
    return {
        "model": "glide",
        "answers": {
            "intent": {
                "type": "choice",
                "choice": top,
                "confidence": 0.9,
                "probabilities": probabilities,
            },
            "reports_food": {"type": "noul", "noul": reports_food, "confidence": 0.9},
            "needs_guidance": {
                "type": "noul",
                "noul": needs_guidance,
                "confidence": 0.8,
            },
        },
        "usage": {"input_tokens": 700, "output_tokens": 3},
        "token_usage": 703,
    }


def _client(handler) -> httpx.AsyncClient:
    """A GLiDE client whose requests are answered by ``handler``."""
    return httpx.AsyncClient(
        base_url="https://glide.test",
        headers={"X-API-Key": "test-key"},
        transport=httpx.MockTransport(handler),
    )


def _answering(body: dict, status: int = 200, seen: list | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, json=body)

    return handler


async def _judge(handler, text: str = "2 eggs"):
    with patch.object(system_one, "_get_client", return_value=_client(handler)):
        return await judge_message(text)


async def test_confident_log_meal():
    judgment, failure = await _judge(
        _answering(_body({"log_meal": 0.97, "coaching": 0.02, "other": 0.01})),
        "protein shake",
    )

    assert failure is None
    assert judgment.intent == "log_meal"
    assert judgment.certainty == pytest.approx(0.97)
    assert judgment.raw_choice == "log_meal"
    assert judgment.model == "glide"
    assert judgment.input_tokens == 700


async def test_coaching_and_other_share_a_handler():
    # Split between coaching and other is not routing uncertainty.
    judgment, _ = await _judge(
        _answering(
            _body(
                {"log_meal": 0.04, "coaching": 0.5, "other": 0.46}, needs_guidance=0.8
            )
        ),
        "thanks, and is rice ok?",
    )

    assert judgment.intent == "coaching"
    assert judgment.certainty == pytest.approx(0.96)
    assert judgment.raw_choice == "coaching"
    assert judgment.needs_guidance == pytest.approx(0.8)


async def test_request_sends_only_the_message_and_the_three_questions():
    seen: list[httpx.Request] = []
    await _judge(
        _answering(
            _body({"log_meal": 0.9, "coaching": 0.05, "other": 0.05}), seen=seen
        ),
        "2 eggs and toast",
    )

    (request,) = seen
    assert request.url.path == "/v1/systemone"
    assert request.headers["X-API-Key"] == "test-key"
    sent = json.loads(request.content)
    # Exactly these keys: GLiDE answers 422 to anything else.
    assert set(sent) == {"model", "state", "questions"}
    assert sent["model"] == "fastino/GLiDE"
    assert sent["state"] == {"message": "2 eggs and toast"}  # spec FR-015
    assert sent["questions"] == ROUTING_QUESTIONS
    assert set(sent["questions"]) == {"intent", "reports_food", "needs_guidance"}


async def test_unconfigured_returns_none_without_network(monkeypatch):
    monkeypatch.delenv("FASTINO_API_KEY", raising=False)
    monkeypatch.setattr(system_one, "_client", None)

    assert await judge_message("protein shake") == (None, "not_configured")


@pytest.mark.parametrize("status", [401, 402, 422, 425, 429, 503])
async def test_error_statuses_become_unavailable(status, caplog):
    handler = _answering({"detail": "my secret meal text"}, status=status)
    with caplog.at_level(logging.WARNING, logger="backend.agent.system_one"):
        result = await _judge(handler, "my secret meal text")

    assert result == (None, f"http_{status}")
    # Only the reason is logged, never the message text (FR-015).
    assert "my secret meal text" not in caplog.text


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (httpx.ReadTimeout("slow"), "timeout"),
        (httpx.ConnectTimeout("slow"), "timeout"),
        (httpx.ConnectError("my secret meal text"), "ConnectError"),
    ],
    ids=["read_timeout", "connect_timeout", "connect_error"],
)
async def test_transport_errors_become_unavailable(error, reason, caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        raise error

    with caplog.at_level(logging.WARNING, logger="backend.agent.system_one"):
        result = await _judge(handler, "my secret meal text")

    assert result == (None, reason)
    assert "my secret meal text" not in caplog.text


async def test_missing_answer_is_malformed():
    body = _body({"log_meal": 0.9, "coaching": 0.05, "other": 0.05})
    del body["answers"]["reports_food"]

    assert await _judge(_answering(body)) == (None, "malformed_response")


async def test_unknown_choice_is_malformed():
    body = _body({"log_meal": 0.1, "coaching": 0.1, "maybe": 0.8})

    assert await _judge(_answering(body)) == (None, "malformed_response")


async def test_out_of_range_probability_is_malformed():
    body = _body({"log_meal": 0.9, "coaching": 0.05, "other": 0.05}, reports_food=1.4)

    assert await _judge(_answering(body)) == (None, "malformed_response")


async def test_non_json_body_is_malformed():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>gateway</html>")

    assert await _judge(handler) == (None, "malformed_response")


async def test_cancellation_propagates():
    def handler(request: httpx.Request) -> httpx.Response:
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await _judge(handler)


def test_warn_if_unconfigured(monkeypatch, caplog):
    monkeypatch.delenv("FASTINO_API_KEY", raising=False)
    with caplog.at_level(logging.WARNING, logger="backend.agent.system_one"):
        warn_if_unconfigured()
    assert caplog.text.count("FASTINO_API_KEY") == 1

    caplog.clear()
    monkeypatch.setenv("FASTINO_API_KEY", "test-key")
    with caplog.at_level(logging.WARNING, logger="backend.agent.system_one"):
        warn_if_unconfigured()
    assert caplog.text == ""


def _strings(value: object) -> list[str]:
    """Every string inside a question's instructions/criteria structure."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, (list, tuple)):
        return [s for v in value for s in _strings(v)]
    return []


def test_eval_cases_are_held_out_of_question_examples():
    """No eval message may be taught to GLiDE in the questions (spec FR-011)."""
    taught: set[str] = set()
    for question in ROUTING_QUESTIONS.values():
        taught.update(s.strip().lower() for s in _strings(question["instructions"]))
        taught.update(s.strip().lower() for s in _strings(question.get("criteria")))
    assert len(taught) > 10
    cases = [json.loads(line) for line in _EVAL_CASES.read_text().splitlines()]
    leaked = [c["text"] for c in cases if c["text"].strip().lower() in taught]
    assert leaked == []


async def test_warm_up_never_raises_and_sends_no_user_text(caplog):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        raise httpx.ReadTimeout("slow")

    with (
        patch.object(system_one, "_get_client", return_value=_client(handler)),
        caplog.at_level(logging.WARNING, logger="backend.agent.system_one"),
    ):
        await warm_up()

    (request,) = seen
    assert json.loads(request.content)["state"] == {"message": "warm up"}
    assert request.extensions["timeout"]["read"] == 30.0
    assert "timeout" in caplog.text


async def test_warm_up_waits_once_for_a_warming_model():
    statuses = iter([425, 200])
    body = _body({"log_meal": 0.9, "coaching": 0.05, "other": 0.05})
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(next(statuses), json=body)

    sleep = AsyncMock()
    with (
        patch.object(system_one, "_get_client", return_value=_client(handler)),
        patch.object(system_one.asyncio, "sleep", sleep),
    ):
        await warm_up()

    assert calls == 2
    sleep.assert_awaited_once_with(system_one._WARMING_WAIT_S)


async def test_warm_up_gives_up_when_still_warming():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(425, json={})

    with (
        patch.object(system_one, "_get_client", return_value=_client(handler)),
        patch.object(system_one.asyncio, "sleep", AsyncMock()),
    ):
        await warm_up()

    assert calls == 2


async def test_client_sends_the_key_and_keeps_idle_connections(monkeypatch):
    monkeypatch.setenv("FASTINO_API_KEY", "test-key")
    monkeypatch.setattr(system_one, "_client", None)
    captured: dict = {}
    real = glide.httpx.AsyncClient

    def spy(**kwargs):
        captured.update(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(glide.httpx, "AsyncClient", spy)

    client = system_one._get_client()

    assert captured["limits"].keepalive_expiry == system_one._KEEPALIVE_EXPIRY_S
    assert captured["timeout"] == 0.8
    assert client.headers["X-API-Key"] == "test-key"
    assert str(client.base_url).rstrip("/") == "https://api.fastino.ai"
    await client.aclose()
    monkeypatch.setattr(system_one, "_client", None)
