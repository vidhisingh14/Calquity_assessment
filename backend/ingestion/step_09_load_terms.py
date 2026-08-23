"""Step 9: load declared policy terms, verifying each against its source chunk.

data/terms_overrides.yaml is the SOURCE OF TRUTH. This step does not extract
values -- it VERIFIES them. For each declared term it finds the chunk whose
text literally contains `source_quote`, binds that chunk's id, and FAILS THE
INGEST if the quote is not found.

The point is where the failure lands. A wrong quote breaks the build, loudly,
at ingest time. The alternative -- regex extraction as the primary path --
fails quietly at answer time, producing a confident number nobody can trace.
Regex lives in seed_terms.py and only PROPOSES rows for a human to curate.
"""

from __future__ import annotations

import pathlib
import re
from typing import Any

import yaml

from app.errors import IngestionError
from app.repositories import ingest_repo


def _normalise(text: str) -> str:
    """Whitespace-insensitive comparison.

    PDF extraction collapses and re-wraps whitespace unpredictably, so an exact
    string match would fail on quotes that are genuinely present. Everything
    else about the match stays literal.
    """
    return re.sub(r"\s+", " ", text).strip().lower()


def load_terms(
    terms_path: pathlib.Path,
    chunks_by_doc: dict[str, list[tuple[int, str]]],
    doc_meta: dict[str, dict[str, Any]],
) -> dict[str, int]:
    if not terms_path.exists():
        raise IngestionError(f"Terms file not found: {terms_path}")

    payload = yaml.safe_load(terms_path.read_text(encoding="utf-8")) or {}
    terms = payload.get("terms") or []
    if not terms:
        raise IngestionError(f"No terms declared in {terms_path}")

    normalised_chunks = {
        doc_id: [(cid, _normalise(text)) for cid, text in items]
        for doc_id, items in chunks_by_doc.items()
    }

    loaded = 0
    unverified = 0
    failures: list[str] = []

    for term in terms:
        doc_id = term["doc_id"]
        term_key = term["term_key"]
        quote = term.get("source_quote")

        if not quote:
            failures.append(f"{doc_id}/{term_key}: no source_quote declared")
            continue

        meta = doc_meta.get(doc_id)
        if meta is None:
            failures.append(f"{doc_id}/{term_key}: no such document")
            continue

        needle = _normalise(quote)
        match_id = next(
            (cid for cid, text in normalised_chunks.get(doc_id, []) if needle in text),
            None,
        )
        if match_id is None:
            failures.append(
                f"{doc_id}/{term_key}: source_quote not found verbatim in any chunk "
                f"-> {quote[:70]!r}"
            )
            continue

        is_deprecated = bool(term.get("deprecated")) or meta["authority_tier"] == 5
        row = {
            "doc_id": doc_id,
            "term_key": term_key,
            "term_value": term.get("value"),
            "unit": term.get("unit"),
            "source_chunk_id": match_id,
            "authority_tier": meta["authority_tier"],
            "account_scope": meta.get("account_scope"),
            "deprecated": is_deprecated,
            "enforceable": bool(term.get("enforceable", True)),
            "unverified": bool(term.get("unverified", True)),
        }
        ingest_repo.insert_term(row)
        loaded += 1
        if row["unverified"]:
            unverified += 1

    if failures:
        detail = "\n  ".join(failures)
        raise IngestionError(
            f"{len(failures)} declared term(s) could not be verified against their "
            f"source chunk. Fix the quote in terms_overrides.yaml, or fix the term.\n"
            f"  {detail}"
        )

    return {"loaded": loaded, "unverified": unverified, "verified": loaded - unverified}
