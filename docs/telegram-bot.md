# Telegram bot (M7)

Chat parity with the web app — text + photo meal logging, the same
extract → confirm flow, and coaching Q&A. Multiuser from day one.
Visualization (trends/heatmap/dashboard) stays web-only.

## Setup

1. Create a bot via [@BotFather](https://t.me/BotFather): `/newbot`, choose a
   name and username.
2. Copy the token into `.env`:
   ```bash
   TELEGRAM_BOT_TOKEN=123456:ABC-...
   TELEGRAM_BOT_USERNAME=YourBotUsername   # without the @
   TELEGRAM_USE_WEBHOOK=false              # polling for dev
   ```

## Linking a Telegram account

1. In the web app, go to **Settings -> Telegram Bot -> Connect Telegram**.
2. The app shows a 6-digit code, valid for 10 minutes
   (`POST /telegram/link-code`, stored in Redis as `tglink:code:<code>`).
3. Send `/link <code>` to the bot. It validates the code against Redis and
   writes a row to `telegram_link` (`chat_id <-> user_id`).
4. **Settings -> Telegram Bot -> Disconnect** removes the link
   (`DELETE /telegram/link`).

## Commands

| Command | Behavior |
|---|---|
| `/start` | Welcome message; linking instructions if not yet linked. |
| `/link <code>` | Binds this chat to your NutriChat account. |
| `/new` | Starts a fresh conversation thread (clears context). |
| `/goals` | Shows your daily kcal/protein/fiber goals, dietary prefs, streak. |

## Logging meals

- **Text**: "2 eggs and toast" -> extraction -> confirmation card with
  per-item kcal/protein and totals, plus **Confirm/Cancel** buttons.
- **Photo**: send a photo (optionally with a caption) -> the bot downloads
  the largest size, base64-encodes it, and routes it through the same
  extraction pipeline as the web app's image upload.
- **Corrections**: while a confirmation card is open, reply with free text
  (e.g. "change eggs to 100g and use turkey bacon instead of bacon") instead
  of tapping a button — the graph re-resolves and re-presents the card.
- After a non-paused reply (logged, cancelled, or a coaching answer), the
  active thread rotates (`tgthread:{chat_id}` in Redis) so LangGraph
  checkpoint history doesn't grow unbounded — mirrors the web app's
  per-session `conversationId` behavior.

## Coaching

Any message that isn't part of an active confirmation and isn't an image is
classified as `log_meal` or `coaching` (same `_classify_intent` as the web
app) and answered by the `CoachingAgent` using that user's own totals/goals.

## Running

```bash
uv run python -m backend.telegram.bot   # dev: long polling
```

The bot builds its own `AsyncPostgresSaver` checkpointer against
`DATABASE_URL` and shares Redis (`REDIS_URL`) with the API — no HTTP hop to
the FastAPI service, and no extra service-auth.

## Deployment (Railway)

Run as a separate Railway service (like the Celery worker), or switch to
webhook mode and mount it on the existing FastAPI service:

```bash
TELEGRAM_USE_WEBHOOK=true
TELEGRAM_WEBHOOK_SECRET=<random-secret>
```

In webhook mode, call `backend.telegram.bot.setup_webhook(app)` during
startup (after the checkpointer is ready) and register the webhook URL
(`https://<host>/telegram/webhook`) with Telegram, passing
`secret_token=TELEGRAM_WEBHOOK_SECRET`. The webhook handler checks the
`X-Telegram-Bot-Api-Secret-Token` header against this value.

## Privacy

Photo bytes are never logged — `image_b64` is scrubbed from Logfire spans
(`backend/observability.py:_scrub_extra`), and the bot's spans only record
`has_image` / `image_bytes` (byte length), never raw content.
