"""Database-backed fixtures.

These live under integration/ rather than in the root conftest so that unit
tests -- layer checks, the client guard, pure services -- run with no database
at all. A unit suite that needs Postgres to start is a unit suite people stop
running.
"""

from __future__ import annotations

import os
import pathlib

import psycopg
import pytest
from psycopg.rows import dict_row

from tests.conftest import ADMIN_URL, MIGRATIONS, TEST_DB, TEST_URL


@pytest.fixture(scope="session")
def _database(_configure_env):
    with psycopg.connect(ADMIN_URL, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{TEST_DB}"')

    with psycopg.connect(TEST_URL, autocommit=True, row_factory=dict_row) as conn:
        for path in sorted(MIGRATIONS.glob("*.sql")):
            conn.execute(path.read_text(encoding="utf-8"))

    yield TEST_URL

    from app.repositories.db import close_pool

    close_pool()


@pytest.fixture(autouse=True)
def seeded(_database):
    """Reset and re-seed before every test, so order never matters."""
    from app.repositories.db import connection

    with connection() as conn:
        conn.execute(
            "TRUNCATE doc_terms, doc_chunks, tickets, orders RESTART IDENTITY CASCADE"
        )
        conn.execute("UPDATE accounts SET contract_doc_id = NULL")
        conn.execute("TRUNCATE documents RESTART IDENTITY CASCADE")
        conn.execute("TRUNCATE accounts RESTART IDENTITY CASCADE")
        conn.execute("DELETE FROM system_meta")
        _seed(conn)
        conn.commit()
    yield


def _seed(conn) -> None:
    conn.execute(
        """
        INSERT INTO system_meta (key, value)
        VALUES ('snapshot_time', '2026-08-16T11:00:00+05:30')
        """
    )

    conn.execute(
        """
        INSERT INTO accounts (account_id, account_name, plan, status, premium_support)
        VALUES
          ('ACCT-001', 'Northstar Logistics', 'Enterprise', 'active', TRUE),
          ('ACCT-002', 'LumenWorks',          'Growth',     'active', FALSE),
          ('ACCT-003', 'Beacon Retail',       'Standard',   'active', FALSE)
        """
    )

    conn.execute(
        """
        INSERT INTO documents (doc_id, file_name, doc_type, authority_tier,
                               account_scope, version_label, is_current)
        VALUES
          ('policy_v3',           'p3.pdf',  'policy',   2, NULL,       'v3', TRUE),
          ('policy_v2',           'p2.pdf',  'policy',   5, NULL,       'v2', FALSE),
          ('sop_v4',              'sop.pdf', 'sop',      3, NULL,       'v4', TRUE),
          ('contract_northstar',  'ns.pdf',  'contract', 1, 'ACCT-001', NULL, TRUE),
          ('contract_lumenworks', 'lw.pdf',  'contract', 1, 'ACCT-002', NULL, TRUE)
        """
    )
    conn.execute(
        "UPDATE accounts SET contract_doc_id = 'contract_northstar' WHERE account_id = 'ACCT-001'"
    )
    conn.execute(
        "UPDATE accounts SET contract_doc_id = 'contract_lumenworks' WHERE account_id = 'ACCT-002'"
    )

    # Chunks carry a denormalised tier and scope, exactly as ingestion writes them.
    conn.execute(
        """
        INSERT INTO doc_chunks (doc_id, chunk_index, page, section_path, content,
                                authority_tier, account_scope)
        VALUES
          ('policy_v3', 0, 1, '3. Targets',
           'Enterprise 30 minutes 24x7 for P1 first response.', 2, NULL),
          ('policy_v2', 0, 1, 'Targets',
           'Enterprise 1 hour for P1 first response. DEPRECATED.', 5, NULL),
          ('sop_v4', 0, 1, '1. Cancellation',
           'No fee within 30 minutes of booking. After 30 minutes, charge INR 250.',
           3, NULL),
          ('contract_northstar', 0, 1, '2. Cancellation',
           'Northstar may cancel any BOOKED shipment before pickup with no '
           'cancellation fee, regardless of how long ago the shipment was booked.',
           1, 'ACCT-001'),
          ('contract_lumenworks', 0, 1, '3. Credits',
           'If a pickup is more than 4 hours past the end of the scheduled pickup '
           'window, LumenWorks receives a fixed INR 300 service credit.',
           1, 'ACCT-002')
        """
    )

    conn.execute(
        """
        INSERT INTO orders (order_id, account_id, carrier, status, booked_at,
                            pickup_window_start, pickup_window_end,
                            shipment_fee_inr, carrier_fault, customer_fault,
                            cancellation_requested_at)
        VALUES
          ('ORD-1001', 'ACCT-001', 'SwiftShip', 'BOOKED',
           '2026-08-16T09:00:00+05:30', '2026-08-16T10:30:00+05:30',
           '2026-08-16T11:30:00+05:30', 4200, FALSE, FALSE,
           '2026-08-16T11:00:00+05:30'),
          ('ORD-2002', 'ACCT-002', 'RoadRunner', 'BOOKED',
           '2026-08-16T04:30:00+05:30', '2026-08-16T05:30:00+05:30',
           '2026-08-16T06:30:00+05:30', 2400, TRUE, FALSE, NULL)
        """
    )

    conn.execute(
        """
        INSERT INTO tickets (ticket_id, account_id, created_at, status, subject,
                             description, derived_severity, derived_issue_type,
                             historical_resolution)
        VALUES
          ('TKT-501', 'ACCT-001', '2026-08-16T10:30:00+05:30', 'open',
           'All shipment creation is failing',
           'Every user gets HTTP 500 when creating any shipment.', 'P1', 'outage', NULL),
          ('TKT-502', 'ACCT-002', '2026-08-16T09:45:00+05:30', 'open',
           'Bulk upload fails for 4,200-row CSV',
           'Creating shipments one-by-one still works.', 'P2', 'bulk_upload', NULL),
          ('TKT-450', 'ACCT-001', '2026-07-12T14:10:00+05:30', 'closed',
           'Cancellation fee after 30 minutes', 'Asked about cancelling late.',
           'P3', 'pickup_status',
           'Agent told customer a INR 250 cancellation fee applied after 30 minutes.')
        """
    )

    # A tier-5 term that WOULD satisfy a lookup, so the exclusion test has
    # something real to fail against rather than asserting on an empty table.
    conn.execute(
        """
        INSERT INTO doc_terms (doc_id, term_key, term_value, unit, source_chunk_id,
                               authority_tier, account_scope, deprecated, unverified)
        SELECT 'policy_v2', 'sla.first_response.Enterprise.P1', '1'::jsonb, 'hours',
               c.chunk_id, 5, NULL, TRUE, TRUE
        FROM doc_chunks c WHERE c.doc_id = 'policy_v2' LIMIT 1
        """
    )
    conn.execute(
        """
        INSERT INTO doc_terms (doc_id, term_key, term_value, unit, source_chunk_id,
                               authority_tier, account_scope, deprecated, unverified)
        SELECT 'policy_v3', 'sla.first_response.Enterprise.P1', '30'::jsonb, 'minutes',
               c.chunk_id, 2, NULL, FALSE, TRUE
        FROM doc_chunks c WHERE c.doc_id = 'policy_v3' LIMIT 1
        """
    )


@pytest.fixture
def customer_lumen():
    from app.auth.context import AuthContext

    return AuthContext(user_id="u_lumen", role="customer", account_id="ACCT-002")


@pytest.fixture
def customer_northstar():
    from app.auth.context import AuthContext

    return AuthContext(user_id="u_northstar", role="customer", account_id="ACCT-001")


@pytest.fixture
def ops_lead():
    from app.auth.context import AuthContext

    return AuthContext(user_id="u_ops", role="ops_lead", account_id=None)
