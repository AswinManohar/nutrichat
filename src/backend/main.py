from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from backend.api import (
    goals,
    integrations,
    meals,
    mindful,
    my_meals,
    nutrient_checkup,
    quota,
    telegram_link,
)
from backend.observability import configure_observability


@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    db_url = os.environ.get(
        "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/postgres"
    )
    # AsyncPostgresSaver uses psycopg (v3) which needs plain postgresql:// not +asyncpg
    psycopg_url = db_url.replace("postgresql+asyncpg://", "postgresql://")

    async with AsyncPostgresSaver.from_conn_string(psycopg_url) as checkpointer:
        await checkpointer.setup()
        app_instance.state.checkpointer = checkpointer
        yield


app = FastAPI(title="NutriChat", version="0.1.0", lifespan=lifespan)

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
app.include_router(integrations.router)
app.include_router(telegram_link.router)
app.include_router(nutrient_checkup.router)
app.include_router(mindful.router)
app.include_router(my_meals.router)

if os.environ.get("TELEGRAM_USE_WEBHOOK", "false").lower() == "true":
    from backend.telegram.bot import setup_webhook

    setup_webhook(app)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
