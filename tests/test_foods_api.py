"""Contract tests for GET /foods/search and GET /foods/{fdc_id} (spec 003).

T002 finding: `resolve_local`/`usda_local.lookup` is a synchronous SQLite
read. The only existing async call site, `_fetch_one` in
`backend/agent/tools/usda.py` (~line 496), already wraps it in
`asyncio.to_thread(usda_local.lookup, entity.food_name, ...)` before
awaiting it -- it is never called directly from an `async def` without that
wrapper. The new `GET /foods/search` and `GET /foods/{fdc_id}` endpoints
(T017-T018) must follow the same pattern: call `usda_local.search_foods`
and `usda_local.get_food` via `asyncio.to_thread`, never directly, per
research R8 and `.claude/CLAUDE.md`'s "never call blocking functions from
async code" rule.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.agent.tools import usda_local
from backend.api import foods
from backend.scripts.build_usda_db import create_schema, insert_food_row

_ROWS: list[tuple[int, str]] = [
    (1017, "Shrimp toast"),
    (1018, "Bread, white, toasted"),
]

_SAMPLE_MACROS = {
    "kcal": 293.0,
    "protein_g": 9.0,
    "carbs_g": 50.0,
    "fat_g": 3.5,
    "fiber_g": 2.0,
    "sugar_g": 5.0,
    "sat_fat_g": 0.8,
}

_SAMPLE_NUTRIENTS = {
    "Energy": {"amount": 293.0, "unit": "kcal"},
    "Protein": {"amount": 9.0, "unit": "g"},
}


def _build_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    try:
        create_schema(conn)
        for fdc_id, description in _ROWS:
            insert_food_row(
                conn,
                fdc_id,
                description,
                "sr_legacy_food",
                None,
                None,
                _SAMPLE_MACROS,
                _SAMPLE_NUTRIENTS,
            )
        conn.execute(
            "INSERT INTO food_fts(rowid, description) "
            "SELECT fdc_id, description FROM food"
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def fixture_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    db_path = tmp_path / "usda_fdc.sqlite3"
    _build_db(db_path)
    monkeypatch.setenv("USDA_DB_PATH", str(db_path))
    usda_local._local = usda_local.threading.local()
    yield db_path
    usda_local._local = usda_local.threading.local()


@pytest.fixture
def client(fixture_db: Path, app_factory) -> TestClient:
    return TestClient(app_factory(foods.router))


# --------------------------------------------------------------------------
# GET /foods/search
# --------------------------------------------------------------------------


def test_search_requires_auth(fixture_db: Path, app_factory) -> None:
    client = TestClient(app_factory(foods.router, user_id=None))
    resp = client.get("/foods/search", params={"q": "toast"})
    assert resp.status_code == 401


def test_search_query_too_short_is_422(client: TestClient) -> None:
    resp = client.get("/foods/search", params={"q": "t"})
    assert resp.status_code == 422


def test_search_qty_g_out_of_range_is_422(client: TestClient) -> None:
    resp = client.get("/foods/search", params={"q": "toast", "qty_g": 0})
    assert resp.status_code == 422
    resp = client.get("/foods/search", params={"q": "toast", "qty_g": 5001})
    assert resp.status_code == 422


def test_search_qty_g_defaults_to_100(client: TestClient) -> None:
    resp = client.get("/foods/search", params={"q": "toast"})
    assert resp.status_code == 200
    body = resp.json()
    top = body["results"][0]
    assert top["kcal"] == top["kcal_per_100g"]


def test_search_limit_out_of_range_is_422(client: TestClient) -> None:
    resp = client.get("/foods/search", params={"q": "toast", "limit": 0})
    assert resp.status_code == 422
    resp = client.get("/foods/search", params={"q": "toast", "limit": 21})
    assert resp.status_code == 422


def test_search_response_shape_and_scaling(client: TestClient) -> None:
    resp = client.get(
        "/foods/search", params={"q": "white bread toasted", "qty_g": 28}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["query"] == "white bread toasted"
    assert "normalized_query" in body
    assert body["results"], "expected at least one result"
    top = body["results"][0]
    for key in (
        "fdc_id",
        "name",
        "data_type",
        "kcal_per_100g",
        "protein_g_per_100g",
        "kcal",
        "protein_g",
    ):
        assert key in top
    expected_kcal = round(top["kcal_per_100g"] * 28 / 100, 1)
    assert top["kcal"] == expected_kcal


def test_search_toasted_bread_ranks_above_shrimp_toast(client: TestClient) -> None:
    resp = client.get("/foods/search", params={"q": "toast"})
    assert resp.status_code == 200
    names = [r["name"] for r in resp.json()["results"]]
    toasted_idx = next(i for i, n in enumerate(names) if "toasted" in n.lower())
    shrimp_idx = next(
        (i for i, n in enumerate(names) if "shrimp" in n.lower()), len(names)
    )
    assert toasted_idx < shrimp_idx


def test_search_no_match_returns_empty_results(client: TestClient) -> None:
    resp = client.get("/foods/search", params={"q": "zzqqxxnonsense"})
    assert resp.status_code == 200
    assert resp.json()["results"] == []


def test_search_503_when_db_unavailable(
    monkeypatch: pytest.MonkeyPatch, app_factory
) -> None:
    monkeypatch.setenv("USDA_DB_PATH", "/nonexistent/path/usda.sqlite3")
    usda_local._local = usda_local.threading.local()
    client = TestClient(app_factory(foods.router))
    resp = client.get("/foods/search", params={"q": "toast"})
    assert resp.status_code == 503
    assert resp.json()["detail"] == "food_search_unavailable"
    usda_local._local = usda_local.threading.local()


# --------------------------------------------------------------------------
# GET /foods/{fdc_id}
# --------------------------------------------------------------------------


def test_get_food_requires_qty_g(client: TestClient) -> None:
    resp = client.get("/foods/1018")
    assert resp.status_code == 422


def test_get_food_qty_g_out_of_range_is_422(client: TestClient) -> None:
    resp = client.get("/foods/1018", params={"qty_g": 0})
    assert resp.status_code == 422
    resp = client.get("/foods/1018", params={"qty_g": 5001})
    assert resp.status_code == 422


def test_get_food_returns_card_item_shape(client: TestClient) -> None:
    resp = client.get("/foods/1018", params={"qty_g": 28})
    assert resp.status_code == 200
    body = resp.json()
    assert body["fdc_id"] == 1018
    assert body["qty_g"] == 28
    assert body["source"] == "usda_local"
    assert body["estimated"] is False
    assert body["match_confidence"] == 1.0
    assert body["candidates"] == []
    assert body["candidate_details"] == []
    expected_kcal = round(_SAMPLE_MACROS["kcal"] * 28 / 100, 2)
    assert body["kcal"] == expected_kcal
    assert "nutrients" not in body  # spec 008: no raw per-item map
    assert set(body["micros"]) >= {"iron", "sodium", "vitamin_c"}


def test_get_food_unknown_fdc_id_is_404(client: TestClient) -> None:
    resp = client.get("/foods/9999999", params={"qty_g": 100})
    assert resp.status_code == 404


def test_get_food_503_when_db_unavailable(
    monkeypatch: pytest.MonkeyPatch, app_factory
) -> None:
    monkeypatch.setenv("USDA_DB_PATH", "/nonexistent/path/usda.sqlite3")
    usda_local._local = usda_local.threading.local()
    client = TestClient(app_factory(foods.router))
    resp = client.get("/foods/1018", params={"qty_g": 100})
    assert resp.status_code == 503
    usda_local._local = usda_local.threading.local()
