"""Step 4: split into chunks that inherit their parent's metadata.

THE BUG THIS STEP EXISTS TO PREVENT is metadata loss on split. A chunk that
loses its authority_tier does not error -- it just quietly stops being
filterable, which disables the entire authority model for that document. So
every produced chunk is asserted to carry doc_id, authority_tier and page.

Chunk size is measured with tiktoken purely as a DETERMINISTIC RULER. It is not
the tokenizer of the serving model (Cerebras Llama and Gemini both tokenize
differently), so chunk sizes are approximate BY DESIGN. What matters is that
the same input always produces the same chunks, not that 800 means 800 to the
model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.errors import IngestionError

TARGET_TOKENS = 800
OVERLAP_TOKENS = 120

# Numbered section headings, e.g. "1. Scope and source precedence"
_HEADING = re.compile(r"^\s*(\d+(?:\.\d+)*)\.\s+(.{3,80})$")


@dataclass
class Chunk:
    doc_id: str
    chunk_index: int
    page: int
    section_path: str | None
    content: str
    authority_tier: int
    account_scope: str | None


def _encoder():
    import tiktoken

    return tiktoken.get_encoding("cl100k_base")


def _token_len(text: str, enc) -> int:
    return len(enc.encode(text))


def _split_page(text: str, enc) -> list[tuple[str | None, str]]:
    """Split one page into (section_path, body) blocks on numbered headings."""
    blocks: list[tuple[str | None, str]] = []
    current_heading: str | None = None
    buffer: list[str] = []

    for line in text.splitlines():
        match = _HEADING.match(line)
        if match:
            if buffer:
                blocks.append((current_heading, "\n".join(buffer).strip()))
                buffer = []
            current_heading = f"{match.group(1)} {match.group(2).strip()}"
            buffer.append(line)
        else:
            buffer.append(line)

    if buffer:
        blocks.append((current_heading, "\n".join(buffer).strip()))

    return [(h, b) for h, b in blocks if b]


def _pack(blocks: list[tuple[str | None, str]], enc) -> list[tuple[str | None, str]]:
    """Greedily combine blocks up to TARGET_TOKENS, with overlap between chunks."""
    packed: list[tuple[str | None, str]] = []
    current: list[str] = []
    current_heading: str | None = None

    for heading, body in blocks:
        candidate = "\n\n".join(current + [body]) if current else body
        if current and _token_len(candidate, enc) > TARGET_TOKENS:
            packed.append((current_heading, "\n\n".join(current)))
            tail = current[-1]
            overlap = tail if _token_len(tail, enc) <= OVERLAP_TOKENS else ""
            current = [overlap, body] if overlap else [body]
            current_heading = heading
        else:
            if not current:
                current_heading = heading
            current.append(body)

    if current:
        packed.append((current_heading, "\n\n".join(current)))
    return packed


def chunk_document(doc_meta: dict[str, Any], pages: list[str]) -> list[Chunk]:
    enc = _encoder()
    chunks: list[Chunk] = []
    index = 0

    for page_number, page_text in enumerate(pages, start=1):
        if not page_text.strip():
            continue
        for heading, body in _pack(_split_page(page_text, enc), enc):
            chunks.append(
                Chunk(
                    doc_id=doc_meta["doc_id"],
                    chunk_index=index,
                    page=page_number,
                    section_path=heading,
                    content=body,
                    # Inherited explicitly, never recomputed downstream.
                    authority_tier=doc_meta["authority_tier"],
                    account_scope=doc_meta.get("account_scope"),
                )
            )
            index += 1

    if not chunks:
        raise IngestionError(f"{doc_meta['doc_id']}: produced zero chunks")

    for chunk in chunks:
        if chunk.authority_tier is None or chunk.doc_id is None or chunk.page is None:
            raise IngestionError(
                f"{doc_meta['doc_id']}: chunk {chunk.chunk_index} lost metadata on "
                f"split. This silently disables all authority filtering for the "
                f"document, so ingestion stops here."
            )

    return chunks
