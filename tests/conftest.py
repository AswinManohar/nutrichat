from __future__ import annotations

import os

# Set dummy env vars before any module-level LLM initialization
os.environ.setdefault("GOOGLE_API_KEY", "dummy-key-for-testing")
# True when the operator pointed the suite at a real database. The fallback
# below only exists so imports work; integration tests that would write rows
# skip unless DATABASE_URL was set deliberately.
DATABASE_URL_PRESET = "DATABASE_URL" in os.environ
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://nutrichat:nutrichat@127.0.0.1:5411/nutrichat"
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
