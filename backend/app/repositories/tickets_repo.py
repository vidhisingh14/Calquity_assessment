"""Ticket reads.

`historical_resolution` is tier 4. It is returned, because it is genuinely
useful for investigation, but every caller must mark it context-only. The
repository does not format anything -- it just never pretends the column is
authoritative.
"""

from __future__ import annotations

from typing import Any

from app.repositories.db import connection

_COLUMNS = """
    ticket_id, account_id, created_at, status, subject, description,
    channel, assigned_to, last_customer_message_at, historical_resolution,
    derived_severity, severity_rationale, derived_issue_type
"""

ALLOWED_FILTERS = frozenset(
    {"status", "derived_severity", "derived_issue_type", "account_id"}
)


def get_ticket(ticket_id: str, account_scope: str | None) -> dict[str, Any] | None:
    with connection() as conn:
        return conn.execute(
            f"""
            SELECT {_COLUMNS}
            FROM tickets
            WHERE ticket_id = %(ticket_id)s
              AND (%(scope)s::text IS NULL OR account_id = %(scope)s)
            """,
            {"ticket_id": ticket_id, "scope": account_scope},
        ).fetchone()


def list_tickets(
    account_scope: str | None,
    filters: dict[str, Any] | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    filters = filters or {}
    unknown = set(filters) - ALLOWED_FILTERS
    if unknown:
        raise ValueError(
            f"Unknown filter keys {sorted(unknown)}; allowed: {sorted(ALLOWED_FILTERS)}"
        )

    clauses = ["(%(scope)s::text IS NULL OR account_id = %(scope)s)"]
    params: dict[str, Any] = {"scope": account_scope, "limit": limit}
    for key, value in filters.items():
        clauses.append(f"{key} = %({key})s")
        params[key] = value

    with connection() as conn:
        return conn.execute(
            f"""
            SELECT {_COLUMNS}
            FROM tickets
            WHERE {' AND '.join(clauses)}
            ORDER BY created_at DESC NULLS LAST
            LIMIT %(limit)s
            """,
            params,
        ).fetchall()


def list_tickets_all_accounts(limit: int = 100) -> list[dict[str, Any]]:
    """Cross-account read for internal roles and the detection job.

    Named explicitly, per the build spec's section 4.1, so every deliberate
    scope bypass is greppable. Callers MUST check
    auth.policies.can_read_all_accounts first.
    """
    with connection() as conn:
        return conn.execute(
            f"""
            SELECT {_COLUMNS}
            FROM tickets
            ORDER BY created_at DESC NULLS LAST
            LIMIT %s
            """,
            (limit,),
        ).fetchall()
