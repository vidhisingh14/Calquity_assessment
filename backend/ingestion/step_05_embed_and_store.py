"""Step 5: batch embed chunks and store them.

Chunks are embedded with task_type=RETRIEVAL_DOCUMENT. Queries at search time
use RETRIEVAL_QUERY. Mixing the two costs recall silently.
"""

from __future__ import annotations

from app.llm.embeddings import Embedder
from app.repositories import ingest_repo
from ingestion.step_04_chunk import Chunk


def embed_and_store(chunks: list[Chunk], embedder: Embedder) -> list[int]:
    rows = [
        {
            "doc_id": c.doc_id,
            "chunk_index": c.chunk_index,
            "page": c.page,
            "section_path": c.section_path,
            "content": c.content,
            "authority_tier": c.authority_tier,
            "account_scope": c.account_scope,
        }
        for c in chunks
    ]
    vectors = embedder.embed([c.content for c in chunks], task_type="RETRIEVAL_DOCUMENT")
    return ingest_repo.insert_chunks(rows, vectors)
