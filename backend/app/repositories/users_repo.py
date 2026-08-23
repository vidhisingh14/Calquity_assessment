"""SQL only. Returns rows; decides nothing."""

from __future__ import annotations

from typing import Any

from app.repositories.db import connection


def get_user(user_id: str) -> dict[str, Any] | None:
    with connection() as conn:
        return conn.execute(
            """
            SELECT user_id, display_name, role, account_id
            FROM users
            WHERE user_id = %s
            """,
            (user_id,),
        ).fetchone()


def list_users() -> list[dict[str, Any]]:
    """Backs the UI role switcher."""
    with connection() as conn:
        return conn.execute(
            """
            SELECT user_id, display_name, role, account_id
            FROM users
            ORDER BY role, user_id
            """
        ).fetchall()
