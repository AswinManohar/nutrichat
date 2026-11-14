"""Readback in chat (spec 013 US4): questions, answers, ordering, mentions."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agent import orchestrator
from backend.agent.memory import readback
from backend.agent.memory.curator import TurnExtraction
from backend.config import get_tunables
from backend.safety.profile import (
    AllergyValue,
    DietSettingValue,
    MedicationValue,
)
from backend.safety.tables import load_tables
from tests.profile_helpers import hard_entry

# The save paths are tested here; tests/test_meal_check.py tests the check.
pytestmark = pytest.mark.usefixtures("no_meal_warnings")


TABLES = load_tables()
CFG = get_tunables().memory
NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
THREAD = "user-1:conv-1"
SHELLFISH = AllergyValue(allergen_group="shellfish")


def _asked(entry, at: datetime = NOW, conversation: str = THREAD):
    return entry.model_copy(
        update={"readback_asked_at": at, "conversation_id": conversation}
    )


def _pending(value=SHELLFISH, **kwargs):
    return _asked(hard_entry(value, "pending", source="inferred"), **kwargs)


def _retiring(**kwargs):
    entry = hard_entry(MedicationValue(name="Warfarin"), entry_id="e-w")
    return _asked(entry.model_copy(update={"retire_requested_at": NOW}), **kwargs)


@pytest.fixture(autouse=True)
def _pinned_clock() -> Iterator[None]:
    with patch.object(readback, "_now", return_value=NOW):
        yield


# --- reading an answer -----------------------------------------------------------


@pytest.mark.parametrize(
    ("message", "kind"),
    [
        ("yes", "confirm"),
        ("Yes!", "confirm"),
        ("yeah that's right", "confirm"),
        ("ok", "confirm"),
        ("no", "reject"),
        ("nope", "reject"),
        ("never mind", "reject"),
        ("no, it's prawns", "correction"),
        ("actually no, it's my sister", "other"),  # does not open with a no
        ("no it's just prawns not all shellfish", "correction"),
        ("what's a good dinner?", "other"),
        ("log 2 eggs", "other"),
        ("yes please also log my lunch and tell me more", "other"),
        ("how much sodium is in rice", "other"),
        ("", "other"),
    ],
)
def test_reply_kind(message: str, kind: str) -> None:
    assert readback.reply_kind(message) == kind


# --- which entries are waiting ---------------------------------------------------


def test_the_awaiting_batch_is_the_one_asked_last_in_this_conversation() -> None:
    old = _pending(DietSettingValue(setting="vegan"), at=NOW - timedelta(minutes=5))
    a = _pending()
    b = _pending(DietSettingValue(setting="keto"))
    elsewhere = _pending(DietSettingValue(setting="paleo"), conversation="user-1:other")
    unasked = hard_entry(DietSettingValue(setting="low_carb"), "pending")
    confirmed = hard_entry(MedicationValue(name="X"))

    batch = readback.awaiting_reply([old, a, b, elsewhere, unasked, confirmed], THREAD)

    assert {e.id for e in batch} == {a.id, b.id}


def test_a_retirement_request_awaits_an_answer() -> None:
    assert [e.id for e in readback.awaiting_reply([_retiring()], THREAD)] == ["e-w"]
    assert readback.awaiting_reply([_retiring(conversation="user-1:x")], THREAD) == []


# --- what a reply carries --------------------------------------------------------


def test_a_pending_entry_is_asked_once_per_conversation() -> None:
    fresh = hard_entry(SHELLFISH, "pending", source="inferred")

    planned = readback.plan_readback([fresh], THREAD, TABLES)

    assert (
        planned.text
        == "I'll note this on your profile: Shellfish allergy. Is that right?"
    )
    assert planned.readback == readback.Readback(
        entry_id=fresh.id, text=planned.text, kind="add"
    )
    assert readback.plan_readback([_asked(fresh)], THREAD, TABLES).empty
    # A new conversation asks again (US4-6).
    again = readback.plan_readback([_asked(fresh, conversation="old")], THREAD, TABLES)
    assert again.asks == [_asked(fresh, conversation="old")]


def test_a_retirement_is_read_back_in_its_own_words() -> None:
    entry = _retiring(conversation="old")

    planned = readback.plan_readback([entry], THREAD, TABLES)

    assert planned.text == "Should I stop applying this from now on: Warfarin?"
    assert planned.readback.kind == "retire"


def test_the_readback_field_is_the_latest_one_asked() -> None:
    first = hard_entry(SHELLFISH, "pending")
    second = hard_entry(DietSettingValue(setting="vegan"), "pending")

    planned = readback.plan_readback([first, second], THREAD, TABLES)

    assert planned.readback.entry_id == second.id
    assert planned.text.count("Is that right?") == 2


def test_an_accepted_inferred_entry_is_mentioned_once() -> None:
    accepted = hard_entry(SHELLFISH, source="inferred").model_copy(
        update={"confirmed_by": "inference"}
    )

    planned = readback.plan_readback([accepted], THREAD, TABLES)

    assert planned.text == (
        "I've noted this on your profile: Shellfish allergy. Tell me if that's wrong."
    )
    assert planned.readback is None and planned.mentions == [accepted]
    done = accepted.model_copy(update={"mentioned_at": NOW})
    assert readback.plan_readback([done], THREAD, TABLES).empty
    patient = accepted.model_copy(update={"acknowledged_at": NOW})
    assert readback.plan_readback([patient], THREAD, TABLES).empty
    typed = hard_entry(SHELLFISH)  # entered by the patient: nothing to mention
    assert readback.plan_readback([typed], THREAD, TABLES).empty


def test_no_conversation_plans_nothing() -> None:
    fresh = hard_entry(SHELLFISH, "pending")

    assert readback.plan_readback([fresh], None, TABLES).empty


async def test_commit_records_the_asks_and_the_mentions() -> None:
    fresh = hard_entry(SHELLFISH, "pending")
    accepted = hard_entry(DietSettingValue(setting="vegan"), source="inferred")
    accepted = accepted.model_copy(update={"confirmed_by": "inference"})
    planned = readback.plan_readback([fresh, accepted], THREAD, TABLES)

    with (
        patch.object(readback.profile, "mark_readback", AsyncMock()) as asked,
        patch.object(readback.profile, "mark_mentioned", AsyncMock()) as mentioned,
    ):
        await readback.commit_readback("user-1", planned, THREAD)

    asked.assert_awaited_once_with("user-1", [fresh.id], THREAD)
    mentioned.assert_awaited_once_with("user-1", accepted.id)


# --- applying an answer ----------------------------------------------------------


@pytest.fixture
def writes() -> Iterator[SimpleNamespace]:
    with (
        patch.object(readback.profile, "confirm", AsyncMock()) as confirm,
        patch.object(readback.profile, "deny", AsyncMock()) as deny,
        patch.object(readback.profile, "retire", AsyncMock()) as retire,
        patch.object(readback.profile, "cancel_retirement", AsyncMock()) as cancel,
    ):
        yield SimpleNamespace(confirm=confirm, deny=deny, retire=retire, cancel=cancel)


async def test_yes_confirms_a_pending_entry(writes) -> None:
    entry = _pending()

    text = await readback.apply_reply("user-1", [entry], "confirm")

    writes.confirm.assert_awaited_once_with("user-1", entry.id)
    writes.deny.assert_not_awaited()
    assert text == "Got it, I'll apply that from now on."


async def test_no_denies_a_pending_entry_without_binding_it(writes) -> None:
    entry = _pending()

    text = await readback.apply_reply("user-1", [entry], "reject")

    writes.deny.assert_awaited_once_with("user-1", entry.id)
    writes.confirm.assert_not_awaited()
    assert text == "Okay, I won't save that."


async def test_yes_to_a_retirement_retires_and_no_withdraws_the_request(writes) -> None:
    entry = _retiring()

    assert await readback.apply_reply("user-1", [entry], "confirm") == (
        "Got it, I'll stop applying that."
    )
    writes.retire.assert_awaited_once_with("user-1", "e-w", by="patient")

    assert await readback.apply_reply("user-1", [entry], "reject") == (
        "Okay, I'll keep applying it."
    )
    writes.cancel.assert_awaited_once_with("user-1", "e-w")
    writes.deny.assert_not_awaited()


async def test_an_entry_that_changed_meanwhile_does_not_fail_the_reply(writes) -> None:
    writes.confirm.side_effect = readback.profile.StateConflict("retired")

    text = await readback.apply_reply("user-1", [_pending()], "confirm")

    assert text == CFG.readback_confirm_text


# --- handle_message: answers, ordering, unrelated messages ----------------------


@pytest.fixture
def turn(writes) -> Iterator[SimpleNamespace]:
    graph = MagicMock()
    graph.aget_state = AsyncMock(
        return_value=SimpleNamespace(next=(), values={}, created_at=None)
    )
    with (
        patch.object(orchestrator, "_graph_for", return_value=graph),
        patch.object(orchestrator, "_load_entries", new=AsyncMock()) as entries,
        patch.object(
            orchestrator,
            "judge_message",
            new=AsyncMock(return_value=(None, "off")),
        ),
        patch.object(
            orchestrator,
            "_route",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    intent="coaching",
                    offer_to_log=False,
                    routing_record=lambda: None,
                )
            ),
        ),
        patch.object(
            orchestrator,
            "_handle_coaching",
            new=AsyncMock(
                return_value={
                    "status": "success",
                    "message": "coach answer",
                    "paused": False,
                    "items": [],
                }
            ),
        ) as coaching,
        patch.object(
            orchestrator,
            "_handle_meal_logging",
            new=AsyncMock(
                return_value={
                    "status": "success",
                    "message": "card answer",
                    "paused": False,
                    "items": [],
                }
            ),
        ) as logging_,
        patch.object(orchestrator, "_record_turn", new=AsyncMock()) as record,
        patch.object(orchestrator, "_enqueue_fact_extraction") as facts,
        patch.object(orchestrator, "extract_turn", new=AsyncMock()) as extract,
    ):
        yield SimpleNamespace(
            graph=graph,
            entries=entries,
            coaching=coaching,
            logging=logging_,
            record=record,
            facts=facts,
            extract=extract,
            **vars(writes),
        )


async def _send(text: str):
    return await orchestrator.handle_message(
        "user-1", text, THREAD, checkpointer=MagicMock()
    )


async def test_yes_confirms_without_routing_or_a_model_call(turn) -> None:
    entry = _pending()
    turn.entries.return_value = [entry]

    result = await _send("yes")

    turn.confirm.assert_awaited_once_with("user-1", entry.id)
    assert result["message"] == "Got it, I'll apply that from now on."
    turn.coaching.assert_not_awaited()
    turn.logging.assert_not_awaited()
    turn.extract.assert_not_awaited()
    turn.facts.assert_not_called()
    turn.record.assert_awaited_once()


async def test_no_denies_and_saves_nothing(turn) -> None:
    entry = _pending()
    turn.entries.return_value = [entry]

    result = await _send("no")

    turn.deny.assert_awaited_once_with("user-1", entry.id)
    assert result["message"] == "Okay, I won't save that."
    turn.extract.assert_not_awaited()


async def test_a_correction_denies_then_reads_the_new_statement(turn) -> None:
    entry = _pending()
    prawns = hard_entry(AllergyValue(custom_terms=["prawns"]), "pending")
    turn.entries.side_effect = [[entry]]
    turn.extract.return_value = TurnExtraction(asked=[prawns])
    message = "no, it's prawns not all shellfish"
    with (
        patch.object(
            orchestrator.profile, "load_hard_profile", AsyncMock(return_value=[prawns])
        ),
        patch.object(readback.profile, "mark_readback", AsyncMock()) as asked,
    ):
        result = await _send(message)

    turn.deny.assert_awaited_once_with("user-1", entry.id)
    turn.extract.assert_awaited_once_with("user-1", message)
    asked.assert_awaited_once_with("user-1", [prawns.id], THREAD)
    assert result["message"].startswith("Okay, I won't save that.")
    assert result["message"].endswith("Is that right?")
    assert result["readback"]["entry_id"] == prawns.id
    assert result["readback"]["kind"] == "add"
    turn.facts.assert_not_called()


async def test_a_no_that_states_no_new_fact_of_that_type_is_not_an_answer(
    turn,
) -> None:
    turn.entries.return_value = [_pending()]
    turn.extract.return_value = TurnExtraction()

    result = await _send("no carb ideas please")

    turn.extract.assert_awaited_once()
    turn.deny.assert_not_awaited()
    turn.confirm.assert_not_awaited()
    turn.coaching.assert_awaited_once()
    assert result["message"] == "coach answer"


async def test_a_no_that_states_another_type_of_fact_is_not_a_correction(turn) -> None:
    vegan = hard_entry(DietSettingValue(setting="vegan"), "pending")
    turn.entries.return_value = [_pending()]
    turn.extract.return_value = TurnExtraction(asked=[vegan])

    await _send("no thanks, I also take warfarin daily")

    turn.deny.assert_not_awaited()
    turn.coaching.assert_awaited_once()


async def test_a_bare_no_denies_without_reading_the_message(turn) -> None:
    turn.entries.return_value = [_pending()]

    await _send("no thanks")

    turn.deny.assert_awaited_once()
    turn.extract.assert_not_awaited()


async def test_a_long_no_to_a_retirement_keeps_the_entry_without_a_model_call(
    turn,
) -> None:
    turn.entries.return_value = [_retiring()]

    result = await _send("no, I'm still on it, keep applying it please")

    turn.cancel.assert_awaited_once_with("user-1", "e-w")
    turn.extract.assert_not_awaited()
    assert result["message"] == "Okay, I'll keep applying it."


async def test_an_unrelated_message_leaves_the_entry_pending_and_routes_normally(
    turn,
) -> None:
    turn.entries.return_value = [_pending()]

    result = await _send("how much protein did I eat today?")

    turn.confirm.assert_not_awaited()
    turn.deny.assert_not_awaited()
    turn.coaching.assert_awaited_once()
    assert result["message"] == "coach answer"
    turn.facts.assert_called_once()


async def test_a_yes_with_nothing_awaiting_is_an_ordinary_message(turn) -> None:
    turn.entries.return_value = [hard_entry(SHELLFISH, "pending")]  # never asked

    await _send("yes")

    turn.confirm.assert_not_awaited()
    turn.coaching.assert_awaited_once()


async def test_a_readback_from_another_conversation_is_not_answered_here(turn) -> None:
    turn.entries.return_value = [_pending(conversation="user-1:old")]

    await _send("yes")

    turn.confirm.assert_not_awaited()


def _paused(created_at: datetime) -> SimpleNamespace:
    return SimpleNamespace(
        next=("confirm",),
        values={"usda_results": [], "saved_meal_id": None},
        created_at=created_at.isoformat(),
    )


async def test_a_card_asked_after_the_readback_takes_the_reply(turn) -> None:
    entry = _pending(at=NOW)
    turn.entries.return_value = [entry]
    turn.graph.aget_state.return_value = _paused(NOW + timedelta(minutes=1))

    result = await _send("yes")

    turn.confirm.assert_not_awaited()
    turn.logging.assert_awaited_once()
    assert result["message"].startswith("card answer")
    assert "I'm still waiting for your answer on this: " in result["message"]
    assert "Shellfish allergy" in result["message"]


async def test_a_readback_asked_after_the_card_takes_the_reply_and_names_the_card(
    turn,
) -> None:
    entry = _pending(at=NOW)
    turn.entries.return_value = [entry]
    turn.graph.aget_state.return_value = _paused(NOW - timedelta(minutes=1))

    result = await _send("yes")

    turn.confirm.assert_awaited_once_with("user-1", entry.id)
    turn.logging.assert_not_awaited()
    assert result["message"] == (
        "Got it, I'll apply that from now on.\n\n"
        "Your meal card is still waiting for you."
    )
    assert result["paused"] is True


async def test_an_unrelated_message_while_both_wait_goes_to_the_card(turn) -> None:
    turn.entries.return_value = [_pending(at=NOW)]
    turn.graph.aget_state.return_value = _paused(NOW - timedelta(minutes=1))

    result = await _send("make it 200g of rice")

    turn.confirm.assert_not_awaited()
    turn.logging.assert_awaited_once()
    assert "still waiting" not in result["message"]


async def test_celery_extraction_is_skipped_when_the_turn_extracted(turn) -> None:
    turn.coaching.return_value = {
        "status": "success",
        "message": "x",
        "paused": False,
        "items": [],
        "facts_extracted": True,
    }
    turn.entries.return_value = []

    result = await _send("I'm allergic to shellfish")

    turn.facts.assert_not_called()
    assert "facts_extracted" not in result


# --- sessions --------------------------------------------------------------------


def test_an_unanswered_question_is_asked_again_in_a_later_session() -> None:
    """The app keeps one conversation id; a session ends with the history TTL."""
    stale = _pending(at=NOW - timedelta(seconds=CFG.coaching_history_ttl_s + 60))

    assert readback.awaiting_reply([stale], THREAD) == []
    planned = readback.plan_readback([stale], THREAD, TABLES)
    assert [e.id for e in planned.asks] == [stale.id]


def test_a_question_asked_in_this_session_is_not_asked_twice() -> None:
    fresh = _pending(at=NOW - timedelta(minutes=10))

    assert readback.awaiting_reply([fresh], THREAD) == [fresh]
    assert readback.plan_readback([fresh], THREAD, TABLES).asks == []
