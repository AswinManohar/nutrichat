"""Eval for coaching with a curated profile (live Gemini, no database).

Two gates, both required at 100% before the profile is enabled for users:

1. Restrictions. For profiles with an allergy, a diet setting, a religious
   rule or a dislike, every snack / dinner / meal-plan suggestion must avoid
   the excluded foods, and the coach must make NO memory tool call (a
   spurious call would add a model round trip to an ordinary turn).
2. Memory requests. Explicit remember / forget / diet-change messages must
   call the right tool.

The response agent is called directly with a hand-built context, and the
memory tools' database write is replaced by a recorder, so nothing is read
from or written to Postgres.

    PYTHONPATH=src python eval/eval_profile_coaching.py [--runs N]

Exit code 1 when any case fails in any run. Word matching is literal, so
read each reported failure: "skip the peanuts" would be flagged.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
import uuid
from dataclasses import dataclass, field
from unittest.mock import patch

from backend.agent.coaching import generate_response
from backend.agent.context import ContextBundle, GoalSummary, build_system_prompt
from backend.agent.memory import ApplyOutcome, MemoryFact, MemoryOp, OpResult
from backend.db.redis_client import TodayTotals

_TOTALS = TodayTotals(kcal=1300, protein_g=60, fiber_g=12, n_meals=2)
_GOALS = {"kcal_goal": 2200, "protein_goal": 140, "fiber_goal": 30}

_MEAT = [
    "chicken",
    "beef",
    "pork",
    "bacon",
    "ham",
    "turkey",
    "lamb",
    "sausage",
    "salmon",
    "tuna",
    "fish",
    "shrimp",
    "prawn",
    "steak",
    "mutton",
]

_ASKS = [
    "what should I have for a snack?",
    "what should I have for dinner to hit my protein goal?",
    "give me a simple one-day meal plan that meets my goals",
]

# "peanut-free", "no peanuts", "without peanuts", "avoid peanuts" are fine.
_NEGATED = (
    r"(?:\b(?:no|not|without|avoid(?:ing|s)?|skip(?:ping)?|free of)\s+"
    r"(?:any\s+)?{w}\w*|\b{w}\w*[- ]free)"
)


def _fact(text: str, kind: str) -> MemoryFact:
    return MemoryFact(id=text, fact=text, kind=kind, source="stated")


@dataclass
class Profile:
    name: str
    forbidden: list[str]
    facts: list[MemoryFact] = field(default_factory=list)
    chips: list[str] = field(default_factory=list)


PROFILES = [
    Profile(
        "peanut allergy", ["peanut"], [_fact("Allergic to peanuts", "restriction")]
    ),
    Profile("vegetarian setting", _MEAT, chips=["vegetarian"]),
    Profile(
        "no pork",
        ["pork", "bacon", "ham", "sausage", "prosciutto", "chorizo"],
        [_fact("Does not eat pork for religious reasons", "restriction")],
    ),
    Profile(
        "dislikes mushrooms", ["mushroom"], [_fact("Dislikes mushrooms", "dislike")]
    ),
]


@dataclass
class MemoryCase:
    message: str
    tool: str
    arg_contains: str
    facts: list[MemoryFact] = field(default_factory=list)
    chips: list[str] = field(default_factory=list)


MEMORY_CASES = [
    MemoryCase("remember that I hate mushrooms", "add", "mushroom"),
    MemoryCase("please remember I'm allergic to shellfish", "add", "shellfish"),
    MemoryCase("don't suggest tofu to me again", "add", "tofu"),
    MemoryCase(
        "forget that I dislike mushrooms, I like them now",
        "remove",
        "Dislikes mushrooms",
        facts=[_fact("Dislikes mushrooms", "dislike")],
    ),
    MemoryCase(
        "I've gone vegetarian, keep that in mind", "set_diet_chip", "vegetarian"
    ),
    MemoryCase(
        "I'm not vegan any more",
        "set_diet_chip",
        "vegan",
        chips=["vegan"],
    ),
]


def _context(facts: list[MemoryFact], chips: list[str]) -> tuple[str, dict]:
    prefs = {chip: True for chip in chips}
    ctx = ContextBundle(
        today_totals=_TOTALS,
        goals=GoalSummary(dietary_prefs=prefs, streak_days=3, **_GOALS),
        profile_active=True,
        profile=facts,
    )
    data = {
        "today_totals": _TOTALS.model_dump(),
        "goals": {**_GOALS, "dietary_prefs": prefs},
        "period": {"days": 1, "label": "today"},
    }
    return build_system_prompt(ctx), data


def _violations(reply: str, forbidden: list[str]) -> list[str]:
    text = reply.lower()
    hits = []
    for word in forbidden:
        cleaned = re.sub(_NEGATED.format(w=re.escape(word)), " ", text)
        if re.search(rf"\b{re.escape(word)}", cleaned):
            hits.append(word)
    return hits


class _Recorder:
    """Stands in for the memory tools' database access, keyed by user id.

    Cases run concurrently under one patch, so each case gets its own user
    id and the recorder keeps their profiles and attempted ops apart.
    """

    def __init__(self) -> None:
        self.profiles: dict[str, list[MemoryFact]] = {}
        self.attempted: dict[str, list[MemoryOp]] = {}

    async def apply_ops(
        self, user_id: str, ops: list[MemoryOp], actor: str
    ) -> ApplyOutcome:
        self.attempted.setdefault(user_id, []).extend(ops)
        return ApplyOutcome(results=[OpResult(op=op, applied=True) for op in ops])

    async def load_profile(self, user_id: str) -> list[MemoryFact]:
        return self.profiles.get(user_id, [])


async def _ask(
    recorder: _Recorder, message: str, facts: list[MemoryFact], chips: list[str]
) -> tuple[str, list[MemoryOp]]:
    """Run one coaching reply; return it with the ops the tools tried to apply."""
    user_id = str(uuid.uuid4())
    recorder.profiles[user_id] = facts
    context_prompt, data = _context(facts, chips)
    reply = await generate_response(
        message, data, context_prompt=context_prompt, user_id=user_id
    )
    return reply, recorder.attempted.get(user_id, [])


def _op_text(op: MemoryOp) -> str:
    return " ".join(str(v) for v in op.model_dump().values()).lower()


async def _run_once() -> int:
    recorder = _Recorder()
    with (
        patch("backend.agent.coaching.profile_active", return_value=True),
        patch("backend.agent.memory_tools.apply_ops", recorder.apply_ops),
        patch("backend.agent.memory_tools.load_profile", recorder.load_profile),
    ):
        return await _score(recorder)


async def _score(recorder: _Recorder) -> int:
    failures = 0

    restriction_cases = [(p, ask) for p in PROFILES for ask in _ASKS]
    results = await asyncio.gather(
        *(_ask(recorder, ask, p.facts, p.chips) for p, ask in restriction_cases)
    )
    for (profile, ask), (reply, attempted) in zip(
        restriction_cases, results, strict=True
    ):
        hits = _violations(reply, profile.forbidden)
        if hits or attempted:
            failures += 1
            print(f"  FAIL [{profile.name}] {ask!r}")
            if hits:
                print(f"       suggested: {', '.join(hits)}")
            if attempted:
                print(f"       spurious tool call: {[_op_text(o) for o in attempted]}")
            print("       " + reply.replace("\n", "\n       "))
    print(
        f"restrictions: {len(restriction_cases) - failures}/"
        f"{len(restriction_cases)} passed"
    )

    memory_failures = 0
    results = await asyncio.gather(
        *(_ask(recorder, c.message, c.facts, c.chips) for c in MEMORY_CASES)
    )
    for case, (reply, attempted) in zip(MEMORY_CASES, results, strict=True):
        resolved = [
            # forget is resolved to a fact id; map it back to the fact text.
            _op_text(op) if op.op != "remove" else f"remove {op.id}".lower()
            for op in attempted
        ]
        ok = any(
            op.op == case.tool and case.arg_contains.lower() in text
            for op, text in zip(attempted, resolved, strict=True)
        )
        if not ok:
            memory_failures += 1
            print(f"  FAIL [memory] {case.message!r} -> {resolved or 'no tool call'}")
            print(f"       {reply}")
    print(
        f"memory requests: {len(MEMORY_CASES) - memory_failures}/"
        f"{len(MEMORY_CASES)} passed"
    )
    return failures + memory_failures


async def main(runs: int) -> int:
    total = 0
    for run in range(1, runs + 1):
        print(f"run {run}")
        total += await _run_once()
    return 1 if total else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=1)
    sys.exit(asyncio.run(main(parser.parse_args().runs)))
