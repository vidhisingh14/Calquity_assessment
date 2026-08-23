"""Tool: the state-changing action. Two phase, confirmation required.

PHASE 1 (prepare) validates, builds the full escalation object, stores it in
`pending_actions` with a random token and a TTL, and returns the draft.
NOTHING is written to `escalations`.

PHASE 2 (execute) happens only through POST /actions/{token}/confirm, which
verifies the token exists, is still pending, has not expired, and belongs to
the same session and user. The escalation's idempotency key is derived from the
token, so a duplicate confirm cannot create a second row.

The tool itself can only ever run phase 1. There is no argument that makes it
write, which is why "escalation created without asking" is not reachable from
here.
"""

from __future__ import annotations

import secrets
from typing import Literal

from pydantic import BaseModel, Field

from app.auth import policies
from app.auth.context import AuthContext
from app.config import get_settings
from app.errors import PermissionDenied
from app.repositories import actions_repo
from app.tools.base import ToolResult


class CreateEscalationArgs(BaseModel):
    summary: str = Field(description="One line describing what needs a human.")
    reason: str = Field(
        description="Why this needs escalation. Use one of the machine-readable "
                    "reasons where it fits, e.g. 'verdict_undecidable'."
    )
    severity: Literal["low", "medium", "high", "urgent"]
    order_id: str | None = None
    ticket_id: str | None = None
    linked_sources: list[str] = Field(default_factory=list)


class CreateEscalationTool:
    name = "create_escalation"
    description = (
        "Prepare an escalation to a human support specialist.\n\n"
        "USE THIS when a verdict came back undecidable, when two sources of equal "
        "authority conflict, when the caller asks for an exception to a written "
        "rule (a goodwill waiver, for example), when the request needs an action "
        "this system cannot perform, or when the caller asks for a human.\n\n"
        "DO NOT use this to answer a question that the documents and the policy "
        "engine can already answer -- escalating a decidable question wastes a "
        "specialist's time.\n\n"
        "IMPORTANT: this only DRAFTS the escalation. Nothing is created until the "
        "user explicitly confirms it in the interface. Present the draft and tell "
        "the caller it is awaiting their confirmation. Never say an escalation has "
        "been created.\n\n"
        "Example: summary='Cannot confirm carrier fault for late pickup', "
        "reason='verdict_undecidable', severity='medium'."
    )
    args_model = CreateEscalationArgs
    requires_confirmation = True

    def run(
        self,
        args: CreateEscalationArgs,
        ctx: AuthContext,
        session_id: str = "default",
    ) -> ToolResult:
        if not policies.can_escalate(ctx):
            raise PermissionDenied("This role may not raise escalations.")

        settings = get_settings()

        # The account is resolved from the AuthContext, never from arguments.
        account_id = ctx.account_id
        if account_id is None:
            # Internal staff escalate against the record's account.
            account_id = self._account_from_records(args, ctx)
        if account_id is None:
            return ToolResult(
                ok=False,
                error="Could not determine which account this escalation belongs "
                      "to. Supply an order_id or ticket_id.",
            )

        payload = {
            "account_id": account_id,
            "created_by": ctx.user_id,
            "severity": args.severity,
            "summary": args.summary,
            "reason": args.reason,
            "order_id": args.order_id,
            "ticket_id": args.ticket_id,
            "linked_sources": args.linked_sources,
        }

        token = secrets.token_urlsafe(24)
        actions_repo.create_pending(
            token=token,
            session_id=session_id,
            user_id=ctx.user_id,
            action_type="create_escalation",
            payload=payload,
            ttl_minutes=settings.pending_action_ttl_minutes,
        )

        return ToolResult(
            ok=True,
            data={
                "status": "awaiting_confirmation",
                "token": token,
                "action_type": "create_escalation",
                "preview": payload,
                "expires_in_minutes": settings.pending_action_ttl_minutes,
            },
            notes=[
                "DRAFT ONLY. No escalation exists yet. Tell the caller it is "
                "awaiting their confirmation, and do not claim it was created.",
            ],
        )

    def _account_from_records(self, args, ctx):
        from app.repositories import orders_repo, tickets_repo

        if args.order_id:
            row = orders_repo.get_order(args.order_id, None)
            if row:
                return row["account_id"]
        if args.ticket_id:
            row = tickets_repo.get_ticket(args.ticket_id, None)
            if row:
                return row["account_id"]
        return None


TOOL = CreateEscalationTool()
