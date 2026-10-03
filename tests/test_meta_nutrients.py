"""Contract test for GET /meta/nutrients (spec 008 FR-015, contracts/
nutrients-catalogue.md)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.api import meta


def test_catalogue_endpoint_is_public_cacheable_and_complete(app_factory) -> None:
    client = TestClient(app_factory(meta.router, user_id=None))
    resp = client.get("/meta/nutrients")
    assert resp.status_code == 200
    assert "max-age=3600" in resp.headers["cache-control"]
    body = resp.json()
    assert body["version"] >= 1
    assert [g["id"] for g in body["groups"]] == [
        "carbs",
        "fat",
        "other",
        "vitamins",
        "minerals",
    ]
    assert len(body["nutrients"]) == 48
    for n in body["nutrients"]:
        assert not {"usda_names", "max_per_100g", "column"} & n.keys()
        assert {"key", "name", "unit", "group", "order", "direction"} <= n.keys()
    salt = next(n for n in body["nutrients"] if n["key"] == "salt")
    assert salt["derived"] == {"from": "sodium", "factor": 0.0025}
