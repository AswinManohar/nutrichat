from __future__ import annotations

import os

# Set dummy env vars before any module-level LLM initialization
os.environ.setdefault("GOOGLE_API_KEY", "dummy-key-for-testing")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://nutrichat:nutrichat@127.0.0.1:5411/nutrichat")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
