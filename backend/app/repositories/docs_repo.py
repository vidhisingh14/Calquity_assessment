"""Document and chunk reads: vector search, keyword search, metadata.

Scope filtering happens IN SQL, never as a post-filter in Python. The rule from
the build spec's section 8.2 is `WHERE account_scope IS NULL OR account_scope =
:scope`, and it is applied inside every query below. Retrieving everything and
filtering afterwards means the rows briefly existed in a variable the prompt
could reach; filtering in SQL means they never left the database.
"""

from __future__ import annotations

from typing import Any

from app.repositories.db import connection

_CHUNK_COLUMNS = """
    c.chunk_id, c.doc_id, c.chunk_index, c.page, c.section_path,
    c.content, c.authority_tier, c.account_scope,
    d.doc_type, d.version_label, d.is_current, d.file_name
"""


def vector_search(
    embedding: list[float],
    tiers: list[int],
    account_scope: str | None,
    k: int,
) -> list[dict[str, Any]]:
    with connection() as conn:
        return conn.execute(
            f"""
            SELECT {_CHUNK_COLUMNS},
                   1 - (c.embedding <=> %(embedding)s::vector) AS similarity
            FROM doc_chunks c
            JOIN documents d ON d.doc_id = c.doc_id
            WHERE c.authority_tier = ANY(%(tiers)s)
              AND (c.account_scope IS NULL OR c.account_scope = %(scope)s)
              AND c.embedding IS NOT NULL
            ORDER BY c.embedding <=> %(embedding)s::vector
            LIMIT %(k)s
            """,
            {"embedding": embedding, "tiers": tiers, "scope": account_scope, "k": k},
        ).fetchall()


def keyword_search(
    query: str,
    tiers: list[int],
    account_scope: str | None,
    k: int,
) -> list[dict[str, Any]]:
    with connection() as conn:
        return conn.execute(
            f"""
            SELECT {_CHUNK_COLUMNS},
                   ts_rank(c.content_tsv, websearch_to_tsquery('english', %(q)s)) AS rank
            FROM doc_chunks c
            JOIN documents d ON d.doc_id = c.doc_id
            WHERE c.authority_tier = ANY(%(tiers)s)
              AND (c.account_scope IS NULL OR c.account_scope = %(scope)s)
              AND c.content_tsv @@ websearch_to_tsquery('english', %(q)s)
            ORDER BY rank DESC
            LIMIT %(k)s
            """,
            {"q": query, "tiers": tiers, "scope": account_scope, "k": k},
        ).fetchall()


def search_scoped_tier1(
    embedding: list[float],
    account_scope: str | None,
    k: int,
) -> list[dict[str, Any]]:
    """Reserved-slot pass over the caller's own tier-1 contract.

    Bucket promotion during ranking is worthless if the contract chunk never
    reaches the candidate pool in the first place -- generic policy chunks can
    crowd it out on raw similarity. This pass guarantees it is present, and the
    ranker then decides whether it clears the relevance floor.
    """
    if account_scope is None:
        return []

    with connection() as conn:
        return conn.execute(
            f"""
            SELECT {_CHUNK_COLUMNS},
                   1 - (c.embedding <=> %(embedding)s::vector) AS similarity
            FROM doc_chunks c
            JOIN documents d ON d.doc_id = c.doc_id
            WHERE c.authority_tier = 1
              AND c.account_scope = %(scope)s
              AND c.embedding IS NOT NULL
            ORDER BY c.embedding <=> %(embedding)s::vector
            LIMIT %(k)s
            """,
            {"embedding": embedding, "scope": account_scope, "k": k},
        ).fetchall()


def get_chunk(chunk_id: int, account_scope: str | None) -> dict[str, Any] | None:
    """Backs the source drawer in the UI."""
    with connection() as conn:
        return conn.execute(
            f"""
            SELECT {_CHUNK_COLUMNS}
            FROM doc_chunks c
            JOIN documents d ON d.doc_id = c.doc_id
            WHERE c.chunk_id = %(chunk_id)s
              AND (c.account_scope IS NULL OR c.account_scope = %(scope)s)
            """,
            {"chunk_id": chunk_id, "scope": account_scope},
        ).fetchone()


def get_document(doc_id: str) -> dict[str, Any] | None:
    with connection() as conn:
        return conn.execute(
            """
            SELECT doc_id, file_name, doc_type, authority_tier, account_scope,
                   version_label, effective_from, superseded_by, is_current
            FROM documents WHERE doc_id = %s
            """,
            (doc_id,),
        ).fetchone()


def list_documents() -> list[dict[str, Any]]:
    with connection() as conn:
        return conn.execute(
            """
            SELECT doc_id, file_name, doc_type, authority_tier, account_scope,
                   version_label, is_current, superseded_by
            FROM documents ORDER BY authority_tier, doc_id
            """
        ).fetchall()
