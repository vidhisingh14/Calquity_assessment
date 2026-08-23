"""Thin pass-through so the controller never imports repositories directly."""

from __future__ import annotations

from typing import Any

from app.repositories import signals_repo


def list_signals(severity: str | None, status: str | None) -> list[dict[str, Any]]:
    return signals_repo.list_signals(severity, status)
