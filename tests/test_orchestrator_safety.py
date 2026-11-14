"""Red-flag screen in handle_message (spec 013 US3): fixed reply, no model."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import SQLAlchemyError

from backend.agent import orchestrator
from backend.agent.routing.router import RouteDecision
from backend.safety import escalation, red_flags, tables

FLAGGED = "I stopped my insulin yesterday and I am tired"


@pytest.fixture
def paths() -> Iterator[SimpleNamespace]:
    """Every collaborator a turn could use, mocked, so absence can be asserted."""
    graph = MagicMock()
    graph.aget_state = AsyncMock(return_value=SimpleNamespace(next=("confirm",)))
    with (
        patch.object(orchestrator, "graph_for", return_value=graph),
        patch.object(orchestrator, "judge_message", new=AsyncMock()) as judge,
        patch.object(orchestrator, "_handle_coaching", new=AsyncMock()) as coaching,
        patch.object(orchestrator, "handle_meal_logging", new=AsyncMock()) as logging_,
        patch.object(orchestrator, "_record_turn", new=AsyncMock()) as record,
        patch.object(orchestrator, "_enqueue_fact_extraction") as facts,
    ):
        yield SimpleNamespace(
            graph=graph,
            judge=judge,
            coaching=coaching,
            logging=logging_,
            record=record,
            facts=facts,
        )


@pytest.fixture
def store(patch_get_session) -> Iterator[SimpleNamespace]:
    session = MagicMock()
    session.add = MagicMock()
    session.commit = AsyncMock()

    def _assign_id(row) -> None:
        row.id = "esc-1"

    session.add.side_effect = _assign_id
    patch_get_session(escalation, session)
    with patch.object(escalation, "notify_escalation") as task:
        yield SimpleNamespace(session=session, task=task)


async def _handle(text: str, **kwargs):
    return await orchestrator.handle_message(
        "user-1", text, "thread-1", checkpointer=MagicMock(), **kwargs
    )


def _assert_no_model_or_graph(paths: SimpleNamespace) -> None:
    paths.judge.assert_not_called()
    paths.graph.aget_state.assert_not_called()
    paths.coaching.assert_not_called()
    paths.logging.assert_not_called()
    paths.record.assert_not_called()
    paths.facts.assert_not_called()


async def test_match_returns_fixed_reply_and_stores_escalation(
    paths, store, monkeypatch
) -> None:
    monkeypatch.setenv("SAFETY_WEBHOOK_URL", "https://hooks.example/x")

    result = await _handle(FLAGGED)

    assert result["kind"] == "safety"
    assert result["status"] == "success"
    assert result["paused"] is False
    assert result["items"] == []
    assert "insulin" in result["message"].lower()
    _assert_no_model_or_graph(paths)
    row = store.session.add.call_args.args[0]
    assert row.message == FLAGGED
    assert row.rule_id == "stopped_insulin"
    assert row.notify_status == "pending"
    assert len(row.rules_version) == 64
    assert row.user_id == "user-1"
    store.session.commit.assert_awaited_once()
    store.task.delay.assert_called_once_with("esc-1")


async def test_match_with_paused_card_leaves_the_graph_alone(
    paths, store, monkeypatch
) -> None:
    monkeypatch.setenv("SAFETY_WEBHOOK_URL", "https://hooks.example/x")

    result = await _handle("I want to die", meal_type="lunch", action="confirm")

    assert result["kind"] == "safety"
    _assert_no_model_or_graph(paths)


async def test_text_sent_with_an_image_is_screened(paths, store, monkeypatch) -> None:
    monkeypatch.setenv("SAFETY_WEBHOOK_URL", "https://hooks.example/x")

    result = await _handle(FLAGGED, image_b64="abcd")

    assert result["kind"] == "safety"
    _assert_no_model_or_graph(paths)


async def test_unset_webhook_stores_no_recipient_and_enqueues_nothing(
    paths, store, monkeypatch
) -> None:
    monkeypatch.delenv("SAFETY_WEBHOOK_URL", raising=False)

    with patch.object(escalation.logfire, "error") as error:
        result = await _handle(FLAGGED)

    assert result["kind"] == "safety"
    assert store.session.add.call_args.args[0].notify_status == "no_recipient"
    store.task.delay.assert_not_called()
    error.assert_called_once()
    assert FLAGGED not in str(error.call_args)


async def test_store_failure_still_returns_the_fixed_reply(
    paths, store, monkeypatch
) -> None:
    monkeypatch.setenv("SAFETY_WEBHOOK_URL", "https://hooks.example/x")
    store.session.commit.side_effect = SQLAlchemyError("down")

    with patch.object(escalation.logfire, "error") as error:
        result = await _handle(FLAGGED)

    assert result["kind"] == "safety"
    store.task.delay.assert_not_called()
    error.assert_called_once()


async def test_unreadable_list_returns_fallback_and_calls_no_model(
    paths, store, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(tables, "clinical_dir", lambda directory=None: tmp_path)
    monkeypatch.setattr(red_flags, "clinical_dir", lambda directory=None: tmp_path)

    with patch.object(orchestrator.logfire, "error") as error:
        result = await _handle("2 eggs and toast")

    assert result["kind"] == "safety"
    assert result["message"] == red_flags.HARD_FALLBACK_TEXT
    _assert_no_model_or_graph(paths)
    store.session.add.assert_not_called()
    error.assert_called_once()


async def test_ordinary_message_takes_the_normal_path(paths, store) -> None:
    paths.graph.aget_state.return_value = SimpleNamespace(next=())
    paths.logging.return_value = {
        "status": "success",
        "message": "ok",
        "paused": False,
        "items": [],
    }
    decision = RouteDecision(
        intent="log_meal", path="judgment", judgment=None, offer_to_log=False
    )

    with patch.object(
        orchestrator, "route_message", new=AsyncMock(return_value=decision)
    ):
        result = await _handle("2 eggs and toast")

    assert "kind" not in result
    paths.graph.aget_state.assert_awaited_once()
    paths.logging.assert_awaited_once()
    paths.record.assert_awaited_once()
    store.session.add.assert_not_called()
    store.task.delay.assert_not_called()
