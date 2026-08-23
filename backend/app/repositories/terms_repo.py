"""Policy term lookup.

THE TIER-5 EXCLUSION IS ENFORCED HERE, BY CONSTRUCTION.

`lookup_terms` hard-codes `authority_tier < 5 AND NOT deprecated` into its SQL
and exposes no parameter that can relax it. This is deliberate: a comment
saying "never select deprecated terms" is not a control, because the next
person to add a caller does not read it. A query that cannot express the unsafe
case is a control.

Deprecated terms are reachable only through `lookup_deprecated_terms_for_
comparison`, which exists for one purpose (an internal role explicitly
comparing policy versions) and is never called by the policy engine.
"""

from __future__ import annotations

from typing import Any

from app.repositories.db import connection

_COLUMNS = """
    t.term_id, t.doc_id, t.term_key, t.term_value, t.unit,
    t.source_chunk_id, t.authority_tier, t.account_scope,
    t.deprecated, t.enforceable, t.unverified
"""


def lookup_terms(
    term_keys: list[str],
    account_scope: str | None,
) -> list[dict[str, Any]]:
    """Terms usable for an actual verdict.

    Tier 5 and deprecated rows can never come back from this function.
    Ordered by authority tier ascending, so tier 1 (a contract) precedes
    tier 2 (current policy) precedes tier 3 (SOP) for the caller to resolve.
    """
    if not term_keys:
        return []

    with connection() as conn:
        return conn.execute(
            f"""
            SELECT {_COLUMNS}
            FROM doc_terms t
            WHERE t.term_key = ANY(%(keys)s)
              AND t.authority_tier < 5          -- structural: never deprecated
              AND t.deprecated IS FALSE         -- belt and braces
              AND (t.account_scope IS NULL OR t.account_scope = %(scope)s)
            ORDER BY t.authority_tier ASC, t.doc_id ASC
            """,
            {"keys": term_keys, "scope": account_scope},
        ).fetchall()


def lookup_terms_for_doc(
    doc_id: str,
    term_keys: list[str],
    account_scope: str | None,
) -> list[dict[str, Any]]:
    """Same guarantees as `lookup_terms`, narrowed to one document.

    Used by the term resolver when it already knows which contract governs.
    """
    if not term_keys:
        return []

    with connection() as conn:
        return conn.execute(
            f"""
            SELECT {_COLUMNS}
            FROM doc_terms t
            WHERE t.doc_id = %(doc_id)s
              AND t.term_key = ANY(%(keys)s)
              AND t.authority_tier < 5
              AND t.deprecated IS FALSE
              AND (t.account_scope IS NULL OR t.account_scope = %(scope)s)
            ORDER BY t.term_key
            """,
            {"doc_id": doc_id, "keys": term_keys, "scope": account_scope},
        ).fetchall()


def lookup_deprecated_terms_for_comparison(
    term_keys: list[str],
) -> list[dict[str, Any]]:
    """Deprecated (tier-5) terms, for the internal version-comparison case only.

    NEVER call this from the policy engine. It exists so an ops_lead asking
    "compare the v2 and v3 targets" can be answered, and for tests that assert
    those values never reach a customer answer.
    """
    if not term_keys:
        return []

    with connection() as conn:
        return conn.execute(
            f"""
            SELECT {_COLUMNS}
            FROM doc_terms t
            WHERE t.term_key = ANY(%(keys)s)
              AND (t.authority_tier = 5 OR t.deprecated IS TRUE)
            ORDER BY t.doc_id
            """,
            {"keys": term_keys},
        ).fetchall()


def count_unverified() -> dict[str, int]:
    """Backs the /healthz split so it is visible at a glance how much of the
    term set a human has actually signed off."""
    with connection() as conn:
        row = conn.execute(
            """
            SELECT
              COUNT(*) FILTER (WHERE unverified)     AS unverified,
              COUNT(*) FILTER (WHERE NOT unverified) AS verified
            FROM doc_terms
            """
        ).fetchone()
    return {"verified": int(row["verified"]), "unverified": int(row["unverified"])}
