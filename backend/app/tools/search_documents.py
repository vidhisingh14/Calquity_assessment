"""Tool: search policies, SOPs, product docs, and the caller's own contract."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.auth import policies
from app.auth.context import AuthContext
from app.config import get_settings
from app.llm.embeddings import get_embedder
from app.repositories import docs_repo
from app.services import conflict, retrieval
from app.tools.base import ToolResult


class SearchDocumentsArgs(BaseModel):
    query: str = Field(description="Natural-language description of what to find.")
    doc_types: list[Literal["policy", "sop", "product_guide", "contract"]] | None = Field(
        default=None, description="Optional filter by document type."
    )
    include_deprecated: bool = Field(
        default=False,
        description="Internal roles only. Include superseded documents, for "
                    "version-comparison questions.",
    )
    k: int = Field(default=8, ge=1, le=20)


class SearchDocumentsTool:
    name = "search_documents"
    description = (
        "Search ParcelPilot's written sources: the current support policy, the "
        "cancellation and service-credit SOP, the product operations guide and "
        "known issues, and the caller's own customer agreement.\n\n"
        "USE THIS whenever the answer depends on a written rule, before stating "
        "any policy, entitlement, threshold or procedure. Always retrieve a rule "
        "before asserting it.\n\n"
        "DO NOT use this to look up an order, account or ticket record -- use "
        "lookup_records. DO NOT use it to compute a fee, credit or SLA outcome -- "
        "use evaluate_policy, which does the arithmetic in code.\n\n"
        "Example: query='cancellation fee window for a booked shipment'."
    )
    args_model = SearchDocumentsArgs
    requires_confirmation = False

    def run(self, args: SearchDocumentsArgs, ctx: AuthContext) -> ToolResult:
        settings = get_settings()

        # Scope comes from the AuthContext, never from arguments. There is no
        # account_id parameter on this tool at all, so the model cannot supply
        # one to be overridden.
        scope = ctx.account_scope_filter()
        tiers = policies.visible_doc_tiers(
            ctx, include_deprecated=args.include_deprecated
        )

        notes: list[str] = []
        if args.include_deprecated and not policies.can_see_deprecated_docs(ctx):
            notes.append(
                "Deprecated documents were requested but are not available to "
                "this role; results cover current sources only."
            )

        try:
            ranked, promotions, excluded = retrieval.search(
                query=args.query,
                embedder=get_embedder(),
                docs_repo=docs_repo,
                tiers=tiers,
                account_scope=scope,
                k=min(args.k, settings.retrieval_k * 2),
            )
        except Exception as exc:  # noqa: BLE001 - tools return, never raise
            return ToolResult(ok=False, error=f"retrieval failed: {exc}")

        if args.doc_types:
            wanted = set(args.doc_types)
            ranked = [c for c in ranked if c.doc_type in wanted]

        conflicts = conflict.detect(ranked)

        chunks = [{
            "doc_id": c.doc_id,
            "tier": c.authority_tier,
            "page": c.page,
            "section": c.section_path,
            "text": c.content,
            "score": round(c.fused_score, 4),
            "contract_override": c.promoted,
        } for c in ranked]

        for promo in promotions:
            if promo.get("promoted"):
                notes.append(
                    f"{promo['doc_id']} was promoted above general policy because "
                    f"it is this account's own agreement."
                )

        return ToolResult(
            ok=True,
            data={
                "chunks": chunks,
                "conflicts": [c.to_dict() for c in conflicts],
                "excluded": excluded,
            },
            sources=[c.to_source() for c in ranked],
            notes=notes,
        )


TOOL = SearchDocumentsTool()
