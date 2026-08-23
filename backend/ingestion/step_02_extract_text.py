"""Step 2: per-page text extraction, page numbers preserved.

Asserts every page yielded text. A scanned PDF returns a healthy page count and
empty text, which then silently poisons every answer sourced from it -- the
document looks ingested, the retrieval just never finds anything in it.

`allow_empty_pages` exists so one genuinely blank page cannot hard-block an
ingest, but it is OFF by default, it records exactly which pages it skipped,
and the deployed ingest path never sets it. A skipped page that nobody can see
is the same failure the assertion was written to prevent.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass, field

import pdfplumber

from app.errors import IngestionError


@dataclass
class ExtractedDoc:
    file_name: str
    pages: list[str]
    skipped_pages: list[int] = field(default_factory=list)

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def text(self) -> str:
        return "\n".join(self.pages)


def extract_text(path: pathlib.Path, allow_empty_pages: bool = False) -> ExtractedDoc:
    pages: list[str] = []
    empty: list[int] = []

    with pdfplumber.open(path) as pdf:
        for index, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            if not text.strip():
                empty.append(index)
            pages.append(text)

    if empty and not allow_empty_pages:
        raise IngestionError(
            f"{path.name}: no text extracted from page(s) {empty}. "
            f"This is what a scanned PDF looks like, and it would silently "
            f"produce a document that retrieval can never find anything in. "
            f"Add OCR, or re-run with --allow-empty-pages if the page really is "
            f"blank (the skip is then recorded and surfaced on /healthz)."
        )

    return ExtractedDoc(file_name=path.name, pages=pages, skipped_pages=empty)
