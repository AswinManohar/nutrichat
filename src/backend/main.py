from __future__ import annotations
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from backend.api import meals

@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    db_url = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/postgres")
    
    # Utilizing the async context manager from AsyncPostgresSaver ensuring connection pooling lifecycle is handled properly
    async with AsyncPostgresSaver.from_conn_string(db_url) as checkpointer:
        await checkpointer.setup()
        app_instance.state.checkpointer = checkpointer
        yield

app = FastAPI(title="NutriChat", version="0.1.0", lifespan=lifespan)

app.include_router(meals.router)

@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
