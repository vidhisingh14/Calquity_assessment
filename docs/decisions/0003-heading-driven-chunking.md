# ADR-0003: Chunk on headings, not purely on token budget

**Status:** Accepted. **Date:** 2026-08-23

## Context

The build spec's default is ~800 tokens with 120 overlap. Every document in
the real pack is 600–1400 characters — well under 800 tokens — so a purely
size-based packer produced exactly one chunk per document, with
`section_path` NULL on all of them.

That was bad in three compounding ways: source cards degraded to
"Support Policy v3, page 1" with no section; `services/conflict.py` could only
ever say two whole *documents* disagree, never point at the clause; and
`search_documents` returned an entire document for a question about one
clause, diluting the context with irrelevant sections.

## Decision

A numbered heading (`"1. Scope and source precedence"`, `"5.2 Cancellation"`)
always starts a new chunk regardless of token count. `TARGET_TOKENS` still
applies *within* a section, for the case of one long section. A heading
detector (`ingestion/step_04_chunk.py::_looks_like_heading`) explicitly
rejects lines that look like flattened table rows or numbered list items, so
an SLA table row is never mistaken for a section start.

Result on the real pack: 6 documents → 22 chunks (was 6), each with a real
`section_path`, verified against the real embeddings — the Northstar
cancellation query now ranks `contract_northstar / "2. Shipment cancellation"`
first at similarity 0.77, well clear of the next result.

## Consequence

Every section in this corpus happens to be a self-contained rule, so
heading-driven splitting aligns with the seams the authors already put there.
A corpus with longer, less-structured sections would need the token-budget
path to do more work; that path (`_split_oversized`) is kept and tested for
exactly that case.
