from __future__ import annotations

import json
from unittest.mock import patch

import httpx
import pytest

from backend.agent import memory_judge
from backend.agent.memory import (
    AddFact,
    MemoryFact,
    ProfileState,
    RemoveFact,
    ReplaceFact,
    SetDietChip,
)
from backend.agent.memory_judge import judge_ops, select_ops


def _state() -> ProfileState:
    return ProfileState(
        facts=[
            MemoryFact(id="id-b", fact="Loves chicken", kind="like", source="stated")
        ]
    )


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url="https://glide.test", transport=httpx.MockTransport(handler)
    )


def _answer(question: str, probability: float, status: int = 200) -> httpx.Response:
    return httpx.Response(
        status,
        json={
            "model": "glide",
            "answers": {
                question: {"type": "noul", "noul": probability, "confidence": 0.5}
            },
            "usage": {"input_tokens": 300, "output_tokens": 1},
            "token_usage": 301,
        },
    )


# --- select_ops: the deterministic save decision -------------------------------


def test_select_ops_keeps_only_ops_at_or_above_the_threshold() -> None:
    ops = [
        AddFact(fact="Allergic to peanuts", kind="restriction"),
        AddFact(fact="Likes salad", kind="like"),
        SetDietChip(chip="vegetarian", on=True),
        RemoveFact(id="id-b"),
    ]

    kept = select_ops(ops, [0.97, 0.12, 0.6, 0.59])

    assert kept == [
        AddFact(fact="Allergic to peanuts", kind="restriction", confidence=0.97),
        SetDietChip(chip="vegetarian", on=True),
    ]


def test_select_ops_stores_the_score_as_confidence_on_a_replacement() -> None:
    op = ReplaceFact(id="id-b", fact="Avoids chicken", kind="dislike")

    assert select_ops([op], [0.81]) == [op.model_copy(update={"confidence": 0.81})]


@pytest.mark.parametrize(("save_unjudged", "n_kept"), [(True, 1), (False, 0)])
def test_select_ops_unjudged_follows_the_tunable(
    save_unjudged: bool, n_kept: int
) -> None:
    op = AddFact(fact="Allergic to peanuts", kind="restriction")
    cfg = memory_judge._TUNABLES.memory.model_copy(
        update={"save_unjudged": save_unjudged}
    )

    with patch.object(memory_judge._TUNABLES, "memory", cfg):
        kept = select_ops([op], [None])

    assert len(kept) == n_kept
    assert all(k.confidence is None for k in kept)


# --- judge_ops: one GLiDE question per candidate ------------------------------


async def test_judge_ops_without_an_api_key_scores_nothing(monkeypatch) -> None:
    monkeypatch.delenv("FASTINO_API_KEY", raising=False)

    scores = await judge_ops("x", [AddFact(fact="Likes dal", kind="like")], _state())

    assert scores == [None]


async def test_judge_ops_asks_the_right_question_per_op() -> None:
    sent: list[tuple[str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        (question,) = body["questions"]
        sent.append((question, body["state"]))
        return _answer(question, 0.9 if question == "worth_remembering" else 0.7)

    ops = [
        AddFact(fact="Avoids chicken", kind="dislike"),
        SetDietChip(chip="gluten_free", on=True),
        RemoveFact(id="id-b"),
        RemoveFact(id="unknown"),
    ]

    with patch.object(
        memory_judge.glide, "make_client", return_value=_client(handler)
    ) as make:
        scores = await judge_ops("I've gone vegetarian", ops, _state())

    assert scores == [0.9, 0.9, 0.7, None]
    make.assert_called_once_with(5.0)
    message = "I've gone vegetarian"
    assert sorted(sent, key=lambda s: s[1]["candidate"]) == [
        ("worth_remembering", {"message": message, "candidate": "Avoids chicken"}),
        (
            "worth_remembering",
            {"message": message, "candidate": "Follows a gluten free diet"},
        ),
        ("no_longer_true", {"message": message, "candidate": "Loves chicken"}),
    ]


async def test_judge_ops_service_error_scores_none_for_that_op() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        candidate = json.loads(request.content)["state"]["candidate"]
        if candidate == "Likes dal":
            return _answer("worth_remembering", 0.0, status=503)
        return _answer("worth_remembering", 0.8)

    ops = [AddFact(fact="Likes dal", kind="like"), AddFact(fact="Vegan", kind="like")]

    with patch.object(memory_judge.glide, "make_client", return_value=_client(handler)):
        scores = await judge_ops("x", ops, _state())

    assert scores == [None, 0.8]
