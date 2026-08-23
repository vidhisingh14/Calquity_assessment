"""Step 1: locate the PDFs. Fails loudly on a missing or unexpected file."""

from __future__ import annotations

import pathlib

from app.errors import IngestionError

EXPECTED_PDF_COUNT = 6


def load_pdfs(raw_dir: pathlib.Path) -> list[pathlib.Path]:
    if not raw_dir.exists():
        raise IngestionError(f"Raw data directory not found: {raw_dir}")

    pdfs = sorted(raw_dir.glob("*.pdf"))
    if len(pdfs) != EXPECTED_PDF_COUNT:
        found = [p.name for p in pdfs]
        raise IngestionError(
            f"Expected {EXPECTED_PDF_COUNT} PDFs in {raw_dir}, found {len(pdfs)}: {found}"
        )
    return pdfs
