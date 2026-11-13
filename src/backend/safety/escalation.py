"""Store a red-flag escalation and hand it to the notification task.

Only ids reach logs and spans (FR-040c); the message text stays in the row.
"""

from __future__ import annotations

import os

import logfire
from kombu.exceptions import OperationalError
from sqlalchemy.exc import SQLAlchemyError

from backend.db.models import RedFlagEscalation
from backend.db.session import get_session
from backend.safety.red_flags import RedFlagMatch
from backend.workers.tasks import notify_escalation


async def record_escalation(
    user_id: str, conversation_id: str | None, message: str, match: RedFlagMatch
) -> None:
    """Persist the escalation, then enqueue the webhook when one is configured.

    Never raises: the patient's fixed reply must not wait on, or fail with,
    the bookkeeping. Failures are logged as errors.

    Args:
        user_id: The patient's Supabase Auth UUID.
        conversation_id: Chat thread the message came in on.
        message: The patient's text (stored for the reviewer only).
        match: The rule that matched.
    """
    has_recipient = bool(os.environ.get("SAFETY_WEBHOOK_URL"))
    row = RedFlagEscalation(
        user_id=user_id,
        conversation_id=conversation_id,
        message=message,
        rule_id=match.rule_id,
        rule_label=match.label,
        rules_version=match.rules_version,
        notify_status="pending" if has_recipient else "no_recipient",
    )
    try:
        async with get_session()() as session:
            session.add(row)
            await session.commit()
            escalation_id = row.id
    except SQLAlchemyError as exc:
        logfire.error(
            "red-flag escalation not stored",
            user_id=user_id,
            rule_id=match.rule_id,
            error=type(exc).__name__,
        )
        return
    if not has_recipient:
        logfire.error(
            "red-flag escalation has no recipient: SAFETY_WEBHOOK_URL is unset",
            user_id=user_id,
            rule_id=match.rule_id,
            escalation_id=escalation_id,
        )
        return
    try:
        notify_escalation.delay(escalation_id)
    except (OperationalError, OSError) as exc:
        logfire.error(
            "red-flag notification not enqueued",
            user_id=user_id,
            escalation_id=escalation_id,
            error=type(exc).__name__,
        )
