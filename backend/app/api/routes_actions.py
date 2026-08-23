"""Confirm / reject pending actions. The controller passes the token through."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.agent import confirmation
from app.api.deps import get_auth_context
from app.auth.context import AuthContext

router = APIRouter(tags=["actions"])


class RejectBody(BaseModel):
    reason: str | None = None


@router.post("/actions/{token}/confirm")
def confirm_action(token: str, ctx: AuthContext = Depends(get_auth_context)) -> dict:
    return confirmation.confirm(token, user_id=ctx.user_id)


@router.post("/actions/{token}/reject")
def reject_action(
    token: str,
    body: RejectBody | None = None,
    ctx: AuthContext = Depends(get_auth_context),
) -> dict:
    return confirmation.reject(
        token, user_id=ctx.user_id, reason=(body.reason if body else None)
    )
