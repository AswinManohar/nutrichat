"""Unit tests for quota.consume_llm_credit()."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch


from backend.quota import FREE_QUOTA, PAID_QUOTA, consume_llm_credit


def _make_session(row=None):
    result = MagicMock()
    result.fetchone.return_value = row
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=session)


async def test_consume_credit_granted_when_under_quota():
    factory = _make_session(row=(1,))
    with patch("backend.quota.get_session", return_value=factory):
        result = await consume_llm_credit("user-abc")
    assert result is True


async def test_consume_credit_denied_when_over_quota():
    factory = _make_session(row=None)
    with patch("backend.quota.get_session", return_value=factory):
        result = await consume_llm_credit("user-abc")
    assert result is False


async def test_consume_credit_new_user_upsert_grants_credit():
    factory = _make_session(row=(1,))
    with patch("backend.quota.get_session", return_value=factory):
        result = await consume_llm_credit("brand-new-user")
    assert result is True


def test_quota_constants():
    assert FREE_QUOTA == 50
    assert PAID_QUOTA == 150
