"""The reviewer queue per contracts/review-api.md, against the local database."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from backend.api import profile as profile_api
from backend.api import review
from backend.auth.supabase import get_current_user_id
from backend.config import get_tunables
from backend.db.models import (
    ProfileEntry,
    Recommendation,
    RedFlagEscalation,
    ReviewItem,
)
from backend.db.session import get_session
from backend.safety import profile
from backend.safety.profile import _new_row

REVIEWER = str(uuid.uuid4())
ACTOR = f"reviewer:{REVIEWER}"
PEANUT = {"allergen_group": "peanut"}
SODIUM = {"nutrient": "sodium", "amount": 1500, "unit": "mg", "period": "per_day"}
ALL_DECISIONS = ("approved", "rejected", "edited", "handled")
EDIT_ALLERGY = {"type": "allergy", "value": {"allergen_group": "shellfish"}}
EDIT_LIMIT = {"type": "nutrient_limit", "value": SODIUM}


@pytest.fixture(autouse=True)
def reviewer_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REVIEWER_USER_IDS", f"someone-else, {REVIEWER.upper()}")


@pytest.fixture
async def client(
    app_factory: Callable[..., FastAPI], db_user: str
) -> AsyncIterator[httpx.AsyncClient]:
    app = app_factory(review.router, user_id=REVIEWER)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


async def _pending(
    user_id: str, *, evidence: str | None = None, created_at: datetime | None = None
) -> profile.HardEntry:
    async with get_session()() as session, session.begin():
        row = _new_row(
            user_id,
            profile.AllergyValue(allergen_group="peanut"),
            label=None,
            source="inferred",
            state="pending",
            created_by="curator",
            client_request_id=None,
        )
        row.evidence = evidence
        if created_at:
            row.created_at = created_at
        session.add(row)
    return await profile.get_entry(user_id, row.id)


async def _escalation(user_id: str, message: str = "my chest hurts") -> str:
    esc = RedFlagEscalation(
        id=str(uuid.uuid4()),
        user_id=user_id,
        message=message,
        rule_id="chest_pain",
        rule_label="Chest pain",
        rules_version="v1",
        notify_status="sent",
    )
    async with get_session()() as session, session.begin():
        session.add(esc)
    return esc.id


async def _stored_item(
    user_id: str, kind: str, subject_id: str | None = None, detail: dict | None = None
) -> str:
    item = ReviewItem(
        id=str(uuid.uuid4()),
        user_id=user_id,
        kind=kind,
        subject_id=subject_id or str(uuid.uuid4()),
        detail=detail,
    )
    async with get_session()() as session, session.begin():
        session.add(item)
    return item.id


async def _recommendation(user_id: str, name: str = "Rice bowl") -> str:
    rec = Recommendation(
        id=str(uuid.uuid4()),
        user_id=user_id,
        recipe={"name": name},
        check_snapshot={
            "passed": True,
            "attempt": 1,
            "applied": [{"phrase": "your peanut allergy"}],
        },
        attempts=1,
        status="shown",
    )
    async with get_session()() as session, session.begin():
        session.add(rec)
    return rec.id


async def _limit(user_id: str, amount: float) -> profile.HardEntry:
    return await profile.add_entry(
        user_id,
        profile.NutrientLimitValue(
            nutrient="sodium", amount=amount, unit="mg", period="per_day"
        ),
        source="patient",
        state="confirmed",
        created_by="patient",
    )


async def _conflict(user_id: str) -> tuple[str, list[profile.HardEntry]]:
    entries = [await _limit(user_id, 2000), await _limit(user_id, 1500)]
    item_id = await _stored_item(
        user_id,
        "rule_conflict",
        entries[0].id,
        {"entries": [e.id for e in entries], "note": "differ"},
    )
    return item_id, entries


async def _make(kind: str, user_id: str) -> str:
    """An open item of the kind; returns the id the decision route takes."""
    if kind == "pending_entry":
        return (await _pending(user_id)).id
    if kind == "escalation":
        return await _escalation(user_id)
    if kind == "rule_conflict":
        return (await _conflict(user_id))[0]
    if kind == "plan_sample":
        return await _stored_item(
            user_id, "plan_sample", await _recommendation(user_id)
        )
    return await _stored_item(user_id, "unknown_medication", detail={"medication": "X"})


async def _decide(client: httpx.AsyncClient, item_id: str, decision: str, **body):
    return await client.post(
        f"/admin/review/items/{item_id}/decision", json={"decision": decision, **body}
    )


async def _entries(user_id: str) -> list[ProfileEntry]:
    async with get_session()() as session:
        rows = await session.execute(
            select(ProfileEntry).where(ProfileEntry.user_id == user_id)
        )
        return list(rows.scalars())


# ---- access ---------------------------------------------------------------


async def test_a_non_reviewer_gets_403_on_every_route(
    app_factory: Callable[..., FastAPI], db_user: str
) -> None:
    app = app_factory(review.router, user_id=db_user)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        some = str(uuid.uuid4())
        responses = [
            await c.get("/admin/review/items"),
            await c.get(f"/admin/review/escalations/{some}"),
            await _decide(c, some, "handled"),
            await c.post(
                f"/admin/review/patients/{db_user}/entries",
                json={"type": "allergy", "value": PEANUT},
            ),
        ]

    assert [r.status_code for r in responses] == [403] * 4


async def test_nobody_is_a_reviewer_when_the_variable_is_unset(
    app_factory: Callable[..., FastAPI],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("REVIEWER_USER_IDS")
    app = app_factory(review.router, user_id=REVIEWER)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        assert (await c.get("/admin/review/items")).status_code == 403


async def test_a_missing_token_is_401_not_403(
    app_factory: Callable[..., FastAPI],
) -> None:
    app = app_factory(review.router, user_id=None)
    assert get_current_user_id not in app.dependency_overrides
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        assert (await c.get("/admin/review/items")).status_code == 401


# ---- the decision table ----------------------------------------------------

_TABLE: dict[str, set[str]] = {
    "pending_entry": {"approved", "rejected", "edited"},
    "rule_conflict": {"edited"},
    "escalation": {"handled"},
    "plan_sample": {"approved", "rejected"},
    "unknown_medication": {"handled"},
}


@pytest.mark.parametrize("kind", list(_TABLE))
async def test_combinations_outside_the_table_are_422_and_leave_the_item_open(
    client: httpx.AsyncClient, db_user: str, kind: str
) -> None:
    for decision in (d for d in ALL_DECISIONS if d not in _TABLE[kind]):
        item_id = await _make(kind, db_user)
        extra = {"edit": EDIT_LIMIT} if decision == "edited" else {}

        resp = await _decide(client, item_id, decision, comment="c", **extra)

        assert resp.status_code == 422, (kind, decision)
    open_ids = {
        i["id"] for i in (await client.get("/admin/review/items")).json()["items"]
    }
    assert item_id in open_ids


async def test_pending_entry_approved_confirms_it_as_the_reviewer(
    client: httpx.AsyncClient, db_user: str
) -> None:
    entry = await _pending(db_user)

    resp = await _decide(client, entry.id, "approved", comment="seen the report")

    assert resp.status_code == 200
    body = resp.json()
    assert (body["decision"], body["decided_by"]) == ("approved", ACTOR)
    assert (
        body["entry"]["state"] == "confirmed" and body["entry"]["source"] == "inferred"
    )
    [row] = await _entries(db_user)
    assert (row.state, row.confirmed_by) == ("confirmed", ACTOR)
    [item] = await _items_for(db_user, "pending_entry")
    assert (item.subject_id, item.decision, item.comment) == (
        entry.id,
        "approved",
        "seen the report",
    )
    assert item.decided_by == ACTOR and item.decided_at is not None


async def _items_for(user_id: str, kind: str) -> list[ReviewItem]:
    async with get_session()() as session:
        rows = await session.execute(
            select(ReviewItem).where(
                ReviewItem.user_id == user_id, ReviewItem.kind == kind
            )
        )
        return list(rows.scalars())


async def test_pending_entry_rejected_retires_it(
    client: httpx.AsyncClient, db_user: str
) -> None:
    entry = await _pending(db_user)

    resp = await _decide(client, entry.id, "rejected")

    assert resp.status_code == 200 and resp.json()["entry"] is None
    [row] = await _entries(db_user)
    assert (row.state, row.retired_by, row.retired_reason) == (
        "retired",
        ACTOR,
        "denied",
    )


async def test_pending_entry_edited_replaces_it_with_a_clinician_entry(
    client: httpx.AsyncClient, db_user: str
) -> None:
    entry = await _pending(db_user)

    resp = await _decide(client, entry.id, "edited", edit=EDIT_ALLERGY)

    assert resp.status_code == 200
    rows = {r.id: r for r in await _entries(db_user)}
    old = rows[entry.id]
    new = rows[resp.json()["entry"]["id"]]
    assert (old.state, old.retired_reason) == ("retired", "replaced")
    assert (new.state, new.source, new.created_by) == ("confirmed", "clinician", ACTOR)
    assert new.replaces_id == old.id and new.confirmed_by == ACTOR
    assert new.value == {"allergen_group": "shellfish"}


async def test_an_invalid_edit_is_422_and_changes_nothing(
    client: httpx.AsyncClient, db_user: str
) -> None:
    entry = await _pending(db_user)

    bad = await _decide(
        client, entry.id, "edited", edit={"type": "allergy", "value": {"x": 1}}
    )
    missing = await _decide(client, entry.id, "edited")
    extra = await _decide(client, entry.id, "approved", edit=EDIT_ALLERGY)

    assert [bad.status_code, missing.status_code, extra.status_code] == [422] * 3
    assert [r.state for r in await _entries(db_user)] == ["pending"]
    assert await _items_for(db_user, "pending_entry") == []


async def test_rule_conflict_edited_creates_the_clinician_limit_that_resolves_it(
    client: httpx.AsyncClient, db_user: str
) -> None:
    item_id, entries = await _conflict(db_user)

    resp = await _decide(client, item_id, "edited", edit=EDIT_LIMIT, comment="1500")

    assert resp.status_code == 200
    rows = {r.id: r for r in await _entries(db_user)}
    assert [rows[e.id].state for e in entries] == ["retired", "retired"]
    new = rows[resp.json()["entry"]["id"]]
    assert (new.entry_type, new.state, new.source, new.created_by) == (
        "nutrient_limit",
        "confirmed",
        "clinician",
        ACTOR,
    )
    assert new.replaces_id == entries[0].id
    [item] = await _items_for(db_user, "rule_conflict")
    assert (item.decision, item.decided_by) == ("edited", ACTOR)


async def test_rule_conflict_needs_a_nutrient_limit_edit(
    client: httpx.AsyncClient, db_user: str
) -> None:
    item_id, entries = await _conflict(db_user)

    wrong_type = await _decide(client, item_id, "edited", edit=EDIT_ALLERGY)
    no_edit = await _decide(client, item_id, "edited")

    assert (wrong_type.status_code, no_edit.status_code) == (422, 422)
    assert {r.state for r in await _entries(db_user)} == {"confirmed"}


async def test_escalation_handled_stores_decision_and_date(
    client: httpx.AsyncClient, db_user: str
) -> None:
    esc_id = await _escalation(db_user)

    resp = await _decide(client, esc_id, "handled", comment="called the patient")

    assert resp.status_code == 200 and resp.json()["id"] == esc_id
    [item] = await _items_for(db_user, "escalation")
    assert (item.subject_id, item.decision, item.comment) == (
        esc_id,
        "handled",
        "called the patient",
    )
    assert item.decided_at is not None and item.decided_by == ACTOR
    detail = (await client.get(f"/admin/review/escalations/{esc_id}")).json()
    assert detail["decision"] == "handled"


async def test_plan_sample_approved_stores_the_comment(
    client: httpx.AsyncClient, db_user: str
) -> None:
    item_id = await _make("plan_sample", db_user)

    assert (
        await _decide(client, item_id, "approved", comment="fine")
    ).status_code == 200

    [item] = await _items_for(db_user, "plan_sample")
    assert (item.decision, item.comment) == ("approved", "fine")


async def test_plan_sample_rejected_needs_a_comment(
    client: httpx.AsyncClient, db_user: str
) -> None:
    item_id = await _make("plan_sample", db_user)

    for body in ({}, {"comment": "   "}):
        assert (await _decide(client, item_id, "rejected", **body)).status_code == 422
    ok = await _decide(client, item_id, "rejected", comment="peanut oil")

    assert ok.status_code == 200
    [item] = await _items_for(db_user, "plan_sample")
    assert (item.decision, item.comment) == ("rejected", "peanut oil")


async def test_unknown_medication_handled(
    client: httpx.AsyncClient, db_user: str
) -> None:
    item_id = await _make("unknown_medication", db_user)

    resp = await _decide(client, item_id, "handled", comment="no table rule needed")

    assert resp.status_code == 200
    [item] = await _items_for(db_user, "unknown_medication")
    assert item.decision == "handled"


@pytest.mark.parametrize("kind", ["pending_entry", "escalation", "plan_sample"])
async def test_deciding_twice_is_409_and_keeps_the_first_decision(
    client: httpx.AsyncClient, db_user: str, kind: str
) -> None:
    item_id = await _make(kind, db_user)
    first = "handled" if kind == "escalation" else "approved"
    assert (await _decide(client, item_id, first)).status_code == 200

    again = await _decide(client, item_id, first)

    assert again.status_code == 409
    [item] = await _items_for(db_user, kind)
    assert item.decision == first


async def test_a_stored_item_can_be_decided_once_by_its_row_id(
    client: httpx.AsyncClient, db_user: str
) -> None:
    item_id = await _make("unknown_medication", db_user)

    assert (await _decide(client, item_id, "handled")).status_code == 200
    assert (await _decide(client, item_id, "handled")).status_code == 409


async def test_a_pending_entry_the_patient_already_settled_is_409(
    client: httpx.AsyncClient, db_user: str
) -> None:
    entry = await _pending(db_user)
    await profile.confirm(db_user, entry.id)

    assert (await _decide(client, entry.id, "approved")).status_code == 409


async def test_unknown_or_malformed_ids_are_404(client: httpx.AsyncClient) -> None:
    for bad in (str(uuid.uuid4()), "not-a-uuid"):
        assert (await _decide(client, bad, "handled")).status_code == 404
    assert (await client.get("/admin/review/escalations/zzz")).status_code == 404


async def test_the_edit_respects_the_profile_cap(
    client: httpx.AsyncClient, db_user: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_tunables().safety, "hard_profile_max_entries", 2)
    await _limit(db_user, 900)
    entry = await _pending(db_user)

    # Retiring the pending entry frees its slot, so an edit still fits.
    assert (
        await _decide(client, entry.id, "edited", edit=EDIT_ALLERGY)
    ).status_code == 200

    other = await _pending(db_user)
    assert await _entries(db_user)  # one more live entry would exceed the cap
    resp = await client.post(
        f"/admin/review/patients/{db_user}/entries",
        json={"type": "allergy", "value": PEANUT},
    )
    assert resp.status_code == 409
    assert other.state == "pending"


# ---- listing ---------------------------------------------------------------


async def test_listing_is_newest_first_filterable_and_pages(
    client: httpx.AsyncClient, db_user: str
) -> None:
    now = datetime.now(UTC)
    entry = await _pending(
        db_user,
        evidence="I found out I'm allergic",
        created_at=now - timedelta(minutes=4),
    )
    esc_id = await _escalation(db_user, message="secret message text")
    med_id = await _stored_item(
        db_user, "unknown_medication", detail={"medication": "Zorbitrex"}
    )
    plan_id = await _make("plan_sample", db_user)
    async with get_session()() as session, session.begin():
        esc = await session.get(RedFlagEscalation, esc_id)
        esc.created_at = now - timedelta(minutes=3)
        (await session.get(ReviewItem, med_id)).created_at = now - timedelta(minutes=2)
        (await session.get(ReviewItem, plan_id)).created_at = now - timedelta(minutes=1)

    body = (await client.get("/admin/review/items")).json()
    mine = [i for i in body["items"] if i["patient_id"] == db_user]

    assert [i["kind"] for i in mine] == [
        "plan_sample",
        "unknown_medication",
        "escalation",
        "pending_entry",
    ]
    by_kind = {i["kind"]: i for i in mine}
    assert by_kind["pending_entry"]["content"] == {
        "type": "allergy",
        "label": "Peanut allergy",
        "evidence": "I found out I'm allergic",
    }
    assert by_kind["pending_entry"]["id"] == entry.id
    assert by_kind["escalation"]["content"]["rule_label"] == "Chest pain"
    assert "secret message text" not in (await client.get("/admin/review/items")).text
    assert by_kind["plan_sample"]["content"]["recipe_name"] == "Rice bowl"
    assert by_kind["plan_sample"]["content"]["check"]["applied"] == [
        "your peanut allergy"
    ]
    assert by_kind["unknown_medication"]["content"] == {"medication": "Zorbitrex"}

    only = (
        await client.get("/admin/review/items", params={"kind": "escalation"})
    ).json()
    assert {i["kind"] for i in only["items"]} == {"escalation"}

    first = (await client.get("/admin/review/items", params={"limit": 1})).json()
    assert len(first["items"]) == 1 and first["next_before"] is not None
    second = (
        await client.get(
            "/admin/review/items", params={"limit": 1, "before": first["next_before"]}
        )
    ).json()
    assert second["items"][0]["id"] != first["items"][0]["id"]
    assert (
        await client.get("/admin/review/items", params={"limit": 101})
    ).status_code == 422


async def test_decided_items_leave_the_open_list_and_show_in_the_closed_one(
    client: httpx.AsyncClient, db_user: str
) -> None:
    entry = await _pending(db_user)
    await _decide(client, entry.id, "rejected", comment="not an allergy")

    open_ids = {
        i["id"] for i in (await client.get("/admin/review/items")).json()["items"]
    }
    closed = (await client.get("/admin/review/items", params={"open": "false"})).json()

    assert entry.id not in open_ids
    [mine] = [i for i in closed["items"] if i["patient_id"] == db_user]
    assert (mine["id"], mine["decision"], mine["comment"]) == (
        entry.id,
        "rejected",
        "not an allergy",
    )


async def test_the_escalation_detail_is_the_only_place_with_the_message(
    client: httpx.AsyncClient, db_user: str
) -> None:
    esc_id = await _escalation(db_user, message="my chest hurts")

    listing = (
        await client.get("/admin/review/items", params={"kind": "escalation"})
    ).text
    detail = (await client.get(f"/admin/review/escalations/{esc_id}")).json()

    assert "my chest hurts" not in listing
    assert detail["message"] == "my chest hurts"
    assert (detail["rule_id"], detail["notify_status"], detail["decision"]) == (
        "chest_pain",
        "sent",
        None,
    )
    assert detail["patient_id"] == db_user


# ---- clinician entries -----------------------------------------------------


async def test_a_reviewer_adds_a_confirmed_clinician_entry(
    client: httpx.AsyncClient, db_user: str
) -> None:
    resp = await client.post(
        f"/admin/review/patients/{db_user}/entries",
        json={"type": "nutrient_limit", "value": SODIUM},
    )

    assert resp.status_code == 201
    body = resp.json()
    assert (body["source"], body["state"], body["created_by"]) == (
        "clinician",
        "confirmed",
        ACTOR,
    )
    [row] = await _entries(db_user)
    assert row.confirmed_by == ACTOR


async def test_clinician_entry_errors(client: httpx.AsyncClient, db_user: str) -> None:
    bad = await client.post(
        f"/admin/review/patients/{db_user}/entries",
        json={"type": "nutrient_limit", "value": {"nutrient": "sodium"}},
    )
    unknown = await client.post(
        f"/admin/review/patients/{uuid.uuid4()}/entries",
        json={"type": "allergy", "value": PEANUT},
    )

    assert (bad.status_code, unknown.status_code) == (422, 404)
    assert await _entries(db_user) == []


async def test_patients_cannot_create_clinician_entries_through_the_profile_api(
    app_factory: Callable[..., FastAPI], db_user: str
) -> None:
    app = app_factory(profile_api.router, user_id=REVIEWER)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        resp = await c.post(
            "/profile/entries",
            json={"type": "allergy", "value": PEANUT, "source": "clinician"},
        )

    assert resp.status_code == 403
