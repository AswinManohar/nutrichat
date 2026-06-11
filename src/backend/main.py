from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from backend.api import goals, meals


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

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(meals.router)
app.include_router(goals.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
