"""Shared auth stubs for API tests.

The backend only accepts real Supabase bearer tokens. Tests that exercise an
endpoint as an authenticated user override the `get_current_user_id`
dependency instead, taking the user from the `X-Debug-User-Id` header.
Tests that want the real 401 path simply do not apply the override.
"""

from __future__ import annotations

from fastapi import FastAPI, Request

from backend.auth.supabase import get_current_user_id

DEFAULT_TEST_USER = "user-1"


def header_user_override(request: Request) -> str:
    """Resolve the test user from the X-Debug-User-Id header."""
    return request.headers.get("X-Debug-User-Id", DEFAULT_TEST_USER)


def with_header_auth(app: FastAPI) -> FastAPI:
    """Authenticate `app` requests as the user named in X-Debug-User-Id."""
    app.dependency_overrides[get_current_user_id] = header_user_override
    return app
