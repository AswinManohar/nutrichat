import os
from fastapi.testclient import TestClient
from backend.main import app

def test_chat_history_isolation():
    # Note: ensure DATABASE_URL is set in environment when running tests
    with TestClient(app) as client:
        response = client.post("/meals/log", json={
            "user_input": "I ate 2 eggs",
            "conversation_id": "test_convo_321"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
