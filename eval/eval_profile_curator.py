"""Offline-data eval for the profile curator prompt (live Gemini, no database).

Each case gives a starting profile (soft facts and hard entries) and one
conversation turn, and checks the soft operations, hard drafts and retirements
the curator model proposes; every hard draft must also quote the user's
message. Only the model call is exercised: nothing is read from or written to
Postgres.

    PYTHONPATH=src python eval/eval_profile_curator.py [--runs N]

Exit code 1 when any case fails in any run.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from langchain_core.messages import HumanMessage, SystemMessage

from backend.agent.memory import MemoryFact, ProfileState
from backend.agent.memory_curator import (
    _CURATOR_SYSTEM,
    CuratorOutput,
    _curator_llm,
    build_curator_input,
    evidence_in,
)
from backend.safety import profile
from backend.safety.profile import HardEntry
from backend.safety.tables import load_tables

Check = Callable[[CuratorOutput], bool]


def _fact(handle_text: str, kind: str) -> MemoryFact:
    return MemoryFact(id=handle_text, fact=handle_text, kind=kind, source="stated")


def _entry(value: profile.EntryValue, state: str = "confirmed") -> HardEntry:
    now = datetime(2026, 11, 1, tzinfo=UTC)
    return HardEntry(
        id=f"entry-{value.model_dump_json()}",
        type=profile._TYPE_OF[type(value)],
        value=value,
        source="patient",
        state=state,
        created_at=now,
        created_by="patient",
        confirmed_at=now if state == "confirmed" else None,
    )


def nothing(out: CuratorOutput) -> bool:
    return not (out.ops or out.hard or out.retire)


def no_ops(out: CuratorOutput) -> bool:
    return not out.ops


def no_hard(out: CuratorOutput) -> bool:
    return not out.hard and not out.retire


def adds(kind: str, *words: str) -> Check:
    """Some soft add/replace of this kind mentions every word."""

    def check(out: CuratorOutput) -> bool:
        return any(
            op.action in ("add", "replace")
            and op.kind == kind
            and all(w in (op.fact or "").lower() for w in words)
            for op in out.ops
        )

    return check


def hard(entry_type: str, *words: str) -> Check:
    """Some hard draft of this type mentions every word in its fields."""

    def check(out: CuratorOutput) -> bool:
        return any(
            d.type == entry_type
            and all(w in d.model_dump_json(exclude_none=True).lower() for w in words)
            for d in out.hard
        )

    return check


def retires(ref: str) -> Check:
    return lambda out: any(r.ref.lower() == ref for r in out.retire)


def leaves(ref: str) -> Check:
    """No replace/remove targets this soft handle."""
    return lambda out: (
        not any(
            op.action in ("replace", "remove") and (op.ref or "").lower() == ref
            for op in out.ops
        )
    )


def touches(ref: str) -> Check:
    return lambda out: not leaves(ref)(out)


def never_adds(*words: str) -> Check:
    return lambda out: (
        not any(
            op.action in ("add", "replace")
            and all(w in (op.fact or "").lower() for w in words)
            for op in out.ops
        )
        and not any(
            all(w in d.model_dump_json(exclude_none=True).lower() for w in words)
            for d in out.hard
        )
    )


def quotes_the_user(out: CuratorOutput, user: str) -> bool:
    """Every hard draft and retirement quotes the user's own message (FR-023)."""
    quotes = [d.evidence for d in out.hard] + [r.evidence for r in out.retire]
    return all(evidence_in(user, q) for q in quotes)


def all_of(*checks: Check) -> Check:
    return lambda out: all(c(out) for c in checks)


@dataclass
class Case:
    name: str
    user: str
    check: Check
    assistant: str = ""
    state: ProfileState = field(default_factory=ProfileState)
    entries: list[HardEntry] = field(default_factory=list)


CASES: list[Case] = [
    Case("plain log", "log 2 eggs and toast", nothing, "Logged 290 kcal."),
    Case("one-off meal", "had a vegetarian lunch today: dal and rice", nothing),
    Case("question", "should I avoid dairy?", nothing),
    Case("hypothetical", "if I went vegan, would I get enough protein?", nothing),
    Case("temporary", "I'm eating out tonight, what should I order?", nothing),
    Case("one day only", "no dairy today, my stomach is off", no_hard),
    Case("third person", "my sister is allergic to shellfish", no_hard),
    Case("past state", "I used to take warfarin but not any more", no_hard),
    Case("negated", "I'm not allergic to anything", no_hard),
    Case(
        "assistant suggestion only",
        "what should I have for dinner?",
        nothing,
        "Try grilled salmon with quinoa. Since you are allergic to shellfish, "
        "I left out prawns.",
    ),
    Case("allergy", "I'm allergic to peanuts", hard("allergy", "peanut")),
    Case(
        "religious rule",
        "I don't eat pork for religious reasons",
        hard("food_exclusion", "pork"),
    ),
    Case(
        "diagnosis",
        "I was diagnosed with type 2 diabetes last month",
        hard("diagnosis", "diabetes"),
    ),
    Case("medication", "I take warfarin every morning", hard("medication", "warfarin")),
    Case(
        "nutrient limit",
        "my nephrologist limited me to 2000 mg of sodium a day",
        hard("nutrient_limit", "sodium", "2000"),
    ),
    Case(
        "physical limitation",
        "I can't chew anything hard since my surgery",
        hard("physical_limitation", "chewing"),
    ),
    Case("dislike", "I hate mushrooms", adds("dislike", "mushroom")),
    Case("habit", "I usually skip breakfast", adds("habit", "breakfast")),
    Case(
        "context",
        "I cook for my family of four most nights",
        adds("context", "four"),
    ),
    Case("diet chip", "I'm gluten free", hard("diet_setting", "gluten_free")),
    Case(
        "diet chip contradicts a like",
        "I've gone vegetarian",
        all_of(hard("diet_setting", "vegetarian"), touches("m1")),
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
        "already in the hard profile",
        "just so you know, I'm allergic to peanuts",
        no_hard,
        entries=[_entry(profile.AllergyValue(allergen_group="peanut"))],
    ),
    Case(
        "retire a confirmed fact",
        "turns out I'm not allergic to peanuts after all, the test was negative",
        retires("h1"),
        entries=[_entry(profile.AllergyValue(allergen_group="peanut"))],
    ),
    Case(
        "retire a medication",
        "the doctor took me off warfarin last week",
        retires("h1"),
        entries=[_entry(profile.MedicationValue(name="Warfarin"))],
    ),
    Case(
        "implied by a diet setting",
        "as a vegetarian I don't eat meat",
        never_adds("meat"),
        entries=[_entry(profile.DietSettingValue(setting="vegetarian"))],
    ),
    Case(
        "user removed it",
        "that curry was great, I love spicy food",
        never_adds("spicy"),
        state=ProfileState(tombstones=["Likes spicy food"]),
    ),
]


async def _run_case(case: Case) -> tuple[bool, CuratorOutput]:
    output = await _curator_llm.ainvoke(
        [
            SystemMessage(content=_CURATOR_SYSTEM),
            HumanMessage(
                content=build_curator_input(
                    case.state, case.user, case.assistant, case.entries, load_tables()
                )
            ),
        ]
    )
    return case.check(output) and quotes_the_user(output, case.user), output


async def main(runs: int) -> int:
    failures = 0
    for run in range(1, runs + 1):
        results = await asyncio.gather(*(_run_case(c) for c in CASES))
        passed = sum(ok for ok, _ in results)
        print(f"run {run}: {passed}/{len(CASES)} passed")
        for case, (ok, output) in zip(CASES, results, strict=True):
            if not ok:
                failures += 1
                print(
                    f"  FAIL {case.name!r}: {case.user!r} -> "
                    f"{output.model_dump(exclude_none=True)}"
                )
    return 1 if failures else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=1)
    sys.exit(asyncio.run(main(parser.parse_args().runs)))
