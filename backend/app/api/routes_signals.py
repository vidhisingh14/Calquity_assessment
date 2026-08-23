"""Read API for the internal signals board. Internal roles only."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_auth_context
from app.auth import policies
from app.auth.context import AuthContext
from app.errors import PermissionDenied
from app.services import signals as signals_service

router = APIRouter(tags=["signals"])


@router.get("/signals")
def get_signals(
    severity: str | None = None,
    status: str | None = None,
    ctx: AuthContext = Depends(get_auth_context),
) -> dict:
    if not policies.can_read_all_accounts(ctx):
        raise PermissionDenied("Signals are visible to internal roles only.")
    return {"signals": signals_service.list_signals(severity, status)}
