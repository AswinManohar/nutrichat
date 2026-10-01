from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import nutrient_checkup
from backend.db.models import NutrientCheckup


@pytest.fixture
def client(app_factory: Callable[..., FastAPI]) -> TestClient:
    return TestClient(app_factory(nutrient_checkup.router, header_auth=True))


def _auth_headers(user_id: str) -> dict[str, str]:
    return {"X-Debug-User-Id": user_id}


@pytest.fixture
def checkup_session(
    make_session: Callable[..., MagicMock],
    mock_session_factory: Callable[[MagicMock], MagicMock],
) -> Callable[[NutrientCheckup | None], tuple[MagicMock, MagicMock]]:
    """Build (session, factory) whose execute().scalar_one_or_none() is row."""

    def build(row: NutrientCheckup | None) -> tuple[MagicMock, MagicMock]:
        exec_result = MagicMock()
        exec_result.scalar_one_or_none.return_value = row
        session = make_session()
        session.execute = AsyncMock(return_value=exec_result)
        return session, mock_session_factory(session)

    return build


def test_get_nutrient_checkup_returns_latest_row(
    client: TestClient, checkup_session: Callable[..., tuple[MagicMock, MagicMock]]
) -> None:
    row = NutrientCheckup(
        id="ck-1",
        user_id="user-1",
        date=date(2026, 6, 14),
        nutrients={
            "Protein": {
                "avg": 100.0,
                "prev_avg": 90.0,
                "unit": "g",
                "trend_pct": 0.111,
                "direction": "up",
                "rda_pct": 200.0,
            },
            "Vitamin C": {
                "avg": 0.0,
                "prev_avg": 0.0,
                "unit": "mg",
                "trend_pct": None,
                "direction": "flat",
                "rda_pct": 0.0,
            },
        },
        notable_nutrients=[
            {"name": "Protein", "rda_pct": 200.0, "status": "over"},
        ],
        summary_text=(
            "This week, your Protein intake is at 200% of the daily target — "
            "you're well above the daily target."
        ),
        generated_at=datetime(2026, 6, 15, 1, 30, tzinfo=UTC),
    )

    _, factory = checkup_session(row)

    with patch("backend.api.nutrient_checkup.get_session", return_value=factory):
        resp = client.get("/nutrient-checkup", headers=_auth_headers("user-1"))

    assert resp.status_code == 200
    body = resp.json()
    assert body["date"] == "2026-06-14"
    by_name = {item["name"]: item for item in body["nutrients"]}
    assert by_name["Protein"]["avg"] == 100.0
    assert by_name["Protein"]["direction"] == "up"
    assert by_name["Protein"]["rda_pct"] == 200.0
    assert by_name["Vitamin C"]["trend_pct"] is None
    assert body["notable"] == ["Protein"]
    assert body["summary_text"] == row.summary_text


def test_get_nutrient_checkup_tolerates_legacy_row_without_rda_pct(
    client: TestClient, checkup_session: Callable[..., tuple[MagicMock, MagicMock]]
) -> None:
    # Regression: rows persisted before rda_pct existed omit the key entirely;
    # the endpoint must still return 200 with rda_pct=null, not 500.
    row = NutrientCheckup(
        id="ck-old",
        user_id="user-1",
        date=date(2026, 6, 10),
        nutrients={
            "Iron": {
                "avg": 0.0,
                "prev_avg": 0.0,
                "unit": "mg",
                "trend_pct": None,
                "direction": "flat",
            }
        },
        notable_nutrients=[],
        summary_text=None,
        generated_at=datetime(2026, 6, 10, 1, 30, tzinfo=UTC),
    )
    _, factory = checkup_session(row)

    with patch("backend.api.nutrient_checkup.get_session", return_value=factory):
        resp = client.get("/nutrient-checkup", headers=_auth_headers("user-1"))

    assert resp.status_code == 200
    assert resp.json()["nutrients"][0]["rda_pct"] is None


def test_get_nutrient_checkup_404_when_none_yet(
    client: TestClient, checkup_session: Callable[..., tuple[MagicMock, MagicMock]]
) -> None:
    _, factory = checkup_session(None)

    with patch("backend.api.nutrient_checkup.get_session", return_value=factory):
        resp = client.get("/nutrient-checkup", headers=_auth_headers("user-1"))

    assert resp.status_code == 404


def test_pending_nudge_returns_summary_when_unseen(
    client: TestClient, checkup_session: Callable[..., tuple[MagicMock, MagicMock]]
) -> None:
    row = NutrientCheckup(
        id="ck-1",
        user_id="user-1",
        date=date(2026, 6, 14),
        nutrients={},
        notable_nutrients=[{"name": "Fiber", "rda_pct": 50.0, "status": "under"}],
        summary_text="This week, your Fiber intake is at 50% of the daily target.",
        chat_nudge_seen_at=None,
        generated_at=datetime(2026, 6, 15, 1, 30, tzinfo=UTC),
    )

    _, factory = checkup_session(row)

    with patch("backend.api.nutrient_checkup.get_session", return_value=factory):
        resp = client.get(
            "/nutrient-checkup/pending-nudge", headers=_auth_headers("user-1")
        )

    assert resp.status_code == 200
    assert resp.json() == {"summary_text": row.summary_text}


def test_pending_nudge_returns_none_when_already_seen(
    client: TestClient, checkup_session: Callable[..., tuple[MagicMock, MagicMock]]
) -> None:
    row = NutrientCheckup(
        id="ck-1",
        user_id="user-1",
        date=date(2026, 6, 14),
        nutrients={},
        notable_nutrients=[],
        summary_text="This week, your Fiber intake is at 50% of the daily target.",
        chat_nudge_seen_at=datetime(2026, 6, 15, 8, 0, tzinfo=UTC),
        generated_at=datetime(2026, 6, 15, 1, 30, tzinfo=UTC),
    )

    _, factory = checkup_session(row)

    with patch("backend.api.nutrient_checkup.get_session", return_value=factory):
        resp = client.get(
            "/nutrient-checkup/pending-nudge", headers=_auth_headers("user-1")
        )

    assert resp.status_code == 200
    assert resp.json() == {"summary_text": None}


def test_pending_nudge_returns_none_when_no_row(
    client: TestClient, checkup_session: Callable[..., tuple[MagicMock, MagicMock]]
) -> None:
    _, factory = checkup_session(None)

    with patch("backend.api.nutrient_checkup.get_session", return_value=factory):
        resp = client.get(
            "/nutrient-checkup/pending-nudge", headers=_auth_headers("user-1")
        )

    assert resp.status_code == 200
    assert resp.json() == {"summary_text": None}


def test_pending_nudge_ack_marks_seen(
    client: TestClient, checkup_session: Callable[..., tuple[MagicMock, MagicMock]]
) -> None:
    session, factory = checkup_session(None)

    with patch("backend.api.nutrient_checkup.get_session", return_value=factory):
        resp = client.post(
            "/nutrient-checkup/pending-nudge/ack", headers=_auth_headers("user-1")
        )

    assert resp.status_code == 204
    stmt = str(session.execute.call_args[0][0])
    assert "chat_nudge_seen_at" in stmt
    session.commit.assert_awaited()
