from __future__ import annotations

import os
from typing import Optional
from pydantic import BaseModel, ConfigDict
import redis.asyncio as redis

# Global connection pool 
_redis_pool: Optional[redis.Redis] = None

def get_redis() -> redis.Redis:
    """Returns the globally active Redis connection pool manager."""
    global _redis_pool
    if _redis_pool is None:
        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        _redis_pool = redis.from_url(redis_url, encoding="utf-8", decode_responses=True)
    return _redis_pool

class TodayTotals(BaseModel):
    """Pydantic model holding validated memory properties for the active user's daily tracker."""
    kcal: float = 0.0
    protein_g: float = 0.0
    fiber_g: float = 0.0
    n_meals: int = 0
    
    model_config = ConfigDict(extra="forbid")

async def get_today_totals(user_id: str) -> TodayTotals:
    """Retrieves session memory totals for the current active day from Redis directly mapping into TodayTotals."""
    client = get_redis()
    key = f"today:{user_id}"
    data = await client.hgetall(key)
    
    if not data:
        return TodayTotals()
        
    return TodayTotals(
        kcal=float(data.get("kcal", 0.0)),
        protein_g=float(data.get("protein_g", 0.0)),
        fiber_g=float(data.get("fiber_g", 0.0)),
        n_meals=int(data.get("n_meals", 0))
    )

async def increment_today(user_id: str, kcal: float, protein_g: float, fiber_g: float) -> TodayTotals:
    """
    Pipelines increment transactions preventing double-submits.
    Automatically refreshes the 24h key TTL safely tracking macros.
    """
    client = get_redis()
    key = f"today:{user_id}"
    
    async with client.pipeline(transaction=True) as pipe:
        pipe.hincrbyfloat(key, "kcal", kcal)
        pipe.hincrbyfloat(key, "protein_g", protein_g)
        pipe.hincrbyfloat(key, "fiber_g", fiber_g)
        pipe.hincrby(key, "n_meals", 1)
        pipe.expire(key, 86400) # Enforce 24-hour TTL boundary on active key
        results = await pipe.execute()
        
    # Map the returning mapped pipe responses securely:
    return TodayTotals(
        kcal=float(results[0]),
        protein_g=float(results[1]),
        fiber_g=float(results[2]),
        n_meals=int(results[3])
    )

async def reset_day_key(user_id: str) -> None:
    """Unlink function utilized typically by Celery cron cleanup at midnight."""
    client = get_redis()
    key = f"today:{user_id}"
    await client.delete(key)
