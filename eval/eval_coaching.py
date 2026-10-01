import asyncio
import os
import json
from dotenv import load_dotenv

load_dotenv()

from backend.agent.coaching import CoachingAgent

USER_ID = "5c3f42d5-4955-4ca6-acd2-3dcb0a043b6d"

QUESTIONS = [
    "what is the most unhealthiest food i had",
    "How much protein did I eat yesterday?",
    "Did I meet my calorie goal this week?",
    "What are my top 3 most frequently eaten foods?",
    "How much fiber have I had so far this month?",
    "Show me the highest calorie foods I ate in the last 7 days.",
    "What was my total fat intake last month?",
    "Have I eaten any junk food recently?",
    "Am I eating enough Vitamin B-12?",
    "What was my calorie intake over the last 90 days?",
    "How does my carbohydrate intake look for this week?",
    "What are my favorite foods to eat?",
    "Am I eating too much sugar?",
    "Did I eat more protein or carbs today?",
    "What's the unhealthiest thing I ate last week?",
    "Is my diet balanced right now?",
    "What's the most calorie-dense food I logged today?",
    "How much iron did I get from my meals in the last 30 days?",
    "Show me my macro breakdown for yesterday.",
    "What should I cut back on to improve my health?",
    "Have I hit my fiber goal today?",
    "What's the healthiest food I've eaten this month?",
    "How many calories do I have left for today?",
    "What did I eat most often in the past two months?",
    "Tell me my average daily protein intake for the last 30 days.",
    "Have I logged any meals that are considered unhealthy?",
    "What is my vitamin D intake looking like?",
    "Did I hit my protein goal every day last week?",
    "What are the most frequent junk foods I consume?",
    "How much water did I drink yesterday?",
    "Summarize my nutrition for the last 7 days."
]

async def main():
    agent = CoachingAgent()
    results = []
    
    for i, q in enumerate(QUESTIONS):
        print(f"\n--- Question {i+1}/{len(QUESTIONS)} ---")
        print(f"Q: {q}")
        try:
            # We don't want to hit rate limits or timeout, so we add a small sleep
            # wait, the Google API handles some concurrency but we are sequential here.
            response = await agent.handle(USER_ID, q)
            print(f"A: {response}")
            results.append({"q": q, "a": response, "status": "success"})
        except Exception as e:
            print(f"Error: {e}")
            results.append({"q": q, "error": str(e), "status": "error"})
        
        await asyncio.sleep(1)
        
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "coaching_eval_results.json")
    with open(out, "w") as f:
        json.dump(results, f, indent=2)

if __name__ == "__main__":
    asyncio.run(main())
