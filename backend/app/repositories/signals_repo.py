"""Signal persistence. Deterministic signal_id means re-runs upsert."""

from __future__ import annotations

import json
from typing import Any

from app.repositories.db import connection


def upsert(signal: dict[str, Any]) -> None:
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO signals (signal_id, signal_type, severity, title, detail,
                affected_accounts, first_seen_at, last_seen_at, status)
            VALUES (%(signal_id)s, %(signal_type)s, %(severity)s, %(title)s,
                %(detail)s, %(affected_accounts)s, now(), now(), 'open')
            ON CONFLICT (signal_id) DO UPDATE SET
                severity = EXCLUDED.severity,
                title = EXCLUDED.title,
                detail = EXCLUDED.detail,
                affected_accounts = EXCLUDED.affected_accounts,
                last_seen_at = now()
            """,
            {**signal,
             "detail": json.dumps(signal["detail"]),
             "affected_accounts": json.dumps(signal.get("affected_accounts") or [])},
        )
        conn.commit()


def list_signals(severity: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
    clauses = ["1=1"]
    params: dict[str, Any] = {}
    if severity:
        clauses.append("severity = %(severity)s")
        params["severity"] = severity
    if status:
        clauses.append("status = %(status)s")
        params["status"] = status
    with connection() as conn:
        return conn.execute(
            f"""
            SELECT signal_id, signal_type, severity, title, detail,
                   affected_accounts, first_seen_at, last_seen_at, status
            FROM signals WHERE {' AND '.join(clauses)}
            ORDER BY
              CASE severity WHEN 'urgent' THEN 0 WHEN 'high' THEN 1
                            WHEN 'medium' THEN 2 ELSE 3 END,
              last_seen_at DESC
            """,
            params,
        ).fetchall()


def snapshot_open_tickets() -> list[dict[str, Any]]:
    """Everything services/detection.py's rules need, fetched once."""
    with connection() as conn:
        return conn.execute(
            """
            SELECT ticket_id, account_id, created_at, status,
                   derived_severity, derived_issue_type, subject, description
            FROM tickets
            """
        ).fetchall()


def snapshot_orders() -> list[dict[str, Any]]:
    with connection() as conn:
        return conn.execute(
            """
            SELECT order_id, account_id, carrier, status, booked_at,
                   pickup_window_start, pickup_window_end, pickup_actual_at,
                   carrier_fault, customer_fault
            FROM orders
            """
        ).fetchall()
