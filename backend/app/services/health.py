"""Health composition.

Exists because the controller may not reach the data layer directly (build spec
section 4.1: a controller may call one agent or service entry point). This
service does the composing; it contains no SQL of its own.
"""

from __future__ import annotations

from typing import Any

from app.repositories import system_repo, terms_repo


def health_report() -> dict[str, Any]:
    counts = system_repo.row_counts()
    extras = system_repo.health_extras()

    try:
        terms_split = terms_repo.count_unverified()
    except Exception:  # noqa: BLE001 - table may not exist before migrations
        terms_split = {"verified": 0, "unverified": 0}

    ingested = counts.get("documents", 0) > 0 and counts.get("doc_chunks", 0) > 0

    return {
        "status": "ok",
        "ingested": ingested,
        "snapshot_time": extras["snapshot_time"],
        "skipped_empty_pages": extras["skipped_empty_pages"],
        "row_counts": counts,
        # Surfaced so it is obvious at a glance how much of the policy term set
        # a human has signed off, rather than trusting drafted values.
        "terms": terms_split,
    }
