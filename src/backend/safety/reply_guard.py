"""Layers 1-2 of the reply guard: scan a prose reply for forbidden foods.

Runs on every coaching reply for a patient with confirmed food constraints
(allergies, exclusions, diet settings, drug interactions). Layer 1 matches the
constraint words in the reply itself. Layer 2 resolves the food phrases in the
reply in the USDA database and matches the constraint words against the
matched descriptions, which catches a dish whose description names the
allergen ("satay sauce"). Layer 3, a GLiDE judgment, lives in
``agent/coaching/reply_judge.py``.

This module must not import ``backend.agent`` (tests/safety/test_boundaries.py),
so the USDA lookup is passed in.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from backend.config import get_tunables
from backend.safety.checker import Failure
from backend.safety.matching import TermRule, find_terms, term_rules
from backend.safety.profile import HardEntry
from backend.safety.tables import ClinicalTables

# Words that never name a food; a food phrase is a run of the others.
_STOPWORDS = frozenset(
    "a about all also an and any are as at be been but by can could do does "
    "for from get give had has have here how i if in into is it its just like "
    "make may more most much my no not of on one only or other our out over "
    "should so some such than that the their them then there these they this "
    "those to too try up us very was we well were what when which while who "
    "will with would you your".split()
)
_WORD = re.compile(r"[a-z][a-z'-]*")
_SENTENCE_END = ".!?;\n"
_FREE_AFTER = re.compile(r"(?:-| )free\b")
_NEGATION_WORDS = 3
_MAX_PHRASE_WORDS = 3
_MIN_WORD_CHARS = 3


class _Match(Protocol):
    """The part of ``usda_local.LocalMatch`` the scan reads."""

    description: str
    match_confidence: float


class GuardVerdict(BaseModel):
    """What the guard found in one reply."""

    violations: list[Failure] = Field(default_factory=list)
    layer: Literal["lexical", "usda", "glide", "none"] = "none"
    glide_probability: float | None = None
    retry_reason: str = ""
    # Phrases that resolved to a food; layer 3 runs only when there is one.
    food_phrases: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


def retry_reason(violations: list[Failure]) -> str:
    """The instruction fed back to the model when a reply is rejected."""
    found = "; ".join(v.detail for v in violations)
    return (
        f"The reply breaks the patient's hard restrictions ({found}). Rewrite it "
        "without suggesting or naming those foods, and offer a safe alternative."
    )


def food_phrases(text: str, limit: int) -> list[str]:
    """Candidate food phrases: runs of up to three non-stopwords, deduplicated.

    Args:
        text: The reply.
        limit: Most phrases to return, longest phrases first.

    Returns:
        Phrases such as ``"satay sauce"``, ``"satay"``.
    """
    words = [
        w if len(w) >= _MIN_WORD_CHARS and w not in _STOPWORDS else ""
        for w in _WORD.findall(text.casefold())
    ]
    phrases: dict[str, None] = {}
    for size in range(_MAX_PHRASE_WORDS, 0, -1):
        for start in range(len(words) - size + 1):
            window = words[start : start + size]
            if all(window):
                phrases[" ".join(window)] = None
    return list(phrases)[:limit]


def _negated(folded: str, start: int, end: int) -> bool:
    """Whether a term is used as an exclusion ("no peanuts", "peanut-free")."""
    if _FREE_AFTER.match(folded, end):
        return True
    before = folded[:start]
    sentence = before[max(before.rfind(c) for c in _SENTENCE_END) + 1 :]
    window = " ".join(_WORD.findall(sentence)[-_NEGATION_WORDS:])
    return any(
        re.search(rf"\b{re.escape(n)}\b", window)
        for n in get_tunables().safety.reply_guard_negations
    )


def _lexical(rule: TermRule, text: str) -> tuple[Failure | None, list[tuple[int, int]]]:
    """A violation for the first non-negated mention, and the negated spans."""
    folded = text.casefold()
    spans = sorted(find_terms(text, rule.terms, rule.exclude_terms), key=lambda t: t[1])
    negated = [(a, b) for _, a, b in spans if _negated(folded, a, b)]
    for term, start, end in spans:
        if (start, end) not in negated:
            return (
                Failure(
                    rule=rule.rule,
                    entry_id=rule.entry_id,
                    detail=f"{rule.rule}: {rule.name} (reply mentions {term!r})",
                ),
                negated,
            )
    return None, negated


def _is_food(phrase: str, match: _Match, floor: float) -> bool:
    """Whether a USDA match really names the phrase.

    Match confidence is coverage of the query words, so a lone word matches any
    description that contains it ("curry" -> "Beef curry"). A single word is
    accepted only when it is one of the description's first two comma segments
    ("Milk, NFS"; "Fish, salmon, raw"); multi-word phrases ("pad thai",
    "satay sauce") are specific enough.
    """
    if match.match_confidence < floor:
        return False
    segments = [s.strip() for s in match.description.casefold().split(",")[:2]]
    return len(phrase.split()) > 1 or phrase in segments


def _violation(
    rule: TermRule, text: str, where: Callable[[str], str]
) -> Failure | None:
    term = rule.hit(text)
    if term is None:
        return None
    return Failure(
        rule=rule.rule,
        entry_id=rule.entry_id,
        detail=f"{rule.rule}: {rule.name} ({where(term)})",
    )


def _without(text: str, spans: list[tuple[int, int]]) -> str:
    """The text with negated mentions blanked, so they are not food phrases."""
    folded = text.casefold()
    for start, end in sorted(set(spans), reverse=True):
        folded = folded[:start] + " . " + folded[end:]
    return folded


async def scan(
    text: str,
    entries: list[HardEntry],
    tables: ClinicalTables,
    lookup: Callable[[str], _Match | None],
) -> GuardVerdict:
    """Run layers 1 and 2 on a reply.

    Args:
        text: The reply.
        entries: The patient's live hard entries; only confirmed ones bind.
        tables: Clinical tables.
        lookup: ``usda_local.lookup``; blocking, so it runs in worker threads.

    Returns:
        The verdict. It stops at the first layer with a violation.

    Raises:
        TablesUnavailable: A confirmed entry names a group the tables lack.
        Exception: Whatever ``lookup`` raises (``FoodDbUnavailable``).
    """
    rules = term_rules(entries, tables)
    if not rules:
        return GuardVerdict()
    checked = [_lexical(r, text) for r in rules]
    lexical = [v for v, _ in checked if v]
    if lexical:
        return GuardVerdict(
            violations=lexical, layer="lexical", retry_reason=retry_reason(lexical)
        )
    excluded = [(a, b) for r in rules for _, a, b in find_terms(text, r.exclude_terms)]
    remaining = _without(
        text, [span for _, spans in checked for span in spans] + excluded
    )
    config = get_tunables()
    phrases = food_phrases(remaining, config.safety.reply_guard_max_phrases)
    matches = await asyncio.gather(
        *(asyncio.to_thread(lookup, phrase) for phrase in phrases)
    )
    floor = config.usda.match_confidence_floor
    foods = [
        (phrase, match.description)
        for phrase, match in zip(phrases, matches, strict=True)
        if match is not None and _is_food(phrase, match, floor)
    ]
    resolved = [
        v
        for r in rules
        for phrase, desc in foods
        if (v := _violation(r, desc, lambda _, p=phrase, d=desc: f"{p!r} is {d}"))
    ]
    if resolved:
        return GuardVerdict(
            violations=resolved,
            layer="usda",
            retry_reason=retry_reason(resolved),
            food_phrases=[p for p, _ in foods],
        )
    return GuardVerdict(food_phrases=[p for p, _ in foods])
