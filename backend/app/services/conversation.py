"""Conversation persistence, sitting between the agent and the repository.

Exists so `agent/memory.py` does not import a repository directly. The agent
layer may call services; it may not reach the data layer.
"""

from __future__ import annotations

from typing import Any

from app.repositories import messages_repo


def recent_turns(session_id: str, limit: int) -> list[dict[str, Any]]:
    return messages_repo.recent(session_id, limit=limit)


def record(
    session_id: str,
    user_id: str,
    role: str,
    content: str,
    envelope: dict[str, Any] | None = None,
) -> None:
    messages_repo.insert(session_id, user_id, role, content, envelope)


def full_transcript(session_id: str) -> list[dict[str, Any]]:
    return messages_repo.all_for_session(session_id)
