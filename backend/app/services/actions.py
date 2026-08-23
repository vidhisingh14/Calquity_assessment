"""Pending-action persistence, sitting between the agent and the repository.

Exists so `agent/confirmation.py` does not import a repository directly.
"""

from __future__ import annotations

from typing import Any

from app.repositories import actions_repo


def get_pending(token: str) -> dict[str, Any] | None:
    return actions_repo.get_pending(token)


def mark_pending(token: str, status: str) -> None:
    actions_repo.mark_pending(token, status)


def create_escalation(**kwargs: Any) -> dict[str, Any]:
    return actions_repo.create_escalation(**kwargs)


def create_pending(**kwargs: Any) -> dict[str, Any]:
    return actions_repo.create_pending(**kwargs)
