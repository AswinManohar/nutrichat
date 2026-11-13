"""GET/POST /profile per contracts/profile-api.md, against the local database."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import delete

from backend.api import profile as profile_api
from backend.config import get_tunables
from backend.safety import profile

PEANUT = {"allergen_group": "peanut"}


@pytest.fixture
async def client(
    app_factory: Callable[..., FastAPI], db_user: str
) -> AsyncIterator[httpx.AsyncClient]:
    app = app_factory(profile_api.router, user_id=db_user)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _create(client: httpx.AsyncClient, entry_type: str, value: dict, **extra):
    return await client.post(
        "/profile/entries", json={"type": entry_type, "value": value, **extra}
    )


async def test_empty_profile(client: httpx.AsyncClient) -> None:
    body = (await client.get("/profile")).json()

    assert body["hard"] == [] and body["soft"] == [] and body["pending_count"] == 0
    # No clinician role exists yet: a typed, always-empty list.
    assert body["care_team"] == []
    assert body["missing_values"] == []
    assert len(body["version"]) == 64


async def test_patient_entry_is_created_confirmed_and_listed(
    client: httpx.AsyncClient,
) -> None:
    empty_version = (await client.get("/profile")).json()["version"]
    resp = await _create(client, "allergy", PEANUT, client_request_id="c1")

    assert resp.status_code == 201
    entry = resp.json()
    assert entry["label"] == "Peanut allergy"
    assert (entry["source"], entry["state"]) == ("patient", "confirmed")
    assert entry["value"] == PEANUT and entry["retire_requested"] is False
    listed = (await client.get("/profile")).json()
    assert [e["id"] for e in listed["hard"]] == [entry["id"]]
    assert listed["version"] != empty_version


async def test_repeating_a_client_request_id_returns_the_first_entry(
    client: httpx.AsyncClient,
) -> None:
    first = (await _create(client, "allergy", PEANUT, client_request_id="c1")).json()
    second = (await _create(client, "allergy", PEANUT, client_request_id="c1")).json()

    assert first["id"] == second["id"]
    assert len((await client.get("/profile")).json()["hard"]) == 1


async def test_a_clinician_source_is_forbidden(client: httpx.AsyncClient) -> None:
    for source in ("clinician", "inferred"):
        resp = await _create(client, "allergy", PEANUT, source=source)
        assert resp.status_code == 403

    assert (await client.get("/profile")).json()["hard"] == []


async def test_invalid_bodies_are_422(client: httpx.AsyncClient) -> None:
    bad_value = await _create(client, "nutrient_limit", {"nutrient": "sodium"})
    bad_type = await _create(client, "mood", {})
    extra = await client.post(
        "/profile/entries", json={"type": "allergy", "value": PEANUT, "state": "x"}
    )

    assert bad_value.status_code == bad_type.status_code == extra.status_code == 422


async def test_editing_replaces_the_entry(client: httpx.AsyncClient) -> None:
    limit = {"nutrient": "sodium", "amount": 1500, "unit": "mg", "period": "per_day"}
    old = (await _create(client, "nutrient_limit", limit)).json()

    new = await _create(
        client, "nutrient_limit", {**limit, "amount": 1200}, replaces_id=old["id"]
    )

    assert new.status_code == 201
    history = (await client.get("/profile/history")).json()
    by_id = {e["id"]: e for e in history}
    assert by_id[old["id"]]["retired_reason"] == "replaced"
    assert by_id[new.json()["id"]]["replaces_id"] == old["id"]
    assert history[0]["id"] == new.json()["id"]  # newest first
    assert [e["id"] for e in (await client.get("/profile")).json()["hard"]] == [
        new.json()["id"]
    ]


async def test_retire_needs_confirm_true_and_is_idempotent(
    client: httpx.AsyncClient,
) -> None:
    entry = (await _create(client, "allergy", PEANUT)).json()
    url = f"/profile/entries/{entry['id']}/retire"

    assert (await client.post(url, json={})).status_code == 422
    assert (await client.post(url, json={"confirm": False})).status_code == 422
    first = await client.post(url, json={"confirm": True, "client_request_id": "r"})
    second = await client.post(url, json={"confirm": True, "client_request_id": "r"})

    assert first.status_code == second.status_code == 200
    assert first.json()["state"] == second.json()["state"] == "retired"
    assert (await client.get("/profile")).json()["hard"] == []


async def test_confirm_and_deny_follow_the_state_rules(
    client: httpx.AsyncClient, db_user: str
) -> None:
    pending = await profile.add_entry(
        db_user,
        profile.DietSettingValue(setting="vegan"),
        source="inferred",
        state="pending",
        created_by="curator",
    )
    other = await profile.add_entry(
        db_user,
        profile.DietSettingValue(setting="keto"),
        source="inferred",
        state="pending",
        created_by="curator",
    )
    body = (await client.get("/profile")).json()
    assert body["pending_count"] == 2

    first = await client.post(f"/profile/entries/{pending.id}/confirm")
    again = await client.post(f"/profile/entries/{pending.id}/confirm")
    denied = await client.post(f"/profile/entries/{other.id}/deny")
    denied_again = await client.post(f"/profile/entries/{other.id}/deny")

    assert first.json()["state"] == again.json()["state"] == "confirmed"
    assert denied.status_code == denied_again.status_code == 200
    assert denied.json()["state"] == "retired"
    # Conflicting states: 409.
    assert (await client.post(f"/profile/entries/{pending.id}/deny")).status_code == 409
    assert (
        await client.post(f"/profile/entries/{other.id}/confirm")
    ).status_code == 409
    assert (await client.get("/profile")).json()["pending_count"] == 0


async def test_unknown_and_foreign_entries_are_404(client: httpx.AsyncClient) -> None:
    missing = "00000000-0000-4000-8000-000000000000"

    for action in ("confirm", "deny"):
        assert (
            await client.post(f"/profile/entries/{missing}/{action}")
        ).status_code == 404
    retire = await client.post(
        f"/profile/entries/{missing}/retire", json={"confirm": True}
    )
    assert retire.status_code == 404
    assert (await client.post("/profile/entries/nope/confirm")).status_code == 404


async def test_a_full_profile_is_a_409(client: httpx.AsyncClient) -> None:
    class _Cap:
        class safety:  # noqa: N801 - mirrors the tunables attribute path
            hard_profile_max_entries = 1

    with patch("backend.safety.profile.get_tunables", return_value=_Cap):
        assert (await _create(client, "allergy", PEANUT)).status_code == 201
        full = await _create(client, "diet_setting", {"setting": "vegan"})

    assert full.status_code == 409


async def test_profile_reports_missing_values_for_a_declared_condition(
    client: httpx.AsyncClient,
) -> None:
    await _create(client, "diagnosis", {"condition": "ckd"})

    body = (await client.get("/profile")).json()

    assert "potassium limit for chronic kidney disease" in body["missing_values"]


async def test_limits_today_endpoint_shape(client: httpx.AsyncClient) -> None:
    await _create(
        client,
        "nutrient_limit",
        {"nutrient": "sodium", "amount": 1500, "unit": "mg", "period": "per_day"},
    )

    body = (await client.get("/profile/limits/today")).json()

    assert (body["on_track"], body["total"]) == (1, 1)
    assert set(body["limits"][0]) == {
        "entry_id",
        "nutrient",
        "label",
        "amount",
        "min_amount",
        "unit",
        "period",
        "so_far",
        "unknown_items",
        "on_track",
    }


async def test_profile_is_503_with_the_retry_text_when_it_cannot_load(
    client: httpx.AsyncClient,
) -> None:
    with patch(
        "backend.api.profile.profile.load_hard_profile",
        AsyncMock(side_effect=OSError("postgres down")),
    ):
        resp = await client.get("/profile")

    assert resp.status_code == 503
    assert resp.json()["detail"] == get_tunables().safety.profile_unavailable_text


async def _recommendation(user_id: str) -> str:
    from backend.db.models import Recommendation
    from backend.db.session import get_session

    row_id = str(uuid.uuid4())
    async with get_session()() as session:
        session.add(
            Recommendation(
                id=row_id,
                user_id=user_id,
                recipe={"name": "Soup"},
                check_snapshot={"passed": True},
                attempts=1,
                status="shown",
            )
        )
        await session.commit()
    return row_id


async def _stored(row_id: str):
    from backend.db.models import Recommendation
    from backend.db.session import get_session

    async with get_session()() as session:
        return await session.get(Recommendation, row_id)


async def test_meal_feedback_is_stored_and_idempotent(
    client: httpx.AsyncClient, db_user: str
) -> None:
    row_id = await _recommendation(db_user)
    url = f"/profile/meals/{row_id}/feedback"

    first = await client.post(url, json={"status": "rejected", "reason": "too salty"})
    again = await client.post(url, json={"status": "rejected", "reason": "too salty"})

    assert first.status_code == again.status_code == 200
    assert first.json() == {"recommendation_id": row_id, "status": "rejected"}
    row = await _stored(row_id)
    assert (row.status, row.rejection_reason) == ("rejected", "too salty")


async def test_accepting_after_rejecting_clears_the_reason(
    client: httpx.AsyncClient, db_user: str
) -> None:
    row_id = await _recommendation(db_user)
    url = f"/profile/meals/{row_id}/feedback"

    await client.post(url, json={"status": "rejected", "reason": "no time"})
    resp = await client.post(url, json={"status": "accepted"})

    assert resp.status_code == 200
    row = await _stored(row_id)
    assert (row.status, row.rejection_reason) == ("accepted", None)


async def test_meal_feedback_validates_the_body(
    client: httpx.AsyncClient, db_user: str
) -> None:
    url = f"/profile/meals/{await _recommendation(db_user)}/feedback"

    too_long = await client.post(url, json={"status": "rejected", "reason": "x" * 501})
    shown = await client.post(url, json={"status": "shown"})

    assert too_long.status_code == shown.status_code == 422


async def test_meal_feedback_for_an_unknown_or_foreign_recommendation_is_404(
    client: httpx.AsyncClient, db_user: str
) -> None:
    from backend.db.models import UserGoal
    from backend.db.session import get_session

    other = str(uuid.uuid4())
    async with get_session()() as session:
        session.add(UserGoal(user_id=other))
        await session.commit()
    try:
        foreign = await _recommendation(other)
        for target in (foreign, str(uuid.uuid4()), "not-a-uuid"):
            resp = await client.post(
                f"/profile/meals/{target}/feedback", json={"status": "accepted"}
            )
            assert resp.status_code == 404
        assert (await _stored(foreign)).status == "shown"
    finally:
        async with get_session()() as session:
            await session.execute(delete(UserGoal).where(UserGoal.user_id == other))
            await session.commit()


async def test_requests_without_a_token_are_401(
    app_factory: Callable[..., FastAPI], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-secret")
    app = app_factory(profile_api.router, user_id=None)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        assert (await c.get("/profile")).status_code == 401
