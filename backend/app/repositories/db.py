"""Connection pool and the startup schema assertion.

This is the only module that knows how to open a database connection.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import get_settings
from app.errors import IngestionError

log = logging.getLogger(__name__)

_pool: ConnectionPool | None = None


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = ConnectionPool(
            settings.database_url,
            min_size=1,
            max_size=10,
            kwargs={"row_factory": dict_row},
            open=True,
        )
    return _pool


@contextmanager
def connection() -> Iterator[Connection]:
    with get_pool().connection() as conn:
        yield conn


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def assert_embedding_dim_matches_config() -> int:
    """Fail loudly at startup if EMBED_DIM disagrees with the actual column.

    A mismatch here is silent and catastrophic: inserts fail late, or worse,
    a re-ingest against a differently-sized column leaves the table half
    populated. pgvector stores the declared dimension in atttypmod, so we can
    read the truth from the database rather than trusting the migration to
    have matched the setting.
    """
    settings = get_settings()
    with connection() as conn:
        row = conn.execute(
            """
            SELECT atttypmod AS dim
            FROM pg_attribute
            WHERE attrelid = 'doc_chunks'::regclass
              AND attname = 'embedding'
              AND NOT attisdropped
            """
        ).fetchone()

    if row is None:
        raise IngestionError(
            "doc_chunks.embedding column not found. Run migrations first."
        )

    actual = int(row["dim"])
    if actual != settings.embed_dim:
        raise IngestionError(
            f"Embedding dimension mismatch: EMBED_DIM={settings.embed_dim} but "
            f"doc_chunks.embedding is VECTOR({actual}). "
            f"Change EMBED_DIM to {actual}, or migrate the column, then re-ingest. "
            f"Embeddings written under one dimension are not comparable with "
            f"embeddings written under another."
        )
    log.info("embedding dimension ok: %d", actual)
    return actual
