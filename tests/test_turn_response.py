"""The shared response shape every chat turn returns."""

from __future__ import annotations

from backend.agent.turn import turn_response


def test_default_shape() -> None:
    assert turn_response("hi") == {
        "status": "success",
        "message": "hi",
        "paused": False,
        "items": [],
    }


def test_paused_is_keyword_only_and_set() -> None:
    assert turn_response("card", paused=True)["paused"] is True


def test_extra_keys_follow_the_fixed_ones_in_order() -> None:
    out = turn_response("careful", kind="safety", meal_id="m1")

    assert list(out) == ["status", "message", "paused", "items", "kind", "meal_id"]
    assert out["kind"] == "safety"


def test_each_call_gets_its_own_items_list() -> None:
    first = turn_response("a")
    first["items"].append({"food_name": "egg"})

    assert turn_response("b")["items"] == []
