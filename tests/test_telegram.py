"""Unit tests for the Telegram bot handlers (mocked aiogram + stubbed agent).

Covers: link-code success/expiry, unlinked-user prompt, thread rotation
after a non-paused reply, confirm/cancel callbacks resuming with "yes"/
"cancel", the photo -> image_b64 path, and per-chat user_id isolation.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.api import telegram_link
from backend.telegram import auth as tg_auth
from backend.telegram import handlers
from backend.telegram import session as tg_session


class FakeRedis:
    """Minimal async Redis stand-in backed by an in-memory dict."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = str(value)

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)


_PAUSED_ITEMS = [
    {
        "food_name": "fried egg",
        "qty_g": 100.0,
        "kcal": 196.0,
        "protein_g": 13.6,
        "carbs_g": 0.8,
        "fat_g": 15.0,
        "fiber_g": 0.0,
        "fdc_id": 1,
        "confidence": 0.7,
        "candidates": ["fried egg", "scrambled egg", "boiled egg"],
        "source": "USDA",
        "estimated": False,
    },
    {
        "food_name": "toast",
        "qty_g": 50.0,
        "kcal": 130.0,
        "protein_g": 4.0,
        "carbs_g": 24.0,
        "fat_g": 1.5,
        "fiber_g": 1.2,
        "fdc_id": 2,
        "confidence": 0.9,
        "candidates": ["toast"],
        "source": "USDA",
        "estimated": False,
    },
]


def _mock_callback(
    chat_id: int, data: str, text: str = "Here's what I found:\n\n- ..."
):
    callback = MagicMock()
    callback.data = data
    callback.message.chat.id = chat_id
    callback.message.text = text
    callback.message.edit_text = AsyncMock()
    callback.message.answer = AsyncMock()
    callback.answer = AsyncMock()
    callback.bot.checkpointer = MagicMock()
    return callback


@pytest.fixture
def fake_redis():
    client = FakeRedis()
    with (
        patch("backend.telegram.auth.get_redis", return_value=client),
        patch("backend.telegram.session.get_redis", return_value=client),
        patch("backend.telegram.handlers.get_redis", return_value=client),
    ):
        yield client


def _mock_message(
    text: str | None = None, chat_id: int = 111, photo=None, caption=None
):
    message = MagicMock()
    message.chat.id = chat_id
    message.text = text
    message.caption = caption
    message.photo = photo
    message.answer = AsyncMock()
    return message


def _mock_session_factory(scalar_return=None):
    session = AsyncMock()
    session.scalar = AsyncMock(return_value=scalar_return)
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.get = AsyncMock(return_value=scalar_return)
    session.add = MagicMock()

    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=None)
    return factory, session


# ---------------------------------------------------------------------------
# Link codes
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Help command
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_help_lists_all_commands(fake_redis):
    message = _mock_message(text="/help", chat_id=123)

    await handlers.cmd_help(message)

    message.answer.assert_awaited_once()
    text = message.answer.call_args[0][0]
    for command in ("/start", "/help", "/link", "/goals", "/progress", "/new"):
        assert command in text


# ---------------------------------------------------------------------------
# Progress command
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_progress_unlinked_user(fake_redis):
    message = _mock_message(text="/progress", chat_id=998)

    await handlers.cmd_progress(message)

    message.answer.assert_awaited_once()
    assert "isn't linked" in message.answer.call_args[0][0]


@pytest.mark.asyncio
async def test_progress_no_goals(fake_redis):
    await fake_redis.set("tguser:601", "user-1")
    message = _mock_message(text="/progress", chat_id=601)

    factory, _ = _mock_session_factory(scalar_return=None)
    with patch("backend.telegram.handlers.get_session", return_value=factory):
        await handlers.cmd_progress(message)

    message.answer.assert_awaited_once()
    assert "haven't set up nutrition goals" in message.answer.call_args[0][0]


@pytest.mark.asyncio
async def test_progress_shows_summary(fake_redis):
    await fake_redis.set("tguser:602", "user-1")
    message = _mock_message(text="/progress", chat_id=602)

    goal = MagicMock(kcal_goal=2000.0, protein_goal=100.0, fiber_goal=30.0)
    factory, _ = _mock_session_factory(scalar_return=goal)

    totals = MagicMock(kcal=1000.0, protein_g=50.0, fiber_g=15.0, n_meals=2)
    with (
        patch("backend.telegram.handlers.get_session", return_value=factory),
        patch(
            "backend.telegram.handlers.get_today_totals",
            new_callable=AsyncMock,
            return_value=totals,
        ),
    ):
        await handlers.cmd_progress(message)

    message.answer.assert_awaited_once()
    text = message.answer.call_args[0][0]
    assert "🔥" in text and "💪" in text and "🌾" in text
    assert "50%" in text
    assert "Meals logged: 2" in text


@pytest.mark.asyncio
async def test_progress_no_meals_logged(fake_redis):
    await fake_redis.set("tguser:603", "user-1")
    message = _mock_message(text="/progress", chat_id=603)

    goal = MagicMock(kcal_goal=2000.0, protein_goal=100.0, fiber_goal=30.0)
    factory, _ = _mock_session_factory(scalar_return=goal)

    totals = MagicMock(kcal=0.0, protein_g=0.0, fiber_g=0.0, n_meals=0)
    with (
        patch("backend.telegram.handlers.get_session", return_value=factory),
        patch(
            "backend.telegram.handlers.get_today_totals",
            new_callable=AsyncMock,
            return_value=totals,
        ),
    ):
        await handlers.cmd_progress(message)

    message.answer.assert_awaited_once()
    text = message.answer.call_args[0][0]
    assert "Nothing logged yet today" in text
    assert "0%" in text


@pytest.mark.asyncio
async def test_link_success(fake_redis):
    await fake_redis.set("tglink:code:123456", "user-abc")
    message = _mock_message(text="/link 123456", chat_id=555)
    command = MagicMock(args="123456")

    factory, session = _mock_session_factory()
    with patch("backend.telegram.handlers.get_session", return_value=factory):
        await handlers.cmd_link(message, command)

    session.execute.assert_awaited_once()
    session.commit.assert_awaited_once()
    message.answer.assert_awaited_once()
    assert "Linked" in message.answer.call_args[0][0]
    # Code consumed
    assert await fake_redis.get("tglink:code:123456") is None
    # Cached for resolve_user_id
    assert await fake_redis.get("tguser:555") == "user-abc"


@pytest.mark.asyncio
async def test_link_expired_or_invalid_code(fake_redis):
    message = _mock_message(text="/link 999999", chat_id=555)
    command = MagicMock(args="999999")

    await handlers.cmd_link(message, command)

    message.answer.assert_awaited_once()
    assert "invalid or expired" in message.answer.call_args[0][0]


# ---------------------------------------------------------------------------
# Unlinked-user prompts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unlinked_user_gets_link_instructions(fake_redis):
    message = _mock_message(text="2 eggs and toast", chat_id=999)

    factory, _ = _mock_session_factory(scalar_return=None)
    with patch("backend.telegram.auth.get_session", return_value=factory):
        await handlers.on_text(message, bot=MagicMock())

    message.answer.assert_awaited_once()
    assert "isn't linked" in message.answer.call_args[0][0]


# ---------------------------------------------------------------------------
# Thread rotation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_thread_rotates_after_non_paused_reply(fake_redis):
    chat_id = 222
    await fake_redis.set("tguser:222", "user-1")
    await fake_redis.set("tgthread:222", "tg:222:old-thread")

    message = _mock_message(text="2 eggs", chat_id=chat_id)
    bot = MagicMock()
    bot.checkpointer = MagicMock()
    bot.send_chat_action = AsyncMock()

    result = {"status": "success", "message": "Logged!", "paused": False, "items": []}
    with patch(
        "backend.telegram.handlers.handle_message", new_callable=AsyncMock
    ) as mock_handle:
        mock_handle.return_value = result
        await handlers.on_text(message, bot)

    mock_handle.assert_awaited_once()
    assert mock_handle.call_args.kwargs["thread_id"] == "tg:222:old-thread"
    # Thread rotated to a new id
    new_thread = await fake_redis.get("tgthread:222")
    assert new_thread != "tg:222:old-thread"
    assert new_thread.startswith("tg:222:")
    message.answer.assert_awaited_once_with("Logged!")


@pytest.mark.asyncio
async def test_thread_not_rotated_when_paused(fake_redis):
    chat_id = 223
    await fake_redis.set("tguser:223", "user-1")
    await fake_redis.set("tgthread:223", "tg:223:active-thread")

    message = _mock_message(text="2 eggs", chat_id=chat_id)
    bot = MagicMock()
    bot.checkpointer = MagicMock()
    bot.send_chat_action = AsyncMock()

    result = {
        "status": "success",
        "message": "Here's what I found:",
        "paused": True,
        "items": [
            {
                "food_name": "egg",
                "qty_g": 100.0,
                "kcal": 155.0,
                "protein_g": 13.0,
                "carbs_g": 1.1,
                "fat_g": 11.0,
                "fiber_g": 0.0,
                "fdc_id": 1,
                "confidence": 0.9,
                "candidates": [],
            }
        ],
    }
    with patch(
        "backend.telegram.handlers.handle_message", new_callable=AsyncMock
    ) as mock_handle:
        mock_handle.return_value = result
        await handlers.on_text(message, bot)

    assert await fake_redis.get("tgthread:223") == "tg:223:active-thread"
    message.answer.assert_awaited_once()
    args, kwargs = message.answer.call_args
    assert "egg" in args[0]
    assert "reply_markup" in kwargs


# ---------------------------------------------------------------------------
# Confirm / cancel callbacks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirm_callback_resumes_with_yes(fake_redis):
    chat_id = 333
    await fake_redis.set("tguser:333", "user-1")

    callback = MagicMock()
    callback.message.chat.id = chat_id
    callback.message.answer = AsyncMock()
    callback.answer = AsyncMock()
    callback.bot.checkpointer = MagicMock()

    result = {"status": "success", "message": "Logged!", "paused": False, "items": []}
    with patch(
        "backend.telegram.handlers.handle_message", new_callable=AsyncMock
    ) as mock_handle:
        mock_handle.return_value = result
        await handlers.on_confirm(callback)

    mock_handle.assert_awaited_once()
    assert mock_handle.call_args.kwargs["user_input"] == "yes"
    assert mock_handle.call_args.kwargs["user_id"] == "user-1"


@pytest.mark.asyncio
async def test_cancel_callback_resumes_with_cancel(fake_redis):
    chat_id = 334
    await fake_redis.set("tguser:334", "user-1")

    callback = MagicMock()
    callback.message.chat.id = chat_id
    callback.message.answer = AsyncMock()
    callback.answer = AsyncMock()
    callback.bot.checkpointer = MagicMock()

    result = {
        "status": "success",
        "message": "Cancelled.",
        "paused": False,
        "items": [],
    }
    with patch(
        "backend.telegram.handlers.handle_message", new_callable=AsyncMock
    ) as mock_handle:
        mock_handle.return_value = result
        await handlers.on_cancel(callback)

    mock_handle.assert_awaited_once()
    assert mock_handle.call_args.kwargs["user_input"] == "cancel"


# ---------------------------------------------------------------------------
# Photo -> image_b64
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_photo_routes_image_b64(fake_redis):
    chat_id = 444
    await fake_redis.set("tguser:444", "user-1")

    photo_size = MagicMock(file_id="file-123")
    message = _mock_message(chat_id=chat_id, photo=[photo_size], caption="my lunch")

    bot = MagicMock()
    bot.checkpointer = MagicMock()
    bot.send_chat_action = AsyncMock()
    bot.get_file = AsyncMock(return_value=MagicMock(file_path="path/to/file"))

    import io

    bot.download_file = AsyncMock(return_value=io.BytesIO(b"fake-image-bytes"))

    result = {"status": "success", "message": "Got it", "paused": False, "items": []}
    with patch(
        "backend.telegram.handlers.handle_message", new_callable=AsyncMock
    ) as mock_handle:
        mock_handle.return_value = result
        await handlers.on_photo(message, bot)

    mock_handle.assert_awaited_once()
    kwargs = mock_handle.call_args.kwargs
    assert kwargs["image_b64"]
    assert kwargs["user_input"] == "my lunch"


# ---------------------------------------------------------------------------
# Per-chat isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_chats_resolve_to_different_users(fake_redis):
    await fake_redis.set("tguser:1", "user-a")
    await fake_redis.set("tguser:2", "user-b")

    assert await tg_auth.resolve_user_id(1) == "user-a"
    assert await tg_auth.resolve_user_id(2) == "user-b"


@pytest.mark.asyncio
async def test_thread_ids_independent_per_chat(fake_redis):
    thread_a = await tg_session.get_thread_id(10)
    thread_b = await tg_session.get_thread_id(20)

    assert thread_a != thread_b
    assert thread_a.startswith("tg:10:")
    assert thread_b.startswith("tg:20:")


# ---------------------------------------------------------------------------
# Unlink clears Redis cache
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unlink_clears_user_cache(fake_redis):
    await fake_redis.set("tguser:777", "user-z")

    factory, session = _mock_session_factory(scalar_return=777)
    with (
        patch("backend.api.telegram_link.get_session", return_value=factory),
        patch("backend.api.telegram_link.get_redis", return_value=fake_redis),
    ):
        # Simulate one row deleted.
        session.execute.return_value = MagicMock(rowcount=1)
        await telegram_link.delete_link(user_id="user-z")

    assert await fake_redis.get("tguser:777") is None


@pytest.mark.asyncio
async def test_unlink_404_when_no_row(fake_redis):
    factory, session = _mock_session_factory(scalar_return=None)
    with (
        patch("backend.api.telegram_link.get_session", return_value=factory),
        patch("backend.api.telegram_link.get_redis", return_value=fake_redis),
    ):
        session.execute.return_value = MagicMock(rowcount=0)
        with pytest.raises(Exception) as exc_info:
            await telegram_link.delete_link(user_id="user-nope")

    assert getattr(exc_info.value, "status_code", None) == 404


# ---------------------------------------------------------------------------
# Re-linking a chat already linked to a different user
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_relink_chat_to_different_user_rebinds(fake_redis):
    await fake_redis.set("tglink:code:654321", "user-new")
    message = _mock_message(text="/link 654321", chat_id=888)
    command = MagicMock(args="654321")

    factory, session = _mock_session_factory()
    with patch("backend.telegram.handlers.get_session", return_value=factory):
        await handlers.cmd_link(message, command)

    # Old rows (chat_id=888 owned by some other user, or user-new owning
    # another chat) are deleted before the fresh row is added.
    session.execute.assert_awaited_once()
    session.add.assert_called_once()
    added = session.add.call_args[0][0]
    assert added.chat_id == 888
    assert added.user_id == "user-new"
    session.commit.assert_awaited_once()

    message.answer.assert_awaited_once()
    assert "Linked" in message.answer.call_args[0][0]
    assert await fake_redis.get("tguser:888") == "user-new"


@pytest.mark.asyncio
async def test_relink_same_pair_is_idempotent(fake_redis):
    await fake_redis.set("tglink:code:111222", "user-same")
    message = _mock_message(text="/link 111222", chat_id=889)
    command = MagicMock(args="111222")

    factory, session = _mock_session_factory()
    with patch("backend.telegram.handlers.get_session", return_value=factory):
        await handlers.cmd_link(message, command)

    session.execute.assert_awaited_once()
    session.add.assert_called_once()
    session.commit.assert_awaited_once()
    message.answer.assert_awaited_once()
    assert "Linked" in message.answer.call_args[0][0]


# ---------------------------------------------------------------------------
# Meal-edit card: qty stepper, swap picker, confirm/cancel
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_paused_card_stores_edit_state_and_keyboard(fake_redis):
    chat_id = 700
    await fake_redis.set("tguser:700", "user-1")
    await fake_redis.set("tgthread:700", "tg:700:thread")

    message = _mock_message(text="2 eggs and toast", chat_id=chat_id)
    bot = MagicMock()
    bot.checkpointer = MagicMock()
    bot.send_chat_action = AsyncMock()

    result = {
        "status": "success",
        "message": "Here's what I found:",
        "paused": True,
        "items": _PAUSED_ITEMS,
    }
    with patch(
        "backend.telegram.handlers.handle_message", new_callable=AsyncMock
    ) as mock_handle:
        mock_handle.return_value = result
        await handlers.on_text(message, bot)

    edit = await tg_session.get_edit_state(chat_id)
    assert edit["items"] == _PAUSED_ITEMS
    assert edit["qty"] == {} and edit["swaps"] == {}

    args, kwargs = message.answer.call_args
    assert "fried egg" in args[0]
    keyboard = kwargs["reply_markup"]
    # Row 0: qty stepper for item 0, row 1: swap (item 0 has >1 candidate)
    row0_texts = [b.text for b in keyboard.inline_keyboard[0]]
    assert "−25g" in row0_texts and "+25g" in row0_texts
    assert keyboard.inline_keyboard[0][2].callback_data == "q:0:+"
    assert keyboard.inline_keyboard[1][0].callback_data == "sw:0"


@pytest.mark.asyncio
async def test_qty_plus_updates_state_and_rerenders(fake_redis):
    chat_id = 701
    edit = {"items": _PAUSED_ITEMS, "qty": {}, "swaps": {}}
    await tg_session.set_edit_state(chat_id, edit)

    callback = _mock_callback(chat_id, "q:0:+")
    await handlers.on_qty_step(callback)

    new_edit = await tg_session.get_edit_state(chat_id)
    assert new_edit["qty"]["0"] == 125.0  # 100g + 25g

    callback.message.edit_text.assert_awaited_once()
    rendered = callback.message.edit_text.call_args[0][0]
    assert "125g" in rendered
    # Macros rescaled linearly: 196 kcal * 1.25 = 245
    assert "245" in rendered
    callback.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_qty_minus_respects_minimum(fake_redis):
    chat_id = 702
    edit = {"items": _PAUSED_ITEMS, "qty": {"0": 5.0}, "swaps": {}}
    await tg_session.set_edit_state(chat_id, edit)

    callback = _mock_callback(chat_id, "q:0:-")
    await handlers.on_qty_step(callback)

    new_edit = await tg_session.get_edit_state(chat_id)
    assert new_edit["qty"]["0"] == 5.0  # floored at _MIN_QTY_G


@pytest.mark.asyncio
async def test_swap_open_shows_candidates(fake_redis):
    chat_id = 703
    edit = {"items": _PAUSED_ITEMS, "qty": {}, "swaps": {}}
    await tg_session.set_edit_state(chat_id, edit)

    callback = _mock_callback(chat_id, "sw:0")
    await handlers.on_swap_open(callback)

    callback.message.edit_text.assert_awaited_once()
    keyboard = callback.message.edit_text.call_args[1]["reply_markup"]
    callback_datas = [b.callback_data for row in keyboard.inline_keyboard for b in row]
    assert "pk:0:0" in callback_datas
    assert "pk:0:1" in callback_datas
    assert "pk:0:2" in callback_datas


@pytest.mark.asyncio
async def test_swap_pick_records_swap_and_returns_to_card(fake_redis):
    chat_id = 704
    edit = {"items": _PAUSED_ITEMS, "qty": {}, "swaps": {}}
    await tg_session.set_edit_state(chat_id, edit)

    callback = _mock_callback(chat_id, "pk:0:1")  # "scrambled egg"
    await handlers.on_swap_pick(callback)

    new_edit = await tg_session.get_edit_state(chat_id)
    assert new_edit["swaps"]["0"] == "scrambled egg"

    rendered = callback.message.edit_text.call_args[0][0]
    assert "scrambled egg" in rendered


@pytest.mark.asyncio
async def test_confirm_composes_qty_and_swap_corrections(fake_redis):
    chat_id = 705
    await fake_redis.set("tguser:705", "user-1")

    edit = {
        "items": _PAUSED_ITEMS,
        "qty": {"0": 125.0},
        "swaps": {"1": "wholegrain toast"},
    }
    await tg_session.set_edit_state(chat_id, edit)

    callback = _mock_callback(chat_id, "ok")
    result = {"status": "success", "message": "Logged!", "paused": False, "items": []}
    with patch(
        "backend.telegram.handlers.handle_message", new_callable=AsyncMock
    ) as mock_handle:
        mock_handle.return_value = result
        await handlers.on_confirm(callback)

    mock_handle.assert_awaited_once()
    sent = mock_handle.call_args.kwargs["user_input"]
    assert "change fried egg to 125g" in sent
    assert "use wholegrain toast instead of toast" in sent
    assert " and " in sent

    # Edit state cleared after confirm
    assert await tg_session.get_edit_state(chat_id) is None


@pytest.mark.asyncio
async def test_confirm_with_no_edits_sends_yes(fake_redis):
    chat_id = 706
    await fake_redis.set("tguser:706", "user-1")

    edit = {"items": _PAUSED_ITEMS, "qty": {}, "swaps": {}}
    await tg_session.set_edit_state(chat_id, edit)

    callback = _mock_callback(chat_id, "ok")
    result = {"status": "success", "message": "Logged!", "paused": False, "items": []}
    with patch(
        "backend.telegram.handlers.handle_message", new_callable=AsyncMock
    ) as mock_handle:
        mock_handle.return_value = result
        await handlers.on_confirm(callback)

    assert mock_handle.call_args.kwargs["user_input"] == "yes"


@pytest.mark.asyncio
async def test_cancel_clears_edit_state(fake_redis):
    chat_id = 707
    await fake_redis.set("tguser:707", "user-1")

    edit = {"items": _PAUSED_ITEMS, "qty": {"0": 125.0}, "swaps": {}}
    await tg_session.set_edit_state(chat_id, edit)

    callback = _mock_callback(chat_id, "no")
    result = {
        "status": "success",
        "message": "Cancelled.",
        "paused": False,
        "items": [],
    }
    with patch(
        "backend.telegram.handlers.handle_message", new_callable=AsyncMock
    ) as mock_handle:
        mock_handle.return_value = result
        await handlers.on_cancel(callback)

    assert mock_handle.call_args.kwargs["user_input"] == "cancel"
    assert await tg_session.get_edit_state(chat_id) is None
