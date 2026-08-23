"""Yes/no permission questions. No business rules, no SQL.

Every function here answers one question about what a role may do. Tools call
these; they never re-implement the logic inline.
"""

from __future__ import annotations

from app.auth.context import AuthContext
from app.config import get_settings


def can_read_account(ctx: AuthContext, account_id: str) -> bool:
    """Internal staff read any account. A customer reads exactly their own."""
    if ctx.is_internal:
        return True
    return ctx.account_id is not None and ctx.account_id == account_id


def can_read_all_accounts(ctx: AuthContext) -> bool:
    """Gates the explicitly-named cross-account repository functions."""
    return ctx.is_internal


def can_see_deprecated_docs(ctx: AuthContext) -> bool:
    """Tier-5 documents are visible to internal roles on explicit request only.

    Customers never see them. This is what makes g12 (an ops_lead legitimately
    comparing policy versions) pass while g11 (a customer asking the same) does
    not.
    """
    if not ctx.is_internal:
        return False
    return get_settings().enable_deprecated_docs_for_internal


def can_escalate(ctx: AuthContext) -> bool:
    """Anyone may request an escalation; the confirmation gate is what
    actually protects the write."""
    return True


def visible_doc_tiers(ctx: AuthContext, include_deprecated: bool = False) -> list[int]:
    """The authority tiers this caller may retrieve from."""
    if include_deprecated and can_see_deprecated_docs(ctx):
        return [1, 2, 3, 4, 5]
    return [1, 2, 3, 4]
