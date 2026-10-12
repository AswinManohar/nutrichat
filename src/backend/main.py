from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.agent.system_one import warm_up, warn_if_unconfigured
from backend.api import (
    account,
    billing,
    coaching_feedback,
    devices,
    foods,
    goals,
    integrations,
    meals,
    memory,
    meta,
    mindful,
    my_meals,
    nutrient_checkup,
    push,
    quota,
    telegram_link,
)
from backend.db.checkpointer import pooled_checkpointer
from backend.observability import configure_observability
from backend.ratelimit import RateLimitMiddleware


@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    warn_if_unconfigured()
    # Background: never delays startup; the reference keeps it from being GC'd.
    app_instance.state.typesafe_warm_up = asyncio.create_task(warm_up())
    async with pooled_checkpointer() as checkpointer:
        app_instance.state.checkpointer = checkpointer
        yield


app = FastAPI(title="Mealsy", version="0.1.0", lifespan=lifespan)

configure_observability(app)

# Production frontend (Vercel) origin, in addition to localhost dev origins.
# Set FRONTEND_ORIGIN to the deployed Vercel URL, e.g.
# https://nutrichat.vercel.app — comma-separated values are supported for
# preview deployments (e.g. multiple Vercel preview URLs).
_frontend_origins = [
    origin.strip()
    for origin in os.environ.get("FRONTEND_ORIGIN", "").split(",")
    if origin.strip()
]

# Coarse per-IP flood protection; per-user limits live on the routers.
# Middleware runs outermost-added-last, so CORS (added after) still wraps
# 429 responses with the proper CORS headers.
app.add_middleware(
    RateLimitMiddleware,
    limit=int(os.environ.get("RATE_LIMIT_IP_PER_MIN", "120")),
    window_s=60,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_frontend_origins,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(meals.router)
app.include_router(goals.router)
app.include_router(quota.router)
app.include_router(billing.router)
app.include_router(integrations.router)
app.include_router(telegram_link.router)
app.include_router(nutrient_checkup.router)
app.include_router(mindful.router)
app.include_router(my_meals.router)
app.include_router(push.router)
app.include_router(devices.router)
app.include_router(meta.router)
app.include_router(account.router)
app.include_router(foods.router)
app.include_router(coaching_feedback.router)
app.include_router(memory.router)

if os.environ.get("TELEGRAM_USE_WEBHOOK", "false").lower() == "true":
    from backend.telegram.bot import setup_webhook

    setup_webhook(app)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
