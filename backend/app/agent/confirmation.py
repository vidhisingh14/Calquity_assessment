"""Two-phase action tokens.

A token is only honoured when it exists, is still pending, has not expired, and
belongs to the SAME session and user that created it. The escalation's
idempotency key is derived from the token, so a duplicate confirm cannot create
a second row -- enforced by a UNIQUE constraint, not by application logic.
"""

from __future__ import annotations

import hashlib
from typing import Any

from app.errors import DataNotFound, PermissionDenied
from app.services import actions


def _idempotency_key(token: str) -> str:
    return hashlib.sha256(f"escalation:{token}".encode()).hexdigest()[:40]


def _escalation_id(token: str) -> str:
    return "ESC-" + hashlib.sha256(token.encode()).hexdigest()[:10].upper()


def _load_and_check(token: str, user_id: str, session_id: str | None) -> dict[str, Any]:
    row = actions.get_pending(token)
    if row is None:
        raise DataNotFound("No such pending action.")

    if row["user_id"] != user_id:
        # Same response as a missing token: confirming that someone else's
        # token exists is itself a leak.
        raise DataNotFound("No such pending action.")

    if session_id is not None and row["session_id"] != session_id:
        raise PermissionDenied("This action belongs to a different session.")

    return row


def confirm(token: str, user_id: str, session_id: str | None = None) -> dict[str, Any]:
    row = _load_and_check(token, user_id, session_id)

    key = _idempotency_key(token)

    if row["status"] == "confirmed":
        # Idempotent replay: return the row that already exists rather than
        # creating a second one or erroring.
        existing = actions.create_escalation(
            escalation_id=_escalation_id(token),
            account_id=row["payload"]["account_id"],
            created_by=row["payload"]["created_by"],
            severity=row["payload"]["severity"],
            summary=row["payload"]["summary"],
            reason=row["payload"]["reason"],
            idempotency_key=key,
            order_id=row["payload"].get("order_id"),
            ticket_id=row["payload"].get("ticket_id"),
            linked_sources=row["payload"].get("linked_sources"),
        )
        return {"escalation_id": existing["escalation_id"], "status": "already_confirmed"}

    if row["status"] == "rejected":
        raise PermissionDenied("This action was rejected and cannot be confirmed.")

    if row["is_expired"]:
        actions.mark_pending(token, "expired")
        raise PermissionDenied(
            "This confirmation has expired. Ask again and confirm the new draft."
        )

    payload = row["payload"]
    escalation = actions.create_escalation(
        escalation_id=_escalation_id(token),
        account_id=payload["account_id"],
        created_by=payload["created_by"],
        severity=payload["severity"],
        summary=payload["summary"],
        reason=payload["reason"],
        idempotency_key=key,
        order_id=payload.get("order_id"),
        ticket_id=payload.get("ticket_id"),
        linked_sources=payload.get("linked_sources"),
    )
    actions.mark_pending(token, "confirmed")

    return {"escalation_id": escalation["escalation_id"], "status": "confirmed"}


def reject(
    token: str, user_id: str, session_id: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    row = _load_and_check(token, user_id, session_id)
    if row["status"] == "confirmed":
        raise PermissionDenied("This action was already confirmed.")
    actions.mark_pending(token, "rejected")
    return {"status": "rejected", "reason": reason}
