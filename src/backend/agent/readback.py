"""Readback in chat: ask about a hard fact, mention an inferred one, take the answer.

Hard facts the patient states reach the profile as pending entries (ask band)
or inferred confirmed ones (accept band), see agent/memory_judge.py. This
module turns them into the sentences the coach appends to a reply and reads
the patient's answer to them (spec 013 US4, research R13). Sentences come from
fixed templates in tunables and the entry's label, never from model text.

An entry is *awaiting* an answer when it is pending, or confirmed with a
retirement request. The coach asks once per session (the conversation id
within the coaching-history window) and records when (``readback_asked_at``).
The answer is read with the same keyword classifier the meal card uses
(agent/tools/meals.py classify_intent), made stricter: a yes is a short
message that opens with a yes word and a no opens with a no word, so
"what's a good dinner?" or "no carb ideas, please" never answer.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict

from backend.agent.tools.meals import classify_intent
from backend.config import get_tunables
from backend.safety import profile
from backend.safety.profile import HardEntry, label_for
from backend.safety.tables import ClinicalTables

logger = logging.getLogger(__name__)

_TUNABLES = get_tunables()

ReadbackKind = Literal["add", "retire"]
ReplyKind = Literal["confirm", "reject", "correction", "other"]


class Readback(BaseModel):
    """The ``readback`` field of the chat response: the latest question asked."""

    entry_id: str
    text: str
    kind: ReadbackKind

    model_config = ConfigDict(extra="forbid")


def _kind_of(entry: HardEntry) -> ReadbackKind:
    return "retire" if entry.state == "confirmed" else "add"


def is_awaiting(entry: HardEntry) -> bool:
    """Whether the patient still has to answer for this entry."""
    if entry.state == "pending":
        return True
    return entry.state == "confirmed" and entry.retire_requested_at is not None


def sentence(entry: HardEntry, tables: ClinicalTables) -> str:
    """The question for an awaiting entry, from its tunable template."""
    cfg = _TUNABLES.memory
    template = (
        cfg.retire_readback_text if _kind_of(entry) == "retire" else cfg.readback_text
    )
    return template.format(label=label_for(entry, tables))


def _now() -> datetime:
    """Current time; a seam so tests can pin the clock."""
    return datetime.now(UTC)


def _asked_this_session(entry: HardEntry, conversation_id: str) -> bool:
    """Asked in this conversation within the coaching-history window.

    The app keeps one conversation id per install, so the id alone never
    changes. A session ends when the coaching history expires
    (``memory.coaching_history_ttl_s``): an older question is asked again,
    once, in the next session (US4-6).
    """
    if entry.readback_asked_at is None or entry.conversation_id != conversation_id:
        return False
    window = timedelta(seconds=_TUNABLES.memory.coaching_history_ttl_s)
    return _now() - entry.readback_asked_at < window


def awaiting_reply(entries: list[HardEntry], conversation_id: str) -> list[HardEntry]:
    """The batch asked last in this session and still unanswered.

    Entries asked in one turn share a timestamp and are answered together.
    """
    asked = [
        e for e in entries if is_awaiting(e) and _asked_this_session(e, conversation_id)
    ]
    if not asked:
        return []
    latest = max(e.readback_asked_at for e in asked if e.readback_asked_at)
    return [e for e in asked if e.readback_asked_at == latest]


def reply_kind(message: str) -> ReplyKind:
    """Read a message as an answer to the readback, or as something else.

    Args:
        message: The patient's message.

    Returns:
        ``confirm`` for a short yes; ``reject`` for a message that starts with
        a no; ``correction`` for a no followed by more words (a new statement
        to read); ``other`` for anything else, which is not an answer.
    """
    cfg = _TUNABLES.memory
    intent = classify_intent(message)
    words = re.sub(r"[^\w\s]", "", message.lower()).split()
    plain = " ".join(words)
    if intent == "confirm":
        keywords = set(_TUNABLES.routing.confirm_keywords) - set(
            cfg.readback_confirm_excluded_words
        )
        short = len(words) <= cfg.readback_confirm_max_words
        return "confirm" if short and _opens_with(plain, keywords) else "other"
    if intent == "reject" and _opens_with(plain, _TUNABLES.routing.reject_keywords):
        return (
            "correction"
            if len(words) >= cfg.readback_correction_min_words
            else "reject"
        )
    return "other"


def _opens_with(plain: str, keywords: Iterable[str]) -> bool:
    """Whether the message starts with one of the keywords (word boundary)."""
    return any(plain == kw or plain.startswith(kw + " ") for kw in keywords)


async def apply_reply(user_id: str, awaiting: list[HardEntry], kind: ReplyKind) -> str:
    """Confirm or deny what was asked, and return the fixed reply text.

    A confirmed add becomes confirmed, a confirmed retirement retires the
    entry; a denied add is retired unbound, a denied retirement is withdrawn.
    An entry that changed meanwhile (confirmed in the app) is left as it is.

    Args:
        user_id: Supabase Auth UUID.
        awaiting: The batch from :func:`awaiting_reply`.
        kind: ``confirm``, ``reject`` or ``correction``.

    Returns:
        The reply text for the answer; one sentence per kind of entry.
    """
    cfg = _TUNABLES.memory
    texts: list[str] = []
    for entry in awaiting:
        retire = _kind_of(entry) == "retire"
        try:
            if kind == "confirm":
                if retire:
                    await profile.retire(user_id, entry.id, by="patient")
                else:
                    await profile.confirm(user_id, entry.id)
            elif retire:
                await profile.cancel_retirement(user_id, entry.id)
            else:
                await profile.deny(user_id, entry.id)
        except profile.ProfileError as exc:
            logger.warning("readback answer not applied for %s: %s", user_id, exc)
        text = (
            (cfg.retire_confirm_text if retire else cfg.readback_confirm_text)
            if kind == "confirm"
            else (cfg.retire_keep_text if retire else cfg.readback_reject_text)
        )
        if text not in texts:
            texts.append(text)
    return " ".join(texts)


@dataclass
class Plan:
    """What to append to one reply: questions, mentions, and what to record."""

    asks: list[HardEntry] = field(default_factory=list)
    mentions: list[HardEntry] = field(default_factory=list)
    text: str = ""
    readback: Readback | None = None

    @property
    def empty(self) -> bool:
        """Whether the reply carries nothing extra."""
        return not self.asks and not self.mentions


def plan_readback(
    entries: list[HardEntry], conversation_id: str | None, tables: ClinicalTables
) -> Plan:
    """Decide which questions and mentions this reply carries. No I/O.

    A question is asked once per conversation for every awaiting entry. An
    inferred entry saved without a question is mentioned once.

    Args:
        entries: The patient's live entries, including any written this turn.
        conversation_id: The chat thread; None plans nothing.
        tables: Clinical tables, for labels.

    Returns:
        The plan; ``text`` is the sentences, mentions first and questions last.
    """
    if conversation_id is None:
        return Plan()
    asks = [
        e
        for e in entries
        if is_awaiting(e) and not _asked_this_session(e, conversation_id)
    ]
    mentions = [
        e
        for e in entries
        if e.state == "confirmed"
        and e.source == "inferred"
        and e.confirmed_by == "inference"
        and e.mentioned_at is None
        and e.acknowledged_at is None
    ]
    noted = _TUNABLES.memory.noted_text
    parts = [noted.format(label=label_for(e, tables)) for e in mentions]
    parts += [sentence(e, tables) for e in asks]
    last = asks[-1] if asks else None
    return Plan(
        asks=asks,
        mentions=mentions,
        text=" ".join(parts),
        readback=(
            Readback(entry_id=last.id, text=sentence(last, tables), kind=_kind_of(last))
            if last
            else None
        ),
    )


async def commit_readback(user_id: str, planned: Plan, conversation_id: str) -> None:
    """Record that the questions were asked and the mentions made.

    Failures are logged, not raised: the reply is already written, and an
    entry not recorded as asked is simply asked again next turn.
    """
    try:
        if planned.asks:
            await profile.mark_readback(
                user_id, [e.id for e in planned.asks], conversation_id
            )
        for entry in planned.mentions:
            await profile.mark_mentioned(user_id, entry.id)
    except profile.ProfileError as exc:
        logger.warning("readback not recorded for %s: %s", user_id, exc)


__all__ = [
    "Plan",
    "Readback",
    "apply_reply",
    "awaiting_reply",
    "commit_readback",
    "is_awaiting",
    "plan_readback",
    "reply_kind",
    "sentence",
]
