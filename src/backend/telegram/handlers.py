"""aiogram message/command/callback handlers for the NutriChat bot.

Each handler resolves `chat_id -> user_id` via `auth.resolve_user_id`,
delegates to `handle_message()` (the same orchestrator entry point the web
app uses), and renders the response. A paused meal-logging turn shows a
summary + Confirm/Cancel inline keyboard; free-text replies while paused
flow straight into `handle_message()` as corrections.
"""

from __future__ import annotations

import base64
from typing import Any

import logfire
from aiogram import Bot, F, Router
from aiogram.enums import ChatAction
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy import delete, or_

from backend.agent.orchestrator import handle_message
from backend.db.models import TelegramLink, UserGoal
from backend.db.redis_client import get_redis, get_today_totals
from backend.db.session import get_session
from backend.telegram.auth import cache_user_id, resolve_user_id
from backend.telegram.session import (
    clear_edit_state,
    get_edit_state,
    get_thread_id,
    rotate_thread,
    set_edit_state,
)

router = Router(name="nutrichat")

_LINK_CODE_PREFIX = "tglink:code:"

_NOT_LINKED_MSG = (
    "Your Telegram account isn't linked yet.\n\n"
    "Open NutriChat in your browser, go to Settings -> Telegram Bot, "
    'tap "Connect Telegram", and send me the code with /link <code>.'
)

_CONFIRM_CALLBACK = "ok"
_CANCEL_CALLBACK = "no"

_QTY_STEP_G = 25.0
_MIN_QTY_G = 5.0
_SHORT_NAME_LEN = 18

_HELP_MSG = (
    "NutriChat commands:\n\n"
    "/start - welcome message & account-linking instructions\n"
    "/help - show this list\n"
    "/link <code> - link your Telegram to your NutriChat account "
    "(get the code from the web app -> Settings -> Telegram)\n"
    "/goals - show your current calorie/protein/fiber goals\n"
    "/progress - see how much of today's goals you've hit\n"
    "/new - start a fresh conversation (resets the current "
    "meal-logging thread)\n\n"
    "Just type what you ate (e.g. \"2 eggs and toast\"), send a food "
    "photo, or ask a question like \"how much protein today?\""
)


def _short_name(food_name: str) -> str:
    """Truncate a food name for display on an inline keyboard button."""
    if len(food_name) <= _SHORT_NAME_LEN:
        return food_name
    return food_name[: _SHORT_NAME_LEN - 1] + "…"


def _display_item(item: dict[str, Any], edit: dict[str, Any], i: int) -> dict[str, Any]:
    """Apply pending qty/swap overrides from edit state to one item.

    Args:
        item: Original item dict from the paused `handle_message()` result.
        edit: Edit state dict with "qty" and "swaps" maps (str keys).
        i: Item index.

    Returns:
        A copy of `item` with `food_name`/`qty_g` and macros rescaled
        linearly to the overridden qty (nutrients are per-gram linear).
    """
    out = dict(item)
    out["food_name"] = edit["swaps"].get(str(i), item["food_name"])
    new_qty = edit["qty"].get(str(i), item["qty_g"])
    out["qty_g"] = new_qty
    scale = new_qty / item["qty_g"] if item["qty_g"] else 1.0
    for macro in ("kcal", "protein_g", "carbs_g", "fat_g", "fiber_g"):
        out[macro] = item[macro] * scale
    return out


def _format_items(items: list[dict[str, Any]]) -> str:
    """Format paused meal items as a human-readable summary.

    Args:
        items: Display-ready items (after applying any pending edits).

    Returns:
        Multi-line summary: one line per item plus totals.
    """
    lines = []
    total_kcal = total_protein = 0.0
    for item in items:
        lines.append(
            f"- {item['food_name']} ({item['qty_g']:.0f}g): "
            f"{item['kcal']:.0f} kcal, {item['protein_g']:.1f}g protein"
        )
        total_kcal += item["kcal"]
        total_protein += item["protein_g"]
    lines.append("")
    lines.append(f"Total: {total_kcal:.0f} kcal, {total_protein:.1f}g protein")
    return "\n".join(lines)


def _meal_keyboard(items: list[dict[str, Any]], edit: dict[str, Any]) -> InlineKeyboardMarkup:
    """Build the per-item qty/swap rows plus the Confirm/Cancel footer.

    Args:
        items: Original `items` list from the paused result.
        edit: Edit state dict with "qty" and "swaps" maps (str keys).

    Returns:
        Inline keyboard: one row per item (- qty / name+qty / + qty,
        followed by a Swap button if the item has >1 candidate), then a
        Confirm/Cancel footer row.
    """
    rows: list[list[InlineKeyboardButton]] = []
    for i, item in enumerate(items):
        display = _display_item(item, edit, i)
        row = [
            InlineKeyboardButton(text="−25g", callback_data=f"q:{i}:-"),
            InlineKeyboardButton(
                text=f"{_short_name(display['food_name'])} {display['qty_g']:.0f}g",
                callback_data="noop",
            ),
            InlineKeyboardButton(text="+25g", callback_data=f"q:{i}:+"),
        ]
        rows.append(row)
        if len(item["candidates"]) > 1:
            rows.append(
                [InlineKeyboardButton(text="↹ Swap", callback_data=f"sw:{i}")]
            )
    rows.append(
        [
            InlineKeyboardButton(text="✅ Confirm", callback_data=_CONFIRM_CALLBACK),
            InlineKeyboardButton(text="❌ Cancel", callback_data=_CANCEL_CALLBACK),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _swap_keyboard(item: dict[str, Any], i: int) -> InlineKeyboardMarkup:
    """Build the candidate-picker keyboard for one item.

    Args:
        item: Original item dict (its `candidates` list is indexed).
        i: Item index.

    Returns:
        One button per candidate (`pk:<i>:<cand_idx>`) plus a back button.
    """
    rows = [
        [InlineKeyboardButton(text=_short_name(cand), callback_data=f"pk:{i}:{j}")]
        for j, cand in enumerate(item["candidates"])
    ]
    rows.append([InlineKeyboardButton(text="« Back", callback_data=f"bk:{i}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _card_text(message: str, items: list[dict[str, Any]], edit: dict[str, Any]) -> str:
    """Build the summary text for a paused meal card.

    Args:
        message: The orchestrator's message for this turn.
        items: Original `items` list from the paused result.
        edit: Edit state dict with "qty" and "swaps" maps (str keys).

    Returns:
        Summary text + correction hint.
    """
    display_items = [_display_item(item, edit, i) for i, item in enumerate(items)]
    return (
        f"{message}\n\n"
        f"{_format_items(display_items)}\n\n"
        'Reply with a correction like "change eggs to 100g", '
        "or tap a button below."
    )


async def _render_result(message: Message, result: dict[str, Any]) -> None:
    """Send a `handle_message()` result back to the chat.

    If paused, stores fresh edit state in Redis and sends the item summary
    with the qty/swap/confirm/cancel keyboard plus a correction hint.
    Otherwise sends the plain reply and rotates the active thread so
    history doesn't grow unbounded.

    Args:
        message: The incoming aiogram message (used to reply into the chat).
        result: Dict with status, message, paused, and items.
    """
    if result["paused"] and result["items"]:
        items = result["items"]
        edit = {"items": items, "qty": {}, "swaps": {}}
        await set_edit_state(message.chat.id, edit)
        text = _card_text(result["message"], items, edit)
        await message.answer(text, reply_markup=_meal_keyboard(items, edit))
    else:
        await message.answer(result["message"] or "Done.")
        await rotate_thread(message.chat.id)
        await clear_edit_state(message.chat.id)


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    """Welcome message + linking instructions."""
    user_id = await resolve_user_id(message.chat.id)
    if user_id:
        await message.answer(
            "Welcome back! Tell me what you ate, send a photo, or ask a "
            "nutrition question. Send /help to see all commands."
        )
    else:
        await message.answer(
            "Welcome to NutriChat!\n\n" + _NOT_LINKED_MSG + "\n\nSend /help "
            "to see all commands."
        )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    """List all available commands and basic usage instructions."""
    await message.answer(_HELP_MSG)


@router.message(Command("link"))
async def cmd_link(message: Message, command: CommandObject) -> None:
    """Validate a link code from Redis and bind chat_id <-> user_id.

    Args:
        message: Incoming `/link <code>` message.
        command: Parsed command with `args` holding the code.
    """
    code = (command.args or "").strip()
    if not code:
        await message.answer("Usage: /link <code> (from Settings -> Telegram Bot)")
        return

    client = get_redis()
    redis_key = f"{_LINK_CODE_PREFIX}{code}"
    user_id = await client.get(redis_key)
    if not user_id:
        await message.answer(
            "That code is invalid or expired. Generate a new one from "
            "Settings -> Telegram Bot."
        )
        return

    session_factory = get_session()
    async with session_factory() as session:
        # Remove any existing link involving this chat or this user (in
        # either direction) so the fresh insert below can't collide on
        # either the chat_id primary key or the user_id unique constraint.
        # Re-linking the same (chat_id, user_id) pair is then a harmless
        # delete + re-insert, i.e. idempotent.
        await session.execute(
            delete(TelegramLink).where(
                or_(
                    TelegramLink.chat_id == message.chat.id,
                    TelegramLink.user_id == user_id,
                )
            )
        )
        session.add(TelegramLink(chat_id=message.chat.id, user_id=user_id))
        await session.commit()

    await client.delete(redis_key)
    await cache_user_id(message.chat.id, user_id)
    await message.answer(
        "Linked! You can now log meals and ask coaching questions here."
    )


@router.message(Command("new"))
async def cmd_new(message: Message) -> None:
    """Clear the active conversation thread for this chat."""
    user_id = await resolve_user_id(message.chat.id)
    if not user_id:
        await message.answer(_NOT_LINKED_MSG)
        return

    await rotate_thread(message.chat.id)
    await message.answer("Started a new conversation.")


@router.message(Command("goals"))
async def cmd_goals(message: Message) -> None:
    """Show the user's current nutrition goals."""
    user_id = await resolve_user_id(message.chat.id)
    if not user_id:
        await message.answer(_NOT_LINKED_MSG)
        return

    session_factory = get_session()
    async with session_factory() as session:
        goal = await session.get(UserGoal, user_id)

    if goal is None:
        await message.answer(
            "You haven't set up nutrition goals yet — use the web app first."
        )
        return

    prefs = ", ".join(k for k, v in goal.dietary_prefs.items() if v) or "none"
    await message.answer(
        "Your daily goals:\n"
        f"- Calories: {goal.kcal_goal:.0f} kcal\n"
        f"- Protein: {goal.protein_goal:.0f} g\n"
        f"- Fiber: {goal.fiber_goal:.0f} g\n"
        f"- Dietary preferences: {prefs}\n"
        f"- Streak: {goal.streak_days} day(s)"
    )


def _progress_bar(consumed: float, goal: float, width: int = 10) -> tuple[str, int]:
    """Build a simple text progress bar and the (uncapped-display) percent.

    Args:
        consumed: Amount consumed so far today.
        goal: Daily goal amount.
        width: Number of characters in the bar.

    Returns:
        Tuple of (bar string like "[█████░░░░░]", percent capped at 100).
    """
    if goal <= 0:
        ratio = 0.0
    else:
        ratio = consumed / goal
    percent = min(100, round(ratio * 100))
    filled = min(width, round(ratio * width))
    bar = "[" + "█" * filled + "░" * (width - filled) + "]"
    return bar, percent


@router.message(Command("progress"))
async def cmd_progress(message: Message) -> None:
    """Show today's progress toward calorie/protein/fiber goals."""
    user_id = await resolve_user_id(message.chat.id)
    if not user_id:
        await message.answer(_NOT_LINKED_MSG)
        return

    session_factory = get_session()
    async with session_factory() as session:
        goal = await session.get(UserGoal, user_id)

    if goal is None:
        await message.answer(
            "You haven't set up nutrition goals yet — use the web app first."
        )
        return

    totals = await get_today_totals(user_id)

    if totals.n_meals == 0:
        kcal_bar, _ = _progress_bar(0, goal.kcal_goal)
        protein_bar, _ = _progress_bar(0, goal.protein_goal)
        fiber_bar, _ = _progress_bar(0, goal.fiber_goal)
        await message.answer(
            "Nothing logged yet today.\n\n"
            f"🔥 Calories {kcal_bar} 0%\n"
            f"💪 Protein {protein_bar} 0%\n"
            f"🌾 Fiber {fiber_bar} 0%"
        )
        return

    kcal_bar, kcal_pct = _progress_bar(totals.kcal, goal.kcal_goal)
    protein_bar, protein_pct = _progress_bar(totals.protein_g, goal.protein_goal)
    fiber_bar, fiber_pct = _progress_bar(totals.fiber_g, goal.fiber_goal)

    kcal_remaining = max(0.0, goal.kcal_goal - totals.kcal)
    protein_remaining = max(0.0, goal.protein_goal - totals.protein_g)
    fiber_remaining = max(0.0, goal.fiber_goal - totals.fiber_g)

    await message.answer(
        "Today's progress:\n\n"
        f"🔥 Calories {kcal_bar} {kcal_pct}%\n"
        f"{totals.kcal:.0f} / {goal.kcal_goal:.0f} kcal "
        f"({kcal_remaining:.0f} kcal left)\n\n"
        f"💪 Protein {protein_bar} {protein_pct}%\n"
        f"{totals.protein_g:.0f} / {goal.protein_goal:.0f} g "
        f"({protein_remaining:.0f} g left)\n\n"
        f"🌾 Fiber {fiber_bar} {fiber_pct}%\n"
        f"{totals.fiber_g:.0f} / {goal.fiber_goal:.0f} g "
        f"({fiber_remaining:.0f} g left)\n\n"
        f"Meals logged: {totals.n_meals}"
    )


def _compose_correction(edit: dict[str, Any]) -> str:
    """Build the same natural-language correction text the web card sends.

    Args:
        edit: Edit state dict with "items", "qty", and "swaps" maps.

    Returns:
        "yes" if there are no pending edits, otherwise the qty/swap
        corrections joined with " and ", e.g. "change eggs to 100g and use
        scrambled egg instead of fried egg".
    """
    items = edit["items"]
    corrections: list[str] = []
    for i, item in enumerate(items):
        key = str(i)
        if key in edit["swaps"]:
            corrections.append(f"use {edit['swaps'][key]} instead of {item['food_name']}")
        if key in edit["qty"] and round(edit["qty"][key]) != round(item["qty_g"]):
            corrections.append(f"change {item['food_name']} to {round(edit['qty'][key])}g")
    return " and ".join(corrections) if corrections else "yes"


@router.callback_query(F.data == "noop")
async def on_noop(callback: CallbackQuery) -> None:
    """Acknowledge taps on the non-interactive name/qty label button."""
    await callback.answer()


@router.callback_query(F.data.startswith("q:"))
async def on_qty_step(callback: CallbackQuery) -> None:
    """Adjust an item's pending quantity by +/-25g and re-render the card."""
    if callback.message is None:
        await callback.answer()
        return

    _, idx_str, sign = callback.data.split(":")
    i = int(idx_str)

    edit = await get_edit_state(callback.message.chat.id)
    if edit is None:
        await callback.answer("This card has expired.", show_alert=True)
        return

    item = edit["items"][i]
    current = edit["qty"].get(idx_str, item["qty_g"])
    delta = _QTY_STEP_G if sign == "+" else -_QTY_STEP_G
    edit["qty"][idx_str] = max(_MIN_QTY_G, current + delta)
    await set_edit_state(callback.message.chat.id, edit)

    await callback.answer()
    items = edit["items"]
    text = _card_text(callback.message.text or "", items, edit)
    await callback.message.edit_text(text, reply_markup=_meal_keyboard(items, edit))


@router.callback_query(F.data.startswith("sw:"))
async def on_swap_open(callback: CallbackQuery) -> None:
    """Show the candidate picker for one item."""
    if callback.message is None:
        await callback.answer()
        return

    i = int(callback.data.split(":")[1])
    edit = await get_edit_state(callback.message.chat.id)
    if edit is None:
        await callback.answer("This card has expired.", show_alert=True)
        return

    await callback.answer()
    item = edit["items"][i]
    await callback.message.edit_text(
        f"Pick a replacement for {edit['swaps'].get(str(i), item['food_name'])}:",
        reply_markup=_swap_keyboard(item, i),
    )


@router.callback_query(F.data.startswith("bk:"))
async def on_swap_back(callback: CallbackQuery) -> None:
    """Return from the candidate picker to the main card."""
    if callback.message is None:
        await callback.answer()
        return

    edit = await get_edit_state(callback.message.chat.id)
    if edit is None:
        await callback.answer("This card has expired.", show_alert=True)
        return

    await callback.answer()
    items = edit["items"]
    text = _card_text(callback.message.text or "", items, edit)
    await callback.message.edit_text(text, reply_markup=_meal_keyboard(items, edit))


@router.callback_query(F.data.startswith("pk:"))
async def on_swap_pick(callback: CallbackQuery) -> None:
    """Record a candidate swap and return to the main card."""
    if callback.message is None:
        await callback.answer()
        return

    _, idx_str, cand_idx_str = callback.data.split(":")
    i, cand_idx = int(idx_str), int(cand_idx_str)

    edit = await get_edit_state(callback.message.chat.id)
    if edit is None:
        await callback.answer("This card has expired.", show_alert=True)
        return

    item = edit["items"][i]
    candidate = item["candidates"][cand_idx]
    if candidate == item["food_name"]:
        edit["swaps"].pop(idx_str, None)
    else:
        edit["swaps"][idx_str] = candidate
    await set_edit_state(callback.message.chat.id, edit)

    await callback.answer()
    items = edit["items"]
    text = _card_text(callback.message.text or "", items, edit)
    await callback.message.edit_text(text, reply_markup=_meal_keyboard(items, edit))


@router.callback_query(F.data == _CONFIRM_CALLBACK)
async def on_confirm(callback: CallbackQuery) -> None:
    """Resume the paused graph with the composed correction (or "yes")."""
    edit = await get_edit_state(callback.message.chat.id) if callback.message else None
    correction = _compose_correction(edit) if edit else "yes"
    await _handle_callback(callback, correction)


@router.callback_query(F.data == _CANCEL_CALLBACK)
async def on_cancel(callback: CallbackQuery) -> None:
    """Resume a paused meal-logging graph with a cancellation."""
    await _handle_callback(callback, "cancel")


async def _handle_callback(callback: CallbackQuery, reply_text: str) -> None:
    """Resolve the user, resume the paused graph, and render the result.

    Args:
        callback: The Confirm/Cancel callback query.
        reply_text: The text forwarded to `handle_message()` — either the
            composed correction, "yes", or "cancel".
    """
    if callback.message is None:
        await callback.answer()
        return

    user_id = await resolve_user_id(callback.message.chat.id)
    if not user_id:
        await callback.answer("Not linked.", show_alert=True)
        return

    await callback.answer()
    checkpointer = callback.bot.checkpointer  # type: ignore[union-attr]
    thread_id = await get_thread_id(callback.message.chat.id)

    with logfire.span(
        "telegram_update", chat_id=callback.message.chat.id, kind="callback"
    ):
        result = await handle_message(
            user_id=user_id,
            user_input=reply_text,
            thread_id=thread_id,
            checkpointer=checkpointer,
        )

    await clear_edit_state(callback.message.chat.id)
    await _render_result(callback.message, result)


@router.message(F.photo)
async def on_photo(message: Message, bot: Bot) -> None:
    """Download the largest photo size and forward it as meal-logging input.

    Args:
        message: Incoming photo message.
        bot: The aiogram Bot, used to fetch and download the file.
    """
    user_id = await resolve_user_id(message.chat.id)
    if not user_id:
        await message.answer(_NOT_LINKED_MSG)
        return

    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)

    largest = message.photo[-1]
    file = await bot.get_file(largest.file_id)
    buffer = await bot.download_file(file.file_path)
    image_b64 = base64.b64encode(buffer.read()).decode("ascii")

    checkpointer = bot.checkpointer  # type: ignore[attr-defined]
    thread_id = await get_thread_id(message.chat.id)
    user_text = message.caption or "What did I eat?"

    with logfire.span(
        "telegram_update",
        chat_id=message.chat.id,
        kind="photo",
        has_image=True,
        image_bytes=len(image_b64),
    ):
        result = await handle_message(
            user_id=user_id,
            user_input=user_text,
            thread_id=thread_id,
            checkpointer=checkpointer,
            image_b64=image_b64,
        )

    await _render_result(message, result)


@router.message(F.text)
async def on_text(message: Message, bot: Bot) -> None:
    """Catch-all text handler: route to the orchestrator and render."""
    user_id = await resolve_user_id(message.chat.id)
    if not user_id:
        await message.answer(_NOT_LINKED_MSG)
        return

    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)

    checkpointer = bot.checkpointer  # type: ignore[attr-defined]
    thread_id = await get_thread_id(message.chat.id)

    with logfire.span("telegram_update", chat_id=message.chat.id, kind="text"):
        result = await handle_message(
            user_id=user_id,
            user_input=message.text or "",
            thread_id=thread_id,
            checkpointer=checkpointer,
        )

    await _render_result(message, result)
