"""notify_escalation: payload, retries and status transitions (spec 013 R12)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from celery.exceptions import Retry

from backend.workers import tasks

URL = "https://hooks.example/secret-token"
MESSAGE = "I stopped my insulin, my name is Jane Doe jane@example.com"


def _row(status: str = "pending") -> SimpleNamespace:
    return SimpleNamespace(
        id="esc-1",
        user_id="user-1",
        message=MESSAGE,
        rule_id="stopped_insulin",
        rule_label="Stopped insulin",
        notify_status=status,
        notify_attempts=0,
        notified_at=None,
        created_at=datetime(2026, 11, 20, 10, 0, tzinfo=UTC),
    )


@pytest.fixture
def row(patch_get_session) -> SimpleNamespace:
    session = MagicMock()
    row = _row()
    session.get = AsyncMock(return_value=row)
    session.commit = AsyncMock()
    patch_get_session(tasks, session)
    return row


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SAFETY_WEBHOOK_URL", URL)
    monkeypatch.setenv("SAFETY_REVIEW_BASE_URL", "https://api.example/")


def _client(post: AsyncMock) -> MagicMock:
    client = MagicMock()
    client.post = post
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


def _post_with(status: int = 200, error: Exception | None = None):
    post = AsyncMock(
        return_value=httpx.Response(status, request=httpx.Request("POST", URL)),
        side_effect=error,
    )
    return post, patch.object(tasks.httpx, "AsyncClient", return_value=_client(post))


async def test_success_posts_ids_only_and_marks_sent(row) -> None:
    post, client = _post_with(200)

    with client as factory:
        outcome = await tasks._notify_escalation("esc-1", 0)

    assert outcome == "sent"
    assert row.notify_status == "sent"
    assert row.notify_attempts == 1
    assert row.notified_at is not None
    assert factory.call_args.kwargs["timeout"] == 5
    payload = post.call_args.kwargs["json"]
    assert post.call_args.args[0] == URL
    assert payload == {
        "text": (
            "Mealsy red flag: Stopped insulin. Patient user-1. "
            "Review: https://api.example/admin/review/escalations/esc-1"
        ),
        "escalation_id": "esc-1",
        "rule_id": "stopped_insulin",
        "patient_id": "user-1",
        "created_at": "2026-11-20T10:00:00+00:00",
    }
    blob = json.dumps(payload)
    assert "insulin," not in blob
    assert "Jane" not in blob and "example.com" not in blob.replace("api.example", "")


@pytest.mark.parametrize(
    "kwargs",
    [{"status": 500}, {"error": httpx.ConnectTimeout("boom " + URL)}],
)
async def test_failure_requests_a_retry(row, kwargs) -> None:
    _, client = _post_with(**kwargs)

    with client:
        outcome = await tasks._notify_escalation("esc-1", 2)

    assert outcome == "retry"
    assert row.notify_status == "pending"
    assert row.notify_attempts == 3


async def test_failure_after_the_last_retry_marks_failed_and_logs(row) -> None:
    _, client = _post_with(503)

    with client, patch.object(tasks.logfire, "error") as error:
        outcome = await tasks._notify_escalation("esc-1", 5)

    assert outcome == "failed"
    assert row.notify_status == "failed"
    error.assert_called_once()
    assert MESSAGE not in str(error.call_args) and URL not in str(error.call_args)


async def test_unset_url_marks_no_recipient_without_posting(
    row, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SAFETY_WEBHOOK_URL")
    post, client = _post_with(200)

    with client, patch.object(tasks.logfire, "error") as error:
        outcome = await tasks._notify_escalation("esc-1", 0)

    assert outcome == "no_recipient"
    assert row.notify_status == "no_recipient"
    post.assert_not_called()
    error.assert_called_once()


async def test_already_sent_row_is_not_posted_again(row) -> None:
    row.notify_status = "sent"
    post, client = _post_with(200)

    with client:
        assert await tasks._notify_escalation("esc-1", 1) == "sent"

    post.assert_not_called()


@pytest.mark.parametrize(
    "retries, countdown", [(0, 5), (1, 15), (2, 45), (3, 120), (4, 300)]
)
def test_task_retries_with_the_configured_backoff(retries, countdown) -> None:
    task = tasks.notify_escalation
    with (
        patch.object(tasks, "_run", return_value="retry"),
        patch.object(tasks, "_notify_escalation", new=MagicMock()),
        patch.object(task, "retry", side_effect=Retry()) as retry,
        pytest.raises(Retry),
    ):
        task.push_request(retries=retries)
        try:
            task.run("esc-1")
        finally:
            task.pop_request()

    assert retry.call_args.kwargs == {"countdown": countdown, "max_retries": 5}


def test_task_returns_the_outcome_when_done() -> None:
    with (
        patch.object(tasks, "_run", return_value="sent"),
        patch.object(tasks, "_notify_escalation", new=MagicMock()),
    ):
        assert tasks.notify_escalation.run("esc-1") == "sent"
