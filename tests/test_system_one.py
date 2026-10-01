"""Tests for the TypeSafe Jev routing judgment (no network: the client is faked)."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx2
import pytest
from typesafe_sdk import (
    TypeSafeAPIConnectionError,
    TypeSafeAPITimeoutError,
    TypeSafeAuthenticationError,
    TypeSafeInternalServerError,
    TypeSafeRateLimitError,
)

from backend.agent import system_one
from backend.agent.system_one import (
    ROUTING_QUESTIONS,
    judge_message,
    warm_up,
    warn_if_unconfigured,
)

_EVAL_CASES = Path(__file__).parent.parent / "eval" / "cases" / "intent_routing.jsonl"


def _response(
    probabilities: dict[str, float],
    reports_food: float = 0.03,
    needs_guidance: float = 0.1,
) -> SimpleNamespace:
    """The slice of SystemOneResponse that judge_message reads."""
    top = max(probabilities, key=lambda k: probabilities[k])
    return SimpleNamespace(
        choices={
            "intent": SimpleNamespace(
                choice=top, confidence=0.9, probabilities=probabilities
            )
        },
        nouls={
            "reports_food": SimpleNamespace(noul=reports_food),
            "needs_guidance": SimpleNamespace(noul=needs_guidance),
        },
        usage=SimpleNamespace(input_tokens=700, output_tokens=40),
    )


def _client(**kwargs) -> MagicMock:
    client = MagicMock()
    client.system_one = AsyncMock(**kwargs)
    return client


def _api_error(cls: type) -> Exception:
    return cls(500, {}, httpx2.Headers(), message="boom")


async def test_confident_log_meal():
    client = _client(
        return_value=_response({"log_meal": 0.97, "coaching": 0.02, "other": 0.01})
    )
    with patch.object(system_one, "_get_client", return_value=client):
        judgment, failure = await judge_message("protein shake")

    assert failure is None
    assert judgment.intent == "log_meal"
    assert judgment.certainty == pytest.approx(0.97)
    assert judgment.raw_choice == "log_meal"


async def test_coaching_and_other_share_a_handler():
    # Split between coaching and other is not routing uncertainty.
    client = _client(
        return_value=_response(
            {"log_meal": 0.04, "coaching": 0.5, "other": 0.46}, needs_guidance=0.8
        )
    )
    with patch.object(system_one, "_get_client", return_value=client):
        judgment, _ = await judge_message("thanks, and is rice ok?")

    assert judgment.intent == "coaching"
    assert judgment.certainty == pytest.approx(0.96)
    assert judgment.raw_choice == "coaching"
    assert judgment.needs_guidance == pytest.approx(0.8)


async def test_request_sends_only_the_message_and_the_three_questions():
    client = _client(
        return_value=_response({"log_meal": 0.9, "coaching": 0.05, "other": 0.05})
    )
    with patch.object(system_one, "_get_client", return_value=client):
        await judge_message("2 eggs and toast")

    state, questions = client.system_one.await_args.args
    assert state == {"message": "2 eggs and toast"}  # spec FR-015
    assert set(questions) == {"intent", "reports_food", "needs_guidance"}


async def test_unconfigured_returns_none_without_network(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setattr(system_one, "_client", None)

    assert await judge_message("protein shake") == (None, "not_configured")


@pytest.mark.parametrize(
    "error",
    [
        TypeSafeAPITimeoutError(0.8),
        TypeSafeAPIConnectionError("reset"),
        _api_error(TypeSafeRateLimitError),
        _api_error(TypeSafeAuthenticationError),
        _api_error(TypeSafeInternalServerError),
    ],
    ids=lambda e: type(e).__name__,
)
async def test_service_errors_become_unavailable(error, caplog):
    client = _client(side_effect=error)
    with (
        patch.object(system_one, "_get_client", return_value=client),
        caplog.at_level(logging.WARNING, logger="backend.agent.system_one"),
    ):
        result = await judge_message("my secret meal text")

    assert result == (None, type(error).__name__)
    # Only the class name is logged, never the message text (FR-015).
    assert "my secret meal text" not in caplog.text


async def test_missing_answer_is_malformed():
    response = _response({"log_meal": 0.9, "coaching": 0.05, "other": 0.05})
    del response.nouls["reports_food"]
    client = _client(return_value=response)
    with patch.object(system_one, "_get_client", return_value=client):
        assert await judge_message("2 eggs") == (None, "malformed_response")


async def test_unknown_choice_is_malformed():
    client = _client(
        return_value=_response({"log_meal": 0.1, "coaching": 0.1, "maybe": 0.8})
    )
    with patch.object(system_one, "_get_client", return_value=client):
        assert await judge_message("2 eggs") == (None, "malformed_response")


async def test_cancellation_propagates():
    client = _client(side_effect=asyncio.CancelledError())
    with patch.object(system_one, "_get_client", return_value=client):
        with pytest.raises(asyncio.CancelledError):
            await judge_message("2 eggs")


def test_warn_if_unconfigured(monkeypatch, caplog):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with caplog.at_level(logging.WARNING, logger="backend.agent.system_one"):
        warn_if_unconfigured()
    assert caplog.text.count("TYPESAFE_API_KEY") == 1

    caplog.clear()
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
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
    """No eval message may be taught to Jev in the questions (spec FR-011)."""
    taught: set[str] = set()
    for question in ROUTING_QUESTIONS.values():
        taught.update(s.strip().lower() for s in _strings(question.instructions))
        taught.update(
            s.strip().lower() for s in _strings(getattr(question, "criteria", None))
        )
    cases = [json.loads(line) for line in _EVAL_CASES.read_text().splitlines()]
    leaked = [c["text"] for c in cases if c["text"].strip().lower() in taught]
    assert leaked == []


async def test_warm_up_never_raises_and_sends_no_user_text(caplog):
    client = _client(side_effect=TypeSafeAPITimeoutError(0.8))
    with (
        patch.object(system_one, "_get_client", return_value=client),
        caplog.at_level(logging.WARNING, logger="backend.agent.system_one"),
    ):
        await warm_up()

    assert client.system_one.await_args.args[0] == {"message": "warm up"}
    assert client.system_one.await_args.kwargs["timeout"] == 10.0
    assert "TypeSafeAPITimeoutError" in caplog.text


def test_client_keeps_idle_connections(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.setattr(system_one, "_client", None)
    captured = {}
    monkeypatch.setattr(
        system_one.httpx2,
        "AsyncClient",
        lambda **kwargs: captured.update(kwargs) or MagicMock(),
    )
    monkeypatch.setattr(system_one, "AsyncTypeSafeClient", MagicMock())

    system_one._get_client()

    assert captured["limits"].keepalive_expiry == system_one._KEEPALIVE_EXPIRY_S
    monkeypatch.setattr(system_one, "_client", None)
