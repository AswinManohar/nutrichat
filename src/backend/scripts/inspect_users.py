import asyncio
from sqlalchemy import text as sa_text
from dotenv import load_dotenv
load_dotenv()

from backend.db.session import get_session, dispose_engine

async def main():
    session_factory = get_session()
    async with session_factory() as session:
        # Check users in user_goal
        res = await session.execute(sa_text("SELECT user_id, kcal_goal, protein_goal, streak_days FROM user_goal"))
        users = res.fetchall()
        print("--- USER GOALS ---")
        for u in users:
            print(f"User ID: {u[0]} | kcal_goal: {u[1]} | protein_goal: {u[2]} | streak: {u[3]}")
            
        # Count meals per user
        res = await session.execute(sa_text("SELECT user_id, COUNT(*), MIN(logged_at), MAX(logged_at) FROM meal_log GROUP BY user_id"))
        meals = res.fetchall()
        print("\n--- MEAL LOG COUNTS ---")
        for m in meals:
            print(f"User ID: {m[0]} | Count: {m[1]} | First: {m[2]} | Last: {m[3]}")
            
    await dispose_engine()

if __name__ == "__main__":
    asyncio.run(main())
