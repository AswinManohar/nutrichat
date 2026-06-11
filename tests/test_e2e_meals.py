from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.main import app


@pytest.mark.integration
def test_chat_history_isolation() -> None:
    """Requires a live Postgres + checkpointer (DATABASE_URL)."""
    with TestClient(app) as client:
        response = client.post(
            "/meals/log",
            json={"user_input": "I ate 2 eggs", "conversation_id": "test_convo_321"},
            headers={"X-Debug-User-Id": "00000000-0000-0000-0000-000000000001"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
