"""Tool: all arithmetic and all rule evaluation.

The model supplies identifiers; CODE produces the verdict. This is the one
place where the numbers must be exactly right, so the model is never asked to
compute one.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.auth.context import AuthContext
from app.errors import PolicyUndecidable
from app.repositories import accounts_repo, orders_repo, system_repo, tickets_repo
from app.services import policy_engine, terms as terms_service
from app.tools.base import ToolResult


class EvaluatePolicyArgs(BaseModel):
    rule: Literal["cancellation_fee", "service_credit", "sla_status"]
    order_id: str | None = None
    ticket_id: str | None = None
    stated_facts: dict[str, Any] | None = Field(
        default=None,
        description="Facts the caller asserted rather than the system holding, "
                    "e.g. {'delay_hours': 3, 'carrier_fault': true, "
                    "'customer_fault': false, 'shipment_fee_inr': 4200}.",
    )


class EvaluatePolicyTool:
    name = "evaluate_policy"
    description = (
        "Compute a policy verdict in code: cancellation fees, failed-pickup "
        "service credits, and SLA first-response status.\n\n"
        "USE THIS for EVERY number and EVERY rule outcome. It resolves which "
        "source governs (a customer agreement overrides general policy), does the "
        "arithmetic against the dataset's reference time, and returns the working "
        "so the reasoning is auditable. Never calculate a fee, credit, deadline or "
        "elapsed time yourself -- call this instead.\n\n"
        "DO NOT use this to retrieve policy text (use search_documents) or to read "
        "a record (use lookup_records), though it will fetch what it needs itself.\n\n"
        "If facts are missing or ambiguous it returns outcome='undecidable' with a "
        "reason. Treat that as the honest answer and offer escalation; do not fill "
        "the gap with an assumption.\n\n"
        "Example: rule='cancellation_fee', order_id='ORD-1001'."
    )
    args_model = EvaluatePolicyArgs
    requires_confirmation = False

    def run(self, args: EvaluatePolicyArgs, ctx: AuthContext) -> ToolResult:
        scope = ctx.account_scope_filter()

        try:
            snapshot = system_repo.get_snapshot_time()
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, error=f"snapshot time unavailable: {exc}")

        try:
            if args.rule == "sla_status":
                return self._sla(args, ctx, scope, snapshot)
            if args.rule == "cancellation_fee":
                return self._cancellation(args, ctx, scope, snapshot)
            return self._credit(args, ctx, scope, snapshot)
        except PolicyUndecidable as exc:
            # Not an error to the user: the system knowing it does not know.
            return ToolResult(
                ok=True,
                data={
                    "rule": args.rule,
                    "outcome": "undecidable",
                    "reason_code": "facts_missing",
                    "working": [exc.reason],
                    "confidence": "low",
                },
                notes=[f"Undecidable: {exc.reason}. Offer escalation."],
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, error=f"evaluation failed: {exc}")

    # -- helpers ------------------------------------------------------------

    def _account_for(self, account_id: str | None, scope: str | None):
        target = scope or account_id
        if target is None:
            return None
        return accounts_repo.get_account(target, scope)

    def _result(self, verdict) -> ToolResult:
        payload = verdict.to_dict()
        notes: list[str] = []
        if verdict.override_applied and verdict.governing_source:
            notes.append(
                f"{verdict.governing_source} overrode the general rule. The answer "
                f"must say so explicitly."
            )
        if verdict.caveats:
            notes.append(
                f"Caveat {', '.join(verdict.caveats)} could INVERT this verdict. "
                f"State it and say what changes if it holds."
            )
        if verdict.outcome == "undecidable":
            notes.append("Undecidable. Offer escalation rather than guessing.")
        return ToolResult(
            ok=True, data=payload,
            sources=[{"doc_id": d} for d in dict.fromkeys(verdict.sources)],
            notes=notes,
        )

    def _cancellation(self, args, ctx, scope, snapshot) -> ToolResult:
        if not args.order_id:
            return ToolResult(ok=False, error="cancellation_fee requires order_id")

        order = orders_repo.get_order(args.order_id, scope)
        if order is None:
            return ToolResult(
                ok=True,
                data={"rule": "cancellation_fee", "outcome": "undecidable",
                      "reason_code": "facts_missing"},
                notes=["No such order is available to you."],
            )

        account = self._account_for(order["account_id"], scope)
        term_set = terms_service.load(account, scope or order["account_id"])
        verdict = policy_engine.evaluate_cancellation(order, term_set, snapshot)
        return self._result(verdict)

    def _credit(self, args, ctx, scope, snapshot) -> ToolResult:
        order = None
        if args.order_id:
            order = orders_repo.get_order(args.order_id, scope)
            if order is None:
                return ToolResult(
                    ok=True,
                    data={"rule": "service_credit", "outcome": "undecidable",
                          "reason_code": "facts_missing"},
                    notes=["No such order is available to you."],
                )

        account_id = (order or {}).get("account_id") or scope
        account = self._account_for(account_id, scope)
        term_set = terms_service.load(account, scope or account_id)
        verdict = policy_engine.evaluate_service_credit(
            term_set, snapshot, order=order, stated_facts=args.stated_facts
        )
        return self._result(verdict)

    def _sla(self, args, ctx, scope, snapshot) -> ToolResult:
        if not args.ticket_id:
            return ToolResult(ok=False, error="sla_status requires ticket_id")

        ticket = tickets_repo.get_ticket(args.ticket_id, scope)
        if ticket is None:
            return ToolResult(
                ok=True,
                data={"rule": "sla_status", "outcome": "undecidable",
                      "reason_code": "facts_missing"},
                notes=["No such ticket is available to you."],
            )

        account = self._account_for(ticket["account_id"], scope)
        term_set = terms_service.load(account, scope or ticket["account_id"])
        verdict = policy_engine.evaluate_sla(ticket, term_set, snapshot)

        result = self._result(verdict)
        if verdict.detail.get("severity_derived"):
            result.notes.append(
                "Severity was DERIVED from the ticket text, not read from a "
                "field. State the derivation inline and offer escalation if the "
                "caller disputes it."
            )
        return result


TOOL = EvaluatePolicyTool()
