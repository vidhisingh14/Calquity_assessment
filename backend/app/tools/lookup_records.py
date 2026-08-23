"""Tool: read structured account, order and ticket data."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.auth.context import AuthContext
from app.repositories import accounts_repo, orders_repo, tickets_repo
from app.tools.base import ToolResult


class LookupRecordsArgs(BaseModel):
    entity: Literal["account", "order", "ticket"]
    record_id: str | None = Field(
        default=None, description="Exact id, e.g. 'ORD-1001' or 'TKT-501'."
    )
    filters: dict[str, Any] | None = Field(
        default=None,
        description="Whitelisted filters only. Orders: status, carrier. "
                    "Tickets: status, derived_severity, derived_issue_type.",
    )
    limit: int = Field(default=20, ge=1, le=100)


def _serialise(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in row.items():
        out[key] = value.isoformat() if hasattr(value, "isoformat") else value
    return out


class LookupRecordsTool:
    name = "lookup_records"
    description = (
        "Read ParcelPilot's structured operational data: accounts, orders and "
        "support tickets.\n\n"
        "USE THIS to fetch the facts a question depends on -- an order's status "
        "and timestamps, a ticket's details, an account's plan and whether it has "
        "a customer agreement. Look the record up BEFORE reasoning about it.\n\n"
        "DO NOT use this for written rules or policy text -- use "
        "search_documents. DO NOT use it to calculate a fee, credit or SLA "
        "outcome -- use evaluate_policy.\n\n"
        "Note: a ticket's historical_resolution field is PAST CONTEXT ONLY and is "
        "returned marked as such. Some past resolutions in this data are wrong. "
        "Never cite one as a rule.\n\n"
        "Example: entity='order', record_id='ORD-1001'."
    )
    args_model = LookupRecordsArgs
    requires_confirmation = False

    def run(self, args: LookupRecordsArgs, ctx: AuthContext) -> ToolResult:
        # The scope is appended by the tool, always, from the AuthContext. A
        # customer's scope is their own account id no matter what was asked for.
        scope = ctx.account_scope_filter()
        notes: list[str] = []

        try:
            if args.entity == "account":
                rows = self._accounts(args, scope)
            elif args.entity == "order":
                rows = self._orders(args, scope)
            else:
                rows = self._tickets(args, scope, notes)
        except ValueError as exc:
            # An unknown filter key returns the valid list so the model can
            # correct itself rather than reasoning on a bad result.
            return ToolResult(ok=False, error=str(exc))
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, error=f"lookup failed: {exc}")

        if not rows:
            # Deliberately identical whether the record is missing or belongs to
            # another account. A different message here would confirm existence.
            return ToolResult(
                ok=True,
                data={"entity": args.entity, "rows": [], "count": 0,
                      "truncated": False},
                notes=["No matching records are available to you."],
            )

        truncated = len(rows) >= args.limit
        if truncated:
            notes.append(
                f"Results truncated at {args.limit}; do not reason as if this "
                f"were the complete set."
            )

        return ToolResult(
            ok=True,
            data={
                "entity": args.entity,
                "rows": [_serialise(r) for r in rows],
                "count": len(rows),
                "truncated": truncated,
            },
            notes=notes,
        )

    def _accounts(self, args, scope):
        if args.record_id:
            row = accounts_repo.get_account(args.record_id, scope)
            return [row] if row else []
        if scope:
            row = accounts_repo.get_account(scope, scope)
            return [row] if row else []
        return accounts_repo.list_accounts_all()

    def _orders(self, args, scope):
        if args.record_id:
            row = orders_repo.get_order(args.record_id, scope)
            return [row] if row else []
        return orders_repo.list_orders(scope, args.filters, args.limit)

    def _tickets(self, args, scope, notes):
        if args.record_id:
            row = tickets_repo.get_ticket(args.record_id, scope)
            rows = [row] if row else []
        else:
            rows = tickets_repo.list_tickets(scope, args.filters, args.limit)

        marked = []
        for row in rows:
            row = dict(row)
            if row.get("historical_resolution"):
                row["historical_resolution"] = {
                    "text": row["historical_resolution"],
                    "authority": "context_only",
                    "warning": "Past resolution. May be incorrect. Never cite as a rule.",
                }
            if row.get("derived_severity"):
                row["derived_severity"] = {
                    "value": row["derived_severity"],
                    "authority": "derived_not_source_truth",
                    "rationale": row.get("severity_rationale"),
                }
            marked.append(row)

        if any(r.get("historical_resolution") for r in marked):
            notes.append(
                "A historical_resolution field is present. It is context only "
                "and may be incorrect; verify against current policy before "
                "repeating it."
            )
        return marked


TOOL = LookupRecordsTool()
