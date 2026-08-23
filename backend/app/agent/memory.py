"""Conversation state per session. No SQL here -- repositories own that."""

from __future__ import annotations

from typing import Any

from app.services import conversation

MAX_HISTORY_TURNS = 12


def load_history(session_id: str, user_id: str) -> list[dict[str, Any]]:
    rows = conversation.recent_turns(session_id, limit=MAX_HISTORY_TURNS)
    return [{"role": r["role"], "content": r["content"]} for r in rows]


def append_user(session_id: str, user_id: str, content: str) -> None:
    conversation.record(session_id, user_id, "user", content, None)


def append_assistant(
    session_id: str, user_id: str, content: str, envelope: dict[str, Any]
) -> None:
    conversation.record(session_id, user_id, "assistant", content, envelope)


def transcript(session_id: str) -> list[dict[str, Any]]:
    return conversation.full_transcript(session_id)
