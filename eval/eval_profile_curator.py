"""Offline-data eval for the profile curator prompt (live Gemini, no database).

Each case gives a starting profile and one conversation turn, and checks the
operations the curator model proposes. Only the model call is exercised:
nothing is read from or written to Postgres.

    PYTHONPATH=src python eval/eval_profile_curator.py [--runs N]

Exit code 1 when any case fails in any run.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Callable
from dataclasses import dataclass, field

from langchain_core.messages import HumanMessage, SystemMessage

from backend.agent.memory import MemoryFact, ProfileState
from backend.agent.memory_curator import (
    _CURATOR_SYSTEM,
    CuratorOp,
    _curator_llm,
    build_curator_input,
)

Check = Callable[[list[CuratorOp]], bool]


def _fact(handle_text: str, kind: str) -> MemoryFact:
    return MemoryFact(id=handle_text, fact=handle_text, kind=kind, source="stated")


def no_ops(ops: list[CuratorOp]) -> bool:
    return not ops


def adds(kind: str, *words: str) -> Check:
    """Some add/replace of this kind mentions every word."""

    def check(ops: list[CuratorOp]) -> bool:
        return any(
            op.action in ("add", "replace")
            and op.kind == kind
            and all(w in (op.fact or "").lower() for w in words)
            for op in ops
        )

    return check


def sets_diet(chip: str) -> Check:
    return lambda ops: any(op.action == "set_diet" and op.chip == chip for op in ops)


def leaves(ref: str) -> Check:
    """No replace/remove targets this handle."""
    return lambda ops: (
        not any(
            op.action in ("replace", "remove") and (op.ref or "").lower() == ref
            for op in ops
        )
    )


def touches(ref: str) -> Check:
    return lambda ops: not leaves(ref)(ops)


def never_adds(*words: str) -> Check:
    return lambda ops: (
        not any(
            op.action in ("add", "replace")
            and all(w in (op.fact or "").lower() for w in words)
            for op in ops
        )
    )


def all_of(*checks: Check) -> Check:
    return lambda ops: all(c(ops) for c in checks)


@dataclass
class Case:
    name: str
    user: str
    check: Check
    assistant: str = "Got it."
    state: ProfileState = field(default_factory=ProfileState)


CASES: list[Case] = [
    Case("plain log", "log 2 eggs and toast", no_ops, "Logged 290 kcal."),
    Case("one-off meal", "had a vegetarian lunch today: dal and rice", no_ops),
    Case("question", "should I avoid dairy?", no_ops, "Not unless it bothers you."),
    Case("hypothetical", "if I went vegan, would I get enough protein?", no_ops),
    Case("temporary", "I'm eating out tonight, what should I order?", no_ops),
    Case("medical", "I was diagnosed with type 2 diabetes last month", no_ops),
    Case(
        "assistant suggestion only",
        "what should I have for dinner?",
        no_ops,
        "Try grilled salmon with quinoa and broccoli.",
    ),
    Case("allergy", "I'm allergic to peanuts", adds("restriction", "peanut")),
    Case(
        "religious rule",
        "I don't eat pork for religious reasons",
        adds("restriction", "pork"),
    ),
    Case("dislike", "I hate mushrooms", adds("dislike", "mushroom")),
    Case("habit", "I usually skip breakfast", adds("habit", "breakfast")),
    Case(
        "context",
        "I cook for my family of four most nights",
        adds("context", "four"),
    ),
    Case("diet chip", "I'm gluten free", sets_diet("gluten_free")),
    Case(
        "diet chip contradicts a like",
        "I've gone vegetarian",
        all_of(sets_diet("vegetarian"), touches("m1")),
        state=ProfileState(facts=[_fact("Loves chicken", "like")]),
    ),
    Case(
        "update a like",
        "I've switched from oat milk to almond milk",
        all_of(touches("m1"), adds("like", "almond")),
        state=ProfileState(facts=[_fact("Prefers oat milk in coffee", "like")]),
    ),
    Case(
        "already known",
        "I can't stand mushrooms",
        no_ops,
        state=ProfileState(facts=[_fact("Dislikes mushrooms", "dislike")]),
    ),
    Case(
        "cannot loosen a restriction",
        "turns out I'm not allergic to peanuts after all",
        leaves("m1"),
        state=ProfileState(facts=[_fact("Allergic to peanuts", "restriction")]),
    ),
    Case(
        "implied by a diet setting",
        "as a vegetarian I don't eat meat",
        never_adds("meat"),
        state=ProfileState(diet_chips=["vegetarian"]),
    ),
    Case(
        "user removed it",
        "that curry was great, I love spicy food",
        never_adds("spicy"),
        state=ProfileState(tombstones=["Likes spicy food"]),
    ),
]


async def _run_case(case: Case) -> tuple[bool, list[CuratorOp]]:
    output = await _curator_llm.ainvoke(
        [
            SystemMessage(content=_CURATOR_SYSTEM),
            HumanMessage(
                content=build_curator_input(case.state, case.user, case.assistant)
            ),
        ]
    )
    return case.check(output.ops), output.ops


async def main(runs: int) -> int:
    failures = 0
    for run in range(1, runs + 1):
        results = await asyncio.gather(*(_run_case(c) for c in CASES))
        passed = sum(ok for ok, _ in results)
        print(f"run {run}: {passed}/{len(CASES)} passed")
        for case, (ok, ops) in zip(CASES, results, strict=True):
            if not ok:
                failures += 1
                dumped = [op.model_dump(exclude_none=True) for op in ops]
                print(f"  FAIL {case.name!r}: {case.user!r} -> {dumped}")
    return 1 if failures else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=1)
    sys.exit(asyncio.run(main(parser.parse_args().runs)))
