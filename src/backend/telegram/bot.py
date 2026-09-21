"""aiogram bot process — runs alongside the FastAPI app and Celery worker.

Builds its own `AsyncPostgresSaver` checkpointer + DB pool against Supabase
(mirrors `backend.main.lifespan`) and calls `handle_message()` in-process —
no HTTP hop, no service-auth. Polling mode for dev; `setup_webhook()` is
provided for prod (guarded by `TELEGRAM_USE_WEBHOOK`).
"""

from __future__ import annotations

import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand
from fastapi import FastAPI, Request, Response

from backend.agent.system_one import warn_if_unconfigured
from backend.db.checkpointer import pooled_checkpointer
from backend.observability import configure_observability
from backend.telegram.handlers import router

logger = logging.getLogger(__name__)

_WEBHOOK_PATH = "/telegram/webhook"

_BOT_COMMANDS = [
    BotCommand(command="start", description="Welcome & account-linking instructions"),
    BotCommand(command="help", description="Show all commands and how to use the bot"),
    BotCommand(command="link", description="Link your account with a code"),
    BotCommand(command="goals", description="Show your calorie/protein/fiber goals"),
    BotCommand(command="progress", description="See today's goal progress"),
    BotCommand(command="new", description="Start a fresh conversation"),
]


async def _register_commands(bot: Bot) -> None:
    """Register the bot's command menu with Telegram.

    Args:
        bot: The aiogram Bot to register commands on.
    """
    await bot.set_my_commands(_BOT_COMMANDS)


def build_bot() -> Bot:
    """Construct the aiogram Bot from `TELEGRAM_BOT_TOKEN`.

    No global parse_mode: replies are sent as plain text. HTML/Markdown
    parsing crashes on literal characters that appear in normal content —
    e.g. "<code>" in the link instructions, or the coaching agent's "**"
    recipe-card markdown — with a TelegramBadRequest, silently dropping the
    reply. Plain text is robust; rich Telegram formatting can be layered in
    later by converting per-message with explicit escaping.
    """
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    return Bot(token=token)


def build_dispatcher() -> Dispatcher:
    """Construct the aiogram Dispatcher with the Mealsy router attached."""
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    return dispatcher


async def run_polling() -> None:
    """Entry point for dev: long-polling. `python -m backend.telegram.bot`."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    configure_observability(None)
    # Webhook mode (prod) runs inside backend.main's lifespan, which warns there.
    warn_if_unconfigured()
    bot = build_bot()
    dispatcher = build_dispatcher()

    async with pooled_checkpointer() as checkpointer:
        bot.checkpointer = checkpointer  # type: ignore[attr-defined]
        await bot.delete_webhook(drop_pending_updates=True)
        await _register_commands(bot)
        logger.info("Starting Telegram bot in polling mode")
        await dispatcher.start_polling(bot)


def setup_webhook(app: FastAPI) -> None:
    """Wire a Telegram webhook route onto an existing FastAPI app (prod).

    Reuses `app.state.checkpointer` (set up by `backend.main.lifespan`) so
    the webhook path shares the same checkpointer pool as the API.

    Args:
        app: The FastAPI app to attach the webhook route to.
    """
    bot = build_bot()
    dispatcher = build_dispatcher()
    secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET")

    asyncio.create_task(_register_commands(bot))

    @app.post(_WEBHOOK_PATH)
    async def telegram_webhook(request: Request) -> Response:
        if secret and request.headers.get("X-Telegram-Bot-Api-Secret-Token") != secret:
            return Response(status_code=401)

        bot.checkpointer = app.state.checkpointer  # type: ignore[attr-defined]
        update = await request.json()
        await dispatcher.feed_webhook_update(bot, update)
        return Response(status_code=200)


if __name__ == "__main__":
    asyncio.run(run_polling())
