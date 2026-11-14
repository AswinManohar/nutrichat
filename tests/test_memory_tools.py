from __future__ import annotations

from unittest.mock import AsyncMock, patch

from pydantic_ai import capture_run_messages
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from backend.agent import coaching
from backend.agent.coaching import generate_response
from backend.agent.memory.facts import (
    PENDING_ADD,
    PENDING_REMOVAL,
    AddFact,
    AddRestriction,
    ApplyOutcome,
    MemoryFact,
    OpResult,
    RemoveFact,
    SetDietChip,
)
from backend.agent.memory.tools import forget_fact, remember_fact, set_diet_setting
from backend.safety import profile
from backend.safety.tables import load_tables
from tests.profile_helpers import hard_entry

USER = "user-1"


def _outcome(op, applied: bool = True, reason: str = "") -> ApplyOutcome:
    return ApplyOutcome(results=[OpResult(op=op, applied=applied, reason=reason)])


def _apply(applied: bool = True, reason: str = "") -> AsyncMock:
    async def fake(user_id, ops, actor):
        return _outcome(ops[0], applied, reason)

    return AsyncMock(side_effect=fake)


def _profile(*facts: str) -> AsyncMock:
    return AsyncMock(
        return_value=[
            MemoryFact(id=f"id-{f}", fact=f, kind="dislike", source="stated")
            for f in facts
        ]
    )


def _no_hard() -> AsyncMock:
    return AsyncMock(return_value=[])


# --- tool logic --------------------------------------------------------------


async def test_remember_fact_writes_as_the_user() -> None:
    apply = _apply()
    with patch("backend.agent.memory.tools.apply_ops", apply):
        message = await remember_fact(USER, " Dislikes mushrooms ", "dislike")

    apply.assert_awaited_once_with(
        USER, [AddFact(fact="Dislikes mushrooms", kind="dislike")], "user"
    )
    assert message == 'Saved to the profile: "Dislikes mushrooms".'


async def test_remember_fact_reports_a_rejection() -> None:
    with patch("backend.agent.memory.tools.apply_ops", _apply(False, "already known")):
        message = await remember_fact(USER, "Dislikes mushrooms", "dislike")

    assert message == "Nothing saved: already known."


async def test_forget_fact_matches_by_substring() -> None:
    apply = _apply()
    with (
        patch(
            "backend.agent.memory.tools.load_profile",
            _profile("Dislikes mushrooms", "Likes dal"),
        ),
        patch("backend.agent.memory.tools.profile.load_hard_profile", _no_hard()),
        patch("backend.agent.memory.tools.apply_ops", apply),
    ):
        message = await forget_fact(USER, "mushrooms")

    apply.assert_awaited_once_with(
        USER, [RemoveFact(id="id-Dislikes mushrooms")], "user"
    )
    assert message == 'Removed from the profile: "Dislikes mushrooms".'


async def test_forget_fact_prefers_an_exact_match_over_substrings() -> None:
    apply = _apply()
    with (
        patch(
            "backend.agent.memory.tools.load_profile",
            _profile("Dislikes fish", "Dislikes fish sauce"),
        ),
        patch("backend.agent.memory.tools.profile.load_hard_profile", _no_hard()),
        patch("backend.agent.memory.tools.apply_ops", apply),
    ):
        await forget_fact(USER, "dislikes fish")

    assert apply.await_args.args[1] == [RemoveFact(id="id-Dislikes fish")]


async def test_forget_fact_ambiguous_or_missing_changes_nothing() -> None:
    apply = _apply()
    with (
        patch(
            "backend.agent.memory.tools.load_profile",
            _profile("Dislikes fish", "Dislikes fish sauce"),
        ),
        patch("backend.agent.memory.tools.profile.load_hard_profile", _no_hard()),
        patch("backend.agent.memory.tools.apply_ops", apply),
    ):
        ambiguous = await forget_fact(USER, "fish")
        missing = await forget_fact(USER, "okra")

    apply.assert_not_awaited()
    assert "several facts match" in ambiguous
    assert "no stored fact matches" in missing
    assert "Dislikes fish sauce" in missing


async def test_set_diet_setting_normalizes_the_key() -> None:
    apply = _apply()
    with patch("backend.agent.memory.tools.apply_ops", apply):
        message = await set_diet_setting(USER, "Gluten-Free", True)

    apply.assert_awaited_once_with(
        USER, [SetDietChip(chip="gluten_free", on=True)], "user"
    )
    assert message.startswith(f"The gluten_free diet setting is {PENDING_ADD}.")
    assert "confirms" in message


async def test_set_diet_setting_reports_unknown_and_unchanged() -> None:
    with patch(
        "backend.agent.memory.tools.apply_ops", _apply(False, "unknown diet setting")
    ):
        unknown = await set_diet_setting(USER, "carnivore", True)
    with patch("backend.agent.memory.tools.apply_ops", _apply(True, "no change")):
        unchanged = await set_diet_setting(USER, "vegan", False)

    assert unknown == "Nothing changed: unknown diet setting."
    assert unchanged == "The vegan diet setting was already off."


async def test_remember_a_restriction_creates_a_pending_hard_entry() -> None:
    apply = _apply(True, PENDING_ADD)
    with patch("backend.agent.memory.tools.apply_ops", apply):
        message = await remember_fact(USER, "Allergic to peanuts", "restriction")

    apply.assert_awaited_once_with(
        USER, [AddRestriction(fact="Allergic to peanuts")], "user"
    )
    assert message.startswith('Recorded as pending: "Allergic to peanuts".')
    assert "does not apply until the user confirms" in message


async def test_forget_a_confirmed_hard_fact_only_requests_retirement() -> None:
    allergy = hard_entry(profile.AllergyValue(allergen_group="peanut"), entry_id="e1")
    request = AsyncMock()
    apply = _apply()
    with (
        patch("backend.agent.memory.tools.load_profile", _profile("Likes dal")),
        patch(
            "backend.agent.memory.tools.profile.load_hard_profile",
            AsyncMock(return_value=[allergy]),
        ),
        patch("backend.agent.memory.tools.load_tables", load_tables),
        patch("backend.agent.memory.tools.profile.request_retirement", request),
        patch("backend.agent.memory.tools.apply_ops", apply),
    ):
        message = await forget_fact(USER, "peanut allergy")

    request.assert_awaited_once_with(USER, "e1")
    apply.assert_not_awaited()
    assert PENDING_REMOVAL in message
    assert "stays in effect" in message


async def test_forget_a_pending_hard_fact_denies_it() -> None:
    pending = hard_entry(
        profile.DietSettingValue(setting="vegan"), "pending", entry_id="e1"
    )
    deny = AsyncMock()
    with (
        patch("backend.agent.memory.tools.load_profile", _profile()),
        patch(
            "backend.agent.memory.tools.profile.load_hard_profile",
            AsyncMock(return_value=[pending]),
        ),
        patch("backend.agent.memory.tools.profile.deny", deny),
    ):
        message = await forget_fact(USER, "vegan")

    deny.assert_awaited_once_with(USER, "e1")
    assert message.startswith("Dropped the unconfirmed entry")


async def test_set_diet_off_reports_the_pending_removal() -> None:
    with patch("backend.agent.memory.tools.apply_ops", _apply(True, PENDING_REMOVAL)):
        message = await set_diet_setting(USER, "vegan", False)

    assert PENDING_REMOVAL in message
    assert "stays on" in message


async def test_forget_says_so_when_the_profile_cannot_be_read() -> None:
    with (
        patch("backend.agent.memory.tools.load_profile", _profile()),
        patch(
            "backend.agent.memory.tools.profile.load_hard_profile",
            AsyncMock(side_effect=OSError("down")),
        ),
    ):
        message = await forget_fact(USER, "peanuts")

    assert message == "Nothing removed: the profile could not be read."


# --- wiring into the response agent ------------------------------------------


def _recording_model(seen: list[AgentInfo]) -> FunctionModel:
    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        seen.append(info)
        return ModelResponse(parts=[TextPart("ok")])

    return FunctionModel(respond)


async def test_a_call_without_a_user_gets_no_tools_and_no_profile_rules() -> None:
    seen: list[AgentInfo] = []
    with (
        coaching._response_agent.override(model=_recording_model(seen)),
        capture_run_messages() as msgs,
    ):
        await generate_response("am I on track?", {})

    assert seen[0].function_tools == []
    assert "<profile_rules>" not in msgs[0].instructions


async def test_every_user_gets_tools_and_rules_but_one_round_trip() -> None:
    seen: list[AgentInfo] = []
    with (
        coaching._response_agent.override(model=_recording_model(seen)),
        capture_run_messages() as msgs,
    ):
        await generate_response(
            "am I on track?", {}, context_prompt="CTX", user_id=USER
        )

    assert sorted(t.name for t in seen[0].function_tools) == [
        "forget",
        "remember",
        "set_diet",
    ]
    instructions = msgs[0].instructions
    assert instructions.index("<profile_rules>") < instructions.index("CTX")
    # No tool call was made, so the model was asked exactly once.
    assert len(seen) == 1


async def test_explicit_remember_runs_the_tool_then_answers() -> None:
    calls = 0

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal calls
        calls += 1
        if calls == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "remember", {"fact": "Dislikes mushrooms", "kind": "dislike"}
                    )
                ]
            )
        return ModelResponse(parts=[TextPart("Noted, no mushrooms.")])

    apply = _apply()
    with (
        patch("backend.agent.memory.tools.apply_ops", apply),
        coaching._response_agent.override(model=FunctionModel(respond)),
        capture_run_messages() as msgs,
    ):
        reply = await generate_response("remember I hate mushrooms", {}, user_id=USER)

    assert reply == "Noted, no mushrooms."
    assert calls == 2
    apply.assert_awaited_once_with(
        USER, [AddFact(fact="Dislikes mushrooms", kind="dislike")], "user"
    )
    tool_return = next(
        part
        for message in msgs
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    )
    assert tool_return.content == 'Saved to the profile: "Dislikes mushrooms".'
