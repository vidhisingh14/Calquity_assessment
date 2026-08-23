"""system_meta reads/writes and the row counts /healthz reports."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.errors import IngestionError
from app.repositories.db import connection

SNAPSHOT_KEY = "snapshot_time"
SKIPPED_PAGES_KEY = "ingest_skipped_empty_pages"


def set_meta(key: str, value: str) -> None:
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO system_meta (key, value, updated_at)
            VALUES (%s, %s, now())
            ON CONFLICT (key) DO UPDATE
              SET value = EXCLUDED.value, updated_at = now()
            """,
            (key, value),
        )


def get_meta(key: str) -> str | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT value FROM system_meta WHERE key = %s", (key,)
        ).fetchone()
    return row["value"] if row else None


def get_snapshot_time() -> datetime:
    """The reference time for EVERY time-based calculation.

    Read from the workbook README, never `datetime.now()`. A wrong clock here
    makes every cancellation and SLA answer wrong while sounding perfectly
    confident, which is why this raises rather than falling back.
    """
    raw = get_meta(SNAPSHOT_KEY)
    if raw is None:
        raise IngestionError(
            "snapshot_time missing from system_meta. Run ingestion before "
            "serving requests -- time-based answers are meaningless without it."
        )
    return datetime.fromisoformat(raw)


def row_counts() -> dict[str, int]:
    tables = [
        "accounts", "orders", "tickets", "documents",
        "doc_chunks", "doc_terms", "escalations", "signals", "users",
    ]
    counts: dict[str, int] = {}
    with connection() as conn:
        for table in tables:
            row = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
            counts[table] = int(row["n"])
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM doc_chunks WHERE embedding IS NULL"
        ).fetchone()
        counts["doc_chunks_missing_embedding"] = int(row["n"])
    return counts


def health_extras() -> dict[str, Any]:
    """Ingestion facts a reviewer needs to see on a deployed instance.

    `skipped_empty_pages` is surfaced deliberately: the escape hatch that lets
    ingestion continue past a blank page must be VISIBLE, or a silently
    half-ingested document looks identical to a healthy one.
    """
    return {
        "snapshot_time": get_meta(SNAPSHOT_KEY),
        "skipped_empty_pages": get_meta(SKIPPED_PAGES_KEY),
    }
