"""Test fixtures.

Tests run against a REAL Postgres (a separate `parcelpilot_test` database in
the same container), because the things most worth testing here -- scope
filtering, the tier-5 exclusion, generated tsvector columns -- live in SQL. A
mocked repository would assert that the mock filters correctly, which proves
nothing about the query that actually runs in production.

Seed data is hand-written SQL rather than a full ingest: it is faster, and it
lets a test construct exactly the adversarial shape it needs (two accounts,
each with a contract the other must never see).
"""

from __future__ import annotations

import os
import pathlib

import psycopg
import pytest
from psycopg.rows import dict_row

BACKEND = pathlib.Path(__file__).resolve().parent.parent
MIGRATIONS = BACKEND / "migrations"

ADMIN_URL = os.environ.get(
    "TEST_ADMIN_DATABASE_URL",
    "postgresql://parcelpilot:parcelpilot@localhost:5432/postgres",
)
TEST_DB = os.environ.get("TEST_DB_NAME", "parcelpilot_test")
TEST_URL = os.environ.get(
    "TEST_DATABASE_URL",
    f"postgresql://parcelpilot:parcelpilot@localhost:5432/{TEST_DB}",
)


@pytest.fixture(scope="session", autouse=True)
def _configure_env():
    """Point the app's settings at the test database before anything imports it."""
    os.environ["DATABASE_URL"] = TEST_URL
    os.environ.setdefault("EMBED_DIM", "1536")
    from app.config import get_settings

    get_settings.cache_clear()
    yield
