"""Step 8: post-ingest assertions and a summary table.

This step is the difference between debugging for ten minutes and debugging for
three hours. Every check here corresponds to a failure that is otherwise
invisible until it produces a confident wrong answer.
"""

from __future__ import annotations

from app.errors import IngestionError
from app.repositories.db import connection


def _scalar(conn, sql: str, params: tuple = ()) -> int:
    return int(conn.execute(sql, params).fetchone()["n"])


def run_assertions() -> dict[str, int]:
    problems: list[str] = []
    summary: dict[str, int] = {}

    with connection() as conn:
        for table in ("accounts", "orders", "tickets", "documents",
                      "doc_chunks", "doc_terms"):
            summary[table] = _scalar(conn, f"SELECT COUNT(*) AS n FROM {table}")
            if summary[table] == 0:
                problems.append(f"{table} is empty")

        missing_embeddings = _scalar(
            conn, "SELECT COUNT(*) AS n FROM doc_chunks WHERE embedding IS NULL"
        )
        summary["chunks_missing_embedding"] = missing_embeddings
        if missing_embeddings:
            problems.append(f"{missing_embeddings} chunk(s) have no embedding")

        missing_tier = _scalar(
            conn, "SELECT COUNT(*) AS n FROM doc_chunks WHERE authority_tier IS NULL"
        )
        if missing_tier:
            problems.append(
                f"{missing_tier} chunk(s) lost authority_tier -- authority "
                f"filtering is silently disabled for those chunks"
            )

        # A tier-1 chunk with no scope would override general policy for EVERY
        # customer, which is a cross-account leak wearing a different hat.
        unscoped_tier1 = _scalar(
            conn,
            "SELECT COUNT(*) AS n FROM doc_chunks "
            "WHERE authority_tier = 1 AND account_scope IS NULL",
        )
        if unscoped_tier1:
            problems.append(f"{unscoped_tier1} tier-1 chunk(s) have no account_scope")

        orphan_orders = _scalar(
            conn,
            "SELECT COUNT(*) AS n FROM orders o "
            "LEFT JOIN accounts a ON a.account_id = o.account_id "
            "WHERE a.account_id IS NULL",
        )
        orphan_tickets = _scalar(
            conn,
            "SELECT COUNT(*) AS n FROM tickets t "
            "LEFT JOIN accounts a ON a.account_id = t.account_id "
            "WHERE a.account_id IS NULL",
        )
        if orphan_orders or orphan_tickets:
            problems.append(
                f"orphan foreign keys: {orphan_orders} order(s), {orphan_tickets} ticket(s)"
            )

        # Every account claiming a contract must have the document row to match.
        unmatched = conn.execute(
            """
            SELECT a.account_id FROM accounts a
            WHERE a.contract_doc_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM documents d WHERE d.doc_id = a.contract_doc_id)
            """
        ).fetchall()
        if unmatched:
            problems.append(
                f"accounts reference missing contract documents: "
                f"{[r['account_id'] for r in unmatched]}"
            )

        # Contracts must be scoped to an account that actually exists.
        bad_scope = conn.execute(
            """
            SELECT d.doc_id FROM documents d
            WHERE d.account_scope IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM accounts a WHERE a.account_id = d.account_scope)
            """
        ).fetchall()
        if bad_scope:
            problems.append(
                f"documents scoped to non-existent accounts: "
                f"{[r['doc_id'] for r in bad_scope]}"
            )

        snapshot = conn.execute(
            "SELECT value FROM system_meta WHERE key = 'snapshot_time'"
        ).fetchone()
        if snapshot is None:
            problems.append("snapshot_time missing from system_meta")

        terms_split = conn.execute(
            """
            SELECT COUNT(*) FILTER (WHERE unverified)     AS unverified,
                   COUNT(*) FILTER (WHERE NOT unverified) AS verified
            FROM doc_terms
            """
        ).fetchone()
        summary["terms_verified"] = int(terms_split["verified"])
        summary["terms_unverified"] = int(terms_split["unverified"])

        # Deprecated documents must be tier 5, and only tier 5.
        mislabelled = _scalar(
            conn,
            "SELECT COUNT(*) AS n FROM documents "
            "WHERE (is_current = FALSE AND authority_tier <> 5) "
            "   OR (is_current = TRUE  AND authority_tier = 5)",
        )
        if mislabelled:
            problems.append(
                f"{mislabelled} document(s) disagree between is_current and tier 5"
            )

    if problems:
        raise IngestionError(
            "Ingestion assertions failed:\n  - " + "\n  - ".join(problems)
        )

    return summary


def print_summary(summary: dict[str, int]) -> None:
    width = max(len(k) for k in summary)
    print("\n  ingestion summary")
    print("  " + "-" * (width + 10))
    for key, value in summary.items():
        print(f"  {key:<{width}}  {value:>6}")
    print("  " + "-" * (width + 10))
