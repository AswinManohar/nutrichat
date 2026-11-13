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
from backend.db.session import get_session
from backend.ratelimit import RateLimitResult
from backend.safety import profile

PEANUT = {"allergen_group": "peanut"}
_SODIUM = {"nutrient": "sodium", "amount": 1500, "unit": "mg", "period": "per_day"}


@pytest.fixture(autouse=True)
def _no_rate_limit():
    with patch(
        "backend.ratelimit.check_rate_limit",
        new_callable=AsyncMock,
        return_value=RateLimitResult(allowed=True, remaining=9),
    ):
        yield


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


# --- soft preferences, meal history and export (spec 013 US5) -------------------


async def _remember(user_id: str, text: str, kind: str = "like") -> str:
    from backend.agent.memory import AddFact, apply_ops, load_state

    await apply_ops(user_id, [AddFact(fact=text, kind=kind)], "user")
    facts = (await load_state(user_id)).facts
    return next(f.id for f in facts if f.fact == text)


async def test_a_soft_fact_is_listed_with_its_dates(
    client: httpx.AsyncClient, db_user: str
) -> None:
    await _remember(db_user, "Dal")

    [fact] = (await client.get("/profile")).json()["soft"]

    assert (fact["kind"], fact["text"], fact["source"]) == ("like", "Dal", "stated")
    assert fact["created_at"] and fact["updated_at"]


async def test_patching_a_soft_fact_edits_its_text_and_kind(
    client: httpx.AsyncClient, db_user: str
) -> None:
    fact_id = await _remember(db_user, "Cooks 30 minutes", "habit")

    resp = await client.patch(
        f"/profile/soft/{fact_id}",
        json={"text": "Cooks 15 minutes on weekdays", "kind": "cooking_time"},
    )

    assert resp.status_code == 200
    assert resp.json()["id"] == fact_id
    assert resp.json()["kind"] == "cooking_time"
    assert resp.json()["text"] == "Cooks 15 minutes on weekdays"
    [listed] = (await client.get("/profile")).json()["soft"]
    assert listed["text"] == "Cooks 15 minutes on weekdays"


async def test_patching_only_the_kind_keeps_the_text(
    client: httpx.AsyncClient, db_user: str
) -> None:
    fact_id = await _remember(db_user, "Thai", "like")

    resp = await client.patch(f"/profile/soft/{fact_id}", json={"kind": "cuisine"})

    assert (resp.json()["text"], resp.json()["kind"]) == ("Thai", "cuisine")


async def test_patching_into_an_existing_preference_merges_the_two(
    client: httpx.AsyncClient, db_user: str
) -> None:
    await _remember(db_user, "Thai", "cuisine")
    other = await _remember(db_user, "Thai food", "like")

    resp = await client.patch(f"/profile/soft/{other}", json={"text": "thai"})

    assert resp.status_code == 200 and resp.json()["text"] == "Thai"
    assert len((await client.get("/profile")).json()["soft"]) == 1


async def test_soft_patch_validation_and_unknown_ids(
    client: httpx.AsyncClient, db_user: str
) -> None:
    fact_id = await _remember(db_user, "Dal")
    missing = "00000000-0000-4000-8000-000000000000"

    assert (await client.patch(f"/profile/soft/{fact_id}", json={})).status_code == 422
    assert (
        await client.patch(f"/profile/soft/{fact_id}", json={"kind": "restriction"})
    ).status_code == 422
    assert (
        await client.patch(f"/profile/soft/{fact_id}", json={"text": "x" * 201})
    ).status_code == 422
    assert (
        await client.patch(f"/profile/soft/{missing}", json={"text": "Rice"})
    ).status_code == 404
    assert (
        await client.patch("/profile/soft/nope", json={"text": "Rice"})
    ).status_code == 404


async def test_deleting_a_soft_fact_is_idempotent_and_not_relearned(
    client: httpx.AsyncClient, db_user: str
) -> None:
    from backend.agent.memory import AddFact, apply_ops

    fact_id = await _remember(db_user, "Coriander", "dislike")

    first = await client.delete(f"/profile/soft/{fact_id}")
    again = await client.delete(f"/profile/soft/{fact_id}")

    assert first.status_code == again.status_code == 204
    assert (await client.get("/profile")).json()["soft"] == []
    # The curator may not learn it again; the patient restating it may.
    learned = await apply_ops(
        db_user, [AddFact(fact="Coriander", kind="dislike")], "curator"
    )
    assert learned.n_applied == 0
    restated = await apply_ops(
        db_user, [AddFact(fact="Coriander", kind="dislike")], "user"
    )
    assert restated.n_applied == 1
    assert (await client.delete("/profile/soft/nope")).status_code == 404


async def test_the_soft_routes_only_touch_the_callers_facts(
    client: httpx.AsyncClient, db_user: str
) -> None:
    from backend.db.models import UserGoal

    other = str(uuid.uuid4())
    async with get_session()() as session:
        session.add(UserGoal(user_id=other))
        await session.commit()
    try:
        theirs = await _remember(other, "Liver", "dislike")

        patched = await client.patch(f"/profile/soft/{theirs}", json={"text": "Kale"})
        deleted = await client.delete(f"/profile/soft/{theirs}")
        from backend.agent.memory import load_state

        still = (await load_state(other)).facts
    finally:
        async with get_session()() as session:
            await session.execute(delete(UserGoal).where(UserGoal.user_id == other))
            await session.commit()

    assert patched.status_code == 404 and deleted.status_code == 204
    assert [f.fact for f in still] == ["Liver"]


async def _seed_meals(user_id: str) -> None:
    from datetime import UTC, datetime, timedelta

    from backend.db.models import MealLog, Recommendation

    old = datetime.now(UTC) - timedelta(days=40)
    async with get_session()() as session:
        session.add_all(
            [
                Recommendation(
                    user_id=user_id,
                    recipe={"name": "Lemon chicken"},
                    check_snapshot={},
                    attempts=1,
                    status="rejected",
                    rejection_reason="too bland",
                ),
                Recommendation(
                    user_id=user_id,
                    recipe={"name": "Dal"},
                    check_snapshot={},
                    attempts=1,
                    status="accepted",
                ),
                Recommendation(
                    user_id=user_id,
                    recipe={"name": "Ancient stew"},
                    check_snapshot={},
                    attempts=1,
                    status="shown",
                    created_at=old,
                ),
                MealLog(
                    user_id=user_id,
                    meal_type="lunch",
                    kcal=1,
                    protein_g=1,
                    carbs_g=1,
                    fat_g=1,
                    fiber_g=1,
                    label="Oatmeal",
                ),
                MealLog(
                    user_id=user_id,
                    meal_type="lunch",
                    kcal=1,
                    protein_g=1,
                    carbs_g=1,
                    fat_g=1,
                    fiber_g=1,
                    label="Old toast",
                    logged_at=old,
                ),
            ]
        )
        await session.commit()


async def test_meals_lists_the_window_with_status_and_reason(
    client: httpx.AsyncClient, db_user: str
) -> None:
    await _seed_meals(db_user)

    body = (await client.get("/profile/meals")).json()

    assert body["days"] == 21
    by_name = {r["name"]: r for r in body["recommendations"]}
    assert set(by_name) == {"Lemon chicken", "Dal"}
    assert by_name["Lemon chicken"]["status"] == "rejected"
    assert by_name["Lemon chicken"]["rejection_reason"] == "too bland"
    assert by_name["Dal"]["status"] == "accepted"
    assert [m["label"] for m in body["eaten"]] == ["Oatmeal"]
    wide = (await client.get("/profile/meals?days=90")).json()
    assert len(wide["recommendations"]) == 3
    assert {m["label"] for m in wide["eaten"]} == {"Oatmeal", "Old toast"}


async def test_meals_days_is_bounded(client: httpx.AsyncClient) -> None:
    assert (await client.get("/profile/meals?days=90")).status_code == 200
    assert (await client.get("/profile/meals?days=91")).status_code == 422
    assert (await client.get("/profile/meals?days=0")).status_code == 422


async def test_export_is_a_json_attachment_of_everything_remembered(
    client: httpx.AsyncClient, db_user: str
) -> None:
    from backend.db.models import RedFlagEscalation

    old = (await _create(client, "nutrient_limit", _SODIUM)).json()
    await _create(
        client, "nutrient_limit", {**_SODIUM, "amount": 1200}, replaces_id=old["id"]
    )
    await _remember(db_user, "Dal")
    gone = await _remember(db_user, "Coriander", "dislike")
    await client.delete(f"/profile/soft/{gone}")
    await _seed_meals(db_user)
    async with get_session()() as session:
        session.add(
            RedFlagEscalation(
                user_id=db_user,
                message="I stopped my insulin",
                rule_id="r1",
                rule_label="Stopped insulin",
                rules_version="v1",
                notify_status="sent",
            )
        )
        await session.commit()

    resp = await client.get("/profile/export")

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/json"
    assert resp.headers["content-disposition"] == (
        'attachment; filename="mealsy-profile.json"'
    )
    body = resp.json()
    assert len(body["hard"]) == 2  # the retired entry is part of the history
    assert {e["retired_reason"] for e in body["hard"]} == {None, "replaced"}
    assert [f["text"] for f in body["soft"]] == ["Dal"]
    assert "Coriander" not in resp.text
    assert {r["status"] for r in body["recommendations"]} == {
        "rejected",
        "accepted",
        "shown",
    }
    [escalation] = body["escalations"]
    assert escalation["rule_label"] == "Stopped insulin"
    assert escalation["message"] == "I stopped my insulin"
    assert escalation["notify_status"] == "sent"


async def test_export_of_an_empty_profile_has_empty_lists(
    client: httpx.AsyncClient,
) -> None:
    body = (await client.get("/profile/export")).json()

    assert (body["hard"], body["soft"], body["recommendations"]) == ([], [], [])
    assert body["escalations"] == []


def test_the_old_memory_routes_are_marked_deprecated() -> None:
    from backend.api import memory

    flags = {route.path: route.deprecated for route in memory.router.routes}

    assert flags == {"/memory": True, "/memory/{fact_id}": True}
