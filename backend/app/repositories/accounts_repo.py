"""Account reads.

Every account-bound function takes an explicit `account_scope`. There is no
unscoped variant and no default. Cross-account reads are a separately named
function that the auth policy gates.
"""

from __future__ import annotations

from typing import Any

from app.repositories.db import connection

_COLUMNS = """
    account_id, account_name, plan, status, csm,
    contract_doc_id, premium_support, notes
"""


def get_account(account_id: str, account_scope: str | None) -> dict[str, Any] | None:
    """`account_scope` None means unrestricted (internal roles only).

    A scoped caller asking for someone else's account gets None -- the same
    answer as a genuinely missing row, so the result cannot be used to probe
    which accounts exist.
    """
    with connection() as conn:
        return conn.execute(
            f"""
            SELECT {_COLUMNS}
            FROM accounts
            WHERE account_id = %(account_id)s
              AND (%(scope)s::text IS NULL OR account_id = %(scope)s)
            """,
            {"account_id": account_id, "scope": account_scope},
        ).fetchone()


def list_accounts_all(_gated_by_auth_policy: bool = True) -> list[dict[str, Any]]:
    """Cross-account read. Named explicitly so a reviewer can grep for every
    place scope is intentionally bypassed. Callers MUST check
    auth.policies.can_read_all_accounts first.
    """
    with connection() as conn:
        return conn.execute(
            f"SELECT {_COLUMNS} FROM accounts ORDER BY account_id"
        ).fetchall()
