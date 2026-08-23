"""Hybrid retrieval, fusion, and authority ranking.

The authority rule from the build spec's section 6.1 -- "a tier-1 chunk with a
matching account_scope beats any tier-2 or tier-3 chunk on the same subject" --
is implemented as a GUARANTEE, not a heuristic. A score multiplier would only
make the override *likely*; a stable sort on (bucket, score) makes it certain.

Three parts, in order:

1. RESERVED SLOTS. A dedicated pass fetches the caller's own tier-1 contract
   chunks. Bucket promotion is worthless if the contract never reaches the
   candidate pool, and on raw similarity a generic policy chunk can crowd it
   out.
2. RELEVANCE FLOOR. Promotion applies only to chunks that clear a fused-score
   floor, so an irrelevant contract clause does not top the context merely for
   being tier 1.
3. STABLE BUCKET SORT. Scoped tier-1 is bucket 0, everything else bucket 1.
   Within a bucket, fused score decides.

Every promotion is recorded so the trace can show the override happening.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Reciprocal rank fusion constant, per the build spec: score = sum(1/(60+rank)).
RRF_K = 60

# A chunk must reach this fraction of the best fused score before authority
# promotion applies to it.
PROMOTION_FLOOR_RATIO = 0.35

# How many candidate slots are reserved for the caller's own contract.
RESERVED_TIER1_SLOTS = 3


@dataclass
class RankedChunk:
    chunk_id: int
    doc_id: str
    page: int | None
    section_path: str | None
    content: str
    authority_tier: int
    account_scope: str | None
    doc_type: str
    fused_score: float
    promoted: bool = False
    retrievers: list[str] = field(default_factory=list)

    def to_source(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "tier": self.authority_tier,
            "page": self.page,
            "section": self.section_path,
            "score": round(self.fused_score, 4),
        }


def fuse(
    ranked_lists: dict[str, list[dict[str, Any]]],
) -> dict[int, tuple[float, dict[str, Any], list[str]]]:
    """Reciprocal rank fusion across named retrievers.

    RRF is used rather than score normalisation because cosine similarity and
    ts_rank are not on comparable scales, and normalising them requires
    assumptions about their distributions that do not hold on a corpus this
    small.
    """
    fused: dict[int, tuple[float, dict[str, Any], list[str]]] = {}
    for retriever, rows in ranked_lists.items():
        for rank, row in enumerate(rows, start=1):
            chunk_id = row["chunk_id"]
            contribution = 1.0 / (RRF_K + rank)
            if chunk_id in fused:
                score, existing, sources = fused[chunk_id]
                fused[chunk_id] = (score + contribution, existing, sources + [retriever])
            else:
                fused[chunk_id] = (contribution, row, [retriever])
    return fused


def apply_authority(
    fused: dict[int, tuple[float, dict[str, Any], list[str]]],
    account_scope: str | None,
    k: int,
) -> tuple[list[RankedChunk], list[dict[str, Any]]]:
    """Rank by (authority bucket, fused score) and report promotions.

    Returns (ranked_chunks, promotions). `promotions` is written into the trace
    so an override is observable rather than merely claimed in prose.
    """
    if not fused:
        return [], []

    best = max(score for score, _, _ in fused.values())
    floor = best * PROMOTION_FLOOR_RATIO

    chunks: list[RankedChunk] = []
    promotions: list[dict[str, Any]] = []

    for chunk_id, (score, row, retrievers) in fused.items():
        tier = row["authority_tier"]
        scope = row["account_scope"]

        # Bucket 0 is reserved for a contract that belongs to THIS caller and
        # is actually relevant. Everything else shares bucket 1.
        is_scoped_contract = tier == 1 and scope is not None and scope == account_scope
        clears_floor = score >= floor
        promoted = is_scoped_contract and clears_floor

        chunks.append(
            RankedChunk(
                chunk_id=chunk_id,
                doc_id=row["doc_id"],
                page=row.get("page"),
                section_path=row.get("section_path"),
                content=row["content"],
                authority_tier=tier,
                account_scope=scope,
                doc_type=row.get("doc_type", ""),
                fused_score=score,
                promoted=promoted,
                retrievers=retrievers,
            )
        )

        if is_scoped_contract and not clears_floor:
            promotions.append({
                "doc_id": row["doc_id"],
                "chunk_id": chunk_id,
                "promoted": False,
                "reason": "tier-1 chunk did not clear the relevance floor",
                "score": round(score, 4),
                "floor": round(floor, 4),
            })
        elif promoted:
            promotions.append({
                "doc_id": row["doc_id"],
                "chunk_id": chunk_id,
                "promoted": True,
                "reason": "account-scoped contract outranks general policy",
                "score": round(score, 4),
                "floor": round(floor, 4),
            })

    # Stable sort: bucket first, then score. This is the guarantee.
    chunks.sort(key=lambda c: (0 if c.promoted else 1, -c.fused_score))
    return chunks[:k], promotions


def search(
    query: str,
    embedder,
    docs_repo,
    tiers: list[int],
    account_scope: str | None,
    k: int,
) -> tuple[list[RankedChunk], list[dict[str, Any]], list[dict[str, Any]]]:
    """Full retrieval: hybrid fetch, reserved slots, fusion, authority ranking.

    Returns (ranked, promotions, excluded).
    """
    query_vector = embedder.embed([query], task_type="RETRIEVAL_QUERY")[0]

    vector_rows = docs_repo.vector_search(query_vector, tiers, account_scope, k * 2)
    keyword_rows = docs_repo.keyword_search(query, tiers, account_scope, k * 2)
    reserved = docs_repo.search_scoped_tier1(
        query_vector, account_scope, RESERVED_TIER1_SLOTS
    )

    fused = fuse({
        "vector": vector_rows,
        "keyword": keyword_rows,
        "contract": reserved,
    })
    ranked, promotions = apply_authority(fused, account_scope, k)

    # What was deliberately ignored is part of the trust story, so it is
    # reported rather than silently dropped.
    excluded: list[dict[str, Any]] = []
    if 5 not in tiers:
        excluded.append({
            "doc_id": "policy_v2",
            "reason": "deprecated, superseded by policy_v3",
        })

    return ranked, promotions, excluded
