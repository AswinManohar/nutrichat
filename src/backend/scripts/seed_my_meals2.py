import asyncio
import os
import random
import uuid
from datetime import datetime, time, timedelta, timezone
from sqlalchemy import text as sa_text
import json

from dotenv import load_dotenv
load_dotenv()

from backend.db.session import get_session, dispose_engine

async def main():
    user_id = "5c3f42d5-4955-4ca6-acd2-3dcb0a043b6d"
    session_factory = get_session()
    async with session_factory() as session:
        # Template from user3 (healthy)
        template = {
            "meal_type": "lunch",
            "kcal": 420.0, "protein_g": 22.0, "carbs_g": 55.0, "fat_g": 12.0, "fiber_g": 10.0,
            "entities": [
                {"food_name": "Lentil curry", "qty_g": 280.0, "kcal": 280.0,
                 "protein_g": 16.0, "carbs_g": 38.0, "fat_g": 8.0, "fiber_g": 10.0, "confidence": 1.0, "unit": "g"},
                {"food_name": "Mixed berries", "qty_g": 100.0, "kcal": 80.0,
                 "protein_g": 1.0, "carbs_g": 14.0, "fat_g": 3.0, "fiber_g": 3.0, "confidence": 1.0, "unit": "g"},
            ],
            "flags": {"has_junk": False, "junk_items": []},
        }

        rng = random.Random(99)
        today = datetime.now(timezone.utc).date()
        
        count = 0
        for offset in range(30):
            day = today - timedelta(days=offset)
            t = time(hour=rng.randint(12, 14), minute=rng.choice([0, 15, 30, 45]))
            logged_at = datetime.combine(day, t, tzinfo=timezone.utc)
            
            var = rng.uniform(0.8, 1.2)
            
            row_data = {
                "meal_id": str(uuid.uuid4()),
                "user_id": user_id,
                "logged_at": logged_at,
                "meal_type": "lunch",
                "kcal": template["kcal"] * var,
                "protein_g": template["protein_g"] * var,
                "carbs_g": template["carbs_g"] * var,
                "fat_g": template["fat_g"] * var,
                "fiber_g": template["fiber_g"] * var,
                "entities": template["entities"],
                "flags": template["flags"],
                "updated_at": logged_at,
            }
            
            await session.execute(
                sa_text(
                    "INSERT INTO meal_log "
                    "(meal_id, user_id, logged_at, meal_type, kcal, protein_g, "
                    "carbs_g, fat_g, fiber_g, entities, flags, updated_at) "
                    "VALUES (:meal_id, :user_id, :logged_at, :meal_type, :kcal, "
                    ":protein_g, :carbs_g, :fat_g, :fiber_g, "
                    "CAST(:entities AS jsonb), CAST(:flags AS jsonb), :updated_at)"
                ),
                {
                    **row_data,
                    "entities": json.dumps(row_data["entities"]),
                    "flags": json.dumps(row_data["flags"]),
                },
            )
            count += 1
            
        await session.commit()
        print(f"Successfully logged {count} meals for user {user_id}")

    await dispose_engine()

if __name__ == "__main__":
    asyncio.run(main())
