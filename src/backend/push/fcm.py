"""Send FCM notifications to a user's registered Android devices.

Lazy-initializes firebase-admin from FIREBASE_CREDENTIALS_JSON (a service
account JSON document, as a string). When the env var is absent (dev, CI),
sending is a logged no-op so the rest of the app never needs Firebase
credentials locally.
"""

from __future__ import annotations

import asyncio
import json
import os

import firebase_admin
import logfire
from firebase_admin import credentials, messaging
from sqlalchemy import delete, select

from backend.db.models import DeviceToken
from backend.db.session import get_session

_app: firebase_admin.App | None = None


def _get_app() -> firebase_admin.App | None:
    """Lazily initialize the firebase-admin app, or None if unconfigured."""
    global _app
    if _app is not None:
        return _app
    raw = os.environ.get("FIREBASE_CREDENTIALS_JSON", "").strip()
    if not raw:
        return None
    _app = firebase_admin.initialize_app(credentials.Certificate(json.loads(raw)))
    return _app


def _send_one(token: str, title: str, body: str, data: dict[str, str]) -> None:
    """Blocking single-message send; called via asyncio.to_thread."""
    messaging.send(
        messaging.Message(
            token=token,
            notification=messaging.Notification(title=title, body=body),
            data=data,
        )
    )


async def send_to_user(
    user_id: str,
    title: str,
    body: str,
    data: dict[str, str] | None = None,
) -> int:
    """Send a push notification to every device registered to user_id.

    Tokens that FCM reports as unregistered are pruned from `device_token`
    so future sends don't keep retrying them.

    Args:
        user_id: Supabase Auth UUID.
        title: Notification title.
        body: Notification body.
        data: Optional string-keyed payload delivered alongside the
            notification (e.g. a deep link).

    Returns:
        Number of tokens the push was successfully sent to.
    """
    if _get_app() is None:
        logfire.info("fcm_disabled", user_id=user_id)
        return 0

    session_factory = get_session()
    async with session_factory() as session:
        tokens = (
            (
                await session.execute(
                    select(DeviceToken.token).where(DeviceToken.user_id == user_id)
                )
            )
            .scalars()
            .all()
        )

        sent = 0
        for token in tokens:
            try:
                await asyncio.to_thread(_send_one, token, title, body, data or {})
                sent += 1
            except messaging.UnregisteredError:
                await session.execute(
                    delete(DeviceToken).where(DeviceToken.token == token)
                )
        await session.commit()
    return sent
