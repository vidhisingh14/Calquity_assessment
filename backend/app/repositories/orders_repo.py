"""Order reads. Scope is a required parameter on every account-bound query."""

from __future__ import annotations

from typing import Any

from app.repositories.db import connection

_COLUMNS = """
    order_id, account_id, carrier, status, booked_at,
    pickup_window_start, pickup_window_end, pickup_actual_at,
    shipment_fee_inr, carrier_fault, customer_fault,
    cancellation_requested_at, notes
"""

# Only these keys may be filtered on. An unknown key is rejected by the tool
# layer with the valid list, which the model can then correct.
ALLOWED_FILTERS = frozenset({"status", "carrier", "account_id"})


def get_order(order_id: str, account_scope: str | None) -> dict[str, Any] | None:
    """A scoped caller asking for another account's order gets None.

    Not a permission error -- an empty result. A 403 here would confirm the
    order exists, which is itself a leak.
    """
    with connection() as conn:
        return conn.execute(
            f"""
            SELECT {_COLUMNS}
            FROM orders
            WHERE order_id = %(order_id)s
              AND (%(scope)s::text IS NULL OR account_id = %(scope)s)
            """,
            {"order_id": order_id, "scope": account_scope},
        ).fetchone()


def list_orders(
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
            FROM orders
            WHERE {' AND '.join(clauses)}
            ORDER BY booked_at DESC NULLS LAST
            LIMIT %(limit)s
            """,
            params,
        ).fetchall()
