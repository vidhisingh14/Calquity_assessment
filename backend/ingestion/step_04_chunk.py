"""Step 4: split into chunks that inherit their parent's metadata.

THE BUG THIS STEP EXISTS TO PREVENT is metadata loss on split. A chunk that
loses its authority_tier does not error -- it just quietly stops being
filterable, which disables the entire authority model for that document. So
every produced chunk is asserted to carry doc_id, authority_tier and page.

SPLITTING IS HEADING-DRIVEN, NOT PURELY SIZE-DRIVEN.

Every document in this pack is shorter than an 800-token budget, so a purely
size-based packer produced exactly one chunk per document, with section_path
NULL on all of them. That is bad in three specific ways:

  1. Citations degrade to "Support Policy v3, page 1" with no section, which is
     most of the value of a source card.
  2. Conflict detection compares whole documents instead of claims, so it can
     only ever say "these two documents disagree somewhere".
  3. Retrieval returns an entire document for a question about one clause,
     which crowds the context with irrelevant sections.

So a numbered heading always starts a new chunk, regardless of token count.
Each section in this corpus is a self-contained rule, so this splits along the
seams the authors already put there rather than at an arbitrary token offset.
TARGET_TOKENS still applies WITHIN a section, for the case of a long section.

Chunk size is measured with tiktoken purely as a DETERMINISTIC RULER. It is not
the tokenizer of the serving model (Cerebras GPT-OSS and Gemini both tokenize
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

# Sections shorter than this get folded into the previous chunk rather than
# standing alone -- a two-line fragment is not independently retrievable.
MIN_CHUNK_CHARS = 60

# Numbered section headings, e.g. "1. Scope and source precedence"
# or "5.2 Cancellation". The heading line itself stays in the chunk body so the
# text remains readable when shown in the source drawer.
_HEADING = re.compile(r"^\s*(\d+(?:\.\d+)*)\.?\s+(\S.{2,80})$")


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


def _looks_like_heading(line: str) -> tuple[str, str] | None:
    """A numbered heading, but not a numbered list item or a data row.

    Rejects lines ending in a sentence period and lines that are mostly
    numbers, so a flattened SLA table row ("Enterprise 30 minutes, 24x7 ...")
    is never mistaken for a section start.
    """
    match = _HEADING.match(line)
    if not match:
        return None
    title = match.group(2).strip()
    if title.endswith("."):
        return None
    digits = sum(c.isdigit() for c in title)
    if digits > len(title) / 3:
        return None
    return match.group(1), title


def _split_into_sections(text: str) -> list[tuple[str | None, str]]:
    """Split one page into (section_path, body) blocks on numbered headings.

    Text appearing before the first heading (title, status, effective date)
    becomes its own block with section_path None. It carries the document's
    identity and version, which is worth retrieving on its own.
    """
    blocks: list[tuple[str | None, str]] = []
    heading: str | None = None
    buffer: list[str] = []

    for line in text.splitlines():
        parsed = _looks_like_heading(line)
        if parsed:
            if buffer:
                blocks.append((heading, "\n".join(buffer).strip()))
            number, title = parsed
            heading = f"{number}. {title}"
            buffer = [line]
        else:
            buffer.append(line)

    if buffer:
        blocks.append((heading, "\n".join(buffer).strip()))

    return [(h, b) for h, b in blocks if b.strip()]


def _split_oversized(heading: str | None, body: str, enc) -> list[tuple[str | None, str]]:
    """Only used when a single section exceeds the token budget."""
    if _token_len(body, enc) <= TARGET_TOKENS:
        return [(heading, body)]

    paragraphs = [p for p in body.split("\n\n") if p.strip()]
    out: list[tuple[str | None, str]] = []
    current: list[str] = []

    for paragraph in paragraphs:
        candidate = "\n\n".join(current + [paragraph])
        if current and _token_len(candidate, enc) > TARGET_TOKENS:
            out.append((heading, "\n\n".join(current)))
            tail = current[-1]
            overlap = [tail] if _token_len(tail, enc) <= OVERLAP_TOKENS else []
            current = overlap + [paragraph]
        else:
            current.append(paragraph)

    if current:
        out.append((heading, "\n\n".join(current)))
    return out


def _merge_tiny(blocks: list[tuple[str | None, str]]) -> list[tuple[str | None, str]]:
    merged: list[tuple[str | None, str]] = []
    for heading, body in blocks:
        if merged and len(body) < MIN_CHUNK_CHARS:
            prev_heading, prev_body = merged[-1]
            merged[-1] = (prev_heading, f"{prev_body}\n\n{body}")
        else:
            merged.append((heading, body))
    return merged


def chunk_document(doc_meta: dict[str, Any], pages: list[str]) -> list[Chunk]:
    enc = _encoder()
    chunks: list[Chunk] = []
    index = 0

    for page_number, page_text in enumerate(pages, start=1):
        if not page_text.strip():
            continue

        sections = _split_into_sections(page_text)
        expanded: list[tuple[str | None, str]] = []
        for heading, body in sections:
            expanded.extend(_split_oversized(heading, body, enc))

        for heading, body in _merge_tiny(expanded):
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
