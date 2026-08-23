"""Pending actions and escalations.

The idempotency key on `escalations` is a UNIQUE constraint, not application
logic, so a double confirm cannot create a second row even under a race.
"""

from __future__ import annotations

import json
from typing import Any

from app.repositories.db import connection


def create_pending(
    token: str,
    session_id: str,
    user_id: str,
    action_type: str,
    payload: dict[str, Any],
    ttl_minutes: int,
) -> dict[str, Any]:
    with connection() as conn:
        row = conn.execute(
            """
            INSERT INTO pending_actions
                (token, session_id, user_id, action_type, payload, expires_at)
            VALUES (%s, %s, %s, %s, %s, now() + make_interval(mins => %s))
            RETURNING token, session_id, user_id, action_type, payload, status,
                      created_at, expires_at
            """,
            (token, session_id, user_id, action_type, json.dumps(payload), ttl_minutes),
        ).fetchone()
        conn.commit()
    return row


def get_pending(token: str) -> dict[str, Any] | None:
    with connection() as conn:
        return conn.execute(
            """
            SELECT token, session_id, user_id, action_type, payload, status,
                   created_at, expires_at, (expires_at < now()) AS is_expired
            FROM pending_actions WHERE token = %s
            """,
            (token,),
        ).fetchone()


def mark_pending(token: str, status: str) -> None:
    with connection() as conn:
        conn.execute(
            "UPDATE pending_actions SET status = %s WHERE token = %s",
            (status, token),
        )
        conn.commit()


def expire_token_for_test(token: str) -> None:
    """Age one token so the expiry path can be exercised deterministically.

    Chosen over a TTL settings override because it touches only the token under
    test: no clock manipulation, and no mutated setting that could leak into
    the confirm-immediately assertions in the same test.
    """
    with connection() as conn:
        conn.execute(
            "UPDATE pending_actions SET expires_at = now() - interval '1 minute' "
            "WHERE token = %s",
            (token,),
        )
        conn.commit()


def create_escalation(
    escalation_id: str,
    account_id: str,
    created_by: str,
    severity: str,
    summary: str,
    reason: str,
    idempotency_key: str,
    order_id: str | None = None,
    ticket_id: str | None = None,
    linked_sources: list[str] | None = None,
) -> dict[str, Any]:
    """Insert, or return the existing row if this key was already used.

    ON CONFLICT DO NOTHING plus a follow-up SELECT means a duplicate confirm is
    a no-op that still reports the original escalation id.
    """
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO escalations
                (escalation_id, account_id, created_by, ticket_id, order_id,
                 severity, summary, reason, linked_sources, idempotency_key)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (idempotency_key) DO NOTHING
            """,
            (escalation_id, account_id, created_by, ticket_id, order_id,
             severity, summary, reason, json.dumps(linked_sources or []),
             idempotency_key),
        )
        conn.commit()
        return conn.execute(
            """
            SELECT escalation_id, account_id, severity, summary, reason, status,
                   created_at
            FROM escalations WHERE idempotency_key = %s
            """,
            (idempotency_key,),
        ).fetchone()


def count_escalations() -> int:
    with connection() as conn:
        return int(conn.execute(
            "SELECT COUNT(*) AS n FROM escalations"
        ).fetchone()["n"])
