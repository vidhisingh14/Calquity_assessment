"""Writes used only by the ingestion pipeline.

Kept separate from the read repositories so that a grep for "who writes to
doc_chunks" has exactly one answer. Ingestion is idempotent: it truncates and
reloads rather than trying to reconcile.
"""

from __future__ import annotations

import json
from typing import Any

from app.repositories.db import connection


def truncate_all() -> None:
    """Ordered so foreign keys never block the reload."""
    with connection() as conn:
        conn.execute(
            """
            TRUNCATE doc_terms, doc_chunks, tickets, orders RESTART IDENTITY CASCADE;
            """
        )
        # accounts.contract_doc_id references documents, so detach before clearing.
        conn.execute("UPDATE accounts SET contract_doc_id = NULL")
        conn.execute("TRUNCATE documents RESTART IDENTITY CASCADE")
        conn.execute("TRUNCATE accounts RESTART IDENTITY CASCADE")
        conn.commit()


def insert_accounts(rows: list[dict[str, Any]]) -> int:
    with connection() as conn:
        for r in rows:
            conn.execute(
                """
                INSERT INTO accounts (account_id, account_name, plan, status, csm,
                                      premium_support, notes)
                VALUES (%(account_id)s, %(account_name)s, %(plan)s, %(status)s,
                        %(csm)s, %(premium_support)s, %(notes)s)
                ON CONFLICT (account_id) DO UPDATE SET
                    account_name = EXCLUDED.account_name,
                    plan = EXCLUDED.plan,
                    status = EXCLUDED.status,
                    csm = EXCLUDED.csm,
                    premium_support = EXCLUDED.premium_support,
                    notes = EXCLUDED.notes
                """,
                r,
            )
        conn.commit()
    return len(rows)


def link_account_contract(account_id: str, doc_id: str) -> None:
    with connection() as conn:
        conn.execute(
            "UPDATE accounts SET contract_doc_id = %s WHERE account_id = %s",
            (doc_id, account_id),
        )
        conn.commit()


def insert_orders(rows: list[dict[str, Any]]) -> int:
    with connection() as conn:
        for r in rows:
            conn.execute(
                """
                INSERT INTO orders (order_id, account_id, carrier, status, booked_at,
                    pickup_window_start, pickup_window_end, pickup_actual_at,
                    shipment_fee_inr, carrier_fault, customer_fault,
                    cancellation_requested_at, notes)
                VALUES (%(order_id)s, %(account_id)s, %(carrier)s, %(status)s,
                    %(booked_at)s, %(pickup_window_start)s, %(pickup_window_end)s,
                    %(pickup_actual_at)s, %(shipment_fee_inr)s, %(carrier_fault)s,
                    %(customer_fault)s, %(cancellation_requested_at)s, %(notes)s)
                ON CONFLICT (order_id) DO NOTHING
                """,
                r,
            )
        conn.commit()
    return len(rows)


def insert_tickets(rows: list[dict[str, Any]]) -> int:
    with connection() as conn:
        for r in rows:
            conn.execute(
                """
                INSERT INTO tickets (ticket_id, account_id, created_at, status,
                    subject, description, channel, assigned_to,
                    last_customer_message_at, historical_resolution,
                    derived_severity, severity_rationale, derived_issue_type)
                VALUES (%(ticket_id)s, %(account_id)s, %(created_at)s, %(status)s,
                    %(subject)s, %(description)s, %(channel)s, %(assigned_to)s,
                    %(last_customer_message_at)s, %(historical_resolution)s,
                    %(derived_severity)s, %(severity_rationale)s, %(derived_issue_type)s)
                ON CONFLICT (ticket_id) DO NOTHING
                """,
                r,
            )
        conn.commit()
    return len(rows)


def insert_document(meta: dict[str, Any]) -> None:
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO documents (doc_id, file_name, doc_type, authority_tier,
                account_scope, version_label, effective_from, superseded_by, is_current)
            VALUES (%(doc_id)s, %(file_name)s, %(doc_type)s, %(authority_tier)s,
                %(account_scope)s, %(version_label)s, %(effective_from)s,
                %(superseded_by)s, %(is_current)s)
            ON CONFLICT (doc_id) DO UPDATE SET
                authority_tier = EXCLUDED.authority_tier,
                account_scope = EXCLUDED.account_scope,
                is_current = EXCLUDED.is_current
            """,
            meta,
        )
        conn.commit()


def set_superseded_by(doc_id: str, superseded_by: str) -> None:
    with connection() as conn:
        conn.execute(
            "UPDATE documents SET superseded_by = %s WHERE doc_id = %s",
            (superseded_by, doc_id),
        )
        conn.commit()


def insert_chunks(rows: list[dict[str, Any]], embeddings: list[list[float]]) -> list[int]:
    """Returns the assigned chunk_ids, in input order, so terms can bind to them."""
    ids: list[int] = []
    with connection() as conn:
        for row, vector in zip(rows, embeddings):
            result = conn.execute(
                """
                INSERT INTO doc_chunks (doc_id, chunk_index, page, section_path,
                    content, embedding, authority_tier, account_scope)
                VALUES (%(doc_id)s, %(chunk_index)s, %(page)s, %(section_path)s,
                    %(content)s, %(embedding)s, %(authority_tier)s, %(account_scope)s)
                RETURNING chunk_id
                """,
                {**row, "embedding": vector},
            ).fetchone()
            ids.append(int(result["chunk_id"]))
        conn.commit()
    return ids


def insert_term(row: dict[str, Any]) -> None:
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO doc_terms (doc_id, term_key, term_value, unit,
                source_chunk_id, authority_tier, account_scope, deprecated,
                enforceable, unverified)
            VALUES (%(doc_id)s, %(term_key)s, %(term_value)s, %(unit)s,
                %(source_chunk_id)s, %(authority_tier)s, %(account_scope)s,
                %(deprecated)s, %(enforceable)s, %(unverified)s)
            ON CONFLICT (doc_id, term_key) DO UPDATE SET
                term_value = EXCLUDED.term_value,
                source_chunk_id = EXCLUDED.source_chunk_id,
                unverified = EXCLUDED.unverified
            """,
            {**row, "term_value": json.dumps(row["term_value"])},
        )
        conn.commit()
