from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx2
import pytest
from typesafe_sdk import TypeSafeInternalServerError

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


def _client(side_effect) -> MagicMock:
    client = MagicMock()
    client.system_one = AsyncMock(side_effect=side_effect)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


def _answer(question: str, probability: float) -> SimpleNamespace:
    return SimpleNamespace(nouls={question: SimpleNamespace(noul=probability)})


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


# --- judge_ops: one Jev question per candidate -------------------------------------


async def test_judge_ops_without_an_api_key_scores_nothing(monkeypatch) -> None:
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)

    scores = await judge_ops("x", [AddFact(fact="Likes dal", kind="like")], _state())

    assert scores == [None]


async def test_judge_ops_asks_the_right_question_per_op(monkeypatch) -> None:
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")

    async def answer(state: dict, questions: dict) -> SimpleNamespace:
        (question,) = questions
        return _answer(question, 0.9 if question == "worth_remembering" else 0.7)

    client = _client(answer)
    ops = [
        AddFact(fact="Avoids chicken", kind="dislike"),
        SetDietChip(chip="gluten_free", on=True),
        RemoveFact(id="id-b"),
        RemoveFact(id="unknown"),
    ]

    with patch.object(memory_judge, "AsyncTypeSafeClient", return_value=client):
        scores = await judge_ops("I've gone vegetarian", ops, _state())

    assert scores == [0.9, 0.9, 0.7, None]
    sent = [
        (next(iter(call.args[1])), call.args[0])
        for call in client.system_one.await_args_list
    ]
    message = "I've gone vegetarian"
    assert sent == [
        ("worth_remembering", {"message": message, "candidate": "Avoids chicken"}),
        (
            "worth_remembering",
            {"message": message, "candidate": "Follows a gluten free diet"},
        ),
        ("no_longer_true", {"message": message, "candidate": "Loves chicken"}),
    ]


async def test_judge_ops_service_error_scores_none_for_that_op(monkeypatch) -> None:
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    error = TypeSafeInternalServerError(500, {}, httpx2.Headers(), message="boom")
    client = _client([error, _answer("worth_remembering", 0.8)])
    ops = [AddFact(fact="Likes dal", kind="like"), AddFact(fact="Vegan", kind="like")]

    with patch.object(memory_judge, "AsyncTypeSafeClient", return_value=client):
        scores = await judge_ops("x", ops, _state())

    assert scores == [None, 0.8]
