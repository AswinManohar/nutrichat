"""Mint a service token for the read-only integration API.

Generates an `nck_<random>` token, stores its SHA-256 hash in
`integration_token`, and prints the plaintext token once. The plaintext is
never stored — if lost, mint a new token and revoke the old one.

Usage:
    DATABASE_URL=postgresql+asyncpg://... uv run python -m backend.scripts.mint_token \\
        --user-id <uuid> --name "life-os"
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import secrets

from sqlalchemy import text as sa_text

from backend.db.session import dispose_engine, get_session

_TOKEN_PREFIX = "nck_"


async def _mint(user_id: str, name: str, scopes: list[str]) -> str:
    """Insert a new integration_token row and return the plaintext token.

    Args:
        user_id: Supabase Auth UUID the token grants access to.
        name: Human-readable label for the token (e.g. "life-os").
        scopes: List of scope strings, e.g. ["nutrition:read"].

    Returns:
        The plaintext token string, shown only once.
    """
    plaintext = _TOKEN_PREFIX + secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(plaintext.encode("utf-8")).hexdigest()

    session_factory = get_session()
    async with session_factory() as session:
        await session.execute(
            sa_text(
                "INSERT INTO integration_token (user_id, token_hash, name, scopes) "
                "VALUES (:user_id, :token_hash, :name, :scopes)"
            ),
            {
                "user_id": user_id,
                "token_hash": token_hash,
                "name": name,
                "scopes": scopes,
            },
        )
        await session.commit()
    return plaintext


def main() -> None:
    parser = argparse.ArgumentParser(description="Mint a Mealsy integration token")
    parser.add_argument("--user-id", required=True, help="Supabase Auth user UUID")
    parser.add_argument("--name", required=True, help="Label for this token")
    parser.add_argument(
        "--scope",
        action="append",
        dest="scopes",
        default=None,
        help="Scope to grant (repeatable). Defaults to nutrition:read.",
    )
    args = parser.parse_args()
    scopes = args.scopes or ["nutrition:read"]

    async def _run() -> None:
        try:
            token = await _mint(args.user_id, args.name, scopes)
        finally:
            await dispose_engine()
        print("Token minted. Store it now — it will not be shown again:\n")
        print(token)

    asyncio.run(_run())


if __name__ == "__main__":
    main()
