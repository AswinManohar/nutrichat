from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.auth.supabase import get_current_user_id
from backend.main import app

_TEST_USER = "00000000-0000-0000-0000-000000000001"


@pytest.mark.integration
def test_chat_history_isolation() -> None:
    """Requires a live Postgres + checkpointer (DATABASE_URL)."""
    app.dependency_overrides[get_current_user_id] = lambda: _TEST_USER
    try:
        with TestClient(app) as client:
            response = client.post(
                "/meals/log",
                json={
                    "user_input": "I ate 2 eggs",
                    "conversation_id": "test_convo_321",
                },
            )
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
    finally:
        app.dependency_overrides.pop(get_current_user_id, None)
